# RDS/Aurora Acceleration with ElastiCache

## Caching Patterns

### Cache-Aside (Lazy Loading)

The application manages the cache explicitly. On read, check cache first. On miss, read from RDS and populate cache.

```
Read path:  App -> Cache? -> hit -> return cached data
                          -> miss -> RDS -> write to cache -> return data
Write path: App -> RDS -> invalidate/update cache
```

**Best for**: Most read-heavy workloads. Simple to implement. Application controls exactly what gets cached and for how long.

**Trade-off**: First request for any key is always a cache miss (cold start). Stale data possible between TTL expiry and next read.

### Read-Through

A cache layer handles RDS reads transparently. The application always reads from the cache layer, which fetches from RDS on a miss.

```
Read path:  App -> Cache Layer -> hit -> return cached data
                               -> miss -> RDS -> store in cache -> return data
```

**Best for**: When you want to encapsulate caching logic in a middleware layer rather than scattering it across the application.

**Trade-off**: Requires a wrapper layer. More complexity than cache-aside but cleaner application code.

### Write-Through

The application writes to both cache and RDS simultaneously (or through a layer that does both). Every write updates the cache, so reads are always fresh.

```
Write path: App -> Cache Layer -> write to cache + write to RDS
Read path:  App -> Cache -> always a hit (for previously written keys)
```

**Best for**: Workloads where read-after-write consistency is critical. Eliminates stale data for writes you control.

**Trade-off**: Higher write latency (two writes per operation). Cache fills with data that may never be read.

### Reading from Replicas

If you are using ElastiCache Serverless or have provisioned read replicas (node-based clusters), direct reads to replicas to achieve better scalability and/or lower latency. Reads from replicas are eventually consistent with the primary. In ElastiCache Serverless, reading from the replica port (6380) will direct reads to the client's local availability zone when possible, reducing retrieval latency.

> **Security group / NACL note:** If using the serverless reader port (6380), ensure your security groups and NACLs allow traffic on both port 6379 (primary) and port 6380 (reader). Missing rules for 6380 will cause reader-port connections to fail silently.
> **Best practice:** For node-based clusters with multiple read replicas, distribute read traffic across replicas rather than pinning all reads to a single replica. Cluster-aware clients handle this automatically; for non-clustered (CMD) deployments, use the reader endpoint, which DNS-load-balances across replicas.

## Invalidation Strategies

### TTL-based (simplest)

Set a time-to-live on every cached entry. Data becomes stale for at most TTL seconds.

```python
cache.set(f"user:{user_id}", json.dumps(user_data), ex=300)  # 5 minute TTL
```

- **Pros**: Zero coordination. Works with any write pattern.
- **Cons**: Stale data window equals the TTL. Must balance freshness vs cache hit rate.

### Event-driven (RDS events to Lambda to cache invalidation)

Use application-level events, database triggers, or change data capture (CDC) tools like AWS DMS to detect data changes and trigger cache invalidation. For simpler cases, time-based TTL expiry provides eventual consistency without additional infrastructure.

**Note**: RDS and ElastiCache SNS/EventBridge event notifications are for operational events (failovers, backups, configuration changes), not row-level data changes. Data-change-driven invalidation requires application-level mechanisms.

```
App write -> Application event / CDC -> Lambda -> cache.delete(key)
```

- **Pros**: Near-real-time invalidation. No stale window.
- **Cons**: More infrastructure (event source, Lambda). Eventual consistency between event publish and cache delete.

### Application-level invalidation (most common)

Invalidate or update the cache in the same code path as the database write.

```python
def update_user(user_id: str, data: dict):
    db.execute("UPDATE users SET ... WHERE id = %s", (user_id,))
    cache.delete(f"user:{user_id}")  # Invalidate on write
```

- **Pros**: Precise. No extra infrastructure. Immediate.
- **Cons**: Must be applied consistently in every write path. Easy to miss an invalidation.

## "Create cache from RDS settings" path

ElastiCache can inherit VPC, subnet group, and security group settings from an existing RDS instance. When creating a cache via the AWS Console, use "Create ElastiCache cache" from the RDS console and it will pre-populate network settings from your database. For IaC, reference the same VPC, subnets, and create a security group that allows traffic from the application SG.

## Python Example: Cache-Aside with valkey-py and psycopg2

```python
import os
import json
import valkey
import psycopg2
from psycopg2.extras import RealDictCursor

# Connection pool for cache (reuse across requests)
cache_pool = valkey.ConnectionPool(
    host=os.environ['CACHE_ENDPOINT'],
    port=int(os.environ.get('CACHE_PORT', '6379')),
    username=os.environ.get('CACHE_USERNAME', 'appuser'),
    password=os.environ.get('CACHE_PASSWORD', ''),
    ssl=True,
    ssl_cert_reqs='required',  # Use 'required' for production; 'none' disables certificate verification
    decode_responses=True,
    max_connections=20,
    socket_connect_timeout=5,
    socket_timeout=5,
    retry_on_timeout=True,
)
cache = valkey.Valkey(connection_pool=cache_pool)

# Database connection
db = psycopg2.connect(
    host=os.environ['DB_HOST'],
    dbname=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'],
    sslmode='require',
)

DEFAULT_TTL = 300  # 5 minutes


def get_user(user_id: str) -> dict:
    """Cache-aside read: check cache first, fall back to RDS."""
    cache_key = f"user:{user_id}"

    # Step 1: Try cache
    try:
        cached = cache.get(cache_key)
        if cached:
            return json.loads(cached)
    except valkey.ValkeyError as e:
        # Cache failure should not break the application
        print(f"Cache read error: {e}")

    # Step 2: Cache miss - read from RDS
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, email, plan FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            return None

    user_data = dict(row)

    # Step 3: Populate cache with TTL
    try:
        cache.set(cache_key, json.dumps(user_data, default=str), ex=DEFAULT_TTL)
    except valkey.ValkeyError as e:
        print(f"Cache write error: {e}")

    return user_data


def update_user(user_id: str, name: str, email: str) -> None:
    """Write to RDS, then invalidate cache."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE users SET name = %s, email = %s WHERE id = %s",
            (name, email, user_id),
        )
    db.commit()

    # Invalidate cache entry
    try:
        cache.delete(f"user:{user_id}")
    except valkey.ValkeyError as e:
        print(f"Cache invalidation error: {e}")


def get_user_orders(user_id: str, limit: int = 20) -> list:
    """Cache-aside for a query result set."""
    cache_key = f"user:{user_id}:orders:limit:{limit}"

    try:
        cached = cache.get(cache_key)
        if cached:
            return json.loads(cached)
    except valkey.ValkeyError:
        pass

    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, total, status, created_at FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]

    try:
        cache.set(cache_key, json.dumps(rows, default=str), ex=60)  # Short TTL for order data
    except valkey.ValkeyError:
        pass

    return rows
```

Key patterns in this example:

- **Cache failures are non-fatal**: Every cache operation is wrapped in try/except. The application falls back to RDS if cache is unavailable.
- **TTL on every key**: Prevents unbounded cache growth and limits stale data window.
- **Invalidate on write**: `update_user` deletes the cache entry after a successful database write.
- **Query result caching**: `get_user_orders` caches full query results with shorter TTL for frequently changing data.

## Python Example: Cache-Aside with valkey-py and PyMySQL

Replace psycopg2 with PyMySQL for MySQL/Aurora MySQL:

```python
import pymysql

db = pymysql.connect(
    host=os.environ['DB_HOST'],
    database=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'],
    ssl={'ssl': True},
    cursorclass=pymysql.cursors.DictCursor,
)
```

The caching logic is identical. Only the database driver changes.

## Java: Automatic Query Caching with the AWS Advanced JDBC Wrapper

For Java applications using JDBC with PostgreSQL, MySQL, or MariaDB, the [AWS Advanced JDBC Wrapper](https://github.com/aws/aws-advanced-jdbc-wrapper) provides a Remote Query Cache Plugin that automatically caches query results in ElastiCache with minimal code changes. Instead of implementing cache-aside logic manually, you annotate queries with SQL comment hints:

```java
// The SQL comment hint tells the plugin to cache this query for 300 seconds
ResultSet rs = stmt.executeQuery(
    "/* CACHE_PARAM(ttl=300s) */ SELECT product_name, price FROM products WHERE category = 'electronics'"
);
```

The plugin handles cache lookups, misses, and population transparently. Prerequisites include AWS Advanced JDBC Wrapper 3.3.0+, Apache Commons Pool 2.11.1+, and Valkey Glide 2.3.0+. Both ElastiCache Serverless and node-based caches are supported.

Query caching is not recommended for queries where strong consistency is required, or for queries inside multi-statement transactions that require read-after-write consistency.

## Invalidation Gotchas

### Stale reads after write

**Problem**: Between a database write and cache invalidation (or TTL expiry), reads return stale data.

**Mitigation**: Use application-level invalidation (delete cache key immediately after DB write). For strict consistency, use write-through instead of cache-aside.

### Thundering herd

**Problem**: When a popular cache key expires, many concurrent requests all miss the cache and hit RDS simultaneously, overloading the database.

**Mitigation**: Use cache stampede protection. Only one request fetches from RDS while others wait:

```python
import time
import uuid

def get_with_stampede_protection(cache_key: str, fetch_fn, ttl: int = 300, lock_ttl: int = 10) -> str:
    """Cache-aside with distributed lock to prevent thundering herd."""
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Try to acquire a lock
    lock_key = f"lock:{cache_key}"
    lock_value = str(uuid.uuid4())
    acquired = cache.set(lock_key, lock_value, nx=True, ex=lock_ttl)

    if acquired:
        # This request won the lock: fetch from DB and populate cache
        try:
            result = fetch_fn()
            cache.set(cache_key, result, ex=ttl)
            return result
        finally:
            # Release lock (only if we still hold it)
            if cache.get(lock_key) == lock_value:
                cache.delete(lock_key)
    else:
        # Another request is fetching. Wait briefly, then retry cache.
        for _ in range(10):
            time.sleep(0.1)
            cached = cache.get(cache_key)
            if cached:
                return cached
        # Fallback: fetch from DB directly
        return fetch_fn()
```

### Cache stampede on hot keys

**Problem**: A key with extremely high read rate expires, and even with lock protection, the single fetch may be too slow.

**Mitigation**: Use "early recompute" -- refresh the cache before TTL expires. Set a logical TTL shorter than the actual TTL:

```python
import json
import time

def set_with_early_recompute(cache_key: str, value: str, ttl: int = 300, buffer: int = 30):
    """Store value with metadata for early recompute."""
    payload = json.dumps({'value': value, 'expires_at': time.time() + ttl - buffer})
    cache.set(cache_key, payload, ex=ttl)

def get_with_early_recompute(cache_key: str, fetch_fn, ttl: int = 300, buffer: int = 30):
    """Return cached value, trigger background refresh if near expiry."""
    cached = cache.get(cache_key)
    if cached:
        data = json.loads(cached)
        if time.time() < data['expires_at']:
            return data['value']
        # Near expiry: refresh in background (or synchronously)
        result = fetch_fn()
        set_with_early_recompute(cache_key, result, ttl, buffer)
        return result

    result = fetch_fn()
    set_with_early_recompute(cache_key, result, ttl, buffer)
    return result
```
