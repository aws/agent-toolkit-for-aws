# Glue ETL Job Creation Guide

Complete guide for creating AWS Glue ETL jobs that import data from external databases into S3 Tables.

## Overview

Glue ETL jobs use PySpark to connect to external databases via connections, read data incrementally using watermark columns, apply transformations, and write to Iceberg tables in S3 Tables.

## PySpark Script Structure

### Basic Incremental Append Template

For immutable data (transactions, events, logs) where you only need to append new records:

```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame
import boto3
from datetime import datetime
from pyspark.sql.functions import lit

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'connection_name',
    'source_table',
    'target_table',
    'watermark_column',
    'watermark_bucket',
    'watermark_key'
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read last watermark from S3
s3 = boto3.client('s3')
try:
    obj = s3.get_object(Bucket=args['watermark_bucket'], Key=args['watermark_key'])
    last_watermark = obj['Body'].read().decode('utf-8').strip()
    print(f"Last watermark: {last_watermark}")
except s3.exceptions.NoSuchKey:
    last_watermark = '1970-01-01 00:00:00'  # Default for timestamp
    # OR last_watermark = '0'  # Default for ID column
    print("No previous watermark found, starting from beginning")

# Read from external database using Glue connection
source_df = glueContext.create_dynamic_frame.from_catalog(
    database="<temp-catalog-db>",
    table_name="<source-table>",
    transformation_ctx="source_df",
    additional_options={
        "connectionName": args['connection_name']
    }
).toDF()

# Apply incremental filter
filtered_df = source_df.filter(
    f"{args['watermark_column']} > '{last_watermark}'"
)

row_count = filtered_df.count()
print(f"Loading {row_count} new/updated records")

if row_count > 0:
    # Apply transformations (type casting, column mapping, etc.)
    transformed_df = filtered_df.select(
        # Map source columns to target schema
        filtered_df["source_col1"].cast("int").alias("target_col1"),
        filtered_df["source_col2"].alias("target_col2"),
        filtered_df["source_col3"].cast("double").alias("target_col3"),
        # Add load metadata
        lit(datetime.now()).alias("load_timestamp")
    )

    # Write to Iceberg table (append mode)
    transformed_df.writeTo(args['target_table']).append()

    # Update watermark in S3
    new_watermark = filtered_df.agg({args['watermark_column']: "max"}).collect()[0][0]
    s3.put_object(
        Bucket=args['watermark_bucket'],
        Key=args['watermark_key'],
        Body=str(new_watermark)
    )
    print(f"Updated watermark to: {new_watermark}")
    print(f"Successfully loaded {row_count} records")
else:
    print("No new records to load")

job.commit()
```

### Incremental Upsert Template

For mutable data (customer profiles, product catalog) where records can be updated:

```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import col, lit
import boto3
from datetime import datetime

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'connection_name',
    'source_table',
    'target_table',
    'watermark_column',
    'primary_key',  # Column used for merging
    'watermark_bucket',
    'watermark_key'
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read last watermark
s3 = boto3.client('s3')
try:
    obj = s3.get_object(Bucket=args['watermark_bucket'], Key=args['watermark_key'])
    last_watermark = obj['Body'].read().decode('utf-8').strip()
    print(f"Last watermark: {last_watermark}")
except s3.exceptions.NoSuchKey:
    last_watermark = '1970-01-01 00:00:00'
    print("No previous watermark found, starting from beginning")

# Read from external database
source_df = glueContext.create_dynamic_frame.from_catalog(
    database="<temp-catalog-db>",
    table_name="<source-table>",
    transformation_ctx="source_df",
    additional_options={
        "connectionName": args['connection_name']
    }
).toDF()

# Get new/updated records
changed_records_df = source_df.filter(
    f"{args['watermark_column']} > '{last_watermark}'"
)

row_count = changed_records_df.count()
print(f"Found {row_count} new/updated records")

if row_count > 0:
    # Apply transformations
    transformed_df = changed_records_df.select(
        changed_records_df["customer_id"].cast("int").alias("customer_id"),
        changed_records_df["customer_name"].alias("name"),
        changed_records_df["email"].alias("email"),
        changed_records_df["status"].alias("status"),
        changed_records_df["updated_at"].alias("updated_at"),
        lit(datetime.now()).alias("load_timestamp")
    )

    # Create temporary view for MERGE operation
    transformed_df.createOrReplaceTempView("source_view")

    # Execute MERGE INTO (upsert)
    spark.sql(f"""
    MERGE INTO {args['target_table']} AS target
    USING source_view AS source
    ON target.{args['primary_key']} = source.{args['primary_key']}
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)

    # Update watermark
    new_watermark = changed_records_df.agg({args['watermark_column']: "max"}).collect()[0][0]
    s3.put_object(
        Bucket=args['watermark_bucket'],
        Key=args['watermark_key'],
        Body=str(new_watermark)
    )
    print(f"Updated watermark to: {new_watermark}")
    print(f"Upserted {row_count} records")
else:
    print("No new records to process")

job.commit()
```

### Custom SQL Query Template

When users want to filter or transform at source with custom SQL:

```python
import sys
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import lit
import boto3
from datetime import datetime

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'connection_name',
    'source_query',  # SQL query to execute
    'target_table',
    'watermark_column',
    'watermark_bucket',
    'watermark_key',
    'jdbc_driver'
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Retrieve JDBC credentials from Glue connection
jdbc_conf = glueContext.extract_jdbc_conf(args['connection_name'])

# Read last watermark
s3 = boto3.client('s3')
try:
    obj = s3.get_object(Bucket=args['watermark_bucket'], Key=args['watermark_key'])
    last_watermark = obj['Body'].read().decode('utf-8').strip()
    print(f"Last watermark: {last_watermark}")
except s3.exceptions.NoSuchKey:
    last_watermark = '1970-01-01 00:00:00'
    print("Starting from beginning")

# Build query with watermark filter
query = f"""
SELECT * FROM ({args['source_query']}) AS base_query
WHERE {args['watermark_column']} > '{last_watermark}'
"""

print(f"Executing query: {query}")

# Read using JDBC with custom query
source_df = spark.read.format("jdbc").options(
    url=jdbc_conf['url'],
    dbtable=f"({query}) AS subquery",
    user=jdbc_conf['user'],
    password=jdbc_conf['password'],
    driver=args['jdbc_driver']  # e.g., "oracle.jdbc.OracleDriver"
).load()

row_count = source_df.count()
print(f"Query returned {row_count} records")

if row_count > 0:
    # Add load metadata
    transformed_df = source_df.withColumn("load_timestamp", lit(datetime.now()))

    # Write to Iceberg table
    transformed_df.writeTo(args['target_table']).append()

    # Update watermark
    new_watermark = source_df.agg({args['watermark_column']: "max"}).collect()[0][0]
    s3.put_object(
        Bucket=args['watermark_bucket'],
        Key=args['watermark_key'],
        Body=str(new_watermark)
    )
    print(f"Updated watermark to: {new_watermark}")
else:
    print("No new records")

job.commit()
```

### Full Refresh Template

For small dimension tables or when source doesn't support watermarks:

```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import lit
from datetime import datetime

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'connection_name',
    'source_table',
    'target_table'
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read all records from source
source_df = glueContext.create_dynamic_frame.from_catalog(
    database="<temp-catalog-db>",
    table_name="<source-table>",
    transformation_ctx="source_df",
    additional_options={
        "connectionName": args['connection_name']
    }
).toDF()

row_count = source_df.count()
print(f"Loading {row_count} records (full refresh)")

# Apply transformations
transformed_df = source_df.select(
    source_df["col1"].alias("col1"),
    source_df["col2"].alias("col2"),
    lit(datetime.now()).alias("load_timestamp")
)

# Overwrite target table
transformed_df.writeTo(args['target_table']).overwritePartitions()

print(f"Full refresh completed: {row_count} records loaded")

job.commit()
```
