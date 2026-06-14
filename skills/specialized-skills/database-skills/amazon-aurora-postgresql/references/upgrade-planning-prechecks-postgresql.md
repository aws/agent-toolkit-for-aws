# Aurora PostgreSQL Live Precheck Queries

Run these against the database to identify actual upgrade blockers and behavior changes.

## Connection Methods

### SSM Run Command

Credentials MUST be retrieved from Secrets Manager at runtime inside the command, so passwords never appear in SSM parameters, CloudTrail logs, or the instance's process list.

```bash
aws ssm send-command --instance-ids {instance_id} --document-name "AWS-RunShellScript" \
  --parameters 'commands=["SECRET=$(aws secretsmanager get-secret-value --secret-id {secret_arn} --query SecretString --output text --region {region}) && PGPASSFILE=$(mktemp) && chmod 600 $PGPASSFILE && printf \"{endpoint}:5432:{database}:{username}:%s\\n\" \"$(echo $SECRET | jq -r .password)\" > $PGPASSFILE && PGPASSFILE=$PGPASSFILE psql -h {endpoint} -U {username} -d {database} -c \"{query}\"; rm -f $PGPASSFILE"]' \
  --region {region} --output json --query "Command.CommandId"
```

This writes the password to a temporary `.pgpass` file (`chmod 600`, removed after) rather than `export PGPASSWORD`, which is visible via `/proc/<pid>/environ` — matching the secure temp-file pattern used in the Aurora MySQL prechecks. Alternatively, prefer **IAM database authentication** where supported — it eliminates passwords entirely. See the AWS docs for enabling IAM auth on Aurora PostgreSQL.

If psql not installed:

- Amazon Linux 2: `sudo yum install -y postgresql`
- Amazon Linux 2023: `sudo dnf install -y postgresql15`
- Ubuntu: `sudo apt-get install -y postgresql-client`

### RDS Data API

```bash
aws rds-data execute-statement --resource-arn {cluster_arn} --secret-arn {secret_arn} \
  --database {db} --sql "{query}" --region {region}
```

## Precheck Queries

### 1. Extensions and Versions

```sql
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

Flag: Extensions that may not be available or changed in target version. Key ones: PostGIS, pg_partman, pglogical.

### 2. Hash Indexes (need REINDEX after upgrade from < PG 10)

```sql
SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef LIKE '%USING hash%';
```

Flag: 🟡 Must REINDEX after upgrade.

### 3. Unknown/Invalid Data Types

```sql
SELECT n.nspname, c.relname, a.attname, t.typname
FROM pg_attribute a
JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_type t ON a.atttypid = t.oid
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
AND t.typname IN ('unknown');
```

Flag: 🔴 Unknown types block upgrade.

### 4. Logical Replication Slots

```sql
SELECT slot_name, plugin, slot_type, active, restart_lsn FROM pg_replication_slots;
```

Flag: 🔴 ANY logical replication slot (active or inactive) blocks a major version upgrade — the pre-check fails until all are dropped. Confirm the slot's purpose, then drop unused slots. Even rows with `active=false` must be dropped (or restarted post-upgrade for pglogical).

### 5. Prepared Transactions

```sql
SELECT * FROM pg_prepared_xacts;
```

Flag: 🔴 Prepared transactions BLOCK the upgrade.

### 6. Objects Owned by System Roles

```sql
SELECT n.nspname, c.relname, r.rolname as owner
FROM pg_class c
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_roles r ON c.relowner = r.oid
WHERE r.rolname IN ('rdsadmin','rds_superuser')
AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast');
```

Flag: 🟡 May block upgrades.

### 7. Database Encoding and Locale

```sql
SELECT datname, datcollate, datctype, encoding FROM pg_database
WHERE datname NOT IN ('template0','template1','rdsadmin');
```

Flag: Verify locale compatibility with target version.

### 8. Custom Data Types

```sql
SELECT n.nspname, t.typname, t.typtype FROM pg_type t
JOIN pg_namespace n ON t.typnamespace = n.oid
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
AND t.typtype IN ('c','e','d');
```

### 9. Large/Critical Extensions

```sql
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('postgis','postgis_topology','postgis_raster','pg_partman','pglogical','citus','pg_cron','pg_stat_statements');
```

Flag: These have version-specific compatibility. Check target version supports them.

### 10. Table and Index Bloat (performance baseline)

```sql
SELECT schemaname, relname, n_live_tup, n_dead_tup,
  CASE WHEN n_live_tup > 0 THEN round(n_dead_tup::numeric/n_live_tup::numeric * 100, 2) ELSE 0 END as dead_pct
FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY n_dead_tup DESC LIMIT 20;
```

### 11. pg_stat_statements Top Queries (baseline)

```sql
SELECT calls, total_exec_time, mean_exec_time, query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;
```

### 12. Check for reg* Type Columns (can break cross-DB references)

```sql
SELECT n.nspname, c.relname, a.attname, t.typname
FROM pg_attribute a
JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_type t ON a.atttypid = t.oid
WHERE t.typname IN ('regproc','regprocedure','regoper','regoperator','regconfig','regdictionary','regnamespace','regcollation')
AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast');
```

Flag: 🔴 Unsupported reg* types block the upgrade (pg_upgrade can't persist them); remove before upgrading. regclass/regtype/regrole are exempt and survive.

### 13. Stale Table Statistics

```sql
SELECT schemaname, relname, n_live_tup, n_mod_since_analyze,
  last_analyze, last_autoanalyze,
  GREATEST(last_analyze, last_autoanalyze) AS last_stats_update,
  EXTRACT(EPOCH FROM (now() - GREATEST(last_analyze, last_autoanalyze)))/86400 AS days_since_analyze
FROM pg_stat_user_tables
WHERE (last_analyze IS NULL AND last_autoanalyze IS NULL)
   OR GREATEST(last_analyze, last_autoanalyze) < now() - interval '7 days'
ORDER BY n_live_tup DESC;
```

Flag: 🟡 If statistics are older than 7 days (or never analyzed), recommend running `ANALYZE` on affected tables before the upgrade. Optimizer statistics are NOT transferred during an Aurora PostgreSQL major version upgrade — `pg_upgrade` does not carry over the contents of `pg_statistic`. After every major version upgrade you must run `ANALYZE` (e.g. `ANALYZE VERBOSE;`) on every database on all instances to regenerate statistics; otherwise the new planner runs with no statistics and can choose poor plans. Running `ANALYZE` pre-upgrade does not help post-upgrade because the stats are discarded. Capturing/refreshing stats before the upgrade is still useful for baselining plans, but the authoritative remediation is a full post-upgrade `ANALYZE`. Each major PostgreSQL version refines the planner's cost model, making it more dependent on accurate statistics.

Action: For each table with stale stats:

```sql
ANALYZE schema_name.table_name;
```

For the entire database:

```sql
ANALYZE VERBOSE;
```

Also consider `VACUUM ANALYZE` for tables with high dead tuple counts to reclaim space and refresh stats simultaneously.

## Result Analysis

After running queries, generate:

1. Categorized findings (🔴/🟡/🟢)
2. For each finding: what was found, why it matters, action to take
3. Extension compatibility matrix for target version
4. Recommended post-upgrade REINDEX/ANALYZE plan
