# Alarm Packs

CloudWatch alarm configurations for ElastiCache serverless and node-based deployments.

## Alarm Philosophy

- **Start conservative, tune from baseline.** Set initial thresholds based on the guidance below, then adjust after observing 1-2 weeks of production traffic patterns.
- **Use workload-dependent thresholds, not fixed generic values.** A cache with 90% hit rate serving web sessions has different alarm thresholds than a cache doing vector search with 60% hit rate. The numbers below are starting points.
- **Alarm on sustained conditions, not transient spikes.** Use multiple evaluation periods (e.g., 3 out of 5 datapoints) to avoid false alarms from brief traffic bursts.
- **Pair alarms with runbooks.** Every alarm should link to an action. If an alarm fires and the team does not know what to do, it is noise.
- **Escalate gradually.** Start with warning thresholds that notify. Add critical thresholds that page.

## Serverless Alarm Pack

Dimension all alarms on `ServerlessCacheName`. Use `ComparisonOperator: GreaterThanThreshold` except for CacheHitRate which uses `LessThanThreshold`. Set `TreatMissingData: notBreaching` for all.

| Alarm Name | Metric | Statistic | Period | Threshold | EvalPeriods / Datapoints | Starting Threshold Guidance |
|---|---|---|---|---|---|---|
| ThrottledCmds (P0) | ThrottledCmds | Sum | 60s | 0 | 3 / 2 | > 0 sustained across 2 of 3 minutes. Any throttling warrants investigation. |
| ECPUSpike | ElastiCacheProcessingUnits | Sum | 60s | (baseline-dependent) | 5 / 3 | Set to 2x your observed 1-minute average during normal traffic. Uses 60s period to match ThrottledCmds cadence. Tune after establishing a baseline. |
| StorageApproachingLimit | BytesUsedForCache | Maximum | 300s | (80% of MaxDataStorageGB) | 3 / 2 | Set to 80% of configured `MaxDataStorageGB`. For a 5 GB limit, alarm at ~4 GB (4,000,000,000 bytes). |
| ReadLatency | SuccessfulReadRequestLatency | Average | 60s | 5000 (microseconds) | 5 / 3 | > 5ms sustained. Adjust based on application SLA. Serverless latency is typically 1-3ms at p50. |
| LowHitRate | CacheHitRate | Average | 300s | 80 (LessThan) | 6 / 4 | < 80% sustained over 20 minutes. Adjust based on workload; caches warming up or doing write-heavy work will naturally have lower hit rates. |

## Node-Based Alarm Pack

Dimension alarms on `CacheClusterId` and `CacheNodeId` (the dimensions under which node-level metrics are published). To get replication-group-level visibility, create per-node alarms or use CloudWatch metric math to aggregate across nodes. Use `ComparisonOperator: GreaterThanThreshold` except for CacheHitRate which uses `LessThanThreshold`. Set `TreatMissingData: notBreaching` for all.

| Alarm Name | Metric | Statistic | Period | Threshold | EvalPeriods / Datapoints | Starting Threshold Guidance |
|---|---|---|---|---|---|---|
| EngineCPU (P0) | EngineCPUUtilization | Maximum | 60s | 90 | 5 / 3 | > 90% sustained across 3 of 5 minutes. For nodes with 2 or fewer vCPUs (t4g.micro, t4g.small), use `CPUUtilization` with threshold `90 / vCPU_count` instead, since EngineCPU can spike to 100% on a single thread while overall host capacity remains available. |
| MemoryHigh | DatabaseMemoryUsagePercentage | Maximum | 60s | 80 | 5 / 3 | > 80% sustained. Evictions may begin depending on `maxmemory-policy`. Set a critical alarm at 90%. |
| ReplicationLag | ReplicationLag | Maximum | 60s | 1 (seconds) | 5 / 3 | > 1 second sustained. For apps reading from replicas needing consistency, set tighter (e.g., 0.1s). Valkey 7.2+/Redis OSS 5.0.6+ measure sub-second precision. The CloudWatch metric unit is seconds, not milliseconds. |
| Evictions | Evictions | Sum | 300s | 100 | 3 / 2 | > 100 evictions per 5-minute period sustained. Some eviction is normal with volatile-* policies, but sustained eviction means the dataset outgrew the cache. For clusters using `volatile-lru` or `volatile-ttl` policies, eviction of TTL'd keys is expected behavior. Raise or disable this alarm for those policies. Not user-tunable on serverless (serverless manages eviction automatically). |
| NewConnections | NewConnections | Sum | 60s | 1000 | 3 / 2 | > 1000 new connections per minute sustained. Indicates connection storm or missing pooling. Tune based on your steady-state new connection rate. |
| ReadLatency | SuccessfulReadRequestLatency | Average | 60s | 5000 (microseconds) | 5 / 3 | > 5ms sustained. Adjust based on application SLA. Node-based latency is typically 0.5-2ms at p50. |
| WriteLatency | SuccessfulWriteRequestLatency | Average | 60s | 5000 (microseconds) | 5 / 3 | > 5ms sustained. Critical for write-heavy workloads (session stores, counters, rate limiters). Adjust based on application SLA. Node-based write latency is typically 0.5-2ms at p50. |
| LowHitRate | CacheHitRate | Average | 300s | 80 (LessThan) | 6 / 4 | < 80% sustained over 20 minutes. Investigate key design, TTL strategy, working set size. |

**Per-node alarms for hot-shard detection:** For cluster-mode clusters with 3+ shards, create a separate EngineCPU alarm per primary node (dimensioned on `CacheClusterId` and `CacheNodeId`) to detect hot shards. A single alarm aggregating across nodes can hide shard imbalance when multiple shards are hot but none is the single highest.

**Note on CPUUtilization vs. EngineCPUUtilization:** AWS recommends using `EngineCPUUtilization` rather than `CPUUtilization` for capacity planning. `CPUUtilization` may vary across engine versions and node types due to changes in how enhanced I/O features utilize available cores, making it an unreliable metric for capacity planning.

**Network saturation alarms (recommended for large instances):** Add alarms for `TrafficManagementActive`, `NetworkBandwidthInAllowanceExceeded`, `NetworkBandwidthOutAllowanceExceeded`, `NetworkConntrackAllowanceExceeded`, and `NetworkPacketsPerSecondAllowanceExceeded`. These fire before general performance degradation becomes visible and are the first signal of host-level saturation. `DatabaseCapacityUsagePercentage` is available on all node-based clusters (on data-tiering instances (r6gd), the formula includes SSD storage; on all other instances, it is calculated as `used_memory/maxmemory`); add it alongside `DatabaseMemoryUsagePercentage`.

## Alarm-to-Runbook Mapping

| Alarm | Runbook (troubleshooting.md) |
|-------|------------------------------|
| EngineCPU | High CPU |
| MemoryHigh | Memory Pressure |
| ReplicationLag | Replication Lag |
| Evictions | Memory Pressure (eviction policy) |
| LowHitRate | Low Hit Rate |
| ReadLatency | High Latency |
| WriteLatency | High Latency |
| ThrottledCmds | Throttling (Serverless) |
| ECPUSpike | Throttling (if ThrottledCmds also firing) or cost-reporting.md (if no throttling, indicates approaching limits) |
| StorageApproachingLimit | Memory Pressure |

## Deploying Alarm Packs

### Via the Generate Script

```bash
# Serverless (generates dashboard + alarms)
python3 scripts/generate_dashboards.py --serverless <cache-name> \
  --sns-topic arn:aws:sns:us-east-1:123456789012:cache-alerts \
  --output observability.json

# Node-based
python3 scripts/generate_dashboards.py --replication-group <cluster-id> \
  --sns-topic arn:aws:sns:us-east-1:123456789012:cache-alerts \
  --output observability.json
```

### Deploy

```bash
aws cloudformation deploy \
  --template-file observability.json \
  --stack-name <cache-name>-observability \
  --region us-east-1
```

## Notification Routing

| Destination | Integration |
|---|---|
| Slack | SNS → AWS Chatbot → Slack channel |
| PagerDuty | SNS → PagerDuty Events API v2 (HTTPS subscription) |
| Email | SNS → Email subscription (confirm required) |

**Restrict who can subscribe.** Attach an SNS topic access policy that limits `sns:Subscribe` to authorized principals or accounts only. Operational alerts carry infrastructure details (cache names, ARNs, thresholds), so an open subscribe policy lets unauthorized parties receive them.

## Tuning Thresholds from Baseline

After deploying the initial alarm pack:

1. **Observe for 1-2 weeks** under normal production traffic.
2. **Review CloudWatch metric graphs** to identify the natural baseline (average, p95, p99) for each metric.
3. **Adjust thresholds** to sit above the p99 of normal operation. The goal is zero false alarms during normal traffic while catching genuine anomalies.
4. **Add anomaly detection alarms** for metrics with variable baselines (e.g., ECPU following business hours). Use CloudWatch anomaly detection alarms with `ANOMALY_DETECTION_BAND`. CloudWatch learns the pattern and alarms on deviation from the expected band.
