# Monitor and Alarm MSK Clusters

## Monitoring Levels

MSK Provisioned clusters support 4 monitoring levels. Each level includes all metrics from the previous level.

| Level | Cost | Dimensions | What It Adds |
|---|---|---|---|
| DEFAULT | Free | Cluster Name; Cluster Name + Broker ID; Cluster Name + Consumer Group + Topic | Core metrics: CPU, memory, disk, bytes in/out, connection count, URP (Standard), partition count, consumer lag, TrafficShaping (Standard) |
| PER_BROKER | Paid | Cluster Name + Broker ID | Request handler/network idle %, EBS volume metrics (Standard), traffic shaping detailed (Standard), connection rates, produce/fetch latency, tiered storage metrics (Standard) |
| PER_TOPIC_PER_BROKER | Paid | Cluster Name + Broker ID + Topic | Per-topic message rates, conversion rates, tiered storage per topic (Standard) |
| PER_TOPIC_PER_PARTITION | Paid | Consumer Group + Topic + Partition | Per-partition consumer lag (OffsetLag, EstimatedTimeLag) |

**Recommendation**: Use PER_BROKER as the minimum for production clusters. Use PER_TOPIC_PER_BROKER if you need per-topic throughput visibility. Use PER_TOPIC_PER_PARTITION only if you need partition-level consumer lag granularity.

**Key metrics NOT available on Express** (do not alarm on these for Express clusters): `UnderReplicatedPartitions`, `OfflinePartitionsCount`, `KafkaDataLogsDiskUsed`, `HeapMemoryAfterGC`, `BurstBalance`, `VolumeQueueLength`, `BwInAllowanceExceeded`, `BwOutAllowanceExceeded`. Express uses `ProduceThrottleTime`, `FetchThrottleTime`, and `StorageUsed` instead.

For the full metric list per broker type and monitoring level, search AWS docs for `"MSK CloudWatch metrics Standard brokers"` or `"MSK CloudWatch metrics Express brokers"`.

Update monitoring level:

```
# Get the cluster's current revision version first (this is an opaque revision string, NOT a Kafka version number):
# aws kafka describe-cluster-v2 --cluster-arn <cluster-arn> --query 'ClusterInfo.CurrentVersion' --output text

aws kafka update-monitoring --cluster-arn <cluster-arn> --current-version <cluster-current-version> \
  --enhanced-monitoring PER_BROKER
```

Follow [SNS security best practices](https://docs.aws.amazon.com/sns/latest/dg/sns-security-best-practices.html) when wiring alarm actions to an SNS topic (e.g. `--alarm-actions` for `aws cloudwatch put-metric-alarm` calls).

## Recommended Alarms

### Critical alarms (set these for every cluster)

| Metric | Condition | Action | Source |
|---|---|---|---|
| `CpuUser + CpuSystem` | Average > 60% for 5 min | Scale broker size or add brokers. Check client batch config first. | MSK Best Practices |
| `KafkaDataLogsDiskUsed` (Standard) | Max > 85% per broker | Expand EBS storage. Review topic retention. Enable auto-scaling. | MSK Best Practices |
| `UnderReplicatedPartitions` (Standard) | Sum > 0 for 15 min | Check if maintenance is in progress. If not, investigate broker health. | MSK Best Practices |
| `UnderMinIsrPartitionCount` (Standard) | Average ≥ 1 for 1 min | Partitions have fallen below `min.insync.replicas`. Produce calls with `acks=all` will fail with `NotEnoughReplicas`. Differs from URP: URP fires when any replica is behind; UnderMinIsr fires only when ISR drops to a level that breaks writes. Confirm broker health and replication factor ≥ 3 across topics. | MSK Best Practices |
| `OfflinePartitionsCount` (Standard) | Sum > 0 | Immediate investigation — partitions unavailable for produce/consume. | MSK Best Practices |
| `ActiveControllerCount` | Maximum < 1 for 5 min | No active controller. Brief dip during controller election on broker restart is normal. | MSK Best Practices |

### Performance alarms (most require PER_BROKER level)

| Metric | Condition | Action |
|---|---|---|
| `RequestHandlerAvgIdlePercent` | Average < 0.3 (30%) for 5 min | Request threads saturated. Check client batch sizes before scaling. |
| `NetworkProcessorAvgIdlePercent` | Average < 0.3 for 5 min | Network threads saturated. May indicate connection storms or high TLS overhead. |
| `BwInAllowanceExceeded` or `BwOutAllowanceExceeded` (Standard) | Sum > 0 for 5 min | Traffic shaping active. Check per-broker traffic distribution. Consider larger broker. |
| `HeapMemoryAfterGC` (Standard, DEFAULT level) | Average > 60% for 5 min, 3 consecutive periods | Memory pressure after GC. Check connection count, consumer groups, partition count. Reduce `transactional.id.expiration.ms` from 604800000 (7 days) to 86400000 (1 day) to lower per-transaction memory footprint. Review high-cardinality consumer groups and excessive partition counts. |
| `CPUCreditBalance` (Standard, t3 brokers only) | Average ≤ 100 for 5 min, 3 consecutive periods | t3 brokers earn CPU credits up to a max of 576. When the balance hits 0, CPU is capped at the 20% baseline and broker performance degrades sharply. Upgrade from t3 to m7g brokers — t3 is appropriate only for dev/test, never production sustained load. |
| `(Sum(VolumeReadBytes) + Sum(VolumeWriteBytes)) / (5 * 60 * 1024 * 1024)` (Standard) | ≥ 80% of available volume throughput in MiB/s for 5 min, 3 consecutive periods | Underlying EBS volume read+write activity is approaching the volume's throughput limit. EBS throughput ceilings are invisible in Kafka metrics — this is the alarm that surfaces them. Use a metric math expression: sum `VolumeReadBytes` + `VolumeWriteBytes` per broker over a 5-min period, divide by `5*60` for per-second, then by `1024*1024` for MiB/s. Threshold = 0.8 × the volume's provisioned throughput. Remediation: provision higher EBS storage throughput, switch to gp3 with explicit throughput, or scale to a larger broker. See [MSK provisioned throughput management](https://docs.aws.amazon.com/msk/latest/developerguide/msk-provision-throughput-management.html). |
| `IAMTooManyConnections` | Sum > 0 for 5 min | Clients exceeding the 100 new IAM connections/sec per broker limit (4/sec on t3). Check for connection storms from deployments, missing singleton patterns, or Lambda cold starts creating new clients per invocation. Add random jitter before client creation. See [configure-clients.md](configure-clients.md) connection management guidance. |
| `ConnectionCreationRate` (IAM) | Sum ≥ 80 per minute for 1 min, 3 consecutive periods | Proactive alarm — fires before `IAMTooManyConnections` throttling kicks in. The 100/sec limit is fixed and cannot be raised. Use **Sum** statistic, NOT Average: a single broker reports `ConnectionCreationRate` as multiple datapoints across its network processors, so summing at the broker level gives the true total. Same remediation as `IAMTooManyConnections`. |
| `ClientConnectionCount` per broker | Sum > 80% of the configured limit for 5 min, 3 consecutive periods | **For IAM**: the 3000 default cap is enforced — at 3000 new connections are rejected. Adjustable via `listener.name.client_iam.max.connections` (Kafka dynamic config, applied with `kafka-configs.sh --bootstrap-server <bootstrap> --command-config client.properties --alter ...`, where `client.properties` carries the IAM SASL settings — `security.protocol=SASL_SSL`, `sasl.mechanism=AWS_MSK_IAM`, `sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;`, `sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler` — and is NOT an AWS CLI command). **For SASL/SCRAM and mTLS**: MSK does NOT enforce a connection cap, but high counts still consume network threads, file descriptors, and heap, and can cascade into `RequestHandlerAvgIdlePercent` saturation and produce/fetch latency. Alarm at the same 2400 (80% of 3000) baseline for non-IAM unless you have measured a different ceiling for the workload. Use the `Client Authentication` dimension to scope the alarm to the relevant listener. Use **Sum** statistic per minute — a single broker reports this metric as multiple datapoints across network processors. Common causes: creating new producer/consumer instances per request instead of reusing one per application, connection leaks from missing `close()` calls, or too many microservices connecting to the same cluster. See [configure-clients.md](configure-clients.md) connection management guidance. |

### Consumer lag alarms (DEFAULT level)

| Metric | Condition | Action |
|---|---|---|
| `MaxOffsetLag` | Maximum > threshold (app-specific, e.g., 10000 offsets) for 15 min | Per-partition worst case. Catches a single hot partition falling behind even when the topic-wide total looks fine. Use this when partition-level SLAs matter. Check consumer group health. |
| `SumOffsetLag` | Average ≥ threshold (app-specific) for 5 min, 3 consecutive periods | Aggregated lag across all partitions in a topic for a consumer group. Catches whole-topic backlog growth. Use this when total backlog or end-to-end latency matters more than any single partition. For partition-level detail, use the `Offset` metric (PER_TOPIC_PER_PARTITION level) or `kafka-consumer-groups.sh --describe`. |
| `EstimatedMaxTimeLag` | > threshold (app-specific) | Lag expressed as time. Set threshold based on SLA. |

### Per-broker capacity alarms

| Metric | Applies to | Condition | Action |
|---|---|---|---|
| `PartitionCount` per broker | Standard and Express | > recommended limit for broker size (see [size-and-choose-cluster.md](size-and-choose-cluster.md)) | Approaching partition hard limit. Scale to larger broker size or add brokers to redistribute. |
| `BytesInPerSec` per broker | Express only | > ~80% of sustained ingress limit for broker size | Approaching per-broker ingress quota. Scale to larger broker size or add brokers. |
| `BytesOutPerSec` per broker | Express only | > ~80% of sustained egress limit for broker size | Approaching per-broker egress quota. Scale or reduce consumer groups. |

Standard brokers do not have MSK-enforced per-broker throughput quotas — throughput is bounded by EBS volume type and EC2 network bandwidth instead. For Standard throughput alarming, use `BwInAllowanceExceeded` and `BwOutAllowanceExceeded` in the performance alarms section above.

### Express-specific alarms

| Metric | Condition | Action |
|---|---|---|
| `ProduceThrottleTime` | Average > 0 for 5 min | Per-broker ingress quota exceeded. Scale to larger Express broker or add brokers. |
| `FetchThrottleTime` | Average > 0 for 5 min | Per-broker egress quota exceeded. Scale or reduce consumer groups. |
| `StorageUsed` | See below — anomaly detection by default; static threshold when retention is known | Express storage is fully managed but billed per byte-hour, so unbounded growth = unbounded cost. ALWAYS create a storage alarm — never skip it. |

**`StorageUsed` alarm — choose ONE of the two patterns:**

1. **Default (retention unknown, or you want to catch unusual growth):** anomaly-detection alarm on `StorageUsed`. CloudWatch builds a per-cluster baseline and alerts when usage falls outside the predicted band — no static threshold needed and it adapts as the workload changes. Use `LessThanLowerOrGreaterThanUpperThreshold` with `ANOMALY_DETECTION_BAND(m1, 2)`. This is the recommended default for new clusters where you don't yet know the steady-state size.

   ```
   aws cloudwatch put-metric-alarm \
     --alarm-name MSK-<cluster>-StorageUsed-Anomaly \
     --metrics '[
       {"Id":"m1","MetricStat":{"Metric":{"Namespace":"AWS/Kafka","MetricName":"StorageUsed","Dimensions":[{"Name":"Cluster Name","Value":"<cluster>"}]},"Period":300,"Stat":"Maximum"},"ReturnData":true},
       {"Id":"ad1","Expression":"ANOMALY_DETECTION_BAND(m1, 2)","Label":"StorageUsed (expected)"}
     ]' \
     --threshold-metric-id ad1 \
     --comparison-operator LessThanLowerOrGreaterThanUpperThreshold \
     --evaluation-periods 3 --datapoints-to-alarm 3 \
     --treat-missing-data notBreaching
   ```

2. **Static threshold (retention is known):** `Maximum > SUM(BytesInPerSec) × retention_seconds × 3` for 15 min (RF=3 on Express). Use this once the cluster has been running long enough to know steady-state ingress and retention is locked.

## CloudWatch Dimension Reference

All MSK metrics use namespace `AWS/Kafka`.

| Dimension | Format | Example |
|---|---|---|
| Cluster Name | String (cluster name, not ARN) | `my-msk-cluster` |
| Broker ID | Integer string | `1`, `2`, `3` |
| Topic | String | `my-topic` |
| Consumer Group | ASCII string (non-ASCII drops metrics) | `my-consumer-group` |
| Partition | Integer string | `0`, `1`, `2` |
| Client Authentication | String | `SSL`, `SASL_SCRAM`, `IAM` |

**Important**: Consumer group names MUST use ASCII characters only. Non-ASCII characters cause consumer lag metrics to be silently dropped from CloudWatch.

## Dashboard Construction

Create a CloudWatch dashboard with these sections:

1. **Cluster Health**: `ActiveControllerCount`, `OfflinePartitionsCount` (Standard), `UnderReplicatedPartitions` (Standard); for Express add `ProduceThrottleTime` and `FetchThrottleTime`
2. **CPU**: `CpuUser` per broker (line chart, one series per broker to spot AZ skew)
3. **Throughput**: `BytesInPerSec` and `BytesOutPerSec` per broker
4. **Storage**: `KafkaDataLogsDiskUsed` per broker (Standard); `StorageUsed` cluster-level (Express)
5. **Consumer Lag**: `MaxOffsetLag` per consumer group/topic
6. **Request Performance**: `RequestHandlerAvgIdlePercent`, `ProduceTotalTimeMsMean` per broker

Use metric math for composite CPU alarm: `m1 + m2` where m1 is defined as `CpuUser` and m2 is defined as `CpuSystem` for the target broker.
