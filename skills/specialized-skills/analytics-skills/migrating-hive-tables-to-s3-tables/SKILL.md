---
name: migrating-hive-tables-to-s3-tables
description: "Migrates a Glue Data Catalog Hive table (Parquet) into Amazon S3 Tables as managed Iceberg using the native S3 Tables migration API (StartTableMigration, SyncTableMigration, CompleteTableMigration), a managed service call, not a self-run CTAS, Glue, or EMR job. The source is a Hive table; an Iceberg source is never in scope, even when the destination is S3 Tables. Covers plan review, migrate, sync, complete, and validate. Same-account, same-region, Glue Hive Parquet source only. Use when the request asks to migrate or import a Hive table into S3 Tables, or names the native migration API. Not applicable to converting a self-managed or standard Iceberg table into S3 Tables (ingesting-into-data-lake covers that), self-run CTAS/Glue-ETL/Spark migrations (ingesting-into-data-lake), or creating empty tables (creating-data-lake-table)."
version: 1
---

# Migrating Hive Tables to S3 Tables

## Contents

- [Overview](#overview)
- [Before you migrate](#before-you-migrate)
- [When to use](#when-to-use)
- [When NOT to use (use another skill)](#when-not-to-use-use-another-skill)
- [Scope and constraints](#scope-and-constraints)
- [The 6 migration APIs](#the-6-migration-apis)
- [Migration lifecycle](#migration-lifecycle-phases)
- [Pre-migration guardrails](#pre-migration-guardrails-run-every-time-before-start)
- [Post-migration guardrails](#post-migration-guardrails-verify-success-before-complete)
- [Key API shapes](#key-api-shapes)
- [Security considerations](#security-considerations)
- [References](#references)

## Overview

This skill guides an agent through migrating one Glue Hive Parquet table into an S3 table
bucket with the native S3 Tables migration API. Amazon S3 Tables plans the migration, reports
column and object compatibility, copies the data, and keeps the destination in sync with the
source until you complete it. Your coding agent, following this skill, runs preflight checks, starts the migration, presents
the plan for approval, monitors progress, completes the migration, and validates the result.

When the AWS MCP Server is available, use it to load this skill and its references
(`aws___retrieve_skill`, with `file="references/<name>.md"`) and to run the AWS calls.

## Before you migrate

**Agent instruction:** You MUST present the migration plan and obtain explicit user approval
before any step that changes tables, data, metadata, or catalog entries, and before any IAM, KMS,
or S3 bucket change (creating or editing a role or policy, editing a key policy, creating a report
bucket). Show the exact JSON or command first. For a key policy, read it with `get-key-policy`,
add one statement, and never replace the whole policy. The plan MUST list:

- the source table and the destination table bucket, namespace, and table name;
- the write paths that will change (ETL jobs, streaming or ingest, `INSERT`/`MERGE`, CDC);
- the query engines and downstream consumers that read the table;
- the datasets, saved queries, and permissions that reference the old Glue table or S3 prefix.

Up-front approval in the user's request (naming the source, destination, and intent to migrate)
covers only read-only checks and a Start with plan review. Approving the plan, accepting any
`setNull` or `drop` policy, Complete, and any delete always need explicit approval during the
conversation. If the actual state differs from what was approved (a different schema,
partition layout, row count, or resource), stop, explain the difference, and get approval again.

Confirm these constraints with the user as part of the plan:

- Every writer to the destination writes through an Iceberg-aware engine (for example Athena,
  EMR or Glue with Iceberg). Writers that write Parquet files directly to S3 will not work.
- Every reader supports Iceberg and the S3 Tables catalog.
- Jobs and queries move from the Glue Hive table to the S3 Tables catalog reference.
- The source is not changed. Keep writers on the source until the destination is validated.
- Validate row counts and sample values ([references/validation.md](references/validation.md))
  before moving production traffic.

See [Migrating tables to S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)
for the full list of supported sources and limits.

> **Runtime:** works with or without the AWS MCP server; steps use AWS CLI syntax. The AWS MCP
> server is recommended for sandboxed execution and audit logging. The migration commands are
> part of `aws s3tables`; if an older CLI lacks them, see
> [references/api-setup.md](references/api-setup.md).

## When to use

Use this skill when the source is a Glue Data Catalog Hive table with Parquet data
(`TableType=EXTERNAL_TABLE`, Hive Parquet SerDe) and the destination is an S3 table bucket in the
same account and Region:

- Migrating that table into S3 Tables as managed Iceberg with the native migration API.
- Keeping the migrated table in sync with the active Hive source before cutover.

## When NOT to use (use another skill)

The names below are other agent skills. For these requests, do not use this skill; load the named
skill instead. When asked when not to use this skill, list every case:

- A self-run CTAS, Glue ETL, or EMR/Spark migration into Iceberg: use the `ingesting-into-data-lake` skill (this skill covers only the managed migration API).
- Converting a self-managed or standard Iceberg table: use the `ingesting-into-data-lake` skill.
- Loading raw files (Parquet with no Glue table, CSV, JSON) or other sources (JDBC, Snowflake, BigQuery, DynamoDB): use the `ingesting-into-data-lake` skill.
- Creating a new empty Iceberg table: use the `creating-data-lake-table` skill.
- Running or managing Athena queries: use the `querying-data-lake` skill.
- Locating tables or assets: use the `finding-data-lake-assets` skill. Auditing the catalog: use the `exploring-data-catalog` skill.
- Setting up Glue connections: use the `connecting-to-data-source` skill.
- Any destination other than S3 Tables.

## Prompt patterns (trigger phrasings)

- "Migrate my Glue Hive table `<db>.<tbl>` into my table bucket `<name>`."
- "Import an existing Hive table into S3 Tables using the native migration API."
- "Move my Parquet Hive table to Iceberg without running CTAS or a Glue/Spark job."
- "Use StartTableMigration to convert `<tbl>`."
- "Keep my migrated table in sync with the source before cutover" → Sync.
- "Complete my migrated table" → Complete.
- "Check the status or plan of migration `<id>`" → Get.
- "List my table migrations" → List.

## Scope and constraints

- **Source:** Glue Hive Parquet table in the same account and region as the destination table bucket.
- **Destination:** an existing S3 table bucket and namespace; the migration creates the table.
- **Not supported (confirm the current list in the [S3 Tables migration guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)):** Lake Formation registered tables, partitions outside the table
  location, non-Parquet formats, Iceberg sources, cross-account, SSE-C, and archived storage
  classes. Check these in preflight and stop if any apply. For a Lake Formation registered table,
  tell the user it is not supported and suggest contacting AWS Support or their account team
  with the migration ID to request support. Never change Lake Formation settings.
- Compatibility problems are reported during planning. Always review the plan before approving.
- **All-or-nothing copy:** if a single object fails, the whole migration fails. A `succeeded` run has no failed objects.
- Three reports are written to a general-purpose bucket you supply: table compatibility, object
  compatibility, and object migration.
- **Cost and duration:** the migration writes a second copy of the data; plan for roughly double
  storage until the source is decommissioned. Large tables can take hours.
- **Quotas:** see [S3 Tables quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-regions-quotas.html).
- **Migration policies:** by default an incompatible column fails the run. `incompatibleValuesPolicy: setNull`
  and `unmatchedSourceFieldsPolicy: drop` apply to the whole column and the run still reports
  `succeeded`. Treat any `setNull` or `dropped` column as data loss that needs explicit approval.

## The 6 migration APIs

| API | Purpose | Phase |
|-----|---------|-------|
| `StartTableMigration` | Plan and begin a migration. With `--review-migration-plan`, pauses at `pendingReview`. | Start |
| `GetTableMigration` | Returns `state`, `hasValidPlan`, `planningStats`, `migrationStats`, `migrationOutput`, `failureReason`. | Track, review |
| `UpdateTableMigration` | Approve (`--requested-state queued`) or cancel. | Approve |
| `SyncTableMigration` | Apply source changes since the last plan; repeat until current. | Sync |
| `CompleteTableMigration` | Promote the destination to read-write. Takes `--table-arn`. Returns an empty body; the migration state stays `succeeded`. Confirm with `get-table` (`managedByService` is null). | Complete |
| `ListTableMigrations` | List migrations for one table bucket or table. | Discover |

Request and response shapes are in [references/lifecycle.md](references/lifecycle.md).

## Migration lifecycle (phases)

1. **Preflight** → [references/preflight.md](references/preflight.md), [references/iam-roles.md](references/iam-roles.md)
2. **Start and plan:** `start-table-migration --review-migration-plan`; `planning` → `pendingReview`.
3. **Review:** `get-table-migration`; read the compatibility reports and present the plan for approval.
4. **Approve and migrate:** `update-table-migration --requested-state queued`; poll `migrating` → `succeeded`.
5. **Sync (optional):** `sync-table-migration`; repeat until current.
6. **Validate:** on the `succeeded` table, before Complete, query the destination in Athena and compare with the source → [references/validation.md](references/validation.md). Validation is part of every migration: run the row-count and sample checks without being asked, unless the user opts out. If counts are short, reconcile with `sync-table-migration` (not possible after Complete).
7. **Complete:** once parity holds and the user approves, `complete-table-migration --table-arn ...`, then confirm `get-table` shows `managedByService` null.

Phases 2 to 7 are in [references/lifecycle.md](references/lifecycle.md).

## Pre-migration guardrails (run every time, before Start)

Do not call `start-table-migration` until all of these pass. Commands are in
[references/preflight.md](references/preflight.md) and [references/iam-roles.md](references/iam-roles.md).

0. **Plan approved.** The plan in [Before you migrate](#before-you-migrate) has been presented and approved.
1. **Credentials and region.** `sts get-caller-identity` succeeds; the source and destination are in the same account and region.
2. **Source is Glue Hive Parquet.** `TableType=EXTERNAL_TABLE`, Hive Parquet format and SerDe; not Iceberg, not ACID/transactional, no storage handler. Record `catalogId`.
3. **Partition locations.** Every partition location is under the table location; partitions outside it fail planning with `UNSUPPORTED_PARTITIONS`. Check for partition projection and `skip.header.line.count`.
4. **Lake Formation.** If the source table or its location is registered with Lake Formation, stop: not supported (confirm current support in the migration guide). Do not change Lake Formation settings.
5. **Destination exists.** The table bucket and namespace exist. A missing namespace fails Start with `NotFoundException`.
6. **Migration role trust.** One statement, principal `migration.s3tables.amazonaws.com`, conditions `aws:SourceAccount` and `aws:SourceArn`.
7. **Migration role permissions.** Scoped source S3 and Glue read, destination write, report bucket write. The caller also needs `iam:PassRole` on the role, conditioned on `iam:PassedToService` = `migration.s3tables.amazonaws.com`.
8. **KMS.** If data is encrypted with a customer managed key, grant `kms:Decrypt` and `kms:GenerateDataKey`. For an SSE-KMS destination, the key policy must also allow `maintenance.s3tables.amazonaws.com`, or table creation fails and planning never completes (see [preflight](references/preflight.md) §7 and [IAM roles](references/iam-roles.md)).

## Post-migration guardrails (verify success before Complete)

Full detail in [references/validation.md](references/validation.md).

Run checks 1 to 7 on the `succeeded` table before Complete, because Sync is refused after Complete. After Complete, only confirm that `get-table` shows `managedByService` null.

1. **Terminal state:** `state: succeeded`, `failureReason` null.
2. **Object accounting:** `objectsFailedMigration` is 0 and `objectsMigrated` matches the planned object count. If it differs, check the source object count (an extra file from an earlier sync is legitimate) and confirm with row-count parity before treating it as a failure.
3. **Row count parity:** destination `count(*)` equals source.
4. **Partition parity:** per-partition row counts match (partitioned tables).
5. **Spot-check rows:** sample values match, including converted columns such as timestamps.
6. **Schema review:** every column's type label (`Lossless`, `Widened`, `Converted`) was accepted in the plan; none is `Incompatible` or `Unsupported`.
7. **Catalog naming:** query as `"s3tablescatalog/<table-bucket>"."<namespace>"."<table>"`.

## Key API shapes

- `sourceType` = `glueTable` (top level) and `source` = `{"glueTable":{"catalogId":"<acct>","databaseName":"<db>","tableName":"<tbl>"}}`. `catalogId` is required. The role member is `roleARN`.
- `--destination-table` = `{"tableBucketARN":"<arn>","namespace":"<ns>","name":"<tbl>"}`.
- `migrationOutput` is required: `{bucket, prefixes}`, where `bucket` is a general-purpose bucket ARN and `prefixes` optionally sets `tableCompatibilityReport`, `objectCompatibilityReport`, `objectMigrationReport`.
- Optional `dataMigration.migrationPolicies`: `unmatchedSourceFieldsPolicy` (`fail` | `drop`), `incompatibleValuesPolicy` (`fail` | `setNull`). Both default `fail`.
- Do not add `sts:ExternalId` to the trust policy; Amazon S3 Tables does not send one.
- States: `new → planning → pendingReview → queued → migrating → succeeded`, plus `failed`, `cancelling`, `cancelled`.
- On cancel or failure the destination table is kept. If `hasValidPlan` is true, resume with `sync-table-migration`; otherwise delete the table and start again. Rules in [references/lifecycle.md](references/lifecycle.md).
- Complete only a `succeeded` migration. Completing twice returns `409 ConflictException` or `400 BadRequestException`; treat either as "already done."
- Athena reference: `"s3tablescatalog/<table-bucket>"."<namespace>"."<table>"`. Requires the table bucket to be integrated with the Glue Data Catalog.

## Security considerations

- Instructions only; no shipped code or dependencies.
- **Migration role:** trusts `migration.s3tables.amazonaws.com` with `aws:SourceAccount` and `aws:SourceArn` conditions; permissions scoped to the exact source, destination, and report resources.
- **Encryption:** SSE-KMS on the destination table bucket and report bucket is recommended, with TLS-only bucket policies. A customer managed destination key must allow `maintenance.s3tables.amazonaws.com` in its key policy.
- **Logging:** enable CloudTrail for the migration APIs and role assumptions, S3 data-event or server-access logging on the buckets involved, and CloudWatch alarms on failures. Encrypt log destinations.
- No secrets in generated commands, reports, or state files.

## References

| File | Topic |
|------|-------|
| [references/api-setup.md](references/api-setup.md) | Confirming the migration commands are in the `aws s3tables` CLI |
| [references/preflight.md](references/preflight.md) | Credentials, source checks, partition locations, Lake Formation, destination |
| [references/iam-roles.md](references/iam-roles.md) | Caller policy and migration role trust and permissions |
| [references/lifecycle.md](references/lifecycle.md) | State machine and per-phase calls: start, review, approve, sync, complete |
| [references/validation.md](references/validation.md) | Athena row-count, aggregate, and sample checks; catalog naming |
| [references/troubleshooting.md](references/troubleshooting.md) | `failureReason` codes and fixes |
