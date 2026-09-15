# Streaming tables for Apache Iceberg on S3 Tables

Streaming tables deliver records from a Kinesis stream to Apache Iceberg tables on S3 Tables. Serverless, no consumer management, 5-minute minimum data freshness, exactly-once delivery to Iceberg. Records are converted to Parquet with inline compaction, and become queryable in Athena, EMR, Redshift, Spark, or Managed Service for Apache Flink within minutes.

See [monitoring-security-and-limits.md](monitoring-security-and-limits.md) for metrics, alarms, channel states, encryption, quotas, and update constraints.

## Constraints

- **ON_DEMAND streams only** — provisioned-mode streams are not supported
- **Namespace and table names must be all-lowercase** — uppercase causes silent or hard-to-diagnose failures
- **KMS: `aws/kinesis` managed key is NOT allowed** — use a customer-managed KMS key with the full key ARN (aliases are not supported)
- Data freshness is **300–900 seconds**. No minimum throughput requirement for the 5-minute window
- **Append-only** — no CDC, upserts, or deletes
- Record format must be **`GSR_JSON`** or **`JSON`** (with `GSRSchemaARN` supplied) — `STRING` and `BYTE_ARRAY` are not supported for Iceberg
- **Schema evolution is not supported**
- Creates its own Iceberg tables — **cannot write to existing** Iceberg tables
- **No backfill** — only records produced after the channel is `ACTIVE` are delivered
- **Partitioning is required**, and only the `TIME_HOUR` transform is supported
- **DLQ is required** for Iceberg destinations
- Maximum **nesting depth of 16 levels** for structs, maps, and lists. Deeper schemas are rejected at channel creation
- **One S3 Tables channel and one S3 channel per stream** at launch — adjustable, and expected to rise over time. Channel reads consume **no shard capacity**

If the customer needs CDC, schema evolution, or transformations, recommend **Managed Service for Apache Flink** instead.

## Prerequisites

- KDS stream in ON_DEMAND mode
- Glue Schema Registry with a registered JSON Schema (draft-04 or draft-07) — the partition field must have `"format": "date-time"`
- S3 Table bucket in the **same Region** as the stream
- General-purpose S3 bucket for the DLQ — required
- Customer-managed KMS key (full ARN, no aliases)
- IAM service execution role (see IAM Setup below)

## Record Format

| `RecordFormat` | How it works |
|---|---|
| `GSR_JSON` | GSR-serialized JSON — records carry the GSR schema version UUID in the wire header. Producer must use the GSR serializer library. Schema is resolved per-record from the embedded UUID. |
| `JSON` | Plain JSON — producer writes raw JSON bytes. Requires `GSRSchemaARN` in `OutputFormat`. The service uses the referenced schema to map to the Iceberg schema. |

## Schema Requirements

Register a JSON Schema (draft-04 or draft-07) in Glue Schema Registry. The partition source field **MUST** have `"format": "date-time"` to map to Iceberg `timestamptz`. `PartitionSpec.Transform` must contain **exactly one** field — multi-column partitioning is not supported.

### JSON Schema to Iceberg type mapping

| JSON Schema | Condition | Iceberg type |
|---|---|---|
| `string` | plain | `string` |
| `string` | `"format": "date-time"` | `timestamptz` |
| `string` | `"format": "date"` | `date` |
| `string` | `"format": "time"` | `time` |
| `string` | `"format": "uuid"` | `uuid` |
| `string` | `"encoding": "byte"` or `"base64"` | `binary` |
| `integer` | `maximum`/`exclusiveMaximum` <= 2^31 | `int` |
| `integer` | exceeds 32-bit | `long` |
| `number` | with `multipleOf` | `decimal(38, scale)` — precision derived from `multipleOf` |
| `number` | plain | `double` |
| `boolean` | — | `boolean` |
| `object` | named properties | `struct` |
| `object` | `additionalProperties` | `map` with string keys |
| `array` | — | `list<E>` |
| `enum` | — | `string` |

### Field handling

- **Extra fields** not in the schema → silently dropped, not written to the table
- **Missing optional fields** → written as `null`
- **Missing required fields** → the whole record goes to the DLQ
- Fields in the schema's `required` array become non-nullable Iceberg columns
- The **partition key column is automatically required** regardless of the `required` array. Records missing the partition value go to the DLQ

### Example schema

```json
{
  "$schema": "http://json-schema.org/draft-04/schema#",
  "title": "Event",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "id":         {"type": "integer"},
    "event_time": {"type": "string", "format": "date-time"},
    "source":     {"type": "string"},
    "value":      {"type": "number"}
  },
  "required": ["id", "event_time", "value"]
}
```

Register in Glue:

```bash
aws glue create-registry --registry-name my-kds-registry --region $REGION

aws glue create-schema \
  --registry-id RegistryName=my-kds-registry \
  --schema-name my-event-schema \
  --data-format JSON \
  --compatibility NONE \
  --schema-definition '<schema JSON above>'
```

## IAM Setup

### Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "kinesis.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "ACCOUNT_ID"},
      "ArnLike": {"aws:SourceArn": "arn:aws:kinesis:REGION:ACCOUNT_ID:channel/*"}
    }
  }]
}
```

### Permission Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3TablesAccess",
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableBucket",
        "s3tables:GetTableMetadataLocation",
        "s3tables:UpdateTableMetadataLocation",
        "s3tables:GetNamespace",
        "s3tables:CreateNamespace",
        "s3tables:CreateTable",
        "s3tables:PutTableData",
        "s3tables:GetTableData",
        "s3tables:PutTableEncryption",
        "s3tables:PutTableRecordExpirationConfiguration",
        "s3tables:TagResource"
      ],
      "Resource": [
        "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/TABLE_BUCKET",
        "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/TABLE_BUCKET/table/*"
      ]
    },
    {
      "Sid": "DLQBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetBucketLocation",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:UploadPart",
        "s3:CompleteMultipartUpload",
        "s3:CreateMultipartUpload"
      ],
      "Resource": [
        "arn:aws:s3:::DLQ_BUCKET",
        "arn:aws:s3:::DLQ_BUCKET/*"
      ]
    },
    {
      "Sid": "GlueSchemaRegistryAccess",
      "Effect": "Allow",
      "Action": [
        "glue:GetRegistry",
        "glue:GetSchema",
        "glue:GetSchemaVersion",
        "glue:GetSchemaByDefinition",
        "glue:ListRegistries",
        "glue:ListSchemas"
      ],
      "Resource": [
        "arn:aws:glue:REGION:ACCOUNT_ID:registry/REGISTRY",
        "arn:aws:glue:REGION:ACCOUNT_ID:schema/REGISTRY/SCHEMA"
      ]
    },
    {
      "Sid": "KMSAccess",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID"
    },
    {
      "Sid": "KMSAccessDLQ",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/DLQ_KEY_ID",
      "Condition": {
        "StringEquals": {"kms:ViaService": "s3.REGION.amazonaws.com"},
        "StringLike": {"kms:EncryptionContext:aws:s3:arn": "arn:aws:s3:::DLQ_BUCKET/*"}
      }
    },
    {
      "Sid": "CloudWatchLogsAccess",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/kinesis/CHANNEL_NAME:*"
    }
  ]
}
```

**Statement notes:**

- `s3tables:PutTableEncryption` is required when the channel uses KMS encryption (the default). Without it, `CreateTable` succeeds but `PutTableEncryption` fails with `AccessDenied` — the namespace appears, the table never does, and the channel stays `ACTIVE`.
- `s3tables:PutTableRecordExpirationConfiguration` is required.
- `KMSAccess` covers the S3 Tables destination and needs **no** `kms:ViaService` condition, unlike S3 destinations. The KMS `KeyId` must be the **full key ARN**, not an alias.
- `KMSAccessDLQ` is required when the DLQ bucket uses SSE-KMS. The DLQ is a standard S3 bucket, so its key is reached via `kms:ViaService: s3.REGION.amazonaws.com`. Omit only if the DLQ uses SSE-S3 (AES-256).
- `GlueSchemaRegistryAccess` — all listed actions are needed; the service resolves schemas both by ARN and by definition.
- `CloudWatchLogsAccess` is required whenever delivery logging is enabled.

### KMS key policy for S3 Tables maintenance

When the table bucket is encrypted with a customer-managed KMS key, grant the S3 Tables maintenance service principal access in the **KMS key policy** — the execution role's IAM policy is not sufficient, because background compaction and snapshot maintenance run as `maintenance.s3tables.amazonaws.com`, not as the execution role:

```json
{
  "Sid": "AllowS3TablesMaintenance",
  "Effect": "Allow",
  "Principal": {"Service": "maintenance.s3tables.amazonaws.com"},
  "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
  "Resource": "*",
  "Condition": {
    "StringEquals": {"aws:SourceAccount": "ACCOUNT_ID"},
    "ArnLike": {"aws:SourceArn": "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/TABLE_BUCKET*"}
  }
}
```

Add the trailing `*` to the table bucket ARN in `aws:SourceArn` — the maintenance service's source ARN is table-level (`bucket/TABLE_BUCKET/table/TABLE_ID`), not bucket-level, so an exact bucket ARN does not match.

### Cross-account table buckets

Cross-account delivery is supported within the same Region. The destination account must attach a table bucket resource policy granting the source account's execution role access:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "CrossAccountTableBucketAccess",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::SOURCE_ACCOUNT_ID:role/EXECUTION_ROLE_NAME"},
    "Action": [
      "s3tables:GetTable",
      "s3tables:GetTableBucket",
      "s3tables:GetTableMetadataLocation",
      "s3tables:UpdateTableMetadataLocation",
      "s3tables:GetNamespace",
      "s3tables:CreateNamespace",
      "s3tables:CreateTable",
      "s3tables:PutTableData"
    ],
    "Resource": [
      "arn:aws:s3tables:REGION:DEST_ACCOUNT_ID:bucket/TABLE_BUCKET",
      "arn:aws:s3tables:REGION:DEST_ACCOUNT_ID:bucket/TABLE_BUCKET/table/*"
    ]
  }]
}
```

## Create the Channel

### 1. Create supporting resources

```bash
# S3 Tables bucket
aws s3tables create-table-bucket --name my-table-bucket --region $REGION

# DLQ bucket
aws s3 mb s3://my-kds-iceberg-dlq-$ACCOUNT --region $REGION

# CW log group — create before the channel
aws logs create-log-group \
  --log-group-name "/aws/kinesis/my-iceberg-channel" \
  --region $REGION
aws logs put-retention-policy \
  --log-group-name "/aws/kinesis/my-iceberg-channel" \
  --retention-in-days 30 \
  --region $REGION
```

### 2. Create the channel

Pass `--service-execution-role-arn`, `--stream-configuration-list`, `--s3-tables-destination-configuration`, and `--logging-configuration` as separate top-level parameters.

```bash
cat > stream-config.json << 'EOF'
[{
  "StreamARN": "STREAM_ARN",
  "RecordConfiguration": {
    "RecordFormatType": "GSR_JSON",
    "GSRSchemaARN": "arn:aws:glue:REGION:ACCOUNT_ID:schema/my-kds-registry/my-event-schema"
  }
}]
EOF

cat > s3-tables-dest.json << 'EOF'
{
  "DataFreshnessInSeconds": 300,
  "DeadLetterQueueS3Configuration": {
    "BucketARN": "arn:aws:s3:::my-kds-iceberg-dlq-ACCOUNT_ID",
    "ExpectedBucketOwner": "ACCOUNT_ID",
    "ErrorOutputPrefix": "errors/my-iceberg-channel/"
  },
  "S3TablesConfigurationList": [{
    "TableBucketARN": "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/my-table-bucket",
    "Namespace": "my_namespace",
    "TableName": "my_table",
    "CompressionType": "ZSTD",
    "PartitionSpec": {
      "PartitionFields": [{"Transform": "TIME_HOUR", "SourceName": "event_time"}]
    }
  }]
}
EOF

cat > logging.json << 'EOF'
{"CloudWatchLogs": {"Enabled": true, "LogGroupName": "/aws/kinesis/my-iceberg-channel", "LogStreamName": "DestinationDelivery"}}
EOF

aws kinesis create-channel \
  --region $REGION \
  --channel-name my-iceberg-channel \
  --service-execution-role-arn $SER_ARN \
  --stream-configuration-list file://stream-config.json \
  --s3-tables-destination-configuration file://s3-tables-dest.json \
  --logging-configuration file://logging.json
```

`ExpectedBucketOwner` (12-digit account ID) is required on `DeadLetterQueueS3Configuration` with no default. `CompressionType` is required on each `S3TablesConfigurationList` entry (`NONE`, `ZSTD`, or `SNAPPY`). To encrypt with a CMK, add a separate top-level `--encryption-configuration '{"EncryptionType": "KMS", "KeyId": "arn:aws:kms:..."}'` (full key ARN, not alias).

For plain JSON producers, set `"RecordFormatType": "JSON"` and keep `GSRSchemaARN` — it is required for both Iceberg formats.

### 3. Wait for ACTIVE

```bash
aws kinesis describe-channel \
  --region $REGION \
  --channel-arn $CHANNEL_ARN \
  --query 'ChannelDescription.ChannelStatus'
```

Only produce records after `ACTIVE` — records sent before that are not delivered, and there is no backfill.

### 4. Produce GSR-serialized records

Use the Glue Schema Registry serializer library so each record carries the schema version UUID in its header.

```python
from aws_schema_registry import SchemaRegistryClient, KafkaSerializer, DataAndSchema
from aws_schema_registry.jsonschema import JsonSchema
import boto3

session = boto3.Session(region_name=REGION)
registry_client = SchemaRegistryClient(session.client("glue"), registry_name="my-kds-registry")
serializer = KafkaSerializer(
    client=registry_client,
    schema_naming_strategy=lambda topic, is_key, schema: "my-event-schema",
)
json_schema = JsonSchema(SCHEMA_DEF)

record = {"id": 1, "event_time": "2026-07-09T20:00:00Z", "source": "app", "value": 1.5}
gsr_bytes = serializer.serialize(
    topic=STREAM_NAME,
    data_and_schema=DataAndSchema(data=record, schema=json_schema),
)
session.client("kinesis").put_record(
    StreamName=STREAM_NAME, Data=gsr_bytes, PartitionKey="1"
)
```

Sending plain JSON to a `GSR_JSON` channel DLQs with `INVALID_SCHEMA`. Sending GSR bytes to a `JSON` channel DLQs with `DESERIALIZATION_ERROR`.

## Channel Management

All lifecycle calls except `create-channel` and `list-channels` identify the channel by `--channel-arn` alone — not stream ARN + channel name.

```bash
# Describe
aws kinesis describe-channel --region $REGION --channel-arn $CHANNEL_ARN

# List channels on a stream
aws kinesis list-channels --region $REGION --stream-filter "{\"StreamARN\": \"$STREAM_ARN\"}"

# Update — only DataFreshnessInSeconds and logging are mutable
aws kinesis update-channel --region $REGION \
  --channel-arn $CHANNEL_ARN \
  --s3-tables-destination-configuration '{"DataFreshnessInSeconds": 600}'

# Delete — already-delivered data is NOT removed
aws kinesis delete-channel --region $REGION \
  --channel-arn $CHANNEL_ARN
```

Delete all channels on a stream before deleting the stream.

## Verify Delivery

```bash
# Namespace appears within ~1 min of the first delivery attempt
aws s3tables list-namespaces --table-bucket-arn $TABLE_BUCKET_ARN --region $REGION

# Table appears after the first successful delivery cycle
aws s3tables list-tables --table-bucket-arn $TABLE_BUCKET_ARN \
  --namespace my_namespace --region $REGION

# Failed records
aws s3 ls s3://my-kds-iceberg-dlq-$ACCOUNT/errors/ --recursive

# Delivery errors
aws logs filter-log-events \
  --log-group-name "/aws/kinesis/my-iceberg-channel" --region $REGION
```

### Querying with Athena

Grant Lake Formation permissions first:

```bash
aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier="arn:aws:iam::ACCOUNT_ID:role/QUERY_ROLE" \
  --resource '{"Database":{"CatalogId":"ACCOUNT_ID:s3tablescatalog/TABLE_BUCKET","Name":"my_namespace"}}' \
  --permissions DESCRIBE SELECT

aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier="arn:aws:iam::ACCOUNT_ID:role/QUERY_ROLE" \
  --resource '{"Table":{"CatalogId":"ACCOUNT_ID:s3tablescatalog/TABLE_BUCKET","DatabaseName":"my_namespace","Name":"my_table"}}' \
  --permissions SELECT DESCRIBE
```

```sql
SELECT * FROM "s3tablescatalog/TABLE_BUCKET"."my_namespace"."my_table" LIMIT 10;
```

## Table Format and Maintenance

Tables created by a channel are **managed and read-only** — do not write to them or alter their schema directly. Channel-managed table properties control write behavior, compaction, and metadata management; do not modify them externally.

| Property | Value |
|---|---|
| Iceberg format version | v2 |
| Iceberg spec version | 1.9.0 |
| File format | Apache Parquet |
| Compression | ZSTD (data files), Snappy (metadata) |

S3 Tables handles **compaction**, **snapshot expiration**, and **unreferenced file cleanup** automatically. Keep these enabled — metadata growth from many small commits is a leading cause of rising `DataChannel.DataFreshness`.

Record expiration (TTL) is set on the table itself, not on the channel:

```bash
aws s3tables put-table-record-expiration-configuration ...
```

## Troubleshooting

| Symptom | Likely Cause | Action |
|---|---|---|
| Channel stuck in `CREATING`, then `FAILED` | Invalid role ARN, insufficient role permissions, destination in a different Region, or unresolvable GSR schema ARN | Read `ChannelStatusReason` from `describe-channel`. Fix, delete, recreate — `FAILED` is not recoverable |
| Namespace created, table never created | Missing `s3tables:PutTableEncryption` | Add it to the service role policy |
| Namespace and table created, but delivery cycles fail repeatedly with a generic `InternalError` in delivery logs | Table bucket uses a customer-managed KMS key without a key-policy grant for `maintenance.s3tables.amazonaws.com` | Check CloudTrail for `EventSource: s3tables.amazonaws.com`, `EventName: CreateTable` — the `BadRequestException` there names the missing grant. Add the KMS key-policy statement above |
| Channel `ACTIVE`, no data, no DLQ entries, no logs | Service role missing CloudWatch Logs or S3 Tables permissions | Check CloudTrail for `s3tables.*` and `logs.*` `AccessDenied` from the assumed role session |
| Records in DLQ | Schema mismatch, wrong type, missing required field, or producer not using the GSR serializer for `GSR_JSON` | Inspect DLQ keys and bodies for error codes; verify the partition field has `"format": "date-time"` |
| Rising `DataChannel.DataFreshness` | High partition count, metadata growth from many small commits, or low throughput against a low freshness setting | Enable S3 Tables maintenance; raise `DataFreshnessInSeconds` for low-throughput streams |
| Delivery stopped after a schema change | Schema evolution is unsupported — new-version records fail validation | Revert the producer schema, or delete and recreate the channel on the new schema |
| Channel suspended | Destination table deleted, bucket owner mismatch, or incompatible partition column | Cannot be resumed — create a new channel |
| `AccessDenied` on `sts:AssumeRole` | Trust policy misconfigured | Verify principal `kinesis.amazonaws.com` and that `aws:SourceAccount` / `aws:SourceArn` match the account and `channel/*` ARN |
| Channel not available for the stream | Stream is in provisioned mode | Switch the stream to On-Demand |
