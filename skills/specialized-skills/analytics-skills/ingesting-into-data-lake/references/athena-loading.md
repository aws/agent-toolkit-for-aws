# Data Loading via Athena INSERT INTO

Fallback approach for simple one-time data loads when Glue ETL is unavailable or unnecessary.

## Step 1: Create External Table for Source

Create a temporary external table pointing to source files in S3.

### CSV

```sql
CREATE EXTERNAL TABLE temp_source_<timestamp> (
  customer_id INT,
  first_name STRING,
  last_name STRING,
  email STRING,
  signup_date STRING
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://<bucket>/<prefix>/'
TBLPROPERTIES ('skip.header.line.count'='1');
```

### JSON

```sql
CREATE EXTERNAL TABLE temp_source_<timestamp> (
  order_id BIGINT,
  customer_id BIGINT,
  order_date STRING,
  total DECIMAL(10,2)
)
ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe'
LOCATION 's3://<bucket>/<prefix>/';
```

### Parquet / ORC

```sql
CREATE EXTERNAL TABLE temp_source_<timestamp> (
  event_id BIGINT,
  event_type STRING,
  timestamp TIMESTAMP
)
STORED AS PARQUET  -- or ORC
LOCATION 's3://<bucket>/<prefix>/';
```

## Step 2: Transform and Insert

```sql
INSERT INTO "<catalog>"."<namespace>"."<target_table>"
SELECT
  CAST(customer_id AS BIGINT) AS customer_id,
  first_name,
  last_name,
  email,
  DATE_PARSE(signup_date, '%Y-%m-%d') AS signup_date
FROM temp_source_<timestamp>
WHERE customer_id IS NOT NULL
```

For detailed type casting, date parsing, null handling, and boolean conversion patterns, see [type-transformations.md](type-transformations.md).

### Execute via CLI

```bash
QUERY_ID=$(aws athena start-query-execution \
  --query-string "<INSERT INTO query>" \
  --query-execution-context Database=<namespace> \
  --result-configuration OutputLocation=s3://<results-bucket>/ \
  --region <region> \
  --query 'QueryExecutionId' --output text)

aws athena get-query-execution --query-execution-id "$QUERY_ID" --region <region>
```

## Step 3: Validate

```sql
-- Row count
SELECT COUNT(*) as row_count FROM "<catalog>"."<namespace>"."<target_table>";

-- Spot check
SELECT * FROM "<catalog>"."<namespace>"."<target_table>" LIMIT 10;

-- Null check on critical columns
SELECT
  SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) as null_ids,
  COUNT(*) as total
FROM "<catalog>"."<namespace>"."<target_table>";
```

## Step 4: Clean Up

```sql
DROP TABLE IF EXISTS temp_source_<timestamp>;
```

## Large Datasets

If Athena times out (30-minute limit):

1. **Batch by partition**: Load one month/day at a time
2. **Switch to Glue ETL**: Better for datasets > 1GB — handles larger data with more workers, provides monitoring and retries

## Limitations

| Limitation | Workaround |
|-----------|------------|
| No scheduling | Use EventBridge or Step Functions to trigger queries |
| Limited transformations | Use Glue ETL for complex PySpark logic |
| 30-minute timeout | Batch loads or switch to Glue ETL |
