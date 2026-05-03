# Format-Specific Data Loading

Complete guide for reading and processing different file formats in Glue ETL jobs.

## Overview

This reference covers format-specific configuration and code examples for loading data from various file formats into S3 Tables:

- CSV/TSV (delimited text files)
- JSON/JSONL (JavaScript Object Notation)
- Parquet (columnar format with embedded schema)
- Avro (row-based format with embedded schema)
- ORC (Optimized Row Columnar)

## CSV and TSV Files

### Basic CSV Reading

```python
# CSV with custom delimiter
source_df = spark.read.format("csv") \
    .option("header", "true") \
    .option("delimiter", ",") \
    .option("inferSchema", "true") \
    .load(args['source_path'])
```

### TSV (Tab-Separated Values)

```python
# TSV (tab-separated)
source_df = spark.read.format("csv") \
    .option("header", "true") \
    .option("delimiter", "\t") \
    .load(args['source_path'])
```

### CSV Options

| Option | Value | Description |
|--------|-------|-------------|
| `header` | `true`/`false` | First row contains column names |
| `delimiter` | `,`, `\t`, `\|`, etc. | Field separator character |
| `inferSchema` | `true`/`false` | Automatically detect column types |
| `quote` | `"` (default) | Character for quoting fields |
| `escape` | `\` (default) | Escape character |
| `nullValue` | `NULL`, empty, etc. | String representing null values |
| `dateFormat` | `yyyy-MM-dd` | Date parsing format |
| `timestampFormat` | `yyyy-MM-dd HH:mm:ss` | Timestamp parsing format |

### Advanced CSV Example

```python
# CSV with custom options
source_df = spark.read.format("csv") \
    .option("header", "true") \
    .option("delimiter", ",") \
    .option("quote", "\"") \
    .option("escape", "\\") \
    .option("nullValue", "NULL") \
    .option("dateFormat", "yyyy-MM-dd") \
    .option("timestampFormat", "yyyy-MM-dd HH:mm:ss") \
    .option("mode", "DROPMALFORMED") \
    .load(args['source_path'])
```

## JSON and JSONL Files

### JSON Lines (JSONL)

One JSON object per line (most common):

```python
# JSON Lines (one JSON object per line)
source_df = spark.read.format("json").load(args['source_path'])
```

### Nested JSON Handling

#### Option A: Flatten Nested Structures

```python
from pyspark.sql.functions import col

# Flatten nested JSON
flattened_df = source_df.select(
    col("customer.customer_id").alias("customer_id"),
    col("customer.name").alias("customer_name"),
    col("customer.email").alias("email"),
    col("order_id"),
    col("order_date"),
    col("amount")
)
```

#### Option B: Preserve as STRUCT

No transformation needed - Iceberg supports STRUCT types:

```python
# Preserve nested structure (no transformation)
# Schema becomes:
# - order_id: BIGINT
# - customer: STRUCT<customer_id:BIGINT, name:STRING, email:STRING>
# - order_date: DATE
# - amount: DECIMAL
```

### JSON Options

| Option | Value | Description |
|--------|-------|-------------|
| `multiLine` | `true`/`false` | Parse multi-line JSON objects |
| `mode` | `PERMISSIVE`, `DROPMALFORMED`, `FAILFAST` | How to handle malformed records |
| `dateFormat` | `yyyy-MM-dd` | Date parsing format |
| `timestampFormat` | `yyyy-MM-dd'T'HH:mm:ss.SSSXXX` | Timestamp format |

### Array Handling

```python
# Explode array into separate rows
from pyspark.sql.functions import explode

df_with_items = source_df.select(
    col("order_id"),
    explode(col("items")).alias("item")
).select(
    col("order_id"),
    col("item.product_id"),
    col("item.quantity"),
    col("item.price")
)

# Or preserve as ARRAY type in Iceberg
# Schema: items ARRAY<STRUCT<product_id:STRING, quantity:INT, price:DECIMAL>>
```

## Parquet Files

### Basic Parquet Reading

```python
# Parquet (direct read, schema preserved)
source_df = spark.read.format("parquet").load(args['source_path'])
```

### Partitioned Parquet

Spark automatically detects Hive-style partitions:

```python
# Partitioned Parquet (Spark auto-detects partitions)
source_df = spark.read.format("parquet").load("s3://bucket/events/")
# Partitions like year=2024/month=01/ are automatically handled
```

### Detect Partition Structure

For partitioned data with Hive-style partitioning (e.g., `year=2024/month=01/day=15/`):

**Using Python regex**:

```python
import re

# Example S3 path: s3://bucket/events/year=2024/month=01/day=15/part-0000.parquet
sample_s3_path = "s3://bucket/events/year=2024/month=01/day=15/part-0000.parquet"

# Extract partition key-value pairs
path_pattern = r'(\w+)=([^/]+)'
partitions = re.findall(path_pattern, sample_s3_path)
# Result: [('year', '2024'), ('month', '01'), ('day', '15')]

partition_columns = [col for col, _ in partitions]
print(f"Detected partition columns: {partition_columns}")
# Output: ['year', 'month', 'day']
```

**Using AWS CLI**:

```bash
# List S3 paths to identify partition patterns
aws s3 ls s3://bucket/events/ --recursive | head -20

# Look for patterns like:
# year=2024/month=01/day=01/
# year=2024/month=01/day=02/
```

### Partition Column Inference

- Partition columns should typically be: `INT`, `STRING`, or `DATE` types
- Common partition patterns: `year`, `month`, `day`, `region`, `category`
- **Important**: Partition columns will NOT appear in the data files themselves (they're in the path)

### Present Partition Info to User

```
Detected partitioned data structure:
- Partition columns: year (INT), month (INT), day (INT)
- Data columns: event_id, event_type, timestamp, user_id, properties
- Sample partition: year=2024/month=01/day=15
- Estimated partitions: ~90 (covering 3 months)
```

## Avro Files

### Basic Avro Reading

```python
# Avro format
source_df = spark.read.format("avro").load(args['source_path'])
```

### Avro Schema Extraction

Avro files contain embedded schemas. Extract and display:

**Using Python avro library**:

```python
import avro.datafile
import avro.io
import json

# Read Avro file and extract schema
with open('downloaded-sample.avro', 'rb') as f:
    reader = avro.datafile.DataFileReader(f, avro.io.DatumReader())
    schema_json = reader.meta.get('avro.schema').decode('utf-8')
    schema = json.loads(schema_json)

    print("Avro Schema:")
    print(json.dumps(schema, indent=2))

    # Extract field names and types
    for field in schema['fields']:
        print(f"  {field['name']}: {field['type']}")
```

**Using fastavro**:

```python
import fastavro

with open('downloaded-sample.avro', 'rb') as f:
    reader = fastavro.reader(f)
    schema = reader.writer_schema
    for field in schema['fields']:
        print(f"  {field['name']}: {field['type']}")
```

### Avro to Iceberg Type Mapping

| Avro Type | Iceberg Type | Notes |
|-----------|--------------|-------|
| `int` | `INTEGER` | 32-bit signed integer |
| `long` | `BIGINT` | 64-bit signed integer |
| `float` | `FLOAT` | 32-bit floating point |
| `double` | `DOUBLE` | 64-bit floating point |
| `boolean` | `BOOLEAN` | Direct mapping |
| `string` | `STRING` | Direct mapping |
| `bytes` | `BINARY` | Direct mapping |
| `fixed` | `BINARY` | Fixed-length byte array |
| `enum` | `STRING` | Store enum values as strings |
| `array<T>` | `ARRAY<T>` | Direct mapping with recursive type |
| `map<string, T>` | `MAP<STRING, T>` | Direct mapping |
| `record` | `STRUCT` | Nested structure |
| `union [null, T]` | Nullable `T` | Avro nullable pattern |
| `union [T1, T2, ...]` | `STRING` | Multiple types → JSON string |

### Handling Avro Union Types

Avro uses unions for nullable fields:

```json
// Avro schema with nullable field
{
  "name": "age",
  "type": ["null", "int"]
}
```

Maps to Iceberg:

```sql
age INT  -- Nullable by default in Iceberg
```

**For complex unions** (non-nullable):

```python
from pyspark.sql.functions import col, when

# Example: Handle union of int and string
df_with_union = source_df.withColumn(
    "age_clean",
    when(col("age").cast("int").isNotNull(), col("age").cast("int"))
    .otherwise(None)
)
```

**Options for complex unions**:

- **Option A**: Convert to JSON string and store as STRING
- **Option B**: Flatten union types into separate columns (age_int, age_string)
- **Option C**: Fail and ask user how to handle

### Present Avro Schema to User

```
Detected Avro schema with 15 fields:
- user_id (long) → BIGINT
- username (string) → STRING
- age (union[null, int]) → INT (nullable)
- status (enum: active, inactive) → STRING
- metadata (map<string, string>) → MAP<STRING, STRING>
- preferences (record) → STRUCT
```

### Glue Job Configuration for Avro

**Option A: Use `--datalake-formats`** (spark-avro built-in in Glue 5.1 or higher):

```python
# In job DefaultArguments
'--datalake-formats': 'iceberg,delta,hudi,avro'
```

**Option B: Provide spark-avro JAR**:

```bash
# In create-job command
--default-arguments '{
  "--extra-jars": "s3://my-bucket/jars/spark-avro_2.12-3.4.0.jar"
}'
```

## ORC Files

### Basic ORC Reading

```python
# ORC format
source_df = spark.read.format("orc").load(args['source_path'])
```

ORC files include embedded schema similar to Parquet. No special configuration needed.

## Sampling Source Data

Before loading, sample source files to understand structure:

### CSV Sampling

```bash
# Download and inspect first 10 lines
aws s3 cp s3://<bucket>/<key> - | head -10
```

### Parquet Schema Inspection

```python
import pyarrow.parquet as pq

# Read Parquet schema
table = pq.read_table('s3://<bucket>/<key>')
print(table.schema)

# Sample first 10 rows
df = table.to_pandas()
print(df.head(10))
```

### JSON Sampling

```bash
# Download and inspect first 5 JSON objects
aws s3 cp s3://<bucket>/<key> - | head -5
```

## Complete Glue ETL Script Template

```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'source_path', 'target_table', 'source_format'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read source data based on format
if args['source_format'] == 'csv':
    source_df = spark.read.format("csv") \
        .option("header", "true") \
        .option("inferSchema", "true") \
        .load(args['source_path'])
elif args['source_format'] == 'json':
    source_df = spark.read.format("json").load(args['source_path'])
elif args['source_format'] == 'parquet':
    source_df = spark.read.format("parquet").load(args['source_path'])
elif args['source_format'] == 'avro':
    source_df = spark.read.format("avro").load(args['source_path'])
elif args['source_format'] == 'orc':
    source_df = spark.read.format("orc").load(args['source_path'])
else:
    raise ValueError(f"Unsupported format: {args['source_format']}")

# Apply transformations as needed
transformed_df = source_df.select(
    # Column transformations here
)

# Write to Iceberg table
transformed_df.writeTo(args['target_table']).append()

job.commit()
```

## Format-Specific Common Issues

### CSV Issues

**Issue**: Column type inference incorrect
**Solution**: Explicitly specify schema or cast columns after reading

**Issue**: Quoted fields not parsed correctly
**Solution**: Set `.option("quote", "\"")` and `.option("escape", "\\")`

### JSON Issues

**Issue**: Multi-line JSON not parsing
**Solution**: Set `.option("multiLine", "true")`

**Issue**: Malformed JSON records
**Solution**: Set `.option("mode", "DROPMALFORMED")` or `"PERMISSIVE"`

### Parquet Issues

**Issue**: Partition columns not detected
**Solution**: Verify path follows Hive-style partitioning (`key=value/`)

**Issue**: Schema evolution errors
**Solution**: Use `.option("mergeSchema", "true")` when reading

### Avro Issues

**Issue**: Avro library not found
**Solution**: Add `--datalake-formats: iceberg,avro` to job arguments

**Issue**: Complex union types failing
**Solution**: Convert to STRING or handle with conditional logic

## Best Practices

1. **Always sample data first**: Understand structure before loading
2. **Validate schema mapping**: Ensure source types map correctly to Iceberg
3. **Handle malformed records**: Use appropriate error handling mode
4. **Test with small dataset**: Verify transformations work before full load
5. **Monitor CloudWatch logs**: Check for parsing errors or warnings
6. **Document format-specific options**: Keep track of delimiter, quote char, etc.
7. **Use schema evolution carefully**: Understand impact on existing data

## Summary

Different file formats require different reading configurations:

| Format | Key Considerations | Primary Options |
|--------|-------------------|-----------------|
| CSV/TSV | Delimiter, header, quotes | `delimiter`, `header`, `quote` |
| JSON | Nested structures, arrays | `multiLine`, flatten vs preserve |
| Parquet | Partition detection | Auto-detected, `mergeSchema` |
| Avro | Union types, embedded schema | `--datalake-formats: avro` |
| ORC | Similar to Parquet | Auto-schema, minimal config |

With format-specific configuration, Glue ETL can successfully load data from any supported format into S3 Tables.
