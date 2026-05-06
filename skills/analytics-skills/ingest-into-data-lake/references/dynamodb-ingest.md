# DynamoDB Ingest

Import DynamoDB tables into the data lake. DynamoDB is unique among sources: no Glue connection needed, schemaless items, and no natural watermark column.

## Contents

- [Method Selection](#method-selection)
- [Native Export (Path A)](#native-export-path-a)
- [Glue Direct Read (Path B)](#glue-direct-read-path-b)
- [Schema Flattening](#schema-flattening)
- [Incremental Strategies](#incremental-strategies)
- [Throughput Guidance](#throughput-guidance)
- [Gotchas](#gotchas)

## Method Selection

Assess the table:

```bash
aws dynamodb describe-table --table-name <TABLE>
```

Note item count, table size, billing mode, and PITR status.

| Table size | Method | Why |
|---|---|---|
| Small (<10K items, <1 GB) | Glue direct read | Simple, low throughput impact |
| Medium (10K-100M items, 1-100 GB) | Native export | No read capacity consumed |
| Large (>100M items, >100 GB) | Native export | Glue direct read would throttle production |

## Native Export (Path A)

Recommended for medium/large tables. Uses no read capacity.

### Export Command

```bash
aws dynamodb export-table-to-point-in-time \
  --table-arn arn:aws:dynamodb:<REGION>:<ACCOUNT>:table/<TABLE> \
  --s3-bucket <EXPORT_BUCKET> \
  --s3-prefix exports/<TABLE>/ \
  --export-format DYNAMODB_JSON \
  --export-type FULL_EXPORT
```

Export formats:

- `DYNAMODB_JSON` (default) -- each item as JSON with type descriptors like `{"S": "value"}`
- `ION` -- Amazon Ion, more compact, handles binary natively

### Monitoring

```bash
aws dynamodb describe-export --export-arn <EXPORT_ARN>
```

States: `IN_PROGRESS`, `COMPLETED`, `FAILED`. Large tables take minutes to hours.

### Output Structure

```
s3://<bucket>/exports/<table>/AWSDynamoDB/<export-id>/
  manifest-summary.json
  manifest-files.json
  data/                    (gzipped JSON or Ion)
```

### Read Export in Glue

```python
export_df = spark.read.json("s3://<bucket>/exports/<table>/AWSDynamoDB/<export-id>/data/")
# Items are nested in type descriptors -- flatten per Schema Flattening below
```

Native export items are wrapped in DynamoDB type descriptors (`{"S": "value"}`, `{"N": "123"}`). Unwrap before flattening:

```python
# Native export items are wrapped in type descriptors -- unwrap before flattening:
flat_df = export_df.select(
    col("Item.pk.S").alias("partition_key"),
    col("Item.name.S").alias("name"),
    col("Item.age.N").cast("bigint").alias("age")
)
```

### Incremental Export

Requires PITR enabled on the source table.

```bash
aws dynamodb export-table-to-point-in-time \
  --table-arn <arn> \
  --s3-bucket <bucket> \
  --export-type INCREMENTAL_EXPORT \
  --incremental-export-specification '{"ExportFromTime":"<last>","ExportToTime":"<now>","ExportViewType":"NEW_AND_OLD_IMAGES"}'
```

## Glue Direct Read (Path B)

For small tables. No connection needed -- Glue reads DynamoDB via AWS APIs with the Glue job role's permissions.

```python
dynamodb_df = glueContext.create_dynamic_frame.from_options(
    connection_type="dynamodb",
    connection_options={
        "dynamodb.input.tableName": "<TABLE>",
        "dynamodb.throughput.read.percent": "0.5"
    }
).toDF()

# After flattening, write to target (see iceberg-catalog-config-and-usage.md for path syntax)
flat_df.writeTo("s3tablescatalog.<namespace>.<table>").append()
```

Options:

| Option | Default | Purpose |
|---|---|---|
| `dynamodb.throughput.read.percent` | 0.5 | Fraction of RCUs to consume (0.1-1.0) |
| `dynamodb.splits` | auto | Parallel scan segments |
| `dynamodb.input.tableName` | required | Table name |

## Schema Flattening

Applies to Glue direct-read (Path B) output. For native export (Path A) output, use the type-descriptor unwrapping pattern shown above.

DynamoDB type to Iceberg:

| DDB | Iceberg | Notes |
|---|---|---|
| `S` | STRING | |
| `N` | BIGINT, DOUBLE, or DECIMAL | Inspect values |
| `BOOL` | BOOLEAN | |
| `B` | BINARY | Rarely useful |
| `M` | STRUCT or flatten to columns | |
| `L` | ARRAY or JSON STRING | |
| `SS` / `NS` | ARRAY&lt;STRING&gt; / ARRAY&lt;DOUBLE&gt; | |

### Strategy options

**Top-level only (simplest):**

```python
flat_df = dynamodb_df.select(
    col("pk").alias("partition_key"),
    col("name").cast("string"),
    col("created_at").cast("timestamp")
)
```

**Flatten one level:**

```python
flat_df = dynamodb_df.select(
    col("pk").alias("user_id"),
    col("profile.first_name").alias("first_name"),
    col("address.city").alias("city")
)
```

**Preserve as STRUCT:**

```python
flat_df = dynamodb_df.select(col("pk"), col("profile"), col("tags"))
```

**Serialize complex types to JSON:**

```python
from pyspark.sql.functions import to_json
flat_df = dynamodb_df.select(col("pk"), to_json(col("metadata")).alias("metadata_json"))
```

### Sample items for schema inference

```bash
aws dynamodb scan --table-name <TABLE> --limit 10 --output json
```

Or in Spark:

```python
sample = dynamodb_df.limit(100).toPandas()
all_columns = set()
for _, row in sample.iterrows():
    all_columns.update(row.dropna().index.tolist())
```

### Missing attributes

```python
from pyspark.sql.functions import coalesce, lit
flat_df = dynamodb_df.select(
    col("pk"),
    coalesce(col("email"), lit("")).alias("email"),
    coalesce(col("status"), lit("unknown")).alias("status")
)
```

## Incremental Strategies

| Strategy | Latency | Read impact | Best for |
|---|---|---|---|
| Scheduled full export | Hours | None | Large tables, daily freshness |
| Incremental export | Minutes-hours | None | Medium tables with PITR |
| DynamoDB Streams + Lambda | Seconds | None | Near-real-time |
| Application watermark | Minutes | Some | Tables with `last_modified` attribute |
| Full refresh via Glue | Minutes | High | Small tables (<10K items) |

**Scheduled full export:** EventBridge rule triggers Lambda that runs `export-table-to-point-in-time` then a Glue job. Simple, captures deletes.

**DynamoDB Streams:** Enable with `--stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES`. Lambda consumes stream, writes to S3 or target. 24-hour stream retention -- Lambda must keep up.

**Application watermark:** If items have `last_modified` attribute, filter in Glue: `dynamodb_df.filter(f"last_modified > '{last_watermark}'")`. Requires app cooperation and consumes read capacity.

**Full refresh:** For small tables, `dynamodb_df.writeTo(target).using("iceberg").createOrReplace()`. Do NOT use `overwritePartitions()` -- it only replaces partitions present in the DataFrame, leaving deleted items as stale data.

## Throughput Guidance

| Billing mode | Recommendation |
|---|---|
| On-demand | `read.percent` = 0.5 or lower |
| Provisioned | `read.percent` = 0.25-0.5; avoid peak hours |
| Large table (any mode) | Use native export instead |

## Gotchas

- Native export consumes no read capacity -- always prefer for tables over 1 GB
- Glue direct reads with high `read.percent` can throttle production traffic
- DynamoDB Number is arbitrary precision -- decide BIGINT vs DECIMAL based on actual values
- Binary (`B`) attributes rarely useful in analytics -- exclude unless required
- DynamoDB Streams retention is 24 hours -- if the consumer falls behind, data is lost
- Incremental export requires PITR enabled
- `overwritePartitions()` does NOT delete partitions missing from the source DataFrame
