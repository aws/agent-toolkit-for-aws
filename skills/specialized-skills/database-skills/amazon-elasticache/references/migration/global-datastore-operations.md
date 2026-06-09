# Global Datastore Operations

Operational guide for setting up, managing, and upgrading ElastiCache Global Datastore for cross-region replication.

## Prerequisites

Global Datastore has specific requirements that must be met before creation:

* **Node-based only.** Serverless caches do not support Global Datastore.
* **Supported instance families:** M5, M6g, M7g, R5, R6g, R6gd, R7g, C7gn in size **large and above** only. Prior-generation instances (M4, R4) and burstable instances (t2, t3, t4g) are not supported.
* **Multi-AZ and automatic failover required** on the primary replication group.
* **Same node type, engine version, and primary node count** across all regions. Each cluster in the global datastore can have a different number of read replicas to accommodate read traffic local to that cluster. When creating a secondary, the node type is inferred from the primary and should not be specified.
* **Same engine and version** across all regions at the time of creation. Engine upgrades follow a specific ordering (see "Upgrading Engine Version" below).
* **Both cluster mode disabled (CMD) and cluster mode enabled (CME) are supported.** If using cluster-mode enabled, the number of shards must match across all clusters. Pub/sub propagation behavior differs between the two modes.
* **Transit encryption (TLS)** settings must match across all regions (all enabled or all disabled).
* **At-rest encryption** settings must also match across all regions (all enabled or all disabled).
* **IPv6 not supported.** Global datastores do not support Internet Protocol version 6 (IPv6).
* **Maximum of three regions**: one primary and up to two secondary regions. The exception is the China (Beijing) and China (Ningxia) regions, where replication can only occur between those two regions.
* **China region restriction:** In China, Global Datastore replication can only occur between the Beijing (cn-north-1) and Ningxia (cn-northwest-1) regions. Cross-region replication to or from regions outside China is not supported.

## Creating a Global Datastore

### Step 1: Create the Global Datastore from an Existing Primary

The primary replication group must already exist and be in `available` status.

```bash
aws elasticache create-global-replication-group \
  --global-replication-group-id-suffix my-global-ds \
  --primary-replication-group-id <primary-cluster-id> \
  --region <primary-region>
```

This registers the existing primary replication group as the primary member of the Global Datastore.

Wait for the Global Datastore status to become `available`:

```bash
aws elasticache describe-global-replication-groups \
  --global-replication-group-id ldgnf-my-global-ds \
  --region <primary-region>
```

Note: The full Global Datastore ID is prefixed with a short string derived from the primary region (e.g., `ldgnf-` for us-east-1). Use `describe-global-replication-groups` without the ID filter to discover the prefix if needed.

### Step 2: Add a Secondary Region

Create a replication group in the secondary region that joins the Global Datastore:

```bash
aws elasticache create-replication-group \
  --replication-group-id <secondary-cluster-id> \
  --replication-group-description "Secondary region for Global Datastore" \
  --global-replication-group-id ldgnf-my-global-ds \
  --cache-subnet-group-name <subnet-group-in-secondary-region> \
  --security-group-ids <sg-id-in-secondary-region> \
  --region <secondary-region>
```

Many parameters are inherited from the Global Datastore and must not be specified when creating a secondary, including: `PrimaryClusterId`, `AutomaticFailoverEnabled`, `NumNodeGroups`, `CacheParameterGroupName`, `CacheNodeType`, `Engine`, `EngineVersion`, `CacheSecurityGroupNames`, `EnableTransitEncryption`, `AtRestEncryptionEnabled`, `SnapshotArns`, and `SnapshotName`.

Monitor until the secondary reaches `available` and replication lag is minimal:

```bash
aws elasticache describe-global-replication-groups \
  --global-replication-group-id ldgnf-my-global-ds \
  --show-member-info \
  --region <primary-region>
```

## Removing a Secondary Region

Removing a secondary region is a two-step process: disassociate, then delete.

### Step 1: Disassociate the Secondary

```bash
aws elasticache disassociate-global-replication-group \
  --global-replication-group-id ldgnf-my-global-ds \
  --replication-group-id <secondary-cluster-id> \
  --replication-group-region <secondary-region> \
  --region <primary-region>
```

Wait for the disassociation to complete. The secondary becomes a standalone replication group in its region.

### Step 2: Delete or Retain the Secondary

After disassociation, the secondary is independent. Delete it if no longer needed:

```bash
aws elasticache delete-replication-group \
  --replication-group-id <secondary-cluster-id> \
  --final-snapshot-identifier <secondary-cluster-id>-final-$(date +%Y%m%d) \
  --region <secondary-region>
```

Or retain it as a standalone cluster in that region.

### Deleting the Global Datastore

To delete the Global Datastore itself, all secondaries must be disassociated first:

```bash
aws elasticache delete-global-replication-group \
  --global-replication-group-id ldgnf-my-global-ds \
  --retain-primary-replication-group \
  --region <primary-region>
```

Use `--retain-primary-replication-group` to keep the primary as a standalone cluster after disassociation. Use `--no-retain-primary-replication-group` to delete the primary replication group as part of the Global Datastore deletion. If you want to keep the primary, you must specify `--retain-primary-replication-group` explicitly.

## Upgrading Engine Version on Global Datastore

Engine upgrades must be performed on the Global Datastore object, not on individual members. See `upgrade-patching.md` for the version compatibility matrix and general upgrade procedures.

```bash
aws elasticache modify-global-replication-group \
  --global-replication-group-id ldgnf-my-global-ds \
  --engine-version 8.0 \
  --apply-immediately \
  --region <primary-region>
```

The key difference from standalone upgrades: you cannot upgrade individual member replication groups independently. The upgrade applies to secondary regions first, then to the primary region.

## Failover Between Regions

Use regional failover to promote a secondary to primary. This is used for disaster recovery or planned region migration.

> **Important:** ElastiCache does not support automatic cross-region failover. When needed, you must promote a secondary cluster manually.

```bash
aws elasticache failover-global-replication-group \
  --global-replication-group-id ldgnf-my-global-ds \
  --primary-region <current-secondary-region> \
  --primary-replication-group-id <current-secondary-cluster-id> \
  --region <current-primary-region>
```

After failover:

* The former secondary becomes the new primary (read-write).
* The former primary becomes the new secondary (read-only).
* Application writes must target the new primary region's endpoint.
* Update application connection strings or DNS to point to the new primary region.

Monitor failover progress:

```bash
aws elasticache describe-global-replication-groups \
  --global-replication-group-id ldgnf-my-global-ds \
  --show-member-info \
  --region <new-primary-region>
```

### Planned Failover vs Unplanned Scenarios

The `failover-global-replication-group` command performs a planned failover (both regions must be healthy). For unplanned scenarios where the primary region is unavailable:

1. Disassociate the secondary from the Global Datastore (this promotes it to a standalone primary).
2. Point applications to the promoted cluster.
3. When the original primary region recovers, assess data divergence before re-establishing replication.

## Node Type Changes on Global Datastore

Same principle as engine upgrades: modify the Global Datastore object, not individual members. See `upgrade-patching.md` for general node type change procedures.

```bash
aws elasticache modify-global-replication-group \
  --global-replication-group-id ldgnf-my-global-ds \
  --cache-node-type cache.r7g.xlarge \
  --apply-immediately \
  --region <primary-region>
```
