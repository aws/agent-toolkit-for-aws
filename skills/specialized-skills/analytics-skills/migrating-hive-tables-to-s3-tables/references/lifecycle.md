# Migration lifecycle

Full state machine plus the per-phase request shapes and calls, in order: Start + plan →
Plan review → Approve + migrate → Sync (optional) → Complete. Pre-flight and IAM setup are in
`references/preflight.md` and `references/iam-roles.md`; failure codes are in
`references/troubleshooting.md`; post-migration checks are in `references/validation.md`.

## State machine

```
new → planning → pendingReview → queued → migrating → succeeded ──(complete)──▶ table managedByService cleared
                                              │
                                    failed / cancelling → cancelled
```

`MigrationState` is exactly: `new`, `planning`, `pendingReview`,
`queued`, `migrating`, `succeeded`, `failed`, `cancelling`, `cancelled`. There is **no `active`
state**, Complete does not transition the migration; it promotes the table, returns an empty body,
and clears the table's `managedByService` flag (see Complete below).

| State | Meaning | Allowed next action |
|-------|---------|---------------------|
| `new` | Migration record created, planning not yet started | Poll `get-table-migration` |
| `planning` | Async plan generation in progress | Poll `get-table-migration` |
| `pendingReview` | Plan ready (`hasValidPlan: true`); paused for review | `update-table-migration --requested-state queued` (approve) or cancel |
| `queued` | Approved, waiting to be picked up | Poll; no action needed |
| `migrating` | Copying + converting + compacting | Poll `migrationStats` |
| `succeeded` | Copy finished (`objectsFailedMigration` 0; confirm data via row-count parity) | `complete-table-migration --table-arn ...` |
| `failed` | Plan or copy failed | Read `failureReason`; fix; then recover (see Recovery below) |
| `cancelling` | Cancellation in progress | Poll until `cancelled` |
| `cancelled` | Cancelled | Destination table is kept. Resume with Sync if `hasValidPlan` is true, or delete the table and Start again (see Recovery below) |

### Recovery after a cancel or fail

A failed or cancelled migration keeps the destination table and any data already committed. The
table name stays taken, so a plain re-Start returns a `ConflictException` (409)
until you delete the table. Check `hasValidPlan` (`get-table-migration` or
`list-table-migrations --table-arn <ARN>`), then:

- **Failed in planning, no table created:** `get-table` returns `NotFoundException`. Fix the
  cause and start a new migration.
- **`hasValidPlan` is true and the cause is fixed outside the migration settings** (for example a
  permission you have since granted, or a cancel at review): resume with `sync-table-migration`.
  Sync plans only what is not yet migrated.
- **The fix changes migration settings** (`migrationPolicies`, sort order, destination schema, or
  the source table): delete the destination table and Start again. Sync reuses the original
  source and settings, so it cannot carry these changes.
- **`hasValidPlan` is false:** delete the destination table and Start again.
- To abandon a migration, delete the destination table.

Deleting a table and starting again are changes; confirm with the user first.

### Notes

- Planning is asynchronous; compatibility failures appear as `failed` with a `failureReason`, or as invalid findings in the compatibility reports, not as an immediate CLI error.
- `complete-table-migration` should be called only on a `succeeded` migration (completing a `failed`/`cancelled` run would publish a partial table) and takes `--table-arn`, not `--migration-id`.

## Start + plan

Use `--cli-input-json` with a JSON body.

### Request body (start-migration.json)

```json
{
  "roleARN": "arn:aws:iam::<ACCT>:role/<MIGRATION_ROLE>",
  "sourceType": "glueTable",
  "source": {
    "glueTable": {
      "catalogId": "<ACCT>",
      "databaseName": "<DB>",
      "tableName": "<TBL>"
    }
  },
  "destinationTable": {
    "tableBucketARN": "arn:aws:s3tables:<REGION>:<ACCT>:bucket/<DEST_BUCKET>",
    "namespace": "<NS>",
    "name": "<DEST_TABLE_NAME>"
  },
  "reviewMigrationPlan": true,
  "migrationOutput": {
    "bucket": "arn:aws:s3:::<REPORT_BUCKET>",
    "prefixes": {
      "tableCompatibilityReport": "migration-api-reports",
      "objectCompatibilityReport": "migration-api-reports",
      "objectMigrationReport": "migration-api-reports"
    }
  }
}
```

- **`sourceType` is a top-level member** (`glueTable`), and `source` holds only `glueTable`. The role member is `roleARN`.
- **`catalogId` is REQUIRED** in the source; omitting it fails plan generation.
- **Sort order (optional):** set it as `destinationTable.icebergSortOrder`. Each field refers to a destination column by field ID (`sourceId`). Start rejects a field that names no column or whose transform does not fit the column type. Rows are sorted within each data file the migration writes.
- **`migrationOutput` is MANDATORY**, and its shape is `{bucket, prefixes}`: `bucket` is one general-purpose bucket ARN (required, `arn:aws:s3:::<name>`); `prefixes` names an optional key prefix for each of the three reports, `tableCompatibilityReport`, `objectCompatibilityReport`, `objectMigrationReport` (a report with no prefix is written at the bucket root). Reports are written under
`<prefix>/<migration-id>/<report-type>/v1/...`; take each object key from `migrationOutput.<report>.key` rather than building the path, because the folder layout can change. For the object compatibility and object migration reports the key points to the report's manifest; for the table compatibility report it points to the report file. An empty `migrationOutput` `{}` is rejected because `bucket` is required. The example gives all three reports the **same** prefix so a single `s3:PutObject` grant on that prefix covers them (see `references/iam-roles.md`); if you give them distinct prefixes, the role needs one grant per prefix.
- `reviewMigrationPlan: true` pauses at `pendingReview` so you can inspect before any data moves. Always set it; never auto-approve.
- Do not add an `sts:ExternalId` condition to the role trust policy (see `references/iam-roles.md`); the migration service does not send one (there is no API field for it), so such a condition would fail every assume.

### Call

```bash
aws s3tables start-table-migration \
  --region <R> \
  --cli-input-json file://start-migration.json
```

Response: `{ "migrationId": "...", "state": "..." }` (`new` or `planning`). Record the `migrationId`.

### Then

Poll with `get-table-migration` until `state` leaves `new` and `planning`. Planning is async, wait
~45–60s between polls. Expect `pendingReview` with `hasValidPlan: true`, or `failed` with a
named `failureReason` (see `references/troubleshooting.md`). Proceed to the Plan review section
below.

## Plan review

At `pendingReview`, pull the full record and inspect before approving.

```bash
aws s3tables get-table-migration \
  --region <R> \
  --migration-id <ID>
```

### What to check

The current API does **not** return a `plannedTransformations` list on `get-table-migration`. The plan is reviewed through the two **compatibility reports** that planning writes (before any data moves), surfaced in the `migrationOutput` echo of the record.

1. **`hasValidPlan: true`** and `state: pendingReview`.
2. **`migrationOutput`** (response shape) carries `bucket` plus a `ReportOverview` for each report, `tableCompatibilityReport`, `objectCompatibilityReport`, and (only after the migrating phase) `objectMigrationReport`. Each `ReportOverview` has `prefix`, `key`, `checksumCRC64NVME`, and `invalidFindings` (a map of counts by category: `access`, `metadata`, `data`, `internal`). A populated `key` confirms the report was written (so report-bucket write works); non-zero `invalidFindings` means blocking issues were found.
3. **Read the table compatibility report** (the CSV object at `migrationOutput.tableCompatibilityReport.key`; the report is plain `text/csv`, not gzipped, so `aws s3 cp s3://<REPORT_BUCKET>/<key> -` reads it directly and the key ends `report.csv`) for the per-column type changes. Each row: `finding_type` (`invalid` blocks the migration, `informational` does not), `finding_category` (`access`/`metadata`/`data`/`internal`), `finding_subcategory` (e.g. `schemaTransformation.widened`, `schemaTransformation.converted`, `glueTableParameters`), and `details` (JSON: `fieldPath`, `glueType`, `destinationType`, partition flag, the applicable policy, and `outcome`). The type-change class is the **lowercase** value in `finding_subcategory` (`schemaTransformation.<class>`): `lossless`, `widened`, `converted`, `incompatible`, `unsupported`. Match it case-insensitively; the Title-case labels below are display only:
   - **Lossless**, type and every value unchanged.
   - **Widened**, larger type of the same kind, no value lost (e.g. `int`→`long`, `varchar(n)`→`string`). Acceptable; confirm intent.
   - **Converted**, the value is preserved except where the conversion itself loses precision (e.g. `char(n)`→`string` drops length/padding; Parquet INT96 nanoseconds → Iceberg `timestamptz` microseconds truncates sub-microsecond values). Review and accept consciously; this is not lossless.
   - **Incompatible**, the destination type can't hold every value (e.g. `bigint`→`int`). `incompatibleValuesPolicy` decides **column-wide**, not per object: `fail` (default) fails the run, `setNull` writes the entire column null (the whole column, whatever the values). Treat as data loss requiring explicit user sign-off.
   - **Unsupported**, no Iceberg type / unsupported change; the migration fails unless you drop the column via `unmatchedSourceFieldsPolicy: drop` (removes the whole column; data loss requiring sign-off; you cannot drop a partition column).
4. **Object compatibility report** (`objectCompatibilityReport.key`) lists each scanned source object and any issue that keeps it out of the migration.
5. **`planningStats`**, `objectsScanned`, `objectsPlanned`, `partitionCount`. **`migrationStats.objectsPendingMigration`** should match the source object count you expect.

### Compact plan view

```bash
aws s3tables get-table-migration \
  --region <R> --migration-id <ID> \
  --query '{state:state,hasValidPlan:hasValidPlan,reportKey:migrationOutput.tableCompatibilityReport.key,invalid:migrationOutput.tableCompatibilityReport.invalidFindings,objInvalid:migrationOutput.objectCompatibilityReport.invalidFindings,pending:migrationStats.objectsPendingMigration}'
```

### Decision

- `hasValidPlan: true`, both compatibility reports' `invalidFindings` all zero, and the table compatibility report shows only type changes you accept (`Lossless`/`Widened`, plus any `Converted` you consciously accept) → safe to approve (see Approve + migrate below).
- Before approving, scan the table compatibility report's `details.outcome`: any `setNull` or `dropped` entry is column-wide data loss (the whole column, not a per-object issue) and needs explicit user sign-off. Plan review does not block on it, so you must check.
- Any non-zero `invalidFindings`, any `invalid` `finding_type`, an `Unsupported` change, or an `Incompatible` change you cannot accept → **cancel this migration first** with `update-table-migration --requested-state cancelled`. A cancelled migration keeps its destination table. To change `migrationPolicies`, the destination schema, or the sort order, delete the destination table (with the user's confirmation) and Start again; Sync reuses the Start's settings, so it cannot apply these changes. If you only fixed the source and `hasValidPlan` is true, resume with `sync-table-migration` instead. See Recovery after a cancel or fail.
- If `hasValidPlan` is not `true`, or `migrationOutput.tableCompatibilityReport.key` is absent / the report cannot be read, treat it as cannot-verify and STOP. Never read a missing report as "no findings / clean". Re-pull the record; if it stays absent, open a case with AWS Support (include the `migrationId` and region) before approving.

## Approve + migrate

Only after the plan is reviewed and the user has approved it (see "Before you migrate" in
`SKILL.md`). Approving starts the data copy into the destination table.

### Approve (release into the copy)

**`--requested-state` MUST be lowercase.** The enum accepts only `queued` and `cancelled`.
`QUEUED` (or any other casing) fails with `ValidationException: Member must satisfy enum value
set: [cancelled, queued]`. Always pass `queued`, never `QUEUED`.

```bash
aws s3tables update-table-migration \
  --region <R> \
  --migration-id <ID> \
  --requested-state queued
```

Response shows `state: queued`.

### Poll to completion

```bash
aws s3tables get-table-migration \
  --region <R> --migration-id <ID> \
  --query '{state:state,objectsMigrated:migrationStats.objectsMigrated,objectsPending:migrationStats.objectsPendingMigration,failed:migrationStats.objectsFailedMigration,failureReason:failureReason}'
```

- `queued → migrating → succeeded`. Wait ~30–60s between polls. Do not poll indefinitely: if the state has not changed for roughly 30 minutes on a modest table, or elapsed time is well past what a plain S3 copy of the same byte volume would take, stop and treat it as the stuck-in-`migrating` case under Failure handling below.
- **Success:** `state: succeeded`, `objectsPending: 0`, `objectsFailedMigration: 0`, `objectsMigrated` equal to `planningStats.objectsPlanned`, `failureReason: null`. Then confirm the data with row-count parity (`references/validation.md`).
- If `objectsMigrated` differs from the planned count, check the source object count before calling it a bug; a table with an extra file from an earlier sync legitimately reports more.

### Failure handling

- **Copy is all-or-nothing.** If even one object fails to copy, the whole migration and table go to `failed` with a `failureReason` (often `objectMigrationReport`); the run never ends `succeeded` with failed objects. The destination table is kept. Read the object migration report for the failed key and `error_code`, fix the cause, then resume with `sync-table-migration` if `hasValidPlan` is true, or delete the table and Start again.
- `failed` with a `failureReason` → look it up in `references/troubleshooting.md`, fix, then recover per the Recovery rules above.
- Stuck in `queued` with no pickup for an extended period, no `failureReason` → likely a service-side delay before the job starts, not your setup. Capture the `migrationId` and open a case with AWS Support (include the `migrationId` and region).
- Stuck in `migrating` with no progress (as a rough basis: no state change for ~30 minutes on a modest table, or elapsed time well beyond a plain S3 copy of the same byte volume), and no `failureReason` → capture the `migrationId` and open a case with AWS Support (include the `migrationId` and region). A prolonged `migrating` with no progress is a failure signal, not success.

## Sync (optional)

Use Sync to catch the destination up with changes the source accumulated since the plan, before
you cut over. Repeat until the delta is current.

### Request body (sync-migration.json)

```json
{
  "roleARN": "arn:aws:iam::<ACCT>:role/<MIGRATION_ROLE>",
  "tableARN": "<DESTINATION_TABLE_ARN>",
  "reviewMigrationPlan": true,
  "migrationOutput": {
    "bucket": "arn:aws:s3:::<REPORT_BUCKET>",
    "prefixes": {
      "tableCompatibilityReport": "migration-api-reports",
      "objectCompatibilityReport": "migration-api-reports",
      "objectMigrationReport": "migration-api-reports"
    }
  }
}
```

Reuse the Start report prefix so the role's existing `WriteReports` grant covers it. A different
prefix needs its own `s3:PutObject` grant, or Sync fails with `destinationPermissions`.

```bash
aws s3tables sync-table-migration \
  --region <R> \
  --cli-input-json file://sync-migration.json
```

The Sync body is NOT the same as Start: it takes only `roleARN`, `tableARN` (the
migrated table, top level), `reviewMigrationPlan`, and `migrationOutput`, there is **no `source`**. The
service infers the source from the original migration and uses the last valid plan as the diff
basis. (A `reviewMigrationPlan: true` sync plans the delta and pauses at
`pendingReview`, same as Start.)

### Semantics

- Sync applies only the delta since the last plan or sync, not a full re-copy. A Sync is a change to the destination table; it needs the same plan review and approval as Start.
- Sync reconciles **new and appended** source objects. It does **not** handle an already-migrated object that was overwritten **in place** (the same S3 key rewritten): the sync fails with failure code `objectCompatibilityReport` and finding `data.objectModified`. Hive `INSERT OVERWRITE` rewrites the same keys, so a source changed that way between plan and sync cannot be synced incrementally, re-migrate it fresh instead.
- Each Sync returns its **own** `migrationId` and `state`; poll that id, not the original migration's.
- With `reviewMigrationPlan: true` the sync parks at `pendingReview`; approve it with `update-table-migration --requested-state queued` on the sync's own `migrationId`, the same as Start. If you copy `reviewMigrationPlan: true` and never approve, the sync sits in `pendingReview` and the next Sync is rejected.
- A Sync started while anything on the table is still non-terminal returns `ConflictException` (409); a Sync after Complete returns `BadRequestException` (400).
- A Sync with no source changes succeeds with 0 objects planned.
- On cancel or fail the destination table is kept; the last valid plan is the basis for the next Sync.
- Repeat Sync until `objectsPendingMigration` is 0 and the source is quiesced, then Complete.

### When to Sync vs. Complete

- Source still receiving writes and you want minimal cutover delta → Sync repeatedly, then Complete during a short freeze.
- Source already frozen / point-in-time is fine → skip Sync, go straight to Complete.

## Complete

Promotes the migrated destination table to an ordinary read-write S3 Table. Complete does not set
a migration state called `active` (there is none) and returns an **empty body**; confirm it by
calling `get-table` and checking that the table's `managedByService` is cleared to null.

```bash
aws s3tables complete-table-migration \
  --region <R> \
  --table-arn <DESTINATION_TABLE_ARN>
```

### Important

- Takes **`--table-arn`**, NOT `--migration-id`. The table ARN is in the migration record (`get-table-migration` → `tableARN`).
- Complete **only a `succeeded` migration**. Completing promotes whatever data is committed on the destination table to read-write, so completing a `failed` or `cancelled` migration would publish a partial table. Calling Complete while the copy is still in progress (`queued`/`migrating`) returns `ConflictException` (409, e.g. `MIGRATION_IN_PROGRESS`); a malformed or otherwise invalid request returns `BadRequestException` (400).
- Completing a migration that is already complete returns `ConflictException` (409) or `BadRequestException` (400). Treat either as "already done", not an error to fix: confirm `get-table` shows `managedByService` null, then stop.
- **Complete is one-way, so validate first.** After Complete, Sync is refused (`BadRequestException` 400), so you cannot reconcile a shortfall afterward. The destination holds committed data and is queryable while still `succeeded` (before Complete), so run the destination row-count parity check (`references/validation.md`) on the `succeeded` table **before** Complete; if it is short, `sync-table-migration` to reconcile (only possible pre-Complete), and Complete only once parity holds.
- After Complete, confirm `get-table` shows `managedByService` null. The table is then read-write and queryable normally.

### Response

`CompleteTableMigration` returns an **empty body** (HTTP success with no content) and does not
change the migration's `state`. There is no `active` state and no `completedAt` field. Confirm
completion by calling `get-table --table-arn <ARN>` and checking that `managedByService` is cleared
to null (it reads `migration.s3tables.amazonaws.com` while the migration owns the table and is
absent/null once Complete hands it over), then query the table (validation).

## List migrations

`ListTableMigrations` discovers migrations on the endpoint. The request members are
`tableBucketARN`, `namespace`, `name`, `tableARN`, `state`, `hasValidPlan`, `maxResults`,
and `nextToken`. It is **not account-wide**: scope it by `tableBucketARN` (optionally narrowed by `namespace`, then `name`), or by
`tableARN` alone. A bare call is rejected.

```bash
# in-flight migrations for one destination table bucket
aws s3tables list-table-migrations \
  --region <R> \
  --table-bucket-arn <DEST_BUCKET_ARN> \
  --state planning

# migrations for one destination table
aws s3tables list-table-migrations \
  --region <R> \
  --table-arn <DESTINATION_TABLE_ARN>
```
