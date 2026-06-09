# Self-Managed Redis Migration to ElastiCache

Migrate from self-managed Redis (running on EC2, on-premises, or another cloud provider) to Amazon ElastiCache. This guide covers assessment, migration approaches, and cutover.

## Assessment Phase

Before migrating, inventory your source environment and validate compatibility.

### 1. Source Inventory

Gather the following from your self-managed Redis instance:

| Item | How to check | Why it matters |
|------|-------------|----------------|
| Redis version | `INFO server` -> `redis_version` | Valkey 7.2 is compatible with Redis OSS up to version 7.2.4. Older source versions may use deprecated features. |
| Data size | `INFO memory` -> `used_memory_human` | Determines target cache sizing and migration duration |
| Key count | `DBSIZE` | Helps estimate migration time and validate completeness |
| Command usage | `INFO commandstats` | Identifies unsupported or uncommon commands |
| Persistence config | `CONFIG GET save`, `CONFIG GET appendonly` | Determines whether RDB snapshots or AOF are in use for snapshot-based migration |
| Cluster mode | `INFO cluster` -> `cluster_enabled` | Cluster mode affects migration tooling and target topology |
| Modules loaded | `MODULE LIST` | RedisJSON, RediSearch, RedisTimeSeries, etc. may not all be available in Valkey |
| Connected clients | `INFO clients` -> `connected_clients` | Helps size the target cache |
| Peak memory | `INFO memory` -> `used_memory_peak_human` | Size the target to handle peak load |
| Replication topology | `INFO replication` | Identifies primary/replica structure to replicate on the target |

### 2. Automated Preflight Check

Run the bundled preflight script against your source Redis:

```bash
# Without TLS
python3 scripts/migration_preflight.py --host <source-host> --port 6379

# With TLS
python3 scripts/migration_preflight.py --host <source-host> --port 6379 --tls
```

The script checks version compatibility, module usage, key count, memory, cluster mode, and sizing. Resolve any **FAIL** findings before proceeding.

### 3. Compatibility Check

Review potential compatibility issues:

- **Unsupported commands:** Some Redis commands may behave differently or be unavailable. Check `commandstats` output against [ElastiCache supported commands](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/RestrictedCommands.html).
- **Modules:** If you use RedisJSON, RediSearch, or RedisTimeSeries modules, verify whether Valkey provides equivalent functionality or plan application changes.
- **Lua scripts:** Test all Lua scripts against the target engine. Most standard Lua scripts work unchanged, but scripts that use module-specific commands need updates.
- **Restricted commands:** The following commands are unavailable on ElastiCache: `bgrewriteaof`, `bgsave`, `config`, `debug`, `migrate`, `replicaof`, `save`, `slaveof`, `shutdown`, and `sync`. Use parameter groups instead of `CONFIG` commands. Check your application code and scripts for usage of any of these commands.

### 4. Network Planning

ElastiCache runs inside a VPC. Plan connectivity from your source to the target:

- **Source on EC2 (same VPC):** Direct access. Ensure security groups allow traffic on port 6379.
- **Source on EC2 (different VPC):** Use VPC peering or Transit Gateway.
- **Source on-premises:** Use AWS Direct Connect or Site-to-Site VPN for replication-based migration. For snapshot-based, upload the RDB file to S3.
- **Source on another cloud:** Use VPN, Direct Connect, or snapshot-based migration via S3.

---

## Migration Approaches

### Approach 1: Snapshot-Based (Offline)

**Best for:** Small to medium datasets, acceptable downtime window, simplest execution.

**Steps:**

```bash
# 1. Create RDB snapshot on the source
valkey-cli -h <source-host> BGSAVE
# Wait for completion:
valkey-cli -h <source-host> LASTSAVE

# 2. Copy the RDB file to S3
aws s3 cp /var/lib/redis/dump.rdb s3://my-migration-bucket/dump.rdb

# 3. Grant ElastiCache access to the S3 bucket by adding a bucket policy:
# {
#   "Version": "2012-10-17",
#   "Statement": [{
#     "Sid": "ElastiCacheSnapshotAccess",
#     "Effect": "Allow",
#     "Principal": { "Service": "<region>.elasticache-snapshot.amazonaws.com" },
#     "Action": ["s3:GetObject", "s3:ListBucket", "s3:GetBucketAcl"],
#     "Resource": [
#       "arn:aws:s3:::my-migration-bucket",
#       "arn:aws:s3:::my-migration-bucket/*"
#     ]
#   }]
# }

# 4. Create an ElastiCache replication group and seed from the snapshot
aws elasticache create-replication-group \
  --replication-group-id my-new-cache \
  --replication-group-description "Migrated from self-managed Redis" \
  --engine valkey \
  --engine-version 9.0 \
  --cache-node-type cache.r7g.large \
  --num-cache-clusters 2 \
  --snapshot-arns arn:aws:s3:::my-migration-bucket/dump.rdb \
  --transit-encryption-enabled \
  --region <region>
```

**Downtime:** Equals the time from final snapshot to application cutover. For large datasets, this can be minutes to hours.

**Limitations:**

- Requires a downtime window
- Any writes during migration are lost
- RDB format must be compatible with the target engine version
- For node-based clusters, use `--snapshot-arns` with `create-replication-group`. For serverless caches, use `--snapshot-arns-to-restore` with `create-serverless-cache` instead.

### Approach 2: Replication-Based (Online)

> **Eligibility:** Online migration is not supported to ElastiCache serverless caches or clusters running on the r6gd node type. This approach is designed for migrating from self-hosted Redis/Valkey on EC2 to ElastiCache, not for moving data between ElastiCache clusters.

**Best for:** Large datasets, minimal downtime requirement, source is network-reachable from VPC.

**Steps:**

```bash
# 1. Create the target replication group (without snapshot seeding)
aws elasticache create-replication-group \
  --replication-group-id my-new-cache \
  --replication-group-description "Migration target" \
  --engine valkey \
  --engine-version 9.0 \
  --cache-node-type cache.r7g.large \
  --num-cache-clusters 2 \
  --automatic-failover-enabled \
  --multi-az-enabled \
  --region <region>

# 2. Test the migration (validates connectivity and compatibility)
aws elasticache test-migration \
  --replication-group-id my-new-cache \
  --customer-node-endpoint-list Address=<source-host>,Port=6379 \
  --region <region>

# 3. Start the migration (begins replication)
aws elasticache start-migration \
  --replication-group-id my-new-cache \
  --customer-node-endpoint-list Address=<source-host>,Port=6379 \
  --region <region>

# 4. Monitor replication status
# Option A: Use INFO replication on the ElastiCache primary node
# to check master_link_status (should be 'up') and replication offset
valkey-cli -h <elasticache-primary-endpoint> -p 6379 INFO replication

# Option B: Monitor the ReplicationLag and PrimaryLinkHealthStatus
# CloudWatch metrics for the target replication group
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElastiCache \
  --metric-name ReplicationLag \
  --dimensions Name=CacheClusterId,Value=my-new-cache-001 \
  --statistics Average \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --region <region>

# 5. When lag is minimal, complete the migration (promotes the target)
aws elasticache complete-migration \
  --replication-group-id my-new-cache \
  --region <region>

# To abort migration without ensuring data is in sync, use --force:
# aws elasticache complete-migration \
#   --replication-group-id my-new-cache \
#   --force \
#   --region <region>
# WARNING: --force stops migration without ensuring data is in sync.
# Use it only to abort migration, not for normal completion.
```

**Replication lag convergence:** "Minimal" means ReplicationLag < 1 second for 5 consecutive checks (1 minute apart). If lag does not converge below 1s within 30 minutes, check source write rate and network bandwidth between source and target. Do not proceed with `complete-migration` until lag is stable.

**Monitoring replication health:** In addition to the CLI command above, verify replication status using:

- Run `INFO replication` on the ElastiCache primary node and confirm `master_link_status` is `up`
- Monitor the **Primary Link Health Status** CloudWatch metric (value of 1 means data is in sync)
- Verify low client output buffer by running `CLIENT LIST` on your source Redis instances

**Downtime:** Near zero. Only the brief moment during the DNS/endpoint switch in your application.

**Important:** During migration, the ElastiCache cluster is read-only. You can use ElastiCache nodes for reads, but you cannot write to the ElastiCache cluster. All writes must continue going to the source Redis until `complete-migration` is executed.

**Requirements:**

*Target requirements:*

- Target must NOT have encryption in-transit enabled (TLS must be disabled during migration; you can enable it after migration completes) (verify against current online migration prerequisites documentation)
- Target must have Multi-AZ enabled (`--automatic-failover-enabled`)
- Target must be using Valkey, or Redis OSS 5.0.6 or higher
- Target must NOT be part of a global datastore
- Target must have data tiering disabled
- Number of shards in source and target must match (prerequisite).
- Number of logical databases must be the same on source and target (set via `databases` in Redis config)
- Target must have sufficient memory available to fit the data from the source cluster. See `sizing-assessment.md` for memory sizing guidance.

*Source requirements:*

- Source Redis must be accessible from the ElastiCache VPC (security groups, VPC peering, VPN, or Direct Connect)
- The security group attached to source Redis instances must allow inbound traffic from ElastiCache nodes
- Source must NOT have AUTH enabled
- Source `protected-mode` must be set to `no`
- If source has `bind` configuration, it must be updated to allow requests from ElastiCache nodes
- Data-modification commands must not be renamed (e.g., `sync`, `psync`, `info`, `config`, `command`, `cluster`)
- All source Redis instances must be running on the same port
- Source must have enough capacity to handle replication overhead
- For cluster-mode disabled, source can be Redis 2.8.21 onward (via CLI). For cluster-mode enabled, source can be any cluster-mode enabled version.

### Approach 3: Dual-Write (Application-Level)

**Best for:** Complex migrations, need full control, source not directly reachable from VPC, or need to transform data during migration.

> **Warning:** Do NOT use DUMP/RESTORE for cross-engine migration (e.g., Redis OSS to Valkey). The serialization format is engine-specific and may fail silently or produce corrupted data. Use application-level copy or the ElastiCache migration tools instead.

**Steps:**

```python
# Dual-write wrapper example
import valkey

old_client = valkey.Valkey(host="old-redis-host", port=6379, decode_responses=True)
new_client = valkey.Valkey(
    host="new-cache.serverless.use1.cache.amazonaws.com",
    port=6379,
    ssl=True,
    decode_responses=True,
)

# Feature flag to control read source
READ_FROM_NEW = False  # Flip to True when new cache is warm


def cache_set(key: str, value: str, ttl: int = 300):
    """Write to both caches during migration."""
    old_client.setex(key, ttl, value)
    try:
        new_client.setex(key, ttl, value)
    except Exception:
        # Log but don't fail -- old cache is still the primary
        pass


def cache_get(key: str) -> str | None:
    """Read from the active cache."""
    if READ_FROM_NEW:
        result = new_client.get(key)
        if result is None:
            # Fall back to old cache during warm-up
            result = old_client.get(key)
            if result is not None:
                # Backfill into new cache
                ttl = old_client.ttl(key)
                if ttl and ttl > 0:
                    new_client.setex(key, ttl, result)
        return result
    else:
        return old_client.get(key)
```

**Downtime:** Zero, if the application handles the dual-write correctly.

**Trade-offs:**

- Requires application code changes
- Double write latency during the migration period
- Must handle failures on either cache gracefully
- Most flexible: works even when source is not directly reachable from the VPC

---

## Cutover Checklist

Complete each item before and during the cutover:

- [ ] Target cache provisioned and accessible from application VPC
- [ ] Data migrated or replication caught up (lag below acceptable threshold)
- [ ] Application updated with the new ElastiCache endpoint
- [ ] Authentication configured (RBAC or IAM on the target; serverless does not support AUTH tokens)
- [ ] TLS enabled on the target (mandatory for serverless; strongly recommended for node-based)
- [ ] Client connection code uses `ssl=True` / `tls: {}` for the new endpoint
- [ ] Monitoring configured on the target (CloudWatch metrics, alarms, dashboards -- see `monitoring` sub-skill)
- [ ] Security audit passed on the new cache (`python3 scripts/security_audit.py --serverless <name>` or `--replication-group <name>`)
- [ ] Rollback plan documented (keep old source running until validation period ends)
- [ ] DNS or application config switch executed
- [ ] Smoke tests passed (read/write operations, latency within expected range)
- [ ] Old source decommissioned after validation period (recommended: keep source running for 48-72 hours post-cutover)

---

## Choosing an Approach

| Factor | Snapshot-Based | Replication-Based | Dual-Write |
|--------|:-----------:|:-------------:|:--------:|
| Downtime | Minutes to hours | Near zero | Zero |
| Complexity | Low | Medium | High |
| Network requirement | S3 upload only | Source reachable from VPC | No direct connectivity needed |
| Data transformation | None (exact copy) | None (exact copy) | Possible during write |
| Data size limit | Practical limit ~100 GB | No practical limit | No practical limit |
| Application changes | Endpoint update only | Endpoint update only | Dual-write logic required |
| Best for | Small data, simple setup | Large data, minimal downtime | Complex scenarios, unreachable source |

---

## Post-Migration Validation

After cutover, verify the migration was successful:

1. **Key count:** Compare `DBSIZE` on source vs target
2. **Spot-check data:** Read a sample of keys and verify values match
3. **Latency:** Confirm read/write latency meets expectations (sub-ms for node-based, single-digit ms for serverless)
4. **Hit rate:** Monitor cache hit rate -- expect it to ramp up over the warm-up period
5. **Error rate:** Monitor application logs for connection errors or unexpected responses
6. **Run security audit:**

   ```bash
   python3 scripts/security_audit.py --serverless <name>
   # or
   python3 scripts/security_audit.py --replication-group <name>
   ```
