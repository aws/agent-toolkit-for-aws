# Incremental Loading Strategies

Complete guide for configuring incremental data loading from external databases.

## Overview

Incremental loading imports only new or changed records instead of the entire dataset on each run. This is essential for recurring pipelines to minimize data transfer and processing time.

## Identify Watermark Column

A watermark column tracks which records have been loaded. The Glue job queries for records where watermark > last_loaded_value.

### Common Watermark Patterns

**Timestamp column** (preferred):

- `updated_at`, `modified_date`, `last_changed`, `etl_timestamp`
- Query: `WHERE timestamp_col > '2024-03-12 10:30:00'`
- Best for: Mutable data that gets updated

**Monotonic ID column**:

- `id`, `order_id`, `transaction_id` (auto-incrementing)
- Query: `WHERE id > 1234567`
- Best for: Immutable data with sequential IDs

**Both timestamp and ID**:

- Use timestamp for recent changes, ID as fallback for historical data
- Query: `WHERE timestamp_col > '...' OR (timestamp_col IS NULL AND id > ...)`

### Ask the User

Present candidates from the source schema:

```
I found these potential watermark columns:
1. CREATED_DATE (TIMESTAMP) - Never changes once set
2. UPDATED_AT (TIMESTAMP) - Updates when record changes (recommended)
3. ID (NUMBER) - Auto-incrementing primary key

Which should I use to track new/updated records?
```

**Recommendation logic**:

- If `updated_at` or `modified_date` exists → Recommend this (captures updates)
- Else if timestamp column exists → Use creation timestamp
- Else if auto-incrementing ID → Use ID
- Else → Recommend full refresh

## Determine Load Strategy

### Incremental Append (New Records Only)

**Best for**: Immutable data

- Transaction logs
- Event streams
- Historical orders
- Audit trails

**How it works**:

1. Query source for records where `watermark > last_watermark`
2. Append new records to target table
3. Update watermark to max value from current batch

**Pros**: Simple, fast, no deduplication needed
**Cons**: Doesn't capture updates to existing records

**PySpark example**:

```python
# Filter for new records
new_records_df = source_df.filter(
    f"{watermark_column} > '{last_watermark}'"
)

# Append to target
new_records_df.writeTo(target_table).append()
```

### Incremental Upsert (New + Updated Records)

**Best for**: Mutable data

- Customer profiles
- Product catalogs
- Employee records
- Account balances

**How it works**:

1. Query source for records where `watermark > last_watermark`
2. Merge into target table using primary key
3. Update existing records, insert new ones
4. Update watermark

**Pros**: Captures both new records and updates
**Cons**: More complex, requires MERGE operation

**PySpark example**:

```python
# Get new/updated records
changed_records_df = source_df.filter(
    f"{watermark_column} > '{last_watermark}'"
)

# Merge into target (upsert)
spark.sql(f"""
MERGE INTO {target_table} AS target
USING changed_records AS source
ON target.{primary_key} = source.{primary_key}
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")
```

### Full Refresh

**Best for**:

- Small dimension tables (< 10K rows)
- Data without watermark columns
- When source doesn't support incremental queries

**How it works**:

1. Truncate or drop target table
2. Load all records from source
3. No watermark needed

**Pros**: Simple, guarantees data consistency
**Cons**: Inefficient for large tables, higher data transfer costs

**PySpark example**:

```python
# Read all records
all_records_df = source_df.select("*")

# Overwrite target table
all_records_df.writeTo(target_table).overwritePartitions()
```

## Watermark Storage Options

The Glue job needs to persist the last loaded watermark value between runs.

### Option A: S3 File (Simple)

Store watermark in a text file in S3.

**Advantages**:

- Simple to implement
- No additional AWS services
- Easy to inspect and debug

**Implementation**:

```python
import boto3

s3 = boto3.client('s3')
watermark_bucket = args['watermark_bucket']
watermark_key = args['watermark_key']

# Read last watermark
try:
    obj = s3.get_object(Bucket=watermark_bucket, Key=watermark_key)
    last_watermark = obj['Body'].read().decode('utf-8').strip()
    print(f"Last watermark: {last_watermark}")
except s3.exceptions.NoSuchKey:
    last_watermark = '1970-01-01 00:00:00'  # Default for timestamp
    # OR last_watermark = '0'  # Default for ID
    print("No previous watermark found, starting from beginning")

# After loading, update watermark
new_watermark = filtered_df.agg({watermark_column: "max"}).collect()[0][0]
s3.put_object(
    Bucket=watermark_bucket,
    Key=watermark_key,
    Body=str(new_watermark)
)
print(f"Updated watermark to: {new_watermark}")
```

**S3 path structure**:

```
s3://my-glue-watermarks/
  customers.txt          → "2024-03-12 14:30:00"
  orders.txt             → "2024-03-12 14:25:00"
  products.txt           → "2024-03-10 08:00:00"
```

### Option B: DynamoDB Table (Robust)

Store watermarks in a DynamoDB table with one item per job.

**Advantages**:

- Atomic updates
- Query watermarks programmatically
- Can store additional metadata (last run time, row count, etc.)

**Create table**:

```bash
aws dynamodb create-table \
  --table-name glue-job-watermarks \
  --attribute-definitions \
    AttributeName=job_name,AttributeType=S \
  --key-schema \
    AttributeName=job_name,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region <region>
```

**Implementation**:

```python
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('glue-job-watermarks')
job_name = args['JOB_NAME']

# Read last watermark
try:
    response = table.get_item(Key={'job_name': job_name})
    item = response['Item']
    last_watermark = item['watermark']
    print(f"Last watermark for {job_name}: {last_watermark}")
except KeyError:
    last_watermark = '1970-01-01 00:00:00'
    print("No previous watermark found, starting from beginning")

# After loading, update watermark
new_watermark = filtered_df.agg({watermark_column: "max"}).collect()[0][0]
table.put_item(Item={
    'job_name': job_name,
    'watermark': str(new_watermark),
    'last_run_time': datetime.now().isoformat(),
    'rows_loaded': row_count
})
print(f"Updated watermark to: {new_watermark}")
```

### Option C: Query Target Table (Advanced)

Query the target S3 Table to determine the max watermark value.

**Advantages**:

- No external storage needed
- Watermark always matches actual data

**Disadvantages**:

- Requires target table scan (can be slow)
- Doesn't work for first run (empty table)

**Implementation**:

```python
# Query target table for max watermark
try:
    max_watermark_df = spark.sql(f"""
        SELECT MAX({watermark_column}) as max_value
        FROM {target_table}
    """)
    last_watermark = max_watermark_df.collect()[0]['max_value']
    if last_watermark is None:
        last_watermark = '1970-01-01 00:00:00'
    print(f"Max watermark in target: {last_watermark}")
except:
    last_watermark = '1970-01-01 00:00:00'
    print("Target table empty or doesn't exist, starting from beginning")
```

**Recommendation**: Use **Option A (S3 file)** for simplicity unless you have specific requirements for DynamoDB's features.

## Handling Edge Cases

### Timezone Considerations

**Problem**: Source database uses one timezone, target uses another
**Solution**: Normalize all timestamps to UTC

```python
from pyspark.sql.functions import to_utc_timestamp

# Convert source timestamp to UTC
df_utc = source_df.withColumn(
    "timestamp_utc",
    to_utc_timestamp(col("source_timestamp"), "America/New_York")
)
```

### Backfill Historical Data

**Scenario**: Need to load historical data before starting incremental loads

**Approach**:

1. Set watermark to earliest desired date: `1900-01-01 00:00:00`
2. Run job once to load all historical data
3. Subsequent runs will be incremental from that point forward

**OR** load in batches:

```python
# Batch 1: Load 2020 data
WHERE timestamp >= '2020-01-01' AND timestamp < '2021-01-01'

# Batch 2: Load 2021 data
WHERE timestamp >= '2021-01-01' AND timestamp < '2022-01-01'

# Batch 3: Load 2022+ data
WHERE timestamp >= '2022-01-01'

# Then switch to incremental
```

### Late-Arriving Data

**Problem**: Records arrive after their timestamp (e.g., event from yesterday arrives today)

**Solution 1**: Add buffer window

```python
# Load data from 1 day before last watermark to catch late arrivals
buffer_watermark = last_watermark - timedelta(days=1)
WHERE timestamp > buffer_watermark
```

**Solution 2**: Use separate updated_at column

```python
# Use updated_at instead of event_timestamp
WHERE updated_at > last_watermark
```

### Deleted Records

**Problem**: Source deletes records, but incremental load doesn't capture deletions

**Solutions**:

**Option 1**: Periodic full refresh

- Run incremental loads daily
- Run full refresh weekly to remove deleted records

**Option 2**: Soft deletes

- Source system marks records as deleted instead of removing them
- Filter: `WHERE updated_at > last_watermark OR deleted_at > last_watermark`

**Option 3**: Compare and prune

- Periodically query source for all IDs
- Find IDs in target that don't exist in source
- Delete those records from target

### Duplicate Records

**Problem**: Same record loaded multiple times due to job retries or watermark issues

**Prevention**:

1. Use upsert instead of append for mutable data
2. Add deduplication logic:

```python
from pyspark.sql.window import Window
from pyspark.sql.functions import row_number

# Deduplicate by primary key, keeping latest by watermark
window = Window.partitionBy("primary_key").orderBy(col(watermark_column).desc())
deduplicated_df = df.withColumn("row_num", row_number().over(window)) \
    .filter(col("row_num") == 1) \
    .drop("row_num")
```

## Performance Optimization

### Index Watermark Column

Ensure the watermark column has an index in the source database:

```sql
-- Oracle
CREATE INDEX idx_customers_updated_at ON CUSTOMERS(UPDATED_AT);

-- SQL Server
CREATE INDEX idx_customers_updated_at ON CUSTOMERS(UPDATED_AT);

-- PostgreSQL
CREATE INDEX idx_customers_updated_at ON customers(updated_at);
```

Without an index, source database will do full table scans.

### Batch Size Tuning

For high-volume tables, load data in smaller batches:

```python
# Load 1 hour of data at a time
batch_size = timedelta(hours=1)
current_watermark = last_watermark

while current_watermark < datetime.now():
    next_watermark = current_watermark + batch_size

    batch_df = source_df.filter(
        (col(watermark_column) > current_watermark) &
        (col(watermark_column) <= next_watermark)
    )

    batch_df.writeTo(target_table).append()

    current_watermark = next_watermark
```

### Parallel Reads

Use Spark's partitioning for parallel reads from source:

```python
source_df = spark.read.format("jdbc").options(
    url=jdbc_url,
    dbtable=table_name,
    numPartitions=10,  # Read in parallel with 10 partitions
    partitionColumn=watermark_column,
    lowerBound=last_watermark,
    upperBound=current_time
).load()
```

## Monitoring and Alerting

Track these metrics for each incremental load:

- **Rows loaded**: Number of new/updated records
- **Watermark advancement**: How much watermark advanced
- **Load duration**: Time taken for the job
- **Data lag**: Difference between source max watermark and loaded watermark

```python
# Log metrics
print(f"Job metrics:")
print(f"  Rows loaded: {row_count}")
print(f"  Previous watermark: {last_watermark}")
print(f"  New watermark: {new_watermark}")
print(f"  Watermark advancement: {new_watermark - last_watermark}")
print(f"  Load duration: {load_duration} seconds")

# Publish to CloudWatch (optional)
cloudwatch = boto3.client('cloudwatch')
cloudwatch.put_metric_data(
    Namespace='GlueJobs',
    MetricData=[{
        'MetricName': 'RowsLoaded',
        'Value': row_count,
        'Unit': 'Count',
        'Dimensions': [{'Name': 'JobName', 'Value': job_name}]
    }]
)
```

## Best Practices

1. **Choose the right watermark column**: Prefer `updated_at` over `created_at` for mutable data
2. **Test with small batches first**: Verify logic before full-scale loads
3. **Add buffer for late arrivals**: Consider loading data from 1 day before watermark
4. **Monitor watermark advancement**: Alert if watermark stops advancing
5. **Handle timezones consistently**: Convert all timestamps to UTC
6. **Index watermark column in source**: Dramatically improves query performance
7. **Use upsert for mutable data**: Prevents duplicates and captures updates
8. **Store watermark reliably**: S3 file is simple and sufficient for most cases

## Summary

Incremental loading workflow:

1. **Identify watermark column** - Timestamp or auto-incrementing ID
2. **Choose load strategy** - Append (immutable) vs Upsert (mutable) vs Full Refresh
3. **Store watermark** - S3 file, DynamoDB, or query target table
4. **Handle edge cases** - Timezones, late arrivals, deletions, duplicates
5. **Optimize performance** - Index watermark, batch loading, parallel reads
6. **Monitor** - Track rows loaded, watermark advancement, data lag

With proper incremental loading, recurring pipelines efficiently sync only changed data from external databases.
