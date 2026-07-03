# RDS MySQL / MariaDB Live Precheck Queries

Run these against the database to identify upgrade blockers and behavior changes. These queries apply to both RDS MySQL and RDS MariaDB engines.

## Connection Methods

### SSM Run Command

```bash
aws ssm send-command --instance-ids {instance_id} --document-name "AWS-RunShellScript" \
  --parameters 'commands=["SECRET=$(aws secretsmanager get-secret-value --secret-id {secret_arn} --query SecretString --output text | jq -r .password); mysql -h {endpoint} -u {username} -p\"$SECRET\" -e \"{query}\""]' \
  --region {region} --output json --query "Command.CommandId"
```

**Never pass plaintext passwords in SSM command parameters** — they are visible in SSM command history, CloudTrail logs, and process listings. Always retrieve the password from Secrets Manager at execution time as shown above. If query results may contain sensitive data, enable KMS encryption on the SSM Run Command output.

**Preferred: IAM database authentication** — where supported, use `aws rds generate-db-auth-token` to produce a short-lived token and connect with `--password="$TOKEN"`. This avoids any long-lived password in the environment or command history. Use minimal-privilege credentials (a read-only user with SELECT on `information_schema`, `performance_schema`, and `mysql.user`) rather than the master user.
Retrieve results:

```bash
aws ssm get-command-invocation --command-id {id} --instance-id {instance_id} --region {region}
```

Note: RDS Data API is NOT available for standalone RDS instances.

## Precheck Queries

### 1. Reserved Keywords (MySQL 5.7→8.0)

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
WHERE UPPER(COLUMN_NAME) IN ('CUME_DIST','DENSE_RANK','EMPTY','EXCEPT','FIRST_VALUE',
'GROUPING','GROUPS','JSON_TABLE','LAG','LAST_VALUE','LATERAL','LEAD','NTH_VALUE',
'NTILE','OF','OVER','PERCENT_RANK','RANK','RECURSIVE','ROW','ROWS','ROW_NUMBER',
'SYSTEM','WINDOW')
AND TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
```

Flag: Any results = must quote with backticks or rename.

### 2. Authentication Plugins

```sql
SELECT user, host, plugin FROM mysql.user;
```

Flag: `mysql_native_password` deprecated in 8.0. `sha256_password` replaced by `caching_sha2_password`.

### 3. XA Transactions

```sql
XA RECOVER;
```

Flag: 🔴 Any results BLOCK the upgrade.

### 4. Server Character Set and Collation

```sql
SELECT @@character_set_server, @@collation_server, @@character_set_database, @@collation_database;
```

Flag: If `latin1` — MySQL 8.0 defaults to `utf8mb4`.

### 5. Schema-Level Character Sets

```sql
SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA;
```

### 6. Critical Global Variables

```sql
SHOW GLOBAL VARIABLES WHERE Variable_name IN (
  'lower_case_table_names','explicit_defaults_for_timestamp',
  'query_cache_type','query_cache_size','default_authentication_plugin',
  'innodb_strict_mode','sql_mode','optimizer_switch','log_warnings',
  'innodb_file_format','innodb_large_prefix'
);
```

| Variable | Issue | Impact |
|----------|-------|--------|
| `query_cache_type=ON` | 🔴 Removed in 8.0 | Performance regression |
| `sql_mode=''` | 🟡 8.0 defaults strict | Apps may break |
| `log_warnings` | 🟡 Removed in 8.0 | Replace with `log_error_verbosity` |
| `innodb_strict_mode=OFF` | 🟡 8.0 defaults ON | Preserve in parameter group |

### 7. Stored Procedures and Functions

```sql
SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE, DEFINER
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
```

### 8. Triggers and Events with Null Definers

```sql
SELECT TRIGGER_SCHEMA, TRIGGER_NAME, DEFINER FROM information_schema.TRIGGERS
WHERE DEFINER = '' OR DEFINER IS NULL;
SELECT EVENT_SCHEMA, EVENT_NAME, DEFINER FROM information_schema.EVENTS
WHERE DEFINER = '' OR DEFINER IS NULL;
```

Flag: 🔴 Null definers cause precheck failures.

### 9. Partitioned Tables

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, PARTITION_METHOD FROM information_schema.PARTITIONS
WHERE PARTITION_METHOD IS NOT NULL
AND TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
```

### 10. Table Engines and Row Formats

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, TABLE_COLLATION, ROW_FORMAT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys')
AND TABLE_TYPE='BASE TABLE';
```

Flag: Non-InnoDB tables, COMPACT row format.

### 11. Foreign Keys, Views, Grants

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
WHERE REFERENCED_TABLE_NAME IS NOT NULL
AND TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
SELECT TABLE_SCHEMA, TABLE_NAME, DEFINER, SECURITY_TYPE FROM information_schema.VIEWS
WHERE TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
SELECT user, host, Super_priv, Grant_priv FROM mysql.user
WHERE user NOT IN ('rdsadmin','mysql.sys','rdsrepladmin');
```

### 12. Stale Table Statistics

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, UPDATE_TIME, TABLE_ROWS,
  DATEDIFF(NOW(), UPDATE_TIME) AS days_since_update
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys')
AND TABLE_TYPE = 'BASE TABLE'
AND (UPDATE_TIME IS NULL OR DATEDIFF(NOW(), UPDATE_TIME) > 7)
ORDER BY days_since_update DESC;
```

Flag: 🟡 Use this to record which tables have stale statistics as a pre-upgrade baseline — it helps you spot post-upgrade plan regressions. A major version upgrade invalidates optimizer statistics, so statistics are recalculated **after** the upgrade — see the post-upgrade checklist, which scopes `ANALYZE TABLE` to the affected tables in a low-traffic window.

## Result Analysis

Generate:

1. Categorized findings (🔴/🟡/🟢)
2. For each finding: what was found, why it matters, action to take
3. Recommended DB parameter group for target version preserving current behavior
