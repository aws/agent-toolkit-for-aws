# Serverless vs Node-Based

## Hard Routing Rules (non-negotiable)

These constraints override all other guidance. Never recommend serverless for these workloads.

1. **Vector search MUST use node-based Valkey 8.2 or above (recommend 9.0).** Serverless does not support vector search. Any workload requiring vector similarity (semantic cache, RAG, conversational memory with vector retrieval, recommendations via embeddings, semantic search) MUST be deployed on a node-based Valkey 8.2 or above cluster (recommend 9.0). Do NOT suggest serverless as a fallback or future option for vector search.

2. **Global Datastore MUST use node-based clusters.** Multi-Region replication via Global Datastore is not available on serverless. Any workload requiring cross-Region reads or disaster recovery via Global Datastore MUST use a node-based deployment.

> ElastiCache Serverless supports Valkey 7.2+, Redis OSS 7.1+, and Memcached 1.6.22+. Regional availability may vary; check the [ElastiCache pricing page](https://aws.amazon.com/elasticache/pricing/) or the AWS Region Table before selecting a deployment model.

## Quick Decision

**Default to serverless** unless one of the hard routing rules or node-based requirements below applies.

| Factor | Serverless | Node-Based |
|--------|-----------|---------------------------|
| Setup time | 1-5 minutes | 5-15 minutes |
| Capacity planning | Automatic | Manual (choose node type, count) |
| Scaling | Instant, automatic | Manual or auto-scaling policies |
| Maintenance windows | None (zero downtime) | Required for patching |
| Pricing model | Pay per GB stored + ECPUs consumed | Pay per node-hour (reserved or on-demand) |
| Minimum cost | ~$6/month (Valkey) | Depends on node type |
| In-transit encryption (TLS) | Always on (cannot disable) | Optional (recommended) |
| Authentication | RBAC/IAM only (no AUTH tokens) | RBAC/IAM and AUTH tokens (legacy) |
| Best for | Variable/unpredictable traffic, new projects, getting started | Predictable high-throughput, cost optimization at scale |

## When serverless wins

- New projects or prototypes
- Variable or spiky traffic patterns
- Teams that don't want to manage infrastructure
- When time-to-value matters (under 1 minute to create)
- Workloads under ~100 GB or with unpredictable growth

## When node-based is required or preferred

- **Vector search** -- requires Valkey 8.2 or above on node-based clusters (recommend 9.0). Available in all AWS Regions at no additional cost. Not supported on data-tiering instances (r6gd) or serverless.
- **Data Tiering** -- the r6gd instance family (SSD-backed data tiering) is only available on node-based clusters.
- **Global Datastore** -- multi-Region replication requires node-based clusters. Global Datastore has specific engine version requirements and is available only in regions that support multi-Region replication. Check the [ElastiCache documentation](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/GlobalDatastore.html) for supported regions and engine versions.
- **Reserved instances** -- reserved nodes save approximately 30-55% depending on term length and payment option (run `python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` for current estimates)
- **Fine-grained parameter tuning** -- custom parameter groups for advanced optimization
- Predictable, steady-state high throughput with strict sub-millisecond latency at 50k+ connections
- Large datasets where reserved instances save significant cost
- Compliance requirements needing specific instance families

## Serverless Constraints and Limits

These constraints are inherent to the serverless deployment model and cannot be changed. Verify each one against the workload requirements before choosing serverless.

### Encryption and TLS

- **TLS is always on.** In-transit encryption cannot be disabled on serverless caches. All clients must connect with TLS enabled (`ssl=True` in valkey-py, `tls: {}` in ioredis, `--tls` in valkey-cli). If the application cannot use TLS, use node-based instead.
- **At-rest encryption is always on.** Cannot be disabled.

### Authentication

- **RBAC or IAM only.** AUTH token (password-only) authentication is not supported on serverless. Applications using legacy AUTH tokens must switch to RBAC users or IAM-based authentication before migrating to serverless.

### Connections

- **65,000 max concurrent connections.** Beyond this threshold, additional connections may or may not succeed depending on current load. If the workload consistently approaches this limit, use node-based with multiple nodes, or implement connection pooling.
- Connection pooling is strongly recommended regardless of deployment model.

### Storage and Throughput Limits

- **Maximum storage: 5,000 GiB.** Configurable via `CacheUsageLimits.DataStorage.Maximum`. Maximum per-slot storage is 32 GiB.
- **Maximum ECPU/s: 15,000,000 ECPU/s.** This is the hard platform maximum. `CacheUsageLimits.ECPUPerSecond.Maximum` lets you set a lower ceiling for cost control, but cannot exceed 15,000,000. Per-slot throughput ranges from 30,000 to 90,000 ECPU/s.
- For workloads requiring storage beyond 5 TB or predictable high throughput, evaluate node-based for cost efficiency.

### Feature Restrictions

- **No vector search.** Vector search requires Valkey 8.2 or above on node-based clusters (recommend 9.0).
- **No Global Datastore.** Multi-region replication requires node-based clusters.
- **Cluster-mode-enabled only.** All serverless caches operate in cluster mode. Clients must support cluster protocol (MOVED/ASK redirects). Non-cluster clients will fail to connect properly.
- **No keyspace notifications.** Keyspace events are not supported on serverless caches. Workloads relying on keyspace notifications must use node-based.
- **Eviction policy is volatile-lru (not configurable).** Only keys with a TTL set are candidates for eviction. Keys without TTL are never evicted. If storage reaches the maximum and no keys can be evicted, writes receive OOM errors. Always set a TTL on serverless.
- **No custom parameter groups.** Parameter tuning is not available on serverless.
- **Manual snapshots supported.** Use `CreateServerlessCacheSnapshot` for on-demand snapshots. Restore via `create-serverless-cache --snapshot-arns-to-restore`. Automatic daily snapshots are not enabled by default; set `SnapshotRetentionLimit` > 0 to enable them.
- **SELECT command not supported.** Multiple logical databases (SELECT 0, SELECT 1, etc.) are not available. All data lives in a single logical namespace. Use key prefixes for logical separation.
- **Lua scripting restrictions.** Scripts that access keys across multiple slots may fail. Keep scripts single-key or use hash tags to colocate keys.

### Operations

- **No maintenance windows.** Patching is applied transparently with zero downtime. No operator action required.
- **Provisioning time: 1-5 minutes.** While the console may say "under a minute," actual creation takes 1-5 minutes in practice.

### Networking

- **Port 6379 and 6380 on the same hostname.** Serverless uses port 6379 for writes and port 6380 for reads, both on the same endpoint hostname. Security groups must allow inbound TCP on both ports. Many clients connect to both ports automatically. Since TLS is mandatory, ensure no intermediate proxies strip TLS.
- **VPC required.** Serverless caches are always deployed inside a VPC.

### Latency

- **Single-digit millisecond latency.** Serverless does not guarantee sub-millisecond latency. For workloads requiring consistent sub-millisecond response times at high concurrency (50,000+ connections), use node-based.

## Serverless Performance Tuning

### ECPU consumption model

Serverless bills in ElastiCache Processing Units (ECPUs). How commands are charged:

- **Fixed commands** (GET, SET, HGET, INCR, EXISTS, PING, DEL, UNLINK, and other O(1) operations): each request consumes at least 1 ECPU, with 1 ECPU per KB of data transferred. A GET returning 3.2 KB of data consumes 3.2 ECPUs (see [ElastiCache pricing](https://aws.amazon.com/elasticache/pricing/)).
- **Non-fixed commands** (EVAL, SORT, MGET, HGETALL, and other variable-cost operations): consume ECPUs based on the higher of vCPU time or data transferred. For example, an HMGET that takes 3x the vCPU time of a GET and transfers 3.2 KB consumes 3.2 ECPUs (data wins). If it transfers only 2 KB, it consumes 3 ECPUs (vCPU wins). See the [ElastiCache Serverless pricing blog](https://aws.amazon.com/blogs/database/unlock-on-demand-cost-optimized-performance-with-amazon-elasticache-serverless/).
- **Pipelined commands** are charged individually (each command in the pipeline costs its own ECPUs), but pipelining still reduces round-trip latency and network overhead.
- **Non-key commands** (ACL, SELECT, ECHO, TIME, etc.): these consume ECPUs as fixed commands. INFO and PUBLISH are exceptions — they are not metered.
- **Pub/sub commands** (SUBSCRIBE, PUBLISH, etc.): SUBSCRIBE and UNSUBSCRIBE are not metered. SPUBLISH, SSUBSCRIBE, and SUNSUBSCRIBE are metered.
- **Metadata commands** (AUTH, MULTI, EXEC, CONFIG): these are not metered.
- **Replication/cluster commands** (REPLCONF, PSYNC, CLUSTER): these are internal to the serverless infrastructure and are not metered.

Use `scripts/command_classifier.py` with `INFO commandstats` output for ECPU estimation of an existing workload. Note: the classifier uses heuristic approximations; actual ECPU consumption may differ. For precise billing, use CloudWatch ECPU metrics on a running serverless cache.

### Key CloudWatch metrics for serverless

| Metric | What it tells you |
|--------|-------------------|
| `ElastiCacheProcessingUnits` (Sum) | Total ECPUs consumed per period. Primary cost driver. |
| `ThrottledCmds` (Sum) | Commands rejected due to ECPU limit. Any value > 0 needs action. |
| `SuccessfulReadRequestLatency` (p99) | Read latency. Baseline is single-digit ms; spikes suggest hot keys or large payloads. |
| `SuccessfulWriteRequestLatency` (p99) | Write latency. Same baseline expectations as reads. |
| `BytesUsedForCache` | Storage consumed. Drives the storage component of the bill. |
| `CurrConnections` | Active connections against the 65K limit. |

### When to increase ECPU limits

If `ThrottledCmds > 0` sustained across multiple minutes, raise the ceiling:

```bash
aws elasticache modify-serverless-cache \
  --serverless-cache-name <name> \
  --cache-usage-limits '{"ECPUPerSecond": {"Maximum": <higher-value>}}' \
  --region <region>
```

Before increasing, check whether expensive commands (SORT, large LRANGE, unoptimized Lua scripts) are inflating ECPU consumption. Optimizing command patterns is cheaper than raising limits.

### Client-side optimization

- Keep payloads small. Every KB transferred adds ECPUs. Compress values over 1 KB (gzip or lz4) when the workload is read-heavy.
- Use pipelining to batch commands and reduce round trips. Each command still costs ECPUs, but latency drops significantly.
- Prefer MGET/MSET over loops of GET/SET for bulk operations.
- Use hash tags `{tag}` to colocate related keys on the same slot when using multi-key commands.

## Serverless Connection Management

Proper connection pooling is critical given the 65K per-cache connection limit (documented above). For per-library pool configuration and code examples, see `../monitoring/client-tuning-and-diagnostics.md` (Connection Pooling section).

Key serverless-specific guidance:

- Monitor `CurrConnections` in CloudWatch. Alert at 50K to leave headroom for spikes.
- Lambda and short-lived compute: reuse connections across invocations (module-level client). Each new TLS handshake adds ~5 ms latency and a connection slot.

## Serverless Backup Behavior

- **Automatic daily snapshots**: serverless caches can take one automated snapshot per day, but this must be explicitly enabled by setting `SnapshotRetentionLimit` > 0. The default is 0 (disabled).
- **On-demand snapshots**: use `CreateServerlessCacheSnapshot` for on-demand logical snapshots of serverless caches.
- **Retention**: `SnapshotRetentionLimit` controls how many days automatic snapshots are kept (0 disables, max 35 days). Set via `--snapshot-retention-limit` on `create-serverless-cache` or `modify-serverless-cache`.
- **Cross-region snapshot copy**: not available natively for serverless. As a workaround, use the `export-serverless-cache-snapshot` API to export a snapshot to S3, then copy the S3 object to the target region. For long-term retention beyond 35 days, consider node-based clusters which support `copy-snapshot --target-bucket` for S3 export.

## Cost comparison tip
For workloads over ~50 GB with steady traffic, run `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options` to compare. Reserved node-based instances can be cheaper at scale, but serverless eliminates operational overhead.
