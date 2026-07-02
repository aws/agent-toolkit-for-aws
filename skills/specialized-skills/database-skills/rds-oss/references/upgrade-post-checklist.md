# RDS Post-Upgrade Checklist — MySQL, MariaDB, PostgreSQL

## Step 1: Verify the Upgrade Completed Successfully

```bash
aws rds describe-db-instances \
  --db-instance-identifier <instance-id> \
  --query "DBInstances[0].{EngineVersion:EngineVersion,DBInstanceStatus:DBInstanceStatus,DBParameterGroups:DBParameterGroups[0].{Name:DBParameterGroupName,Status:ParameterApplyStatus}}" \
  --region <region>
```

Confirm:

- EngineVersion matches the target version
- DBInstanceStatus is `available`
- Parameter group status is `in-sync` (if `pending-reboot`, reboot the instance)

## Step 2: Verify Application Connectivity and Query Performance

Connect to the instance and confirm basic operations work:

**MySQL/MariaDB:**

```sql
SELECT VERSION();
SHOW DATABASES;
SELECT 1;
```

**PostgreSQL:**

```sql
SELECT version();
\l
SELECT 1;
```

Check that:

- Connection succeeds (for MySQL 8.0: auth plugin may have changed to `caching_sha2_password` — older clients may need `--default-auth=mysql_native_password`)
- All expected databases are present
- Key application queries return expected results

If you observe query performance regressions at this step, table statistics may be stale. The new optimizer in the target version relies more heavily on accurate statistics. You can refresh statistics for the affected tables:

**MySQL/MariaDB:**

```sql
ANALYZE TABLE schema_name.table_name;
```

**PostgreSQL:**

```sql
ANALYZE schema_name.table_name;
```

Note: `ANALYZE TABLE` and `OPTIMIZE TABLE` are expensive operations. Do NOT run them blanket across all tables while production traffic is active. Target only the tables where you observe performance issues, and run during a low-traffic window.

## Step 3: Verify Application Connectivity

Beyond basic database connectivity, verify that your actual application connects and operates correctly against the upgraded instance:

- Point your application (or a staging/canary instance) at the upgraded database
- Confirm the application driver is compatible with the new engine version — auth plugin changes (MySQL 8.0: `caching_sha2_password`), TLS negotiation, and connection pooling behavior may differ
- Run key application workflows end-to-end (reads, writes, transactions)
- Check application logs for connection errors, query failures, or unexpected behavior
- If using connection pooling (HikariCP, PgBouncer, ProxySQL), verify pools reconnected and are healthy

## Step 4: Verify Parameter Group Settings

If you created a custom parameter group to preserve previous behavior, confirm the key settings took effect:

**MySQL (5.7 → 8.0):**

```sql
SELECT @@character_set_server, @@collation_server, @@sql_mode, @@innodb_strict_mode;
```

**PostgreSQL:**

```sql
SHOW server_encoding;
SHOW lc_collate;
SHOW work_mem;
SHOW shared_buffers;
```

If you used the default parameter group for the target family, these will be the new version's defaults — verify your application handles them correctly.

## Step 5: Check for Query Plan Changes

The optimizer in the target version may choose different execution plans. Run EXPLAIN on your most critical queries and compare with pre-upgrade behavior:

**MySQL/MariaDB:**

```sql
EXPLAIN FORMAT=JSON SELECT ... ;
```

Watch for (MySQL 8.0):

- Hash joins replacing nested loop joins (new in 8.0 — usually faster, but verify)
- GROUP BY results no longer implicitly sorted — add explicit ORDER BY if your app relied on this
- Index choices may differ due to updated cost model

**PostgreSQL:**

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ... ;
```

Watch for (PG 15+):

- work_mem per-operation accounting changes
- Memoize nodes on nested loops (PG 14+)
- Parallel query threshold changes

## Step 6: Verify Audit and Access Logging

Parameter group changes during an upgrade can reset logging settings. After the upgrade, confirm logging is still enabled:

- **MySQL/MariaDB**: audit plugin still active; `general_log` and `slow_query_log` settings preserved
- **PostgreSQL**: `pgaudit` extension settings, `log_connections`, `log_disconnections` preserved
- **All engines**: CloudTrail is still capturing RDS API calls for the account/region

## Step 7: Monitor CloudWatch Metrics

Monitor these CloudWatch metrics for the first 24-48 hours post-upgrade. These apply to all RDS engines (MySQL, MariaDB, PostgreSQL):

- `CPUUtilization` — should be comparable to pre-upgrade baseline
- `DatabaseConnections` — confirm apps reconnected successfully
- `ReadIOPS` — watch for unexpected spikes indicating plan regressions
- `WriteIOPS` — watch for unexpected spikes
- `FreeableMemory` — the new version may use memory differently
- `FreeStorageSpace` — upgrade process may temporarily consume extra storage

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=<instance-id> \
  --start-time <start> --end-time <end> \
  --period 300 --statistics Average \
  --region <region>
```

If any metric shows a significant regression compared to pre-upgrade baseline, investigate before considering the upgrade successful.

## Step 8: Clean Up

Only proceed with cleanup after you have confirmed the upgrade was successful and you do not observe any performance or operational regressions. Keep the pre-upgrade snapshot and old Blue/Green environment available as a rollback option until you are fully confident.

Once confirmed:

- Delete the pre-upgrade snapshot (it incurs storage charges)
- Delete any test instances created during pre-upgrade validation
- If Blue/Green was used: delete the old blue environment and the Blue/Green deployment

```bash
# Delete old snapshot (only after confirming upgrade success)
aws rds delete-db-snapshot \
  --db-snapshot-identifier <instance-id>-pre-upgrade-snapshot \
  --region <region>
```
