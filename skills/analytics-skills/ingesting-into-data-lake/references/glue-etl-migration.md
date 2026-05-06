# Glue ETL Migration for Large Tables

Use Glue ETL (Path B) when Athena CTAS would time out, when transforms are complex, or when the migration needs to be scheduled/repeatable.

## When to Use

- Source table over ~100 GB
- Complex column transformations that benefit from PySpark
- Migration needs to be scheduled or repeatable
- Source has more than 100 target partitions and batching is impractical

## Job Setup

### Requirements

- Glue 5.1 or higher (Spark 3.5.6, Iceberg 1.10.0)
- `--datalake-formats iceberg` job argument
- Catalog config in `--conf` job argument (not `spark.conf.set()`). See [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md) for the exact keys.
- IAM role with S3 Tables, Glue, and S3 permissions

### Job Configuration (JSON)

Use `--cli-input-json` to avoid shell escaping issues:

> **Glue --conf format**: In Glue `DefaultArguments`, multiple Spark configs must be passed as a single `--conf` value with space-separated `--conf key=value` pairs. Do not split them into separate JSON keys — Glue only reads one `--conf` key.

```json
{
    "Name": "migrate-to-s3tables",
    "Role": "arn:aws:iam::<account-id>:role/<glue-role>",
    "Command": {
        "Name": "glueetl",
        "ScriptLocation": "s3://<scripts-bucket>/scripts/migrate.py",
        "PythonVersion": "3"
    },
    "DefaultArguments": {
        "--datalake-formats": "iceberg",
        "--enable-glue-datacatalog": "true",
        "--conf": "<see iceberg-catalog-config-and-usage.md for S3 Tables Analytics Integration or REST config>"
    },
    "GlueVersion": "5.1",
    "NumberOfWorkers": 10,
    "WorkerType": "G.1X"
}
```

```bash
aws glue create-job --cli-input-json file://job-config.json --region <region>
```

Scale `NumberOfWorkers` based on source size: ~2 workers per 50 GB as a starting point.

## PySpark Migration Script

```python
import sys
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job

args = getResolvedOptions(sys.argv, [
    'JOB_NAME', 'source_database', 'source_table',
    'target_namespace', 'target_table'
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read from source (Glue Data Catalog)
source_df = spark.read.table(
    f"glue_catalog.{args['source_database']}.{args['source_table']}"
)

# Apply transforms (customize as needed)
# Example: lowercase column names for S3 Tables compatibility
for col_name in source_df.columns:
    if col_name != col_name.lower():
        source_df = source_df.withColumnRenamed(col_name, col_name.lower())

# Write to S3 Table
target_table = f"s3tablescatalog.{args['target_namespace']}.{args['target_table']}"

source_df.writeTo(target_table) \
    .tableProperty("format-version", "2") \
    .createOrReplace()

# Verify row count
source_count = spark.read.table(
    f"glue_catalog.{args['source_database']}.{args['source_table']}"
).count()
target_count = spark.read.table(target_table).count()
print(f"Source rows: {source_count}, Target rows: {target_count}")

job.commit()
```

## Key Points

- All catalog config goes in `--conf` job argument, never in `spark.conf.set()`. See [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md) for the exact keys.
- No `LOCATION` clause -- S3 Tables manages storage
- Column names must be all lowercase for Athena visibility
- `createOrReplace()` handles both cases: creates the table if absent, replaces it if present (safe for re-runs)
- For partitioned writes, add `.partitionedBy()` before `.createOrReplace()`

## Running and Monitoring

```bash
# Start the job
JOB_RUN_ID=$(aws glue start-job-run \
  --job-name "migrate-to-s3tables" \
  --arguments '{"--source_database":"legacy_db","--source_table":"orders","--target_namespace":"analytics","--target_table":"orders"}' \
  --query 'JobRunId' --output text)

# Check status
aws glue get-job-run --job-name "migrate-to-s3tables" --run-id "$JOB_RUN_ID"
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "Cannot modify static config" | Catalog config in `spark.conf.set()` | Move all catalog config to `--conf` job argument |
| "Access Denied" on S3 Tables | Missing IAM permissions | Add `AmazonS3TablesFullAccess` to Glue role |
| Job runs out of memory | Too few workers for data size | Increase `NumberOfWorkers` or use `G.2X` worker type |
| Table not visible in Athena after Glue job | Used REST endpoint instead of analytics integration | Use the GlueCatalog method with `glue.id` config |
