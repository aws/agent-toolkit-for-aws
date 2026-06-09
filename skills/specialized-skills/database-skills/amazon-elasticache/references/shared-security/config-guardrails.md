# AWS Config Guardrails for ElastiCache

Use AWS Config rules to continuously audit ElastiCache deployments for security and operational compliance. These rules detect configuration drift and non-compliant resources.

## Managed Rules

**Note:** These managed Config rules evaluate only node-based replication groups (`AWS::ElastiCache::ReplicationGroup`). They do not apply to ElastiCache Serverless caches. Serverless caches always have encryption (at-rest and in-transit) enabled by default and have built-in Multi-AZ with automatic failover, so these rules are not needed for serverless deployments.

### elasticache-repl-grp-auto-failover-enabled

**What it checks**: Node-based replication groups have automatic failover enabled.

**Why it matters**: Without automatic failover, a primary node failure requires manual intervention to promote a replica, causing extended downtime.

**Remediation**:

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-name> \
  --automatic-failover-enabled \
  --multi-az-enabled \
  --apply-immediately \
  --region <region>
```

Note: Automatic failover requires at least one replica per shard. If the cluster has no replicas, add replicas first. Also enable Multi-AZ (`--multi-az-enabled`) for automatic failover to provide meaningful HA; without Multi-AZ, the primary and replica may be in the same AZ, reducing fault tolerance.

### elasticache-repl-grp-encrypted-at-rest

**What it checks**: Node-based replication groups have at-rest encryption enabled.

**Why it matters**: Without at-rest encryption, data on disk (snapshots, swap files) is stored in plaintext. This is a compliance finding for most security frameworks (SOC 2, HIPAA, PCI DSS).

**Remediation**: At-rest encryption cannot be enabled on an existing cluster. The remediation path is:

1. Create a new replication group with `AtRestEncryptionEnabled: true`
2. Migrate data from the old cluster to the new one (snapshot-restore or dual-write)
3. Decommission the old cluster

For new clusters, always set `AtRestEncryptionEnabled: true` in the template.

### elasticache-repl-grp-encrypted-in-transit

**What it checks**: Node-based replication groups have in-transit encryption (TLS) enabled.

**Why it matters**: Without TLS, data travels in plaintext between clients and the cache, and between primary and replica nodes. Susceptible to eavesdropping.

**Remediation**: For clusters created without TLS, the remediation depends on engine version:

**Redis OSS 7.0+ / Valkey 7.2+:** In-place TLS enablement is supported. Migrate in three steps:

1. Set `TransitEncryptionEnabled: true` with `TransitEncryptionMode: preferred` (allows both TLS and plaintext clients)
2. Update all application clients to use TLS (`ssl=True` / `tls: {}`)
3. Set `TransitEncryptionMode: required` to enforce TLS-only

**Older engine versions (Redis OSS < 7.0):** Cluster recreation is required:

1. Create a new replication group with `TransitEncryptionEnabled: true`
2. Update application clients to use TLS
3. Migrate data and cut over
4. Decommission the old cluster

## Custom Rules

### RBAC Auth Enabled (custom rule concept)

**What it checks**: Replication groups or serverless caches have a user group associated (not relying solely on the default user with no password).

**Implementation**: Custom Config rule Lambda. Logic: call `describe_replication_groups` or `describe_serverless_caches`, check `UserGroupIds` (node-based) or `UserGroupId` (serverless) is non-empty. For node-based clusters, also check `AuthTokenEnabled`; clusters using AUTH tokens have a valid authentication method even without user groups. Note: `AuthTokenEnabled` is only available in the `describe_replication_groups` response; the `describe_serverless_caches` API does not return this field, so for serverless the check is limited to user group association. COMPLIANT if a user group is associated or AUTH token is enabled (node-based only), NON_COMPLIANT otherwise.

**Remediation**:

```bash
aws elasticache modify-serverless-cache \
  --serverless-cache-name <cache-name> \
  --user-group-id <user-group-id> --region <region>

aws elasticache modify-replication-group \
  --replication-group-id <cluster-name> \
  --user-group-ids-to-add <user-group-id> --region <region>
```

### Engine Version Compliance (custom rule concept)

**What it checks**: ElastiCache clusters run a minimum required engine version (e.g., Valkey 7.2+ or Redis OSS 7.0+ for IAM auth, Valkey 8.2 or above for vector search on node-based clusters).

**Implementation**: Custom Config rule Lambda. Logic: call `describe_replication_groups`, get a member cluster via `describe_cache_clusters`, compare `EngineVersion` against a `minimumVersion` rule parameter (default `7.2`). Use `packaging.version.parse` for comparison.

**Remediation**:

```bash
# For clusters already running Valkey, upgrade the version:
aws elasticache modify-replication-group \
  --replication-group-id <cluster-name> \
  --engine-version 7.2 \
  --apply-immediately --region <region>

# For clusters running Redis OSS, specify --engine valkey to switch engines.
# WARNING: This performs an engine migration from Redis OSS to Valkey, not just a
# version upgrade. Test in a non-production environment first. See valkey-migration-guide.md.
aws elasticache modify-replication-group \
  --replication-group-id <cluster-name> \
  --engine valkey --engine-version 7.2 \
  --apply-immediately --region <region>
```

## Deploying Config Rules

### CloudFormation for managed rules

```yaml
Resources:
  AutoFailoverRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: elasticache-auto-failover-enabled
      Source:
        Owner: AWS
        SourceIdentifier: ELASTICACHE_REPL_GRP_AUTO_FAILOVER_ENABLED
      Scope:
        ComplianceResourceTypes:
          - AWS::ElastiCache::ReplicationGroup

  EncryptedAtRestRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: elasticache-encrypted-at-rest
      Source:
        Owner: AWS
        SourceIdentifier: ELASTICACHE_REPL_GRP_ENCRYPTED_AT_REST
      Scope:
        ComplianceResourceTypes:
          - AWS::ElastiCache::ReplicationGroup

  EncryptedInTransitRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: elasticache-encrypted-in-transit
      Source:
        Owner: AWS
        SourceIdentifier: ELASTICACHE_REPL_GRP_ENCRYPTED_IN_TRANSIT
      Scope:
        ComplianceResourceTypes:
          - AWS::ElastiCache::ReplicationGroup
```

### CloudFormation for custom rules

> **Note:** The `RBACCheckFunction` Lambda is not defined in the snippet below. You must define it separately as an `AWS::Lambda::Function` resource (or import its ARN) with the custom Config rule evaluation logic described in the "RBAC Auth Enabled" section above. Grant Config permission to invoke it via an `AWS::Lambda::Permission` resource with `Principal: config.amazonaws.com`.

```yaml
Resources:
  RBACAuthRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: elasticache-rbac-auth-enabled
      Source:
        Owner: CUSTOM_LAMBDA
        SourceIdentifier: !GetAtt RBACCheckFunction.Arn
        SourceDetails:
          - EventSource: aws.config
            MessageType: ConfigurationItemChangeNotification
      Scope:
        ComplianceResourceTypes:
          - AWS::ElastiCache::ReplicationGroup
          - AWS::ElastiCache::ServerlessCache
```

## Summary of Rules

| Rule | Type | Checks | Remediation complexity |
|------|------|--------|----------------------|
| `elasticache-repl-grp-auto-failover-enabled` | Managed | Automatic failover on | Low (modify in place) |
| `elasticache-repl-grp-encrypted-at-rest` | Managed | At-rest encryption on | High (requires cluster recreation) |
| `elasticache-repl-grp-encrypted-in-transit` | Managed | TLS on | Medium (in-place for Redis OSS 7.0+/Valkey 7.2+; recreation for older versions) |
| `elasticache-rbac-auth-enabled` | Custom | RBAC user group associated | Medium (create and associate user group) |
| Engine version compliance | Custom | Minimum engine version | Medium (in-place version upgrade) |
