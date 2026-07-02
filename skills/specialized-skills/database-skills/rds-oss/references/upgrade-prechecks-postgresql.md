# RDS PostgreSQL Live Precheck Queries

Run these against the database to identify upgrade blockers and behavior changes.

## Connection Methods

### SSM Run Command

```bash
aws ssm send-command --instance-ids {instance_id} --document-name "AWS-RunShellScript" \
  --parameters 'commands=["export PGPASSWORD=$(aws secretsmanager get-secret-value --secret-id {secret_arn} --query SecretString --output text | jq -r .password); psql -h {endpoint} -U {username} -d {database} -c \"{query}\""]' \
  --region {region} --output json --query "Command.CommandId"
```

**Preferred: IAM database authentication** — where supported, use `aws rds generate-db-auth-token` to produce a short-lived token and connect with `--no-password`. This avoids any password in the environment or command history.

**Fallback: Secrets Manager retrieval** (shown above) — never pass plaintext passwords in SSM command parameters, as they are visible in SSM command history, CloudTrail logs, and process listings. Note that `export PGPASSWORD=...` still exposes the value in the shell process environment (`/proc/<pid>/environ`) for its lifetime; where IAM auth is unavailable, prefer a `.pgpass` file (chmod 600) over environment variables. If query results may contain sensitive data, enable KMS encryption on the SSM Run Command output. Use minimal-privilege credentials (a read-only user scoped to the precheck schemas) rather than the master user.

Note: RDS Data API is NOT available for standalone RDS instances.

## Precheck Queries

### 1. Extensions and Versions

```sql
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

Flag: Check target version supports each extension.

### 2. Hash Indexes

```sql
SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef LIKE '%USING hash%';
```

Flag: 🟡 Must REINDEX after upgrade.

### 3. Unknown/Invalid Data Types

```sql
SELECT n.nspname, c.relname, a.attname, t.typname
FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_type t ON a.atttypid = t.oid
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
AND t.typname IN ('unknown');
```

Flag: 🔴 Unknown types block upgrade.

### 4. Logical Replication Slots

```sql
SELECT slot_name, plugin, slot_type, active FROM pg_replication_slots;
```

Flag: 🔴 Active logical replication slots BLOCK major upgrades.

### 5. Prepared Transactions

```sql
SELECT * FROM pg_prepared_xacts;
```

Flag: 🔴 Prepared transactions BLOCK the upgrade.

### 6. Objects Owned by System Roles

```sql
SELECT n.nspname, c.relname, r.rolname as owner
FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid
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

### 8. Custom Data Types

```sql
SELECT n.nspname, t.typname, t.typtype FROM pg_type t
JOIN pg_namespace n ON t.typnamespace = n.oid
WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
AND t.typtype IN ('c','e','d');
```

### 9. Critical Extensions

```sql
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('postgis','postgis_topology','postgis_raster','pg_partman',
'pglogical','citus','pg_cron','pg_stat_statements');
```

Flag: Version-specific compatibility. Check target version supports them.

### 10. Table and Index Bloat

```sql
SELECT schemaname, relname, n_live_tup, n_dead_tup,
  CASE WHEN n_live_tup > 0 THEN round(n_dead_tup::numeric/n_live_tup::numeric * 100, 2) ELSE 0 END as dead_pct
FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY n_dead_tup DESC LIMIT 20;
```

### 11. reg* Type Columns

```sql
SELECT n.nspname, c.relname, a.attname, t.typname
FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
JOIN pg_type t ON a.atttypid = t.oid
WHERE t.typname IN ('regproc','regprocedure','regoper','regoperator','regclass',
'regtype','regconfig','regdictionary')
AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast');
```

Flag: 🟡 reg* types store OIDs that may change after upgrade.

### 12. Stale Table Statistics

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

Flag: 🟡 Use this to record which tables have stale statistics as a pre-upgrade baseline — it helps you spot post-upgrade plan regressions. A major version upgrade does not carry statistics across, so statistics are recalculated **after** the upgrade — see the post-upgrade checklist, which scopes `ANALYZE` to the affected tables in a low-traffic window.

## Result Analysis

Generate:

1. Categorized findings (🔴/🟡/🟢)
2. For each finding: what was found, why it matters, action to take
3. Extension compatibility matrix for target version
4. Recommended post-upgrade REINDEX/ANALYZE plan
