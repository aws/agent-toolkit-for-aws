# Post-Upgrade Checklist

## Common Steps

1. **Verify upgrade completed**

   ```bash
   aws rds describe-db-clusters --db-cluster-identifier {cluster} \
     --query "DBClusters[0].{Engine:Engine,EngineVersion:EngineVersion,Status:Status}" \
     --output json --region {region}
   ```

2. **Preserve the rollback window — do NOT delete pre-upgrade snapshots immediately.** Major version upgrades are **one-way** in-place. Rollback requires restoring from a snapshot or PITR, and both restore the **old** major version:
   - Any **pre-upgrade manual snapshot** restores to the engine version it was taken on (e.g., an Aurora MySQL 3.04 snapshot restores to 3.04 — not to a post-upgrade 3.10).
   - **PITR to any time before the upgrade completed** restores the pre-upgrade major version, not the new one.
   - After the upgrade, Aurora cannot restore backward-in-time into the new major version; that timeline starts at the upgrade's completion.

   Keep the pre-upgrade manual snapshot for **at least 7–14 days of stable production traffic** (longer for regulated workloads) before deleting it. Deleting it early forecloses the cheapest rollback path. Document the snapshot identifier and retain-until date in your change record.

3. **Check performance discrepancies** — Compare CloudWatch metrics against baseline: CPUUtilization, DatabaseConnections, ReadLatency, WriteLatency, FreeableMemory, BufferCacheHitRatio, DMLLatency, SelectLatency. Use Performance Insights to compare database load.

4. **Compare EXPLAIN plans** for critical queries. Look for: different join strategies, missing index usage, full table scans.
   - `EXPLAIN FORMAT=JSON SELECT ...;` (or `EXPLAIN ANALYZE` on MySQL 8.0+ for actual row counts)

5. **Monitor CloudWatch 24-72 hours** — Watch: CPUUtilization, FreeableMemory, DatabaseConnections, ReadLatency, WriteLatency, AuroraReplicaLag, Deadlocks, LoginFailures.

6. **Validate application connectivity** — connections, pooling, SSL/TLS.

7. **Verify parameter group** applied correctly:

   ```bash
   aws rds describe-db-cluster-parameters --db-cluster-parameter-group-name {new_pg} \
     --query "Parameters[?Source=='user'].{Name:ParameterName,Value:ParameterValue}" \
     --output table --region {region}
   ```

8. **Update statistics** — run `ANALYZE TABLE` on hot tables to rebuild optimizer statistics for the new version.

9. **Check error logs**

   ```bash
   aws rds describe-events --source-identifier {cluster} --source-type db-cluster --duration 1440 --region {region}
   ```

## Aurora MySQL-Specific

1. **Verify auth plugin compatibility** — `SELECT user, host, plugin FROM mysql.user;` Check if apps need mysql_native_password.

2. **Check GROUP BY sorting** — 8.0 no longer implicitly sorts. Apps relying on this need explicit ORDER BY.

3. **Validate stored procedures** — run critical routines, check for deprecated syntax.

4. **Verify query cache removal impact** — if query cache was enabled, monitor for increased CPU/latency. Consider ElastiCache if hit ratio was high.
