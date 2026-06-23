# Monitoring & Operations

## When to Activate

User asks about CloudWatch metrics, alarms, instance health, maintenance windows, backups, snapshots, or operational best practices.

## Key CloudWatch Metrics

> **IMPORTANT:** For the full authoritative list of metric names by engine and deployment type, see [metrics.md](metrics.md). The tables below are a quick-reference subset for alarm configuration. Never invent metric names — if it's not in metrics.md, it doesn't exist.

### Instance-Level Metrics (V2 SAZ/MAZ)

| Metric | Description | Alarm Threshold |
|--------|-------------|-----------------|
| `CPUUtilization` | CPU usage percentage | > 80% sustained for 5 min |
| `MemoryUtilization` | Memory usage percentage | > 90% sustained |
| `DiskUtilization` | Disk usage percentage | > 80% |
| `VolumeBytesUsed` | Storage consumed on EBS | > 80% of allocated |
| `ReadIOpsPerSec` / `WriteIOpsPerSec` | I/O operations per second | Baseline + 50% |
| `ReadThroughput` / `WriteThroughput` | Bytes read/written per second | Monitor for anomalies |

### InfluxDB Engine Metrics (V2 SAZ/MAZ CloudWatch only)

| Metric | Description |
|--------|-------------|
| `QueryRequestsTotal` | Query API calls |
| `SeriesCardinality` | Total unique series |
| `HeapMemoryUsage` | Heap memory usage |
| `WriteTimeouts` | Failed write timeouts |
| `APIRequestRate` | Total API request rate |

### V2 Read Replica CloudWatch (LIMITED)

Only these metrics are available: `CPUUtilization`, `MemoryUtilization`, `DiskUtilization`, `ReplicaLag`.

### V3 CloudWatch (LIMITED)

Only these metrics are available: `CPUUtilization`, `MemoryUtilization`. All other V3 metrics require scraping the Prometheus `/metrics` endpoint — see [metrics.md](metrics.md) Part 3B.

## Recommended Alarm Configuration

```bash
# CPU alarm — V2 instance
aws cloudwatch put-metric-alarm \
  --alarm-name "InfluxDB-HighCPU-<instance>" \
  --metric-name CPUUtilization \
  --namespace AWS/TimestreamInfluxDB \
  --statistic Average --period 300 --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 \
  --dimensions Name=DBInstanceIdentifier,Value=<instance-id> \
  --alarm-actions <sns-topic-arn>

# CPU alarm — V3 cluster (use DBClusterIdentifier dimension)
aws cloudwatch put-metric-alarm \
  --alarm-name "InfluxDB-HighCPU-<cluster>" \
  --metric-name CPUUtilization \
  --namespace AWS/TimestreamInfluxDB \
  --statistic Average --period 300 --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 \
  --dimensions Name=DBClusterIdentifier,Value=<cluster-id> \
  --alarm-actions <sns-topic-arn>

# Storage alarm — V2 instance ONLY (VolumeBytesUsed is NOT available for V3)
aws cloudwatch put-metric-alarm \
  --alarm-name "InfluxDB-StorageHigh-<instance>" \
  --metric-name VolumeBytesUsed \
  --namespace AWS/TimestreamInfluxDB \
  --statistic Maximum --period 300 \
  --threshold <80-percent-of-allocated-bytes> \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --dimensions Name=DBInstanceIdentifier,Value=<instance-id> \
  --alarm-actions <sns-topic-arn>
```

> **V3 storage monitoring:** V3 uses S3-backed storage — there is no `VolumeBytesUsed` metric. Monitor storage costs via AWS Cost Explorer or query `system.parquet_files` for actual data size.
>
> **MUST:** Enable SSE-KMS on your SNS topic to encrypt alarm notifications at rest — never use at-rest unencrypted notifications for operational data. Alarm notifications can contain operationally sensitive information (instance IDs, metric thresholds, account details). Ensure your SNS topic access policy restricts `sns:Subscribe` to authorized principals only, and verify that all subscription endpoints (email, HTTPS, Lambda) belong to your organization. If alarm notifications are also delivered to CloudWatch Logs, enable SSE-KMS encryption on those log groups as well.

## Maintenance Windows

Customer Managed Maintenance Windows:

- Set preferred day, time, and timezone via console, CLI, or SDK
- Engine patches and minor updates applied during the window
- Major version changes require explicit approval

```bash
# V2 instance
aws timestream-influxdb update-db-instance \
  --identifier <instance-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":"Sun:03:00-Sun:05:00"}'

# V3 cluster
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":"Sun:03:00-Sun:05:00"}'
```

## Backup & Snapshots

- **Service-managed snapshots** are taken automatically: every hour for InfluxDB 2 (retained 24 hours) and every hour for InfluxDB 3 (retained 30 days). These are NOT directly accessible to customers — there is no console or CLI to list, browse, or restore them.
- **To recover from a snapshot**, customers must open a **Sev-2 support ticket** requesting recovery or retention of a specific snapshot. There is no self-service restore path.
- **Customer-managed snapshots are not available** — there is no `create-db-snapshot` CLI command or equivalent. Do NOT tell customers they can create, schedule, or manage their own snapshots.
- For self-managed backups, use the InfluxDB data-plane API to export data via line protocol or SQL queries to S3:

```bash
# V2: Export data via influx CLI
influx backup /path/to/backup --host https://<endpoint>:8086 --token <token>

# V3: Export data via SQL query to CSV
curl -X POST "https://<endpoint>:8181/api/v3/query_sql" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"db":"<database>","q":"SELECT * FROM <table>","format":"csv"}' > backup.csv
```

## AWS CloudTrail Integration

Timestream for InfluxDB is integrated with AWS CloudTrail and logs all control-plane API calls (e.g., `CreateDbInstance`, `DeleteDbInstance`, `UpdateDbInstance`, `CreateDbCluster`). Enable CloudTrail in your account to maintain an audit trail of who made changes, when, and from where.

**Important limitation:** Timestream for InfluxDB supports **control-plane CloudTrail events only**. Data-plane operations (reads/writes to InfluxDB via the HTTP API) are not logged via CloudTrail — use InfluxDB's own audit logging or the `/metrics` endpoint for data access observability.

## Operational Checklist

- [ ] CloudWatch alarms configured for CPU, memory, storage, and I/O
- [ ] Maintenance window set to low-traffic period
- [ ] Data export/backup strategy defined (service snapshots are not self-service — use data-plane export for customer-controlled backups)
- [ ] SNS topic configured for alarm notifications
- [ ] Instance right-sized for workload (check CPU/memory utilization trends)
- [ ] Storage monitoring in place (V2: allocated storage usage; V3: S3 costs)
