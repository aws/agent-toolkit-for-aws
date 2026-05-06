# JDBC Database Ingest

Move data from a JDBC source (Oracle, SQL Server, PostgreSQL, MySQL, RDS, Aurora, Redshift) into the data lake. Assumes a Glue connection exists. If it doesn't, delegate to the `connecting-to-data-source` skill first.

## Contents

- [Prerequisites](#prerequisites)
- [Workflow](#workflow)
- [Parallel Reads](#parallel-reads)
- [Type Mapping](#type-mapping)
- [Connection Errors](#connection-errors)

## Prerequisites

- A tested Glue connection (created via `connecting-to-data-source` skill)
- Source table name, schema, and optional filter SQL
- Target table (existing or to be created via `creating-data-lake-table` skill)
- Target format decided (default S3 Tables; see [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md))

## Workflow

### 1. Confirm connection exists

```bash
aws glue get-connection --name <CONNECTION_NAME> --region <REGION>
```

If the connection does not exist, stop and delegate to `connecting-to-data-source`.

### 2. Identify source scope

Ask the user which tables, views, or custom SQL query. See [jdbc-schema-discovery.md](jdbc-schema-discovery.md) for crawler-based discovery, direct schema inspection, and custom SQL patterns.

### 3. Decide load strategy

| Intent | Strategy | Reference |
|---|---|---|
| One-time full load | Full scan, write once | [glue-job-scripts.md](glue-job-scripts.md) full-refresh template |
| Recurring, append-only (events, logs) | Incremental append with watermark | [incremental-loading.md](incremental-loading.md) |
| Recurring, mutable (customers, products) | Incremental upsert with MERGE | [incremental-loading.md](incremental-loading.md) |
| Small dimension | Full refresh via `createOrReplace()` | [glue-job-scripts.md](glue-job-scripts.md) |

### 4. Create target table if needed

If the target table doesn't exist, delegate to `creating-data-lake-table`. Never create it inline.

### 5. Build the Glue 5.1 or higher job

Use the PySpark templates in [glue-job-scripts.md](glue-job-scripts.md) and the job config guidance in [glue-job-config.md](glue-job-config.md).

Reference the Glue connection via job `Connections` property:

```json
"Connections": {"Connections": ["<CONNECTION_NAME>"]}
```

In the script, read via connection name -- no credentials in code:

```python
source_df = glueContext.create_dynamic_frame.from_options(
    connection_type="jdbc",
    connection_options={
        "useConnectionProperties": "true",
        "connectionName": args['connection_name'],
        "dbtable": args['source_table']
    }
).toDF()
```

### 6. Test, validate, schedule

- Run the job manually once
- Validate per [data-quality-validation.md](data-quality-validation.md): row counts, null checks on critical columns, spot-check samples
- For recurring pipelines, create a Glue Trigger per [testing-and-scheduling.md](testing-and-scheduling.md)

## Parallel Reads

For large tables, read in parallel via Spark partitioning on a numeric column:

```python
jdbc_conf = glueContext.extract_jdbc_conf(args['connection_name'])

source_df = spark.read.format("jdbc").options(
    url=jdbc_conf["url"],
    user=jdbc_conf["user"],
    password=jdbc_conf["password"],
    dbtable="<SCHEMA>.<TABLE>",
    numPartitions=10,
    partitionColumn="<numeric_column>",
    lowerBound=1,
    upperBound="<max_value>"
).load()
```

Best practices:

- Use a numeric column with even distribution for `partitionColumn`
- Set `numPartitions` = number of Glue workers × 2
- Ensure `lowerBound`/`upperBound` cover actual data range
- Source database must handle concurrent connections

Retrieve credentials from the connection at runtime rather than hardcoding. See [connecting-to-data-source credential-security.md](../../connecting-to-data-source/references/credential-security.md) for IAM DB auth and Secrets Manager patterns.

## Type Mapping

Source-to-Iceberg type mappings for ingest. Apply via `.cast()` or column aliases in the Glue script.

### Oracle

| Oracle | Iceberg | Notes |
|---|---|---|
| VARCHAR2, CHAR | STRING | |
| NUMBER(p,s) | DECIMAL(p,s) | |
| NUMBER (no scale) | BIGINT | For integer values |
| DATE | TIMESTAMP | Oracle DATE includes time |
| TIMESTAMP | TIMESTAMP | |
| CLOB | STRING | |
| BLOB | BINARY | |

### SQL Server

| SQL Server | Iceberg | Notes |
|---|---|---|
| VARCHAR, NVARCHAR, CHAR | STRING | |
| INT, SMALLINT | INTEGER | |
| BIGINT | BIGINT | |
| DECIMAL, NUMERIC | DECIMAL(p,s) | |
| FLOAT, REAL | DOUBLE | |
| BIT | BOOLEAN | |
| DATE | DATE | |
| DATETIME, DATETIME2 | TIMESTAMP | |

### PostgreSQL

| PostgreSQL | Iceberg | Notes |
|---|---|---|
| VARCHAR, TEXT | STRING | |
| INTEGER, SMALLINT | INTEGER | |
| BIGINT | BIGINT | |
| NUMERIC, DECIMAL | DECIMAL(p,s) | |
| REAL | FLOAT | |
| DOUBLE PRECISION | DOUBLE | |
| BOOLEAN | BOOLEAN | |
| DATE | DATE | |
| TIMESTAMP, TIMESTAMPTZ | TIMESTAMP | |
| JSON, JSONB | STRING | Parse in Spark if needed |
| UUID | STRING | |

### MySQL

| MySQL | Iceberg | Notes |
|---|---|---|
| VARCHAR, CHAR, TEXT | STRING | |
| INT, SMALLINT, TINYINT | INTEGER | TINYINT(1) is BOOLEAN |
| BIGINT | BIGINT | |
| DECIMAL | DECIMAL(p,s) | |
| FLOAT | FLOAT | |
| DOUBLE | DOUBLE | |
| DATE | DATE | |
| DATETIME, TIMESTAMP | TIMESTAMP | |
| JSON | STRING | |

### Redshift

Same as PostgreSQL mappings. Redshift-specific additions:

- `SUPER` -> STRING (serialize) or STRUCT (parse)
- `GEOMETRY` / `GEOGRAPHY` -> BINARY or STRING

## Connection Errors

If the Glue job fails with a connection-related error (timeout, auth failure, driver not found, SSL handshake), delegate to `connecting-to-data-source` for troubleshooting. Do not attempt network or credential fixes in this skill.

See [connecting-to-data-source troubleshooting.md](../../connecting-to-data-source/references/troubleshooting.md).
