# Engine Upgrades, Patching, and Node Type Changes

Operational runbook for keeping ElastiCache clusters current with engine versions, service updates, and node type changes.

## Engine Version Upgrades

### Valkey and Redis OSS Engine Version Upgrades

Engine version upgrades are performed in-place with minimal downtime for replication groups running Redis OSS 5.0.6 or higher with Multi-AZ enabled. The cluster is available for reads during the entire upgrade and for writes during most of the upgrade, except during the failover operation which lasts a few seconds. For versions earlier than Redis OSS 5.0.6, you may experience a failover time of 30 to 60 seconds during DNS propagation. Single-node clusters experience primary unavailability during upgrades. Note: pending scale-up operations must complete before an engine upgrade can be applied.

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine-version 8.0 \
  --apply-immediately \
  --region <region>
```

Process (single shard / cluster mode disabled):

1. ElastiCache upgrades replicas first, one at a time
2. Performs a failover to promote an upgraded replica to primary
3. Upgrades the old primary last
4. Total time depends on cluster size and data volume (typically minutes to an hour)

Process (multiple shards / cluster mode enabled):

1. All shards are processed in parallel; only one upgrade operation is performed on a shard at any time
2. In each shard, all replicas are processed before the primary is processed
3. If there are fewer replicas in a shard, the primary in that shard might be processed before replicas in other shards finish
4. Across all shards, primary nodes are processed in series; only one primary node is upgraded at a time

### Valkey Major Version Upgrades (e.g., 7.2 -> 8.2)

Same in-place mechanism as minor upgrades. Major versions may introduce new features (e.g., vector search in 8.2) and deprecate old behaviors.

Pre-upgrade checklist:

- Review the Valkey release notes for breaking changes
- Test the upgrade in a non-production environment first
- Confirm application compatibility with the new version
- When upgrading major engine versions (e.g., from 5.0.6 to 6.0), select a new parameter group that is compatible with the new engine version
- Take a manual snapshot before upgrading (safety net)
- Schedule during a low-traffic window even though the upgrade is online
- Prepare your application for connection drops: during engine upgrades, ElastiCache will terminate existing client connections. Implement error retries with exponential backoff in your Redis/Valkey clients to minimize impact.

```bash
# Take a pre-upgrade snapshot
aws elasticache create-snapshot \
  --replication-group-id <cluster-id> \
  --snapshot-name pre-upgrade-$(date +%Y%m%d) \
  --region <region>

# Upgrade
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine-version 8.2 \
  --apply-immediately \
  --region <region>
```

### Redis OSS to Valkey Migration (In-Place Engine Switch)

Valkey is designed as a drop-in replacement for Redis OSS 7. No application code changes required. When upgrading from Redis OSS 5.0.6 and higher, you will experience no downtime. When upgrading from earlier Redis OSS versions than 5.0.6, you may experience a failover time of 30 to 60 seconds during DNS propagation.

```bash
# If using the default parameter group:
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine valkey \
  --engine-version 8.0 \
  --apply-immediately \
  --region <region>

# If using a custom parameter group, you must also pass a Valkey parameter group:
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine valkey \
  --engine-version 8.0 \
  --cache-parameter-group-name <valkey-param-group> \
  --apply-immediately \
  --region <region>
```

Prerequisites:

- Single-node Redis OSS (cluster mode disabled) clusters must first be added to a replication group before performing the cross-engine upgrade. See [Creating a replication group using an existing cluster](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.CreatingReplGroup.ExistingCluster.html).
- If a custom cache parameter group is applied to the existing Redis OSS replication group, you must pass a custom Valkey cache parameter group with the same Redis OSS static parameter values (use `--cache-parameter-group-name`).

Benefits:

- Immediate 20% cost savings on node-based pricing
- Access to Valkey-specific features in future versions
- No-downtime, zero-data-loss process (from Redis OSS 5.0.6+)
- Can subsequently upgrade to Valkey 8.0 or 8.2 (8.2 required for vector search); Valkey 9.0 is the recommended target

### Cluster Mode Disabled to Cluster Mode Enabled (In-Place)

For Valkey 7.2+ and Redis OSS 7.0+ replication groups with automatic failover and at least one replica, you can convert from cluster mode disabled (CMD) to cluster mode enabled (CME) in-place without creating a new cluster. This is a **one-way operation** — once cluster mode is set to `enabled`, it cannot be disabled. CME→CMD conversion is not supported.

This is a two-step process:

1. Set cluster mode to `compatible` (allows both CMD and CME clients to connect)
2. Set cluster mode to `enabled` (CME only)

```bash
# Step 1: Enable compatible mode
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --cluster-mode compatible \
  --apply-immediately \
  --region <region>

# Wait for modification to complete, then:
# Step 2: Enable cluster mode
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --cluster-mode enabled \
  --apply-immediately \
  --region <region>
```

Prerequisites:

- Valkey 7.2+ or Redis OSS 7.0+
- Automatic failover enabled with at least one replica
- All keys must be in database 0 (DB 0)

**Important:** You can revert from `compatible` back to `disabled`, but once set to `enabled`, the change is **irreversible**. Test in a non-production environment first. For details on auth and ACL considerations during this migration, see `auth-migration.md`.

### Version Compatibility Matrix

| Source Engine | Source Version | Target Engine | Target Version | Method | Downtime |
|--------------|---------------|---------------|----------------|--------|----------|
| Redis OSS | 6.x | Redis OSS | 7.x | In-place upgrade | Zero (Multi-AZ) |
| Redis OSS | 7.x | Valkey | 7.2 | In-place engine switch | Zero (Multi-AZ) |
| Valkey | 7.2 | Valkey | 8.0 | In-place upgrade | Zero (Multi-AZ) |
| Valkey | 7.2 | Valkey | 8.2 | In-place upgrade | Zero (Multi-AZ) |
| Valkey | 8.0 | Valkey | 8.2 | In-place upgrade | Zero (Multi-AZ) |
| Redis OSS | 5.x | Redis OSS | 7.x | In-place (direct jump supported) | Zero (Multi-AZ, 5.0.6+); brief failover for older versions |
| Valkey | 7.2 | Redis OSS | 7.1 | In-place rollback | Zero (Multi-AZ) |
| Any | Any newer | Any | Any older | **Not supported** (except Valkey 7.2 to Redis OSS 7.1) | N/A |

Key rule: **Engine version downgrades are generally not supported.** You cannot roll back from 8.2 to 7.2 using an in-place operation. However, ElastiCache supports rolling back from Valkey 7.2 to Redis OSS 7.1 as a special case, using the same console, API, or CLI steps as an upgrade. This rollback is performed with zero downtime. Rollback from Valkey 8.0 or higher to Redis OSS is not supported. Always test upgrades in a non-production environment first.

### Extended Support for Older Redis OSS Versions

Redis OSS versions 4 and 5 will enter Extended Support on February 1, 2026 (end of standard support: January 31, 2026). Redis OSS v6 will enter Extended Support on February 1, 2027 (end of standard support: January 31, 2027). Running these versions past end of standard support incurs additional charges with escalating yearly premiums. Extended Support is available for up to 3 years. After Extended Support ends, AWS will attempt to upgrade caches still running those versions to a supported version of Valkey; if the upgrade fails, the cache may be deleted. We strongly recommend upgrading to Valkey or Redis OSS v6+ before the end of standard support.

### Rollback Considerations

General engine version downgrades are not supported, with one exception: ElastiCache supports rolling back from Valkey 7.2 to Redis OSS 7.1 using the same in-place process as an upgrade, with zero downtime. Requirements for this rollback:

- Only Valkey 7.2 to Redis OSS 7.1 is supported (even if you upgraded from an earlier version)
- Any user group and user associated with the replication group or serverless cache must be configured with engine type `REDIS`
- You can also restore a Valkey 7.2 snapshot as a Redis OSS 7.1 cache

For all other downgrade scenarios:

- **Before upgrading**: create a manual snapshot
- **If the upgrade causes issues**: restore the snapshot to a new cluster running the old version, update application endpoints, and decommission the upgraded cluster
- **For critical workloads**: run the new version in parallel (blue-green) and cut over only after validation

## Service Updates (Patching)

ElastiCache periodically releases service updates for security patches, bug fixes, and minor improvements.

### Self-Service Updates

Check for available updates:

```bash
aws elasticache describe-service-updates \
  --service-update-status available \
  --region <region>

# Check which clusters need an update
aws elasticache describe-update-actions \
  --service-update-name <update-name> \
  --update-action-status not-applied \
  --region <region>
```

Apply an update:

```bash
aws elasticache batch-apply-update-action \
  --replication-group-ids <cluster-id-1> <cluster-id-2> \
  --service-update-name <update-name> \
  --region <region>
```

### Auto-Apply Updates

Some service updates have an auto-apply date. If you do not apply them before that date, AWS applies them during your maintenance window.

- **Security updates**: typically auto-applied. Apply proactively during a convenient window.
- **Non-security updates**: may have a longer self-service window before auto-apply.

### Maintenance Windows

Node-based clusters have a configurable weekly maintenance window for auto-applied updates. Serverless caches do not have maintenance windows (updates are applied transparently with zero downtime).

Configure the maintenance window:

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --preferred-maintenance-window "sun:03:00-sun:04:00" \
  --region <region>
```

Best practices:

- Set the maintenance window to a low-traffic period
- Multi-AZ clusters experience zero downtime during patching (replicas are patched first, then a failover occurs)
- Single-node clusters experience brief downtime during patching (avoid single-node in production)
- Monitor the `describe-events` output after patching to confirm completion

### Serverless Updates

Serverless caches automatically apply the latest minor and patch software versions transparently, with no downtime and no action required from the operator. There is no maintenance window to configure. However, when a new major version is available, ElastiCache Serverless sends a notification and the operator must choose to upgrade by modifying the cache. Major version upgrades are also performed without downtime.

## Node Type Changes (Vertical Scaling)

### Online Vertical Scaling

For supported node type transitions, ElastiCache performs online scaling with zero downtime (Multi-AZ required).

```bash
# Check which node types you can scale to
aws elasticache list-allowed-node-type-modifications \
  --replication-group-id <cluster-id> \
  --region <region>

# Scale up (or down)
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --cache-node-type cache.r7g.xlarge \
  --apply-immediately \
  --region <region>
```

Process:

1. ElastiCache provisions new nodes with the target type
2. Syncs data to the new nodes
3. Performs DNS failover to the new nodes
4. Removes old nodes

Time: depends on data volume. Large datasets (100+ GB) can take 30 minutes or more.

### Node Type Change Constraints

- Not all transitions are supported. Use `list-allowed-node-type-modifications` to check.
- Scaling down may fail if the target node type has insufficient memory for the current dataset.
- Graviton (r7g, m7g, t4g) node types are recommended for best price-performance.
- Cross-family changes (e.g., r6g to r7g) are supported for most combinations.

### Serverless Scaling

Serverless caches scale automatically. There is no node type to change. Adjust `CacheUsageLimits` to control maximum capacity and cost:

```bash
aws elasticache modify-serverless-cache \
  --serverless-cache-name <name> \
  --cache-usage-limits '{
    "DataStorage": {"Maximum": 10, "Unit": "GB"},
    "ECPUPerSecond": {"Maximum": 15000}
  }' \
  --region <region>
```

## Operational Checklist

Before any upgrade or patching operation:

- [ ] Verify Multi-AZ and automatic failover are enabled (required for zero-downtime operations)
- [ ] Take a manual snapshot (safety net for rollback)
- [ ] Review release notes for the target version
- [ ] Test in a non-production environment
- [ ] Schedule during a low-traffic window
- [ ] Notify stakeholders of the planned change
- [ ] Monitor CloudWatch metrics during and after the operation
- [ ] Run `python3 scripts/security_audit.py` after completion to confirm posture
