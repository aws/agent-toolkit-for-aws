# Aurora serverless — Worked Examples and Scale-to-Zero Rules

Companion to [instructions.md](serverless-advisory-instructions.md) and [formulas-and-examples.md](serverless-advisory-formulas-and-examples.md). The formulas and pricing tables used to produce these numbers live in [formulas-and-examples.md](serverless-advisory-formulas-and-examples.md).

## Worked example — basic sizing

User asks: db.r6g.xlarge, CPU P95 35%, max 72%, 500 GiB storage, should I switch to Aurora serverless? Region: us-east-1.

Agent reply should follow this pattern — present the script output, no derivation shown:

> "Loading `references/serverless-advisory-instructions.md` — this is the serverless sizing workflow.
>
> The command to run this analysis yourself from a machine with Python 3.10+ and boto3 installed:
>
> ```bash
> python3 scripts/acu_calculator.py estimate \
>   --instance db.r6g.xlarge --cpu-p95 35 --cpu-max 72 --storage 500 --region us-east-1
> ```
>
> Running that with your parameters produces:
>
> | Metric | Value |
> |---|---|
> | min ACU | 3.5 |
> | max ACU | 16.0 |
> | typical ACU | 6.0 |
> | Peak ACU vs 256 ceiling | Well under (12.0/256) |
>
> | Monthly cost | Amount |
> |---|---|
> | Provisioned db.r6g.xlarge compute | $379 |
> | Aurora serverless at typical ACU compute | $526 |
> | Aurora serverless total range (min–max, incl. storage) | $357–$1,452 |
> | Storage (500 GiB × $0.10) | $50 |
> | **Total Provisioned / Total Aurora serverless (typical)** | **$429 / $576** |
>
> **Recommendation: not_recommended.** At typical load, Aurora serverless is ~34% more expensive than provisioned ($576 vs $429). Your workload (P95 35%, max 72%) is steady — the burst/idle pattern that makes serverless win isn't present. Stay on db.r6g.xlarge. If you want the savings anyway, consider a 1-year RI on the provisioned instance (~30% off compute), which brings total to ~$315/mo."

Note what this reply does NOT include: no "0.21 × 4 × 4 = 3.36, round up to 3.5" arithmetic; no formula derivation; no "here's how I computed it." Just the script-style output.

(The internal formulas for producing these numbers are in [formulas-and-examples.md](serverless-advisory-formulas-and-examples.md). Use them to generate the output, but don't copy them into the reply.)

## Worked example — migration with connection and working-set constraints

User: db.r7g.2xlarge, 200 peak connections, 12 GiB working set, P95 40%, max 65%, 1 TB storage, region eu-west-1. Walk through the whole thing.

Agent response pattern (abridged):

1. Announce reference: "Loading `references/serverless-advisory-instructions.md`."
2. Print:

    ```bash
    python3 scripts/acu_calculator.py estimate \
      --region eu-west-1 \
      --instance db.r7g.2xlarge \
      --cpu-p95 40 --cpu-max 65 \
      --connections 200 --working-set 12 --storage 1000 \
      --num-instances 1 --format table
    ```

3. Script output (db.r7g.2xlarge, 8 vCPU): min_ACU **8.0** (working-set floor 12/2 = 6.0 is satisfied), peak_ACU **21.0**, max_ACU **27.5** (= max(round_up(21.0 × 1.30), round_up(13.5 × 1.50))), typical_ACU **13.5**.
4. Costs: offline/static mode prices at **us-east-1 rates** ($0.12/ACU-hr, $0.10/GiB-mo storage) regardless of `--region`; only live API mode applies the eu-west-1 rate. Aurora serverless typical 13.5 × $0.12 × 730 = **$1,183/mo compute**, storage 1000 × $0.10 = $100, total**$1,283/mo**. Provisioned r7g.2xlarge: $1.106 × 730 = $807 + $100 = **$907/mo**. Recommendation: **not_recommended** — serverless is ~41% more at this steady load.
5. Memory advisory: your 12 GiB working set means **min_ACU MUST be ≥ 6.0** to keep the hot set in memory. min_ACU=8 already satisfies this. If you set min below 6 you will see buffer-cache misses.
6. Migration approaches:
    - **In-place** (`modify-db-cluster --serverless-v2-scaling-configuration`): simplest, fastest; brief restart per instance. Caveats: cluster must already be r6+ generation.
    - **Blue/Green** (recommended for production): new Aurora serverless writer built as green environment, tested under live replication, switchover in <1 min. Best rollback path.
    - **Snapshot restore to a new cluster**: full rebuild; longest, but gives you a parallel cluster to test end-to-end.
7. Parameter group: MUST be an Aurora serverless-compatible parameter group (family `aurora-postgresql16` for PG16). DO NOT hardcode `shared_buffers` (Aurora resizes it with ACU). Note `max_connections` is derived from the cluster's **maximum** ACU (static; reboot to change), and `work_mem` is NOT Aurora-managed (user-tunable as on provisioned). Override only for well-understood special cases.
8. CloudFormation snippet (Aurora serverless writer):

    ```yaml
    ClusterParameterGroup:
      Type: AWS::RDS::DBClusterParameterGroup
      Properties:
        Family: aurora-postgresql16
        Description: Enforce TLS for Aurora serverless cluster
        Parameters:
          rds.force_ssl: "1"
    DBCluster:
      Type: AWS::RDS::DBCluster
      Properties:
        Engine: aurora-postgresql
        EngineVersion: "16.4"
        DBClusterParameterGroupName: !Ref ClusterParameterGroup
        ServerlessV2ScalingConfiguration:
          MinCapacity: 8.0
          MaxCapacity: 27.5
        StorageEncrypted: true
        EnableCloudwatchLogsExports:
          - postgresql
    WriterInstance:
      Type: AWS::RDS::DBInstance
      Properties:
        DBInstanceClass: db.serverless
        Engine: aurora-postgresql
        DBClusterIdentifier: !Ref DBCluster
    ```

9. CDK snippet (TypeScript):

    ```typescript
    const parameterGroup = new rds.ParameterGroup(this, "PG", {
      engine: rds.DatabaseClusterEngine.auroraPostgres({ version: rds.AuroraPostgresEngineVersion.VER_16_4 }),
      parameters: { "rds.force_ssl": "1" },
    });
    const cluster = new rds.DatabaseCluster(this, "Cluster", {
      engine: rds.DatabaseClusterEngine.auroraPostgres({ version: rds.AuroraPostgresEngineVersion.VER_16_4 }),
      parameterGroup,
      serverlessV2MinCapacity: 8.0,
      serverlessV2MaxCapacity: 27.5,
      writer: rds.ClusterInstance.serverlessV2("Writer"),
      storageEncrypted: true,
      cloudwatchLogsExports: ["postgresql"],
    });
    ```

10. Testing: snapshot-restore to a test cluster first; run full load tests at peak TPS; observe `ServerlessDatabaseCapacity` CloudWatch metric to verify ACU actually scales with load.

## Scale-to-zero / auto-pause rules

Aurora serverless auto-pause requires `MinCapacity: 0` and is **incompatible** with: RDS Proxy, logical replication (`wal_level=logical`), Global Database primary, Zero-ETL integrations, and Babelfish. If the user's workload has any of these, you MUST warn them that scale-to-zero cannot be enabled, and instead recommend a non-zero `MinCapacity` (e.g. 0.5 for dev/test, ≥1.0 for prod). In a multi-AZ cluster, auto-pause still works: the writer and any reader instances with failover priority 0 or 1 pause and resume together (their capacity is tied to the writer), while reader instances with failover priority 2-15 can pause independently. So a reader configured with priority 0/1 will not pause unless the writer also pauses — but the cluster as a whole can still scale to zero. See [concepts.md](serverless-advisory-concepts.md) for the complete compatibility matrix.
