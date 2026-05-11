# Discovery Checklist

## Output Structure

Present findings in this order:

1. Catalog Landscape: catalog count by type (Glue, S3 Tables, Redshift-federated, Remote Iceberg), connection status for federated catalogs
2. Executive Summary: total databases, total tables, primary formats, estimated volume
3. Database Inventory: organized by catalog and database with table counts
4. Unregistered Assets: S3 Tables not in Glue (not queryable via Athena), with registration instructions
5. Schema Analysis: data types, nullable fields, key patterns
6. Storage Analysis: formats, partitioning strategies, S3 locations
7. Recommendations: optimization opportunities, quality issues, missing metadata, unregistered tables to register

## Column Classification

Categorize each column as one of:

- **Identifier**: Unique keys, foreign keys, entity IDs
- **Dimension**: Categorical attributes for grouping/filtering (status, type, region)
- **Metric**: Quantitative values for measurement (revenue, count, duration)
- **Temporal**: Dates and timestamps (created_at, updated_at, event_date)
- **Text**: Free-form text fields (description, notes)
- **Boolean**: True/false flags
- **Structural**: JSON, arrays, nested structures (common in Glue tables from JSON sources)

## Quality Scoring

Rate each column's completeness:

- **Complete** (>99% non-null): reliable for analysis
- **Mostly complete** (95-99%): investigate the nulls before using in calculations
- **Incomplete** (80-95%): understand why, may need imputation or filtering
- **Sparse** (<80%): likely not usable without significant cleanup

## Column Profiling (when deep-diving a table)

For numeric columns: min, max, mean, median, p5, p95, zero count, negative count
For string columns: min/max length, empty string count, distinct values, pattern consistency
For date columns: min/max date, null dates, future dates (if unexpected), gap detection
For boolean columns: true/false/null distribution

## What to Flag

- Tables with no partition keys on datasets > 1GB
- CSV tables that should be Parquet (cost and performance)
- Databases or tables with no descriptions
- Tables with no recent data (stale/abandoned)
- Inconsistent naming conventions across databases
- Tables with high null percentages in key columns
- Columns that appear to be foreign keys (potential join targets)
- Hierarchical dimensions (country > state > city)
- Columns with suspiciously low cardinality (possible default values)
- S3 Tables not registered in Glue (exist but not queryable via Athena)
- Federated catalogs with connection errors or stale metadata

## Format Detection

Map SerDe libraries to human-readable format names:

- `org.apache.hadoop.hive.ql.io.parquet` = Parquet
- `org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe` = CSV/TSV
- `org.openx.data.jsonserde.JsonSerDe` = JSON
- `org.apache.hadoop.hive.serde2.OpenCSVSerde` = CSV
- `org.apache.hadoop.hive.ql.io.orc` = ORC
