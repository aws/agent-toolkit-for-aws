# Snowflake Ingest

Move data from Snowflake into the data lake. Assumes a Glue `SNOWFLAKE` connection exists. If not, delegate to `connecting-to-data-source`.

## Contents

- [Prerequisites](#prerequisites)
- [Read Pattern](#read-pattern)
- [Incremental Loading](#incremental-loading)
- [Partition Pruning](#partition-pruning)
- [Type Mapping](#type-mapping)
- [Further Reading](#further-reading)

## Prerequisites

- Glue connection of type `SNOWFLAKE` (not JDBC)
- Source database, schema, table, and optional query
- Target table in data lake
- Warehouse sized for the read workload (larger warehouse = faster read, more cost)

## Read Pattern

The Glue Snowflake connector reads via Snowflake's COPY INTO mechanism under the hood -- efficient for large extracts.

```python
snowflake_df = glueContext.create_dynamic_frame.from_options(
    connection_type="snowflake",
    connection_options={
        "connectionName": args['connection_name'],
        "sfDatabase": args['database'],
        "sfSchema": args['schema'],
        "dbtable": args['table']
    }
).toDF()
```

For custom SQL, use `query` instead of `dbtable`:

```python
connection_options={
    "connectionName": args['connection_name'],
    "query": "SELECT id, name, updated_at FROM SALES.ORDERS WHERE status = 'CLOSED'"
}
```

## Incremental Loading

Snowflake has reliable timestamps on most tables. Common watermark columns:

- Application-maintained `updated_at` / `modified_at`
- Snowflake-maintained `_FIVETRAN_SYNCED` if sourced via Fivetran
- `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` for schema-level freshness (not row-level)

For tables without an `updated_at`, options:

- Query `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` or `TABLE_STORAGE_METRICS` to identify changed tables for full refresh scheduling
- Use Snowflake Streams to capture CDC (advanced; requires Snowflake-side setup -- see [Snowflake Streams docs](https://docs.snowflake.com/en/user-guide/streams-intro))

Standard watermark filter in the custom query:

```python
connection_options={
    "connectionName": args['connection_name'],
    "query": f"SELECT * FROM {source_table} WHERE updated_at > '{last_watermark}'"
}
```

See [incremental-loading.md](incremental-loading.md) for watermark storage and the broader incremental pattern.

## Partition Pruning

Snowflake tables are automatically micro-partitioned. Push down filters via the `query` option -- do not pull full tables and filter in Spark.

Clustered tables benefit most from filter push-down. Check cluster keys:

```sql
SHOW TABLES LIKE '<table>' IN SCHEMA <db>.<schema>;
-- Look at CLUSTER_BY column
```

If the source table is clustered on `created_date` and you filter on `created_date >= '2026-01-01'`, Snowflake prunes micro-partitions and returns only relevant data.

## Type Mapping

| Snowflake | Iceberg | Notes |
|---|---|---|
| VARCHAR, STRING, TEXT | STRING | |
| NUMBER(p,s) | DECIMAL(p,s) | |
| NUMBER (no scale) | BIGINT | |
| FLOAT, DOUBLE | DOUBLE | |
| BOOLEAN | BOOLEAN | |
| DATE | DATE | |
| TIME | STRING | Iceberg has no TIME type |
| TIMESTAMP_NTZ | TIMESTAMP | Naive timestamp |
| TIMESTAMP_LTZ, TIMESTAMP_TZ | TIMESTAMPTZ | Timezone-aware |
| VARIANT | STRING | Serialize as JSON |
| OBJECT | STRUCT or STRING | Flatten or serialize |
| ARRAY | ARRAY or STRING | |
| BINARY | BINARY | |
| GEOGRAPHY, GEOMETRY | STRING | GeoJSON or WKT |

## Further Reading

- [AWS Glue: Snowflake connections (programming)](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-connect-snowflake-home.html)
- [Snowflake Streams for CDC](https://docs.snowflake.com/en/user-guide/streams-intro)
- [Snowflake query profile and clustering](https://docs.snowflake.com/en/user-guide/ui-query-profile)
