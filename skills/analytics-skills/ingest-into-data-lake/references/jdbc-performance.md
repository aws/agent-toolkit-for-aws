# Performance and Troubleshooting Guide

Guide for diagnosing and resolving performance issues, incremental loading problems, IAM/permissions errors, and monitoring for external data import pipelines.

## Table of Contents

- [Performance Issues](#performance-issues) — Slow queries, job timeouts
- [Incremental Loading Issues](#incremental-loading-issues) — Watermark not advancing, duplicates
- [IAM and Permissions Errors](#iam-and-permissions-errors) — S3 access denied, Glue catalog access
- [Monitoring and Alerting](#monitoring-and-alerting) — CloudWatch alarms, key metrics
- [Troubleshooting Checklist](#troubleshooting-checklist) — Systematic diagnosis steps

## Performance Issues

### Slow Query Execution

**Symptom:**

- Job runs for hours
- CloudWatch logs show: "Executing query..." but no progress

**Root causes:**

1. **Missing indexes** - Source query does full table scan
2. **Too much data** - Loading entire table instead of incremental
3. **Network bandwidth** - Limited throughput between database and Glue
4. **Source database load** - Database under heavy load

**Troubleshooting:**

1. **Check query execution plan in source database:**

   ```sql
   -- Oracle
   EXPLAIN PLAN FOR
   SELECT * FROM large_table WHERE updated_at > '2024-01-01';
   SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);

   -- SQL Server
   SET SHOWPLAN_TEXT ON;
   SELECT * FROM large_table WHERE updated_at > '2024-01-01';

   -- PostgreSQL
   EXPLAIN ANALYZE
   SELECT * FROM large_table WHERE updated_at > '2024-01-01';

   -- MySQL
   EXPLAIN
   SELECT * FROM large_table WHERE updated_at > '2024-01-01';
   ```

2. **Monitor source database load:**
   - Check CPU, memory, I/O utilization
   - Review slow query logs
   - Identify concurrent queries

3. **Measure network throughput:**
   - Check data transfer rate in CloudWatch metrics
   - Look for bandwidth bottlenecks

**Solutions:**

1. **Add index on watermark column:**

   ```sql
   -- Oracle
   CREATE INDEX idx_updated_at ON large_table(updated_at);

   -- SQL Server
   CREATE INDEX idx_updated_at ON large_table(updated_at);

   -- PostgreSQL
   CREATE INDEX idx_updated_at ON large_table(updated_at);

   -- MySQL
   CREATE INDEX idx_updated_at ON large_table(updated_at);
   ```

2. **Use parallel reads:**

   ```python
   source_df = spark.read.format("jdbc").options(
       url=jdbc_url,
       dbtable="large_table",
       numPartitions=10,  # Read in parallel
       partitionColumn="id",
       lowerBound=1,
       upperBound=10000000
   ).load()
   ```

3. **Reduce batch size:**

   ```python
   # Load 1 day at a time instead of full month
   WHERE updated_at >= '2024-01-01' AND updated_at < '2024-01-02'
   ```

4. **Increase Glue workers:**

   ```python
   'NumberOfWorkers': 20,  # Up from 5
   'WorkerType': 'G.2X'    # Larger workers
   ```

### Job Timeout

**Symptom:**

```
ERROR: Job exceeded timeout of 60 minutes
JobRunState: TIMEOUT
```

**Root causes:**

1. **Timeout too short** - Data volume requires more time
2. **Performance issues** - See "Slow Query Execution" above

**Solution:**

Increase job timeout:

```bash
aws glue update-job \
  --job-name external-import-customers \
  --job-update Timeout=180
```

## Incremental Loading Issues

### Watermark Not Advancing

**Symptom:**

- Job runs successfully but loads 0 records every time
- Watermark file contains same value after each run

**Root causes:**

1. **No new data in source** - Actually no changes
2. **Timezone mismatch** - Source uses local time, watermark uses UTC
3. **Watermark filter logic incorrect** - Using `>=` instead of `>`

**Troubleshooting:**

1. **Check source for new data:**

   ```sql
   SELECT COUNT(*) FROM table WHERE updated_at > '<last-watermark>';
   ```

2. **Check timezone:**

   ```python
   print(f"Last watermark: {last_watermark}")
   print(f"Last watermark timezone: {last_watermark_tz}")

   # Convert to UTC
   from datetime import datetime
   import pytz

   utc_watermark = pytz.timezone('America/New_York').localize(
       datetime.strptime(last_watermark, '%Y-%m-%d %H:%M:%S')
   ).astimezone(pytz.utc)
   ```

3. **Check filter logic:**

   ```python
   # Correct: > (strictly greater than)
   filtered_df = source_df.filter(f"{watermark_column} > '{last_watermark}'")

   # Incorrect: >= (will reload last batch every time)
   # filtered_df = source_df.filter(f"{watermark_column} >= '{last_watermark}'")
   ```

**Solution:**

Normalize all timestamps to UTC:

```python
from pyspark.sql.functions import to_utc_timestamp

# Convert source timestamp to UTC
df_utc = source_df.withColumn(
    "updated_at_utc",
    to_utc_timestamp(col("updated_at"), "America/New_York")
)

# Filter using UTC timestamps
filtered_df = df_utc.filter(f"updated_at_utc > '{last_watermark_utc}'")
```

### Duplicate Records

**Symptom:**

- Target table contains duplicate records (same primary key multiple times)

**Root causes:**

1. **Using append instead of upsert** - For mutable data
2. **Job retry** - Job failed mid-run, reran from same watermark
3. **Late-arriving data** - Records arrive after their event timestamp

**Solution:**

1. **Use upsert for mutable data:**

   ```python
   # MERGE INTO instead of append
   spark.sql(f"""
   MERGE INTO {target_table} AS target
   USING source_view AS source
   ON target.customer_id = source.customer_id
   WHEN MATCHED THEN UPDATE SET *
   WHEN NOT MATCHED THEN INSERT *
   """)
   ```

2. **Add deduplication logic:**

   ```python
   from pyspark.sql.window import Window
   from pyspark.sql.functions import row_number

   window = Window.partitionBy("customer_id").orderBy(col("updated_at").desc())
   deduplicated_df = source_df.withColumn("row_num", row_number().over(window)) \
       .filter(col("row_num") == 1) \
       .drop("row_num")
   ```

3. **Handle late arrivals with buffer:**

   ```python
   # Load from 1 day before watermark
   buffer_watermark = last_watermark - timedelta(days=1)
   filtered_df = source_df.filter(f"{watermark_column} > '{buffer_watermark}'")

   # Then upsert to avoid duplicates
   ```

## IAM and Permissions Errors

### S3 Access Denied

**Symptom:**

```
ERROR: Access Denied (Service: Amazon S3; Status Code: 403)
```

**Root cause:**
Glue job IAM role lacks S3 permissions

**Solution:**

Add S3 permissions to Glue role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::<scripts-bucket>/*",
        "arn:aws:s3:::<watermark-bucket>/*",
        "arn:aws:s3:::<data-bucket>/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": [
        "arn:aws:s3:::<scripts-bucket>",
        "arn:aws:s3:::<watermark-bucket>",
        "arn:aws:s3:::<data-bucket>"
      ]
    }
  ]
}
```

### Glue Data Catalog Access Denied

**Symptom:**

```
ERROR: User is not authorized to perform glue:GetTable
```

**Root cause:**
Glue job role lacks Glue Data Catalog permissions

**Solution:**

Add Glue permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:GetPartitions",
        "glue:CreateTable",
        "glue:UpdateTable",
        "glue:DeleteTable"
      ],
      "Resource": [
        "arn:aws:glue:region:account:catalog",
        "arn:aws:glue:region:account:database/*",
        "arn:aws:glue:region:account:table/*/*"
      ]
    }
  ]
}
```

## Monitoring and Alerting

### Set Up CloudWatch Alarms

**Job failure alarm:**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "glue-job-failure-customers" \
  --metric-name JobFailure \
  --namespace AWS/Glue \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=JobName,Value="external-import-customers" \
  --evaluation-periods 1 \
  --alarm-actions <sns-topic-arn>
```

**Long-running job alarm:**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "glue-job-long-running-customers" \
  --metric-name glue.driver.aggregate.elapsedTime \
  --namespace Glue \
  --statistic Maximum \
  --period 300 \
  --threshold 3600000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=JobName,Value="external-import-customers" \
  --evaluation-periods 1 \
  --alarm-actions <sns-topic-arn>
```

### Key Metrics to Track

- `glue.driver.aggregate.recordsRead` - Records read from source
- `glue.driver.aggregate.bytesRead` - Bytes read from source
- `glue.driver.aggregate.elapsedTime` - Job duration
- `glue.driver.aggregate.numCompletedTasks` - Tasks completed
- Job run state (SUCCEEDED, FAILED, TIMEOUT)

## Troubleshooting Checklist

When a job fails, follow this systematic approach:

### 1. Check Job Run Status

```bash
aws glue get-job-run \
  --job-name <job-name> \
  --run-id <run-id> \
  --query 'JobRun.[JobRunState,ErrorMessage]'
```

### 2. Review CloudWatch Logs

```bash
aws logs tail /aws-glue/jobs/output --follow \
  --log-stream-names "<job-name>-<run-id>"
```

Look for:

- `ERROR` messages
- Exception stack traces
- Last successful log message before failure

### 3. Test Connection

```bash
# Test Glue connection
aws glue get-connection --name <connection-name>

# Test from EC2 in same subnet
telnet <db-host> <db-port>
```

### 4. Verify Permissions

```bash
# Check IAM role policies
aws iam get-role --role-name <glue-role-name>
aws iam list-attached-role-policies --role-name <glue-role-name>
```

### 5. Validate Source Data

```sql
-- Run query in source database
SELECT COUNT(*) FROM table WHERE updated_at > '<watermark>';
```

### 6. Check Watermark

```bash
# Read watermark file
aws s3 cp s3://<bucket>/watermarks/<table>.txt -
```

## Summary

Error resolution workflow:

1. **Identify error category** - Connection, schema, performance, incremental, or permissions
2. **Check CloudWatch logs** - Read error messages and stack traces
3. **Test connectivity** - Verify network, security groups, credentials
4. **Validate source data** - Query source database directly
5. **Review job configuration** - Check worker count, timeout, arguments
6. **Monitor metrics** - Set up CloudWatch alarms for proactive detection
7. **Document resolution** - Keep runbook of common issues and fixes

With systematic troubleshooting and proper monitoring, external data import pipelines run reliably with minimal intervention.
