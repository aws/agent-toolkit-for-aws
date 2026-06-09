# Slot Memory Imbalance Detection

**When to use:** Uneven memory across cluster nodes (one node near DatabaseMemoryUsagePercentage ceiling while siblings are well below), suspected hash-tag bundling, or planning resharding and want to identify which slots carry the most memory. Valkey 8.0+ cluster mode enabled only.
**When not needed:** Cluster-wide uniform memory pressure (troubleshooting.md Memory Pressure). Per-node CPU imbalance without memory skew (hot-key-detection.md). Serverless (abstracts slot topology).

## Preconditions

| Deployment | Applicability |
|---|---|
| Serverless | Does not apply. Slot topology is abstracted. |
| Node-based, cluster mode disabled | Does not apply (single-shard). Use big-key-hunter.md + key-space-distribution-by-prefix.md. |
| Node-based, cluster mode enabled | Full playbook. |

### Engine version gate

CLUSTER SLOT-STATS with MEMORY-BYTES requires **Valkey 8.0+** (this is a Valkey-only feature and is not available on any Redis OSS engine version). Verify:

```bash
valkey-cli -h <endpoint> -p 6379 --tls INFO server | grep -E 'redis_version|valkey_version'
```

**Pre-Valkey 8.0 degraded workflow:** 1) Per-shard CloudWatch triage (Tier A). 2) `valkey-cli --bigkeys` against the hot shard's primary. 3) `CLUSTER KEYSLOT <key>` per big-key candidate to find the heavy slot. 4) `MEMORY USAGE <key>` on top candidates for byte confirmation. Takes 15-30 minutes on a 10M-key shard vs. subsecond with SLOT-STATS.

### Feature flag

`cluster-slot-stats-enabled` must be `yes` in the parameter group. This is a Valkey 8.0+ parameter; verify it is available in your cache parameter group before relying on it. Note: This parameter may not appear in ElastiCache parameter groups documentation. It may be enabled by default or not exposed as a configurable parameter. `CONFIG GET` is restricted on all ElastiCache caches; check via the AWS API:

```bash
aws elasticache describe-cache-parameters \
  --cache-parameter-group-name <parameter-group-name> \
  --query "Parameters[?ParameterName=='cluster-slot-stats-enabled'].ParameterValue" \
  --output text --region <region>
```

If missing or `no`, enable via parameter group modification (zero-downtime on most configs).

### Command availability

| Command | Supported | Notes |
|---|---|---|
| CLUSTER SLOT-STATS ORDERBY MEMORY-BYTES | Valkey 8.0+ cluster mode, NB only. Requires `cluster-slot-stats-enabled` parameter set to `yes`. Availability on ElastiCache depends on engine version and parameter group support. | Primary Tier B tool |
| CLUSTER SHARDS | NB (Valkey 7.2+ / Redis OSS 7.0+), SL (virtual shard) | Topology discovery |
| CLUSTER COUNTKEYSINSLOT \<slot\> | NB all versions | Per-slot key count |
| CLUSTER GETKEYSINSLOT \<slot\> \<count\> | NB all versions | Enumerate keys in a slot |
| CLUSTER KEYSLOT \<key\> | NB all versions | Hash key to slot number |
| MEMORY USAGE \<key\> | NB only, blocked on SL | Tier C byte confirmation |

---

## Tier A: Triage with CloudWatch

### Step 1: Per-node memory utilization

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name DatabaseMemoryUsagePercentage \
  --dimensions Name=CacheClusterId,Value=<node-id> Name=CacheNodeId,Value=0001 \
  --start-time <24h-ago> --end-time <now> \
  --period 300 --statistics Maximum --region <region>
```

Run for each primary (discover with `CLUSTER SHARDS`).

**Stop condition:** If all primaries are within 10 percentage points, memory is distributed uniformly. No slot-imbalance problem. Route to troubleshooting.md Memory Pressure if overall memory is high.

Proceed if spread is >15 percentage points (e.g., one node at 85%, another at 45%).

### Step 2: Confirm persistence

Query `BytesUsedForCache` per node over 24h (node-based, using `CacheClusterId` and `CacheNodeId` dimensions). For serverless, use `BytesUsedForCache` with the `ServerlessCacheName` dimension. A stable gap over hours is real. A 10-minute transient is not.

---

## Tier B: Narrow with CLUSTER SLOT-STATS

### Step 1: Identify memory-heavy slots

```bash
valkey-cli -h <endpoint> -p 6379 --tls \
  CLUSTER SLOT-STATS ORDERBY MEMORY-BYTES DESC LIMIT 20
```

A single dominant slot (order of magnitude above peers) is a memory hotspot.

### Cost and impact

Subsecond, negligible impact. Reads stats Valkey already maintains. Safe at any time on production.

### Step 2: Map hot slots to shards

Use `CLUSTER SHARDS` output to map each hot slot to its primary. Hot slot on the already-hot node confirms the story.

### Step 3: Correlate with key count

```bash
valkey-cli -h <endpoint> -p 6379 --tls CLUSTER COUNTKEYSINSLOT <hot-slot>
```

| Pattern | Cause | Next step |
|---|---|---|
| Few keys, large memory | Big-key(s) in this slot | big-key-hunter.md |
| Many keys, large memory | Hash-tag concentration | Continue to Tier C |

**Stop condition:** If top 20 slots are within 2x of each other, no single hot slot. Consider rebalancing slot assignments rather than application-level remediation.

---

## Tier C: Verify with key-level inspection

### Step 1: Sample keys from the hot slot

```bash
valkey-cli -h <endpoint> -p 6379 --tls \
  CLUSTER GETKEYSINSLOT <hot-slot> 200
```

### Step 2: Identify hash-tag pattern

Look for common `{...}` hash-tag prefix in returned keys. If most keys are `{tenant_42}:session:*`, `{tenant_42}:cache:*`, tenant 42 has concentrated its keys into a single slot.

### Step 3: Measure top keys

```bash
valkey-cli -h <endpoint> -p 6379 --tls MEMORY USAGE <key>
```

If one key dominates bytes, this is a big-key problem (route to big-key-hunter.md). If memory is evenly distributed, hash-tag concentration is the cause.

---

## Remediation

Pick based on Tier C classification:

| Cause | Remediation |
|---|---|
| **Hash-tag concentration** (default) | Redesign hash-tag: `{tenant_id}:{shard_id}` where shard_id is a random 4-bit prefix. Spreads keys across 16 slots while keeping intra-tenant MULTI/LUA local. Application change required. |
| **Oversized tenant** | Split to dedicated cache. For tenants using >30% of cluster memory. |
| **Big key in hot slot** | big-key-hunter.md remediation (decomposition, compression, move to S3). |
| **Slot-count skew** | Manual slot rebalance via online resharding (`modify-replication-group-shard-configuration`). |
| **Orphan keys** | Bulk UNLINK after confirming via key-space-distribution-by-prefix.md TTL audit. |
| **Scale up** (last resort) | Larger node type. Only masks the symptom. |

---

## Cross-links

- Hot slot also has high CPU: `hot-key-detection.md` Tier B (same SLOT-STATS, ORDERBY CPU-USEC axis)
- Specific key in slot is oversized: `big-key-hunter.md`
- Concentration is prefix-based, not slot-based: `key-space-distribution-by-prefix.md`
- Alarm patterns for memory imbalance: `alarm-packs.md`
