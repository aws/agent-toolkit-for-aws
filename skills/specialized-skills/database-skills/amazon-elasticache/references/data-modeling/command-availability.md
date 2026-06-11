# Command and Feature Availability by Engine Version

Quick reference for which commands and features are available in each ElastiCache engine version. Use this when recommending data structures or patterns to verify they are supported on the customer's current engine.

## Command Availability Matrix

| Command / Feature | Redis OSS 6.x | Redis OSS 7.x | Valkey 7.2 | Valkey 8.0 | Valkey 8.1 | Valkey 8.2 |
|-------------------|:--------------:|:--------------:|:----------:|:----------:|:----------:|:----------:|
| **Per-Key TTL** | | | | | | |
| EXPIRE, TTL, PEXPIRE, PTTL | Yes | Yes | Yes | Yes | Yes | Yes |
| EXPIREAT, PEXPIREAT | Yes | Yes | Yes | Yes | Yes | Yes |
| EXPIRETIME, PEXPIRETIME | No | Yes | Yes | Yes | Yes | Yes |
| **Per-Field TTL (Hash)** | | | | | | |
| HEXPIRE, HPEXPIRE | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| HTTL, HPTTL | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| HEXPIREAT, HPEXPIREAT | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| HEXPIRETIME, HPEXPIRETIME | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| HPERSIST | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| HSETEX, HGETEX | No | No | No | No | No | No (available on ElastiCache Valkey 9.0) |
| **Bloom Filters** | | | | | | |
| BF.ADD, BF.EXISTS, BF.RESERVE | No | No | No | No | Yes | Yes |
| BF.INSERT, BF.MADD, BF.MEXISTS | No | No | No | No | Yes | Yes |
| BF.CARD, BF.INFO | No | No | No | No | Yes | Yes |
| **Vector Search** | | | | | | |
| FT.CREATE | No | No | No | No | No | Yes (node-based only) |
| FT.SEARCH | No | No | No | No | No | Yes (node-based only) |
| FT.INFO, FT.DROPINDEX | No | No | No | No | No | Yes (node-based only) |
| FT._LIST | No | No | No | No | No | Yes (node-based only) |
| **JSON** | | | | | | |
| JSON.SET, JSON.GET | Yes (6.2.6+) | Yes | Yes | Yes | Yes | Yes |
| JSON.MGET | Yes (6.2.6+) | Yes | Yes | Yes | Yes | Yes |
| JSON.ARRAPPEND, JSON.OBJKEYS | Yes (6.2.6+) | Yes | Yes | Yes | Yes | Yes |
| **Streams** | | | | | | |
| XADD, XREAD, XRANGE | Yes | Yes | Yes | Yes | Yes | Yes |
| XREADGROUP (consumer groups) | Yes | Yes | Yes | Yes | Yes | Yes |
| XAUTOCLAIM | Yes (6.2+) | Yes | Yes | Yes | Yes | Yes |
| **ACL (Access Control)** | | | | | | |
| ACL SETUSER, ACL DELUSER | Yes | Yes | Yes | Yes | Yes | Yes |
| ACL GETUSER, ACL LIST | Yes | Yes | Yes | Yes | Yes | Yes |
| ACL DRYRUN | No | Yes | Yes | Yes | Yes | Yes (available from Redis OSS 7.x; verify serverless availability — some ACL commands are restricted on serverless) |
| **Pub/Sub** | | | | | | |
| PUBLISH, SUBSCRIBE | Yes | Yes | Yes | Yes | Yes | Yes |
| Sharded Pub/Sub (SSUBSCRIBE) | No | Yes | Yes | Yes | Yes | Yes |
| **Functions and Scripting** | | | | | | |
| EVAL (Lua scripting) | Yes | Yes | Yes | Yes | Yes | Yes |
| FUNCTION LOAD (server-side functions) | No | Yes | Yes | Yes | Yes | Yes |
| FUNCTION LIST, FUNCTION DELETE | No | Yes | Yes | Yes | Yes | Yes |
| **Client and Connection** | | | | | | |
| CLIENT NO-EVICT | No | Yes | Yes | Yes | Yes | Yes |
| CLIENT NO-TOUCH | No | No | Yes | Yes | Yes | Yes |
| **Cluster** | | | | | | |
| CLUSTER SHARDS | No | Yes | Yes | Yes | Yes | Yes |
| CLUSTER MYSHARDID | No | Yes | Yes | Yes | Yes | Yes |
| **Other** | | | | | | |
| GETDEL, GETEX | Yes (6.2+) | Yes | Yes | Yes | Yes | Yes |
| LMPOP, ZMPOP | No | Yes | Yes | Yes | Yes | Yes |
| SINTERCARD | No | Yes | Yes | Yes | Yes | Yes |
| OBJECT FREQ, OBJECT IDLE | Yes | Yes | Yes | Yes | Yes | Yes |

## Deployment Model Restrictions

Some commands are further restricted by deployment model:

| Command / Feature | Serverless | Node-Based |
|-------------------|:----------:|:----------:|
| SELECT (multiple databases) | Not supported | Supported (cluster-mode disabled only) |
| Vector search (FT.*) | Not supported | Supported (Valkey 8.2 or above, excludes data tiering nodes; t2/t3/t4g require increased memory reserve) |
| WAIT | Restricted | Supported |
| CONFIG SET/GET | Not supported | Not supported (use parameter groups) |
| DEBUG | Not supported | Not supported |
| BGREWRITEAOF, BGSAVE, SAVE | Not supported | Not supported |
| MIGRATE, REPLICAOF, SLAVEOF | Not supported | Not supported |
| MONITOR | Not supported | Supported |
| SHUTDOWN, SYNC | Not supported | Not supported |
| PSUBSCRIBE, PUNSUBSCRIBE | Not supported | Supported |
| Keyspace notifications | Not supported | Supported |
| KEYS | Not supported | Available but dangerous |
| CLIENT NO-EVICT | Not supported | Supported (Redis OSS 7.x+ / Valkey 7.2+) |
| FUNCTION LOAD, FCALL, FCALL_RO | Not supported | Supported (Redis OSS 7.x+ / Valkey 7.2+) |
| Lua scripts (cross-slot) | Restricted (must have at least one KEY parameter; max 4 MiB script; max 3,999 arguments) | Supported (cluster-mode disabled) |
| SUBSCRIBE (global) | Supported | Supported (cluster-mode disabled) |
| SSUBSCRIBE (sharded) | Supported | Supported |
| OBJECT FREQ | Not supported | Supported |
| OBJECT IDLE | Not supported | Supported |

## Common Scenarios

**"I need per-field TTL on hashes"**: Available on ElastiCache Valkey 9.0. Per-field hash expiration (HEXPIRE, HTTL, HSETEX, HGETEX) was introduced in Valkey 9.0. On engine versions before 9.0, the workaround is to store each field as a separate key with its own EXPIRE, or use a sorted set with timestamps for expiration tracking.

**"I need vector search / semantic similarity"**: Requires Valkey 8.2 or above on node-based clusters (recommend 9.0). Not available on serverless. Not available in Redis OSS on ElastiCache. Use FT.CREATE to define a vector index, FT.SEARCH to query it.

**"I need server-side functions"**: Requires Redis OSS 7.x or Valkey 7.2+. FUNCTION LOAD is available from Redis OSS 7.x (node-based only; not available on serverless). FUNCTION LOAD replaces the older EVAL-only model (though EVAL still works). Functions persist across restarts, unlike EVALSHA-cached scripts.

**"I need sharded Pub/Sub"**: Requires Redis OSS 7.x or Valkey 7.2+. Use SSUBSCRIBE instead of SUBSCRIBE for cluster-mode-enabled deployments. Sharded Pub/Sub routes messages to the shard that owns the channel, reducing cross-node traffic.
