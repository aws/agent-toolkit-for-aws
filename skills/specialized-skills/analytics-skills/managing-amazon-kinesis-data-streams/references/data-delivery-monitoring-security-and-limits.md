# Operating KDS delivery channels

Applies to both destination types: streaming tables on Apache Iceberg (S3 Tables) and general-purpose S3 buckets.

For metric definitions and units, full quota values, naming character sets, and CloudTrail event schemas, read the **Streaming Tables and Amazon S3 Delivery** section of the [KDS Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html) and the [KDS API Reference](https://docs.aws.amazon.com/kinesis/latest/APIReference/). This file covers only the behaviors that change how you configure and debug a channel.

## Channel states

`CREATING` → `ACTIVE` → `UPDATING` / `DELETING`, plus `FAILED`.

Two states are terminal and worth checking before you attempt any repair:

- **`FAILED`** — not recoverable. `ChannelStatusReason` from `describe-channel` holds the cause. Fix it, delete the channel, recreate it.
- **Suspended** — not resumable. Caused by the destination becoming unavailable or incompatible: the destination Iceberg table was deleted, the S3 bucket owner does not match the expected account, or an incompatible partition column was detected. Create a new channel.

Do not wait on or retry either state — both require recreating the channel.

## CloudWatch metrics

Namespace `AWS/Kinesis`. Each destination type publishes its own metric prefix — use the prefix matching the channel's destination:

| Destination | Metric prefix | Metrics |
|---|---|---|
| General-purpose S3 | `DeliveryToS3.*` | `BytesIn`, `BytesOut`, `BytesProcessed`, `RecordCount`, `SuccessfulRecordCount`, `FailedRecordCount`, `DeliverySuccess`, `DataFreshness` |
| Streaming tables (Iceberg/S3 Tables) | `DeliveryToIceberg.*` | `BytesIn`, `BytesOut`, `BytesProcessed`, `TotalRowCount`, `SuccessfulRowCount`, `FailedRowCount`, `CommitSuccess`, `DataFreshness` |

Dimension it with all three of `ChannelName`, `StreamName`, and `ChannelId` — get the channel ID from `create-channel`'s response or `list-channels`.

Metrics only appear after the channel's first delivery attempt, not at channel creation. Run `aws cloudwatch list-metrics --namespace AWS/Kinesis` after that first cycle to confirm the exact metric names and dimension values before building dashboards or alarms.

Two things to get right when reading them:

- **Use 5-minute granularity across a window spanning several freshness periods.** Aggregating into one long period hides early flushes and makes a working channel look idle.
- **`FailedRecordCount`/`FailedRowCount` > 0 with no corresponding growth in the DLQ means records are being dropped outright**, not parked in the DLQ — there is no `DLQDeliverySuccess` metric. Cross-check against actual DLQ object counts in S3, not a CloudWatch metric.

```bash
aws cloudwatch get-metric-statistics \
  --region $REGION \
  --namespace AWS/Kinesis \
  --metric-name DeliveryToS3.FailedRecordCount \
  --dimensions Name=ChannelName,Value=my-channel Name=StreamName,Value=my-stream Name=ChannelId,Value=my-channel-id \
  --start-time "$(date -u -v-2H +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 300 \
  --statistics Sum
```

For a streaming-tables channel, use `DeliveryToIceberg.FailedRowCount` instead. Get the channel ID
from `create-channel`'s response or `list-channels` — it's a required dimension.

Alarm on `DataFreshness` against your own latency threshold, and on `SuccessfulRecordCount`/`SuccessfulRowCount` = 0 to catch a channel that is `ACTIVE` but delivering nothing.

## Delivery logging

Default log group `/aws/kinesis/CHANNEL_NAME`, log stream `DestinationDelivery`.

```bash
--logging-configuration '{
  "CloudWatchLogs": {
    "Enabled": true,
    "LogGroupName": "/aws/kinesis/my-channel",
    "LogStreamName": "DestinationDelivery"
  }
}'
```

Always enable it. Without logs, `AccessDenied` on the destination or DLQ, GSR schema-mapping failures, KMS failures, and table-creation errors are invisible — the channel stays `ACTIVE` and the only symptom is missing data. Create the log group **before** creating the channel, and grant the execution role `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` on it.

Control-plane calls (`CreateChannel`, `UpdateChannel`, `DeleteChannel`, `DescribeChannel`, `ListChannels`) are recorded in CloudTrail. Use it to find `AccessDenied` events from the execution role session when a channel fails to provision or silently stops delivering.

The channel's assumed-role session is always named `Channel-Session-For-Cx-Role`, regardless of the actual role name. Filter `lookup-events` by `EventSource`/`EventName` (e.g. `EventSource=s3tables.amazonaws.com`, `EventName=CreateTable`) — a `Username` filter on the role name will not match these events.

## Dead-letter queue

DLQ entries hold routing metadata and an error code — stream, partition, offset — **not the original payload**. Replay from the stream within its retention window; do not plan on replaying from the DLQ.

Required for Iceberg destinations. Optional for general-purpose S3, where omitting it writes errors into the delivery bucket under an error prefix — configure one explicitly so failures do not land among delivered records.

## Encryption

Details in [KDS Security](https://docs.aws.amazon.com/streams/latest/dev/security.html). Three constraints cause most failures:

- The **`aws/kinesis` managed key cannot be used** for destination encryption. Use a customer managed KMS key.
- Supply the **full key ARN, not an alias**.
- For **S3** destinations the execution role grant needs `kms:ViaService: s3.REGION.amazonaws.com`; for **S3 Tables** destinations it does not.

The role needs `kms:GenerateDataKey` to write encrypted objects and `kms:Decrypt` to read an encrypted stream.

## IAM permissions for channel lifecycle APIs

Separate from the service execution role, the calling principal needs `kinesis:CreateChannel` (on the stream ARN), and `kinesis:UpdateChannel`, `kinesis:DescribeChannel`, `kinesis:DeleteChannel` (on the channel ARN, `arn:aws:kinesis:REGION:ACCOUNT_ID:channel/CHANNEL_ID` — the channel ID assigned at creation, not the channel name). `kinesis:ListChannels` is scoped to `arn:aws:kinesis:REGION:ACCOUNT_ID:stream/*`. Get the channel ARN from `create-channel`'s response or `list-channels`; do not construct it from the channel name.

## Naming

S3 Tables **namespace and table names must be lowercase**. Uppercase characters cause silent or hard-to-diagnose failures rather than a clean validation error.

Current quota values: `aws service-quotas list-service-quotas --service-code kinesis`, or [KDS quotas and limits](https://docs.aws.amazon.com/streams/latest/dev/service-sizes-and-limits.html).

## What you can change after creation

Mutable: **`DataFreshnessInSeconds`** and **logging configuration**.

Immutable: source stream, record format, destination, service execution role, encryption, output key template, partition spec. Changing any of them means deleting and recreating the channel — which also means losing every record produced in the gap, since channels do not backfill.

## Limits that rule the feature out

- Append-only — no CDC, upserts, or deletes
- No schema evolution
- No backfill
- No transformations or filtering
- New destination table per channel; cannot deliver into an existing Iceberg table
- Data freshness floor is 300 seconds — not sub-minute
- Same Region only; cross-account is supported, cross-Region is not
- Source stream must be ON_DEMAND
- A stream cannot be deleted while channels are attached

If any of these block the customer, recommend **Managed Service for Apache Flink** instead.
