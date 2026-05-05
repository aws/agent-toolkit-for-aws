# Glue Job Configuration Guide

Guide for creating Glue jobs, configuring workers, advanced PySpark patterns, and monitoring for external data import pipelines.

## Creating the Glue Job

Once you have the PySpark script saved to S3 (e.g., `s3://<scripts-bucket>/glue-jobs/external-import-<table-name>.py`), create the Glue job.

### AWS CLI

```bash
aws glue create-job \
  --name "external-import-<source>-<table>" \
  --role "<glue-role-arn>" \
  --command "Name=glueetl,ScriptLocation=s3://<scripts-bucket>/glue-jobs/external-import-<table>.py,PythonVersion=3" \
  --connections "Connections=<glue-connection-name>" \
  --default-arguments '{
    "--datalake-formats": "iceberg",
    "--connection_name": "<glue-connection-name>",
    "--source_table": "<schema>.<table>",
    "--target_table": "<catalog>.<namespace>.<s3-table>",
    "--watermark_column": "<timestamp-column>",
    "--watermark_bucket": "<bucket>",
    "--watermark_key": "watermarks/<table-name>.txt",
    "--conf": "<see iceberg-catalog-config-and-usage.md for S3 Tables or standard Iceberg catalog config>",
    "--enable-glue-datacatalog": "true",
    "--enable-metrics": "true",
    "--enable-continuous-cloudwatch-log": "true"
  }' \
  --glue-version "5.1" \
  --number-of-workers 5 \
  --worker-type "G.1X" \
  --timeout 60 \
  --max-retries 1 \
  --region <region>
```

## Job Configuration Parameters

### Worker Types and Sizing

Choose worker type based on workload characteristics:

| Worker Type | vCPUs | Memory | Use Case |
|-------------|-------|--------|----------|
| G.1X | 4 | 16 GB | Standard ETL, small to medium data volumes |
| G.2X | 8 | 32 GB | Large data volumes, memory-intensive transforms |
| G.4X | 16 | 64 GB | Very large data volumes, complex joins |
| G.8X | 32 | 128 GB | Massive data volumes, high parallelism |

**Number of workers guidance:**

- **Small tables** (<1M rows, <1 GB): 2-5 workers, G.1X
- **Medium tables** (1M-10M rows, 1-10 GB): 5-10 workers, G.1X or G.2X
- **Large tables** (10M-100M rows, 10-100 GB): 10-20 workers, G.2X
- **Very large tables** (>100M rows, >100 GB): 20-50 workers, G.2X or G.4X

Start conservative and scale up based on job duration and throughput.

### Timeout Configuration

Set timeout based on expected job duration:

- **Small incremental loads**: 15-30 minutes
- **Medium incremental loads**: 30-60 minutes
- **Large incremental loads**: 60-120 minutes
- **Full refresh of large tables**: 120-480 minutes

Add buffer for source database query time and network latency.

### Retry Configuration

Configure retries for transient failures:

```python
'MaxRetries': 1  # Retry once on failure
```

For production pipelines, consider:

- Setting `MaxRetries` to 1-2 for transient network issues
- Using Glue job bookmarks to avoid duplicate processing
- Implementing idempotent logic (upsert instead of append)

### Important Job Arguments

**Required arguments:**

- `--datalake-formats iceberg`: Required for S3 Tables and standard Iceberg targets
- `--enable-glue-datacatalog`: Enable Glue Data Catalog integration for Iceberg
- `--conf`: Spark catalog configuration. See [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md) for the exact keys per target type.
- `--enable-metrics`: Publish CloudWatch metrics
- `--enable-continuous-cloudwatch-log`: Stream logs to CloudWatch

**Optional arguments:**

- `--enable-spark-ui`: Enable Spark UI for debugging (requires S3 bucket)
- `--spark-event-logs-path`: Where to store Spark UI logs
- `--conf spark.sql.adaptive.enabled=true`: Enable adaptive query execution
- `--conf spark.sql.adaptive.coalescePartitions.enabled=true`: Optimize partition count

### Network Configuration

If the source database is in a VPC, ensure the Glue job has network access:

```python
'Connections': {
    'Connections': ['<glue-connection-name>']
}
```

The connection specifies:

- VPC
- Subnet
- Security groups
- Availability zone

Glue provisions ENIs in the specified subnet to access the database.

## Advanced PySpark Patterns

### Parallel Reads with Partitioning

For large tables, read data in parallel using Spark partitioning:

```python
# Read with parallel partitions
source_df = spark.read.format("jdbc").options(
    url=jdbc_url,
    dbtable="large_table",
    numPartitions=10,  # Read with 10 parallel connections
    partitionColumn="id",  # Partition on this column
    lowerBound=1,  # Min value
    upperBound=10000000  # Max value
).load()
```

This creates 10 parallel queries:

- Partition 1: `WHERE id >= 1 AND id < 1000000`
- Partition 2: `WHERE id >= 1000000 AND id < 2000000`
- ...
- Partition 10: `WHERE id >= 9000000 AND id <= 10000000`

**Best practices:**

- Use a numeric column with even distribution
- Set `numPartitions` = number of workers × cores per worker
- Choose `lowerBound` and `upperBound` based on actual data range

### Deduplication Logic

If there's risk of duplicate records (job retries, late arrivals):

```python
from pyspark.sql.window import Window
from pyspark.sql.functions import row_number

# Deduplicate by primary key, keeping latest by watermark
window = Window.partitionBy("primary_key").orderBy(col(watermark_column).desc())
deduplicated_df = source_df.withColumn("row_num", row_number().over(window)) \
    .filter(col("row_num") == 1) \
    .drop("row_num")
```

### Type Conversion and Validation

Add data quality checks and type conversions:

```python
from pyspark.sql.functions import col, when

transformed_df = source_df.select(
    # Safe type casting with null handling
    when(col("amount").cast("double").isNotNull(), col("amount").cast("double"))
        .otherwise(0.0).alias("amount"),

    # String trimming and validation
    when(col("email").rlike(r"^[\w\.-]+@[\w\.-]+\.\w+$"), col("email"))
        .otherwise(None).alias("email"),

    # Date parsing with fallback
    when(col("order_date").isNotNull(),
         to_date(col("order_date"), "yyyy-MM-dd"))
        .otherwise(None).alias("order_date")
)
```

### Watermark with Buffer for Late Arrivals

If source data can arrive late (event timestamp < updated timestamp):

```python
from datetime import timedelta

# Load data from 1 day before last watermark to catch late arrivals
buffer_watermark = (datetime.strptime(last_watermark, '%Y-%m-%d %H:%M:%S')
                    - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')

filtered_df = source_df.filter(
    f"{args['watermark_column']} > '{buffer_watermark}'"
)

# Then use upsert to avoid duplicates
```

## Monitoring and Observability

### CloudWatch Logs

Glue streams job logs to CloudWatch Logs under:

- Log group: `/aws-glue/jobs/output`
- Log stream: `<job-name>-<job-run-id>`

**Key log patterns to monitor:**

- `Last watermark: <value>` - Starting point for incremental load
- `Loading X new/updated records` - How many records found
- `Updated watermark to: <value>` - New watermark after load
- `ERROR` - Any errors during execution

### CloudWatch Metrics

With `--enable-metrics`, Glue publishes:

- `glue.driver.aggregate.numCompletedTasks` - Tasks completed
- `glue.driver.aggregate.elapsedTime` - Job duration
- `glue.driver.aggregate.recordsRead` - Records read from source
- `glue.driver.aggregate.bytesRead` - Bytes read from source

Set up CloudWatch alarms for:

- Job failures (state = FAILED)
- Long-running jobs (duration > threshold)
- No records loaded (might indicate source issue)

### Spark UI

Enable Spark UI for detailed execution metrics:

```python
'DefaultArguments': {
    '--enable-spark-ui': 'true',
    '--spark-event-logs-path': 's3://<logs-bucket>/spark-logs/'
}
```

Access via Glue console → Job runs → View Spark UI

Use Spark UI to:

- Identify slow stages (data skew, shuffle issues)
- Analyze task distribution across workers
- Debug memory issues (GC time, spills to disk)

## Script Storage and Versioning

**Best practices for script management:**

1. **Store scripts in S3**: `s3://<scripts-bucket>/glue-jobs/<job-name>.py`
2. **Version scripts**: Use S3 versioning or include version in filename
3. **Separate environments**: Different buckets for dev/staging/prod
4. **Use Git**: Maintain scripts in Git, deploy to S3 via CI/CD

**Example structure:**

```
s3://my-glue-scripts/
  prod/
    external-import-customers.py
    external-import-orders.py
  dev/
    external-import-customers.py
    external-import-orders.py
```

## Testing Scripts Locally

Test PySpark scripts locally before deploying to Glue:

```bash
# Install dependencies
pip install pyspark boto3

# Run script locally (modify to use local Spark)
python external-import-customers.py \
  --JOB_NAME test-run \
  --connection_name test-connection \
  --source_table customers \
  --target_table local.test.customers \
  --watermark_column updated_at \
  --watermark_bucket test-bucket \
  --watermark_key watermarks/customers.txt
```

For full local testing, use AWS Glue Docker images:

```bash
docker pull amazon/aws-glue-libs:glue_libs_5.0.0_image_01
```

## Summary

Glue ETL job creation workflow:

1. **Choose template** - Append, Upsert, Custom SQL, or Full Refresh
2. **Customize script** - Add transformations, validation, error handling
3. **Save to S3** - Store script in versioned S3 location
4. **Create job** - Use MCP or CLI with appropriate configuration
5. **Size workers** - Choose worker type and count based on data volume
6. **Configure monitoring** - Enable CloudWatch logs and metrics
7. **Test locally** - Validate logic before deploying (optional)

With a well-configured Glue job, external database data flows continuously into S3 Tables with minimal operational overhead.
