# Pre-Migration Sizing Assessment

**When to use:** Before migrating, assess source workload to determine target sizing: memory, CPU, connections, throughput. Prevents undersizing (performance degradation) or oversizing (wasted cost).

Before migrating, assess the source workload to determine appropriate target sizing. Undersizing causes performance degradation; oversizing wastes cost.

## Memory Utilization and Peak Usage

Collect current and peak memory from the source:

```bash
# Self-managed Redis
valkey-cli -h <source-host> INFO memory | grep -E "used_memory_human|used_memory_peak_human|used_memory_dataset_perc|mem_fragmentation_ratio"

# ElastiCache (via CloudWatch)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name DatabaseMemoryUsagePercentage \
  --dimensions Name=CacheClusterId,Value=<cache-cluster-id> Name=CacheNodeId,Value=0001 \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Maximum Average \
  --region <region>
```

**Sizing rules:**

* **Node-based:** choose a node whose `maxmemory` is at least 2x current peak usage to account for growth, fragmentation, and the default 25% `reserved-memory-percent` (which leaves only 75% of `maxmemory` for data). Account for `reserved-memory-percent` (default 25% for accounts created on or after March 16, 2017; accounts created before that date default to `reserved-memory` with 0 bytes reserved). For burstable instance types, increase `reserved-memory-percent` up to 50% on micro instances and up to 30% on small instances to avoid swap usage during backup and replication.
* **Serverless:** set `DataStorage.Maximum` to at least 2x current usage. The higher multiplier accounts for auto-scaling buffer and the fact that you cannot manually tune memory allocation.
* If `mem_fragmentation_ratio` is above 1.5, the actual memory needed may be lower after migration (ElastiCache manages memory more efficiently).

### CPU Utilization and Command Mix

High CPU on the source may indicate the need for more shards or a larger node type on the target.

```bash
# Self-managed Redis
valkey-cli -h <source-host> INFO commandstats

# Identify expensive commands
valkey-cli -h <source-host> SLOWLOG GET 50

# ElastiCache (via CloudWatch)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name EngineCPUUtilization \
  --dimensions Name=CacheClusterId,Value=<cache-cluster-id> Name=CacheNodeId,Value=0001 \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Maximum Average \
  --region <region>
```

**Sizing rules:**

* If source CPU consistently exceeds 70%, consider adding shards (horizontal scaling) on the target rather than just matching the source topology.
* Heavy `KEYS`, `SORT`, or Lua script usage drives CPU. These patterns may need optimization regardless of migration.
* For serverless targets, CPU is managed automatically, but high-CPU command patterns will increase ECPU consumption and cost.

### Connection Count and Throughput

```bash
# Self-managed Redis
valkey-cli -h <source-host> INFO clients | grep -E "connected_clients|maxclients"
valkey-cli -h <source-host> INFO stats | grep -E "instantaneous_ops_per_sec|total_commands_processed"

# ElastiCache (via CloudWatch)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name CurrConnections \
  --dimensions Name=CacheClusterId,Value=<cache-cluster-id> Name=CacheNodeId,Value=0001 \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Maximum \
  --region <region>
```

**Sizing rules:**

* Both serverless caches and individual ElastiCache node-based nodes support up to 65,000 concurrent client connections (`maxclients`). Verify the peak connection count is within this limit.
* For serverless, connections scale automatically. ECPU consumption is per-request, not per-connection; idle connections do not consume ECPUs. However, use connection pooling to reduce overhead from connection setup.
* If connection count is high, recommend connection pooling in the application (most client libraries support this).
* Throughput (ops/sec) helps determine whether a single shard is sufficient or multiple shards are needed.

### Source-to-Target Sizing Recommendations

| Source Metric | Serverless Target | Node-Based Target |
|---------------|-------------------|-------------------|
| Memory < 1 GB | Default limits (~$6/month minimum) | cache.t4g.small (t4g.micro has only 0.5 GiB; with 25% reserved-memory, usable is ~0.375 GiB) |
| Memory 1-10 GB | Set DataStorage.Maximum to 2x peak | cache.r7g.large (1 shard) |
| Memory 10-50 GB | Set DataStorage.Maximum to 2x peak | cache.r7g.xlarge (1-2 shards) |
| Memory 50-200 GB | Evaluate cost vs node-based | cache.r7g.2xlarge (multiple shards) |
| Memory > 200 GB | Node-based recommended for cost | cache.r7g.4xlarge+ (multiple shards) |
| Ops/sec < 10,000 | Default ECPU limits | Single shard sufficient |
| Ops/sec 10,000-100,000 | Increase ECPUPerSecond.Maximum | 1-3 shards depending on node type |
| Ops/sec > 100,000 | Evaluate cost vs node-based | Multiple shards, consider cluster mode enabled |
| Connections < 1,000 | Default | Most node types support this |
| Connections 1,000-10,000 | Default (scales automatically) | cache.r7g.large+ |
| Connections > 10,000 | Default (but review ECPU cost) | cache.r7g.xlarge+ with connection pooling |

**Migration method constraints:**

* Online migration is **not supported** to ElastiCache serverless caches or clusters running on the r6gd (data tiering) node type. If you plan to use online migration, choose a non-r6gd node-based target. For serverless or r6gd targets, use backup/restore or another migration strategy.
* Online migration additionally requires: the target must have transit encryption (TLS) disabled, Multi-AZ enabled, and not be part of a Global Datastore. The source must not have AUTH enabled and must have `protected-mode` set to `no`. Shard counts should match between source and target. See `topology-validation.md` for the full prerequisites checklist.

Run cost estimation to compare current spend vs target:

```bash
# For node-based to serverless migrations (uses actual cluster metrics)
python3 scripts/serverless_estimator.py --input clusters.csv --commandstats stats.csv

# For greenfield cost comparison (serverless)
python3 scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>
# For greenfield cost comparison (node-based with RI options)
python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options
```

To collect metrics from a running cluster for the estimator:

```bash
./scripts/collect_metrics.sh <endpoint> <port> [output_prefix]
```
