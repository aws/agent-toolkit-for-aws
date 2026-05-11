# Migration Troubleshooting

Common issues when migrating Glue Data Catalog tables to S3 Tables.

## CTAS Errors

| Problem | Cause | Fix |
|---------|-------|-----|
| `GENERIC_INTERNAL_ERROR: Invalid table or column names` | Uppercase in table or column names | Lowercase all names in the CTAS SELECT and table name |
| CTAS times out | Table too large for single Athena query | Use Glue ETL (Path B) or migrate in partitioned batches |
| `LOCATION is not supported` | Included LOCATION clause in CTAS | Remove LOCATION -- S3 Tables manages storage automatically |
| `SYNTAX_ERROR: line X:Y: mismatched input` | Malformed partition transform or missing quotes | Check `partitioning = ARRAY[...]` syntax and quote the catalog path |
| `TABLE_NOT_FOUND` on source | Wrong catalog prefix for source table | Use `awsdatacatalog` as the source catalog for standard Glue tables |

## Validation Failures

| Problem | Cause | Fix |
|---------|-------|-----|
| Row count mismatch | WHERE filter excluded rows, or source has duplicates | Check filter clause; run dedup analysis on source |
| Schema mismatch (extra/missing columns) | SELECT * picked up partition columns or metadata | Explicitly list columns in SELECT |
| Null count differs | Type coercion converted empty strings to nulls | Check source data for empty strings vs actual nulls |
| Boundary values differ | Timezone or precision differences | Compare with explicit CAST to same type |

## Visibility Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Target table not visible in Athena | Analytics integration not enabled | Create `s3tablescatalog` federated catalog. See [ctas-patterns.md](ctas-patterns.md) for catalog path syntax. |
| Table visible but returns no data | CTAS succeeded but wrote zero rows | Check WHERE filter; verify source table has data |
| Table visible but columns show as `_col0`, `_col1` | Used SELECT * with incompatible source format | Explicitly name columns with aliases |

## Partition Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| CTAS fails with too many partitions | Over 100 target partitions in single CTAS | Batch with WHERE filters or use coarser partition transform (e.g., `month()` instead of `day()`) |
| Partition column missing in target | Iceberg hidden partitions derive from source column | The source column must be in the SELECT; the transform is in `partitioning` |
| Uneven partition sizes | Poor transform choice for data distribution | Consider `bucket()` for high-cardinality columns |

## Glue ETL Issues

See [glue-etl-migration.md](glue-etl-migration.md#troubleshooting) for Glue-specific errors.
