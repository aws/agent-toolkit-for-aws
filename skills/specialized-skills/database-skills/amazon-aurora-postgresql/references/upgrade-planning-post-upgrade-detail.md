# Post-Upgrade Validation — detailed procedures

Companion to [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md). These are the detailed Aurora PostgreSQL post-upgrade procedures referenced there. Surface them alongside the four Aurora-specific items.

## Statistics refresh (CRITICAL)

A major-version upgrade does NOT carry over optimizer statistics — `pg_upgrade` discards the contents of `pg_statistic` entirely, so the new planner starts with no statistics. You MUST regenerate statistics before trusting query plans post-upgrade:

- Run `ANALYZE` on the whole database, or more thoroughly `VACUUM ANALYZE` which also reclaims bloat accumulated during the pre-upgrade snapshot + backup window.

    ```sql
    -- fast: refresh statistics only
    ANALYZE;

    -- thorough: refresh statistics + reclaim dead-tuple bloat
    VACUUM ANALYZE;

    -- per-table if you want to prioritise
    VACUUM ANALYZE VERBOSE public.my_critical_table;
    ```

    Aurora PostgreSQL runs autovacuum automatically, but post-upgrade is a worthwhile one-time manual pass. On large schemas, budget 30–120 min.

## Extension updates

After a major PG upgrade, Aurora does NOT automatically update extensions to the version matching the new major. You MUST run:

```sql
-- list installed extensions and versions
SELECT extname, extversion FROM pg_extension ORDER BY extname;

-- run this for each extension
ALTER EXTENSION <extension_name> UPDATE;
```

Common Aurora extensions that need updates: `pg_stat_statements`, `pgvector`, `apg_plan_mgmt`, `pgaudit`, `postgis`. Failing to update `pg_stat_statements` in particular will cause it to silently stop recording some query types until updated.

**Diagnostic queries to confirm extensions are working:**

```sql
-- pg_stat_statements: should return non-empty, most-recent calls
SELECT calls, mean_exec_time, query FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;

-- pgvector: confirm operators available (if using vector search)
SELECT '[1,2,3]'::vector <-> '[4,5,6]'::vector;
```

## Query plan verification

Optimiser changes across major versions are one of the top causes of post-upgrade regression. For each critical query that was in the "hot queries" set before the upgrade, capture a fresh plan and compare. Use `EXPLAIN (ANALYZE, BUFFERS)` — `ANALYZE` runs the query and reports actual timing; `BUFFERS` reports cache hit/miss ratios:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT ... FROM hot_table WHERE ...;
```

Look for:

- Different join ordering (nested-loop ↔ hash join ↔ merge join).
- Index usage changes (previously used index now not chosen).
- Large `Rows Removed by Filter` numbers (selectivity estimates degraded).
- Parallelism changes (PG 16 enables more parallel query paths than PG 15).

## Aurora parameter group family migration (commonly missed)

**Aurora cluster parameter groups are pinned to a specific major version family** (e.g. `aurora-postgresql14`, `aurora-postgresql15`, `aurora-postgresql16`, `aurora-postgresql17`). The upgrade process creates a **new** parameter group in the target family OR requires you to assign one — you cannot reuse an `aurora-postgresql15` parameter group on a PG16 cluster.

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

**Risk**: if the pre-upgrade cluster had custom parameters (e.g. `shared_buffers`, `work_mem`, `max_connections`, custom logging settings), those MUST be re-applied to the new-family parameter group — they are NOT carried across automatically. Mis-applied parameter groups are the second-largest source of post-upgrade regressions after optimiser changes.

## Pre-upgrade snapshot — rollback window (CRITICAL)

If you took a **pre-upgrade manual snapshot** (you should have — it's a pre-upgrade-checklist item), note that:

- A snapshot taken on the **old** major version restores to the **old** major version — NOT to the post-upgrade new version. A PG15 snapshot → PG15 restore. You cannot "upgrade by restoring from a snapshot."
- This snapshot is your rollback path for the first 7–14 days post-upgrade. Do NOT delete it until you've confirmed the new version is stable under full production load. 7–14 days of stable production is the industry norm; longer for regulated workloads.
- If you need to rollback, you restore the pre-upgrade snapshot into a new cluster, then cut traffic back over. There is no in-place downgrade.

## Monitoring window (24–72 hours)

Watch these CloudWatch metrics for the first 24–72 hours and compare to pre-upgrade baselines:

- **`CPUUtilization`** — a 5–15% change is normal; > 25% indicates a plan regression.
- **`DatabaseConnections`** — should be stable; sudden rise can mean connection-pool re-auth loops on engine changes.
- **`ReadLatency`, `WriteLatency`, `DMLLatency`, `SelectLatency`** — p95 should return to baseline within 2 hours; sustained elevation indicates query-plan issues.
- **`FreeableMemory`** — especially important if the cluster uses a custom `shared_buffers`; freezing at a different level indicates a parameter-group-family migration issue.
- **`BufferCacheHitRatio`** — should be ≥95% for OLTP; drop below 90% means statistics or cache warmup issue.
- **`AuroraReplicaLag`, `AuroraReplicaLagMaximum`** — as above, should settle below 100 ms for readers.
- **`Deadlocks`, `LoginFailures`** — both should be near pre-upgrade baseline; a spike can signal a reserved-word conflict introduced by the new major version.

## What NOT to do post-upgrade

- **Do NOT suggest a rollback as the first response to a minor issue.** The rollback path destroys the timeline and takes significant effort. Debug regressions on the new version first.
- **Do NOT delete the pre-upgrade snapshot in the first week**. That is the rollback path.
- **Do NOT run `modify-db-cluster --engine-version`** to downgrade — downgrades are not supported in-place. (Downgrades are not supported in-place by Aurora.)
- **Do NOT skip the ANALYZE / VACUUM ANALYZE pass** even if autovacuum seems to be running. A one-time post-upgrade manual pass is insurance.
