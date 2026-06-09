# Hot Key and Hot Shard Detection

**When to use:** The user reports uneven shard load, one node pinned at high CPU while peers are idle, latency spikes correlated with specific request patterns, or suspected "hot key" problem.
**When not needed:** Broadly high engine CPU across all shards (that's capacity, not a hot key: see `troubleshooting.md` High CPU). Memory pressure with evictions is a different playbook (see Memory Pressure). Connection storms are not hot-key issues (see Connection Spikes).

## Objective

Given a cluster with a suspected hot-key problem, answer three questions in order:

1. Is there actually per-shard imbalance, or is the whole cluster hot?
2. If imbalanced, which shard (which slot range) is hot?
3. Within the hot shard, which specific key is hot?

Each step has stop conditions. Do not proceed to the next step unless the current step confirms the problem.

## Preconditions and Decision Tree

### Check 1: Deployment model

```
Serverless  → Tier A (CloudWatch) plus limited client-side diagnostics.
              Tiers B and C are not available.
              See "Serverless-specific considerations" below for the full diagnostic order.
Node-based  → All tiers available, proceed through Check 2.
```

### Check 2: Engine and version (node-based only)

```
Valkey 8.0+ cluster mode (node-based only) → Tier B (CLUSTER SLOT-STATS) is available and preferred.
Valkey 7.x, Redis OSS 7.x   → Skip Tier B. Use Tier A to find the hot node, then Tier C.
Cluster mode disabled        → Single shard. Skip Tier B. Tier A and Tier C only.
```

Check engine version (use `describe-cache-clusters` which exposes both fields):

```bash
aws elasticache describe-cache-clusters \
  --cache-cluster-id <node-id> --region <region> \
  --query 'CacheClusters[0].[CacheNodeType,EngineVersion,Engine]'
```

### Check 3: Eviction policy (gates Tier C only)

`OBJECT FREQ` requires an LFU policy (`allkeys-lfu` or `volatile-lfu`). `CONFIG GET` is restricted on all ElastiCache caches; check the parameter group instead:

```bash
aws elasticache describe-cache-parameters \
  --cache-parameter-group-name <parameter-group-name> \
  --query "Parameters[?ParameterName=='maxmemory-policy'].ParameterValue" \
  --output text --region <region>
```

- **LFU policy set** → Tier C is available.
- **Non-LFU, can change** -> Change via parameter group; `maxmemory-policy` takes effect immediately (no restart needed), then Tier C.
- **Non-LFU, cannot change** → Skip Tier C. Fallback: Tier B if Valkey 8.0+ cluster mode, otherwise slow log analysis, then `valkey-cli --bigkeys`, then client-side instrumentation. Note: `valkey-cli --hotkeys` also requires LFU.
- **Serverless** → Skip Tier C entirely. Serverless blocks `OBJECT FREQ`.

## Tier A: Triage with CloudWatch

Always-available first step. Tells you whether the problem is real and narrows where to look.

### Step 1: Confirm per-shard imbalance (node-based)

Query `EngineCPUUtilization` per node using the `CacheClusterId` dimension. Do NOT query with `ReplicationGroupId`; the aggregate hides imbalance.

> **Note on CPU metrics:** `EngineCPUUtilization` measures only the main Valkey/Redis OSS engine thread. On nodes with 4+ vCPUs where enhanced I/O features are active, network I/O and TLS processing are offloaded to dedicated I/O threads not captured by `EngineCPUUtilization`, so it may appear lower than expected. For smaller node types with 2 vCPUs or less, use `CPUUtilization` instead. Also check `TrafficManagementActive`; a value of 1 indicates the node may be underscaled for the workload — ElastiCache is actively managing/throttling traffic to protect the engine.

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name EngineCPUUtilization \
  --dimensions Name=CacheClusterId,Value=<node-id> \
  --start-time <1h-ago> --end-time <now> \
  --period 60 --statistics Maximum \
  --region <region>
```

Run for each node (`describe-cache-clusters --show-cache-node-info` to list nodes).

**Stop condition:** If all nodes are within 15 percentage points of each other, this is not a hot-key problem. Route to the High CPU playbook in `troubleshooting.md`.

If one node is at least 1.5x the cluster median, proceed.

### Step 2: Identify the data type driving traffic

Query command-family metrics on the hot node: `StringBasedCmds`, `HashBasedCmds`, `SetBasedCmds`, `SortedSetBasedCmds`, `ListBasedCmds`, `StreamBasedCmds`, `PubSubBasedCmds`, `JsonBasedCmds`, `SearchBasedCmds`.

The family with the highest rate on the hot node points to the data type of the hot key.

### Step 3: Check slow log (node-based only, with log delivery enabled)

Slow log delivery must be enabled via log delivery configuration (see `log-delivery.md` for setup). Search for repeated key patterns. A key appearing in many slow-log entries is a strong hot-key candidate, especially with `HGETALL`, `SMEMBERS`, `LRANGE 0 -1`, `ZRANGE 0 -1`, or `SORT`.

```bash
aws logs filter-log-events \
  --log-group-name /aws/elasticache/<cluster-id>/slowlog \
  --start-time <1h-ago-ms> \
  --filter-pattern "<suspected-key-prefix>" \
  --region <region>
```

### Step 4: Consult LATENCY commands (node-based only)

```bash
valkey-cli -h <endpoint> -p 6379 --tls LATENCY DOCTOR
valkey-cli -h <endpoint> -p 6379 --tls LATENCY LATEST
valkey-cli -h <endpoint> -p 6379 --tls LATENCY HISTORY <event-name>
```

Serverless: the entire `LATENCY *` family is blocked. Use `SuccessfulReadRequestLatency` and `SuccessfulWriteRequestLatency` CloudWatch metrics at p50/p99/p100 instead.

**Tier A summary (produce before proceeding):**

- Per-shard imbalance? (yes / no / single shard N/A)
- Which node is hot? (node-id or "aggregate only")
- Dominant data type? (from Step 2)
- Slow-log fingerprints? (top 3 keys, or N/A)
- Next action: Tier B, Tier C, or serverless diagnostic order

## Tier B: Slot-level diagnosis (Valkey 8.0+ cluster mode)

`CLUSTER SLOT-STATS` reports per-slot command counts and CPU usage. Not available in Redis OSS or earlier Valkey. No LFU requirement.

| Signal | Typical value |
|---|---|
| Runtime | Subsecond on any cluster size |
| Throughput impact | Negligible |
| Production safe | Yes, use `LIMIT 10` for bounded response |

### Step 1: Identify hot slots

```bash
valkey-cli -h <endpoint> -p 6379 --tls --cluster-yes \
  CLUSTER SLOT-STATS ORDERBY CPU-USEC LIMIT 10
```

**Stop condition:** If top 10 slots are within 2x of each other, no single hot slot. Reconsider whether the problem is command-family cost rather than a hot key.

### Step 2: Enumerate candidate keys in the hot slot

```bash
valkey-cli -h <endpoint> -p 6379 --tls \
  CLUSTER GETKEYSINSLOT <hot-slot-number> 200
```

Cross-reference with `MEMORY USAGE <key>` and command family from Tier A Step 2.

**Stop condition:** If Tier A already identified a specific key in slow log that hashes into this slot (verify via `CLUSTER KEYSLOT <key>`), skip enumeration.

### Step 3: Verify the key is hot

If LFU policy: proceed to Tier C on each candidate. If not LFU, use these alternatives in order:

1. **Client-side counters.** Instrument the application to log command and key for a 5-10 minute sampling window. Most effective non-LFU option.
2. **Slow-log analysis.** Run `aws logs filter-log-events`, group by key, rank by frequency.
3. **`MEMORY USAGE <key>` per candidate.** If one candidate is distinctly larger, that's a strong big+hot signal.

## Tier C: Per-key frequency (LFU policy required)

`OBJECT FREQ` reads the logarithmic frequency counter maintained under LFU policies. O(1) per call, safe to run at scale.

### Step 1: Confirm LFU policy

```bash
aws elasticache describe-cache-parameters \
  --cache-parameter-group-name <parameter-group-name> \
  --query "Parameters[?ParameterName=='maxmemory-policy'].ParameterValue" \
  --output text --region <region>
```

If not LFU, stop. The counter is meaningless under LRU.

### Step 2: Sample candidate keys

```bash
valkey-cli -h <endpoint> -p 6379 --tls OBJECT FREQ <key>
```

Interpreting the counter (logarithmic):

- 0-3: rarely accessed
- 4-8: moderate access
- 9-15: high access, candidate
- 15+: capped maximum, very hot

### Step 3: Confirm and assess

Rank candidates by `OBJECT FREQ`. Retrieve sizes via `MEMORY USAGE <key>` to determine whether the problem is request rate (fix with client-side caching or key splitting) or value size (fix with value decomposition).

## MONITOR: do not use on production

**Serverless:** `MONITOR` is blocked. This section applies to node-based only.

`MONITOR` streams every command to the connected client. Do not use on production:

- 50%+ throughput reduction per valkey.io documentation; impact increases with multiple MONITOR clients
- Can saturate the client's network pipe
- No rate limit, cannot scope to a subset of keys

**If genuinely the only option** (no LFU, Tier B unavailable, client instrumentation not feasible):

- Replica node only, never the primary
- Short bounded window: `valkey-cli MONITOR | head -n 100000`
- Off-peak or maintenance window only
- Explicit user acknowledgement of the performance risk

## Serverless-specific considerations

### Blocked commands on serverless

`OBJECT *`, `MEMORY *`, `LATENCY *`, `SLOWLOG *`, `COMMANDLOG` (Valkey 8.1+; not available on serverless), `CONFIG *`, `MONITOR`, `valkey-cli --hotkeys`, `valkey-cli --memkeys`. `valkey-cli --bigkeys` works (uses SCAN + type-length commands).

### Serverless diagnostic order

1. **CloudWatch triage:** command-family metrics to identify the hot data type, latency metrics at p50/p99/p100 to confirm impact, `ThrottledCmds` to spot bursts.
2. **Narrow with `--bigkeys`:** client-side sample scan to identify large values. Run during off-peak.
3. **Confirm with application instrumentation:** log top-N command-and-key pairs for a bounded window.
4. **Remediate** per the options below.

## Remediation options

Ordered by preference. Pick the first that fits; layer in later options if needed.

1. **Client-side caching for read-heavy hot keys.** Cache the value in-process with a short TTL. Reduces cache-side request rate by an order of magnitude.
2. **Key splitting.** Replicate across N logical keys (`hot:1` through `hot:N`), load-balance reads. Use when client-side caching is not feasible.
3. **Add read replicas.** Distribute read load if the application uses reader endpoints.
4. **Value decomposition.** Break large hashes/lists so each request touches less data. Indicated when slow log shows `HGETALL` or `LRANGE 0 -1`.
5. **Finer-grained sharding.** Introduce a finer key space (shard by user-id suffix, time bucket, tenant id).
6. **TTL tuning.** Longer TTL on cache-aside entries reduces miss-driven reloads.

## Cross-links

- Cluster-wide high CPU (not a hot key): `troubleshooting.md` High CPU section
- Hot shard causing replication lag: `troubleshooting.md` Replication Lag section
- Alarm patterns for per-node imbalance: `alarm-packs.md`
- Slow log configuration: `log-delivery.md`
