# Schema Conversion Operations Reference

## Command Summary

| Command | Purpose | Async | Poll via | Waiter |
|---------|---------|-------|----------|--------|
| [start-metadata-model-import](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-import.html) | Import metadata from source or target DB | Yes | `describe-metadata-model-imports` | [`metadata-model-imported`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-imported.html) |
| [start-metadata-model-conversion](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-conversion.html) | Convert source schema to target | Yes | `describe-metadata-model-conversions` | [`metadata-model-converted`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-converted.html) |
| [start-metadata-model-assessment](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-assessment.html) | Assess conversion complexity | Yes | `describe-metadata-model-assessments` | [`metadata-model-assessed`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-assessed.html) |
| [start-metadata-model-creation](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-creation.html) | Create statement-based model | Yes | `describe-metadata-model-creations` | [`metadata-model-created`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-created.html) |
| [start-metadata-model-export-as-script](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-export-as-script.html) | Export DDL to S3 | Yes | `describe-metadata-model-exports-as-script` | [`metadata-model-exported-as-script`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-exported-as-script.html) |
| [start-metadata-model-export-to-target](https://docs.aws.amazon.com/cli/latest/reference/dms/start-metadata-model-export-to-target.html) | Apply converted DDL to target DB | Yes | `describe-metadata-model-exports-to-target` | [`metadata-model-exported-to-target`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-exported-to-target.html) |
| [export-metadata-model-assessment](https://docs.aws.amazon.com/cli/latest/reference/dms/export-metadata-model-assessment.html) | Generate PDF/CSV report to S3 | Sync | N/A | sync |
| [describe-metadata-model-children](https://docs.aws.amazon.com/cli/latest/reference/dms/describe-metadata-model-children.html) | Navigate tree structure | Sync | N/A | sync |
| [describe-metadata-model](https://docs.aws.amazon.com/cli/latest/reference/dms/describe-metadata-model.html) | Get object definition (DDL) | Sync | N/A | sync |
| [cancel-metadata-model-conversion](https://docs.aws.amazon.com/cli/latest/reference/dms/cancel-metadata-model-conversion.html) | Cancel running conversion | Yes* | N/A | [`metadata-model-conversion-cancelled`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-conversion-cancelled.html) |
| [cancel-metadata-model-creation](https://docs.aws.amazon.com/cli/latest/reference/dms/cancel-metadata-model-creation.html) | Cancel running creation | Yes* | N/A | [`metadata-model-creation-cancelled`](https://docs.aws.amazon.com/cli/latest/reference/dms/wait/metadata-model-creation-cancelled.html) |

> \* The cancel API call returns synchronously, but the cancellation state transition is async (`CANCEL_RECEIVED` → `CANCELING` → `CANCELED`). Use the corresponding waiter to confirm the operation reached the `CANCELED` state.
>
> **Note:** All waiters require `--filter 'Name=request-id,Values=<RequestIdentifier>'` in addition to `--migration-project-identifier`.

For full parameter details and examples, refer to the linked CLI documentation for each command.

---

## DMS Waiters

Use DMS waiters to wait for async operations to complete:

| Operation | Waiter command |
|-----------|---------------|
| Import | `aws dms wait metadata-model-imported` |
| Conversion | `aws dms wait metadata-model-converted` |
| Assessment | `aws dms wait metadata-model-assessed` |
| Creation (statement) | `aws dms wait metadata-model-created` |
| Export as script | `aws dms wait metadata-model-exported-as-script` |
| Export to target | `aws dms wait metadata-model-exported-to-target` |
| Cancel conversion | `aws dms wait metadata-model-conversion-cancelled` |
| Cancel creation | `aws dms wait metadata-model-creation-cancelled` |
| Extension pack | `aws dms wait extension-pack-associated` |

Documentation: https://docs.aws.amazon.com/cli/latest/reference/dms/wait/index.html

---

## Operation Statuses

All async operations use the same status values:

| Status | Meaning |
|--------|---------|
| `RECEIVED` | Request received, queued |
| `IN_PROGRESS` | Operation is running |
| `SUCCESS` | Operation completed successfully |
| `FAILED` | Operation failed — check error details |
| `CANCEL_RECEIVED` | Cancellation request received |
| `CANCELING` | Cancellation in progress |
| `CANCELED` | Operation was cancelled |
| `RETRY` | Operation is being retried |
| `PENDING` | Operation is pending |

---

## Execution Pattern

1. Call `start-*` → extract `RequestIdentifier`
2. Wait for completion using the corresponding `aws dms wait` command (see DMS Waiters table)
3. If the waiter returns successfully → proceed to next step
4. If the waiter fails or is unavailable (e.g., `Invalid choice` due to outdated CLI) → fall back to manual polling with the corresponding `describe-*` command until status reaches `SUCCESS` or `FAILED`

**Fallback polling pattern** (use when waiter is not available):

```
aws dms describe-metadata-model-<operation>s \
  --migration-project-identifier <migration_project_identifier> \
  --filter Name=request-id,Values=<RequestIdentifier>
```

Check `Requests[0].Status` — repeat every 30 seconds until it reaches `SUCCESS` or `FAILED`.

**Constraint:** You MUST NOT proceed to the next step until the operation has completed. If the waiter fails or times out, you MUST fall back to polling with the describe command. Never assume an operation succeeded without confirming its status.

---

## Key Notes

- `describe-metadata-model` returns `TargetMetadataModels` with target `SelectionRules` — use these to query the TARGET tree (do NOT reuse source selection rules for target)
- `describe-metadata-model-children` returns `MetadataModelChildren[]` with `MetadataModelName` and `SelectionRules` — use the child's `SelectionRules` to drill deeper
- `export-metadata-model-assessment` is synchronous — returns S3 links immediately (`PdfReport.S3ObjectKey`, `CsvReport.S3ObjectKey`)
- `start-metadata-model-creation` only supports **SQL Server → PostgreSQL/Aurora PostgreSQL**

---

## Auto Import

This procedure imports SOURCE metadata after project creation or when **Work with Tree** finds an empty SOURCE tree. Do not use it for TARGET navigation or rerun it when the required source metadata is already loaded.

1. Build selection rules to import all schemas from the source provider. Use the data-provider resource ID or its exact stored `ServerName` for `server-name`. Include every required engine-specific locator level. For SQL Server, include the exact `database-name` retained from setup or the existing provider configuration. See [Selection rules in DMS Schema Conversion](https://docs.aws.amazon.com/dms/latest/userguide/sc-selection-rules.html).

2. Start the import and store `RequestIdentifier`:

   ```
   aws dms start-metadata-model-import \
     --migration-project-identifier <migration_project_identifier> \
     --origin SOURCE \
     --refresh \
     --selection-rules '<json>'
   ```

3. Wait for completion:

   ```
   aws dms wait metadata-model-imported \
     --migration-project-identifier <migration_project_identifier> \
     --filter 'Name=request-id,Values=<RequestIdentifier>'
   ```

   If the waiter returns successfully, store `import_status = SUCCESS` and continue to Step 5.

4. If the waiter fails or is unavailable, poll the import directly:

   ```
   aws dms describe-metadata-model-imports \
     --migration-project-identifier <migration_project_identifier> \
     --filter 'Name=request-id,Values=<RequestIdentifier>'
   ```

   Check `Requests[0].Status` every 30 seconds until `SUCCESS` or `FAILED`. Store the terminal status as `import_status` and store any `Requests[0].Error`; do not return yet.

5. If the source data provider is virtual and its settings contain `S3Path`, verify the per-file outcomes:
   - Read `SchemaConversionApplicationAttributes.S3BucketPath` from the migration project, then read `<S3BucketPath>/<migration_project_name>/ddl-statistics/ds.csv` without displaying DDL.
   - Report total, `SUCCESS`, `FAILED`, and `SKIPPED` row counts plus failed object keys and comments.
   - Record whether the statistics file is available and whether any row is `FAILED`.

6. Describe the SOURCE root children and record whether the expected schemas or databases are present. Treat this result independently from the request status and DDL statistics.

7. If `import_status = FAILED`, preserve and report the request ID, status, and service error. For an offline source, follow [troubleshooting.md](troubleshooting.md), **Offline Source Failures**, using the statistics and metadata evidence already collected, then return to the invoking root workflow. For an online source, return to the root error-handling workflow.

8. If the import succeeded but the expected metadata is incomplete, or an offline import has no statistics file or any `FAILED` row:
   - For an offline source, follow [troubleshooting.md](troubleshooting.md), **Offline Source Failures**, then return to the invoking root workflow.
   - For an online source, return to the root error-handling workflow.

9. Show the imported schemas or databases:

   > "Import complete. I found the following schemas/databases: `<list>`. Does this look correct?"

10. Return to the invoking root workflow.

## Selection Scope

Before conversion, assessment, report export, or statistics collection:

1. Preserve every required engine-specific locator level and exact provider identity.
2. For a whole schema or database, use the documented broad locator without a leaf object key.
3. For selected object categories, build rules for every requested category. A table rule does not include views or other sibling categories.
4. Reuse the same object set for the operation and its report export. Change only fields the destination API requires, such as `rule-action: "explicit"`.

## Tree Navigation

- Keep the selected `origin` (`SOURCE` or `TARGET`) throughout navigation.
- Pass each child's service-returned `SelectionRules` unchanged. Do not rebuild rules from display names.
- To load an unloaded tree or category, use its exact returned rules, the current `origin`, and `Refresh=false`. Import only when that provider and origin support it. A virtual target cannot be imported.
- Use `Refresh=true` only when the customer explicitly asks to refresh a connected database.
- If loading fails, preserve the operation status and follow the troubleshooting reference. Do not invent a schema or leaf locator.
