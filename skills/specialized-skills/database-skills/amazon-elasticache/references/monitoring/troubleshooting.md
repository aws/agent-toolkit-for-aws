# Troubleshooting Playbooks

Symptom-based runbooks for diagnosing and resolving common ElastiCache operational issues.

## Diagnostic Quick Reference

| Symptom | First Metric to Check | First Action | Deployment |
|---------|----------------------|--------------|------------|
| Slow responses | `EngineCPUUtilization` | Check slow log for expensive commands | Both |
| Low hit rate | `CacheHitRate`, `Evictions` | Verify TTLs and eviction policy | Both |
| Connection errors | `CurrConnections` | Check security groups and connection pooling | Both |
| High CPU | `EngineCPUUtilization` per node | Look for hot keys or expensive commands | Node-based |
| OOM / write failures | `DatabaseMemoryUsagePercentage` | Check eviction policy and key TTLs | Node-based |
| Stale reads | `ReplicationLag` | Check write volume and replica capacity | Node-based |
| Throttled (serverless) | `ThrottledCmds`, `ElastiCacheProcessingUnits` | Increase ECPU limit | Serverless |
| Connection drops | `describe-events` | Check for failover events, verify retry logic | Both |

---

## CLI Template for Metric Checks

All investigation steps below reference metrics by name. Use this template, substituting the metric name and dimensions.

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache --metric-name <metric-name> \
  --dimensions Name=<dimension-name>,Value=<dimension-value> \
  --start-time <start> --end-time <now> --period <seconds> --statistics <stat> \
  --region <region>
```

Common dimensions: `ReplicationGroupId` (cluster-wide), `CacheClusterId` (per node), `ServerlessCacheName` (serverless).

---

## Metric Units Quick Reference

| Metric | Deployment | Unit | Common Mistake |
|--------|------------|------|----------------|
| ReplicationLag | Node-based | Seconds | Not milliseconds. Threshold of 1 = 1 second. |
| SuccessfulReadRequestLatency | Both | Microseconds | Not milliseconds. 5000 = 5ms. |
| SuccessfulWriteRequestLatency | Both | Microseconds | Not milliseconds. 5000 = 5ms. |
| BytesUsedForCache | Both | Bytes | Not GB. 1 GB = 1,073,741,824 bytes. |
| ElastiCacheProcessingUnits | Serverless | Count (ECPUs) | Sum over period, not rate. |
| ThrottledCmds | Serverless | Count | Sum over period. |
| DatabaseMemoryUsagePercentage | Node-based | Percent | Not a ratio. 80 = 80%. |
| DatabaseCapacityUsagePercentage | Node-based | Percent | Available on all node-based clusters. On data-tiering instances (r6gd), the formula includes SSD storage; on all other instances, it is calculated as `used_memory/maxmemory`. |
| EngineCPUUtilization | Node-based | Percent | Single-threaded engine; can hit 100% on one core while host CPU is low. |
| CacheHitRate | Both | Percent | Empty until cache serves real traffic. |
| Slow log duration | Both | Microseconds | Not milliseconds. 10000 = 10ms. |

## Metrics Return Empty

New caches take 5-10 minutes to emit their first CloudWatch datapoints. Serverless caches with zero traffic emit no metrics at all (this is normal, not broken). After confirming the cache exists with `describe-serverless-caches` or `describe-replication-groups`, wait for traffic before investigating further.

---

## High Latency
**Applies to:** Both serverless and node-based. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | `SuccessfulReadRequestLatency` or `SuccessfulWriteRequestLatency` elevated |
| Key metrics | `EngineCPUUtilization`, `SuccessfulReadRequestLatency`, `SuccessfulWriteRequestLatency`, `CurrConnections` |

### Likely Causes

1. **Slow commands**: `KEYS *`, `SMEMBERS` on large sets, `HGETALL` on large hashes, `SORT` on large lists
2. **Network latency**: cross-AZ traffic, VPC peering hops, insufficient bandwidth
3. **TLS overhead**: handshake on every new connection (mitigated by connection reuse)
4. **Insufficient capacity**: node CPU/memory saturated, or serverless ECPU limit reached
5. **Hot key**: single key bottlenecking a single shard

### Investigation Steps
Check: `EngineCPUUtilization` (per node, Maximum), `CurrConnections` (Maximum). For slow log:

```bash
aws logs filter-log-events --log-group-name <your-slow-log-group> \
  --region <region>
```

**Stop condition:** If `EngineCPUUtilization` is below 60% and `CurrConnections` is stable, this is not a capacity or connection problem. Check slow log for expensive commands next.

### Resolution

- **Slow commands**: replace `KEYS` with `SCAN`, use `SSCAN`/`HSCAN`/`ZSCAN` for large data structures
- **Network**: colocate app and cache in same AZ, use reader endpoints for read-heavy workloads
- **TLS**: enable connection pooling and reuse connections
- **Insufficient capacity**: scale up node type, add shards, or increase serverless ECPU limits
- **Hot key**: distribute across multiple logical keys with client-side sharding, or add read replicas. For detailed diagnosis, see `hot-key-detection.md`. For intermittent spikes with slow-log correlation, see `slow-log-cross-signal-diagnosis.md`.

## Low Hit Rate
**Applies to:** Both serverless and node-based. **Severity:** P2 (fix next business day)

| Aspect | Detail |
|--------|--------|
| Symptoms | `CacheHitRate` below 80%, backing store load not decreasing |
| Key metrics | `CacheHits`, `CacheMisses`, `CacheHitRate`, `Evictions`, `DatabaseMemoryUsagePercentage` |

### Likely Causes

1. **TTL too short**: keys expire before reuse
2. **Wrong eviction policy**: keys evicted before natural expiry
3. **Cold cache**: recently created or restarted, not yet populated
4. **Key space mismatch**: different key naming between write and read paths
5. **Cache stampede**: concurrent requests miss simultaneously, overwhelming the backend

### Investigation Steps
Check: `Evictions` (Sum), `DatabaseMemoryUsagePercentage` (Maximum), `CacheHitRate` (Average). All at ReplicationGroupId level.

**Stop condition:** If `Evictions` is zero and `DatabaseMemoryUsagePercentage` is below 70%, eviction is not the cause. Focus on key naming and TTL mismatch.

### Resolution

- **TTL too short**: increase TTL. Start with 5-15 min for frequently changing data, 1-24 hours for reference data.
- **Wrong eviction policy** (node-based only): use `allkeys-lru` for general caching. Use `volatile-lru` only if some keys must never be evicted. **Note:** Serverless caches use `volatile-lru` and this is not configurable; ensure all keys have TTLs set to enable eviction on serverless.
- **Cold cache**: implement cache warming on deployment or restart.
- **Key space mismatch**: audit key naming in write and read paths. Ensure derivation is deterministic and identical.
- **Cache stampede**: implement locking (SETNX-based) so only one request populates on miss, or use "stale while revalidate" TTLs.

## Connection Spikes
**Applies to:** Both serverless and node-based. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | `CurrConnections` spikes, `NewConnections` elevated, connection errors in app logs |
| Key metrics | `CurrConnections`, `NewConnections`, `EngineCPUUtilization` |

### Likely Causes

1. **Connection storm**: app restart causing all instances to connect simultaneously
2. **Missing connection pooling**: each request opens a new connection
3. **Lambda cold starts**: each cold start establishes a new connection
4. **Connection leaks**: connections not returned to pool

### Investigation Steps
Check: `CurrConnections` (Maximum, period 60s), `NewConnections` (Sum, period 60s). Compare per-node to find imbalance.

### Resolution

- **Connection storm**: implement backoff with jitter on startup
- **Missing pooling**: use connection pools (`max_connections` in client library)
- **Lambda cold starts**: initialize connection outside handler. Consider provisioned concurrency or serverless cache.
- **Connection leaks**: add health checks, set idle timeout, implement cleanup in `finally` blocks

## High CPU
**Applies to:** Node-based only. For serverless, see Throttling. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | `EngineCPUUtilization` above 90%, increased latency |
| Key metrics | `EngineCPUUtilization`, `CPUUtilization`, `CurrConnections` |

### Important: CPUUtilization vs EngineCPUUtilization
`EngineCPUUtilization` measures only the main Redis/Valkey engine thread and is the recommended metric for monitoring engine capacity. `CPUUtilization` reflects aggregate CPU usage across all cores, including dedicated I/O threads from Enhanced I/O features, and is **not** a reliable indicator of engine capacity for nodes with 4+ vCPUs. For nodes with 2 or fewer vCPUs, use `CPUUtilization` with a threshold of 90 divided by the number of cores (e.g., 45% for 2-core nodes). For nodes with 4+ vCPUs, use `EngineCPUUtilization` with a 90% threshold.

### Likely Causes

1. **Hot key**: one key receiving disproportionate traffic on a single shard
2. **Expensive commands**: `KEYS`, `SORT`, `SUNIONSTORE` on large datasets, complex Lua scripts
3. **Insufficient shards**: workload concentrated on too few shards
4. **High connection churn**: TLS handshake overhead with many short-lived connections

### Investigation Steps
Check: `EngineCPUUtilization` (per node via CacheClusterId, Maximum, period 60s). Compare across nodes to find hot shards. For slow log:

```bash
aws logs filter-log-events --log-group-name <your-slow-log-group> \
  --region <region>
```

Also check command-family metrics (`StringBasedCmds`, `HashBasedCmds`, etc.) on the hot node to identify the data type driving load before scanning slow logs.

### Resolution

- **Hot key**: use client-side caching, replicate key with suffixes (`hotkey:1`, `hotkey:2`) and load-balance reads
- **Expensive commands**: replace `KEYS` with `SCAN`, use `SSCAN`/`HSCAN`/`ZSCAN`, limit Lua complexity
- **Insufficient shards**: add shards (`modify-replication-group-shard-configuration`), rebalance slots
- **Connection churn**: implement connection pooling, use keep-alive

## Memory Pressure
**Applies to:** Node-based primarily. Serverless auto-scales storage but can hit configured limits. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | `DatabaseMemoryUsagePercentage` above 80%, `Evictions` increasing, OOM errors |
| Key metrics | `DatabaseMemoryUsagePercentage`, `BytesUsedForCache`, `Evictions`, `CurrItems`. For data-tiering instances (r6gd), also check `DatabaseCapacityUsagePercentage` which covers both memory and SSD tiers. |

### Likely Causes

1. **No eviction policy**: `maxmemory-policy` set to `noeviction`, rejects writes when full
2. **Large keys**: individual keys in the MB range consuming disproportionate memory
3. **Memory fragmentation**: high `MemoryFragmentationRatio`
4. **TTL not set**: keys persist indefinitely

### Investigation Steps
Check: `DatabaseMemoryUsagePercentage` (Maximum, period 3600s over 7d), `Evictions` (Sum, period 3600s over 7d). To check eviction policy:

```bash
aws elasticache describe-cache-parameters \
  --cache-parameter-group-name <parameter-group> \
  --region <region> \
  --query "Parameters[?ParameterName=='maxmemory-policy']"
```

**Stop condition:** If `Evictions` is zero and memory is rising slowly, this may be normal growth. Only act if approaching 80% or evictions are sustained.

### Resolution

- **No eviction policy**: set `maxmemory-policy` to `allkeys-lru`
- **Large keys**: break into smaller keys, compress values, use hashes instead of large JSON blobs. For detailed big-key diagnosis, see `big-key-hunter.md`.
- **Memory fragmentation**: restart during maintenance window. For node-based, set `activedefrag` to `yes` in the parameter group (CONFIG SET is restricted on ElastiCache).
- **TTL not set**: audit key creation code, add TTLs. Use `OBJECT IDLETIME` to find stale keys.
- **Reserved memory**: set `reserved-memory-percent` to 25 (for Valkey and Redis OSS 2.8.22+) or 50 (for older Redis OSS versions) via a custom parameter group. The default is 25% for all parameter group families (available since March 2017). For accounts created before March 16, 2017, older parameter families may default to 0. A value of 0 allows the engine to consume all of `maxmemory` with data, leaving insufficient memory for background write processes (BGSAVE, replication sync), which can cause snapshot and sync failures.
- **Scale up**: larger node type or add shards to distribute data

## Replication Lag
**Applies to:** Node-based only. Serverless handles replication internally. **Severity:** P2 (fix next business day, P1 if > 5s)

| Aspect | Detail |
|--------|--------|
| Symptoms | `ReplicationLag` above 1s, stale reads from replicas, failover risk |
| Key metrics | `ReplicationLag`, `ReplicationBytes`, `NetworkBytesOut` (primary), `SaveInProgress` |

### Likely Causes

1. **Write-heavy workload**: primary generating data faster than replicas can consume
2. **Insufficient replica capacity**: replica node type too small
3. **Network bandwidth**: replication traffic saturating the interface
4. **Background save**: `BGSAVE`/snapshot operations competing for I/O

### Investigation Steps
Check: `ReplicationLag` (per replica via CacheClusterId, Maximum, period 60s), `SaveInProgress` (per primary, Maximum, period 60s).

**Stop condition:** If `SaveInProgress` is 1 and lag correlates with snapshot timing, this is snapshot-induced. Schedule snapshots during off-peak rather than scaling.

### Resolution

- **Write-heavy workload**: add shards to distribute writes, or batch writes using pipelining
- **Insufficient replica capacity**: scale up replica node type (must match primary in most configs)
- **Network bandwidth**: move to a larger node type
- **Background save**: schedule snapshots during low-traffic periods

## Throttling (Serverless)
**Applies to:** Serverless only. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | `ThrottledCmds` increasing, throttle errors in clients, `ElastiCacheProcessingUnits` near max |
| Key metrics | `ThrottledCmds`, `ElastiCacheProcessingUnits` |

### Likely Causes

1. **ECPU limit reached**: `CacheUsageLimits.ECPUPerSecond.Maximum` too low for current workload
2. **Burst traffic**: sudden spike exceeding configured maximum
3. **Expensive commands**: single commands consuming many ECPUs (e.g., `SORT`, `ZRANGEBYSCORE` returning thousands)

### Investigation Steps
Check: `ElastiCacheProcessingUnits` (Sum, period 60s), `ThrottledCmds` (Sum, period 60s). Use ServerlessCacheName dimension.

### Resolution

- **Increase ECPU limit**:

  ```bash
  aws elasticache modify-serverless-cache \
    --serverless-cache-name <name> \
    --cache-usage-limits '{"ECPUPerSecond": {"Maximum": <higher-value>}}' \
    --region <region>
  ```

- **Optimize commands**: replace expensive operations with efficient alternatives, use pipelining
- **Cost concern**: consider node-based for steady-state high-throughput with reserved pricing
- **Add client-side retry**: exponential backoff for throttled commands

## Failover Events
**Applies to:** Node-based primarily. Serverless handles failover transparently. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | Brief connection interruption, DNS endpoint change |
| Key metrics | `ReplicationLag` (pre-failover), events from `describe-events` |

### Likely Causes

1. **Node failure**: hardware or software issue on the primary
2. **AZ failure**: entire Availability Zone unavailable
3. **Maintenance**: service update applied during maintenance window
4. **Manual failover**: operator-initiated via `test-failover`

### Investigation Steps
Check recent events:

```bash
aws elasticache describe-events \
  --source-type replication-group \
  --source-identifier <replication-group-id> \
  --duration 1440 \
  --region <region>
```

Also check `ReplicationLag` (Maximum) before the event; high lag means potential data loss.

### Resolution

- **Ensure Multi-AZ is enabled**: automatic failover; failover time varies depending on cluster size and configuration
- **Application resilience**: retry with backoff. Most client libraries handle failover with cluster-aware config.
- **DNS caching**: set app DNS TTL to 5 seconds or less
- **Post-failover**: verify replication is healthy, confirm new primary is in expected AZ
- **Prevent data loss**: keep `ReplicationLag` low. High lag before failover means unreplicated writes are lost.

## Cannot Connect
**Applies to:** Both serverless and node-based. **Severity:** P1 (fix now)

| Aspect | Detail |
|--------|--------|
| Symptoms | Connection timeout, connection refused, TLS handshake failure |
| Key metrics | `CurrConnections` (if any succeed), `describe-events` for failover |

### Decision Fork

- **Never worked (new setup):** Security group, subnet, or endpoint misconfiguration. Check the setup sub-skill's connectivity-diagnostics.
- **Was working, now broken:** Recent change or failover event.

### Likely Causes (was working, now broken)

1. **Security group change**: inbound rule removed or modified
2. **Failover event**: DNS endpoint changed, client caching old IP
3. **Auth credential rotation**: password or IAM token expired
4. **TLS certificate mismatch**: client missing CA bundle or wrong ssl_cert_reqs setting
5. **Network change**: VPC peering route removed, subnet NACL modified
6. **maxclients reached**: some connections succeed but new ones are rejected. Check `CurrConnections` against node's `maxclients` (default 65,000 for most instance types; exceptions: t2.micro/small/medium and t3.micro = 20,000; t3.small/medium = 46,000; t4g.micro = 20,000)

### Investigation Steps
Check `describe-events` for recent failover. Verify security group allows inbound on port 6379 from the client's security group. Test with:

```bash
valkey-cli -h <endpoint> -p 6379 --tls PING
```

If TLS fails, try without TLS to isolate (note: serverless always requires TLS).
### Resolution

- **Security group**: add inbound rule for port 6379 from client SG
- **Failover DNS**: set client DNS TTL to 5s or less; restart application to pick up new IP
- **Auth expired**: rotate credentials in Secrets Manager or refresh IAM token
- **TLS**: ensure client uses `ssl=True` and the correct CA bundle (Amazon root CA)
- **Never worked**: route to `setup/connectivity-diagnostics.md`
