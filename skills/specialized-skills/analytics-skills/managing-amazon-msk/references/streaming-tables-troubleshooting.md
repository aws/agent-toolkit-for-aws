# Streaming Tables — Troubleshooting

## Channel States

| State | Meaning |
|---|---|
| `CREATING` | Provisioning in progress |
| `ACTIVE` | Delivering data |
| `UPDATING` | Config change in progress (still delivering) |
| `DELETING` | Being removed |
| `FAILED` | Creation failed — check DescribeChannel + CW Logs |

## Channel Creation Failures

### Channel stuck in CREATING

Provisioning is in progress. Run `aws kafka describe-channel` to monitor. If it transitions to `FAILED`, check the failure detail. If it stays in `CREATING` well beyond expected time, contact Support.

> Configuration errors (missing permissions, nonexistent destination, unresolvable schema) cause `FAILED`, not prolonged `CREATING`.

### Channel transitions to FAILED

| Cause | Fix |
|---|---|
| Trust policy missing `kafka.amazonaws.com` | Fix trust policy principal and conditions |
| Destination bucket doesn't exist | Create the S3 Table bucket in the same Region as the cluster. The Iceberg **table** is auto-created by Streaming Tables (`enableTableCreation: true`) — you **must not** pre-create the Iceberg table; pre-creating it will break Streaming Tables delivery. Only the bucket must exist. |
| Schema can't be resolved from GSR | Verify: `aws glue get-schema --schema-id SchemaArn=<ARN>` |
| Missing IAM permissions | Compare role policy against reference in [streaming-tables.md](streaming-tables.md) or [data-delivery-for-general-purpose-s3.md](data-delivery-for-general-purpose-s3.md) |
| Wrong catalog ARN | Must be `arn:aws:glue:REGION:ACCOUNT_ID:catalog/s3tablescatalog/BUCKET` |

**Recovery:** Delete failed channel, fix config, recreate.

## Delivery Issues

> **Prerequisite:** Ensure CloudWatch Logs delivery is enabled for the Streaming Tables. Without it, diagnostic logs (e.g., `AccessDenied` errors) are not available. Enable logging when creating or updating the channel.

### No data at destination

1. Check `BytesIn` metric — if zero, no data being produced
2. Check CloudWatch Logs for `AccessDenied`
3. Verify producers are actively writing
4. **No backfill** — only data produced AFTER enablement is delivered

### Data freshness exceeds configured interval

**Causes:** Large table metadata/snapshots, low throughput, transient issues.

**Fix:**

- Enable S3 Tables maintenance (compaction, snapshot expiration)
- For low-throughput topics (< 2.4 MB/s), increase `dataFreshnessSeconds`

### Delivery stops after schema change (Iceberg)

Schema evolution is NOT supported. A change makes records incompatible.

**Fix:** Revert schema OR delete channel and create new one.

## Record Failures

### FailedRowCount / FailedRecordCount > 0

Records don't conform to schema. Common causes:

- Missing required field
- Type mismatch
- Malformed JSON
- Nesting > 16 levels

**Fix:** Inspect DLQ messages + CloudWatch Logs for error details. Fix producer or schema.

### DLQ Error Patterns

> **Warning:** DLQ messages contain full record payloads which may include sensitive data (PII, financial data, etc.). Ensure the DLQ bucket has encryption enabled (SSE-KMS recommended), access is restricted to authorized personnel, and consider enabling S3 access logging for audit purposes.

| Error | Cause | Fix |
|---|---|---|
| Missing required field | Record lacks field in schema `"required"` | Add to producer or remove from `"required"` (needs new channel) |
| Type mismatch | Value doesn't match schema type | Fix producer serialization |
| Schema resolution failure | Embedded schema ID doesn't match GSR (JSON_SCHEMA_GSR) | Verify producer GSR config |

## Permission Issues

### AccessDenied in CloudWatch Logs

1. Compare service role policy against reference policies
2. Check CloudTrail for recent policy/bucket-policy/key-policy changes
3. Verify trust policy has `kafka.amazonaws.com` (do not use any other service principal)
4. For KMS: verify key policy grants role access
5. For cross-account: verify table bucket policy in target account

## Monitoring

<!-- TODO: Add dedicated monitoring reference doc (streaming-tables-monitoring.md) with detailed alarm setup, dashboard templates, and operational runbooks once GA metrics are finalized. -->

**Namespace:** `AWS/Kafka` | **Dimensions:** `ClusterName`, `ChannelName`, `Topic`

### Iceberg metrics

`DeliveryToIceberg.DataFreshness`, `BytesIn`, `BytesProcessed`, `BytesOut`, `TotalRowCount`, `SuccessfulRowCount`, `FailedRowCount`, `CommitSuccess`, `DLQDeliverySuccess`

### S3 metrics

`DeliveryToS3.DataFreshness`, `BytesIn`, `BytesProcessed`, `BytesOut`, `RecordCount`, `SuccessfulRecordCount`, `FailedRecordCount`, `DeliverySuccess`, `DLQDeliverySuccess`

### Recommended alarms

| Alarm | Condition | Action |
|---|---|---|
| High data freshness | `DataFreshness` > configured interval | Investigate throughput |
| Failed records | `FailedRowCount`/`FailedRecordCount` > 0 for 5 min | Check DLQ + schema compatibility |
| DLQ deliveries | `DLQDeliverySuccess` > 0 | Inspect DLQ messages |

## Channel Not Available

**Symptom:** Streaming Tables tab not visible or `CreateChannel` errors.

**Cause:** Cluster uses Standard brokers, or is MSK Serverless.

**Fix:** Streaming Tables requires MSK Provisioned with **Express brokers** only.
