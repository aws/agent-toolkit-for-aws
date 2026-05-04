# Schema Evolution and Nested Structure Handling Reference

This document describes expected approaches for handling schema evolution and nested JSON/struct data during imports.

## Schema Evolution

### What is Schema Evolution?

Schema evolution occurs when source data has columns that don't exist in the target table. This is common when:

- Source data schema changes over time (new fields added)
- Importing from multiple sources with different schemas
- Business requirements evolve and new data points are captured

### Types of Schema Changes

| Change Type | Example | Handling |
|-------------|---------|----------|
| New columns | Source has `phone_number`, table doesn't | ALTER TABLE ADD COLUMNS |
| Missing columns | Table has `country`, source doesn't | Use NULL or default value |
| Type changes | Source `price` is STRING, was INT | Type conflict resolution (see type-transformations.md) |
| Column rename | Source has `customer_name`, table has `name` | Manual mapping or user decision |

## Schema Evolution Workflow

### 1. Detect Schema Differences

```python
# Get current table schema from Glue Catalog
import boto3
glue = boto3.client('glue')

response = glue.get_table(
    DatabaseName='my_database',
    Name='my_table'
)

existing_columns = {col['Name']: col['Type'] for col in response['Table']['StorageDescriptor']['Columns']}

# Compare with source schema
source_columns = {'customer_id': 'int', 'name': 'string', 'email': 'string', 'phone': 'string'}  # Inferred

new_columns = set(source_columns.keys()) - set(existing_columns.keys())
missing_columns = set(existing_columns.keys()) - set(source_columns.keys())
```

Expected output to user:

```
Schema Comparison:

Existing table columns: customer_id, name, email
Source data columns: customer_id, name, email, phone

New columns in source (will be added): phone
Missing columns in source (will be NULL): None

Schema evolution will automatically add new columns to the table.
```

### 2. Add New Columns via ALTER TABLE

**With AWS CLI**:

```bash
aws athena start-query-execution \
  --query-string "ALTER TABLE \"catalog\".\"namespace\".\"table\" ADD COLUMNS (phone STRING)" \
  --query-execution-context Database=namespace \
  --result-configuration OutputLocation=s3://bucket/results/ \
  --region us-east-1
```

### 3. Handle Missing Columns

If source is missing columns that exist in the target table, two approaches:

**Option 1: Use NULL for missing columns** (recommended) — New rows will have NULL in these columns. Existing rows keep their values.

**Option 2: Fail the import** — Ensures data completeness. Requires source to have all columns.

## Nested JSON Handling

### Flatten vs Preserve Decision

When source data has nested structures:

```json
{
  "order_id": 12345,
  "customer": {
    "customer_id": 789,
    "name": "John Doe",
    "email": "john@example.com"
  },
  "items": [
    {"product_id": 456, "quantity": 2, "price": 29.99}
  ]
}
```

### Flattening Implementation

**PySpark - Flatten Struct**:

```python
from pyspark.sql.functions import col

flattened_df = source_df.select(
    col("order_id"),
    col("customer.customer_id").alias("customer_id"),
    col("customer.name").alias("customer_name"),
    col("customer.email").alias("customer_email"),
    col("order_date"),
    col("total")
)
```

**PySpark - Explode Array**:

```python
from pyspark.sql.functions import explode, col

# One row per item
exploded_df = source_df.select(
    col("order_id"),
    col("customer.customer_id").alias("customer_id"),
    explode(col("items")).alias("item")
).select(
    "order_id",
    "customer_id",
    col("item.product_id"),
    col("item.quantity"),
    col("item.price")
)
```

**Athena SQL - Flatten with UNNEST**:

```sql
-- Create external table with nested types
CREATE EXTERNAL TABLE orders_nested (
  order_id BIGINT,
  customer STRUCT<customer_id: BIGINT, name: STRING, email: STRING>,
  items ARRAY<STRUCT<product_id: BIGINT, quantity: INT, price: DECIMAL(10,2)>>,
  order_date DATE,
  total DECIMAL(10,2)
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://bucket/orders/';

-- Flatten and insert
INSERT INTO "catalog"."namespace"."orders_flat"
SELECT
  order_id,
  customer.customer_id,
  customer.name AS customer_name,
  customer.email AS customer_email,
  item.product_id,
  item.quantity,
  item.price,
  order_date
FROM orders_nested
CROSS JOIN UNNEST(items) AS t(item);
```

### Preserving Nested Structures

**S3 Tables DDL with Nested Types**:

```sql
CREATE TABLE "catalog"."namespace"."orders_nested" (
  order_id BIGINT,
  customer STRUCT<
    customer_id: BIGINT,
    name: STRING,
    email: STRING
  >,
  items ARRAY<STRUCT<
    product_id: BIGINT,
    quantity: INT,
    price: DECIMAL(10,2)
  >>,
  order_date DATE,
  total DECIMAL(10,2)
)
USING ICEBERG
```

**Querying Nested Data**:

```sql
-- Access struct fields
SELECT
  order_id,
  customer.name,
  customer.email,
  order_date
FROM "catalog"."namespace"."orders_nested"
WHERE customer.customer_id = 789;

-- Explode array in queries
SELECT
  order_id,
  item.product_id,
  item.quantity,
  item.price
FROM "catalog"."namespace"."orders_nested"
CROSS JOIN UNNEST(items) AS t(item);
```

**PySpark - Write with Nested Types**:

```python
# Preserve nested structure
source_df.writeTo(args['target_table']).append()

# No flattening needed - PySpark DataFrame schema maps directly to Iceberg
```

## Array Handling Options

Implementation examples for each array handling approach:

### Option 1: Keep as Array

Store as `ARRAY<STRUCT<...>>` in S3 Table. Query with UNNEST when needed. Preserves one-to-many relationships efficiently.

### Option 2: Explode to Separate Rows

Each array element becomes its own row. Simple flat table structure. May create many duplicate rows if arrays are large.

### Option 3: Create Separate Related Table

Store items in separate table (e.g., `order_items`). Link via foreign key. Normalized database design.

## Complete Examples

### Example 1: Schema Evolution

**Before** (existing table):

```sql
CREATE TABLE customers (
  customer_id INT,
  name STRING,
  email STRING
)
```

**New Source Data** adds columns: `phone STRING`, `address STRING`

**After Evolution**:

```sql
ALTER TABLE customers ADD COLUMNS (
  phone STRING,
  address STRING
);
```

**Result**:

- Existing rows: `customer_id=1, name="Alice", email="alice@example.com", phone=NULL, address=NULL`
- New rows: `customer_id=2, name="Bob", email="bob@example.com", phone="555-1234", address="123 Main St"`

### Example 2: Nested JSON with Flattening

**Source JSON**:

```json
{
  "user_id": 100,
  "profile": {
    "age": 30,
    "city": "Seattle"
  },
  "purchases": [
    {"item": "book", "amount": 20},
    {"item": "laptop", "amount": 1200}
  ]
}
```

**Flattened Table**:

```
user_id | age | city    | item   | amount
--------|-----|---------|--------|-------
100     | 30  | Seattle | book   | 20
100     | 30  | Seattle | laptop | 1200
```

**PySpark Code**:

```python
from pyspark.sql.functions import explode, col

df = spark.read.json("s3://bucket/data.json")

flattened = df.select(
    col("user_id"),
    col("profile.age"),
    col("profile.city"),
    explode(col("purchases")).alias("purchase")
).select(
    "user_id",
    "age",
    "city",
    col("purchase.item"),
    col("purchase.amount")
)
```

### Example 3: Nested JSON Preserved

**Same Source**, but preserved as nested:

**Table Schema**:

```sql
CREATE TABLE user_purchases (
  user_id BIGINT,
  profile STRUCT<age: INT, city: STRING>,
  purchases ARRAY<STRUCT<item: STRING, amount: DECIMAL(10,2)>>
)
```

**Query Example**:

```sql
-- Get users from Seattle who bought laptops
SELECT
  user_id,
  profile.age,
  purchase.item,
  purchase.amount
FROM user_purchases
CROSS JOIN UNNEST(purchases) AS t(purchase)
WHERE profile.city = 'Seattle'
  AND purchase.item = 'laptop';
```

## Evaluation Criteria

### Schema Evolution

**Detection**:

- Compares source schema to existing table schema
- Identifies new, missing, and changed columns
- Reports differences clearly to user

**Automatic Handling**:

- New columns: Automatically executes ALTER TABLE ADD COLUMNS
- Missing columns: Uses NULL or asks user
- Type changes: Routes to type conflict resolution

**Execution**:

- ALTER TABLE commands are syntactically correct
- Uses appropriate Iceberg/S3 Tables syntax
- Verifies changes applied successfully

### Nested JSON

**Detection**:

- Identifies STRUCT and ARRAY types in source
- Determines nesting depth
- Lists all nested fields clearly

**User Choice**:

- Presents flatten vs preserve options
- Explains pros/cons of each approach
- Waits for user decision

**Implementation**:

- Flatten: Provides complete PySpark/SQL with explode for arrays
- Preserve: Creates correct DDL with nested types
- Validates nested schema is correct

**Query Examples**:

- Shows how to query nested data
- Demonstrates struct field access (e.g., `customer.name`)
- Shows UNNEST/explode for arrays

## Common Mistakes to Avoid

Recreating entire table when only ALTER TABLE ADD COLUMNS is needed
Silently using NULL for missing columns without informing user
Not asking user how to handle nested structures (flatten vs preserve)
Incomplete flattening code (missing some nested fields)
Incorrect DDL for nested types (wrong syntax)
Not validating that ALTER TABLE succeeded
Exploding arrays without explaining it creates multiple rows
Not providing query examples for nested data access
