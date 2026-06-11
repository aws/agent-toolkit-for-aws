# Recipe Gallery

Non-obvious algorithms that require specific implementation details. Standard patterns (session stores, counters, pub/sub, shopping carts, job queues, activity feeds) are omitted because the model generates those from constraints alone. These recipes contain fractional score encoding, probabilistic math, or cleanup semantics that must be implemented precisely.

```python
# Shared setup for all recipes
# Uses valkey-py (pip install valkey). Alternatively, redis-py 4.1.2+ is the
# AWS-validated client (pip install redis) and is API-compatible; replace
# `import valkey` with `import redis` and `valkey.Valkey` with `redis.Redis`.
import valkey, time, json, math, random, uuid

_client = None

def get_client():
    """Lazy client initialization. Never create connections at module level.
    Uses ValkeyCluster because serverless is cluster-mode-enabled only.
    For cluster-mode-disabled node-based clusters, use valkey.Valkey instead.
    """
    global _client
    if _client is None:
        # Serverless requires cluster-mode client
        _client = valkey.ValkeyCluster(
            host="your-cache-endpoint.serverless.use1.cache.amazonaws.com",
            port=6379, ssl=True, decode_responses=True,
            socket_connect_timeout=5, socket_timeout=2,
        )
    return _client
```

---

## 1. Leaderboard Tie-Breaking

Sorted sets order equal scores lexicographically, which is rarely desired. To break ties by time (earliest score wins), encode an inverse timestamp into the fractional part of the score.

**Data structure:** Sorted set  |  **Key:** `leaderboard:{game_id}`
**Score format:** `points.inverse_timestamp` (e.g., `1500.300000000`)  |  **Member:** Player ID

```python
def add_score_with_tiebreak(game_id: str, player_id: str, points: int) -> None:
    """Score = points + fractional inverse-timestamp.
    Example: 1500 pts at epoch 1700000000 -> 1500.300000000
    Higher fractional = earlier timestamp, so ZREVRANGE ranks earlier achievers first.
    """
    max_ts = 9999999999  # far-future ceiling
    fractional = (max_ts - int(time.time())) / (max_ts + 1)
    get_client().zadd(f"leaderboard:{game_id}", {player_id: points + fractional})

def get_top_n(game_id: str, n: int = 10) -> list[tuple[str, float]]:
    return get_client().zrevrange(f"leaderboard:{game_id}", 0, n - 1, withscores=True)

def get_player_rank(game_id: str, player_id: str) -> int | None:
    return get_client().zrevrank(f"leaderboard:{game_id}", player_id)
```

**Why this works:** The fractional part is always < 1, so it never changes integer-point ranking. Within the same points, an earlier player has a larger fractional part (`max_ts - earlier > max_ts - later`), so ZREVRANGE places them higher. No secondary data structure or Lua script needed.

---

## 2. Cache-Aside with XFetch (Probabilistic Early Refresh)

Probabilistic early refresh prevents thundering herd on popular keys. As TTL approaches zero, random callers refresh before actual expiry so the key never truly expires under load.

**Data structure:** String  |  **Key:** `cache:{entity}:{id}`
**TTL:** Varies by staleness tolerance (e.g., 300s for product data, 60s for inventory)

```python
CACHE_TTL = 300  # 5 minutes

def cache_aside_get(entity: str, entity_id: str, db_fetch_fn, ttl: int = CACHE_TTL) -> dict:
    """Cache-aside with XFetch. db_fetch_fn(entity_id) -> dict reads from the DB."""
    key = f"cache:{entity}:{entity_id}"
    c = get_client()
    cached = c.get(key)
    if cached is not None:
        data = json.loads(cached)
        remaining_ttl = c.ttl(key)
        if remaining_ttl > 0 and _should_early_refresh(remaining_ttl, ttl):
            result = db_fetch_fn(entity_id)
            if result is not None:
                c.setex(key, ttl, json.dumps(result))
                return result
        return data
    # Cache miss
    result = db_fetch_fn(entity_id)
    if result is not None:
        c.setex(key, ttl, json.dumps(result))
    return result

def _should_early_refresh(remaining_ttl: int, total_ttl: int) -> bool:
    """XFetch: returns True with increasing probability as TTL approaches 0.
    Only activates in the last 20% of TTL. beta controls aggressiveness."""
    beta = 1.0
    if total_ttl <= 0:
        return False
    threshold = total_ttl * 0.2
    if remaining_ttl >= threshold:
        return False
    return random.random() < math.exp(-remaining_ttl * beta / threshold)
```

**Why probabilistic, not deterministic?** A fixed threshold (e.g., "refresh at 10% TTL remaining") causes all concurrent readers to hit the DB at once. The exponential probability curve means on average exactly one caller refreshes early while the rest serve the cached value.

**When NOT to use:** Do not use XFetch for consistency-critical data (inventory counts, account balances) where serving a stale value during the refresh window is a correctness bug, not just a performance tradeoff.

---

## 3. Sliding-Window Rate Limiter

Each request is a unique sorted set member scored by timestamp. The window slides continuously, and denied requests are cleaned up to avoid polluting the count.

**Data structure:** Sorted set  |  **Key:** `ratelimit:{client_id}:{window}`
**Score:** Epoch seconds  |  **Member:** `{timestamp}:{uuid}` (UUID prevents same-ms collisions)

```python
def sliding_window_rate_limit(
    client_id: str, window_name: str, max_requests: int, window_seconds: int,
) -> tuple[bool, int]:
    """Returns (allowed, remaining)."""
    key = f"ratelimit:{client_id}:{window_name}"
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex[:8]}"
    c = get_client()

    pipe = c.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - window_seconds)  # prune old
    pipe.zadd(key, {member: now})                             # optimistic add
    pipe.zcard(key)                                           # count window
    pipe.expire(key, window_seconds + 1)                      # auto-cleanup
    results = pipe.execute()

    current_count = results[2]
    allowed = current_count <= max_requests
    if not allowed:
        c.zrem(key, member)  # remove denied request to keep count accurate
    return allowed, max(0, max_requests - current_count)
```

> **Cluster mode note:** In cluster mode (including serverless), all keys in a pipeline must hash to the same slot. This recipe uses a single key per pipeline call, so it works as-is. If you extend pipelines to operate on multiple keys, use hash tags (e.g., `{prefix}:key1`, `{prefix}:key2`) to ensure slot co-location.

**Why UUID members?** Timestamp-only members silently drop concurrent requests (ZADD updates the score of an existing member identified by member name, so duplicate timestamps would collapse into one entry). Using a UUID suffix as part of the member name ensures each request is a distinct entry.

**Why remove denied requests?** Without cleanup, denied requests inflate the count, making the limiter progressively stricter under burst traffic.

---

## 4. Cache Invalidation (Write-Through + Event-Driven + TTL Hybrid)

No single invalidation method is reliable on its own: write-through misses changes from other services, event-driven delivery can lag or fail, and TTL alone allows stale reads. Combining all three bounds staleness even when individual layers fail.

* **Write-through:** Update cache on every DB write in the same code path.
* **Event-driven:** Subscribe to change events (SNS/SQS, DynamoDB Streams) to invalidate keys modified by other services.
* **TTL safety net:** Always set a TTL as backstop, so stale keys self-heal if both other layers miss.

```python
CACHE_TTL = 300  # 5-minute backstop

def write_through(entity: str, entity_id: str, data: dict, db_write_fn) -> None:
    """Write to DB then cache. TTL acts as safety net."""
    db_write_fn(entity_id, data)
    get_client().setex(f"cache:{entity}:{entity_id}", CACHE_TTL, json.dumps(data))

def handle_change_event(entity: str, entity_id: str) -> None:
    """Called by SNS/SQS consumer when another service modifies the entity."""
    get_client().delete(f"cache:{entity}:{entity_id}")
```

**Why all three layers?** Write-through keeps the cache fresh for the owning service. Event-driven catches external writes. TTL guarantees bounded staleness even if events are lost or write-through fails. TTL is the only layer that requires zero operational trust.
