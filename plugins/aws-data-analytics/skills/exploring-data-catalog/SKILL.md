---
name: exploring-data-catalog
description: >-
  Full inventory and audit of AWS Glue Data Catalog assets across S3 Tables, Redshift-federated,
  and remote Iceberg catalogs. Triggers on: inventory the catalog, audit databases,
  list all tables, catalog overview, data landscape, enumerate catalogs, data inventory,
  search the catalog. Do NOT use for finding specific data (use finding-data-lake-assets),
  running queries (use querying-data-lake), or creating tables (use creating-data-lake-table).
version: 1
argument-hint: '[search-term|catalog-name|database-name|s3://bucket-path|table-name]'
---

Structured inventory and cataloging across your AWS data landscape: Glue Data Catalog with S3 Tables, Redshift-federated, and remote Iceberg catalogs.

## Overview

Maps data in an AWS account. Starts with catalog landscape (Glue, S3 Tables, federated), then drills into databases and tables. Read-only — no query execution.

**Constraints for parameter acquisition:**

- You MUST ask for the target AWS region upfront if not provided
- You MUST support a single optional argument: search term, catalog name, database name, S3 path, or table name
- You MUST accept the argument as direct input or a pointer to a file containing the spec
- You MUST confirm the scope (full landscape vs. targeted deep dive) before making API calls
- You MUST respect the user's decision to abort at any step

## Common Tasks

**Pagination:** All list and search calls in this workflow may return paginated results. You MUST pass `--next-token` from the previous response until no more tokens are returned. You MUST NOT assume a single page contains all results.

### 1. Verify Dependencies

Check for required tools and AWS access before discovery.

**Constraints:**

- You MUST verify AWS MCP server tools are available (`aws___call_aws`, `aws___search_documentation`) and fall back to AWS CLI if not
- You MUST confirm credentials are valid: `aws sts get-caller-identity`
- You MUST inform the user about any missing tools and ask whether to proceed

### 2. Discover Catalogs

List catalogs in account:

```bash
aws glue get-catalogs --recursive --include-root
```

Classify each catalog by type:

| Field Present | Catalog Type | What It Contains |
|---|---|---|
| Neither `TargetRedshiftCatalog` nor `FederatedCatalog` | **Default (Glue)** | Standard Glue databases and tables |
| `FederatedCatalog.ConnectionName` = `aws:s3tables` | **S3 Tables** | Managed Iceberg table buckets |
| `TargetRedshiftCatalog` | **Redshift-federated** | Redshift databases exposed as Glue catalogs |
| `FederatedCatalog` with `ConnectionName` ≠ `aws:s3tables` | **Remote Iceberg** | External catalogs (Snowflake, Databricks, Iceberg REST) |

**Constraints:**

- You MUST include `--include-root` to capture default account catalog
- You MUST present summary of catalog counts by type
- If only default catalog exists, You SHOULD skip catalog overview and go to step 3

### 3. Enumerate Databases and Tables

For each catalog (or the user-specified one):

```bash
aws glue get-databases --catalog-id <catalog-id>
aws glue get-tables --database-name <db> --catalog-id <catalog-id>
```

For S3 Tables catalogs, also enumerate via the S3 Tables API:

```bash
aws s3tables list-table-buckets
aws s3tables list-namespaces --table-bucket-arn <arn>
aws s3tables list-tables --table-bucket-arn <arn> --namespace <ns>
```

**Constraints:**

- You MUST flag S3 Tables not registered in Glue; You SHOULD suggest registration
- For sub-catalogs, `--catalog-id` accepts the catalog name (not the ARN)
- For the default catalog, omit `--catalog-id` or pass the account ID

### 4. Capture Details and Analyze

For each database, capture table count, formats, partitioning, and S3 locations. For each table of interest, capture column schemas, types, partition keys, SerDe format, and last access time.

You MUST report data formats in human-readable terms (Parquet, CSV, JSON), not raw SerDe class names.

See [discovery-checklist.md](references/discovery-checklist.md) for analysis framework.

### Argument Routing

Resolve the argument in this order; stop at the first match:

1. Starts with `s3://` — S3 path (explore unregistered data, detect formats)
2. Matches a known catalog from step 2 (`get-catalogs`) — deep dive into that catalog
3. Matches a known database (`get-databases`) — deep dive into that database
4. Matches a known table (`get-tables`) — detailed table analysis with schema and partitions
5. No match — treat as search term (Glue `search-tables`)
6. No args — full landscape discovery (catalogs, then databases and tables)

### Principles

- Start with catalog landscape, then narrow based on user interest
- Always report catalog types — users need to know where data lives
- Always report data formats — they drive cost and performance decisions
- Flag stale tables and missing descriptions
- Suggest partitioning for large unpartitioned tables
- Summary first, details on request
- You MUST NOT execute Athena queries (`start-query-execution`) during discovery; query execution belongs to `querying-data-lake`

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| Only sub-catalogs returned, default missing | `--include-root` omitted | Re-run `get-catalogs` with `--include-root` |
| Federated catalog query slow or failing | Network call to remote source; connection misconfigured | Report connection errors clearly rather than silently skipping |
| S3 Tables not queryable via Athena | Tables exist in S3 Tables API but not registered in Glue | Flag as "not queryable"; suggest registration |
| `get-databases`/`get-tables` fails with catalog-id | Default catalog requires omit or account ID | Omit `--catalog-id` or pass account ID for the default catalog |

## Additional Resources

- [Discovery checklist](references/discovery-checklist.md)
- [AWS Glue Data Catalog API](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-catalog-databases.html)
- [S3 Tables list operations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-buckets-operations.html)
