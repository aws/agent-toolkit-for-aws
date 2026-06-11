# Manage MSK Storage

## Standard Brokers: EBS Storage Management

### Monitor disk usage

Monitor `KafkaDataLogsDiskUsed` (DEFAULT level, dimensions: Cluster Name, Broker ID). This metric shows the percentage of disk used for data logs per broker. Set a CloudWatch alarm at 85%.

MSK also sends proactive storage alerts at 60% and 80% usage via the MSK console, Health Dashboard, EventBridge, and account email.

### Expand EBS storage

You can increase but NEVER decrease EBS volume size. Maximum: 16,384 GiB (16 TiB) per broker.

```
aws kafka update-broker-storage \
  --cluster-arn <cluster-arn> \
  --current-version <cluster-version> \
  --target-broker-ebs-volume-info '[{"KafkaBrokerNodeId": "All", "VolumeSizeGB": <target-size>}]'
```

**Constraints:**

- You MUST get the current cluster version first: `aws kafka describe-cluster-v2 --cluster-arn <arn>` — the version string looks like `KTVPDKIKX0DER`, not a simple integer.
- Storage expansion has a cool-down period of minimum 6 hours. A second expansion attempt during cool-down fails with "storage is optimizing."
- Optimization after expansion can take up to 24 hours proportional to storage size.

### Enable auto-scaling

Auto-scaling automatically expands storage when utilization reaches a threshold. Configure via the MSK console or Application Auto Scaling API.

Policy parameters:

- **Storage Utilization Target**: Recommended 50-60%. Range: 10-80%.
- **Maximum Storage Capacity**: Up to 16 TiB per broker.

Auto-scaling increases storage by the larger of 10 GiB or 10% of current storage. A scaling action can occur only once every 6 hours.

**Long-term alternative**: If recurring storage management is a pain point, consider migrating to Express brokers — storage is fully managed, pay-as-you-go, and requires no provisioning or monitoring.

### Identify high-growth topics

To find which topics consume the most storage, check per-topic `BytesInPerSec` (PER_TOPIC_PER_BROKER level) and multiply by retention period:

`Estimated storage per topic = SUM(BytesInPerSec across all brokers for the topic) × retention_seconds × ReplicationFactor`

Use this to identify topics that need retention adjustment. Retention changes require app-owner approval — reducing retention deletes data permanently.

### Provision storage throughput (Standard only)

For broker sizes `kafka.m5.4xlarge` or larger (or `kafka.m7g.2xlarge` or larger), you can provision storage throughput above the default of 250 MiB/s (for volumes 10 GiB+). Check the [MSK storage throughput documentation](https://docs.aws.amazon.com/msk/latest/developerguide/msk-provision-throughput-management.html) for current max provisioned throughput per broker size.

When enabling provisioned throughput, also increase `num.replica.fetchers` (default 2) to match the instance size — e.g., 4 for m5.4xl, 8 for m5.8xl.

## Express Brokers: Managed Storage

Express brokers have fully managed, pay-as-you-go storage. You do NOT provision or manage EBS volumes.

### How Express storage works

Express storage is elastic and virtually unlimited. You do not provision volumes or manage capacity. However, storage is pay-as-you-go based on total data retained, so runaway growth directly impacts cost.

### Monitor Express storage

Monitor total cluster storage with the `StorageUsed` metric (DEFAULT level, dimension: Cluster Name). There are no per-broker disk usage metrics for Express because storage is not tied to individual brokers.

Set a CloudWatch alarm on `StorageUsed` based on expected retention:

`Expected StorageUsed ≈ SUM(BytesInPerSec across all topics) × retention_seconds × 3`

The `× 3` accounts for Express's fixed replication factor. If `StorageUsed` significantly exceeds this estimate, investigate per-topic growth.

### Identify and resolve runaway storage growth

Even though Express storage scales automatically, you should actively monitor for unexpected growth to control costs:

1. **Check per-topic ingress**: Use `BytesInPerSec` at PER_TOPIC_PER_BROKER level to identify which topics are driving the most data volume.
2. **Check topic-level retention overrides**: A topic with `retention.ms` set higher than the cluster default will retain more data. Audit topic configs with:

   ```
   kafka-configs.sh --bootstrap-server <bootstrap> --describe --entity-type topics --entity-name <topic>
   ```

3. **Check for compacted topics**: Topics with `cleanup.policy=compact` retain data indefinitely based on key cardinality, not time. High-cardinality compacted topics can grow without bound.
4. **Check for topic proliferation**: A growing number of topics (each with RF=3) compounds storage. Monitor `GlobalTopicCount` at the cluster level.
5. **Reduce retention**: Lowering `retention.ms` on high-volume topics is the most direct way to reduce stored data. Coordinate with app owners before changing — reducing retention deletes data permanently.

### Storage costs on Express

Express storage is fully managed. Unlike Standard where you explicitly manage EBS and optionally enable tiered storage, Express storage requires no configuration. Storage costs are based on total data retained — reducing retention or cleaning up unused topics is the primary lever for cost control.

## Standard Brokers: Tiered Storage

Standard brokers can optionally enable tiered storage to extend retention beyond EBS capacity.

### How tiered storage works on Standard

1. Closed log segments are copied from primary (EBS) storage to tiered (S3) storage automatically.
2. Active segments are NOT eligible for tiering — segment size (`segment.bytes`, default 128 MiB for tiered clusters) or segment roll time (`segment.ms`) controls when segments close.
3. `local.retention.ms` controls how long data stays on primary storage after being copied to tiered storage. Default `-2` means use `retention.ms` (data stays on both local and tiered until retention expires).
4. `retention.ms` controls total retention (local + tiered). Minimum 3 days for tiered topics.

### Example retention scenario

With `retention.ms = 5 days` and `local.retention.ms = 12 hours`:

- Data stays on fast primary storage for 12 hours
- Data remains in tiered storage for the full 5 days
- Consumers reading data older than 12 hours fetch from tiered storage with slightly higher initial latency

### Tiered storage constraints

- Compacted topics (`cleanup.policy=compact`) are NOT supported with tiered storage
- When explicitly set to a positive value, `local.retention.ms` MUST be less than `retention.ms`. The default `-2` is a sentinel meaning "use `retention.ms`" and is always valid.
- Minimum log segment size: 48 MiB; minimum segment roll time: 10 minutes
- Once disabled for a topic, tiered storage CANNOT be re-enabled on that topic
- Supported on Kafka versions 3.6.0+ and 2.8.2.tiered
- Not supported on `kafka.t3.small` instances
- Clients SHOULD NOT use `read_committed` isolation level when reading from tiered storage unless actively using transactions

### Enable tiered storage on a topic

```
kafka-configs.sh --bootstrap-server <bootstrap> --alter --entity-type topics --entity-name <topic> \
  --add-config 'remote.storage.enable=true,local.retention.ms=43200000,retention.ms=604800000'
```
