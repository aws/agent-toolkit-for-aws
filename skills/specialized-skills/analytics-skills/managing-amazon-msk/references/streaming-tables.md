# Streaming Tables — Iceberg (S3 Tables) Delivery

Streaming Tables for Amazon MSK Express brokers delivers topic data from Express brokers to Apache Iceberg tables in S3 Table buckets. Serverless, no connector management, 5-minute minimum data freshness, auto-scaling to tens of GB/s.

## Streaming Tables for Apache Iceberg on S3 Tables Constraints

Check Streaming Tables documentation for constraints. Some key constraints are:

- Streaming Tables is ONLY available on **Express brokers** — Standard brokers and MSK Serverless are NOT supported
- Data freshness is **5–15 minutes** (minimum 300 seconds). For the 5-minute minimum, the topic must produce at least **2.4 MB/s** uncompressed data
- Streaming Tables is **append-only** — does not support CDC, upserts, or deletes
- Streaming Tables Iceberg destination supports **JSON input only** (plain JSON or GSR-serialized JSON) - does not support Avro/Protobuf input
- **Schema evolution is not supported**
- Streaming Tables creates its own Iceberg tables — it cannot write to **existing** Iceberg tables
- **No backfill** — only records produced AFTER Streaming Tables is enabled are delivered

If the user needs any of the above functionality, recommend **Managed Service for Apache Flink** instead. Streaming Tables are the most cost-effective way
to deliver data to Iceberg tables on S3 Tables, so if it can be used it should be preferred in general.

## Prerequisites

- MSK Provisioned cluster with **Express brokers**
- Kafka topic producing JSON data
- AWS Glue Schema Registry with registered JSON Schema (draft-04 or draft-07)
- S3 Table bucket in the **same Region** as the cluster

## Input Formats

| Format | How it works | When to use |
|---|---|---|
| `JSON` | Plain JSON. You provide a GSR schema ARN in channel config. | Producer writes plain JSON; schema managed externally |
| `JSON_SCHEMA_GSR` | GSR-serialized JSON with schema ID embedded per record. | Producer uses GSR serializer library |

> For `JSON_SCHEMA_GSR`, do NOT provide `schemaRegistryArn` or `schemaArn` in the source configuration — the schema ID is embedded in each record.

## Schema Requirements

**Partition constraint:** Register a JSON Schema (draft-04 or draft-07) in Glue Schema Registry. The partition source column **MUST** have `"format": "date-time"` to map to Iceberg `timestamptz`. `PartitionSpec.SourceList` must contain **exactly one** source column. Multi-column partitioning is not supported. Omitting `SourceList` or providing an empty array fails with `InvalidParameter: sourceList`.

### JSON Schema to Iceberg Type Mapping

| JSON Schema | Condition | Iceberg type |
|---|---|---|
| `string` | plain | `string` |
| `string` | `format: "date-time"` | `timestamptz` |
| `string` | `format: "date"` | `date` |
| `string` | `format: "time"` | `time` |
| `string` | `format: "uuid"` | `uuid` |
| `string` | `format: "byte"` / `contentEncoding: "base64"` | `binary` |
| `integer` | fits 32-bit | `int` |
| `integer` | exceeds 32-bit | `long` |
| `number` | with `multipleOf` | `decimal(38, scale)` |
| `number` | plain | `double` |
| `boolean` | — | `boolean` |
| `object` | named properties | `struct` |
| `object` | `additionalProperties` | `map<string, V>` |
| `array` | — | `list<E>` |

**Schema behavior:**

- Extra fields in source data → silently dropped
- Missing optional fields → written as `null`
- Missing required fields → record sent to DLQ
- Nesting limit: 16 levels max
- Partition column is automatically treated as required

**Example schema:**

```json
{
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "timestamp": {"type": "string", "format": "date-time"},
        "source": {"type": "string"},
        "value": {"type": "number"}
    },
    "required": ["id", "timestamp", "value"]
}
```

## IAM Setup

### Trust Policy

```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "kafka.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {"aws:SourceAccount": "ACCOUNT_ID"},
            "ArnLike": {"aws:SourceArn": "arn:aws:kafka:REGION:ACCOUNT_ID:channel/*"}
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
            "Sid": "S3TablesActions",
            "Effect": "Allow",
            "Action": [
                "s3tables:GetTable", "s3tables:GetTableMetadataLocation",
                "s3tables:UpdateTableMetadataLocation", "s3tables:CreateTable",
                "s3tables:PutTableData", "s3tables:CreateNamespace",
                "s3tables:GetTableData", "s3tables:GetTableBucket",
                "s3tables:TagResource", "s3tables:PutTableRecordExpirationConfiguration"
            ],
            "Resource": [
                "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/BUCKET_NAME",
                "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/BUCKET_NAME/table/*"
            ]
        },
        {
            "Sid": "DLQBucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket",
                "s3:ListBucketMultipartUploads", "s3:UploadPart",
                "s3:CompleteMultipartUpload", "s3:CreateMultipartUpload",
                "s3:ListMultipartUploadParts"
            ],
            "Resource": ["arn:aws:s3:::DLQ_BUCKET", "arn:aws:s3:::DLQ_BUCKET/*"]
        },
        {
            "Sid": "GlueSchemaRegistryAccess",
            "Effect": "Allow",
            "Action": [
                "glue:GetSchemaVersion", "glue:GetSchema", "glue:ListSchemas",
                "glue:GetRegistry", "glue:ListRegistries", "glue:GetSchemaByDefinition"
            ],
            "Resource": [
                "arn:aws:glue:REGION:ACCOUNT_ID:schema/REGISTRY/SCHEMA",
                "arn:aws:glue:REGION:ACCOUNT_ID:registry/REGISTRY"
            ]
        },
        {
            "Sid": "KMSAccess",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
            "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
            "Condition": {
                "StringEquals": {"kms:ViaService": "s3tables.REGION.amazonaws.com"}
            }
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
            "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/msk/streaming-tables/CHANNEL_NAME:*"
        }
    ]
}
```

**Statement notes:** `S3TablesActions` required. `CloudWatchLogsAccess` required whenever CloudWatch Logs delivery logging is enabled (the default) — without it the service role cannot write delivery logs and failures stay invisible; swap for `s3:PutObject` (log bucket) or `firehose:PutRecord`/`firehose:PutRecordBatch` if you route delivery logs to S3 or Firehose instead. `DLQBucketAccess` required. `GlueSchemaRegistryAccess` required (for `JSON` input, only `glue:GetSchemaVersion` needed; for `JSON_SCHEMA_GSR`, include all). `KMSAccess` covers the S3 Tables destination (scoped via `kms:ViaService: s3tables.REGION.amazonaws.com`). `KMSAccessDLQ` is required when the DLQ bucket uses SSE-KMS — the DLQ is a regular S3 bucket, so its key must be reached via `kms:ViaService: s3.REGION.amazonaws.com`; without this statement the service role gets `AccessDenied` writing failed records to an SSE-KMS DLQ. Both KMS statements are recommended for production — omit only if the corresponding bucket relies on SSE-S3 (AES-256) default encryption. SSE-KMS (or at minimum SSE-S3) should always be enabled on both delivery and DLQ buckets.

**Cross-account:** If S3 Table bucket is in another account, the bucket owner must attach a table bucket policy granting the service role access.

## Create the Channel

**Prerequisite: create the CloudWatch log group first.** The log group referenced by `LoggingInfo.CloudWatchLogs.LogGroup` must exist *before* `create-channel` is called. MSK will not auto-create it, and `create-channel` will fail if the group is missing.

**Plain JSON input:**

```bash
# 1. Create the log group up front
aws logs create-log-group --log-group-name "/aws/msk/streaming-tables/CHANNEL_NAME"

# 2. Create the channel
aws kafka create-channel \
    --channel-name "CHANNEL_NAME" \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --topic-configuration-list '[{
        "TopicArn": "arn:aws:kafka:REGION:ACCOUNT_ID:topic/CLUSTER/ID/TOPIC",
        "RecordConverter": {"ValueConverter": "JSON"},
        "RecordSchema": {"GsrArn": "arn:aws:glue:REGION:ACCOUNT_ID:schema/REGISTRY/SCHEMA"}
    }]' \
    --iceberg-destination-configuration '{
        "AppendOnly": true,
        "SchemaEvolution": {"EnableSchemaEvolution": false},
        "Catalog": {
            "CatalogArn": "arn:aws:glue:REGION:ACCOUNT_ID:catalog/s3tablescatalog/BUCKET",
            "WarehouseLocation": "arn:aws:s3tables:REGION:ACCOUNT_ID:bucket/BUCKET"
        },
        "DataFreshnessInSeconds": 300,
        "DeadLetterQueueS3": {
            "BucketArn": "arn:aws:s3:::DLQ_BUCKET",
            "ErrorOutputPrefix": "dlq/"
        },
        "DestinationTableList": [{
            "DestinationDatabaseName": "DB_NAME",
            "DestinationTableName": "TABLE_NAME",
            "PartitionSpec": {
                "PartitionStrategy": "TIME_HOUR",
                "SourceList": [{"SourceName": "timestamp"}]
            }
        }],
        "TableCreation": {"EnableTableCreation": true},
        "ServiceExecutionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/ROLE",
        "CompressionType": "ZSTD"
    }' \
    --logging-info '{
        "CloudWatchLogs": {"Enabled": true, "LogGroup": "/aws/msk/streaming-tables/CHANNEL_NAME"},
        "S3": {"Enabled": true, "Bucket": "LOG_BUCKET", "Prefix": "msk-channel-logs/"},
        "Firehose": {"Enabled": false, "DeliveryStream": ""}
    }'
```

**GSR-serialized input** — same command but the topic entry uses `"RecordConverter": {"ValueConverter": "JSON_SCHEMA_GSR"}` and omits `RecordSchema` (the schema ID is embedded per-record).

## Delivery Logging

**Always enable at least one logging destination** on the channel. Without it, delivery errors (`AccessDenied` on S3 Tables / DLQ, schema-mapping failures, GSR access denials, KMS `Decrypt` failures) are invisible — the only visible symptom is missing rows in Iceberg. Logging is also a prerequisite for [streaming-tables-troubleshooting.md](streaming-tables-troubleshooting.md).

The `--logging-info` field on `aws kafka create-channel` accepts three independent destinations — any subset can be enabled at once:

| Destination | JSON key | Required fields | When to use |
|---|---|---|---|
| CloudWatch Logs | `CloudWatchLogs` | `Enabled`, `LogGroup` (must exist before create-channel) | Default choice — interactive querying via Logs Insights, alarms on log patterns |
| Amazon S3 | `S3` | `Enabled`, `Bucket`, `Prefix` (optional) | Long-term retention, Athena/downstream analysis |
| Firehose | `Firehose` | `Enabled`, `DeliveryStream` | Fan-out to OpenSearch / Splunk / third-party SIEMs |

**Log group prerequisite:** MSK does not auto-create the CloudWatch log group. Create it in advance with `aws logs create-log-group --log-group-name "<name>"` and, for production, set a retention policy (`aws logs put-retention-policy --log-group-name "<name>" --retention-in-days 30`). Passing a nonexistent log group to `create-channel` returns a validation error.

**IAM:** The service role must be able to write to whichever destinations are enabled — for CloudWatch Logs: `logs:CreateLogStream`, `logs:PutLogEvents` on the target log group; for S3: `s3:PutObject` on the log bucket/prefix (plus `kms:GenerateDataKey` if SSE-KMS); for Firehose: `firehose:PutRecord`, `firehose:PutRecordBatch` on the delivery stream.

**Encryption:** Enable SSE-KMS on the CloudWatch log group (via `aws logs associate-kms-key`) and the S3 log bucket — delivery error records may contain payload fragments and topic names.

**Logging is set at channel creation and is not updatable.** `aws kafka update-channel` only accepts `--iceberg-destination-update` and `--s3-destination-update` with a single field (`DataFreshnessInSeconds`). To change logging destinations, delete and recreate the channel.

## Verify and Query

```bash
# Check channel state (wait for ACTIVE) — both --cluster-arn and --channel-arn are required
aws kafka describe-channel \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --channel-arn "CHANNEL_ARN"
```

### Querying with Athena

Before querying Streaming Tables data with Athena, you must grant Lake Formation permissions to your query principal:

```bash
# Grant database-level access
aws lakeformation grant-permissions \
    --principal DataLakePrincipal="{\"DataLakePrincipalIdentifier\":\"arn:aws:iam::ACCOUNT_ID:role/QUERY_ROLE\"}" \
    --resource '{"Database":{"CatalogId":"ACCOUNT_ID:s3tablescatalog/BUCKET","Name":"DB_NAME"}}' \
    --permissions "DESCRIBE" "SELECT"

# Grant table-level access
aws lakeformation grant-permissions \
    --principal DataLakePrincipal="{\"DataLakePrincipalIdentifier\":\"arn:aws:iam::ACCOUNT_ID:role/QUERY_ROLE\"}" \
    --resource '{"Table":{"CatalogId":"ACCOUNT_ID:s3tablescatalog/BUCKET","DatabaseName":"DB_NAME","Name":"TABLE_NAME"}}' \
    --permissions "SELECT" "DESCRIBE"
```

Then query via Athena (after data freshness interval):

```sql
SELECT * FROM "s3tablescatalog/BUCKET"."DB_NAME"."TABLE_NAME" LIMIT 10;
```

For details on Lake Formation permissions with S3 Tables, see the [Athena S3 Tables documentation](https://docs.aws.amazon.com/athena/latest/ug/querying-s3-tables.html).

## Monitoring

Streaming Tables emits its own CloudWatch metrics in the `AWS/Kafka` namespace with dimensions `ClusterName`, `ChannelName`, `Topic`. Recommended alarms — `DeliveryToIceberg.DataFreshness` (or `DeliveryToS3.DataFreshness` for S3 destinations) above the configured freshness interval, `FailedRowCount` (Iceberg) / `FailedRecordCount` (S3) > 0, and `DLQDeliverySuccess` > 0. Full metric list, alarm patterns, and troubleshooting steps live in [streaming-tables-troubleshooting.md](streaming-tables-troubleshooting.md). Do not fall back to generic Express cluster health metrics or DIY S3-bucket-object alarms for Streaming Tables — the channel-scoped metrics above are the correct primitives.

## Throughput and Freshness

> These values are current as of launch. Check the [MSK Streaming Tables documentation](https://docs.aws.amazon.com/msk/latest/developerguide/data-channel.html) for the latest minimum throughput requirements per freshness interval.

| Data freshness | Min throughput |
|---|---|
| 5 minutes | 2.4 MB/s |
| 10 minutes | ~1.2 MB/s |
| 15 minutes | ~0.8 MB/s |

## Table Maintenance

Enable S3 Tables automated maintenance: **compaction**, **snapshot expiration**, **unreferenced file cleanup**. Optionally enable **record expiration** for TTL-based deletion.

- Iceberg table format version: 2, Parquet output. Check the current Iceberg version via `aws kafka describe-channel --cluster-arn <arn> --channel-arn <arn>` response or AWS documentation — it may be upgraded over time.
- Table is managed — read-only from your perspective (do not modify schema or write directly)

## Quotas

> Default quotas may change over time. Check current values via `aws service-quotas list-service-quotas --service-code kafka` or the AWS Service Quotas console.

| Resource | Default | Adjustable |
|---|---|---|
| Channels per cluster | 50 | Yes |
| Channels per topic | 10 | Yes |
| Data freshness | 5–15 min | No |

## Security Considerations

- Enable server-side encryption (SSE-KMS or SSE-S3) on both delivery (S3 Tables) and DLQ buckets
- Enable S3 bucket access logging on the DLQ bucket
- Apply S3 bucket policies to restrict access to authorized principals only
- DLQ contents may include sensitive customer data (PII, financial data) — restrict access and enable encryption
- Enable CloudWatch Logs encryption for log groups that receive Streaming Tables delivery logs
- Regularly audit IAM role policies and cross-account trust relationships
- Use VPC endpoints for S3 where applicable to keep traffic off the public internet
- For additional hardening guidance, see the [MSK Security chapter](https://docs.aws.amazon.com/msk/latest/developerguide/security.html) and [Amazon S3 security best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
