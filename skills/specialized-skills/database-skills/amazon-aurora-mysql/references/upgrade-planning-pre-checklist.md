# Pre-Upgrade Checklist

## Common Steps (Both Engines)

1. **Create test environment via snapshot restore**

   ```bash
   aws rds create-db-cluster-snapshot --db-cluster-identifier {cluster} \
     --db-cluster-snapshot-identifier {cluster}-pre-upgrade-snapshot --region {region}
   aws rds restore-db-cluster-from-snapshot --db-cluster-identifier {cluster}-upgrade-test \
     --snapshot-identifier {cluster}-pre-upgrade-snapshot \
     --engine {engine} --engine-version {target_version} --region {region}
   ```

2. **Review and create new parameter group**

   ```bash
   aws rds describe-db-cluster-parameters --db-cluster-parameter-group-name {current_pg} \
     --query "Parameters[?Source=='user' && ParameterValue!=null].{Name:ParameterName,Value:ParameterValue}" \
     --output table --region {region}
   ```

   Create new group for target version family and apply custom parameters.

3. **Check pending maintenance actions**

   ```bash
   aws rds describe-pending-maintenance-actions \
     --resource-identifier arn:aws:rds:{region}:{account}:cluster:{cluster} --region {region}
   ```

4. **Capture baseline performance metrics** — CloudWatch: CPUUtilization, DatabaseConnections, ReadLatency, WriteLatency, FreeableMemory, BufferCacheHitRatio. Save EXPLAIN plans for critical queries.

5. **Consider Blue/Green Deployments** for minimal downtime. Ref: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/blue-green-deployments.html

6. **Plan maintenance window** — schedule during lowest traffic (use Performance Insights).

## Aurora MySQL-Specific

1. **Run upgrade prechecks** on test cluster first. Ref: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraMySQL.upgrade-prechecks.html

2. **Check reserved keywords** — MySQL 8.0 added: CUME_DIST, DENSE_RANK, EMPTY, EXCEPT, FIRST_VALUE, GROUPING, GROUPS, JSON_TABLE, LAG, LAST_VALUE, LATERAL, LEAD, NTH_VALUE, NTILE, OF, OVER, PERCENT_RANK, RANK, RECURSIVE, ROW, ROWS, ROW_NUMBER, SYSTEM, WINDOW. Full list: https://dev.mysql.com/doc/refman/8.0/en/keywords.html

3. **Review MySQL 8.0 behavior changes** — Customer MUST review:
   - What's New: https://dev.mysql.com/doc/refman/8.0/en/mysql-nutshell.html
   - Release Notes: https://dev.mysql.com/doc/relnotes/mysql/8.0/en/
   - Upgrade Guide: https://dev.mysql.com/doc/refman/8.0/en/upgrading.html
   - Key changes: latin1→utf8mb4 default, GROUP BY no implicit sort, query cache removed, caching_sha2_password default, optimizer changes

4. **Check XA transactions**: `XA RECOVER;` — must commit/rollback before upgrade.

5. **Enable binary logging for Blue/Green** — associate the cluster with a *custom* DB cluster parameter group that has `binlog_format` turned ON (ROW recommended; STATEMENT/MIXED also work), then reboot the writer so it is in sync with the parameter group (otherwise Blue/Green creation fails). Also set a non-NULL binlog retention period. Note `binlog_format` is deprecated as of MySQL 8.0.34, so ROW is preferred for new setups. Ref: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/blue-green-deployments-creating.html

6. **Check deprecated features**: mysql_native_password, partitioned tables in shared tablespaces, old temporal columns.
