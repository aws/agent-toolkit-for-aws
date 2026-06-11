# MSK Maintenance Operations

## How MSK Maintenance Works

### Standard brokers

During patching and version upgrades, MSK performs **rolling broker restarts** — one broker at a time. The cluster enters `MAINTENANCE` state. You can still produce and consume data, but you cannot perform MSK API update operations until the cluster returns to `ACTIVE`. These operations appear as `SECURITY_PATCHING` in the `DescribeClusterOperation` API.

**Expected client impact**: Transient disconnect errors and brief p99 latency spikes (high milliseconds, up to ~2 seconds) lasting up to 2 minutes per broker restart as clients reconnect to new leaders. With the default RF=3 and proper client configuration (retries, `delivery.timeout.ms >= 60000`, `acks=all`), this does NOT cause data loss or prolonged unavailability — retries transparently reconnect to the new leader within seconds. **Topics with RF=1 become completely unavailable while their broker restarts** — there is no replica to fail over to, so producers receive errors and consumers stall for the full restart duration (5-15 min). See [configure-clients.md](configure-clients.md) and the "Consumer Resilience During Maintenance" section below.

**Expected metric impact**: `UnderReplicatedPartitions` increases temporarily (partitions on the offline broker stop replicating). After restart, the broker catches up on missed messages — you may see increased volume throughput and CPU usage during catch-up.

### Express brokers

Express brokers have **no maintenance windows**. MSK updates Express broker software on an ongoing basis in a **time-distributed manner** — occasional singular broker reboots spread across the month. The cluster stays `ACTIVE` during all maintenance. These operations appear as `BROKER_UPDATE` in the `DescribeClusterOperation` API.

**Why Express patching is less disruptive**:

- No cluster-wide maintenance window to plan around
- Throughput quotas prevent overloading during broker restarts
- Fixed RF=3 guarantees all topics survive a single broker restart (no RF=1 or RF=2 topics)
- Faster catch-up after restart than Standard brokers
- No advance notification needed

**Client contract still applies**: Clients must still handle leadership failover. Configure producers with retries, `delivery.timeout.ms >= 60000`, and `acks=all`; configure consumers with `session.timeout.ms = 45000-60000`. See [configure-clients.md](configure-clients.md) and the "Consumer Resilience During Maintenance" section below.

## What Happens During a Rolling Restart

When a broker restarts during maintenance:

1. **Broker goes offline**: The broker's metrics disappear from CloudWatch for several minutes.
2. **Leadership transfer**: Partition leadership moves from the restarting broker to other in-sync replicas. `LeaderCount` shifts across brokers.
3. **UnderReplicatedPartitions (URP) spikes** (Standard only — Express does not emit URP): While the broker is down, its partitions are under-replicated. This is expected and temporary.
4. **ActiveControllerCount may change**: If the controller broker is restarted, a new controller is elected.
5. **Consumer group rebalances**: If consumers were connected to the restarting broker, the session timeout triggers a rebalance.
6. **Broker restarts and catches up**: The broker comes back online, loads logs, replicates missed data, and rejoins ISR. URP decreases as replicas catch up.
7. **MSK moves to the next broker**: MSK waits for the broker to fully catch up before restarting the next one.

**Typical timeline per broker**: 5-15 minutes depending on data volume and partition count. Log loading progress can be tracked via the JMX metrics `remainingLogsToRecover` and `remainingSegmentsToRecover` (available through Prometheus/JMX monitoring, not via CloudWatch).

**Speeding up log recovery**: By default, Kafka uses a single thread per log directory for log recovery after an unclean shutdown. With thousands of partitions, recovery can take hours. Set `num.recovery.threads.per.data.dir` to the number of CPU cores to parallelize recovery. This is a broker-side configuration — update via `aws kafka update-cluster-configuration`.

## What NOT To Do During Maintenance

- **NEVER restart additional brokers** — MSK is already performing a rolling restart. Manual restarts compound the problem.
- **NEVER reassign partitions during URP** — Reassignment adds replication load on already-stressed brokers.
- **NEVER lower `min.insync.replicas`** — This weakens durability guarantees. The `NotEnoughReplicasException` during maintenance is transient.
- **NEVER escalate as a cluster-level issue** if URP is decreasing and only one broker has a metrics gap.

## Impact of Scaling Operations (Standard)

Scaling operations on Standard clusters trigger rolling restarts or add replication load. Plan these during low-traffic periods and ensure the cluster has headroom.

### Broker size updates

Updating the broker size (e.g., kafka.m5.large → kafka.m5.xlarge) triggers a **rolling restart** — MSK takes brokers offline one at a time and temporarily reassigns partition leadership to other brokers. This is the same process as a maintenance rolling restart. A size update typically takes **10-15 minutes per broker**. During this time:

- `UnderReplicatedPartitions` will spike per broker, same as during patching
- Remaining brokers absorb extra leadership and replication load
- Ensure CPU is under 60% before initiating a size change

### Adding brokers and reassigning partitions

After adding brokers to expand a Standard cluster, existing partitions are NOT automatically redistributed. You must manually reassign partitions using `kafka-reassign-partitions.sh`. This creates replication load as data is copied from existing brokers to new ones.

**Constraints:**

- Limit to **10 partitions per reassignment call** for safe operations on Standard clusters
- Do NOT reassign partitions when CPU utilization is above **70%** — replication adds significant CPU and network load that can cascade
- Do NOT reassign partitions while `UnderReplicatedPartitions` > 0
- Consider using [Cruise Control](https://docs.aws.amazon.com/msk/latest/developerguide/cruise-control.html) for continuous, automated partition rebalancing

### Storage expansion

Expanding EBS storage does NOT trigger a rolling restart — it happens online. However, the volume enters an **optimizing** state that can take up to 24 hours, and a second expansion cannot be performed for at least 6 hours. See [manage-storage.md](manage-storage.md) for details.

## Impact of Scaling Operations (Express)

Express scaling is simpler than Standard, but broker size changes still involve rolling restarts.

### Broker size updates

Updating the Express broker size also triggers a **rolling restart**, same as Standard. MSK takes brokers offline one at a time. However, the cluster stays **ACTIVE** (not MAINTENANCE) throughout. Key differences from Standard:

- Express does **not** emit `UnderReplicatedPartitions` — you cannot use URP to track restart progress. Monitor `ProduceThrottleTime`, `FetchThrottleTime`, and consumer lag instead.
- Ensure CPU (CpuUser + CpuSystem) is under 60% before initiating a size change, same as Standard.

### Adding brokers and partition redistribution

When you add brokers to an Express cluster:

- If **Intelligent Rebalancing is enabled** (default): Partitions are automatically redistributed to new brokers. No manual action needed. You cannot use `kafka-reassign-partitions.sh` while Intelligent Rebalancing is active.
- If **Intelligent Rebalancing is disabled**: You must manually reassign partitions using `kafka-reassign-partitions.sh`. Limit to **20 partitions per reassignment call** (vs 10 for Standard).

### Storage

Express storage is fully managed — there is no expansion operation, no cooldown period, and no provisioning required. Storage scales automatically with data retained. However, you should still monitor `StorageUsed` and per-topic ingress to catch runaway growth that impacts cost. See [manage-storage.md](manage-storage.md) for investigation steps.

## Consumer Resilience During Maintenance

Configure consumers to survive broker restarts gracefully. See [configure-clients.md](configure-clients.md) for full settings.

**Key settings for maintenance resilience:**

| Setting | Recommended | Why |
|---|---|---|
| `session.timeout.ms` | 45000-60000 | Must exceed time for broker restart + consumer reconnection. Default 10000 is too short. |
| `heartbeat.interval.ms` | 10000-15000 | Should be < 1/3 of `session.timeout.ms`. |
| `partition.assignment.strategy` | `CooperativeStickyAssignor` | Incremental rebalances instead of stop-the-world. Only moved partitions are reassigned. |
| `group.instance.id` | Unique per consumer | Enables static membership. Consumer can rejoin after brief disconnect without triggering full rebalance. |
| `group.initial.rebalance.delay.ms` | Match average deployment time | **Broker-side config** (set via `aws kafka update-cluster-configuration`, not consumer properties). Prevents cascading rebalances during rolling deployments. |

**Producer settings for maintenance:**

| Setting | Recommended | Why |
|---|---|---|
| `retries` | Integer.MAX_VALUE | Allows retrying through broker restart. |
| `delivery.timeout.ms` | 60000 minimum; 120000 (2 minutes) or higher | Bounds total retry time. AWS recommends a minimum of 60 seconds. Must be ≥ `request.timeout.ms` + `linger.ms`. With RF=3 and `min.insync.replicas=2`, producers only stall during leader election (seconds, not minutes). The 2-min default covers this. Increase if you observe `TimeoutException` during maintenance. |
| `acks` | `all` | With `min.insync.replicas=2` (MSK default), writes succeed as long as 2 of 3 replicas are available. One broker offline is tolerated. |

## Preparing for Maintenance Windows (Standard)

1. **Ensure CPU < 60%**: During maintenance, remaining brokers handle extra leadership and replication. If CPU is already near 60%, the added load during maintenance may cause cascading issues.
2. **Ensure storage headroom**: Brokers that take over leadership temporarily handle more writes.
3. **Use 3-AZ clusters with RF=3 and min.insync.replicas=2**: This tolerates one broker offline.
4. **Distribute connection strings across AZs**: Client bootstrap servers SHOULD include at least one broker from each AZ.
5. **Test consumer resilience**: Simulate broker failure by rebooting a broker via the MSK API: `aws kafka reboot-broker --cluster-arn <arn> --broker-ids <id>`.

## Kafka Version Upgrades

Version upgrades trigger rolling restarts. The process:

1. MSK updates brokers one at a time to the new version.
2. Between each broker restart, MSK waits for the broker to fully catch up.
3. The cluster enters `UPDATING` state during the upgrade.

**Constraints:**

- You MUST check that partition counts per broker are within the limits for the target version before upgrading (see [size-and-choose-cluster.md](size-and-choose-cluster.md)).
- Upgrades are forward-only — you cannot downgrade Kafka versions.
- Express brokers support Kafka versions 3.6, 3.8, and 3.9.

## Monitoring During Maintenance

Watch these metrics to track maintenance progress:

| Metric | What to Look For |
|---|---|
| `UnderReplicatedPartitions` (Standard only) | Should spike when a broker restarts, then decrease as it catches up. If URP stays elevated for > 30 min after a broker comes back, investigate. Express does not emit this metric. |
| `ActiveControllerCount` | Should always be 1. Brief fluctuation during controller broker restart is normal. |
| `CpuUser` on remaining brokers | Should increase temporarily as they absorb extra leadership. If > 80%, cluster is undersized for maintenance. |
| `BytesInPerSec` per broker | Should redistribute when a broker goes offline and rebalance when it returns. |
| `LeaderCount` per broker | Should shift during restart and rebalance afterward via `auto.leader.rebalance.enable=true` (MSK default). |
