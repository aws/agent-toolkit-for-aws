# Troubleshoot MSK Consumer Lag

## Step 1: Determine the lag pattern

Check `SumOffsetLag` (DEFAULT level, dimensions: Cluster Name, Consumer Group, Topic) and `OffsetLag` (PER_TOPIC_PER_PARTITION level, dimensions: Consumer Group, Topic, Partition).

**Decision tree:**

- **Lag increasing across all partitions and consumer groups**: Likely a broker-side issue — go to Step 2.
- **Lag increasing on specific partitions only**: Likely partition skew or hot keys — go to Step 3.
- **Lag increasing on one consumer group only**: Likely a client-side issue — go to Step 4.
- **Lag spiked then is recovering**: Check if maintenance is in progress — go to Step 5.

## Step 2: Broker-side bottleneck

Check these broker metrics (PER_BROKER level):

- `CpuUser + CpuSystem` > 60%: Broker is overloaded. See [troubleshoot-performance.md](troubleshoot-performance.md).
- `ProduceTotalTimeMsMean` elevated: Produce latency is high, slowing replication and consumer fetches.
- `FetchConsumerTotalTimeMsMean` elevated: Consumer fetch requests are slow at the broker.
- `RequestHandlerAvgIdlePercent` < 30%: Request handlers saturated — check client batch sizes before scaling. See [troubleshoot-performance.md](troubleshoot-performance.md) Step 3.
- `NetworkProcessorAvgIdlePercent` < 30%: Network threads saturated. May indicate connection storms, high TLS overhead, or too many small requests.

**Standard-specific checks** (skip for Express):

- `VolumeQueueLength` elevated or `VolumeTotalWriteTime` increasing: EBS throughput saturated. Calculate `BytesInPerSec × RF` vs volume throughput ceiling (250 MiB/s default for GP2/GP3). See [troubleshoot-performance.md](troubleshoot-performance.md) Step 4.
- `BwInAllowanceExceeded` or `BwOutAllowanceExceeded` > 0: EC2 network bandwidth exceeded — traffic shaping active. Check per-broker traffic distribution for AZ skew. See [troubleshoot-performance.md](troubleshoot-performance.md) Step 5.
- `HeapMemoryAfterGC` > 60%: Memory pressure after GC. High connection count, excessive consumer groups, or high partition count can drive this. Reduce `transactional.id.expiration.ms` from 7 days to 1 day as a quick win.
- `BurstBalance` dropping toward 0: GP2 volume I/O burst credits depleting under sustained load. Consider provisioned throughput (GP3) or a larger instance type.

**Express-specific checks:**

- `ProduceThrottleTime` or `FetchThrottleTime` > 0: Per-broker throughput quota exceeded. Scale to a larger Express broker size or add brokers.

If all broker metrics are healthy, the issue is client-side — go to Step 4.

## Step 3: Partition-level bottleneck (hot keys)

When lag is isolated to specific partitions while others have zero lag, the cause is typically:

1. **Hot key partition skew**: Uneven key distribution concentrates data on a few partitions. The consumer instances handling those partitions cannot keep up.
2. **Single consumer bottleneck**: If the consumer processing those partitions is slower (e.g., heavy transformation, external API calls), lag builds up on its assigned partitions.

**Confirm with**: PER_TOPIC_PER_PARTITION level `OffsetLag` — check which partitions have growing lag. Use `kafka-consumer-groups.sh --describe --group <group-id>` to see per-partition lag alongside which consumer owns each partition. Compare per-topic-per-broker `BytesInPerSec` to see if specific brokers receive disproportionate data for that topic.

**Important**: Adding partitions does NOT fix key skew — each hot key still hashes to exactly one partition, so the disproportionate load from high-volume keys remains concentrated regardless of how many partitions exist. You must fix the key distribution itself.

**Fix options:**

- Improve key distribution (add a sub-key or use a different partitioning strategy) to spread data more evenly
- Increase partition count for the topic only if keys are well-distributed but partition count is too low for consumer parallelism (requires app-level coordination)
- Optimize the slow consumer's processing logic (reduce per-record processing time)
- Increase the number of consumers in the group (up to the number of partitions — consumers beyond partition count sit idle)

## Step 4: Client-side consumer issues

### Slow processing

If `max.poll.interval.ms` is exceeded, the consumer is kicked from the group, triggering a rebalance. Check the consumer application for:

- Long-running processing per batch (database writes, HTTP calls)
- Exceptions in message processing causing retries
- `max.poll.records` too high for the processing time available
- Deserialisation errors silently dropping messages or causing retry loops

**Fix**: Reduce `max.poll.records`, optimize processing logic, or increase `max.poll.interval.ms` (not recommended as a first option — it masks the real problem).

### Insufficient consumers

If the number of consumers in the group is less than the number of partitions, some consumers handle multiple partitions and may not keep up. Check consumer group membership via Kafka CLI (requires direct broker connectivity):

```
kafka-consumer-groups.sh --bootstrap-server <bootstrap> --describe --group <group-id>
```

Look at the `LAG` column per partition and the `CONSUMER-ID` column to see which consumers are overloaded.

### Fetch configuration issues

Poor fetch settings can cause the consumer to make excessive small requests, wasting broker resources and slowing the consumer loop:

- `fetch.min.bytes` too low (default 1 byte): Every fetch returns immediately even with minimal data, generating high request rates. Set to at least 1 KB; 32-128 KB for throughput workloads.
- `fetch.max.wait.ms` too low: Broker returns partial fetches too quickly. Recommend 1000ms.
- Monitor client-side `fetch-rate` and `records-consumed-rate` metrics. A high `fetch-rate` with low `records-consumed-rate` indicates inefficient fetching.

### Stuck on `read_committed` with no active transactions

If `isolation.level=read_committed` is set, the consumer only reads up to the Last Stable Offset (LSO). A hanging transaction from a crashed or misconfigured transactional producer will prevent the LSO from advancing, causing lag to grow indefinitely on affected partitions — even if the current producers are non-transactional. Common causes: a Kafka Streams app with `processing.guarantee=exactly_once_v2` that crashed, or a previous producer version that set `transactional.id` and was decommissioned without cleanly aborting its transactions. **Fix**: If no producers actively use transactions, set `isolation.level=read_uncommitted`. Otherwise, check for hanging transactions — see below.

### Hanging transactions

If `OffsetLag` grows on partitions of `__consumer_offsets`, a hanging transaction may block offset commits. Detect with Kafka CLI:

```
kafka-transactions.sh --bootstrap-server <bootstrap> find-hanging --broker-id <broker-id>
```

Abort hanging transactions:

```
kafka-transactions.sh --bootstrap-server <bootstrap> abort --topic __consumer_offsets --partition <partition> --start-offset <offset>
```

## Step 5: Maintenance-induced lag

MSK performs rolling broker restarts during patching (Standard brokers enter MAINTENANCE state; Express brokers stay ACTIVE).

**Confirm maintenance is in progress**: Run `aws kafka describe-cluster-v2 --cluster-arn <arn>` and check `ClusterState`. A value of `MAINTENANCE` (Standard) or `UPDATING` confirms an operation is underway. Express clusters stay `ACTIVE` during maintenance, so check the MSK console or EventBridge for maintenance notifications.

**Symptoms during maintenance (Standard):**

- `UnderReplicatedPartitions` spikes then gradually decreases (Standard only — Express does not emit this metric)
- `ActiveControllerCount` changes (controller election)
- One broker's metrics disappear from CloudWatch for several minutes then resume
- Consumer groups rebalance due to broker disconnect

**Symptoms during maintenance (Express):**

- No `UnderReplicatedPartitions` metric available — cannot use URP to track progress
- `ProduceThrottleTime` or `FetchThrottleTime` may briefly spike if remaining brokers absorb extra load
- Consumer lag increases temporarily then recovers
- `ActiveControllerCount` may briefly fluctuate

**This is expected and self-resolving.** Do NOT:

- Restart additional brokers
- Reassign partitions during URP (Standard) or during active maintenance
- Escalate as a cluster issue if lag is recovering

**Consumer resilience configuration** to minimize maintenance impact — see [configure-clients.md](configure-clients.md):

- `session.timeout.ms = 45000` (or 60000)
- `heartbeat.interval.ms = 10000` (or 15000)
- `partition.assignment.strategy = CooperativeStickyAssignor`
- `group.instance.id` set to a unique value per consumer instance

## Step 6: Consumer group rebalance storms

**Symptoms**: Consumer group state alternates between `Stable` and `PreparingRebalance`. `rebalance-latency-avg` client metric is elevated. Lag grows during each rebalance cycle.

**Common causes:**

1. **Consumer crashes with default RangeAssignor**: Each crash triggers a full stop-the-world rebalance, which can cascade.
2. **`session.timeout.ms` too low**: Default 10000ms (10s) is too short — GC pauses, network blips, or slow consumer startup can cause false evictions, triggering unnecessary rebalances.
3. **Deployment-triggered rebalances**: Restarting all consumers at once causes a cascade of join/leave events. Set `group.initial.rebalance.delay.ms` (broker-side config) to match your average deployment time to batch rebalances.
4. **Topic deletions**: Deleting a topic subscribed by a consumer group triggers a rebalance.
5. **Too many consumer groups**: List groups with `kafka-consumer-groups.sh --bootstrap-server <bootstrap> --list | wc -l`. Excessive consumer groups overload the group coordinator broker.
6. **Stuck rebalance (Kafka ≤ 2.6 bug, KAFKA-9752)**: On clusters running Kafka ≤ 2.6, a consumer group can get stuck in `PreparingRebalance`. This bug does not affect Kafka 3.x+ or Express brokers. Mitigation: identify the coordinator broker and restart it. **Before restarting any broker**, verify `UnderReplicatedPartitions == 0` — restarting during URP risks data loss.

**Fix**:

- Switch to `CooperativeStickyAssignor` to enable incremental rebalances instead of stop-the-world. **Migration requires two rolling restarts**: first deploy with `partition.assignment.strategy=RangeAssignor,CooperativeStickyAssignor`, then remove `RangeAssignor` in a second deployment. Mixing eager and cooperative protocols in the same group causes `InconsistentGroupProtocolException`.
- Set `group.instance.id` for static group membership — consumers can rejoin after brief disconnects without triggering a full rebalance.
- Set `session.timeout.ms = 45000-60000` and `heartbeat.interval.ms = 10000`.
- Set `group.initial.rebalance.delay.ms` (broker-side) to match deployment rollout time.
- Implement a shutdown hook to call `consumer.close()` on SIGTERM for clean group leave instead of relying on session timeout.

**To identify the coordinator broker:**

```
kafka-consumer-groups.sh --bootstrap-server <bootstrap> --describe --group <group-id> --state
```

The output shows the coordinator. If the group is stuck in `PreparingRebalance` on older Kafka versions, restarting the coordinator broker can unblock it.
