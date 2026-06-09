# Log Delivery

ElastiCache log types, destinations, configuration, and cost considerations.

## Log Types

| Log Type | What It Captures | When to Enable | Engine Support |
|----------|-----------------|----------------|----------------|
| Slow log | Commands that exceed the `slowlog-log-slower-than` threshold (default 10,000 microseconds). **Note:** A fixed number of slow log entries are retrieved periodically; depending on `slowlog-max-len`, some entries may not be delivered. | Always recommended for production. Essential for identifying slow commands that degrade performance. | Valkey 7.x+, Redis OSS 6.0+ |
| Engine log | Internal engine events: startup, shutdown, configuration changes, replication events, cluster events | Recommended for production. Useful for debugging replication issues, failover events, and configuration drift. | Valkey 7.x+, Redis OSS 6.2+ |
| Command log (COMMANDLOG) | Records slow executions, large requests, and large replies. Separate from slow log. | Use selectively for debugging or auditing. High-volume workloads generate significant log data. | Valkey 8.1+ only |

## Log Destinations

| Destination | Strengths | Considerations |
|-------------|-----------|----------------|
| CloudWatch Logs | Native integration with CloudWatch Insights, alarms, metric filters, and dashboards. Simple to set up. | CloudWatch Logs charges apply per GB ingested and stored. For high-throughput caches, costs can be significant. |
| Kinesis Data Firehose | Stream to S3, OpenSearch, Redshift, or third-party tools. Good for high-volume log pipelines. | Firehose delivery charges apply in addition to CloudWatch Logs vended-log charges (AWS charges for vended logs even when delivered directly to Firehose). |

### Cost Warning

When using CloudWatch Logs as the destination, standard CloudWatch Logs ingestion and storage charges apply. When using Kinesis Data Firehose as the destination, Firehose delivery charges apply in addition to CloudWatch Logs vended-log charges (AWS charges for vended logs even when delivered directly to Firehose). Factor log delivery costs into your operational budget, especially for:

- High-throughput caches (>10,000 ops/sec) with command logging enabled.
- Large clusters with many nodes, each emitting engine logs.
- Development environments where logs may not be actively monitored (consider disabling or sampling).

## Configuration via CLI

Use the following JSON structure for `--log-delivery-configurations`:

```json
{
  "LogType": "<LogType>",
  "DestinationType": "<DestinationType>",
  "DestinationDetails": {
    "<DestinationDetailsKey>": {
      "<TargetKey>": "<TargetValue>"
    }
  },
  "LogFormat": "json",
  "Enabled": true
}
```

### LogType Values

| Log Type | LogType Value | API Status |
|----------|--------------|------------|
| Slow log | `slow-log` | Available |
| Engine log | `engine-log` | Available |

**⚠️ Command log (`command-log`):** The ElastiCache API accepts only `slow-log` and `engine-log` as LogType values; `command-log` is not a valid LogType. The COMMANDLOG feature (Valkey 8.1+) may be exposed via the `engine-log` LogType or require a separate API enum value for `command-log`. Check the latest API reference before attempting to configure command log delivery.

### DestinationType Values

| Destination | DestinationType | DestinationDetails Key | Target Key |
|-------------|----------------|------------------------|------------|
| CloudWatch Logs | `cloudwatch-logs` | `CloudWatchLogsDetails` | `LogGroup` |
| Kinesis Data Firehose | `kinesis-firehose` | `KinesisFirehoseDetails` | `DeliveryStream` |

Pass to `create-replication-group` (at creation time, without `--apply-immediately`) or `modify-replication-group` / `modify-cache-cluster` (for existing clusters, with `--apply-immediately`). You **must** set the `--apply-immediately` parameter when modifying log delivery on existing clusters.

> **Node-based only.** Log delivery is available for node-based clusters only. Serverless caches do not support log delivery (slow log, engine log, or command log) via the API or console. For serverless observability, use CloudWatch metrics (latency, ECPU, throttling) and client-side logging.

To disable, set `"Enabled": false` (only `LogType` and `Enabled` are required).

### Required IAM Permissions

To configure log delivery, your IAM user/role must have the following permissions:

**For CloudWatch Logs destination:**

- `logs:CreateLogDelivery`
- `logs:UpdateLogDelivery`
- `logs:DeleteLogDelivery`
- `logs:GetLogDelivery`
- `logs:ListLogDeliveries`

**For Kinesis Data Firehose destination:**

The same `logs:*` permissions listed above are required (ElastiCache uses CloudWatch Logs vended-log infrastructure for Firehose delivery). Ensure the Firehose delivery stream resource policy allows the `logs.amazonaws.com` service principal to deliver to it.

## Log Format

ElastiCache supports two log formats:

| Format | Use Case |
|--------|----------|
| `json` | Recommended. Structured, easy to parse with CloudWatch Insights, Athena, or log processing pipelines. |
| `text` | Human-readable. Useful for quick manual inspection via `valkey-cli` slow log format. |

### Sample Slow Log Entry (JSON)

```json
{
  "CacheClusterId": "my-cluster-001",
  "CacheNodeId": "0001",
  "Id": 42,
  "Timestamp": 1700000000,
  "Duration (us)": 15230,
  "Command": "SORT ... (8 more arguments)",
  "ClientAddress": "10.0.1.50:54321",
  "ClientName": "app-worker-3"
}
```

**Note:** ElastiCache replaces actual key names and values with `(N more arguments)` to avoid exposing sensitive data.

**Encrypt logs at rest.** Slow log and engine log entries still include client IP addresses, client names, and command verbs. Encrypt the target CloudWatch Logs log group with a KMS key (`aws logs associate-kms-key --log-group-name <name> --kms-key-id <arn>`) to protect this operational data at rest.

## Interpreting Slow Log Entries

The `Duration (us)` field is in microseconds.

| Duration | Severity | Action |
|----------|----------|--------|
| < 1,000 (1ms) | Normal | No action needed |
| 1,000 - 10,000 (1-10ms) | Warning | Investigate if frequent; may indicate suboptimal data access |
| 10,000 - 100,000 (10-100ms) | High | Identify the command and key; likely O(N) operation on a large collection |
| > 100,000 (100ms+) | Critical | Blocking the engine thread; fix immediately |

Common slow commands: `KEYS *` (scan all keys), `SMEMBERS` on large sets, `HGETALL` on large hashes, `SORT` without LIMIT, `LRANGE 0 -1` on long lists, `ZRANGEBYSCORE` returning thousands of members.

## Querying Logs

### CloudWatch Logs Insights

Find the slowest commands in the last 24 hours:

```
fields @timestamp, `Duration (us)`, Command
| filter `Duration (us)` > 10000
| sort `Duration (us)` desc
| limit 20
```

Find commands from a specific client:

```
fields @timestamp, `Duration (us)`, Command, ClientAddress
| filter ClientAddress like "10.0.1.50"
| sort @timestamp desc
| limit 50
```

Top 10 slowest command types in the last 24 hours:

```
fields Command, `Duration (us)`
| parse Command /^(?<cmd>\S+)/
| stats avg(`Duration (us)`) as avg_duration, max(`Duration (us)`) as max_duration, count(*) as invocations by cmd
| sort max_duration desc
| limit 10
```

Hourly slow command distribution (spot time-of-day patterns):

```
fields @timestamp, `Duration (us)`
| stats count(*) as slow_commands by bin(1h)
| sort bin asc
```

Per-node comparison (find the hot node):

```
fields CacheClusterId, `Duration (us)`, Command
| stats count(*) as slow_count, avg(`Duration (us)`) as avg_duration by CacheClusterId
| sort slow_count desc
```

## Recommendations

| Environment | Slow Log | Engine Log | Command Log |
|-------------|----------|------------|-------------|
| Production | Enable (JSON, CloudWatch Logs, 30-day retention) | Enable (JSON, CloudWatch Logs, 30-day retention) | Disable unless actively debugging |
| Staging | Enable | Enable | Enable selectively for integration testing |
| Development | Optional | Optional | Optional |
