# Migrating off Aurora Express Configuration

This file covers moving an Aurora Express Configuration cluster to Full Configuration — for example, when the workload outgrows the public-endpoint connectivity model, or when VPC isolation, customer-managed KMS keys, or customer-owned parameter groups become requirements. There is no in-place modify operation to move an express cluster into a VPC, so migration is a data-movement story. AWS documents snapshot/PITR restore from an express cluster to a full-configuration cluster (see "Restoring a cluster created through express configuration").

Express Configuration mechanics may evolve. Verify in the AWS User Guide before migrating, especially for production-adjacent clusters.

## In-place conversion

AWS provides no `modify-db-cluster` operation that flips an express cluster into a customer VPC — no "convert to VPC-attached Full Configuration" button or call. What AWS *does* document is restoring out of the express flow: a snapshot or point-in-time restore lands in a full-configuration VPC cluster by default. If AWS later publishes in-place conversion (a `modify` flag or wizard), update this file.

Pick the path that matches your cluster size, downtime tolerance, and connectivity:

- **Snapshot-and-restore** — simplest, widest applicability.
- **Logical replication** — lowest downtime; suitable when both clusters reach the same replication orchestrator.
- **pg_dump / pg_restore** — quickest for small datasets where a maintenance window is acceptable.

## Path 1: Snapshot and restore

Best for most migrations, especially with a short maintenance window.

1. Snapshot the Express cluster. Source: [Creating a DB cluster snapshot](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_CreateSnapshotCluster.html).
2. Stop application writes (writes after the snapshot are lost unless you add a logical-replication catch-up pass).
3. Restore the snapshot to a new Aurora PostgreSQL cluster in Full Configuration mode, in the target VPC and subnet group, with customer security groups, customer-managed KMS key, and customer parameter group as needed. Source: [Restoring from a DB cluster snapshot](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_RestoreFromSnapshot.html).
4. Validate the restored cluster — connectivity, extensions, roles, data integrity.
5. Update the application's connection string to the new endpoint.
6. Decommission the Express cluster once the new cluster is stable.

KMS: an Express cluster is encrypted at rest with an AWS owned key (SSE-RDS), which customers cannot view or manage. If the target must use a customer-managed KMS key, snapshot-and-restore with a key change is the standard Aurora pattern. Source: [Copying an encrypted snapshot to a different KMS key](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_CopySnapshot.html). Verify in the AWS User Guide.

Engine version: restore must target a version supported for restore from the source snapshot. The express flow applies the AWS default engine version; if the target needs a different major version, route the user to `aurora-upgrade-advisor` for post-restore upgrade planning.

Downtime scales with cluster size; the application is unavailable from when writes stop until cutover.

## Path 2: Logical replication

Best for migrations with strict downtime targets, typically production-adjacent workloads.

1. Create the target Full Configuration cluster in your VPC, with the desired engine version, parameter group, and KMS key.
2. Set up logical replication from the Express source to the target. Two mechanisms are common with Aurora PostgreSQL:
   - **PostgreSQL built-in logical replication** (PUBLICATION / SUBSCRIPTION, PostgreSQL 10+). Source: [PostgreSQL Logical Replication documentation](https://www.postgresql.org/docs/current/logical-replication.html).
   - **pglogical extension**. Source: [Using the pglogical extension on Aurora PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.Replication.Logical.html). Verify availability in the AWS User Guide.
3. Let the target catch up. Validate row counts, sequences, and non-replicated objects (DDL, large objects, certain extensions).
4. Cut over: stop source writes, wait for the target to reach the final LSN, then point the application at the target.
5. Decommission the Express cluster.

Prerequisites:

- **Connectivity**: the target must reach the Express cluster over its public endpoint (or vice versa), and your replication orchestrator must reach both. Because Express clusters sit behind the AWS-managed connectivity layer (not a customer VPC), network planning differs from VPC-to-VPC replication — verify in the AWS User Guide.
- **Version compatibility**: both clusters must run a PostgreSQL version that supports the chosen mechanism.
- **Parameters**: logical replication requires `wal_level = logical`, `max_replication_slots`, and `max_wal_senders` on the source. Whether the Express flow permits these changes is subject to change — verify in the AWS User Guide.

Downtime shrinks to the cutover moment (seconds to a few minutes), not the full data copy time.

## Path 3: pg_dump / pg_restore

Best for small datasets where a maintenance window is acceptable. Full steps, commands, and considerations: [migration-pgdump.md](express-create-migration-pgdump.md). Downtime is dump + restore time, scaling roughly linearly with data size; for anything larger than a dev dataset, Path 1 or Path 2 is usually better.

## Choosing a path

| Factor | Snapshot-and-restore | Logical replication | pg_dump / pg_restore |
|--------|----------------------|---------------------|----------------------|
| Cluster size | Any | Any | Small |
| Downtime tolerance | Minutes to hours | Seconds | Minutes to hours |
| Connectivity complexity | Low (AWS-managed) | Higher (orchestrator must reach both) | Medium (client must reach both) |
| KMS-key change | Natively supported via snapshot copy | Possible (target chooses its KMS key) | Possible (target chooses its KMS key) |
| Compliance fit | Good with a maintenance window | Good for production with strict downtime | Best for small/dev datasets |

When in doubt, start with Path 1: most broadly documented and fastest for most Express clusters (which tend to be small and dev-shaped).

## Verify before migrating

Before executing any path, verify in the AWS Aurora User Guide:

- Whether AWS has published an in-place conversion path, new migration tooling, or wizards since this file was written.
- AWS documents this explicitly — a default restore (`restore-db-cluster-from-snapshot` or `restore-db-cluster-to-point-in-time` without `EnableVPCNetworking`/`EnableInternetAccessGateway`) lands in a full-configuration VPC cluster; restoring back to express requires `VPCNetworkingEnabled=false` and `InternetAccessGatewayEnabled=true`. Verify the restore-target constraints (engine version, KMS, storage type).
- Whether the Express cluster's parameter group can be adjusted to enable logical replication (`wal_level = logical`, `max_replication_slots`, `max_wal_senders`).

Do not skip verification for production-adjacent clusters. The AWS User Guide is authoritative; this file is a planning aid.

## Source documentation

Links for each step appear inline above. Additional references:

- Create with express configuration: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html
- Aurora serverless: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html
