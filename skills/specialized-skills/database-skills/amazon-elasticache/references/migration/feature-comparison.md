# Migration Feature Comparison Matrix

Side-by-side comparison of features, capabilities, and constraints across migration paths. Use this reference to identify what is gained, lost, or changed when moving between engines and deployment models.

## Engine Comparison: Valkey vs Redis OSS vs Memcached

| Feature | Valkey (7.2+) | Redis OSS (7.x) | Memcached |
|---------|:------------:|:---------------:|:---------:|
| **Data Structures** | | | |
| Strings | Yes | Yes | Yes |
| Hashes | Yes | Yes | No |
| Lists | Yes | Yes | No |
| Sets | Yes | Yes | No |
| Sorted Sets | Yes | Yes | No |
| Streams | Yes | Yes | No |
| HyperLogLog | Yes | Yes | No |
| Bitmaps | Yes | Yes | No |
| Geospatial | Yes | Yes | No |
| JSON (native) | Yes | Yes | No |
| Vector Search | Yes (8.2+, node-based only) | No | No |
| **Persistence and Replication** | | | |
| Snapshots (RDB) | Yes | Yes | Serverless only (automatic backups) (verify against latest Memcached serverless documentation for current backup behavior) |
| AOF persistence | Deprecated (legacy only) | Deprecated (legacy only) | No |
| Replication | Yes | Yes | No |
| Multi-AZ failover | Yes | Yes | No |
| Global Datastore | Yes (node-based only) | Yes (node-based only) | No |
| **Cluster and Scaling** | | | |
| Cluster mode (sharding) | Yes | Yes | No (data partitioning via client-side auto-discovery) |
| Max shards (cluster mode) | 500 (default 90 nodes; increasable to 500 for v5.0.6+; 250 for earlier versions) | 500 (default 90 nodes; increasable to 500 for v5.0.6+; 250 for earlier versions) | N/A (up to 60 nodes per cluster) |
| Online resharding | Yes | Yes | No |
| Serverless deployment | Yes | Yes | Yes |
| **Authentication and Security** | | | |
| RBAC (per-user ACLs) | Yes | Yes | No |
| IAM authentication | Yes (7.2+) | Yes (7.0+) | No |
| AUTH token (legacy) | Yes (node-based only) | Yes (node-based only) | No |
| In-transit encryption (TLS) | Yes | Yes | Yes |
| At-rest encryption | Yes | Yes | Yes |
| **Pub/Sub and Messaging** | | | |
| Pub/Sub | Yes | Yes | No |
| Keyspace notifications | Yes | Yes | No |
| **Operational** | | | |
| Lua scripting | Yes | Yes | No |
| Transactions (MULTI/EXEC) | Yes | Yes | No (CAS via gets/cas) |
| Pipelining | Yes | Yes | Yes |
| Max item size | 512 MB | 512 MB | 1 MB (default) |
| Max connections | Varies by node type | Varies by node type | Varies by node type |
| **Pricing** | | | |
| Node-based discount vs Redis OSS | 20% lower | Baseline | Lowest node cost |
| Serverless discount vs Redis OSS | 33% lower | Baseline | Available |

### Migration Notes: Redis OSS to Valkey

**What you gain:**

* 20% cost savings on node-based, 33% on serverless
* Access to Valkey-specific features in future releases (vector search in 8.2)
* Active open-source community and roadmap
* Zero application code changes (API-compatible with Redis OSS 7.2)

**What you lose:**

* Nothing for standard Redis OSS workloads
* Redis Ltd. commercial module ecosystem (RediSearch, RedisBloom, RedisTimeSeries) is not available. Valkey 8.1 provides native Bloom filters (BF.* commands) and Valkey 8.2 provides native vector search

**What changes:**

* Engine identifier changes from `redis` to `valkey` in API calls and IaC
* Future version numbers follow Valkey versioning (7.2, 8.0, 8.1, 8.2, 9.0)

### Migration Notes: Memcached to Valkey

**What you gain:**

* Persistence (snapshots, AOF)
* Replication and automatic failover
* Rich data structures (hashes, lists, sets, sorted sets, streams, JSON)
* RBAC and IAM authentication
* Pub/Sub and keyspace notifications
* Lua scripting and transactions
* Serverless deployment option
* Online resharding

**What you lose:**

* Multi-threaded architecture (Memcached uses multiple threads per node; Valkey is primarily single-threaded per shard but compensates with sharding)
* Potentially lower per-node cost for simple key-value workloads (Memcached nodes can be cheaper)
* Slab-based memory allocator (Memcached's memory model differs; unlikely to matter in practice)

**What changes:**

* Client library must change (memcached client to Valkey/Redis client)
* Application code must be rewritten for Valkey commands (SET/GET vs set/get, different API)
* Connection model changes (Valkey uses persistent TCP connections)
* Max item size increases from 1 MB to 512 MB

---

## Deployment Model Comparison: Serverless vs Node-Based

| Feature | Serverless | Node-Based |
|---------|:----------:|:----------:|
| **Provisioning** | | |
| Setup time | Under 1 minute | 5-15 minutes |
| Capacity planning | Automatic | Manual (choose node type, count) |
| Scaling | Automatic (up and down) | Manual or policy-based |
| **Networking** | | |
| VPC required | Yes | Yes |
| Port | 6379 | 6379 (configurable) |
| TLS | Always enabled (cannot disable) | Optional (strongly recommended) |
| **Authentication** | | |
| RBAC | Yes | Yes |
| IAM auth | Yes | Yes |
| AUTH token | Not supported | Yes (legacy) |
| **Data and Performance** | | |
| Max data storage | Default 5 TB (adjustable via `CacheUsageLimits`); max 32 GiB per slot | Limited by node type and shard count |
| Max throughput | Default 15,000,000 ECPU/s (adjustable via `CacheUsageLimits`); 30K-90K ECPU/s per slot | Depends on node type and shard count |
| Latency | Single-digit milliseconds | Sub-millisecond |
| **Features** | | |
| Vector search | Not supported | Yes (Valkey 8.2 or above) |
| Global Datastore | Not supported | Yes |
| Cluster mode | Automatic (transparent) | Configurable (enabled/disabled) |
| Custom parameter groups | Not supported | Yes |
| Pub/Sub | Yes | Yes |
| Keyspace notifications | Not supported | Yes |
| Lua scripting | Yes (with restrictions) | Yes |
| **Operations** | | |
| Maintenance windows | None (transparent patching) | Weekly configurable window |
| Manual snapshots | Yes (`CreateServerlessCacheSnapshot`) | Yes (`create-snapshot`) |
| Snapshot restore | Yes (`create-serverless-cache --snapshot-arns-to-restore`) | Yes (`create-replication-group --snapshot-name`) |
| Node type selection | N/A | Full control |
| Reserved pricing | Not available | Yes (1-year or 3-year) |
| **Pricing Model** | | |
| Billing unit | ECPU + data storage (GB-hours) | Node-hours + optional data transfer |
| Minimum cost | ~$6/month (Valkey, approximate, us-east-1) | Varies by node type (starts ~$12/month for t4g.micro) |
| Cost optimization | Automatic right-sizing | Reserved nodes, right-sizing, Graviton |

### Migration Notes: Node-Based to Serverless

**What you gain:**

* Zero capacity planning and automatic scaling
* No maintenance windows or patching overhead
* Sub-minute provisioning
* Pay only for actual usage (beneficial for variable workloads)
* Always-on TLS and encryption

**What you lose:**

* Sub-millisecond latency (serverless is single-digit ms)
* Vector search support (Valkey 8.2 or above, node-based only)
* Global Datastore (node-based only)
* Custom parameter group tuning
* AUTH token authentication (must use RBAC or IAM)
* Reserved node pricing (no commitment discounts for serverless)
* Direct control over node count and placement

**What changes:**

* Endpoint format changes to `*.serverless.<region>.cache.amazonaws.com`
* Auth must be RBAC or IAM (AUTH tokens not supported)
* TLS is mandatory (update clients if not already using TLS)
* Billing model changes from node-hours to ECPU + storage
* Some Lua script restrictions may apply (scripts must have at least one KEY parameter; max script size 4 MiB; max 3,999 arguments per request)
* `SELECT` command (multiple databases) is not supported (serverless is always cluster-mode enabled, so only database 0 is available)
* Keyspace notifications are not supported on serverless caches

### Migration Notes: Serverless to Node-Based

**What you gain:**

* Sub-millisecond latency
* Vector search (Valkey 8.2 or above)
* Global Datastore for multi-region
* Custom parameter group tuning
* Reserved node pricing (approximately 30-55% savings depending on term length and payment option; run `python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` for current estimates)
* AUTH token option (legacy, but available)
* Full control over topology and placement

**What you lose:**

* Automatic scaling (must manage capacity manually or via policies)
* Zero-maintenance patching (must configure maintenance windows)
* Sub-minute provisioning (node-based takes 5-15 minutes)
* Usage-based pricing (node-based charges for provisioned capacity, not actual use)

**What changes:**

* Endpoint format changes from serverless to standard replication group endpoint
* May switch from RBAC to AUTH token (or keep RBAC)
* TLS becomes optional (but strongly recommended to keep it enabled)
* Billing model changes from ECPU + storage to node-hours
* Must choose node type, shard count, and replica count

---

## Migration Path Quick Reference

| From | To | In-Place? | Data Migration Required? | Application Code Changes? | Auth Changes? |
|------|-----|:---------:|:------------------------:|:-------------------------:|:-------------:|
| Redis OSS (node-based) | Valkey (node-based) | Yes | No | No | No |
| Valkey 7.2 | Valkey 8.1 | Yes | No | No | No |
| Valkey 7.2 | Valkey 8.2 | Yes (direct upgrade supported) | No | No | No |
| Self-managed Redis | ElastiCache (node-based) | No | Yes (replication or snapshot) | Endpoint update | May need RBAC |
| Self-managed Redis | ElastiCache (serverless) | No | Yes (dual-write or app-level) | Endpoint + TLS + auth | Must use RBAC |
| Node-based | Serverless | No | Yes (dual-write or snapshot-restore) | Endpoint + TLS + auth | Must switch to RBAC if using AUTH token |
| Serverless | Node-based | No | Yes (dual-write) | Endpoint, possibly auth | Optional |
| Memcached | Valkey | No | Yes (full rewrite) | Full rewrite | Must add RBAC or IAM |
| Cluster-mode disabled | Cluster-mode enabled | Yes (Valkey 7.2+/Redis OSS 7.0+ via compatible mode); No (older versions) | No (7.0+); Yes (older versions) | Cluster-aware client required | No |

---

## Unsupported Migration Paths

The following transitions are not supported in-place and require special handling:

| Transition | Why Not Supported | Workaround |
|------------|-------------------|------------|
| Valkey to Redis OSS (downgrade) | Valkey 7.2 to Redis OSS 7.1 rollback is supported in-place (no downtime). Other Valkey versions cannot be downgraded in-place. | For Valkey 7.2 node-based: use modify-replication-group specifying Redis OSS 7.1. For Valkey 7.2 serverless: use modify-serverless-cache specifying Redis OSS 7.1. For other versions: restore from pre-upgrade snapshot to new Redis OSS cluster. |
| Higher to lower engine version | Version downgrade not supported | Restore from pre-upgrade snapshot to new cluster with older version |
| Serverless to node-based (direct) | No direct conversion path | Create new node-based cluster, migrate data, cut over |
| Node-based to serverless (direct) | No direct conversion path | Create new serverless cache, migrate data, cut over |
| Memcached to Valkey (direct) | Different engines, different data models | Create new Valkey cache, rewrite application, re-populate data |
