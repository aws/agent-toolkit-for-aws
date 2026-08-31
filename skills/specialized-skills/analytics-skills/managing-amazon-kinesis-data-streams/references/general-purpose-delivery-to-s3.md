# General purpose delivery to Amazon S3

Delivers records from a Kinesis stream to a general-purpose S3 bucket as objects, with configurable compression, storage class, and output key layout. Serverless, no consumer management, 5-minute minimum data freshness. Records are delivered in their **original source format** — no transformation is applied.

Records are batched into objects: multiple stream records land in a single S3 object, keyed by the output key template.

See [monitoring-security-and-limits.md](monitoring-security-and-limits.md) for metrics, alarms, channel states, encryption, quotas, and update constraints.

## Constraints

- **ON_DEMAND streams only** — provisioned-mode streams are not supported
- Data freshness is **300–900 seconds**. No minimum throughput requirement for the 5-minute window
- **No backfill** — only records produced after the channel is `ACTIVE` are delivered
- **No transformations, filtering, or CDC**
- Cross-Region delivery is not supported; the bucket must be in the stream's Region
- **One S3 channel and one S3 Tables channel per stream** at launch — adjustable, and expected to rise over time. Channel reads consume **no additional shard capacity**

If the customer needs transformations, filtering, or CDC, recommend **Managed Service for Apache Flink** instead.

## Prerequisites

- KDS stream in ON_DEMAND mode
- General-purpose S3 delivery bucket in the **same Region** as the stream
- General-purpose S3 bucket for the DLQ — optional here; if omitted, errors are written to the delivery bucket under an error prefix. Configure one explicitly so failures do not land among delivered records
- IAM service execution role (see IAM Setup below)
- Customer-managed KMS key if using SSE-KMS (recommended)

## Record Formats

| `RecordFormat` | Description |
|---|---|
| `BYTE_ARRAY` | Raw bytes written as-is — no schema |
| `STRING` | UTF-8 string records written as-is |
| `JSON` | Plain JSON records |
| `GSR_JSON` | GSR-serialized JSON — schema ID embedded per record; requires `GSRSchemaARN` |

Only `GSR_JSON` requires a schema registry. When the customer asks for "raw" delivery, byte-for-byte copies, or does not mention a specific serialization, use `BYTE_ARRAY` — it writes each record's bytes unmodified regardless of source encoding. Use `JSON` or `STRING` only when the customer explicitly describes their records as JSON or plain text.

## Destination Options

| Option | Values | Notes |
|---|---|---|
| `Compression` | `NONE`, `GZIP`, `ZSTD` | Required. `GZIP` balances ratio and speed; `ZSTD` gives a higher ratio with faster decompression |
| `StorageClass` | `STANDARD`, `INTELLIGENT_TIERING`, `GLACIER_IR` | Defaults to `STANDARD` |
| `OutputKeyTemplate` | Template string | Optional — a default is applied if omitted |
| `DataFreshnessInSeconds` | 300–900 | Defaults to 300 |

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
      "Sid": "DeliveryBucketList",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::DELIVERY_BUCKET",
        "arn:aws:s3:::DELIVERY_BUCKET/*"
      ]
    },
    {
      "Sid": "DeliveryBucketWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:UploadPart",
        "s3:CompleteMultipartUpload",
        "s3:CreateMultipartUpload",
        "s3:ListMultipartUploads",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": "arn:aws:s3:::DELIVERY_BUCKET/PREFIX*"
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
        "s3:CreateMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::DLQ_BUCKET",
        "arn:aws:s3:::DLQ_BUCKET/*"
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

- `KMSAccess` covers the delivery bucket. Grant it unconditionally — do not add a `kms:ViaService`/`EncryptionContext` condition. `CreateChannel` validates the role's KMS access with a direct KMS call, not one proxied through S3, so a `ViaService: s3.REGION.amazonaws.com` condition passes at runtime delivery but fails channel creation. Include `kms:DescribeKey` alongside `kms:Decrypt`/`kms:GenerateDataKey`.
- `KMSAccessDLQ` is required when the DLQ bucket uses SSE-KMS. Omit if the DLQ uses SSE-S3 (AES-256).
- The `aws/kinesis` managed key cannot be used for destination encryption — use a customer managed KMS key with its full ARN.
- `CloudWatchLogsAccess` is required whenever delivery logging is enabled. Without it, delivery errors are invisible.

### Cross-account delivery

Supported within the same Region. Attach a bucket policy on the destination bucket granting the source account's execution role `s3:PutObject` (plus the multipart actions above) on the delivery prefix.

## Create the Channel

### 1. Create supporting resources

```bash
aws s3 mb s3://my-kds-delivery-$ACCOUNT --region $REGION
aws s3 mb s3://my-kds-dlq-$ACCOUNT --region $REGION

# CW log group — create before the channel
aws logs create-log-group \
  --log-group-name "/aws/kinesis/my-s3-channel" --region $REGION
aws logs put-retention-policy \
  --log-group-name "/aws/kinesis/my-s3-channel" \
  --retention-in-days 30 --region $REGION
```

Configure SSE-KMS on both buckets.

### 2. Create the channel

Pass `--service-execution-role-arn`, `--stream-configuration-list`, `--s3-destination-configuration`, and `--logging-configuration` as separate top-level parameters. If `StorageConfiguration.OutputKeyTemplate` is set, write that JSON blob to a file and reference it with `file://` — the `!{...}` template syntax gets mangled by shell quoting (even single quotes) when passed inline. Other JSON blobs without `!{...}` can be passed inline or via file interchangeably.

```bash
cat > s3-dest.json << 'EOF'
{
  "DataFreshnessInSeconds": 300,
  "DeadLetterQueueS3Configuration": {
    "BucketARN": "arn:aws:s3:::my-kds-dlq-ACCOUNT_ID",
    "ExpectedBucketOwner": "ACCOUNT_ID",
    "ErrorOutputPrefix": "errors/my-s3-channel/"
  },
  "StorageConfiguration": {
    "BucketARN": "arn:aws:s3:::my-kds-delivery-ACCOUNT_ID",
    "ExpectedBucketOwner": "ACCOUNT_ID",
    "StorageClass": "STANDARD",
    "CompressionType": "GZIP",
    "OutputKeyTemplate": "data/!{channel-name}/!{yyyy}/!{MM}/!{dd}/!{HH}/!{channel-id}-!{mm}!{extension}"
  }
}
EOF

aws kinesis create-channel \
  --region $REGION \
  --channel-name my-s3-channel \
  --service-execution-role-arn $SER_ARN \
  --stream-configuration-list '[{"StreamARN": "'$STREAM_ARN'", "RecordConfiguration": {"RecordFormatType": "BYTE_ARRAY"}}]' \
  --s3-destination-configuration file://s3-dest.json \
  --logging-configuration '{"CloudWatchLogs": {"Enabled": true, "LogGroupName": "/aws/kinesis/my-s3-channel", "LogStreamName": "DestinationDelivery"}}'
```

`ExpectedBucketOwner` (12-digit account ID) is required on both `DeadLetterQueueS3Configuration` and `StorageConfiguration`. `CompressionType` (`NONE`/`GZIP`/`ZSTD`) is required inside `StorageConfiguration`. `OutputKeyTemplate` is optional there — see the Output Key Template section below for the supported variables.

For `STRING`, `JSON`, or `GSR_JSON`, set `RecordFormatType` accordingly in `stream-config.json`. For `GSR_JSON`, also add `"GSRSchemaARN": "arn:aws:glue:..."`.

### 3. Wait for ACTIVE

```bash
aws kinesis describe-channel \
  --region $REGION \
  --channel-arn $CHANNEL_ARN \
  --query 'ChannelDescription.ChannelStatus'
```

### 4. Produce test records

```bash
aws kinesis put-record \
  --region $REGION \
  --stream-arn $STREAM_ARN \
  --data "test-record" --partition-key "key1" \
  --cli-binary-format raw-in-base64-out
```

## Output Key Template

Default when `OutputKeyTemplate` is omitted:

```
kinesis-channel/!{channel-name}/!{channel-id}/!{yyyy}/!{MM}/!{dd}/!{HH}/!{channel-name}-!{channel-id}-!{yyyy}-!{MM}-!{dd}-!{HH}-!{mm}!{extension}
```

### Variables

| Variable | Description | Example |
|---|---|---|
| `!{channel-name}` | Channel name | `my-channel` |
| `!{channel-id}` | Channel identifier | `abc123def456` |
| `!{stream-name}` | Source Kinesis Data Streams stream name | `my-stream` |
| `!{yyyy}` | Four-digit year (UTC) | `2026` |
| `!{yy}` | Two-digit year (UTC) | `26` |
| `!{MM}` | Month, zero-padded (UTC) | `07` |
| `!{dd}` | Day of month, zero-padded (UTC) | `20` |
| `!{HH}` | Hour, 24-hour zero-padded (UTC) | `14` |
| `!{mm}` | Minute, zero-padded (UTC) | `30` |
| `!{extension}` | File extension implied by `Compression` | `.gz`, `.zst` |

Use `!{channel-id}` combined with time variables down to `!{mm}` to keep object keys unique across delivery cycles — the default template above is a working pattern for this.

### Rules

- Maximum 1024 characters
- Must contain at least one variable
- Must not start or end with `/`
- Must not contain path traversal (`..`)
- All variable references must be balanced (matching `!{` and `}`)
- Allowed characters: alphanumerics, hyphens, underscores, periods, forward slashes, and variable references

### Examples

| Template | Valid | Reason |
|---|---|---|
| `data/!{channel-name}/!{yyyy}/!{MM}/!{dd}/!{HH}/!{channel-id}-!{mm}!{extension}` | Yes | Has variables, unique per channel/minute |
| `!{channel-name}/!{yyyy}-!{MM}-!{dd}/!{HH}!{mm}-!{channel-id}!{extension}` | Yes | Valid characters, date-based prefix |
| `!{channel-name}/!{channel-id}/!{yyyy}!{MM}!{dd}!{HH}!{mm}` | Yes | Minimal valid template |
| `/data/!{channel-name}/!{yyyy}` | No | Starts with `/` |
| `data/!{channel-name}/!{yyyy}/` | No | Ends with `/` |
| `data/../!{channel-name}/!{yyyy}` | No | Path traversal |
| `static-prefix-only` | No | No variables |
| `data/!{channel-name}/!{yyyy` | No | Unbalanced reference |

Match the template to downstream query patterns — use date-based prefixes when consumers filter by time range.

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
  --s3-destination-configuration '{"DataFreshnessInSeconds": 600}'

# Delete — already-delivered objects are NOT removed
aws kinesis delete-channel --region $REGION \
  --channel-arn $CHANNEL_ARN
```

Destination bucket, output key template, record format, service role, and source stream are immutable. Delete all channels on a stream before deleting the stream.

## Verify Delivery

```bash
# Delivered objects — wait DataFreshnessInSeconds after producing
aws s3 ls s3://my-kds-delivery-$ACCOUNT/data/ --recursive

# Failed records
aws s3 ls s3://my-kds-dlq-$ACCOUNT/errors/ --recursive

# Delivery errors
aws logs filter-log-events \
  --log-group-name "/aws/kinesis/my-s3-channel" --region $REGION
```

## Troubleshooting

| Symptom | Likely Cause | Action |
|---|---|---|
| Channel stuck in `CREATING`, then `FAILED` | Invalid role ARN, insufficient permissions, or bucket missing / in another Region | Read `ChannelStatusReason` from `describe-channel`. `FAILED` is not recoverable — fix, delete, recreate |
| No objects in the delivery prefix | Records produced before `ACTIVE` (no backfill), or silent delivery failure | Confirm records were sent after `ACTIVE`; check logs and DLQ |
| Objects in DLQ | Record format does not match the configured `RecordFormat`, KMS failure, or template rendering error | Inspect DLQ keys and bodies plus CloudWatch Logs |
| No CloudWatch logs written | Service role missing `logs:CreateLogStream` / `logs:PutLogEvents` | Add CloudWatch Logs permissions |
| `AccessDenied` in logs | Role policy or bucket policy changed after creation, trust policy broken, or KMS key policy denies access | Review the role policy, bucket policy, trust policy, and KMS key policy |
| Rising `DataChannel.DataFreshness` | Low throughput against a low freshness setting | Raise `DataFreshnessInSeconds` so more data batches per cycle |
| Channel suspended | Bucket owner mismatch or destination unavailable | Cannot be resumed — create a new channel |
| Channel not available for the stream | Stream is in provisioned mode | Switch the stream to On-Demand |
