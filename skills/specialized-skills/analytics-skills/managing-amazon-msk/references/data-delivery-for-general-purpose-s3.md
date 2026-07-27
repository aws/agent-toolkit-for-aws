# Data Delivery for General Purpose S3 Buckets

Data Delivery for General Purpose S3 Buckets for Amazon MSK Express brokers delivers topic data from Express brokers to a general-purpose S3 bucket as objects, with configurable compression, storage class, and output key layout.

> **Note:** Records are batched into S3 objects — multiple Kafka records land in a single S3 object. The output key template determines the key for each object, and the `!{sequence-number}` token provides uniqueness across objects within the same prefix.

## Data Delivery for General Purpose S3 Buckets Constraints

Check Data Delivery for General Purpose S3 Buckets documentation for constraints. Some key constraints are:

- Data Delivery for General Purpose S3 Buckets is ONLY available on **Express brokers** — Standard brokers and MSK Serverless are NOT supported
- Data freshness is **5–15 minutes** (minimum 300 seconds). For the 5-minute minimum, the topic must produce at least **2.4 MB/s** uncompressed data
- **No backfill** — only records produced AFTER Data Delivery for General Purpose S3 Buckets is enabled are delivered

If the user needs any of the above functionality, recommend **Managed Service for Apache Flink** instead. Data Delivery for General Purpose S3 Buckets is the most cost-effective way to deliver data to General Purpose S3 Buckets, so if it can be used it should be preferred in general.

## Prerequisites

- MSK Provisioned cluster with **Express brokers**
- Kafka topic producing data (JSON, ByteArray, or String)
- General-purpose S3 bucket for delivery
- S3 bucket for dead-letter queue (DLQ) — required

## Input Formats

| Format | Description |
|---|---|
| `JSON` | Plain JSON objects |
| `ByteArray` | Raw bytes written as-is |
| `String` | String data written as-is |

No schema registry is required for S3 bucket delivery.

## Destination Options

> Supported values for `compressionType` and `storageClass` may change over time. Run `aws kafka create-channel help` or check the [CreateChannel API reference](https://docs.aws.amazon.com/msk/latest/APIReference/API_CreateChannel.html) for the latest accepted values.

| Option | Values |
|---|---|
| `compressionType` | `NONE`, `GZIP` |
| `storageClass` | `STANDARD`, `STANDARD_IA`, `INTELLIGENT_TIERING`, `GLACIER_IR` |
| `outputPrefix` | String prepended to key template |
| `outputKeyTemplate` | Template with variables (see below) |

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
            "Sid": "DeliveryBucketList",
            "Effect": "Allow",
            "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:GetBucketLocation"],
            "Resource": ["arn:aws:s3:::BUCKET", "arn:aws:s3:::BUCKET/*"]
        },
        {
            "Sid": "DeliveryBucketWrite",
            "Effect": "Allow",
            "Action": [
                "s3:UploadPart", "s3:CompleteMultipartUpload", "s3:CreateMultipartUpload",
                "s3:PutObject", "s3:ListMultipartUploads", "s3:ListMultipartUploadParts"
            ],
            "Resource": "arn:aws:s3:::BUCKET/PREFIX*"
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
            "Sid": "KMSAccess",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
            "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
            "Condition": {
                "StringEquals": {"kms:ViaService": "s3.REGION.amazonaws.com"},
                "StringLike": {"kms:EncryptionContext:aws:s3:arn": "arn:aws:s3:::BUCKET/PREFIX*"}
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
            "Resource": "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/msk/data-delivery/CHANNEL_NAME:*"
        }
    ]
}
```

`CloudWatchLogsAccess` is required whenever CloudWatch Logs delivery logging is enabled (the default) — without it the service role cannot write delivery logs and failures stay invisible. If you route delivery logs to S3 or Firehose instead, swap this for the corresponding `s3:PutObject` (log bucket) or `firehose:PutRecord`/`firehose:PutRecordBatch` permissions per the Delivery Logging section.

`KMSAccess` covers the delivery bucket (its `kms:EncryptionContext` condition is scoped to `BUCKET/PREFIX*`). `KMSAccessDLQ` is required when the DLQ bucket uses SSE-KMS — the delivery-bucket condition does not cover the DLQ, so without this statement the service role gets `AccessDenied` writing failed records to an SSE-KMS DLQ. Both KMS statements are recommended for production — omit only if the corresponding bucket relies on SSE-S3 (AES-256) default encryption. SSE-KMS (or at minimum SSE-S3) should always be enabled on both the delivery and DLQ buckets.

## Create the Channel

**Prerequisite: create the CloudWatch log group first.** The log group referenced by `LoggingInfo.CloudWatchLogs.LogGroup` must exist *before* `create-channel` is called. MSK will not auto-create it, and `create-channel` will fail if the group is missing.

```bash
# 1. Create the log group up front
aws logs create-log-group --log-group-name "/aws/msk/data-delivery/CHANNEL_NAME"

# 2. Create the channel
aws kafka create-channel \
    --channel-name "CHANNEL_NAME" \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --topic-configuration-list '[{
        "TopicArn": "arn:aws:kafka:REGION:ACCOUNT_ID:topic/CLUSTER/ID/TOPIC",
        "RecordConverter": {"ValueConverter": "JSON"}
    }]' \
    --s3-destination-configuration '{
        "DataFreshnessInSeconds": 300,
        "DeadLetterQueueS3": {
            "BucketArn": "arn:aws:s3:::DLQ_BUCKET",
            "ErrorOutputPrefix": "dlq/"
        },
        "ServiceExecutionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/ROLE",
        "Storage": {
            "BucketArn": "arn:aws:s3:::DELIVERY_BUCKET",
            "CompressionType": "GZIP",
            "OutputPrefix": "data/",
            "OutputKeyTemplate": "!{channel-id}/!{topic-name}/!{yyyy}/!{MM}/!{dd}/!{HH}/!{partition-id}+!{sequence-number}",
            "StorageClass": "STANDARD"
        }
    }' \
    --logging-info '{
        "CloudWatchLogs": {"Enabled": true, "LogGroup": "/aws/msk/data-delivery/CHANNEL_NAME"},
        "S3": {"Enabled": true, "Bucket": "LOG_BUCKET", "Prefix": "msk-channel-logs/"},
        "Firehose": {"Enabled": false, "DeliveryStream": ""}
    }'
```

For `ByteArray` or `String` input, change `RecordConverter.ValueConverter` accordingly (`BYTE_ARRAY` / `STRING`).

## Delivery Logging

**Always enable at least one logging destination** on the channel. Without it, delivery errors (`AccessDenied` on the delivery bucket / DLQ, format-mismatch failures, KMS `Decrypt` failures on the delivery-bucket key, template-rendering errors) are invisible — the only visible symptom is missing objects at the expected S3 key. Logging is also a prerequisite for [streaming-tables-troubleshooting.md](streaming-tables-troubleshooting.md).

The `--logging-info` field on `aws kafka create-channel` accepts three independent destinations — any subset can be enabled at once:

| Destination | JSON key | Required fields | When to use |
|---|---|---|---|
| CloudWatch Logs | `CloudWatchLogs` | `Enabled`, `LogGroup` (must exist before create-channel) | Default choice — interactive querying via Logs Insights, alarms on log patterns |
| Amazon S3 | `S3` | `Enabled`, `Bucket`, `Prefix` (optional) | Long-term retention, Athena/downstream analysis |
| Firehose | `Firehose` | `Enabled`, `DeliveryStream` | Fan-out to OpenSearch / Splunk / third-party SIEMs |

**Log group prerequisite:** MSK does not auto-create the CloudWatch log group. Create it in advance with `aws logs create-log-group --log-group-name "<name>"` and, for production, set a retention policy (`aws logs put-retention-policy --log-group-name "<name>" --retention-in-days 30`). Passing a nonexistent log group to `create-channel` returns a validation error.

**IAM:** The service role must be able to write to whichever destinations are enabled — for CloudWatch Logs: `logs:CreateLogStream`, `logs:PutLogEvents` on the target log group; for S3: `s3:PutObject` on the log bucket/prefix (plus `kms:GenerateDataKey` if SSE-KMS); for Firehose: `firehose:PutRecord`, `firehose:PutRecordBatch` on the delivery stream. Use a **separate** log bucket/prefix from the delivery bucket — routing logs through the same prefix that stores delivered records makes downstream analytics unreliable.

**Encryption:** Enable SSE-KMS on the CloudWatch log group (via `aws logs associate-kms-key`) and the S3 log bucket — delivery error records may contain payload fragments and topic names.

**Logging is set at channel creation and is not updatable.** `aws kafka update-channel` only accepts `--iceberg-destination-update` and `--s3-destination-update` with a single field (`DataFreshnessInSeconds`). To change logging destinations, delete and recreate the channel.

## Output Key Template

### Variables

| Variable | Description |
|---|---|
| `!{channel-id}` | Channel ID |
| `!{topic-name}` | Source Kafka topic |
| `!{partition-id}` | Kafka partition ID |
| `!{kafka-offset}` | Kafka offset |
| `!{sequence-number}` | Monotonic per-record sequence |
| `!{yyyy}`, `!{YY}`, `!{MM}`, `!{dd}`, `!{HH}`, `!{mm}` | Time components |

### Rules

- Must contain exactly ONE uniqueness token: `!{sequence-number}` OR `!{kafka-offset}` (mutually exclusive)
- Uniqueness token must be in the **last** `/`-separated segment
- If using `!{kafka-offset}`, must also include `!{partition-id}`
- Must NOT end with `/`
- Max 1024 chars (prefix + template combined)
- Allowed literals: `[a-zA-Z0-9/_\-.+=]` (no spaces)
- No path traversal (`..` or `./`)

### Valid examples

```
!{channel-id}/!{yyyy}/!{MM}/!{dd}/!{sequence-number}
topic=!{topic-name}/!{partition-id}/!{kafka-offset}
data/!{channel-id}/!{HH}/!{sequence-number}.json
```

### Invalid examples

| Template | Why |
|---|---|
| `!{yyyy}/!{MM}/` | Ends with `/` |
| `!{channel-id}/!{topic-name}` | No uniqueness token |
| `!{sequence-number}-!{kafka-offset}` | Both tokens (mutually exclusive) |
| `!{kafka-offset}` | Missing `partition-id` |

## Monitoring

Data Delivery emits its own CloudWatch metrics in the `AWS/Kafka` namespace with dimensions `ClusterName`, `ChannelName`, `Topic`. Recommended alarms — `DeliveryToS3.DataFreshness` above the configured freshness interval, `FailedRecordCount` > 0 (records not conforming to input format), and `DLQDeliverySuccess` > 0 (records routed to DLQ). Full metric list, alarm patterns, and troubleshooting steps live in [streaming-tables-troubleshooting.md](streaming-tables-troubleshooting.md). Do not fall back to generic Express cluster health metrics or S3-bucket-object counts for delivery monitoring — the channel-scoped metrics above are the correct primitives.

## Channel Management

Every channel operation is scoped to a specific cluster — `--cluster-arn` is required on `describe-channel`, `list-channels`, `update-channel`, and `delete-channel`.

```bash
# Check state (both flags required)
aws kafka describe-channel \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --channel-arn "CHANNEL_ARN"

# List channels on a cluster. Only --topic-name-filter is available server-side —
# filter by destination type client-side from the returned DestinationType field.
aws kafka list-channels \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --query "Channels[?DestinationType=='S3']"

# Update freshness — only DataFreshnessInSeconds is updatable
aws kafka update-channel \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --channel-arn "CHANNEL_ARN" \
    --s3-destination-update '{"DataFreshnessInSeconds": 600}'

# Delete (irreversible — already-delivered data is NOT deleted)
aws kafka delete-channel \
    --cluster-arn "arn:aws:kafka:REGION:ACCOUNT_ID:cluster/CLUSTER/ID" \
    --channel-arn "CHANNEL_ARN"
```

> You CANNOT update the topic, record converter, destination bucket/template, service role, or logging config. Only `DataFreshnessInSeconds` is mutable. Delete and recreate for anything else.

## Security Considerations

- Enable server-side encryption (SSE-KMS or SSE-S3) on both delivery and DLQ buckets
- Enable S3 access logging on the delivery bucket
- Apply bucket policies restricting access to authorized principals only
- DLQ bucket may contain sensitive customer data (PII, financial data) — encrypt and restrict access
- Encrypt CloudWatch Logs log groups that receive Data Delivery for General Purpose S3 Buckets delivery logs
- Use VPC endpoints for S3 where applicable to keep traffic off the public internet
- For additional hardening guidance, see the [MSK Security chapter](https://docs.aws.amazon.com/msk/latest/developerguide/security.html) and [Amazon S3 security best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
