# S3 Tables Best Practices

## Iceberg Type Mapping

For the full list of supported Iceberg data types and their mappings to query engine types, search AWS docs for `"Supported data types for Iceberg tables in Athena"`. Complex types (list, map, struct) require `schemaV2` instead of `schema` in API metadata. Search AWS docs for `"IcebergSchemaV2 S3 Tables"` for the full spec. Example with nested struct:

```json
{"iceberg":{"schemaV2":{"type":"struct","fields":[
  {"id":1,"name":"device_id","required":true,"type":"string"},
  {"id":2,"name":"location","required":false,"type":{
    "type":"struct","fields":[
      {"id":3,"name":"latitude","required":true,"type":"double"},
      {"id":4,"name":"longitude","required":true,"type":"double"}
    ]}}
]}}}
```

Key: top-level must have `"type":"struct"`, all fields need explicit `"id"`, nested struct uses `"type":{"type":"struct","fields":[...]}`.

**Default choices when ambiguous:**

- IDs: use `long` (safer than `int` for growth)
- Text: use `string` (no need to specify length in Iceberg)
- Timestamps: use `timestamp` unless timezone awareness is needed, then `timestamptz`
- Money: use `int` or `long` storing cents/smallest unit to avoid floating-point errors. Use `decimal(p,s)` only when fractional amounts are required.

## Partition Strategy

Choose partitions based on query access patterns, not data structure.

**Time-series** (events, logs, metrics):

- High/medium-volume (≥100K rows/day): `PARTITIONED BY (event_date)` with identity transform
- Low-volume (<100K rows/day): partition by month transform

**Multi-tenant**: `PARTITIONED BY (tenant_id)`, add date if high volume per tenant.

**No clear pattern**: Start without partitions. Iceberg supports adding partitions later without rewriting data.

**Partition guidelines:**

- Use columns with low cardinality (10-10,000 unique values) frequently in WHERE clauses
- Limit to 2-3 partition levels
- Do NOT partition by high-cardinality columns (user_id, transaction_id)
- Aim for partition sizes of 100MB-1GB

## Naming Conventions

All names MUST be lowercase (Glue Data Catalog requirement).

- **Table bucket**: lowercase, numbers, hyphens. 3-63 chars. Name by team/domain (e.g., `analytics-tables`, `marketing-data`)
- **Namespace**: lowercase, underscores. Name by data stage or domain (e.g., `raw_events`, `processed`, `analytics`)
- **Table**: lowercase, underscores. Name by entity (e.g., `customer_orders`, `click_events`)
- **Columns**: lowercase, snake_case. Descriptive names, avoid abbreviations.

## Schema Design

- Use descriptive names that won't need renaming
- Avoid packing JSON strings into single columns -- use Iceberg struct/map/array types
- For schema evolution, see `athena-ddl-path.md`.

## Storage Class

Default is STANDARD. For tables with infrequently accessed historical data, set Intelligent Tiering at bucket creation:

```bash
aws s3tables create-table-bucket --name <NAME> --region <REGION> \
  --storage-class-configuration '{"storageClass":"INTELLIGENT_TIERING"}'
```

Bucket default can be changed with `aws s3tables put-table-bucket-storage-class` (applies to new tables only). Per-table storage class is set at creation via `create-table --storage-class-configuration` and cannot be changed after.

## Common Errors

| Error | Fix |
|-------|-----|
| "Access denied creating table bucket" | Need `s3tables:CreateTableBucket`, `s3tables:ListTableBuckets`. For full workflow see Step 6 in SKILL.md and `references/table-creation-glue-etl.md` for granular permissions. |
| "Namespace not found" | Namespaces must exist before tables. Create with `aws s3tables create-namespace`. |
| Table not visible in Athena | Run `aws glue get-catalog --catalog-id s3tablescatalog`. If missing, follow Step 5 in SKILL.md. If present, check execution context format in `athena-ddl-path.md`. |
| Write operations fail | Verify IAM role has `s3tables:PutTableData` and `s3tables:UpdateTableMetadataLocation`. |
| `AccessDeniedException` despite correct IAM policy | `s3tablescatalog` may be in Lake Formation mode. Check with `aws glue get-catalog --catalog-id s3tablescatalog` — if `CreateDatabaseDefaultPermissions` is empty, the catalog is in LF mode. Migrate with `aws glue update-catalog` using `OverwriteChildResourcePermissionsWithDefault: Accept`. WARNING: this propagates to ALL child resources and removes existing LF grants. You MUST confirm with user. Search AWS docs for `"Change access control from Lake Formation to IAM"`. |
| Shell escaping errors with `--catalog-input` JSON | Save JSON to a file and use `--catalog-input file://catalog-input.json` instead of inline JSON. |
