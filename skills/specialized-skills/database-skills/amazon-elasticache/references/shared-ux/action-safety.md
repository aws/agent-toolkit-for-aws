# Action Safety Guide

Safety semantics for destructive and high-impact ElastiCache operations. Every action that can cause data loss, downtime, or irreversible changes must follow the safeguards defined here.

## Safety Levels

| Risk Level | Definition | Required Safeguards |
|-----------|------------|---------------------|
| High | Data loss or significant downtime likely. Irreversible. | Explicit user confirmation. Final snapshot. Impact explanation. |
| Medium | Possible disruption or partial data impact. May be reversible with effort. | User confirmation. Recommend snapshot. Explain impact. |
| Low | Minimal risk. Fully reversible or non-destructive. | Inform the user. Proceed with standard confirmation. |

## Action Safety Matrix

### High Risk Actions

#### DELETE Cache (Serverless or Node-Based)

**Risk level:** High
**Reversibility:** Irreversible. All data is permanently deleted unless a final snapshot is taken.

**Required safeguards:**

1. **Always suggest a final snapshot before deletion.** Ensure the caller has `elasticache:CreateSnapshot` permission (or `elasticache:CreateServerlessCacheSnapshot` for serverless); without it, the API call will fail with an `Access Denied` exception.
2. Require explicit user confirmation with the cache name.
3. Warn that all data, connections, and endpoints will be destroyed.
4. Note that manual snapshots are retained after deletion, but **automatic cache snapshots are NOT retained**. A final snapshot or existing manual snapshot is the only recovery path.
5. Confirm the cache is not referenced by active applications.

**Implementation:**

> **Option A (recommended):** Use `--final-snapshot-identifier` on the delete call. This atomically creates a snapshot during deletion in a single step. Option B below creates a separate snapshot first, which is useful if you want to verify the snapshot before proceeding with deletion.

```bash
# Option A: Delete with atomic final snapshot (single step)
aws elasticache delete-replication-group \
  --replication-group-id my-cluster \
  --final-snapshot-identifier my-cluster-final-$(date +%Y%m%d-%H%M%S) \
  --region us-east-1
```

```bash
# Option B: Create snapshot first, verify, then delete (two steps)
# Step 1: Create and verify snapshot
aws elasticache create-snapshot \
  --replication-group-id my-cluster \
  --snapshot-name my-cluster-final-$(date +%Y%m%d-%H%M%S) \
  --region us-east-1

aws elasticache describe-snapshots \
  --snapshot-name my-cluster-final-<timestamp> \
  --region us-east-1

# Step 2: Delete without final snapshot (already taken above)
aws elasticache delete-replication-group \
  --replication-group-id my-cluster \
  --region us-east-1
```

For serverless:

```bash
aws elasticache delete-serverless-cache \
  --serverless-cache-name my-cache \
  --final-snapshot-name my-cache-final-$(date +%Y%m%d-%H%M%S) \
  --region us-east-1
```

---

#### FLUSHALL / FLUSHDB

**Risk level:** High
**Reversibility:** Irreversible. All keys in the database (FLUSHDB) or all databases (FLUSHALL) are permanently deleted.

**Required safeguards:**

1. **Warn about complete data loss.**
2. Suggest taking a snapshot before flushing.
3. Require explicit user confirmation.
4. Confirm this is intentional and not a cache invalidation scenario (where targeted `DEL` or TTL-based expiry is more appropriate).

**Guidance to present to the user:**

- FLUSHALL removes ALL data from ALL databases on the cache.
- FLUSHDB removes ALL data from the currently selected database.
- There is no undo. A snapshot taken before the operation is the only recovery path.
- For cache invalidation, consider using `DEL` for specific keys, `UNLINK` for async deletion, or TTL-based expiry instead.

---

#### Engine Upgrade (Major Version)

**Risk level:** High
**Reversibility:** Difficult. Downgrade is not supported in-place for major version changes, with one exception: Valkey 7.2 can be rolled back in-place to Redis OSS 7.1 (this is the documented cross-engine rollback path).

**Required safeguards:**

1. Flag compatibility concerns before proceeding.
2. Recommend testing the new engine version in a staging environment first.
3. Create a snapshot before the upgrade.
4. Check for deprecated commands or behavior changes in the target version.
5. Verify client library compatibility with the new engine version.
6. For Redis OSS to Valkey migration, versions 5.0.6+ support zero-downtime migration with Multi-AZ enabled; earlier versions are supported but may experience 30–60 seconds of failover during DNS propagation. Still recommend a snapshot.

**Implementation:**

```bash
# Step 1: Snapshot
aws elasticache create-snapshot \
  --replication-group-id my-cluster \
  --snapshot-name pre-upgrade-$(date +%Y%m%d) \
  --region us-east-1

# Step 2: Modify engine version (cross-engine upgrade to Valkey example)
aws elasticache modify-replication-group \
  --replication-group-id my-cluster \
  --engine valkey \
  --engine-version 8.0 \
  --cache-parameter-group-name my-valkey8-param-group \
  --apply-immediately \
  --region us-east-1
```

---

### Medium Risk Actions

#### Failover (Manual or Test)

**Risk level:** Medium
**Reversibility:** Reversible (fail back). Brief connectivity disruption during promotion.

**Required safeguards:**

1. Explain the impact: the primary will be demoted, a replica will be promoted, and clients will experience a brief disconnection (typically seconds).
2. Suggest performing during a maintenance window or low-traffic period.
3. Verify automatic failover is enabled and replicas are healthy before testing.
4. Confirm the application handles reconnection gracefully (cluster-aware clients, retry logic).

**Implementation:**

```bash
aws elasticache test-failover \
  --replication-group-id my-cluster \
  --node-group-id 0001 \
  --region us-east-1
```

---

#### Modify That Causes Downtime

**Risk level:** Medium
**Reversibility:** Varies by modification type.

Operations that may cause downtime or brief disruption:

- Changing node type (vertical scaling).
- Changing number of shards (horizontal scaling).
- Enabling cluster mode (migration from disabled to enabled via compatible mode; can be reverted from "compatible" back to "disabled", but cannot be reverted once set to fully "enabled").
- Changing engine version (minor or major).
- Changing at-rest encryption (requires creating a new cluster).
- Enabling in-transit encryption (can be done in-place via a two-step process: set transit encryption mode to `preferred`, then to `required`; no new cluster needed).

**Required safeguards:**

1. Flag that the modification may cause brief downtime or failover.
2. Explain the specific impact (e.g., "node type change triggers a rolling replacement with brief failover per shard").
3. Recommend applying during a maintenance window: `--no-apply-immediately` for non-urgent changes.
4. For production caches, suggest testing the modification in staging first.

---

#### Scale-Down (Node Type or Shard Count)

**Risk level:** Medium
**Reversibility:** Reversible (scale back up), but data loss is possible with Memcached.

**Required safeguards:**

1. **For Memcached**: Warn about data loss. Memcached has no persistence or replication. Scaling down removes nodes and their data permanently.
2. **For Valkey/Redis OSS node-based**: Data is redistributed during shard removal. Brief disruption during rebalancing. Verify sufficient memory on remaining shards.
3. **For serverless**: Scaling is automatic; manual scale-down is not applicable.
4. Verify the remaining capacity can handle the current data size and throughput.

---

#### Modify Security Group Rules

**Risk level:** Medium
**Reversibility:** Reversible by restoring previous rules.

**Required safeguards:**

1. Warn that removing inbound rules may immediately disconnect active clients.
2. Verify that any new rules maintain connectivity for all application clients.
3. Review changes before applying: removing a source security group reference will disconnect all clients in that security group.

---

### Low Risk Actions

#### Create Snapshot

**Risk level:** Low
**Reversibility:** Snapshot can be deleted. No impact on the running cache.

**Safeguards:**

- For node-based caches, snapshot creation uses the fork mechanism (or forkless save on newer engine versions such as Valkey 8.0+) and may cause brief memory spike on fork-based engines. Ensure `reserved-memory-percent` allows headroom.
- Snapshots incur S3 storage costs.

---

#### Modify Tags

**Risk level:** Low
**Reversibility:** Fully reversible. Tags can be added, changed, or removed at any time.

**Safeguards:**

- Inform the user that tag changes may affect cost allocation reports and IAM tag-based policies.

---

#### Describe / List Operations

**Risk level:** Low
**Reversibility:** Read-only. No state change.

**Safeguards:**

- None required. These are safe to run at any time.

---

#### Add Replicas

**Risk level:** Low
**Reversibility:** Replicas can be removed later.

**Safeguards:**

- Adding replicas triggers a sync from the primary. Initial sync may briefly impact primary performance for large datasets.
- Verify sufficient subnet IPs for new replicas.

---

#### Enable Log Delivery

**Risk level:** Low
**Reversibility:** Can be disabled at any time.

**Safeguards:**

- Warn about log delivery costs. Slow log and engine log output can be delivered to CloudWatch Logs or Kinesis Data Firehose (mutually exclusive destinations per log type). CloudWatch Logs ingestion costs can be significant for high-throughput caches.

## Never-Auto-Execute List

The following operations must **never** run without direct user confirmation in the current conversation turn, regardless of context, automation pipelines, scripted workflows, or IDE mode:

- Cache deletion (any type)
- FLUSHALL / FLUSHDB
- Snapshot deletion (especially the last/only snapshot for a cache)
- Credential or AUTH token changes on production caches
- Security group rule removal
- User or user group deletion
- Migration cutover execution
- Manual failover on production caches
