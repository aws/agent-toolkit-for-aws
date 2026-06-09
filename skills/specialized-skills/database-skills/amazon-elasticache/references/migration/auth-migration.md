# Authentication Migration Runbooks

Step-by-step procedures for migrating between ElastiCache authentication models and cluster topologies.

## AUTH Token to RBAC Migration

Legacy AUTH token authentication uses a single shared password for all clients. RBAC provides per-user access control with fine-grained command and key permissions. This migration moves from the legacy model to the recommended model.

### Prerequisites

- Node-based replication group with `TransitEncryptionEnabled: true`
- Engine version Redis OSS 6.0 or higher, or Valkey 7.2 or higher (RBAC is not supported on earlier versions)
- AUTH token currently configured on the replication group
- Application code ready to switch to username/password authentication

### Step 1: Create RBAC Users

Create one or more RBAC users that match your application's access needs.

```bash
# Create an application user with full access
aws elasticache create-user \
  --user-id myapp-appuser \
  --user-name appuser \
  --engine <valkey|redis> \
  --access-string "on ~* +@all" \
  --authentication-mode Type=password,Passwords="<strong-password>" \
  --region <region>

# Create a read-only user for monitoring or reporting
aws elasticache create-user \
  --user-id myapp-readonly \
  --user-name readonly \
  --engine <valkey|redis> \
  --access-string "on ~* +@read" \
  --authentication-mode Type=password,Passwords="<strong-password>" \
  --region <region>
```

For IAM auth instead of passwords:

```bash
aws elasticache create-user \
  --user-id myapp-appuser \
  --user-name myapp-appuser \
  --engine <valkey|redis> \
  --access-string "on ~* +@all" \
  --authentication-mode Type=iam \
  --region <region>
```

Store RBAC passwords in Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name elasticache/myapp/appuser \
  --secret-string '{"username":"appuser","password":"<strong-password>"}' \
  --tags Key=Purpose,Value=elasticache-auth \
  --region <region>
```

### Step 2: Create User Group and Associate

```bash
# Create user group (must include the default user)
# Use --engine valkey for Valkey clusters or --engine redis for Redis OSS clusters.
aws elasticache create-user-group \
  --user-group-id myapp-usergroup \
  --engine valkey \
  --user-ids default myapp-appuser myapp-readonly \
  --region <region>

# Associate the user group with the replication group WITHOUT removing the AUTH token
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --user-group-ids-to-add myapp-usergroup \
  --region <region>
```

> **Note:** At this point, both AUTH token and RBAC credentials are active. Existing clients using the AUTH token continue to work.

### Step 3: Update Application to Use RBAC Credentials

Update application code to pass `username` and `password` (or IAM token) instead of just the AUTH token.

Before (AUTH token):

```python
client = valkey.Valkey(host=endpoint, port=6379, ssl=True, password=auth_token)
```

After (RBAC):

```python
client = valkey.Valkey(host=endpoint, port=6379, ssl=True,
                       username="appuser", password=rbac_password)
```

Deploy the updated application. Verify that it connects successfully using RBAC credentials.

### Step 4: Verify RBAC Connectivity

Before removing the AUTH token, verify that all clients are successfully authenticating via RBAC:

```bash
aws elasticache describe-replication-groups \
  --replication-group-id <cluster-id> \
  --region <region>

# Confirm the output shows:
# "AuthTokenEnabled": true,
# "UserGroupIds": ["myapp-usergroup"]
```

Confirm that the application works correctly with RBAC credentials and that no clients still depend on the AUTH token.

### Step 5: Remove AUTH Token

Now that all clients are using RBAC, remove the AUTH token:

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --auth-token-update-strategy DELETE \
  --apply-immediately \
  --region <region>
```

### Step 6: Verify AUTH Token Removal

Verify that the AUTH token is disabled:

```bash
aws elasticache describe-replication-groups \
  --replication-group-id <cluster-id> \
  --region <region>

# Confirm the output shows:
# "AuthTokenEnabled": false,
# "UserGroupIds": ["myapp-usergroup"]
```

### Step 7: Verify and Secure the Default User

The `default` user is always present in RBAC user groups. Disable it or restrict its access to prevent unauthenticated connections:

**For Valkey clusters:** The default user can be removed from the user group entirely, or disabled:

```bash
# Option A: Remove default user from the user group (Valkey only)
aws elasticache modify-user-group \
  --user-group-id myapp-usergroup \
  --user-ids-to-remove default \
  --region <region>

# Option B: Disable the default user (works for both Valkey and Redis OSS)
aws elasticache modify-user \
  --user-id default \
  --access-string "off ~* -@all" \
  --region <region>
```

**For Redis OSS clusters:** The default user **must** remain in the user group (Redis OSS requires it), but should be disabled:

```bash
# Disable the default user (required approach for Redis OSS)
aws elasticache modify-user \
  --user-id default \
  --access-string "off ~* -@all" \
  --region <region>
```

> **Note:** On Redis OSS, removing the default user from a user group will fail. On Valkey, the default user is optional in user groups, so removing it is the cleanest approach.

### Rollback Plan

If issues arise during migration:

1. **Before Step 5:** The AUTH token is still active. Simply revert application code to use AUTH token authentication and deploy. Both auth methods work simultaneously, so rollback is safe at any point before Step 5
2. **After Step 5:** The AUTH token has been removed. To roll back, re-set the AUTH token on the replication group, revert application code, and deploy
3. Remove the user group association if needed:

   ```bash
   aws elasticache modify-replication-group \
     --replication-group-id <cluster-id> \
     --user-group-ids-to-remove myapp-usergroup \
     --region <region>
   ```

## Cluster-Mode Disabled to Cluster-Mode Enabled Migration

Cluster-mode disabled uses a single shard (primary + replicas). Cluster-mode enabled uses multiple shards for horizontal scaling. This migration changes the endpoint model and requires client updates.

### Prerequisites

- Understand that cluster-mode enabled changes the client interaction model
- Client libraries must support `MOVED` and `ASK` redirect handling
- Multi-key commands must use hash tags to colocate keys on the same shard
- **For in-place migration:** Minimum engine version of Valkey 7.2 or Redis OSS 7.0 is required
- **For in-place migration:** Auto-failover must be enabled with at least 1 replica
- **For in-place migration:** The cluster may only have keys in database 0 (multiple databases are not supported)
- **For in-place migration:** CMD→CME is a one-way operation. Once cluster mode is set to `enabled`, it **cannot be reverted back to disabled**. You can only revert from `compatible` back to `disabled`

### Impact Assessment

| Aspect | Cluster-Mode Disabled | Cluster-Mode Enabled |
|--------|----------------------|---------------------|
| Shards | 1 | 1-500 (default limit: up to 90 nodes; 500 requires a limit increase and engine version 5.0.6+; versions below 5.0.6 limited to 250) |
| Max data | Limited by node memory | Distributed across shards |
| Endpoint | Single primary endpoint | Configuration endpoint (resolves to all shards) |
| Client | Standard client | Cluster-aware client required |
| Multi-key ops | Unrestricted | Keys must share a hash slot (use `{tag}`) |
| KEYS command | Works (not recommended) | Scoped to a single shard |

### Step 1: Assess Client Compatibility

Verify that all client applications can handle cluster mode:

| Runtime | Cluster-Aware Client |
|---------|---------------------|
| Python (valkey-py) | `valkey.cluster.ValkeyCluster` |
| Node.js (iovalkey) | `new Redis.Cluster([...])` |
| Java (Lettuce) | `RedisClusterClient.create(uri)` |
| Go (valkey-go) | Automatic (handles redirects natively) |
| CLI | `valkey-cli -c` |

Check for multi-key commands that span keys without hash tags:

- `MGET key1 key2` -- keys must be on the same shard
- `SUNION set1 set2` -- sets must be on the same shard
- Lua scripts accessing multiple keys -- all keys must be in the same slot
- `MULTI`/`EXEC` transactions -- all keys must be in the same slot

Fix: use hash tags like `{user:100}:profile` and `{user:100}:sessions` to ensure related keys land on the same shard.

### Step 2: Create a New Cluster-Mode Enabled Cluster

For Valkey 7.2+ or Redis OSS 7.0+, you can perform an in-place migration from cluster-mode disabled to cluster-mode enabled using the `modify-replication-group` CLI command (or `ModifyReplicationGroup` API). This is a two-step process: first set cluster mode to `compatible`, then to `enabled`. Requirements: auto-failover must be enabled with at least 1 replica, keys must exist only in database 0, and the migration is irreversible once set to `enabled` (you can revert from `compatible` back to `disabled`).

```bash
# Step 1: Set cluster mode to compatible
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --cache-parameter-group-name <cluster-enabled-parameter-group> \
  --cluster-mode compatible \
  --region <region>

# Wait for the cluster to become available, then update applications
# to use cluster protocol and the configuration endpoint.

# Step 2: Set cluster mode to enabled
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --cluster-mode enabled \
  --region <region>
```

> **Note:** In compatible mode, other modification operations such as scaling and engine version upgrades are not allowed. The cluster endpoints will change once cluster mode is set to enabled. Make sure to update your applications with the new endpoints.

For older engine versions (below Redis OSS 7.0), you must create a new cluster and migrate data.

```bash
# Create a new cluster-mode enabled replication group
aws elasticache create-replication-group \
  --replication-group-id <new-cluster-id> \
  --replication-group-description "Cluster-mode enabled migration target" \
  --engine valkey \
  --engine-version <version> \
  --cache-node-type <node-type> \
  --num-node-groups 3 \
  --replicas-per-node-group 1 \
  --cache-subnet-group-name <subnet-group> \
  --security-group-ids <sg-id> \
  --transit-encryption-enabled \
  --at-rest-encryption-enabled \
  --automatic-failover-enabled \
  --multi-az-enabled \
  --region <region>
```

### Step 3: Migrate Data

Option A: Snapshot and restore (brief downtime acceptable)

```bash
# Snapshot the old cluster
aws elasticache create-snapshot \
  --replication-group-id <old-cluster-id> \
  --snapshot-name migration-snapshot \
  --region <region>

# Restore to the new cluster (must delete the new cluster first, then recreate from snapshot)
# Note: restoring a snapshot from a cluster-mode disabled cluster into a cluster-mode enabled
# cluster requires the same number of node groups. Plan shard configuration carefully.
```

Option B: Dual-write migration (zero downtime)

1. Configure the application to write to both old and new clusters
2. Run a backfill to copy existing data from old to new (application-level copy)
3. Gradually shift reads to the new cluster
4. Stop writes to the old cluster
5. Decommission the old cluster

> **Warning:** Do NOT use DUMP/RESTORE for data migration between clusters. The serialization format is engine-version-specific and may produce corrupted data on version mismatches. Use application-level copy (read from source, write to target) or the ElastiCache online migration tools instead.
> **Note:** The ElastiCache online migration tool (`start-migration` / `complete-migration`) is designed exclusively for migrating data from self-hosted open-source Valkey or Redis OSS on Amazon EC2 to ElastiCache. It is **not** for moving data between ElastiCache clusters. Additionally, the target cluster must **not** have encryption in-transit enabled, must have Multi-AZ enabled, must not be part of a global datastore, must have data tiering disabled, and the number of shards in source and target must match. Online migration is not supported for ElastiCache serverless caches or clusters running on the r6gd node type. See the [Online Migration documentation](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/OnlineMigration.html) for details.

Option C: Online migration via ElastiCache (only if source is self-hosted Valkey/Redis on EC2, not an ElastiCache cluster)

```bash
# Ensure the target cluster does NOT have TLS enabled and meets all prerequisites above
aws elasticache start-migration \
  --replication-group-id <new-cluster-id> \
  --customer-node-endpoint-list Address=<self-hosted-endpoint>,Port=6379

# After data is in sync, finalize the migration:
aws elasticache complete-migration \
  --replication-group-id <new-cluster-id>
```

### Step 4: Update Application Endpoints

The new cluster uses a configuration endpoint that resolves to all shards. Update connection strings:

Before:

```python
client = valkey.Valkey(host="old-primary-endpoint", port=6379, ssl=True, ...)
```

After:

```python
client = valkey.cluster.ValkeyCluster(
    host="new-configuration-endpoint", port=6379, ssl=True, ...
)
```

### Step 5: Validate Application Behavior

- Verify all read and write operations succeed
- Check for `CROSSSLOT` errors (indicates multi-key operations on different shards)
- Monitor CloudWatch metrics for error rates, latency, and connection counts
- Run `valkey-cli -h <new-endpoint> -p 6379 --tls PING` for basic validation

### Rollback Plan

**For the in-place migration path (Valkey 7.2+/Redis OSS 7.0+):** Once cluster mode is set to `enabled`, the change is **irreversible** — you cannot convert back to cluster-mode disabled. You can only revert from `compatible` back to `disabled` before completing the final step. Take a snapshot before setting `enabled`.

**For the new-cluster migration path:** The old cluster remains running throughout the migration:

1. Revert application endpoints to the old cluster
2. Deploy the reverted application
3. Delete the new cluster-mode enabled cluster
4. No data loss (old cluster was never modified)

### Note on Endpoint Model Change

This migration changes the endpoint model:

- Cluster-mode disabled: single primary endpoint + single reader endpoint
- Cluster-mode enabled: configuration endpoint that the client uses to discover all shards

Applications must update their connection logic, not just the endpoint hostname. This is the most common source of issues during this migration.
