# Aurora serverless — Migration & Configuration

**This file advises on migration approaches — it never supplies runnable mutation commands.** The skill is assessment-only. Mutation actions belong in the customer's change-control process; this file describes the *console paths* and *flag names* so the customer (or their IaC stack) can execute them safely.

## Migration Approaches (three options)

### 1. In-Place Modification (minimal downtime)

Add an Aurora serverless reader, test under production traffic, failover to promote it, remove old instances. Steps, with their console path or flag name (never a runnable command):

1. **Add a serverless reader.** RDS console → Databases → your cluster → Actions → Add reader. Set the instance class to `db.serverless`. The underlying API is `create-db-instance` with `--db-instance-class db.serverless`, but run it through your IaC / change-control tool, not ad-hoc.
2. **Set scaling configuration.** RDS console → your cluster → Modify → Aurora serverless scaling configuration → set `MinCapacity` and `MaxCapacity` (typically 2 and your expected peak ACU). The underlying API is `modify-db-cluster` with `--serverless-v2-scaling-configuration MinCapacity=N,MaxCapacity=M`.
3. **Failover to promote the serverless reader.** RDS console → your cluster → Actions → Failover, choosing the serverless reader as the target. The underlying API is `failover-db-cluster` with `--target-db-instance-identifier`.
4. **Remove the old provisioned instance.** RDS console → your cluster → the old instance → Actions → Delete. The underlying API is `delete-db-instance`.

**Testing window.** Observe the serverless reader under production traffic for at least 24 hours before the failover. Monitor `ServerlessDatabaseCapacity` in CloudWatch to confirm ACU actually scales up under load.

### 2. Blue/Green Deployment (recommended for production)

Create a Blue/Green deployment. The green environment is a new cluster (pointed at a new Aurora serverless writer) built as a replica of blue. Test green under mirrored load, then switchover. Rollback is trivial — the blue environment is still intact until you explicitly delete it.

Console path: RDS console → Databases → your cluster → Actions → Create blue/green deployment. API endpoint (for reference, not to run ad-hoc): `create-blue-green-deployment`. Switchover API endpoint: `switchover-blue-green-deployment`. Both belong in your change-control workflow.

### 3. Snapshot Restore (cutover window, highest isolation)

Snapshot the provisioned cluster, restore to a new Aurora serverless cluster, validate end-to-end, then cutover application connections. Highest isolation and test fidelity; requires a maintenance window because the application cuts between two clusters.

Console path: RDS console → your cluster → Actions → Take snapshot → (wait) → Actions → Restore snapshot → set writer instance class to `db.serverless`. API endpoints: `create-db-cluster-snapshot`, `restore-db-cluster-from-snapshot`.

## Parameter Group Considerations (critical for Aurora serverless)

- Aurora serverless uses the **same parameter-group families** as provisioned (e.g., `aurora-postgresql16`).
- During scaling, Aurora serverless dynamically resizes `shared_buffers` and **IGNORES any custom value you set**. Remove explicit overrides of it before migrating — they will be ignored by the auto-scaling mechanism.
- `max_connections` does **NOT** scale up/down with ACU — Aurora holds it **CONSTANT**, derived from the **MAXIMUM ACU** (not current capacity), as a static parameter that requires a reboot to change. You may still customize it via a formula in a custom parameter group; if you do, prefer a formula tied to capacity rather than a fixed constant.
- Aurora PostgreSQL also computes these from the **MAXIMUM ACU** (like `max_connections`): `autovacuum_max_workers`, `autovacuum_vacuum_cost_limit`, `autovacuum_work_mem`, `effective_cache_size`, `maintenance_work_mem`.
- `work_mem` is **NOT** Aurora-managed — it behaves exactly as on a provisioned instance (inherited from the cluster parameter group, user-tunable). It does not auto-scale with ACU, so do not assume Aurora sizes it for you.
- Common pre-serverless overrides to remove are `shared_buffers`, `maintenance_work_mem`, `effective_cache_size` (the latter two are computed from the maximum ACU). `work_mem` is not auto-scaled and need not be removed.
- Custom parameters for logging, auth, or specific extensions can stay — they don't interact with ACU scaling.

## CloudFormation snippet (for IaC migration)

```yaml
Resources:
  ClusterParameterGroup:
    Type: AWS::RDS::DBClusterParameterGroup
    Properties:
      Family: aurora-postgresql16
      Description: Enforce TLS for Aurora serverless cluster
      Parameters:
        rds.force_ssl: "1"
  AuroraCluster:
    Type: AWS::RDS::DBCluster
    Properties:
      Engine: aurora-postgresql
      EngineVersion: "16.4"
      DBClusterParameterGroupName: !Ref ClusterParameterGroup
      ServerlessV2ScalingConfiguration:
        MinCapacity: 2
        MaxCapacity: 64
      StorageEncrypted: true
      EnableCloudwatchLogsExports:
        - postgresql
  WriterInstance:
    Type: AWS::RDS::DBInstance
    Properties:
      DBInstanceClass: db.serverless
      Engine: aurora-postgresql
      DBClusterIdentifier: !Ref AuroraCluster
```

The custom cluster parameter group enforces `rds.force_ssl=1` (use `require_secure_transport=ON` for Aurora MySQL). The Aurora PostgreSQL `default.*` parameter groups ship with `rds.force_ssl=0`, so a migration that reuses the default would silently drop the in-transit TLS requirement the skill mandates for production.

This is a **definition** of Aurora serverless infrastructure for your IaC stack (CloudFormation, Terraform, or CDK). Deploy it through your normal change-control process — this skill does not run CloudFormation for you.

## CDK (TypeScript) snippet

```typescript
const parameterGroup = new rds.ParameterGroup(this, 'PG', {
  engine: rds.DatabaseClusterEngine.auroraPostgres({
    version: rds.AuroraPostgresEngineVersion.VER_16_4,
  }),
  parameters: { 'rds.force_ssl': '1' },
});
const cluster = new rds.DatabaseCluster(this, 'Cluster', {
  engine: rds.DatabaseClusterEngine.auroraPostgres({
    version: rds.AuroraPostgresEngineVersion.VER_16_4,
  }),
  parameterGroup,
  serverlessV2MinCapacity: 2,
  serverlessV2MaxCapacity: 64,
  writer: rds.ClusterInstance.serverlessV2('writer'),
  readers: [
    rds.ClusterInstance.serverlessV2('reader', {
      scaleWithWriter: true,
    }),
  ],
  storageEncrypted: true,
  cloudwatchLogsExports: ['postgresql'],
});
```

This skill describes *what to do* and *where to do it*. It does not emit copy-pasteable mutation commands. If you need the exact CLI for a migration step, copy the API endpoint name from this file (e.g., `modify-db-cluster`) and build the command yourself from the AWS CLI reference — or use the console path described above. That keeps change-control in your team's hands, which is where it belongs.
