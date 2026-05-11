# Iceberg Catalog Config and Engine Access Patterns

How to configure Spark catalog settings, select a target format, and address tables from each engine.

## S3 Tables (Default)

Managed Iceberg tables with automatic compaction, snapshot management, and multi-engine access.

- Catalog path: The table bucket is configured in `--conf` via `glue.id`, so the write path is 3-part: `s3tablescatalog.<namespace>.<table>`
- No LOCATION clause in CREATE TABLE
- Table and column names must be lowercase
- Requires Glue 5.1 or higher and `--datalake-formats iceberg` job argument
- All `spark.sql.catalog.*` config goes in `--conf` job arguments, never in `spark.conf.set()` (Glue 5.x static config restriction)
- Delegate table creation to [creating-data-lake-table](../../creating-data-lake-table/SKILL.md)

Two access methods exist. Use Analytics Integration when the table needs to be visible to Athena, Redshift, or EMR. Use REST Endpoint when only Glue Spark jobs access the table.

**Analytics Integration (recommended for multi-engine access):**

```
spark.sql.catalog.s3tablescatalog=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.s3tablescatalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog
spark.sql.catalog.s3tablescatalog.glue.id=<account-id>:s3tablescatalog/<table-bucket-name>
spark.sql.catalog.s3tablescatalog.warehouse=<table-bucket-arn>
```

The `warehouse` parameter is required. Without it Spark fails with "Cannot derive default warehouse location".

**REST Endpoint (Glue-only access):**

```
spark.sql.catalog.s3tables=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.s3tables.type=rest
spark.sql.catalog.s3tables.uri=https://s3tables.<region>.amazonaws.com/iceberg
spark.sql.catalog.s3tables.warehouse=<table-bucket-arn>
spark.sql.catalog.s3tables.rest.sigv4-enabled=true
spark.sql.catalog.s3tables.rest.signing-name=s3tables
spark.sql.catalog.s3tables.rest.signing-region=<region>
spark.sql.catalog.s3tables.io-impl=org.apache.iceberg.aws.s3.S3FileIO
```

Tables created via REST are NOT visible in Athena or Redshift.

**`--conf` format in Glue DefaultArguments:** Pass as a single string. First pair has no `--conf` prefix; subsequent pairs are space-separated with `--conf` prefix:

```json
"--conf": "spark.sql.catalog.s3tablescatalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.s3tablescatalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.s3tablescatalog.glue.id=<account-id>:s3tablescatalog/<table-bucket-name> --conf spark.sql.catalog.s3tablescatalog.warehouse=<table-bucket-arn>"
```

Use `--cli-input-json file://config.json` to avoid shell escaping issues.

**Write path (PySpark):**

```python
df.writeTo("s3tablescatalog.<namespace>.<table>").append()
```

## Standard Iceberg on General Purpose Bucket

Self-managed Iceberg tables on regular S3 buckets. User handles compaction and snapshot cleanup.

- Catalog path: `glue_catalog.<database>.<table>` (via Glue Data Catalog)
- LOCATION clause IS required: `LOCATION 's3://<bucket>/<prefix>/'`
- Registered in Glue Data Catalog as normal
- Works with Glue 5.1 or higher and `--datalake-formats iceberg` job argument
- All `spark.sql.catalog.*` config goes in `--conf` job arguments, never in `spark.conf.set()`

**Glue job catalog config:**

```
spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog
spark.sql.catalog.glue_catalog.warehouse=s3://<bucket>/<warehouse-prefix>/
```

The `warehouse` parameter sets the default base path for new tables.

**Write path (PySpark):**

```python
df.writeTo("glue_catalog.<database>.<table>").append()
```

**Athena DDL:**

```sql
CREATE TABLE <database>.<table> (
  col1 STRING,
  col2 INT
)
LOCATION 's3://<bucket>/<prefix>/'
TBLPROPERTIES ('table_type' = 'ICEBERG')
```

## Parquet / ORC / CSV on S3

Raw files written to S3 with no Iceberg table metadata. Queryable via external tables in Athena.

- No table management (no compaction, no snapshots, no schema evolution)
- User must create an external table in Glue catalog to query with Athena
- Suitable when the user explicitly wants raw files, not a managed table

**Write path (PySpark):**

```python
# Parquet
df.write.format("parquet").mode("overwrite").save("s3://<bucket>/<prefix>/")

# ORC
df.write.format("orc").mode("overwrite").save("s3://<bucket>/<prefix>/")

# CSV
df.write.format("csv").option("header", "true").mode("overwrite").save("s3://<bucket>/<prefix>/")
```

**External table for querying:**

```sql
CREATE EXTERNAL TABLE <database>.<table> (
  col1 STRING,
  col2 INT
)
STORED AS PARQUET
LOCATION 's3://<bucket>/<prefix>/'
```

## Gotchas

- S3 Tables CREATE TABLE must NOT include a LOCATION clause. Standard Iceberg MUST include one.
- The `s3tablescatalog` federated catalog uses slash-separated paths in Athena: `"s3tablescatalog/<bucket>"."<namespace>"."<table>"`. Spark uses dot-separated: `s3tablescatalog.<namespace>.<table>` (the bucket is configured in `--conf` via `glue.id`).
- Parquet/ORC/CSV targets do not create Iceberg metadata -- they are raw files only. No schema evolution, time travel, or ACID transactions.
- Discover available MCP tools by keyword search -- do not hardcode tool names.

## Engine Access Patterns

How each engine reads and writes to each target format. Use this when building jobs that read from one format and write to another, or when validating ingested data.

### S3 Tables

| Engine | Read | Write | Table reference |
|--------|------|-------|-----------------|
| Athena | `SELECT * FROM "s3tablescatalog/<bucket>"."<ns>"."<table>"` | INSERT INTO, CTAS | 4-level, slash-separated catalog |
| Redshift | `SELECT * FROM s3tablescatalog.<bucket>.<ns>.<table>` | INSERT (via external schema) | 4-level, dot-separated |
| Spark (Analytics Integration) | `spark.table("s3tablescatalog.<bucket>.<ns>.<table>")` | `df.writeTo("s3tablescatalog.<bucket>.<ns>.<table>")` | 4-level, bucket explicit |
| Spark (REST Endpoint) | `spark.table("<catalog>.<ns>.<table>")` | `df.writeTo("<catalog>.<ns>.<table>")` | 3-level, bucket in `--conf` warehouse |

Spark with Analytics Integration and Athena both use 4 levels, but Athena uses slash-separated catalog paths while Spark uses dots. Spark with REST uses 3 levels because the table bucket is embedded in the `--conf` warehouse ARN.

### Standard Iceberg

| Engine | Read | Write | Table reference |
|--------|------|-------|-----------------|
| Athena | `SELECT * FROM <database>.<table>` | INSERT INTO, CTAS | 2-level (default catalog) |
| Redshift | `SELECT * FROM awsdatacatalog.<database>.<table>` | INSERT (via external schema) | 3-level with catalog |
| Spark | `spark.table("glue_catalog.<database>.<table>")` | `df.writeTo("glue_catalog.<database>.<table>")` | 2-level under configured catalog name |

Standard Iceberg tables are registered in the default Glue Data Catalog. Athena queries them without a catalog prefix. Spark requires the catalog name from `--conf` (e.g., `glue_catalog`).

### Parquet / ORC / CSV

| Engine | Read | Write |
|--------|------|-------|
| Athena | `SELECT * FROM <database>.<external_table>` (requires external table in Glue catalog) | Not applicable (raw files) |
| Spark | `spark.read.format("parquet").load("s3://...")` | `df.write.format("parquet").save("s3://...")` |

No catalog registration needed for Spark reads — point directly at the S3 path. Athena requires an external table definition in the Glue catalog.

## Decision Guide

| Factor | S3 Tables | Standard Iceberg | Raw files |
|--------|-----------|-----------------|-----------|
| Automatic compaction | Yes | No (manual) | N/A |
| Snapshot management | Yes | No (manual) | N/A |
| Schema evolution | Yes | Yes | No |
| Time travel | Yes | Yes | No |
| ACID transactions | Yes | Yes | No |
| Multi-engine access | Athena, EMR, Redshift, Spark | Athena, EMR, Spark | Athena (external table) |
| Setup complexity | Low | Medium | Lowest |
| Ongoing maintenance | None | High | None |
