---
name: finding-data-lake-assets
description: >-
  Resolve data lake and lakehouse asset references across Glue Data Catalog, S3, S3
  Tables, and Redshift. Triggers on: find the table, where is our data, which table
  has, locate dataset, find data for, search catalog, what tables match, Redshift
  table, lakehouse table, data lake table, warehouse table, reverse lookup S3 path.
  Do NOT use for: full catalog audits (use exploring-data-catalog), running queries
  (use querying-data-lake), creating tables (use creating-data-lake-table).
version: 1
metadata:
  service: [glue, s3, s3tables, redshift]
  task: [debug]
  persona: [developer, data-engineer, architect]
  workload: [data-analytics]
argument-hint: '[table-name|keyword|column-name|s3://path]'
---

# Find Data Lake Assets

## Overview

Resolves data lake asset references to concrete catalog entries. Acts as a
resolver for other skills and direct user requests. Covers Glue,
S3, S3 Tables, and Redshift. Optimized for low token usage — return the
answer fast and get out of the way.

**Constraints for parameter acquisition:**

- You MUST accept a single argument: table name, keyword, column name, or S3 path
- You MUST accept the argument as direct input or a pointer to a file containing the spec
- You MUST ask for the target AWS region if not already set
- You MUST confirm ambiguous input before searching (e.g., "Did you mean table X or bucket Y?")
- You MUST respect the user's decision to abort at any step

## Common Tasks

You MUST execute commands using AWS MCP server tools when connected — they
provide validation, sandboxed execution, and audit logging. Fall back to
AWS CLI only if MCP is unavailable. You MUST explain each step before
executing.

### 1. Verify Dependencies

Check for required tools and AWS access before searching.

**Constraints:**

- You MUST verify AWS MCP server tools (`aws___call_aws`) are available; fall back to AWS CLI if not
- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST inform the user about any missing tools and ask whether to proceed

### 2. Classify the Request

Determine the mode:

- **Resolve** (most common): User/skill references something specific.
  Signals: possessive/definite articles ("our X table", "the Y
  dataset") imply the asset exists. Goal: find it, return the
  reference, done.
- **Search**: User is exploring. Signals: "find tables with", "what
  has customer_id". Goal: rank candidates, present top matches.

You SHOULD default to Resolve mode when ambiguous.

### 3. Extract Search Terms

Parse the request into search dimensions:

- **Name terms**: Table or database names mentioned
- **Domain terms**: Business concepts (billing, orders, churn)
- **Column terms**: Specific column names (customer_id, event_type)
- **Location terms**: S3 paths, bucket names, prefixes

### 4. Layered Search (stop early)

Search sources in order. Stop at the first layer that returns a
high-confidence match. Do NOT search all layers every time.

You MUST track which layers were searched and which were skipped.
Report this in the output (see Step 6).

**Layer 1: Glue Data Catalog** (always start here)

You SHOULD use `SearchTables` as the primary API — it searches table
names, column names, and column comments across the entire catalog in
one call. You MUST NOT loop over databases with `get-tables` unless
you already know the database name. See
[search-strategy.md](references/search-strategy.md) for patterns.

```
aws glue search-tables --search-text "orders"
aws glue get-tables --database-name sales --expression "order.*"
```

**Layer 2: S3 Reverse Lookup** (S3 path provided)

When a user provides an S3 path, you SHOULD default to reverse lookup first —
they usually want the Glue table, not the file contents.

```
aws glue search-tables --search-text "<path-keyword>"
aws s3api list-objects-v2 --bucket <bucket-name> --prefix <prefix>
```

**Layer 3: Redshift Catalog** (if user mentions Redshift, warehouse, or lakehouse)

```sql
SELECT schema_name, table_name, table_type
FROM svv_all_tables
WHERE table_name ILIKE '%orders%';
```

Redshift Spectrum external tables also appear in Glue. If Layer 1
found the table with a Spectrum SerDe, skip Layer 3.

### 4b. Broad Scan Fallback (single turn)

When `search-tables` returns nothing and S3 Tables enumeration also
misses, you MAY need to scan across databases. Do NOT issue separate
CLI calls per database — that burns turns and tokens. Instead, write a
short Python script using boto3 paginators that does the full scan in
one execution. Write the script to a file and run it with `python3`.

The script MUST:

- Paginate `get_databases()` to collect all database names
- For each database, paginate `get_tables()` with an `Expression`
  filter matching the search term
- Print only matching results as structured output (JSON or table)
- Accept the region and search term as arguments or variables

```python
import boto3, sys, json

region = sys.argv[1]
term = sys.argv[2]

glue = boto3.client("glue", region_name=region)
matches = []

db_paginator = glue.get_paginator("get_databases")
for db_page in db_paginator.paginate():
    for db in db_page["DatabaseList"]:
        db_name = db["Name"]
        tbl_paginator = glue.get_paginator("get_tables")
        for tbl_page in tbl_paginator.paginate(
            DatabaseName=db_name, Expression=f".*{term}.*"
        ):
            for tbl in tbl_page["TableList"]:
                matches.append({
                    "database": db_name,
                    "table": tbl["Name"],
                    "format": tbl.get("Parameters", {}).get("classification", "unknown"),
                    "location": tbl.get("StorageDescriptor", {}).get("Location", ""),
                })

print(json.dumps(matches, indent=2) if matches else "No matches found.")
```

You MUST only use this fallback after `search-tables` and S3 Tables
enumeration have already returned nothing. This is a last resort, not
a first choice.

### 5. Apply the Confidence Gate

- **High confidence** (exact name match, single result): Return the resolved
  reference immediately. No summary, no options.
- **Medium confidence** (fuzzy match, 2-3 results): Present top matches with
  one line each: name, why it matched, format. Let the user pick.
- **Low confidence** (many weak matches or none): Report what was searched
  and what was skipped, suggest refining the query or running
  `exploring-data-catalog`.

### 6. Return the Reference

For high-confidence resolve, return a structured reference. Always
include a "Sources searched / skipped" line so the user knows which
data stores were checked and which were not.

```
Table: database_name.table_name
Catalog: default | catalog_name
Format: Parquet | CSV | JSON | ORC | Iceberg
Location: s3://bucket/prefix/
Partition keys: [key1, key2] or none
Sources searched: Glue Data Catalog
Sources skipped: S3, Redshift (stopped early — high-confidence match in Glue)
```

S3 Tables use a 4-level hierarchy (catalog / table-bucket / namespace /
table), and `search-tables` does not index `s3tablescatalog/*`. If the
user mentions S3 Tables explicitly or Layer 1 returns nothing for an
expected S3 Tables asset, enumerate via `aws s3tables list-table-buckets`
and `list-namespaces`. Return as:

```
Table: s3tablescatalog/<table-bucket>/<namespace>/<table>
Format: Iceberg
Location: arn:aws:s3tables:<region>:<account>:bucket/<table-bucket>/table/<table-uuid>
Sources searched: Glue Data Catalog, S3 Tables
Sources skipped: Redshift (not relevant to S3 Tables lookup)
```

SQL reference: `"s3tablescatalog/<table-bucket>"."<namespace>"."<table>"`.

You MUST always include both "Sources searched" and "Sources skipped"
in the output. List the reason for skipping in parentheses. Valid
reasons: "stopped early", "not relevant to this request", "access
denied", "no results in prior layer".

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `get-tables` fails with missing database | Requires `--database-name` | For cross-database search, use `search-tables` instead |
| `search-tables` returns nothing for S3 Tables | Does not cover S3 Tables federated catalogs | Use `aws s3tables list-table-buckets` when S3 Tables is in play |
| `AccessDeniedException` on `search-tables` | Caller lacks `glue:SearchTables` permission | Request the permission or fall back to Glue `get-tables` with a known database |
| API call times out or throttles (`ThrottlingException`) | Throttled by service-level rate limits | Retry with exponential backoff; reduce parallel calls |
| Resource not in expected region | Cross-region lookup | Confirm AWS region; the Glue catalog is region-scoped |
| Delegating caller expects verbose output | Other skill called this as a resolver | Return minimal output — caller needs a catalog reference, not a formatted summary |

## Principles

- You MUST prefer `search-tables` over iterating databases. One API call beats N.
- You MUST pass an `Expression` filter when calling `get-tables`; never call it without one.
- You MUST NOT issue separate CLI calls per database. If a broad scan is needed, use the boto3 paginator script from Step 4b to do it in a single turn.
- You SHOULD resolve fast and stop early. Every extra API call costs tokens.
- You SHOULD assume the asset exists in Resolve mode — search to find it, not to confirm it.

## Additional Resources

- [Search strategy details](references/search-strategy.md)
- [AWS Glue SearchTables API](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-catalog-tables.html#aws-glue-api-catalog-tables-SearchTables)
- [S3 Tables overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html)
- [S3 Metadata tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/metadata-tables-overview.html)
