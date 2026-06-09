# Migration Rollback Procedures

Explicit rollback procedures for every supported migration path. Each procedure assumes the pre-cutover snapshot and the old environment are still available. The skill must reference these procedures during migration planning and present the relevant rollback plan to the user before cutover.

## General Rollback Principles

1. **Never decommission the source** until the validation period ends (minimum 48-72 hours post-cutover).
2. **Always create a snapshot** of the target immediately before cutover so you have a recovery point for the new environment as well.
3. **DNS or connection-string rollback** is the fastest path back. Use DNS TTLs of 60 seconds or less during migration windows.
4. **Data verification** must pass before and after any rollback to confirm consistency.

---

## Rollback: Redis OSS to Valkey (In-Place Engine Upgrade)

**Migration type:** In-place engine switch via `modify-replication-group`. The Valkey 7.2 to Redis OSS 7.1 rollback is zero-downtime and preserves the endpoint IP address. (Note: the 30-60 second failover caveat applies to forward upgrades from Redis OSS versions earlier than 5.0.6, not to this rollback path.)

**Preferred rollback method:** ElastiCache supports rolling back from Valkey 7.2 to Redis OSS 7.1 in-place using `modify-replication-group` (or `modify-serverless-cache` for serverless). You can perform a rollback using the same API/CLI steps as an engine upgrade, specifying Redis OSS 7.1 as the target engine version. The rollback is zero-downtime and preserves the endpoint IP address. Only Valkey 7.2 to Redis OSS 7.1 is supported, even if you originally upgraded from an earlier Redis OSS version. Any user group and user associated with the replication group must be configured with engine type `REDIS` for the rollback to work. If a custom parameter group is in use, a compatible Redis OSS parameter group must be provided.

**Alternative rollback method:** You can also restore a snapshot created from your Valkey 7.2 cache as a Redis OSS 7.1 cache by specifying Redis OSS 7.1 as the target engine version during restore. This creates a new cache from the snapshot and does not affect the Valkey cache.

**Note:** This section covers node-based (replication group) rollback. For serverless caches, use `modify-serverless-cache` with `--engine redis --major-engine-version 7` for in-place rollback, or restore a serverless cache snapshot specifying Redis OSS 7.1 as the target engine.

### Pre-Cutover Preparation

1. Create a manual snapshot before starting the engine switch:

   ```bash
   aws elasticache create-snapshot \
     --replication-group-id <cluster-id> \
     --snapshot-name pre-valkey-upgrade-$(date +%Y%m%d-%H%M%S) \
     --region <region>
   ```

2. Record the current engine, engine version, node type, parameter group, and security group configuration.
3. Confirm the snapshot status is `available` before proceeding with the upgrade.

### Rollback Steps

#### Option A: In-Place Rollback (Preferred, Zero Downtime)

1. **Roll back the engine in-place** using `modify-replication-group`:

   ```bash
   aws elasticache modify-replication-group \
     --replication-group-id <cluster-id> \
     --engine redis \
     --engine-version 7.1 \
     --region <region>
   ```

   For serverless caches, use:

   ```bash
   aws elasticache modify-serverless-cache \
     --serverless-cache-name <cache-name> \
     --engine redis \
     --major-engine-version 7
   ```

2. **Wait for the rollback to complete.** Monitor the replication group status until it returns to `available`. The endpoint IP address and all other aspects of the application will not change.

3. **Verify data integrity** and application behavior (see verification steps below).

**Requirements for in-place rollback:**

* Only Valkey 7.2 to Redis OSS 7.1 is supported (even if you upgraded from an earlier version).
* Any user group and user associated with the replication group must be configured with engine type `REDIS`.
* If a custom parameter group is in use, provide a compatible Redis OSS parameter group via `--cache-parameter-group-name`.

#### Option B: Snapshot Restore (Fallback)

Use this approach if in-place rollback is not possible (e.g., user group engine type issues).

1. **Stop application traffic** to the upgraded (Valkey) cluster if possible, or prepare to redirect traffic.

2. **Restore the pre-upgrade snapshot** to a new replication group running Redis OSS:

   ```bash
   aws elasticache create-replication-group \
     --replication-group-id <cluster-id>-rollback \
     --replication-group-description "Rollback from Valkey to Redis OSS" \
     --engine redis \
     --engine-version 7.1 \
     --cache-node-type <original-node-type> \
     --snapshot-name pre-valkey-upgrade-<timestamp> \
     --num-cache-clusters 2 \
     --transit-encryption-enabled \
     --automatic-failover-enabled \
     --multi-az-enabled \
     --cache-subnet-group-name <subnet-group> \
     --security-group-ids <sg-id> \
     --region <region>
   ```

3. **Wait for the new cluster** to reach `available` status:

   ```bash
   aws elasticache describe-replication-groups \
     --replication-group-id <cluster-id>-rollback \
     --query "ReplicationGroups[0].Status" \
     --region <region>
   ```

4. **Verify data integrity** on the restored cluster:
   * Compare `DBSIZE` with the expected key count from before the upgrade.
   * Spot-check a sample of keys to confirm values match.

5. **Update application connection strings** (or DNS) to point to the restored cluster's endpoint.

6. **Validate application behavior:**
   * Confirm reads and writes succeed.
   * Check latency is within expected range.
   * Monitor error rates in application logs.

7. **Decommission the Valkey cluster** after the validation period:

   ```bash
   aws elasticache delete-replication-group \
     --replication-group-id <cluster-id> \
     --final-snapshot-identifier <cluster-id>-final-$(date +%Y%m%d) \
     --region <region>
   ```

### Data Gap Consideration

**If using in-place rollback (Option A):** No data loss occurs. The rollback preserves all data on the cluster.

**If using snapshot restore (Option B):** Any writes that occurred between the pre-upgrade snapshot and the rollback will be lost. To minimize data loss:

* Keep the migration window as short as possible.
* If the Valkey cluster is still running, consider exporting recent keys before restoring the snapshot.

### Rollback Limitations

* ElastiCache only supports rolling back from Valkey 7.2 to Redis OSS 7.1. This is true even if you upgraded to Valkey 7.2 from an earlier version than Redis OSS 7.1.
* Any user group and user associated with the replication group or serverless cache being rolled back must be configured with engine type `REDIS`.
* If a custom parameter group is applied, a compatible Redis OSS parameter group must be provided during rollback.

---

## Rollback: Self-Managed Redis to ElastiCache

**Migration type:** Replication-based (online) or snapshot-based (offline) migration to an ElastiCache replication group or serverless cache.

**Rollback advantage:** The self-managed Redis source is still running during migration. Rollback is straightforward because the source was never modified.

**Prerequisite note:** Online migration requires the target ElastiCache cluster to have transit encryption (TLS) disabled. If transit encryption was enabled on the target, online migration cannot be used; use backup/restore instead. See `topology-validation.md` for the full prerequisites checklist.

### Pre-Cutover Preparation

1. **Keep the self-managed Redis instance running** throughout the migration and validation period.
2. Create a snapshot of the ElastiCache target before cutover:

   ```bash
   aws elasticache create-snapshot \
     --replication-group-id <target-cluster> \
     --snapshot-name pre-cutover-$(date +%Y%m%d-%H%M%S) \
     --region <region>
   ```

3. Record the current application connection strings and DNS entries.
4. Set DNS TTL to 60 seconds or less if using DNS-based endpoint switching.

### Rollback Steps

1. **Revert application connection strings** to point back to the self-managed Redis endpoint.
   * If using DNS: update the DNS record to the self-managed Redis IP/hostname.
   * If using config files or environment variables: deploy with the old connection string.

2. **Deploy the reverted application** across all instances/containers.

3. **Verify connectivity** to the self-managed Redis:

   ```bash
   valkey-cli -h <self-managed-host> -p 6379 --tls PING  # omit --tls if TLS is not enabled on the source
   ```

4. **Verify data integrity:**
   * Confirm `DBSIZE` matches expectations.
   * Spot-check key values.
   * Verify that writes during the cutover window are present (if the source was still receiving writes via dual-write).

5. **Handle data written only to ElastiCache during cutover:**
   * If the application wrote exclusively to ElastiCache after cutover, those writes are not on the self-managed source.
   * For critical data, export those keys from ElastiCache before decommissioning:

     ```bash
     # Export individual keys via application-level read/write, or create a snapshot for bulk recovery
     aws elasticache create-snapshot \
       --replication-group-id <target-cluster> \
       --snapshot-name post-cutover-backup-$(date +%Y%m%d) \
       --region <region>
     ```

6. **Stop the ElastiCache migration** if it is still in progress: call `complete-migration` with the `--force` flag to stop replication from the source without waiting for sync to finish:

   ```bash
   aws elasticache complete-migration \
     --replication-group-id <target-cluster> \
     --force \
     --region <region>
   ```

   Alternatively, delete the target replication group to cancel entirely:

   ```bash
   aws elasticache delete-replication-group \
     --replication-group-id <target-cluster> \
     --no-retain-primary-replication-group \
     --final-snapshot-identifier <target-cluster>-rollback-$(date +%Y%m%d) \
     --region <region>
   ```

7. **Keep or delete the ElastiCache target** based on whether you plan to retry the migration later.

---

## Rollback: Node-Based to Serverless

**Migration type:** New serverless cache created, data migrated via dual-write or snapshot-restore, then cutover.

**Rollback advantage:** The original node-based cluster remains running during migration.

### Pre-Cutover Preparation

1. **Keep the node-based cluster running** until the validation period ends.
2. Create a snapshot of the node-based cluster before cutover:

   ```bash
   aws elasticache create-snapshot \
     --replication-group-id <node-based-cluster> \
     --snapshot-name pre-serverless-cutover-$(date +%Y%m%d-%H%M%S) \
     --region <region>
   ```

3. Document the differences between node-based and serverless that affect the application:
   * Auth model: serverless requires RBAC (AUTH tokens not supported).
   * TLS: serverless always has TLS enabled.
   * Port: serverless uses port 6379 with mandatory TLS (different from node-based where TLS may be optional).
   * Endpoint format: serverless endpoints use `<cache-name>-xxxxx.serverless.<region-code>.cache.amazonaws.com` (where `<region-code>` is an abbreviated form, e.g., `use1` for us-east-1).
   * Cluster mode: serverless operates in cluster-mode-enabled only. Clients must support cluster protocol (MOVED/ASK redirects). When rolling back to node-based CMD, clients that were updated for cluster mode may need to revert to non-cluster connection handling.

### Rollback Steps

1. **Revert application auth configuration:**
   * If the application was updated from AUTH token to RBAC for serverless, revert to AUTH token auth for the node-based cluster.
   * If the application already used RBAC, revert the endpoint only.

2. **Revert application connection strings** to the node-based cluster endpoint:

   ```python
   # Revert from serverless endpoint
   # client = valkey.Valkey(host="<cache-name>-xxxxx.serverless.use1.cache.amazonaws.com", port=6379, ssl=True, username="appuser", password=pw)

   # Back to node-based endpoint
   client = valkey.Valkey(host="node-based-primary-endpoint", port=6379, ssl=True, password=auth_token)
   ```

3. **Revert TLS configuration** if the node-based cluster does not use TLS:
   * Remove `ssl=True` from client configuration if the original cluster did not have transit encryption enabled.

4. **Deploy the reverted application.**

5. **Verify data on the node-based cluster:**
   * Confirm `DBSIZE` matches expectations.
   * Verify that data written only to serverless during the cutover window is handled (export or accept loss).

6. **Delete the serverless cache** after validation:

   ```bash
   aws elasticache delete-serverless-cache \
     --serverless-cache-name <serverless-cache> \
     --final-snapshot-name <serverless-cache>-final-$(date +%Y%m%d) \
     --region <region>
   ```

### Auth Rollback Detail

If you changed from AUTH token to RBAC as part of the serverless migration:

1. The node-based cluster should still accept AUTH token connections (if you did not remove the AUTH token).
2. Revert application code to use `password=auth_token` without a `username`.
3. See `references/migration/auth-migration.md` for the full AUTH-to-RBAC rollback procedure.

---

## Rollback: Serverless to Node-Based

**Migration type:** New node-based cluster created, data migrated via dual-write or snapshot-restore, then cutover.

**Rollback advantage:** The original serverless cache remains running during migration.

### Pre-Cutover Preparation

1. **Keep the serverless cache running** until the validation period ends.
2. Create a manual snapshot of the serverless cache before cutover using `CreateServerlessCacheSnapshot`:

   ```bash
   aws elasticache create-serverless-cache-snapshot \
     --serverless-cache-name <serverless-cache> \
     --serverless-cache-snapshot-name pre-node-cutover-$(date +%Y%m%d-%H%M%S)
   ```

3. Document the configuration differences for rollback:
   * Auth model: serverless uses RBAC; node-based may use AUTH token or RBAC.
   * TLS: serverless always has TLS; node-based may or may not.
   * Endpoint: serverless endpoint format differs from node-based.

### Rollback Steps

1. **Revert application connection strings** to the serverless cache endpoint:

   ```python
   # Revert from node-based endpoint
   # client = valkey.Valkey(host="node-based-primary-endpoint", port=6379, ssl=True, password=auth_token)

   # Back to serverless endpoint
   client = valkey.Valkey(host="<cache-name>-xxxxx.serverless.use1.cache.amazonaws.com", port=6379, ssl=True, username="appuser", password=rbac_password)
   ```

2. **Revert auth configuration** if you switched from RBAC to AUTH token:
   * Restore `username` parameter in client configuration.
   * Use RBAC credentials instead of AUTH token.

3. **Ensure TLS is enabled** in client configuration (`ssl=True`), since serverless requires it.

4. **Deploy the reverted application.**

5. **Verify connectivity and data:**

   ```bash
   valkey-cli -h <serverless-endpoint> -p 6379 --tls PING
   ```

   * Confirm reads and writes succeed.
   * Check latency is within the expected serverless range (single-digit ms).

6. **Delete the node-based cluster** after the validation period:

   ```bash
   aws elasticache delete-replication-group \
     --replication-group-id <node-based-cluster> \
     --final-snapshot-identifier <node-based-cluster>-final-$(date +%Y%m%d) \
     --region <region>
   ```

---

## Rollback Verification Checklist

After completing any rollback, run through this checklist:

* [ ] Application is connected to the original (pre-migration) cache endpoint
* [ ] Authentication is working (correct auth model, credentials, username if RBAC)
* [ ] TLS configuration matches the original cache (enabled/disabled)
* [ ] `DBSIZE` matches expected key count
* [ ] Spot-check: sample keys return correct values
* [ ] Application read and write latency is within normal range
* [ ] No connection errors in application logs
* [ ] CloudWatch metrics on the original cache show healthy traffic
* [ ] Security audit passes: `python3 scripts/security_audit.py --replication-group <name>` or `--serverless <name>`
* [ ] Stakeholders notified of the rollback
* [ ] Post-mortem scheduled to analyze why the migration failed

## When Rollback Is Not Possible

In rare cases, rollback may not be straightforward:

* **Source was already decommissioned.** This is why the skill enforces keeping the source running during the validation period.
* **Data diverged significantly.** If the application wrote different data to source and target for an extended period, merging is complex. Use the ElastiCache snapshot as the recovery point and accept data written only to the source as lost.
* **Auth model was changed on the original cluster.** If you modified the original cluster's auth configuration (e.g., removed AUTH token) as part of migration prep, restoring auth requires reconfiguring the original cluster or restoring from snapshot.

In all cases, the pre-cutover snapshot provides a recovery point. The skill must confirm a snapshot exists before allowing cutover to proceed.
