# Creating Tables via Athena DDL

Alternative to the S3 Tables API. Use when the user specifically wants SQL DDL or needs schema evolution via ALTER TABLE after creation.

## Prerequisites

- Glue catalog (`s3tablescatalog`) MUST be registered (see Step 5 in SKILL.md)
- Athena workgroup MUST use engine version 3 (required for Iceberg support)
- Output S3 bucket MUST exist in the same region as the table bucket for Athena query results. If Athena has never been used in this region, the user MUST first configure a query result location in the Athena workgroup settings or via `--result-configuration` on each query.

## CREATE TABLE

The catalog reference goes in `--query-execution-context`, NOT in the SQL statement. Use `<database>.<table>` format in SQL:

```sql
CREATE TABLE <namespace>.<table_name> (
  <column_definitions>
)
PARTITIONED BY (<partition_columns>)
TBLPROPERTIES ('table_type' = 'ICEBERG')
```

**CRITICAL: Do NOT include a LOCATION clause.** S3 Tables manages storage automatically. This differs from regular Athena external tables.

**CRITICAL: Do NOT put the catalog name in the SQL.** Athena cannot parse `s3tablescatalog/<bucket>` as a catalog identifier in DDL. It goes in the execution context only.

## Execute via Athena

```bash
aws athena start-query-execution \
  --query-string "<DDL>" \
  --query-execution-context '{"Catalog": "s3tablescatalog/<BUCKET_NAME>", "Database": "<NAMESPACE>"}' \
  --work-group "<WORKGROUP>" \
  --result-configuration '{"OutputLocation": "s3://<RESULTS_BUCKET>/output/"}'
```

Check status with `aws athena get-query-execution --query-execution-id <ID>`.

The results bucket MUST be in the same region as the table bucket.

## Querying

Use the same execution context pattern for SELECT queries:

```bash
aws athena start-query-execution \
  --query-string "SELECT * FROM <namespace>.<table_name> LIMIT 10" \
  --query-execution-context '{"Catalog": "s3tablescatalog/<BUCKET_NAME>", "Database": "<NAMESPACE>"}' \
  --work-group "<WORKGROUP>" \
  --result-configuration '{"OutputLocation": "s3://<RESULTS_BUCKET>/output/"}'
```

## Constraints

- All table and column names MUST be lowercase
- You MUST NOT include a LOCATION clause
- You MUST NOT put catalog name in the SQL -- use execution context
- Output S3 bucket MUST be in the same region
- The querying principal needs `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` plus S3 access to the results bucket. Also requires S3 Tables and Glue permissions — see `access-control.md`.

## Schema Evolution

ALTER TABLE uses the same `--query-execution-context` pattern:

```bash
aws athena start-query-execution \
  --query-string "ALTER TABLE <namespace>.<table_name> ADD COLUMNS (<col> <type>)" \
  --query-execution-context '{"Catalog": "s3tablescatalog/<BUCKET_NAME>", "Database": "<NAMESPACE>"}' \
  --work-group "<WORKGROUP>" \
  --result-configuration '{"OutputLocation": "s3://<RESULTS_BUCKET>/output/"}'
```

Supported operations: `ALTER TABLE ADD COLUMNS`, `ALTER TABLE DROP COLUMN`. WARNING: schema changes affect all future queries. You MUST confirm with the user before executing.

**Alternative**: Schema evolution is also supported via the S3 Tables Iceberg REST API or the S3 Tables Catalog for Apache Iceberg (open-source). Search AWS docs for `"S3 Tables Catalog for Apache Iceberg"` for setup.

## Additional Resources

For latest Athena DDL syntax, search AWS docs for `"Creating Iceberg tables in Athena"` and `"Supported data types for Iceberg tables in Athena"`.
