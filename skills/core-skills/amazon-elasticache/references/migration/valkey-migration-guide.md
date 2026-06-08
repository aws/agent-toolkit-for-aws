# Redis OSS to Valkey Migration Guide

Complete guide for planning and executing a Redis OSS to Valkey migration on ElastiCache, including client compatibility, upgrade paths, and extended support cost implications.

## Decision Tree: Should You Migrate to Valkey?

```
Is your cluster running Redis OSS on ElastiCache?
├── No (self-managed Redis) --> See "Self-Hosted Redis to ElastiCache" in instructions.md
└── Yes
    ├── Running Redis OSS 4.x or 5.x?
    │   └── Yes --> URGENT: These versions are past EOL. You are paying Extended Support fees.
    │       └── Direct upgrade to Valkey is supported (e.g., --engine valkey --engine-version 7.2).
    │           Optionally upgrade to Valkey 8.0, 8.1, or 8.2 for new features (Valkey 9.0 is the recommended target).
    ├── Running Redis OSS 6.x?
    │   └── Yes --> Extended Support fees begin after EOL (check lifecycle calendar).
    │       └── Direct upgrade to Valkey is supported (e.g., --engine valkey --engine-version 7.2).
    │           Optionally upgrade to Valkey 8.0, 8.1, or 8.2 for new features (Valkey 9.0 is the recommended target).
    └── Running Redis OSS 7.x?
        └── Yes --> Direct switch to Valkey 7.2 available (in-place, zero downtime).
            └── After switch: optionally upgrade to Valkey 8.0, 8.1, or 8.2 for new features (Valkey 9.0 is the recommended target).
```

After reaching Valkey 7.2, further upgrades are available:

```
Valkey 7.2
├── Valkey 8.0 (in-place upgrade, adds performance improvements)
├── Valkey 8.1 (in-place upgrade, hash table memory improvements: up to 20% less overhead for common key/value patterns; suitable bridge between 8.0 and 8.2)
├── Valkey 8.2 (in-place upgrade, adds vector search)
└── Valkey 9.0 (in-place upgrade, recommended target version)
```

## Multi-Step Upgrade Paths

In-place engine version downgrades are not supported, except for Valkey 7.2 to Redis OSS 7.1 rollback (see `references/migration/rollback-procedures.md`). Plan upgrades forward only.

| Current Version | Target | Steps | Estimated Time |
|----------------|--------|-------|----------------|
| Redis OSS 4.x | Valkey 7.2 | Direct: `--engine valkey --engine-version 7.2` | 1 operation |
| Redis OSS 5.x | Valkey 7.2 | Direct: `--engine valkey --engine-version 7.2` | 1 operation |
| Redis OSS 6.x | Valkey 7.2 | Direct: `--engine valkey --engine-version 7.2` | 1 operation |
| Redis OSS 7.x | Valkey 7.2 | Direct: `--engine valkey --engine-version 7.2` | 1 operation (minutes) |
| Redis OSS (any) | Valkey 8.0 | Direct: `--engine valkey --engine-version 8.0` | 1 operation |
| Redis OSS (any) | Valkey 8.2 | Direct: `--engine valkey --engine-version 8.2` | 1 operation |
| Valkey 7.2 | Valkey 8.1 | Valkey 7.2 -> 8.1 (direct) | 1 operation (minutes) |
| Valkey 7.2 | Valkey 8.2 | Valkey 7.2 -> 8.2 (direct) | 1 operation (minutes) |
| Valkey 8.0 | Valkey 8.2 | Valkey 8.0 -> 8.2 (direct) | 1 operation (minutes) |
| Valkey 8.1 | Valkey 8.2 | Valkey 8.1 -> 8.2 (direct) | 1 operation (minutes) |

> **Note:** Cross-engine upgrades support jumping directly from any Redis OSS version to any available Valkey version (7.2, 8.0, 8.2, etc.) in a single operation. Verify the target version is available in your region. AWS documentation may not explicitly list every supported source→target combination.

Valkey 8.1 features (verify availability in your region): 20% less memory via new hash table (efficiency improvement), native Bloom filters, COMMANDLOG, SET IFEQ, ZRANK 45% lower latency, PFMERGE/PFCOUNT 12x faster. Note: Valkey 8.0 introduced 20% more data per node (capacity improvement); these are two distinct features.

Valkey 7.2.6 adds: WITHSCORE option for ZRANK/ZREVRANK, CLIENT NO-TOUCH, CLUSTER MYSHARDID.

Each step is an in-place upgrade. Direct cross-engine upgrades from any Redis OSS version to Valkey are supported (e.g., `modify-replication-group --engine valkey --engine-version 7.2`). Multi-step upgrades (e.g., upgrading to Redis OSS 7.x first) are optional for users who prefer incremental validation. When upgrading from Redis OSS 5.0.6 and higher, you will experience no downtime. When upgrading from earlier Redis OSS versions (e.g., 4.x), you may experience a failover time of 30 to 60 seconds during DNS propagation. Take a snapshot before each step. Allow the cluster to stabilize between steps (monitor CloudWatch metrics for 15-30 minutes).

## Extended Support Cost Impact

Redis versions past End-of-Life incur Extended Support charges on top of regular node pricing. These charges increase over time (Year 1, Year 2, Year 3+ tiers). Migrating to Valkey eliminates Extended Support charges entirely and provides 20% node-based pricing savings (33% on serverless).

Run the price calculator to see current Extended Support rates for your cluster:

```bash
# Extended Support surcharge for a 6-node Redis cluster
python3 scripts/price_calculator.py --engine redis --extended-support --nodes 6 --region <region>

# Serverless cost estimate
python3 scripts/price_calculator.py --engine redis --mode serverless --data-gb <your-data-size> --ops-per-sec <N> --region <region>
```

The calculator fetches live pricing from the AWS Bulk Pricing API. Rates are cached locally for 7 days.

## Client Library Compatibility

Valkey is wire-protocol compatible with Redis OSS 7.2. Most client libraries work without code changes. The table below lists minimum versions and any required configuration changes. Client library version requirements are community/vendor-specified and may change. Verify against the latest library documentation.

### Java Clients

| Client | Min Version for Valkey | Code Changes Required | Notes |
|--------|----------------------|----------------------|-------|
| Jedis | 4.0+ (recommended: 5.0+) | None | Works out of the box. 5.0+ has dedicated Valkey support. |
| Lettuce | 6.2+ (recommended: 6.3+) | None | Connection URI stays `redis://` or `rediss://` (TLS). |
| Redisson | Check [Redisson compatibility matrix](https://github.com/redisson/redisson#compatibility) (recommended: 3.30+) | None for basic use | Cluster-mode-enabled with Redisson requires testing: verify `ClusterServersConfig` compatibility. Redisson's distributed objects (locks, maps, queues) work unchanged. |
| Valkey GLIDE (Java) | 1.0+ | New client | Official Valkey client. Consider for new projects building on the Valkey ecosystem. Existing projects can stay on Jedis/Lettuce with no compatibility issues. |

**Redisson-specific notes:**

* Redisson 3.27+ is validated for Valkey 7.2 compatibility.
* If using `RedissonClient` with cluster mode enabled, test the `ClusterServersConfig` scan interval and DNS resolution against Valkey endpoints before production cutover.
* Redisson's `RLock`, `RMap`, `RQueue`, and other distributed objects are Valkey-compatible since they use standard Redis commands internally.
* If using Redisson PRO features (e.g., performance optimizations, additional codecs), verify with Redisson's compatibility matrix.

### Python Clients

| Client | Min Version for Valkey | Code Changes Required | Notes |
|--------|----------------------|----------------------|-------|
| redis-py | 4.5+ (recommended: 5.0+) | None | `redis.Redis()` and `redis.cluster.RedisCluster()` work unchanged. |
| valkey-py | 6.0+ | Import change | `from valkey import Valkey` instead of `from redis import Redis`. API is identical. |
| Valkey GLIDE (Python) | 1.0+ | New client | Official Valkey client. Consider for new projects building on the Valkey ecosystem. Existing projects can stay on redis-py/valkey-py. |

### Node.js Clients

| Client | Min Version for Valkey | Code Changes Required | Notes |
|--------|----------------------|----------------------|-------|
| ioredis | 5.0+ | None | Works out of the box. Connection URL stays `rediss://` for TLS. |
| node-redis | 4.5+ | None | `createClient()` works unchanged with Valkey endpoints. |
| Valkey GLIDE (Node.js) | 1.0+ | New client | Official Valkey client. Consider for new projects building on the Valkey ecosystem. Existing projects can stay on ioredis/node-redis. |

### Go Clients

| Client | Min Version for Valkey | Code Changes Required | Notes |
|--------|----------------------|----------------------|-------|
| go-redis/redis | v9.0+ | None | `redis.NewClusterClient()` and `redis.NewClient()` work unchanged. |
| valkey-go | v2.0+ | Import change | `github.com/valkey-io/valkey-go` instead of `github.com/redis/go-redis`. |
| Valkey GLIDE (Go) | 2.0+ | New client | Official Valkey client. Go support added in GLIDE 2.0. Consider for new projects building on the Valkey ecosystem. |

### .NET Clients

| Client | Min Version for Valkey | Code Changes Required | Notes |
|--------|----------------------|----------------------|-------|
| StackExchange.Redis | 2.7+ | None | `ConnectionMultiplexer.Connect()` works unchanged. |

## Pre-Migration Checklist

Before switching from Redis OSS to Valkey:

* [ ] **Verify source version.** Direct cross-engine upgrade from any Redis OSS version to Valkey is supported. No intermediate Redis OSS version upgrade is required.
* [ ] **Check for Redis module usage.** If using RediSearch, RedisBloom, or RedisTimeSeries modules: RediSearch functionality is replaced by native vector search in Valkey 8.2. RedisBloom is replaced by native Bloom filter support (BF.ADD, BF.EXISTS, BF.RESERVE) in Valkey 8.1+. RedisTimeSeries has no Valkey equivalent; evaluate whether the workload can be redesigned.
* [ ] **Verify client library version.** Check the compatibility table above. Upgrade the client library if below the minimum version.
* [ ] **Test in non-production.** Create a non-production cluster, switch it to Valkey, and run application integration tests.
* [ ] **Run `scripts/migration_preflight.py`.** Validates version compatibility, module usage, memory, and cluster configuration.
* [ ] **Take a manual snapshot.** In-place rollback is only supported from Valkey 7.2 to Redis OSS 7.1. For upgrades beyond Valkey 7.2 (e.g., to 8.0+), the snapshot is your rollback path.
* [ ] **Plan the maintenance window.** The engine switch is zero-downtime with Multi-AZ, but schedule during low traffic as a precaution.
* [ ] **Notify stakeholders.** The engine identifier changes from `redis` to `valkey` in API calls, CloudWatch metrics namespace, and IaC definitions.

## Execution

After all checklist items pass:

> **Important:** If your cluster is a Redis OSS (cluster mode disabled) single-node cluster (no replicas), you must first add it to a replication group before performing the cross-engine upgrade. See [Creating a replication group using an existing cluster](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.CreatingReplGroup.ExistingCluster.html). The `modify-replication-group` command below will fail on standalone single-node clusters.

```bash
# Take pre-migration snapshot
aws elasticache create-snapshot \
  --replication-group-id <cluster-id> \
  --snapshot-name pre-valkey-migration-$(date +%Y%m%d) \
  --region <region>

# Switch engine (zero downtime from Redis OSS 5.0.6+)
# Note: Single-node Redis OSS (cluster mode disabled) clusters must first be
# added to a replication group before cross-engine upgrading.
# If using a custom parameter group, add --cache-parameter-group-name <valkey-param-group>
# The Valkey custom parameter group must have the same Redis OSS static parameter values.
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine valkey \
  --engine-version 8.0 \
  --apply-immediately \
  --region <region>
```

Monitor the operation:

```bash
aws elasticache describe-replication-groups \
  --replication-group-id <cluster-id> \
  --query "ReplicationGroups[0].Status" \
  --region <region>
```

Wait for status to return to `available`. Then optionally upgrade to a newer Valkey version. Valkey 9.0 is the recommended target:

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine-version 9.0 \
  --apply-immediately \
  --region <region>
```

## Post-Migration Validation

* [ ] Confirm engine shows `valkey` in `describe-replication-groups` output
* [ ] Spot-check application reads and writes
* [ ] Verify CloudWatch metrics are flowing (namespace remains `AWS/ElastiCache`; dimensions are `CacheClusterId` and `CacheNodeId`, not an engine dimension)
* [ ] Run `scripts/security_audit.py --replication-group <cluster-id>` to confirm security posture
* [ ] Update IaC definitions to reflect `engine: valkey` and the new engine version
* [ ] Keep the pre-migration snapshot for at least 7 days as a rollback safety net

## Rollback

**Valkey 7.2 rollback (in-place):** ElastiCache supports rolling back from Valkey 7.2 to Redis OSS 7.1 in-place with no downtime and no endpoint changes. Use the same `modify-replication-group` command specifying `--engine redis --engine-version 7.1`. Any user group and user associated with the replication group must be configured with engine type `REDIS`.

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine redis \
  --engine-version 7.1 \
  --apply-immediately \
  --region <region>
```

Alternatively, you can restore a snapshot created from your Valkey 7.2 cache as a Redis OSS 7.1 cache.

**Valkey 8.0+ rollback (snapshot-based):** In-place rollback from Valkey 8.0 or higher to Redis OSS is not supported. If the migration causes issues:

1. Restore the pre-migration snapshot to a new Redis OSS cluster
2. Update application endpoints to point to the restored cluster
3. Decommission the Valkey cluster after confirming the rollback is stable

See `references/migration/rollback-procedures.md` for detailed rollback steps.
