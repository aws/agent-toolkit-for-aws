# Testing and Scheduling Guide

Complete guide for testing Glue ETL jobs, validating data loads, and setting up recurring schedules for external data import pipelines.

## Overview

After creating a Glue ETL job, you must:

1. **Test the job** - Run manually to verify it works
2. **Validate data** - Confirm data loaded correctly into target table
3. **Schedule the job** - Set up recurring execution (for ongoing pipelines)
4. **Monitor execution** - Track job runs and handle failures

## Testing the Job

### Run the Job Manually

Before scheduling, run the job once to validate the entire workflow.

```bash
JOB_RUN_ID=$(aws glue start-job-run \
  --job-name "external-import-<source>-<table>" \
  --region <region> \
  --query 'JobRunId' --output text)

echo "Job run started: $JOB_RUN_ID"
```

### Monitor Job Execution

Check job status and logs:

```bash
# Get job run status
aws glue get-job-run \
  --job-name "external-import-<source>-<table>" \
  --run-id "$JOB_RUN_ID" \
  --region <region>

# Check if job succeeded
STATUS=$(aws glue get-job-run \
  --job-name "external-import-<source>-<table>" \
  --run-id "$JOB_RUN_ID" \
  --query 'JobRun.JobRunState' \
  --output text)

echo "Job status: $STATUS"
```

**Job states:**

- `STARTING` - Job is initializing
- `RUNNING` - Job is executing
- `SUCCEEDED` - Job completed successfully
- `FAILED` - Job failed (check logs for errors)
- `TIMEOUT` - Job exceeded timeout limit
- `STOPPED` - Job was manually stopped

### View CloudWatch Logs

Glue streams logs to CloudWatch Logs:

```bash
# Get log stream name
LOG_STREAM=$(aws glue get-job-run \
  --job-name "external-import-<source>-<table>" \
  --run-id "$JOB_RUN_ID" \
  --query 'JobRun.LogGroupName' \
  --output text)

# Tail logs
aws logs tail /aws-glue/jobs/output --follow \
  --log-stream-names "<job-name>-<run-id>" \
  --region <region>
```

**Key log messages to look for:**

- `Last watermark: <value>` - Starting point for incremental load
- `Loading X new/updated records` - Number of records found
- `Updated watermark to: <value>` - New watermark after successful load
- `Successfully loaded X records` - Confirmation of append/upsert
- `ERROR` or `Exception` - Errors that caused failure

### Common Issues During Testing

#### Connection Timeouts

**Symptom**: Job fails with "Connection timeout" or "Unable to connect to database"

**Causes:**

- VPC/subnet configuration incorrect
- Security groups blocking traffic
- Database firewall rules
- Network ACLs blocking Glue's IP ranges

**Solution:**

1. Test connection in Glue console: Connections → Select connection → Test
2. Verify security groups allow inbound from Glue's security group
3. Check database firewall allows connections from Glue subnet CIDR
4. Ensure NAT gateway/internet gateway for outbound connectivity (if needed)

#### Authentication Failures

**Symptom**: "Access denied" or "Invalid username/password"

**Causes:**

- Incorrect credentials in connection
- Password expired
- Database user lacks required permissions
- IP-based restrictions on database user

**Solution:**

1. Verify credentials by connecting manually (e.g., via SQL client)
2. Check database user has SELECT permission on source tables
3. Ensure user is allowed from Glue's IP/subnet
4. For AWS Secrets Manager: verify secret ARN and IAM permissions

#### Schema Mismatches

**Symptom**: "Type mismatch" or "Cannot cast X to Y"

**Causes:**

- Source column type incompatible with target schema
- Source column is NULL but target doesn't allow NULL
- Decimal precision/scale mismatch

**Solution:**

1. Add explicit type casting in PySpark script
2. Use `.cast("string")` as fallback for problematic columns
3. Add NULL handling: `when(col("x").isNotNull(), col("x")).otherwise(default_value)`
4. Update target schema to match source types more closely

#### Performance Issues

**Symptom**: Job runs slowly or times out

**Causes:**

- Source database query is slow (no indexes, full table scan)
- Too few Glue workers
- Network bandwidth limitations
- Reading too much data in single batch

**Solution:**

1. Add indexes on watermark column in source database
2. Increase number of Glue workers
3. Use parallel reads with `numPartitions` option
4. Reduce batch size by using smaller date ranges
5. Optimize source query (add WHERE clauses, select only needed columns)

#### Watermark Not Advancing

**Symptom**: Job runs but no new records loaded, watermark stays same

**Causes:**

- No new data in source
- Watermark column comparison incorrect (timezone issue)
- Watermark file not updating due to S3 permissions
- Filter logic incorrect

**Solution:**

1. Verify new data exists in source: Query source directly
2. Check timezone handling: Convert all timestamps to UTC
3. Verify Glue job role has S3 write permissions for watermark bucket
4. Add debug logging: Print watermark values and filter query

## Validating Data Load

After the job completes successfully, verify data was loaded correctly.

### Check Row Count

Query the target S3 Table to confirm records were written:

```sql
-- Count total rows
SELECT COUNT(*) FROM "<catalog>"."<namespace>"."<table>";
```

Compare with expected count from job logs (e.g., "Successfully loaded X records").

### Inspect Latest Records

View the most recently loaded records:

```sql
-- Get latest records by watermark column
SELECT *
FROM "<catalog>"."<namespace>"."<table>"
ORDER BY <watermark-column> DESC
LIMIT 10;
```

Verify:

- Columns match expected schema
- Data types are correct
- Values look reasonable
- Timestamps are in expected timezone

### Verify Watermark Updated

Check that the watermark file was updated:

```bash
# Read watermark file from S3
aws s3 cp s3://<bucket>/watermarks/<table-name>.txt -

# Should show the new watermark value matching the job logs
```

### Compare Source and Target

For critical tables, compare aggregations between source and target:

**Source (via Glue connection):**

```sql
SELECT COUNT(*), SUM(amount), MAX(updated_at)
FROM <schema>.<table>
WHERE updated_at > '<last-watermark>';
```

**Target (S3 Table):**

```sql
SELECT COUNT(*), SUM(amount), MAX(load_timestamp)
FROM "<catalog>"."<namespace>"."<table>"
WHERE load_timestamp >= '<job-start-time>';
```

Counts and sums should match.

### Validate Data Quality

Run basic data quality checks:

```sql
-- Check for NULL values in key columns
SELECT COUNT(*) FROM "<catalog>"."<namespace>"."<table>"
WHERE customer_id IS NULL OR email IS NULL;

-- Check for duplicates (if using append instead of upsert)
SELECT customer_id, COUNT(*)
FROM "<catalog>"."<namespace>"."<table>"
GROUP BY customer_id
HAVING COUNT(*) > 1;

-- Check date range
SELECT MIN(order_date), MAX(order_date)
FROM "<catalog>"."<namespace>"."<table>";
```

For production pipelines, consider using AWS Glue Data Quality rules to automate validation.

## Scheduling Recurring Pipelines

Once testing is complete, set up scheduling for ongoing data syncs.

### Determine Schedule Frequency

Choose schedule based on data freshness requirements:

**Real-time (<1 minute latency):**

- Don't use Glue batch jobs - use AWS DMS, Glue Streaming, or Kinesis instead

**Near real-time (5-15 minute latency):**

- Schedule: Every 15 minutes: `cron(0/15 * * * ? *)`
- Consider costs - Glue jobs have minimum 1-minute billing

**Hourly:**

- Schedule: Top of each hour: `cron(0 * * * ? *)`
- Good for: Transaction logs, event streams

**Every 6 hours:**

- Schedule: `cron(0 */6 * * ? *)`
- Good for: Slowly changing data, reporting tables

**Daily:**

- Schedule: 2 AM UTC: `cron(0 2 * * ? *)`
- Good for: Dimension tables, reference data
- Choose off-peak hours to avoid source database load

**Weekly:**

- Schedule: Monday at 2 AM: `cron(0 2 ? * MON *)`
- Good for: Historical archives, full refreshes

**Coordinate with source system:**

- Avoid peak hours when source database is under load
- Schedule after batch processes complete (if applicable)
- Consider maintenance windows

### Create Glue Trigger

Glue Triggers schedule job execution.

```bash
aws glue create-trigger \
  --name "external-import-<table>-schedule" \
  --type SCHEDULED \
  --schedule "cron(0 */6 * * ? *)" \
  --actions JobName="external-import-<source>-<table>" \
  --description "Scheduled sync from <source> to S3 Tables" \
  --start-on-creation \
  --region <region>
```

**Cron expression format:**

```
cron(Minutes Hours Day-of-month Month Day-of-week Year)
```

**Examples:**

- Every 15 minutes: `cron(0/15 * * * ? *)`
- Hourly: `cron(0 * * * ? *)`
- Every 6 hours: `cron(0 */6 * * ? *)`
- Daily at 2 AM UTC: `cron(0 2 * * ? *)`
- Weekdays at 6 AM UTC: `cron(0 6 ? * MON-FRI *)`
- First day of month at midnight: `cron(0 0 1 * ? *)`

### Start/Stop Triggers

**Start a trigger** (enable scheduling):

```bash
aws glue start-trigger \
  --name "external-import-<table>-schedule" \
  --region <region>
```

**Stop a trigger** (disable scheduling):

```bash
aws glue stop-trigger \
  --name "external-import-<table>-schedule" \
  --region <region>
```

### View Trigger Status

Check trigger details and recent runs:

```bash
aws glue get-trigger \
  --name "external-import-<table>-schedule" \
  --region <region>
```

## Monitoring Scheduled Jobs

### CloudWatch Alarms

Set up CloudWatch alarms for job failures:

```bash
# Create alarm for job failures
aws cloudwatch put-metric-alarm \
  --alarm-name "glue-job-failure-<table>" \
  --alarm-description "Alert when Glue job fails" \
  --metric-name JobFailure \
  --namespace AWS/Glue \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=JobName,Value="external-import-<source>-<table>" \
  --evaluation-periods 1 \
  --alarm-actions <sns-topic-arn>
```

**Metrics to monitor:**

- `glue.driver.aggregate.recordsRead` - Records read from source
- `glue.driver.aggregate.elapsedTime` - Job duration
- Job state (SUCCEEDED, FAILED, TIMEOUT)

### View Recent Job Runs

List recent executions of a job:

```bash
aws glue get-job-runs \
  --job-name "external-import-<source>-<table>" \
  --region <region> \
  --max-results 10
```

### Track Watermark Progression

Monitor how watermark advances over time:

```bash
# List watermark history (if versioning enabled on S3 bucket)
aws s3api list-object-versions \
  --bucket <bucket> \
  --prefix watermarks/<table-name>.txt \
  --query 'Versions[*].[LastModified,VersionId]' \
  --output table
```

Create a Lambda function to log watermark values to CloudWatch Logs after each job run for historical tracking.

## Advanced Scheduling Patterns

### Conditional Triggers

Run a job only after another job succeeds:

```bash
aws glue create-trigger \
  --name "external-import-orders-after-customers" \
  --type CONDITIONAL \
  --actions JobName="external-import-orders" \
  --predicate '{
    "Conditions": [{
      "LogicalOperator": "EQUALS",
      "JobName": "external-import-customers",
      "State": "SUCCEEDED"
    }]
  }' \
  --start-on-creation
```

Use for:

- Loading dimension tables before fact tables
- Ensuring dependencies load in correct order
- Chaining transformations

### Event-Driven Triggers

Trigger job based on EventBridge events:

```bash
# Create EventBridge rule to trigger Glue job
aws events put-rule \
  --name "trigger-glue-on-event" \
  --event-pattern '{
    "source": ["aws.s3"],
    "detail-type": ["Object Created"],
    "detail": {
      "bucket": {
        "name": ["source-data-bucket"]
      }
    }
  }'

aws events put-targets \
  --rule "trigger-glue-on-event" \
  --targets "Id=1,Arn=arn:aws:glue:region:account:job/external-import-job"
```

### On-Demand Triggers

Allow users to trigger jobs manually via API/console without scheduling:

```bash
# Don't create a trigger, just run the job when needed
aws glue start-job-run \
  --job-name "external-import-<source>-<table>"
```

## Best Practices

### Testing

1. **Test connection first** - Use Glue console's "Test connection" before creating job
2. **Start small** - Test with small data subset or short time window first
3. **Validate thoroughly** - Check row counts, data quality, watermark progression
4. **Test failure scenarios** - Kill job mid-run to verify watermark isn't corrupted

### Scheduling

1. **Start conservatively** - Begin with less frequent schedule, increase if needed
2. **Avoid peak hours** - Schedule during off-peak times for source database
3. **Set appropriate timeouts** - Allow buffer for larger-than-expected data volumes
4. **Use conditional triggers** - For dependent jobs, use conditional triggers instead of fixed time delays

### Monitoring

1. **Set up CloudWatch alarms** - Alert on failures, long durations, no records loaded
2. **Track watermark progression** - Ensure watermark advances on each run
3. **Monitor source lag** - Compare source max timestamp vs loaded max timestamp
4. **Review logs regularly** - Check for warnings, performance issues

### Maintenance

1. **Review and adjust schedules** - As data volumes change, adjust frequency or worker count
2. **Update scripts in Git** - Version control all job scripts
3. **Test script changes in dev** - Before deploying to production
4. **Archive old watermarks** - Keep historical watermark values for debugging

## Summary

Testing and scheduling workflow:

1. **Run job manually** - Start job and monitor execution
2. **Check CloudWatch logs** - Verify no errors, watermark advanced
3. **Validate data load** - Query target table, check row counts, inspect data
4. **Verify watermark** - Confirm watermark file updated correctly
5. **Create trigger** - Set up scheduled execution with appropriate frequency
6. **Set up monitoring** - CloudWatch alarms for failures, duration, data lag
7. **Monitor initial runs** - Watch first few scheduled executions closely

With proper testing and monitoring, scheduled Glue jobs provide reliable, automated data pipelines from external databases to S3 Tables.
