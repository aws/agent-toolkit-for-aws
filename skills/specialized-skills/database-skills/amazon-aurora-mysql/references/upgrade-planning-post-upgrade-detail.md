# Post-Upgrade Validation — detailed procedures

Companion to [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md). These are the detailed Aurora MySQL post-upgrade procedures referenced there. Surface them alongside the four Aurora-specific items.

## Statistics refresh (CRITICAL)

A major-version upgrade does NOT recompute table statistics, and stale statistics against the new optimizer are a top cause of post-upgrade plan regressions. You MUST refresh statistics before trusting query plans post-upgrade:

- Run `ANALYZE TABLE` on hot tables to rebuild index/column statistics for the new optimizer.

    ```sql
    ANALYZE TABLE critical_table_1, critical_table_2;
    ```

- `OPTIMIZE TABLE` is more aggressive (it rebuilds the table and reclaims fragmentation) but takes a table lock — avoid on production unless you specifically need to defragment, and run it in a maintenance window.

## Plugin / component checks (Aurora MySQL)

Aurora MySQL has no PostgreSQL-style extension catalog to update post-upgrade, but verify any server components or audit plugins are still loaded and compatible with the new major version:

```sql
-- confirm expected plugins are ACTIVE (e.g. audit/auth plugins)
SELECT plugin_name, plugin_status, plugin_type FROM information_schema.plugins
WHERE plugin_status <> 'ACTIVE';
```

If you used `mysql_native_password` auth, confirm application drivers work with the 8.0 default `caching_sha2_password` (or that the plugin is still available).

## Query plan verification

Optimiser changes across major versions are one of the top causes of post-upgrade regression. For each critical query that was in the "hot queries" set before the upgrade, capture a fresh plan and compare:

Use `EXPLAIN FORMAT=JSON` (estimated plan) or `EXPLAIN ANALYZE` (MySQL 8.0+; runs the query and reports actual vs estimated row counts and timing):

```sql
EXPLAIN FORMAT=JSON SELECT ... FROM hot_table WHERE ...;
EXPLAIN ANALYZE      SELECT ... FROM hot_table WHERE ...;
```

Look for:

- Different join ordering or join algorithm (nested-loop ↔ hash join; MySQL 8.0.18+ adds hash joins).
- Index usage changes (previously used index now not chosen).
- Large gaps between estimated and actual rows (selectivity estimates degraded — refresh stats with `ANALYZE TABLE`).

## Aurora parameter group family migration (commonly missed)

**Aurora cluster parameter groups are pinned to a specific major version family** (e.g. `aurora-mysql5.7`, `aurora-mysql8.0`, `aurora-mysql8.4`). The upgrade process creates a **new** parameter group in the target family OR requires you to assign one — you cannot reuse an `aurora-mysql5.7` parameter group on an 8.0 cluster.

Verify the cluster is actually using a target-family parameter group:

```bash
aws rds describe-db-clusters --db-cluster-identifier <cluster> \
  --query "DBClusters[0].{PG:DBClusterParameterGroup}" --region <region>

# Inspect custom parameter values
aws rds describe-db-cluster-parameters \
  --db-cluster-parameter-group-name <new-pg> \
  --query "Parameters[?Source=='user'].{Name:ParameterName,Value:ParameterValue}" \
  --output table --region <region>
```

**Risk**: if the pre-upgrade cluster had custom parameters (e.g. `innodb_buffer_pool_size`, `max_connections`, `innodb_log_file_size`, custom logging settings), those MUST be re-applied to the new-family parameter group — they are NOT carried across automatically. Mis-applied parameter groups are the second-largest source of post-upgrade regressions after optimiser changes.

## Pre-upgrade snapshot — rollback window (CRITICAL)

If you took a **pre-upgrade manual snapshot** (you should have — it's a pre-upgrade-checklist item), note that:

- A snapshot taken on the **old** major version restores to the **old** major version — NOT to the post-upgrade new version. A 3.04 snapshot → 3.04 restore. You cannot "upgrade by restoring from a snapshot."
- This snapshot is your rollback path for the first 7–14 days post-upgrade. Do NOT delete it until you've confirmed the new version is stable under full production load. 7–14 days of stable production is the industry norm; longer for regulated workloads.
- If you need to rollback, you restore the pre-upgrade snapshot into a new cluster, then cut traffic back over. There is no in-place downgrade.

## Monitoring window (24–72 hours)

Watch these CloudWatch metrics for the first 24–72 hours and compare to pre-upgrade baselines:

- **`CPUUtilization`** — a 5–15% change is normal; > 25% indicates a plan regression.
- **`DatabaseConnections`** — should be stable; sudden rise can mean connection-pool re-auth loops on engine changes.
- **`ReadLatency`, `WriteLatency`, `DMLLatency`, `SelectLatency`** — p95 should return to baseline within 2 hours; sustained elevation indicates query-plan issues.
- **`FreeableMemory`** — especially important if the cluster uses a custom `innodb_buffer_pool_size`; freezing at a different level indicates a parameter-group-family migration issue.
- **`BufferCacheHitRatio`** (the Aurora MySQL buffer-pool hit ratio) — should be ≥95% for OLTP; drop below 90% means statistics or cache warmup issue.
- **`AuroraReplicaLag`, `AuroraReplicaLagMaximum`** — as above, should settle below 100 ms for readers.
- **`Deadlocks`, `LoginFailures`** — both should be near pre-upgrade baseline; a spike can signal an authentication-plugin change (`caching_sha2_password` default in MySQL 8.0) or a reserved-word conflict.

## What NOT to do post-upgrade

- **Do NOT suggest a rollback as the first response to a minor issue.** The rollback path destroys the timeline and takes significant effort. Debug regressions on the new version first.
- **Do NOT delete the pre-upgrade snapshot in the first week**. That is the rollback path.
- **Do NOT run `modify-db-cluster --engine-version`** to downgrade — downgrades are not supported in-place. (Downgrades are not supported in-place by Aurora.)
- **Do NOT skip the `ANALYZE TABLE` pass** on hot tables even if the optimizer seems to be running fine. A one-time post-upgrade manual statistics refresh is insurance.
