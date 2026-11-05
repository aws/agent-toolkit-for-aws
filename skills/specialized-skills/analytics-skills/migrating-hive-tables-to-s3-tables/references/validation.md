# Validation, before Complete

Confirm the migration actually succeeded. Do not assume from `state` alone. Run §1 to §6 on the
`succeeded` table **before** Complete: the table is queryable then, and a shortfall can still be
reconciled with `sync-table-migration`. After Complete, Sync is refused, so the only post-Complete
check is that `get-table` shows `managedByService` cleared to null.

## 1. Terminal state + accounting

```bash
aws s3tables get-table-migration \
  --region <R> --migration-id <ID> \
  --query '{state:state,migrated:migrationStats.objectsMigrated,pending:migrationStats.objectsPendingMigration,failed:migrationStats.objectsFailedMigration,failureReason:failureReason}'
```

- Terminal status comes from `state` + `failureReason`: expect `succeeded` with `failureReason: null`. Complete returns an empty body and there is no `active` state; after Complete, confirm via `get-table` that `managedByService` is null. A non-null `failureReason`, or a stall in `migrating`, is the real failure signal.
- `objectsFailedMigration` is 0 and `objectsMigrated` equals `planningStats.objectsPlanned`. If they differ, check the source object count first (an extra file from an earlier sync is a legitimate difference). Always confirm with the row-count parity in §3, which reads the data itself.

## 2. Query the destination, S3 TABLES CATALOG NAMING

> **Prerequisite:** Athena can only query the migrated table once the destination table bucket is integrated with the AWS Glue Data Catalog (the integration uses AWS Glue and Lake Formation). Without it, a migration that succeeded is still invisible to Athena. See [Integrating S3 Tables with AWS analytics services](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integration-overview.html) and [Querying S3 tables with Athena](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-athena.html).

The migrated table is queried in Athena with the table bucket as part of the **catalog
identifier**. The catalog identifier is a single level, `s3tablescatalog/<table-bucket>`
(slash-joined), followed by namespace and table:

```
Catalog identifier: s3tablescatalog/<table-bucket>   (one quoted level, slash-joined)
Fully qualified:    "s3tablescatalog/<table-bucket>"."<namespace>"."<table>"
```

In Athena SQL (quote each level):

```sql
SELECT * FROM "s3tablescatalog/<table-bucket>"."<namespace>"."<table>";
```

The #1 mistake is writing it dotted (`s3tablescatalog.<table-bucket>. ...`, which is not valid
Athena) or defaulting to `awsdatacatalog` (the 3-level `catalog.database.table` form used for
regular Glue tables). Neither works for S3 Tables.

## 3. Row-count parity

```sql
-- source (regular Glue table, 3-level)
SELECT count(*) FROM "awsdatacatalog"."<db>"."<tbl>";
-- destination (S3 Tables, slash-joined catalog)
SELECT count(*) FROM "s3tablescatalog/<table-bucket>"."<namespace>"."<table>";
```

Counts must match.

Row-count parity is the authoritative success check.

If the migration or a sync was scoped to a subset of the source, compare against that subset, not the full source.

## 4. Partition parity

Skip for an unpartitioned table. Compare per-partition row counts on both sides:

```sql
SELECT <part_cols>, count(*) FROM "awsdatacatalog"."<db>"."<tbl>" GROUP BY <part_cols> ORDER BY <part_cols>;
SELECT <part_cols>, count(*) FROM "s3tablescatalog/<table-bucket>"."<namespace>"."<table>" GROUP BY <part_cols> ORDER BY <part_cols>;
```

- The number of groups matches `planningStats.partitionCount` and the partition count recorded in preflight.
- Every partition value and its row count match. Compare query results, not S3 directories against Iceberg metadata.

## 5. Spot-check rows

Sample a handful of rows from both and compare values, especially timestamp columns (INT96
timestamps are `Converted` to `timestamptz`) and any widened numeric types.

## 6. Schema/transform review

Re-confirm every column's type change in the table compatibility report was a class you accept (`Lossless`, `Widened`, or a `Converted` class you consciously accept); none is `Unsupported` or an `Incompatible` change you did not intend. The report spells these lowercase (`lossless`/`widened`/`converted`/`incompatible`/`unsupported`), so match case-insensitively.

## Checklist (before Complete, except the last item)

- [ ] `state` succeeded, no `failureReason`
- [ ] 0 `objectsFailedMigration`; `objectsMigrated` matches the planned count (or a difference is explained by the source object count and row-count parity passes)
- [ ] destination queried via the S3 Tables catalog naming
- [ ] row counts match source (§3), the authoritative success check
- [ ] partition count and per-partition row counts match (if partitioned)
- [ ] sampled rows equal (values + timestamps)
- [ ] all type changes in the table compatibility report are classes you accept (no `unsupported`, no unintended `incompatible`)
- [ ] After Complete: `get-table` shows `managedByService` cleared to null
