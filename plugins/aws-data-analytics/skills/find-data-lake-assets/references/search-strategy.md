# Search Strategy

## Layer Priority and Stop Conditions

Layers are searched in order. Stop searching when a stop condition is met.

| Layer | Source | Best for | Stop condition |
|-------|--------|----------|----------------|
| 1 | Glue Data Catalog | Technical names, columns, keywords | Exact name match (1 result) |
| 2 | S3 Reverse Lookup or Prefix | S3 path to Glue, or uncataloged data | Files or catalog entry found |
| 3 | Redshift Catalog | Warehouse/lakehouse tables | Table found in svv_all_tables |

## Glue Search Patterns

`search-tables` is the default. It searches across all databases and matches
against table names, column names, column comments, and other metadata.

```
# Find tables by name, keyword, or business domain
aws glue search-tables --search-text "orders"
aws glue search-tables --search-text "billing"

# Find tables containing a specific column
aws glue search-tables --search-text "customer_id"

# Find tables pointing to an S3 path fragment (reverse lookup)
aws glue search-tables --search-text "clickstream/events"

# Filtered search (e.g., by owner or parameters)
aws glue search-tables \
  --search-text "orders" \
  --filters '[{"Key":"Parameters.classification","Value":"parquet"}]'
```

Use `get-tables` only when the database is already known:

```
# Exact name within a known database
aws glue get-tables --database-name sales --expression "orders"

# Prefix match within a known database (Expression is a regex, not a glob)
aws glue get-tables --database-name sales --expression "order.*"
```

## S3 Reverse Lookup

When a user provides an S3 path, they usually want to know the catalog entry,
not the file contents. Use `search-tables` with a path fragment first.

```
# User says: what's at s3://my-bucket/data/clickstream/?
# Step 1: reverse lookup in Glue
aws glue search-tables --search-text "clickstream"

# Step 2: verify by checking StorageDescriptor.Location on candidates
aws glue get-table --database-name <db> --name <table> \
  --query 'Table.StorageDescriptor.Location'

# Only fall back to listing objects if no catalog match:
aws s3 list-objects-v2 --bucket my-bucket --prefix data/clickstream/
```

## Redshift Search Patterns

```sql
-- All tables (native + Spectrum external)
SELECT schema_name, table_name, table_type
FROM svv_all_tables
WHERE table_name ILIKE '%orders%';

-- Spectrum external tables only
SELECT schemaname, tablename
FROM svv_external_tables
WHERE tablename ILIKE '%orders%';

-- Column search
SELECT schema_name, table_name, column_name
FROM svv_all_columns
WHERE column_name = 'customer_id';
```

Redshift Spectrum external tables are also registered in Glue. If Layer 1
already found the table in Glue with a Spectrum SerDe, skip Layer 4.

## S3 Tables Naming Hierarchy

S3 Tables use 4 levels instead of the standard Glue 2-level database.table. The correct order is catalog / table-bucket / namespace / table.

| Level | Glue standard | S3 Tables |
|-------|---------------|-----------|
| 1 | (catalog, usually default) | catalog: `s3tablescatalog/<bucket>` |
| 2 | database | table-bucket (inside the catalog string) |
| 3 | table | namespace |
| 4 | (none) | table |

Example references:

```
# Glue standard (2-level)
sales.orders

# S3 Tables (4-level, qualified for SQL)
"s3tablescatalog/analytics-bucket"."events"."clickstream"

# S3 Tables in ARN form
arn:aws:s3tables:us-east-1:123456789012:bucket/analytics-bucket/table/<uuid>
```

## Confidence Scoring

| Signal | Score | Example |
|--------|-------|---------|
| Exact table name match | High | "orders table", found `sales.orders` |
| Single fuzzy match | High | "order data", only `sales.orders` matches |
| Database + partial name | High | "sales orders", found `sales.orders` |
| Multiple name matches | Medium | "orders" matches `sales.orders` and `legacy.orders` |
| Column name match only | Medium | "customer_id" found in 3 tables |
| No direct match, prefix exists in S3 | Low | S3 path has data but no catalog entry |
| No matches anywhere | None | Suggest exploring-data-catalog or refine query |

## Disambiguation

When multiple candidates match (medium confidence):

1. Prefer tables in the default Glue catalog over federated catalogs
2. Prefer Iceberg/Parquet tables over CSV/JSON (more likely production)
3. Prefer tables with recent partitions over stale tables
4. Prefer tables with descriptions over undocumented tables
5. Present top 3 with: name, format, last partition date, match reason
