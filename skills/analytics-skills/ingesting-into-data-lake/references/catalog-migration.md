# Catalog Migration to S3 Tables

Migrate existing Glue Data Catalog tables into Amazon S3 Tables. Source tables can be Hive-format, self-managed Iceberg, or any format Athena can read. The result is a fully managed S3 Table with automatic compaction, snapshot management, and multi-engine access.

## Reference Documentation

- [ctas-patterns.md](ctas-patterns.md) -- Athena CTAS syntax for S3 Tables, format options, partition transforms
- [migration-validation.md](migration-validation.md) -- Row count, schema, and data integrity checks
- [glue-etl-migration.md](glue-etl-migration.md) -- Glue 5.1 or higher PySpark migration for large tables
- [migration-troubleshooting.md](migration-troubleshooting.md) -- Common errors and fixes

## Why Migrate?

Self-managed Iceberg and Hive tables require manual compaction, snapshot cleanup, and storage optimization. S3 Tables handles all of this automatically. Migration also enables the four-part catalog hierarchy (`s3tablescatalog/<bucket>/<namespace>/<table>`) for unified access from Athena, EMR, Redshift, and Spark.

Note: The target for catalog migration is always S3 Tables -- that is the purpose of this workflow.

## Workflow

### Phase 1: Understand the Source

1. **Identify the source table**: Get the fully qualified name (`database.table` or `catalog.database.table`). If the user gives a fuzzy or business name ("our orders table", "the sales data"), delegate to the `finding-data-lake-assets` skill to resolve it before continuing -- the rest of this workflow assumes a concrete reference.
2. **Inspect the source**:
   - **With MCP**: Use `aws-mcp` to get table metadata (format, location, schema, partitions)
   - **Without MCP**: `aws glue get-table --database-name <db> --name <table>`
3. **Classify the source format**:
   - **Hive (CSV, Parquet, ORC, JSON, Avro)**: Standard external table backed by S3 general purpose bucket
   - **Self-managed Iceberg**: Iceberg table in general purpose bucket with manual maintenance
   - **Other**: Any format Athena can query (federated sources, etc.)
4. **Assess size and complexity**:
   - **Small/medium** (under ~100 GB, simple schema): Path A (Athena CTAS) -- single SQL statement
   - **Large** (over ~100 GB, complex transforms, or needs scheduling): Path B (Glue ETL)
   - **Partitioned source**: Note partition columns and strategy for conversion

### Phase 2: Prepare the Target

1. **Ensure table bucket exists**: Check with `aws s3tables list-table-buckets`. If none, delegate to [creating-data-lake-table](../../creating-data-lake-table/SKILL.md) Phase 2.
2. **Ensure analytics integration is enabled**: Verify `s3tablescatalog` exists. Delegate to [creating-data-lake-table](../../creating-data-lake-table/SKILL.md) Phase 2, step 4 if not set up.
3. **Create or select namespace**: Use existing or create new via `aws s3tables create-namespace`.
4. **Plan partition strategy**: Iceberg supports hidden partition transforms (`day()`, `month()`, `year()`, `hour()`, `bucket()`). Recommend converting Hive-style explicit partition columns to Iceberg transforms where possible.

### Phase 3: Migrate the Data

#### Path A: Athena CTAS (default for small/medium tables)

Single SQL statement that creates the S3 Table and populates it in one step. See [ctas-patterns.md](ctas-patterns.md) for full syntax and examples.

Key points:

- Target path: `"s3tablescatalog/<table_bucket_name>"."<namespace>"."<new_table_name>"`
- Default format: `PARQUET`. Also supports `AVRO`, `ORC`.
- Use Iceberg partition transforms (`day()`, `month()`, `bucket()`) instead of Hive-style explicit partition columns.
- No `LOCATION` clause -- S3 Tables manages storage.
- Table and column names must be all lowercase.
- Source catalog for default GDC tables is `awsdatacatalog`.
- Add `WHERE` filters to migrate subsets or batch large migrations.

#### Path B: Glue ETL (for large tables or complex transforms)

Use when CTAS would time out, when transforms are complex, or when the migration needs to be scheduled/repeatable.

1. **Create PySpark script** that reads from source and writes to S3 Table
2. **Create Glue 5.1 or higher job** with `--datalake-formats iceberg` and `--conf` catalog config
3. **Run and monitor** the job

See [glue-etl-migration.md](glue-etl-migration.md) for job configuration, PySpark script template, and catalog setup.

### Phase 4: Validate the Migration

Run all of these checks -- do not skip any:

1. **Row count comparison**:

   ```sql
   SELECT 'source' AS tbl, COUNT(*) AS cnt FROM "<source_catalog>"."<source_db>"."<source_table>"
   UNION ALL
   SELECT 'target' AS tbl, COUNT(*) AS cnt FROM "s3tablescatalog/<bucket>"."<namespace>"."<new_table>"
   ```

2. **Schema comparison**: Verify column names, types, and order match expectations. Minor type promotions (e.g., `int` to `bigint`) are acceptable.

3. **Spot-check data**: Compare a sample of rows between source and target, focusing on:
   - Boundary values (min/max of numeric and date columns)
   - Null counts per column
   - Distinct counts on key columns

4. **Partition verification** (if partitioned):

   ```sql
   SELECT <partition_column>, COUNT(*) FROM "s3tablescatalog/<bucket>"."<namespace>"."<new_table>"
   GROUP BY 1 ORDER BY 1
   ```

See [migration-validation.md](migration-validation.md) for the full checklist.

### Phase 5: Post-Migration Guidance

After validation passes:

1. **Update downstream consumers**: Provide the new table path for queries, dashboards, and ETL jobs.
2. **Recommend keeping the source table** temporarily as a rollback option. Suggest a retention period (e.g., 30 days).
3. **Do NOT drop the source table**. Warn the user and let them decide when to clean up.
4. **Evaluate table lineage**: If the source table has lineage present, use it to recommend next-steps for producers and consumers.

## Gotchas

- Athena CTAS has a 100-partition limit per statement. For sources with more than 100 partitions, either migrate in batches with `WHERE` filters or use Glue ETL (Path B).
- CTAS creates a new table -- it does not do an in-place conversion. The source table remains unchanged.
- Column names with uppercase letters will cause the target table to be invisible to analytics services. Always lowercase column names in the SELECT: `SELECT upper_Col AS upper_col`.
- Self-managed Iceberg tables may have schema evolution history (added/renamed columns). CTAS captures the current schema only -- historical evolution is not preserved.
- Hive tables with complex SerDe configurations (custom delimiters, regex SerDe) should be tested with a small CTAS first to verify Athena can read them correctly. Glue will often read things Athena cannot. Try Glue if Athena fails.
- Time travel on the source Iceberg table is lost after migration. The S3 Table starts fresh with its own snapshot history.

## Troubleshooting

See [migration-troubleshooting.md](migration-troubleshooting.md) for common errors and fixes covering CTAS failures, validation mismatches, visibility issues, and partition problems.
