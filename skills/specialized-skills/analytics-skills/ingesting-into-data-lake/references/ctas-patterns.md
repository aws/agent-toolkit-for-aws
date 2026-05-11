# Athena CTAS Patterns for S3 Tables Migration

## Basic Migration (no partitions)

```sql
CREATE TABLE "s3tablescatalog/my-bucket"."my_namespace"."customers"
WITH (format = 'PARQUET') AS
SELECT * FROM "awsdatacatalog"."legacy_db"."customers"
```

## Migration with Iceberg Partition Transforms

Convert Hive-style explicit partitions to Iceberg hidden partitions:

```sql
-- Source has explicit year/month/day columns from Hive partitioning
-- Target uses Iceberg day() transform on the timestamp column
CREATE TABLE "s3tablescatalog/my-bucket"."analytics"."events"
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['day(event_timestamp)']
) AS
SELECT
    event_id,
    user_id,
    event_type,
    event_timestamp,
    payload
FROM "awsdatacatalog"."raw_db"."events_hive"
```

## Available Partition Transforms

| Transform | Example | Use when |
|-----------|---------|----------|
| `year(col)` | `ARRAY['year(created_at)']` | Multi-year data, infrequent queries |
| `month(col)` | `ARRAY['month(created_at)']` | Monthly reporting, medium cardinality |
| `day(col)` | `ARRAY['day(event_time)']` | Daily data, time-series workloads |
| `hour(col)` | `ARRAY['hour(event_time)']` | High-volume streaming data |
| `bucket(col, N)` | `ARRAY['bucket(user_id, 16)']` | High-cardinality columns, even distribution |
| Multiple | `ARRAY['month(ts)', 'bucket(id, 8)']` | Compound partitioning |

## Batched Migration (over 100 partitions)

Athena CTAS has a 100-partition limit per statement. Migrate in batches:

```sql
-- Batch 1: 2023 data
CREATE TABLE "s3tablescatalog/my-bucket"."ns"."orders"
WITH (format = 'PARQUET', partitioning = ARRAY['month(order_date)']) AS
SELECT * FROM "awsdatacatalog"."sales"."orders"
WHERE order_date >= DATE '2023-01-01' AND order_date < DATE '2024-01-01'

-- Batch 2+: INSERT INTO for subsequent years
INSERT INTO "s3tablescatalog/my-bucket"."ns"."orders"
SELECT * FROM "awsdatacatalog"."sales"."orders"
WHERE order_date >= DATE '2024-01-01' AND order_date < DATE '2025-01-01'
```

## Migration with Column Transformations

```sql
CREATE TABLE "s3tablescatalog/my-bucket"."clean"."users"
WITH (format = 'PARQUET') AS
SELECT
    user_id,
    LOWER(email) AS email,
    COALESCE(display_name, username) AS name,
    CAST(created_at AS timestamp) AS created_at,
    CASE WHEN status = 'A' THEN 'active' ELSE 'inactive' END AS status
FROM "awsdatacatalog"."legacy"."users_raw"
```

## Cross-Catalog Migration (self-managed Iceberg)

```sql
CREATE TABLE "s3tablescatalog/my-bucket"."analytics"."transactions"
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['day(transaction_date)']
) AS
SELECT * FROM "awsdatacatalog"."iceberg_db"."transactions_selfmanaged"
```

## Format Options

| Format | Best for | Notes |
|--------|----------|-------|
| `PARQUET` (default) | Most analytical workloads | Columnar, good compression, wide tool support |
| `AVRO` | Write-heavy, schema evolution | Row-based, fast writes |
| `ORC` | Hive ecosystem compatibility | Columnar, good for Hive migrations |
