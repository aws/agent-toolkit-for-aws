# Data Modeling & Patterns

**When to use:** The user needs help designing key schemas, choosing data structures (strings, hashes, sorted sets, streams, etc.), implementing caching patterns (cache-aside, session store, leaderboard, rate limiting), or generating application code for a specific data access pattern.
**When not needed:** The user is setting up a new cache, choosing an engine or deployment model, configuring authentication, or working on monitoring and cost optimization.

Design key schemas and implement Valkey/Redis data structure patterns for application use cases.

## Loading

Read this file first. Other references in this folder load on demand when the current answer requires them. Scripts in `scripts/` run on demand.

## Routing

- For semantic cache, conversational memory, RAG, or vector-based recommendation, route to the `genai` sub-skill.
- If the user's engine is Memcached, load `memcached-recipe.md` for Memcached-specific patterns and constraints.
- If the user asks whether a specific command or feature is available on their engine version, load `command-availability.md` for the version compatibility matrix.

## Reference File Loading

Load `recipe-gallery.md` when the user asks about ANY of these patterns (do not rely on the Pattern Quick Reference table alone; the gallery has full working code):

| User asks about | Load |
|---|---|
| Cache-aside, read-through, write-through, write-behind | `common-patterns.md` (canonical starter), `recipe-gallery.md` (XFetch probabilistic refresh) |
| Session store, session management, user sessions | `common-patterns.md` (canonical starter) |
| Rate limiting, throttling, API rate control | `common-patterns.md` (fixed window), `recipe-gallery.md` (sliding window) |
| Leaderboard, ranking, scoreboard, sorted set patterns | `recipe-gallery.md` |
| Counters, analytics, HyperLogLog, unique counts | `recipe-gallery.md` |
| Pub/Sub, messaging, event notification | `recipe-gallery.md` |
| Streams, event sourcing, consumer groups, XADD/XREAD | `recipe-gallery.md` |
| Shopping cart, e-commerce cart | `recipe-gallery.md` |
| Job queue, task queue, priority queue | `recipe-gallery.md` |
| Distributed lock, mutex, Redlock | `recipe-gallery.md` |
| "Show me a working example", "give me code for" + any caching pattern | `recipe-gallery.md` |

Load `command-availability.md` when the user asks about command support on a specific engine or version, or when generating code that uses commands beyond basic GET/SET/HSET.

Load `memcached-recipe.md` when engine is Memcached or the user mentions Memcached-specific constraints.

## Check for existing context

Before starting, read `.elasticache/requirements.json` if it exists. Use the values (`engine`, `runtime`, `deployment_model`, `patterns`) as inputs rather than re-asking. If `engine` is `memcached`, load `memcached-recipe.md`. If `patterns` already lists the user's use case, skip pattern selection.

## Workflow

1. Identify the user's use case and match to a pattern below
2. Recommend the right data structures and key design
3. Provide working application code in the user's language
4. Include TTL strategy and invalidation approach

## After implementation

Update `.elasticache/requirements.json`: add or confirm the implemented pattern(s) in the `patterns` array. Read the existing file first, merge your updates, then write it back. Do not overwrite fields owned by other sub-skills.

## Handoff to monitoring

After implementing a pattern, prompt the user: "Want me to set up CloudWatch dashboards and alarms for this cache?" If yes, hand off to the `monitoring` sub-skill. For cache-aside patterns, the key metrics to monitor are hit rate, evictions, and latency. For rate limiters, monitor CPU and connection count.

## Pattern Quick Reference

| Pattern | Key Design | Structures / Commands | TTL |
|---------|-----------|----------------------|-----|
| DB Query Cache | `{table}:{pk}` or `{query_hash}` | Strings/JSON, cache-aside | 60s-3600s |
| Session Store | `session:{session_id}` | Hashes or Strings | Match session timeout |
| Leaderboard | `leaderboard:{game_id}:{period}` | Sorted Sets (ZADD, ZRANGE, ZRANK) | Per period |
| Rate Limiting | `ratelimit:{user_id}:{window}` | INCR+EXPIRE (fixed) or Sorted Sets (sliding) | Window duration |
| Counters & Analytics | `metric:{name}:{window}` | INCR, HINCRBY, HyperLogLog | Per window |
| Pub/Sub | channel names | PUBLISH/SUBSCRIBE (fire-and-forget); prefer SPUBLISH/SSUBSCRIBE (sharded pub/sub) for high-throughput on cluster-mode-enabled clusters | N/A |
| Event Streams | `stream:{topic}` | Streams + Consumer Groups | Per retention policy |
| Shopping Cart | `cart:{user_id}` | Hashes + TTL | Cart expiry |
| Job Queue | `queue:{name}` | Lists (FIFO) or Sorted Sets (priority) | Optional |
| Recommendation | `item:{id}:likes`, `item:{id}:ratings` | INCR/DECR, HSET | Optional |

## Key Design Principles

- Use colons as namespace separators: `{entity}:{id}:{attribute}`
- Include the entity type in the key: `user:u100:profile`, not just `u100`
- Keep keys short but readable
- Use TTL on everything that has a natural expiry. On serverless, Valkey uses a volatile-lru eviction policy and auto-scales storage up to the configured CacheUsageLimits maximum. OOM errors only occur when the maximum is reached AND no keys with a TTL are eligible for eviction. Always set a TTL on serverless caches.
- Prefer atomic operations (INCR, HINCRBY, ZADD) over read-modify-write

## Multi-Tenant Key Namespacing

In multi-tenant systems, prefix every key with the tenant identifier to prevent collisions:

```
{tenant_id}:{resource}:{id}
```

Example: `tenant42:session:abc123`, `tenant42:cart:user7`

Benefits of consistent tenant prefixing:

- Prevents data leaks between tenants; each tenant's keys are isolated by prefix.
- Enables per-tenant SCAN. Use `SCAN 0 MATCH tenant42:*` to enumerate only one tenant's keys.
- Supports per-tenant eviction or cleanup by scanning and deleting a single prefix.

**Hash tags for multi-key operations:** If you use MGET, pipelines, or transactions across multiple keys for the same tenant on cluster-mode-enabled caches (including serverless), wrap the tenant ID in curly braces to ensure all keys hash to the same slot: `{tenant42}:session:abc123`. Without hash tags, multi-key operations across different slots will fail with CROSSSLOT errors. **Hot-slot risk:** Hash tags concentrate all keys for a tenant onto a single shard. For large tenants with high key counts or throughput, this can create a hot slot that overloads one shard while others remain idle. Monitor per-shard CPU and memory metrics, and consider splitting very large tenants across multiple hash tags if hot-spotting occurs.

- Simplifies capacity analysis; count keys per tenant with `SCAN` + prefix match.

## Dangerous Commands -- Never Use KEYS in Production

**The `KEYS` command must never be used in production.** `KEYS *` (or any `KEYS` pattern) blocks the entire Redis/Valkey server while it scans every key in the database. On caches with millions of keys, this can block the server for seconds or longer, causing timeouts and cascading failures for all connected clients. This applies to both node-based and serverless ElastiCache deployments.

**Use `SCAN` with cursor-based iteration instead.** `SCAN` performs the same work incrementally without blocking the server. Each `SCAN` call returns a small batch of keys and a cursor to continue from.

Safe SCAN pattern in Python:

```python
# Using valkey-py (pip install valkey)
import valkey
r = valkey.Valkey(host="your-endpoint", port=6379, ssl=True, decode_responses=True)

# Or using redis-py (pip install redis) -- the AWS-validated Python client
# import redis
# r = redis.Redis(host="your-endpoint", port=6379, ssl=True, decode_responses=True)

def scan_keys(pattern="*", count=100):
    """Iterate over keys matching a pattern without blocking the server.

    Uses SCAN with a cursor to retrieve keys in small batches.
    The count parameter is a hint (not a hard limit) for batch size.
    """
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=count)
        for key in keys:
            yield key
        if cursor == 0:
            break

# Example: find all session keys
for key in scan_keys("session:*"):
    print(key)
```

If a team member or external reference suggests using `KEYS`, always redirect to `SCAN`. The same principle applies to other blocking commands like `SMEMBERS` on very large sets; prefer `SSCAN`, `HSCAN`, and `ZSCAN` for large collections.

## Code Generation

When generating application code:

- Always use TLS (ssl=True / tls:{}) for ElastiCache endpoints
- Prefer connection pooling; avoid creating a new connection per request. Use a module-level singleton pattern (initialize on first use via a `get_client()` function) to reuse connections across requests.
- Use pipelining for multi-command operations (reduces round trips)
- Wrap cache calls in try/except; cache is an optimization, not a dependency
- Reuse connections across requests (connection pooling). Create the connection pool once at application startup and share it; creating a new connection per request is ~13x slower (2.82 ms vs 0.21 ms per AWS benchmarks)
- Include the relevant SDK: redis-py or valkey-py (Python), ioredis (Node.js), Lettuce or Jedis (Java), go-redis (Go), or Valkey Glide (multi-language)
- Never use restricted ElastiCache commands in generated code. The following commands are unavailable on ElastiCache for clusters running Redis OSS or Valkey: `BGREWRITEAOF`, `BGSAVE`, `CONFIG`, `DEBUG`, `MIGRATE`, `REPLICAOF`, `SAVE`, `SLAVEOF`, `SHUTDOWN`, `SYNC`. Some restrictions may vary by engine version; check `command-availability.md` for details.

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."
