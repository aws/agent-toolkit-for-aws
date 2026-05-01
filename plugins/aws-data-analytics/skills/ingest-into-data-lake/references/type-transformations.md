# Type Transformation and Conflict Resolution Reference

This document describes expected approaches for handling type conflicts and transformations during data import.

## Type Conflict Detection

### What is a Type Conflict?

A type conflict occurs when:

1. **Target table exists** with a defined schema
2. **Source data** has a column with a **different type**
3. **Direct load would fail** without transformation

### Common Type Conflicts

| Source Type | Target Type | Example Conflict |
|-------------|-------------|------------------|
| STRING | INT/DECIMAL | "$29.99" → 29.99 |
| STRING | DATE/TIMESTAMP | "2024-01-15" → DATE |
| INT | STRING | 12345 → "12345" |
| STRING | BOOLEAN | "true"/"false" → TRUE/FALSE |
| DECIMAL | INT | 29.99 → 29 (loses precision) |

## Expected User Interaction

When a type conflict is detected, the skill should:

### 1. Clearly Identify the Conflict

```
[!] Type Conflict Detected:

Column: price
Source Type: STRING (contains values like "$29.99", "$149.50")
Target Type: DECIMAL(10,2)

This conflict must be resolved before import can proceed.
```

### 2. Present Clear Options

```
How would you like to handle this?

Option 1: Transform/Cast - Remove $ symbol and cast STRING to DECIMAL
  - Pros: Preserves all valid data
  - Cons: Invalid values may cause import to fail
  - Example: "$29.99" → 29.99

Option 2: Skip Invalid Rows - Skip rows where transformation fails
  - Pros: Import continues even with bad data
  - Cons: May lose some rows
  - Example: "$29.99" → 29.99, "N/A" → skipped

Option 3: Fail Import - Stop if any invalid values found
  - Pros: Ensures data quality
  - Cons: Requires fixing source data first
  - Example: Stops immediately on first invalid value

Which option do you prefer?
```

### 3. Wait for User Decision

Do NOT silently apply a transformation without user confirmation.

## Transformation Patterns

### STRING → Numeric (INT/DECIMAL)

**PySpark**:

```python
from pyspark.sql.functions import regexp_replace, col

# Remove non-numeric characters except decimal point
transformed_df = source_df.withColumn(
    "price",
    regexp_replace(col("price"), "[^0-9.]", "").cast("decimal(10,2)")
)

# With validation (skip invalid)
from pyspark.sql.functions import when

transformed_df = source_df.withColumn(
    "price",
    when(
        regexp_replace(col("price"), "[^0-9.]", "").rlike("^[0-9.]+$"),
        regexp_replace(col("price"), "[^0-9.]", "").cast("decimal(10,2)")
    ).otherwise(None)
).filter(col("price").isNotNull())
```

**Athena SQL**:

```sql
SELECT
  CAST(regexp_replace(price, '[^0-9.]', '') AS DECIMAL(10,2)) AS price
FROM source_table
WHERE regexp_replace(price, '[^0-9.]', '') <> ''
```

### STRING → DATE/TIMESTAMP

**PySpark**:

```python
from pyspark.sql.functions import to_date, to_timestamp

# Simple date parsing
transformed_df = source_df.withColumn(
    "signup_date",
    to_date(col("signup_date"), "yyyy-MM-dd")
)

# Timestamp with timezone
transformed_df = source_df.withColumn(
    "event_timestamp",
    to_timestamp(col("event_timestamp"), "yyyy-MM-dd HH:mm:ss")
)

# Multiple format attempts
from pyspark.sql.functions import coalesce

transformed_df = source_df.withColumn(
    "date_field",
    coalesce(
        to_date(col("date_field"), "yyyy-MM-dd"),
        to_date(col("date_field"), "MM/dd/yyyy"),
        to_date(col("date_field"), "dd-MMM-yyyy")
    )
)
```

**Athena SQL**:

```sql
SELECT
  DATE_PARSE(date_string, '%Y-%m-%d') AS parsed_date,
  FROM_ISO8601_TIMESTAMP(timestamp_string) AS parsed_timestamp
FROM source_table
```

### STRING → BOOLEAN

**PySpark**:

```python
from pyspark.sql.functions import when, upper

transformed_df = source_df.withColumn(
    "is_active",
    when(upper(col("is_active")).isin("TRUE", "T", "YES", "Y", "1"), True)
    .when(upper(col("is_active")).isin("FALSE", "F", "NO", "N", "0"), False)
    .otherwise(None)
)
```

**Athena SQL**:

```sql
SELECT
  CASE
    WHEN UPPER(is_active) IN ('TRUE', 'T', 'YES', 'Y', '1') THEN TRUE
    WHEN UPPER(is_active) IN ('FALSE', 'F', 'NO', 'N', '0') THEN FALSE
    ELSE NULL
  END AS is_active
FROM source_table
```

### Numeric → STRING

**PySpark**:

```python
# Simple cast
transformed_df = source_df.withColumn(
    "id_as_string",
    col("id").cast("string")
)

# With formatting
from pyspark.sql.functions import format_string

transformed_df = source_df.withColumn(
    "price_formatted",
    format_string("$%.2f", col("price"))
)
```

### Handling NULL Values

**PySpark**:

```python
from pyspark.sql.functions import coalesce, lit

# Provide default for nulls
transformed_df = source_df.withColumn(
    "quantity",
    coalesce(col("quantity"), lit(0))
)

# Filter out nulls in critical columns
transformed_df = source_df.filter(
    col("customer_id").isNotNull() &
    col("order_date").isNotNull()
)
```

## Complete Transformation Example

### Scenario
Source CSV has:

- `price` as STRING with "$" prefix
- `signup_date` as STRING "YYYY-MM-DD"
- `is_active` as STRING "true"/"false"

Target table expects:

- `price` as DECIMAL(10,2)
- `signup_date` as DATE
- `is_active` as BOOLEAN

### Glue ETL Script

```python
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import regexp_replace, to_date, when, upper, col

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'source_path', 'target_table'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read source CSV
source_df = spark.read.format("csv") \
    .option("header", "true") \
    .load(args['source_path'])

# Apply transformations
transformed_df = source_df \
    .withColumn(
        "price",
        regexp_replace(col("price"), "[^0-9.]", "").cast("decimal(10,2)")
    ) \
    .withColumn(
        "signup_date",
        to_date(col("signup_date"), "yyyy-MM-dd")
    ) \
    .withColumn(
        "is_active",
        when(upper(col("is_active")) == "TRUE", True)
        .when(upper(col("is_active")) == "FALSE", False)
        .otherwise(None)
    )

# Filter out rows with failed transformations
clean_df = transformed_df.filter(
    col("price").isNotNull() &
    col("signup_date").isNotNull() &
    col("is_active").isNotNull()
)

# Log filtered count
original_count = source_df.count()
clean_count = clean_df.count()
print(f"Original rows: {original_count}")
print(f"Clean rows: {clean_count}")
print(f"Filtered out: {original_count - clean_count}")

# Write to Iceberg table
clean_df.writeTo(args['target_table']).append()

job.commit()
```

## Evaluation Criteria

When evaluating type conflict resolution:

**Detection**:

- Skill compares source schema to target schema
- Identifies specific columns with type mismatches
- Clearly communicates the conflict to user

**User Interaction**:

- Presents at least 2-3 options for handling the conflict
- Explains pros/cons of each option
- Waits for user decision before proceeding
- Does NOT silently transform without confirmation

**Transformation Code**:

- Provides complete PySpark or SQL code for transformation
- Handles edge cases (null values, invalid formats)
- Includes data quality filters if "skip invalid" chosen
- Logs row counts (original vs transformed)

**Validation**:

- Tests transformation on sample data first
- Validates that transformed types match target schema
- Reports success/failure clearly

## Common Mistakes to Avoid

Silently applying transformations without user consent
Not detecting type conflicts before attempting import
Incomplete transformation code (missing null handling)
Not logging how many rows were filtered out
Assuming all source data is valid without validation
Not providing fallback for invalid values
Generic "cast to type" without cleaning data first (e.g., "$29.99" → cast fails)
