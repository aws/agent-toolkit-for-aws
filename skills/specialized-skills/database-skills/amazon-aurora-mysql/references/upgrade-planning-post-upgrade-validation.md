# Post-Upgrade Validation — must-surface items

When the user reports they just completed an upgrade and asks what to check now, you MUST surface **all of the items below** with Aurora-specific detail — do not leave them in the checklist file. They must appear by name in your reply. See [post-upgrade-detail.md](upgrade-planning-post-upgrade-detail.md) for the statistics-refresh, extension-update, plan-verification, parameter-group-family, snapshot-rollback, and monitoring-window procedures.

## Aurora-specific post-upgrade items (MUST appear by name in your reply — not just cited by reference)

A generic RDS-for-MySQL post-upgrade checklist misses Aurora-specific blockers and leaves the user exposed. These Aurora-specific items MUST appear in your reply:

1. **`SELECT aurora_version()`** — run on the writer AND on each reader. Aurora has an internal version distinct from the MySQL-engine version reported by `SELECT VERSION()`. Confirm both writer and readers report the expected Aurora internal version; a mismatch means the rolling-upgrade is incomplete on some readers.
2. **Aurora parameter-group family migration (e.g. `aurora-mysql5.7` → `aurora-mysql8.0`)** — **CRITICAL**: Aurora cluster parameter groups are pinned to a specific major-version family. **An `aurora-mysql5.7` family parameter group does NOT carry forward to an 8.0 cluster** — Aurora cannot attach a 5.7-family parameter group to an 8.0-family cluster. Post-upgrade, the cluster is using either: (a) the new-family default (`default.aurora-mysql8.0`), which is NOT your custom pre-upgrade settings, or (b) a new custom parameter group you created in the new family. **Any custom parameters you had set pre-upgrade (e.g. `innodb_buffer_pool_size`, `max_connections`, `innodb_log_file_size`, `slow_query_log`) MUST be manually re-applied to the new-family parameter group — they are NOT auto-migrated.** Verify with `aws rds describe-db-clusters` that the cluster is on the new-family parameter group, then compare the `user`-sourced parameters against your pre-upgrade notes. Mis-applied parameter-group family is the second-largest source of post-upgrade performance regressions (after optimiser changes).
3. **`AuroraReplicaLag`** CloudWatch metric — replica-to-writer replication lag, in milliseconds. Immediately post-upgrade readers may show 1–10 second lag while catching up; sustained > 100 ms for > 15 min indicates a problem. Also watch **`AuroraReplicaLagMaximum`** for the worst-case reader.
4. **Global Database secondary-cluster status** — if the cluster is part of an Aurora Global Database, the secondary cluster(s) in other regions are upgraded separately and MAY not be in sync. Use `aws rds describe-global-clusters` to confirm each member is on the target version. A secondary stuck at the pre-upgrade version means the cross-region replication is broken until you upgrade the secondary too.

These four items are in ADDITION to the generic items in [post-upgrade-detail.md](upgrade-planning-post-upgrade-detail.md) (statistics refresh via `ANALYZE TABLE`, plugin/component checks, `EXPLAIN`/`EXPLAIN ANALYZE` plan verification, pre-upgrade snapshot rollback window, CloudWatch monitoring). Omitting the four Aurora-specific items above leaves real gaps — include them.

## Immediate cluster-state checks

1. **Confirm the upgrade completed and the cluster is healthy.**

    ```bash
    aws rds describe-db-clusters --db-cluster-identifier <cluster> \
      --query "DBClusters[0].{Engine:Engine,EngineVersion:EngineVersion,Status:Status,ParameterGroup:DBClusterParameterGroup}" \
      --region <region>
    ```

2. **Verify the Aurora engine-internal version matches the expected target** via SQL (NOT just the RDS API — they can differ mid-rollout):

    ```sql
    SELECT aurora_version();
    SELECT VERSION();
    ```

3. **Verify Aurora replicas have re-synced**. The critical CloudWatch metric is **`AuroraReplicaLag`** (milliseconds of replication lag between writer and each reader). Immediately after a rolling-upgrade, readers may show elevated lag (1–10 seconds) for a few minutes while they catch up. If lag stays > 100 ms for more than 15 minutes, something is wrong. Also check `AuroraReplicaLagMaximum` for the worst-case reader.
