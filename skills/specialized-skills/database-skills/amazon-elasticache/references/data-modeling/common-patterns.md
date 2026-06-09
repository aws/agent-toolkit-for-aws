# Common Patterns (Python & Node.js)

Canonical implementations for the three most requested patterns. Each includes connection setup, core operations, error handling, and TTL strategy. For advanced algorithms (XFetch, sliding-window rate limiting, tie-breaking leaderboards), see `recipe-gallery.md`.

All examples use lazy client initialization per the connection safety rule.

> **Cluster mode vs. standalone clients:** ElastiCache Serverless operates in cluster mode enabled only; clients must support cluster mode (e.g., `ValkeyCluster` in Python, `new Redis.Cluster()` in ioredis) to handle slot-based routing. The standalone `Valkey`/`new Redis()` clients shown below work for cluster mode disabled node-based clusters. For serverless or cluster mode enabled deployments, swap to the cluster-aware client variant.

---

## 1. Cache-Aside (DB Query Cache)

Read from cache first. On miss, read from DB, write to cache. On DB write, invalidate cache.

### Python (valkey-py)

```python
import valkey
import json

_client = None

def get_client():
    global _client
    if _client is None:
        _client = valkey.Valkey(
            host="mycluster.xxxxxx.use1.cache.amazonaws.com",  # Replace with your endpoint; for clustercfg endpoints, use ValkeyCluster instead
            port=6379, ssl=True, decode_responses=True,
            username="appuser", password="<your-password-or-iam-token>",
            socket_connect_timeout=5, socket_timeout=2,
        )
    return _client

CACHE_TTL = 300  # 5 minutes; tune per staleness tolerance

def cache_get(client, entity: str, entity_id: str, db_fetch_fn) -> dict | None:
    key = f"cache:{entity}:{entity_id}"
    cached = client.get(key)
    if cached is not None:
        return json.loads(cached)
    result = db_fetch_fn(entity_id)
    if result is not None:
        client.setex(key, CACHE_TTL, json.dumps(result))
    return result

def cache_invalidate(client, entity: str, entity_id: str) -> None:
    client.delete(f"cache:{entity}:{entity_id}")

def cache_write_through(client, entity: str, entity_id: str, data: dict, db_write_fn) -> None:
    db_write_fn(entity_id, data)
    client.setex(f"cache:{entity}:{entity_id}", CACHE_TTL, json.dumps(data))
```

### Node.js (ioredis)

```javascript
const Redis = require("ioredis");

let client;
function getClient() {
  if (!client) {
    client = new Redis({
      host: "mycluster.xxxxxx.use1.cache.amazonaws.com", port: 6379, tls: {},  // For clustercfg or serverless endpoints, use new Redis.Cluster([{host, port}], {redisOptions: {tls: {}}}) instead of standalone new Redis()
      username: "appuser", password: "<your-password-or-iam-token>",
      connectTimeout: 5000, commandTimeout: 2000,
    });
  }
  return client;
}

const CACHE_TTL = 300;

async function cacheGet(entity, entityId, dbFetchFn) {
  const key = `cache:${entity}:${entityId}`;
  const cached = await getClient().get(key);
  if (cached !== null) return JSON.parse(cached);
  const result = await dbFetchFn(entityId);
  if (result !== null && result !== undefined) {
    await getClient().setex(key, CACHE_TTL, JSON.stringify(result));
  }
  return result;
}

async function cacheInvalidate(entity, entityId) {
  await getClient().del(`cache:${entity}:${entityId}`);
}
```

---

## 2. Session Store

Store user session data as a hash. TTL matches session timeout.

### Python (valkey-py)

```python
import valkey
import json
import time

_client = None

def get_client():
    global _client
    if _client is None:
        _client = valkey.ValkeyCluster(
            host="mycluster.xxxxxx.clustercfg.use1.cache.amazonaws.com",  # Replace with your endpoint
            port=6379, ssl=True, decode_responses=True,
            username="appuser", password="<your-password-or-iam-token>",
            socket_connect_timeout=5, socket_timeout=2,
        )
    return _client

SESSION_TTL = 1800  # 30 minutes

def save_session(client, session_id: str, data: dict) -> None:
    key = f"session:{session_id}"
    data["updated_at"] = str(time.time())
    client.hset(key, mapping=data)
    client.expire(key, SESSION_TTL)

def get_session(client, session_id: str) -> dict | None:
    key = f"session:{session_id}"
    data = client.hgetall(key)
    if not data:
        return None
    client.expire(key, SESSION_TTL)  # slide expiry on access
    return data

def delete_session(client, session_id: str) -> None:
    client.delete(f"session:{session_id}")
```

### Node.js (ioredis)

```javascript
const SESSION_TTL = 1800;

async function saveSession(sessionId, data) {
  const key = `session:${sessionId}`;
  data.updated_at = String(Date.now() / 1000);
  await getClient().hset(key, data);
  await getClient().expire(key, SESSION_TTL);
}

async function getSession(sessionId) {
  const key = `session:${sessionId}`;
  const data = await getClient().hgetall(key);
  if (!data || Object.keys(data).length === 0) return null;
  await getClient().expire(key, SESSION_TTL);
  return data;
}

async function deleteSession(sessionId) {
  await getClient().del(`session:${sessionId}`);
}
```

---

## 3. Rate Limiter (Fixed Window)

Simple INCR + EXPIRE pattern. For sliding-window with better accuracy at window boundaries, see `recipe-gallery.md`.

### Python (valkey-py)

```python
import valkey

_client = None

def get_client():
    global _client
    if _client is None:
        _client = valkey.ValkeyCluster(
            host="mycluster.xxxxxx.clustercfg.use1.cache.amazonaws.com",  # Replace with your endpoint
            port=6379, ssl=True, decode_responses=True,
            username="appuser", password="<your-password-or-iam-token>",
            socket_connect_timeout=5, socket_timeout=2,
        )
    return _client

# Lua script: atomic INCR + conditional EXPIRE.
# Returns [count, ttl]. Sets TTL only when the key was just created (count == 1)
# or when TTL is missing (race condition recovery).
#
# NOTE: ElastiCache Serverless requires all Lua scripts to have at least one
# KEY parameter (scripts with 0 keys will fail). This script uses KEYS[1].
# In cluster mode (including Serverless), all keys used in a Lua script must
# hash to the same slot. If you extend this script to use multiple keys,
# use hash tags (e.g., {client_id}) to ensure they share a slot.
_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, ttl}
"""

def is_rate_limited(client, client_id: str, max_requests: int,
                    window_seconds: int) -> tuple[bool, int]:
    """Returns (is_limited, remaining_requests).

    Uses a Lua script for atomicity: INCR and EXPIRE run in a single
    server-side call, eliminating the race where a key could persist
    without a TTL if EXPIRE failed or another request slipped in
    between INCR and EXPIRE.
    """
    key = f"ratelimit:{client_id}:{window_seconds}"
    count, _ = client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)

    remaining = max(0, max_requests - count)
    return count > max_requests, remaining
```

### Node.js (ioredis)

```javascript
// Lua script: atomic INCR + conditional EXPIRE.
// Sets TTL when key is new (count == 1) or TTL is missing (race recovery).
const RATE_LIMIT_SCRIPT = `
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, ttl}
`;

async function isRateLimited(clientId, maxRequests, windowSeconds) {
  const key = `ratelimit:${clientId}:${windowSeconds}`;
  const [count] = await getClient().eval(RATE_LIMIT_SCRIPT, 1, key, windowSeconds);
  const remaining = Math.max(0, maxRequests - count);
  return { limited: count > maxRequests, remaining };
}
```

---

## Error Handling Pattern

Cache is an optimization, not a dependency. Wrap all cache calls so failures fall through to the data source.

```python
def safe_cache_get(client, entity, entity_id, db_fetch_fn):
    try:
        return cache_get(client, entity, entity_id, db_fetch_fn)
    except Exception:
        return db_fetch_fn(entity_id)
```

```javascript
async function safeCacheGet(entity, entityId, dbFetchFn) {
  try {
    return await cacheGet(entity, entityId, dbFetchFn);
  } catch {
    return dbFetchFn(entityId);
  }
}
```

> **Reconnection strategy:** When a client disconnects due to a timeout or failover, retry with exponential backoff and jitter to avoid a thundering herd of reconnections that can overwhelm the server and cause prolonged outages. See the AWS best practices for [cluster client discovery and exponential backoff](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/BestPractices.Clients.Redis.Discovery.html).
