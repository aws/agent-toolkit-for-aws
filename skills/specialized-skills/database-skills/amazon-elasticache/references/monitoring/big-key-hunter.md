# Big-Key Hunter

**When to use:** Memory growing faster than key count, latency spikes on O(N) commands (HGETALL, LRANGE, SMEMBERS), network bandwidth saturation on one node, or client timeouts on reads of known keys.
**When not needed:** Memory pressure with many small keys (troubleshooting.md Memory Pressure). High request rate on normal-sized keys (hot-key-detection.md).

## Preconditions

| Deployment | Available Tiers |
|---|---|
| Serverless | Tier A + Tier B only. `MEMORY USAGE` blocked; estimate from cardinality x element size. |
| Node-based | All tiers. Tier C gives exact bytes via `MEMORY USAGE`. |

### Command availability

| Command | Node-based | Serverless | Purpose |
|---|---|---|---|
| STRLEN, HLEN, LLEN, ZCARD, SCARD, PFCOUNT, XLEN | Yes | Yes | Per-type cardinality |
| `valkey-cli --bigkeys` | Yes | Yes | Client-side SCAN + per-type length sampling |
| `valkey-cli --memkeys` | Yes | Fails | Depends on MEMORY USAGE |
| MEMORY USAGE \<key\> | Yes | Blocked | Exact bytes including overhead |
| DEBUG OBJECT | Blocked | Blocked | Restricted everywhere. Never recommend. |
| XINFO STREAM | Yes | Yes | Stream length + groups + entries |

### "Big" thresholds

| Type | Threshold |
|---|---|
| String | >= 100 KB |
| Hash | >= 1,000 fields |
| List | >= 10,000 items |
| Set | >= 1,000 members |
| Sorted set | >= 1,000 members |
| Stream | >= 100,000 entries |

Tune up for workloads that legitimately use large collections (event sourcing, leaderboards). Tune down if latency is sensitive.

---

## Tier A: Triage with CloudWatch

### Step 1: Memory-to-key-count ratio

Big-key: memory grows faster than key count. Volume: both grow together.

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache --metric-name BytesUsedForCache \
  --dimensions Name=<dim>,Value=<id> \
  --start-time <24h-ago> --end-time <now> \
  --period 3600 --statistics Maximum --region <region>
```

Query both `BytesUsedForCache` and `CurrItems`. Compute bytes-per-key trend.

**Stop condition:** If bytes-per-key is flat and below 10KB, this is not a big-key problem. Route to troubleshooting.md Memory Pressure.

### Step 2: Network bandwidth correlation (node-based)

Big keys on read-heavy workloads show as `NetworkBytesOut` spikes on one node while peers are flat, correlated with elevated `EngineCPUUtilization`. Use `CacheClusterId` dimension (not `ReplicationGroupId` which hides imbalance).

### Step 3: Slow-log fingerprint (node-based only)

```bash
aws logs filter-log-events \
  --log-group-name <your-slow-log-group-name> \
  --filter-pattern "HGETALL SMEMBERS LRANGE SUNIONSTORE SORT" \
  --start-time <1h-ago-ms> --region <region>
```

The log group name is user-specified when configuring log delivery (retrieve via `describe-replication-groups` → `LogDeliveryConfigurations`).

First argument of each entry is the key. Keys appearing repeatedly with O(N) commands are big-key candidates. Serverless: skip (slow-log not delivered).

---

## Tier B: Narrow with client-side sampling

`valkey-cli --bigkeys` is a client-side sampler (SCAN loop + TYPE + per-type length), not a server command. No native server-side big-key detection exists in Valkey (valkey-rfc #34 proposes TOPKEYS).

### Cost and impact

| Signal | Typical value |
|---|---|
| Runtime on 1M keys | 1-3 minutes |
| Runtime on 10M keys | 15-30 minutes |
| Throughput impact | 0.5% to 2% |
| EngineCPU impact | Minimal (reads only) |

Run against a replica on node-based. Run off-peak on serverless (every sampled key consumes ECPUs). Stop if EngineCPU rises >10 percentage points.

### Step 1: Run the sampler

```bash
valkey-cli -h <endpoint> -p 6379 --tls --bigkeys
```

### Step 2: Interpret

`--bigkeys` reports logical size (bytes for strings, element count for aggregates), not memory footprint. A hash with 50000 small fields may use less memory than a 2MB string.

### Step 3: Cross-reference with Tier A

If the big-key matches a slow-log fingerprint or is on the shard with elevated NetworkBytesOut, it is the root cause.

**Stop condition:** If top key per type is below the thresholds table, no remediation needed.

### Alternative: offline RDB analysis (node-based with backups)

For very large keyspaces where online sampling is too slow:

```bash
aws elasticache copy-snapshot \
  --source-snapshot-name <snapshot> \
  --target-snapshot-name <target> \
  --target-bucket <s3-bucket> --region <region>
```

Download and analyze with RDB tools offline. Not available on serverless.

---

## Tier C: Verify with MEMORY USAGE (node-based only)

### Step 1: Measure candidates

```bash
valkey-cli -h <endpoint> -p 6379 --tls MEMORY USAGE <key>
```

Default sampling (5 nested elements) is fast and good enough for ranking. Use `SAMPLES 0` only for the final top-1 or top-2 candidates (O(N) in value size).

### Step 2: Rank and confirm

Note the hash slot via `CLUSTER KEYSLOT <key>` if cluster mode. A big-key on a hot slot (cross-reference hot-key-detection.md Tier B) is the worst case.

---

## Stream big-key detection

Streams need a different approach. Length alone undersells the problem; a stuck consumer group with growing PEL is pathological.

```bash
valkey-cli -h <endpoint> -p 6379 --tls XLEN <stream-key>
valkey-cli -h <endpoint> -p 6379 --tls XINFO STREAM <stream-key>
valkey-cli -h <endpoint> -p 6379 --tls XINFO GROUPS <stream-key>
```

If first-entry timestamp is hours old, consumers are not keeping up. Enforce XTRIM MAXLEN.

---

## Remediation options

**Critical constraint (cluster mode):** ElastiCache does not migrate slots containing items with serialized size larger than 256 MB during slot migration. You must decompose keys exceeding 256 MB before any resharding or scale-out operation.

In order of preference:

1. **Value decomposition** (default): break large value into smaller keys. Large hash becomes `key:part1`, `key:part2`. Long list gets LTRIM or converts to stream.
2. **Stream trimming** (streams only): `XTRIM <key> MAXLEN ~ <n>` with approximate flag. Enforce via scheduled task.
3. **Compression**: gzip/zstd at application layer before writing. Reduces network and memory at cost of CPU.
4. **Avoid O(N) reads**: replace HGETALL with HMGET for specific fields, LRANGE 0 -1 with paginated LRANGE, SMEMBERS with SSCAN. Does not reduce memory but eliminates latency spikes.
5. **TTL tuning**: shorter TTL prevents unbounded growth for aggregated data.
6. **Move to different store**: genuinely large blobs (video metadata, ML features) belong in S3 with a pointer in the cache.

---

## Cross-links

- Big-key also hot (high access frequency): `hot-key-detection.md`
- Memory pressure cluster-wide, not key-specific: `troubleshooting.md` Memory Pressure
- Big-keys causing replication lag: `troubleshooting.md` Replication Lag
- Per-shard memory imbalance from big-key bundling: `slot-memory-imbalance-detection.md`
- Alarm patterns: `alarm-packs.md`
