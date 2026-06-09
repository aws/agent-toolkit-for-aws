# Memcached Scale-Out Recipe

Guidance for using Amazon ElastiCache for Memcached: when it fits, how it scales, and what it lacks.

## When to Use Memcached

Memcached is the right choice when **all** of the following are true:

- You need simple get/set ephemeral caching (string key-value pairs)
- Your workload is read-heavy and benefits from multi-threaded read performance
- You do not need data persistence (data loss on restart is acceptable)
- You do not need replication or automatic failover
- You do not need advanced data structures (sorted sets, streams, hashes, lists)
- You do not need pub/sub, RBAC, IAM authentication, or vector search

**Typical use case:** Caching serialized database query results, HTML fragments, API responses, or computed objects where the source of truth is always the database and the cache is purely an acceleration layer.

## Serverless Memcached vs Node-Based Memcached

### Serverless Memcached

- Requires Memcached engine version 1.6.22 or higher
- Transparent Multi-AZ: data is automatically replicated across availability zones
- Supports automatic daily backups for recovery (must be explicitly enabled)
- No capacity planning or node selection required
- Automatic scaling within configured limits
- TLS always enabled: clients must support TLS connectivity to connect to serverless Memcached
- Simpler operational model: no node monitoring, no manual shard management

### Node-Based Memcached

- Manual scaling: you choose instance types and number of nodes
- No replication: each node holds a unique slice of data
- Node failure means partial data loss (client detects and routes to other nodes, but data is gone)
- Lower per-unit cost at steady-state if you can accurately predict load

**Recommendation:** Start with serverless Memcached unless you have a specific reason to manage nodes (e.g., cost optimization at very large steady-state scale).

## Auto Discovery

ElastiCache Memcached supports Auto Discovery, which lets clients automatically detect when nodes are added or removed. The client connects to the cluster's configuration endpoint (not individual node endpoints), polls for changes once per minute by default (this interval can be adjusted), and updates its node list without any application redeployment. See the [ElastiCache Auto Discovery documentation](https://docs.aws.amazon.com/AmazonElastiCache/latest/mem-ug/AutoDiscovery.html) for implementation details.

## Consistent Hashing

Memcached clients use consistent hashing to distribute keys across nodes:

- Each node is assigned positions on a hash ring
- A key is hashed and placed on the ring; it maps to the next node clockwise
- When a node is added or removed, only a fraction of keys need to remap (roughly `1/N` where N is the number of nodes), rather than all keys

This minimizes cache misses during scaling events.

## Scale-Out Pattern

Adding capacity to a Memcached cluster:

1. **Add nodes** via the console, AWS CLI, or SDK
2. **Auto Discovery** detects the new nodes within the polling interval
3. **Consistent hashing** redistributes a fraction of the key space to new nodes
4. **New nodes start cold**: cache misses for remapped keys will hit the database until the cache warms up

For node-based, scaling is done via `ModifyCacheCluster` (CLI: `aws elasticache modify-cache-cluster`). For serverless Memcached, scaling is automatic within the configured `CacheUsageLimits`; adjust limits via `modify-serverless-cache` with `--cache-usage-limits`. See AWS docs for full parameter reference.

## Node Failure Behavior

- **Data on the failed node is lost.** Node-based Memcached has no replication, so there is no replica to promote.
- The client removes the failed node from its hash ring; affected keys become cache misses that fall through to the database.
- Use serverless Memcached for transparent Multi-AZ redundancy, or design the application to tolerate cache misses gracefully.

## When NOT to Use Memcached

Switch to Valkey (or Redis OSS) if you need any of the following:

| Requirement | Why Memcached cannot help |
|-------------|--------------------------|
| Data persistence | Node-based Memcached is purely in-memory with no persistence. Serverless Memcached supports daily backup/restore but not RDB/AOF snapshots. |
| Replication / automatic failover | Node-based Memcached has no replicas. Serverless Memcached provides transparent Multi-AZ data redundancy. |
| Sorted sets, lists, streams, hashes | Memcached supports only string key-value pairs |
| Pub/sub messaging | Not supported |
| RBAC or IAM authentication | Not supported for Memcached |
| Vector search | Requires Valkey 8.2 or above node-based |
| Lua scripting or server-side logic | Not supported |
| Atomic data structure operations (INCR on hash fields, ZADD, etc.) | Limited to basic INCR/DECR on string counters |

**Rule of thumb:** If your use case goes beyond simple get/set/delete with TTL, use Valkey.

## Memcached Constraints

- Maximum item size: 1 MB
- Maximum 60 nodes per node-based Memcached cluster (default quota; can be increased via Service Quotas; serverless scales differently)
- No persistence (node-based); daily backups only (serverless)
- No pub/sub, no Lua scripting, no server-side logic
- No RBAC or IAM authentication
- Data model limited to string key-value pairs
