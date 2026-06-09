# Encryption Defaults

Node-based encryption gotchas and migration paths. Serverless encryption is always-on and requires no configuration (covered in create-secure-cache.md).

## Node-Based In-Transit Encryption (TLS)

- Best practice is to enable TLS at creation time via `TransitEncryptionEnabled: true`.
- For Redis OSS 7.0+ / Valkey 7.2+, TLS can be enabled post-creation via `modify-replication-group` with `--transit-encryption-enabled` and `--transit-encryption-mode preferred` (then switch to `required`). This is a three-step migration: (1) enable TLS in preferred mode, (2) update all clients to use TLS, (3) switch to required mode.
- For older engine versions, TLS cannot be added post-creation; the only option is snapshot-restore to a new cluster with TLS enabled.
- **Recommendation**: Always enable TLS at creation time to avoid the complexity of post-creation migration.

## Node-Based At-Rest Encryption (KMS)

- Enable via `AtRestEncryptionEnabled: true` at creation time.
- Cannot be changed after creation. A cluster created without at-rest encryption cannot have it added later.
- Uses default service-managed encryption at rest. To use a customer-managed KMS key, specify `KmsKeyId` at creation.
- **Warning**: If you delete or disable the KMS key (or revoke its grants) used to encrypt a cache, the cache becomes **irrecoverable**. AWS KMS deletes root keys only after a waiting period of at least seven days.
- **Recommendation**: Enable at creation time. Use a customer-managed KMS key if your compliance requirements mandate key control or key rotation policies beyond the service-managed defaults.

> **Valkey default:** For Valkey caches, `AtRestEncryptionEnabled` defaults to `true` if not explicitly specified. Redis OSS caches require it to be explicitly set.

## Migration Path for Unencrypted Node-Based Clusters

If an existing node-based cluster was created without encryption, the migration path depends on which encryption is missing.

### Adding In-Transit Encryption (TLS) to an Existing Cluster

For supported engine versions (Redis OSS 7.0+, Valkey 7.2+), you can enable TLS in three steps:

**Step 1: Enable TLS in preferred mode** (accepts both TLS and non-TLS connections)

```bash
aws elasticache modify-replication-group \
  --replication-group-id my-cluster \
  --transit-encryption-enabled \
  --transit-encryption-mode preferred \
  --apply-immediately \
  --region us-east-1
```

Wait for the modification to complete. During this phase, both encrypted and unencrypted connections are accepted.

> **Important**: DNS endpoints change during TLS migration. When switching to `preferred`, new TLS endpoints are generated. When switching to `required`, old non-TLS endpoints are deleted. Do not hardcode endpoints in your application. After each migration step completes, use `describe-replication-group` to retrieve the current endpoints.

#### Step 2: Update all clients to use TLS connections

Verify all application clients are configured with TLS before proceeding.

**Step 3: Switch to required mode** (only TLS connections accepted)

```bash
aws elasticache modify-replication-group \
  --replication-group-id my-cluster \
  --transit-encryption-mode required \
  --apply-immediately \
  --region us-east-1
```

For older engine versions that do not support `modify-replication-group` with transit encryption changes, the only option is:

1. Create a snapshot of the existing cluster.
2. Create a new cluster from the snapshot with `TransitEncryptionEnabled: true`.
3. Update application endpoints to point to the new cluster.
4. Delete the old cluster after validation.

### Adding At-Rest Encryption to an Existing Cluster

At-rest encryption cannot be enabled on an existing cluster. The migration path is:

1. Create a snapshot of the existing cluster.
2. Create a new cluster from the snapshot with `AtRestEncryptionEnabled: true`.
3. Update application endpoints to point to the new cluster.
4. Validate data integrity and application connectivity.
5. Delete the old cluster.

This requires a brief cutover window. Plan for:

- Snapshot creation time (depends on data size).
- New cluster creation time from snapshot.
- DNS or application configuration update.
- Validation period before decommissioning the old cluster.
