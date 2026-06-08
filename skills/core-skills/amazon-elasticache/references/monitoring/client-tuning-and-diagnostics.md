# Client Tuning & Diagnostics

Client-side timeout configuration, connection pooling, TLS setup per language, and CloudWatch metrics troubleshooting. This file covers the client configuration side of performance and connectivity issues. For server-side troubleshooting playbooks, see `troubleshooting.md`. For initial connectivity failures on new caches, see `../setup/connectivity-diagnostics.md`.

---

## Client Timeout Configuration

Poorly tuned timeouts cause two failure modes: too low triggers false failures during brief network blips or failovers; too high makes the application hang when the cache is unreachable.

### Recommended Starting Values

| Timeout | Starting Value | Rationale |
|---------|---------------|-----------|
| Connect timeout | 2-5 seconds | Time to establish TCP + TLS handshake. Increase if cross-AZ or through tunnel. |
| Command (socket) timeout | 1-2 seconds | Max wait for a single command response. Most commands return in under 5ms. |
| Retry attempts | 3 | With exponential backoff. Covers brief failover windows (~15-30s for node-based Multi-AZ). |
| Retry backoff base | 100-200ms | First retry after 100-200ms, then doubles. Avoids thundering herd. |

### Per-Library Configuration

#### Python (redis-py / valkey-py)

```python
import redis

pool = redis.ConnectionPool(
    host="endpoint.cache.amazonaws.com",
    port=6379,
    ssl=True,
    socket_connect_timeout=5,    # seconds, TCP + TLS handshake
    socket_timeout=2,            # seconds, per-command timeout
    retry_on_timeout=True,
    health_check_interval=15,    # seconds, sends PING on idle connections
)
r = redis.Redis(connection_pool=pool)
```

#### Node.js (ioredis)

```javascript
const Redis = require("ioredis");

const client = new Redis({
  host: "endpoint.cache.amazonaws.com",
  port: 6379,
  tls: {},
  connectTimeout: 5000,         // ms, TCP + TLS handshake
  commandTimeout: 2000,         // ms, per-command timeout
  maxRetriesPerRequest: 3,
  retryStrategy(times) {
    return Math.min(times * 200, 2000);  // ms, exponential backoff capped at 2s
  },
});
```

#### Java (Lettuce)

```java
// Socket connect timeout should be lower than command timeout for Lettuce.
// Set JVM DNS cache TTL to support failover DNS changes.
java.security.Security.setProperty("networkaddress.cache.ttl", "10");

RedisURI uri = RedisURI.builder()
    .withHost("endpoint.cache.amazonaws.com")
    .withPort(6379)
    .withSsl(true)
    .withTimeout(Duration.ofMillis(2000))   // per-command timeout
    .build();

ClientResources clientResources = DefaultClientResources.builder()
    .addressResolverGroup(new DirContextDnsResolver())
    .reconnectDelay(
        Delay.fullJitter(
            Duration.ofMillis(100),
            Duration.ofSeconds(10),
            100, TimeUnit.MILLISECONDS))
    .build();

ClientOptions options = ClientOptions.builder()
    .socketOptions(SocketOptions.builder()
        .connectTimeout(Duration.ofMillis(5000))  // TCP + TLS handshake; match table guidance of 2-5s
        .keepAlive(true)
        .build())
    .timeoutOptions(TimeoutOptions.builder()
        .fixedTimeout(Duration.ofMillis(2000))
        .build())
    .build();

RedisClient client = RedisClient.create(clientResources, uri);
client.setOptions(options);
```

#### Go (go-redis)

```go
client := redis.NewClient(&redis.Options{
    Addr:         "endpoint.cache.amazonaws.com:6379",
    TLSConfig:    &tls.Config{},
    DialTimeout:  5 * time.Second,   // TCP + TLS handshake
    ReadTimeout:  2 * time.Second,   // per-command read
    WriteTimeout: 2 * time.Second,   // per-command write
    MaxRetries:   3,
    MinRetryBackoff: 100 * time.Millisecond,
    MaxRetryBackoff: 2 * time.Second,
})
```

### Timeout Tuning After Deployment

1. Check `SuccessfulReadRequestLatency` p99 in CloudWatch (units: microseconds). A p99 of 3000 = 3ms. This metric is calculated at the cache node level; for node-based caches, query it using the `CacheClusterId` dimension; for serverless caches, use `ServerlessCacheName`.
2. Set command timeout to at least 10x the observed p99 to accommodate tail latency and brief slowdowns.
3. If failovers are common (check `aws elasticache describe-events --source-type replication-group --duration 1440`), set connect timeout to at least 5s to survive DNS propagation.
4. For Lambda with VPC attachment, use a 10s connect timeout to handle cold start ENI attachment.

---

## Connection Pooling

Opening a new connection for each request adds 5-20ms of TLS handshake overhead. Connection pooling amortizes this cost across requests.

### Pool Sizing

A good starting point: **pool size = expected concurrent requests per application instance**. For most web applications, 10-50 connections per instance is sufficient.

Signs the pool is too small: commands queue waiting for a free connection, latency increases under load while `EngineCPUUtilization` stays low.
Signs the pool is too large: `CurrConnections` is high, `NewConnections` is high, and most connections sit idle.

### Per-Library Configuration

#### Python (redis-py / valkey-py)

```python
pool = redis.ConnectionPool(
    host="endpoint.cache.amazonaws.com",
    port=6379,
    ssl=True,
    max_connections=50,
)
r = redis.Redis(connection_pool=pool)
# In async frameworks (FastAPI, aiohttp), use redis.asyncio.ConnectionPool instead.
```

#### Node.js (ioredis)

```javascript
// ioredis manages a single persistent connection by default.
// For cluster mode, it opens one connection per node.
// For concurrency, ioredis pipelines commands over the single connection.
// If you need multiple connections (rare), use a manual pool or ioredis Cluster.
const cluster = new Redis.Cluster(
  [{ host: "endpoint.cache.amazonaws.com", port: 6379 }],
  {
    slotsRefreshTimeout: 2000,
    dnsLookup: (address, callback) => callback(null, address),
    redisOptions: { tls: {} },
    scaleReads: "slave",  // read from replicas
  }
);
```

#### Java (Lettuce)

```java
// Lettuce uses a single connection with pipelining by default.
// For thread-safe concurrent access, use StatefulRedisConnection (thread-safe)
// or GenericObjectPool for connection pooling:
GenericObjectPoolConfig<StatefulRedisConnection<String, String>> poolConfig =
    new GenericObjectPoolConfig<>();
poolConfig.setMaxTotal(50);
poolConfig.setMaxIdle(20);
poolConfig.setMinIdle(5);
poolConfig.setTestOnBorrow(true);
```

#### Java (Lettuce) -- Cluster Mode Enabled

For cluster mode enabled, configure `ClusterTopologyRefreshOptions` and node filtering to handle topology changes during failovers:

```java
ClusterTopologyRefreshOptions topologyOptions = ClusterTopologyRefreshOptions.builder()
    .enableAllAdaptiveRefreshTriggers()
    .enablePeriodicRefresh()
    .dynamicRefreshSources(true)
    .build();

ClusterClientOptions clusterOptions = ClusterClientOptions.builder()
    .topologyRefreshOptions(topologyOptions)
    .nodeFilter(it ->
        !(it.is(RedisClusterNode.NodeFlag.FAIL)
        || it.is(RedisClusterNode.NodeFlag.EVENTUAL_FAIL)
        || it.is(RedisClusterNode.NodeFlag.NOADDR)))
    .validateClusterNodeMembership(false)
    .build();

RedisClusterClient clusterClient = RedisClusterClient.create(clientResources, redisUri);
clusterClient.setOptions(clusterOptions);
```

#### Go (go-redis)

```go
client := redis.NewClient(&redis.Options{
    Addr:         "endpoint.cache.amazonaws.com:6379",
    TLSConfig:    &tls.Config{},
    PoolSize:     50,           // max connections in pool
    MinIdleConns: 5,            // keep warm connections ready
    PoolTimeout:  3 * time.Second,  // wait for free connection
    ConnMaxIdleTime: 5 * time.Minute,
})
```

### Monitoring Pool Health

Check these CloudWatch metrics at the cache level:

- `CurrConnections` (Maximum): total open connections across all clients. Compare against expected (pool size x number of app instances).
- `NewConnections` (Sum, per minute): should be low after initial ramp-up. Sustained high values indicate connections are not being reused.

---

## TLS Connection Quick Reference

All ElastiCache serverless caches require TLS. Node-based caches require TLS if created with `--transit-encryption-enabled`, or if TLS is enabled later on an existing cluster using the two-step migration process (`transit-encryption-mode`: `preferred` then `required`). For tunnel-mode TLS settings (connecting through SSM to localhost), see `../setup/connection-guide.md`.

| Language | Library | TLS Setting |
|----------|---------|-------------|
| Python | redis-py / valkey-py | `ssl=True` in connection params |
| Node.js | ioredis | `tls: {}` in options, or use `rediss://` URL scheme |
| Java | Lettuce | `.withSsl(true)` on RedisURI, or `SslOptions.builder().build()` on ClientResources |
| Go | go-redis | `TLSConfig: &tls.Config{}` in Options |
| CLI | valkey-cli | `--tls` flag |

For common TLS error messages and their causes, see `../setup/connectivity-diagnostics.md`.

---

## Missing CloudWatch Metrics

When expected metrics do not appear in CloudWatch, work through this checklist in order.

### 1. No Traffic Yet

ElastiCache emits most metrics only after the cache receives client traffic. A newly created cache with zero commands will have no datapoints for latency, hit rate, or command-family metrics. Send a PING or a test SET/GET, wait 5-10 minutes, then check again.

Metrics that always emit regardless of traffic (node-based): `CurrConnections`, `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`, `FreeableMemory`.
Metrics that require traffic: `CacheHitRate`, `CacheMisses`, `CacheHits`, `SuccessfulReadRequestLatency`, `SuccessfulWriteRequestLatency`, command-family metrics.

### 2. Wrong Namespace or Dimensions

ElastiCache metrics live under the `AWS/ElastiCache` namespace (not `ElastiCache` or `aws/elasticache`; the capitalization and prefix matter).

Dimension reference:

| Deployment | Dimension Name | Dimension Value |
|-----------|---------------|----------------|
| Serverless | `ServerlessCacheName` | The cache name (e.g., `my-cache`) |
| Node-based (cluster-wide) | `ReplicationGroupId` | The replication group ID |
| Node-based (per-node) | `CacheClusterId` | The individual node ID (e.g., `my-cluster-001`) |

Common mistakes:

- Using `CacheClusterId` when the metric only publishes at the `ReplicationGroupId` level, or vice versa. For node-based caches, most metrics including `CacheHits` and `CacheMisses` are per-node (`CacheClusterId`). For serverless caches, `CacheHitRate` uses the `ServerlessCacheName` dimension.
- Using `ReplicationGroupId` for per-node metrics like `EngineCPUUtilization` when you need per-shard visibility.
- Using the cache name as the dimension value for a node-based cache instead of the replication group ID.

### 3. Verify via CLI

```bash
# List available metrics for a serverless cache
aws cloudwatch list-metrics \
  --namespace AWS/ElastiCache \
  --dimensions Name=ServerlessCacheName,Value=<cache-name> \
  --region <region>

# List available metrics for a node-based cache
aws cloudwatch list-metrics \
  --namespace AWS/ElastiCache \
  --dimensions Name=ReplicationGroupId,Value=<replication-group-id> \
  --region <region>
```

If the list is empty: confirm the cache exists and is in `available` status, confirm the region matches, and confirm traffic has been sent.

### 4. Console vs. CLI Mismatch

When metrics appear in the CLI but not in the CloudWatch console:

- Check the time range in the console. The default view may be too narrow to include the metric's retention period.
- Check the statistic selected. Some metrics only make sense with specific statistics (e.g., `ElastiCacheProcessingUnits` should use Sum, not Average).
- Check the region selector in the console matches the cache's region.

### 5. Metric Retention

CloudWatch retains ElastiCache metrics at these resolutions:

- 1-minute datapoints: 15 days
- 5-minute datapoints: 63 days
- 1-hour datapoints: 455 days

If investigating an issue older than 15 days, you must use 5-minute or 1-hour period in your query, or the datapoints will have already expired.
