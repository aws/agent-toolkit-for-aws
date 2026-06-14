# Aurora MySQL Live Precheck Queries

Run these against the database to identify actual upgrade blockers and behavior changes.

## Connection Methods

### SSM Run Command with IAM Authentication (preferred)

IAM database authentication eliminates passwords entirely — the mysql client authenticates with a short-lived token generated from IAM credentials. Requires IAM auth enabled on the cluster and a database account configured for IAM auth.

```bash
aws ssm send-command --instance-ids {instance_id} --document-name "AWS-RunShellScript" \
  --parameters 'commands=["TOKEN=$(aws rds generate-db-auth-token --hostname {endpoint} --port 3306 --region {region} --username {iam_db_user}) && mysql -h {endpoint} -u {iam_db_user} --port=3306 --ssl-ca=/tmp/global-bundle.pem --enable-cleartext-plugin --password=$TOKEN -e \"{query}\""]' \
  --region {region} --output json --query "Command.CommandId"
```

The EC2 instance must have the RDS CA bundle (`global-bundle.pem`) available. Download it as a prior SSM command if needed: `curl -o /tmp/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`

### SSM Run Command with Secrets Manager (fallback)

Use when IAM database authentication is not enabled on the cluster. Credentials are retrieved from Secrets Manager at runtime so passwords never appear in SSM parameters or CloudTrail logs. The password is passed via a temporary options file to avoid exposure in the process list.

```bash
aws ssm send-command --instance-ids {instance_id} --document-name "AWS-RunShellScript" \
  --parameters 'commands=["SECRET=$(aws secretsmanager get-secret-value --secret-id {secret_arn} --query SecretString --output text --region {region}) && TMPFILE=$(mktemp) && chmod 600 $TMPFILE && printf \"[client]\\nuser=%s\\npassword=%s\\n\" \"$(echo $SECRET | jq -r .username)\" \"$(echo $SECRET | jq -r .password)\" > $TMPFILE && mysql --defaults-extra-file=$TMPFILE -h {endpoint} -e \"{query}\"; rm -f $TMPFILE"]' \
  --region {region} --output json --query "Command.CommandId"
```

Retrieve results:

```bash
aws ssm get-command-invocation --command-id {id} --instance-id {instance_id} --region {region}
```

If mysql client not installed:

- Amazon Linux 2: `sudo yum install -y mysql`
- Amazon Linux 2023: `sudo dnf install -y mariadb105`
- Ubuntu: `sudo apt-get install -y mysql-client`

If connection times out (error 110), check security groups:

- Aurora SG must allow inbound from EC2 SG on port 3306
- Add rule: `aws ec2 authorize-security-group-ingress --group-id {aurora_sg} --protocol tcp --port 3306 --source-group {ec2_sg} --region {region}`

### RDS Data API

```bash
aws rds-data execute-statement --resource-arn {cluster_arn} --secret-arn {secret_arn} \
  --database {db} --sql "{query}" --region {region}
```

## Precheck Queries

### 1. Reserved Keywords in Schema Objects

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
WHERE UPPER(COLUMN_NAME) IN ('CUME_DIST','DENSE_RANK','EMPTY','EXCEPT','FIRST_VALUE','GROUPING','GROUPS','JSON_TABLE','LAG','LAST_VALUE','LATERAL','LEAD','NTH_VALUE','NTILE','OF','OVER','PERCENT_RANK','RANK','RECURSIVE','ROW','ROWS','ROW_NUMBER','SYSTEM','WINDOW')
AND TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');

SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.TABLES
WHERE UPPER(TABLE_NAME) IN ('CUME_DIST','DENSE_RANK','EMPTY','EXCEPT','FIRST_VALUE','GROUPING','GROUPS','JSON_TABLE','LAG','LAST_VALUE','LATERAL','LEAD','NTH_VALUE','NTILE','OF','OVER','PERCENT_RANK','RANK','RECURSIVE','ROW','ROWS','ROW_NUMBER','SYSTEM','WINDOW')
AND TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
```

Flag: Any results = must quote with backticks or rename.

### 2. Authentication Plugins

```sql
SELECT user, host, plugin FROM mysql.user;
```

Flag: `mysql_native_password` still works but deprecated. `sha256_password` replaced by `caching_sha2_password`.

### 3. XA Transactions

```sql
XA RECOVER;
```

Flag: 🔴 Any results BLOCK the upgrade. Must commit or rollback first.

### 4. Server Character Set and Collation

```sql
SELECT @@character_set_server, @@collation_server, @@character_set_database, @@collation_database;
```

Flag: If `latin1` — MySQL 8.0 defaults to `utf8mb4`. New objects will differ unless parameter group preserves it.

### 5. Schema-Level Character Sets

```sql
SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA;
```

### 6. Critical Global Variables

```sql
SHOW GLOBAL VARIABLES WHERE Variable_name IN (
  'lower_case_table_names','explicit_defaults_for_timestamp','show_compatibility_56',
  'query_cache_type','query_cache_size','default_authentication_plugin',
  'innodb_strict_mode','sql_mode','optimizer_switch','log_warnings',
  'innodb_file_format','innodb_large_prefix'
);
```

Interpretation:

| Variable | Issue if... | Impact |
|----------|------------|--------|
| `query_cache_type=ON` | 🔴 Query cache REMOVED in 8.0 | Performance regression likely |
| `query_cache_size>0` | Memory was allocated to cache | Will be freed after upgrade |
| `sql_mode=''` (empty) | 🟡 8.0 defaults to strict mode | Apps may break unless preserved |
| `show_compatibility_56=ON` | 🔴 REMOVED in 8.0 | Monitoring querying INFORMATION_SCHEMA.GLOBAL_STATUS breaks |
| `log_warnings` | 🟡 REMOVED in 8.0 | Replace with `log_error_verbosity` |
| `innodb_strict_mode=OFF` | 🟡 8.0 defaults to ON | Preserve in parameter group |

### 7. Stored Procedures and Functions

```sql
SELECT ROUTINE_SCHEMA, ROUTINE_NAME, ROUTINE_TYPE, DEFINER
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys');
```

Flag: Need syntax review for deprecated constructs.

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

Flag: Non-native partitioning removed in 8.0.

### 10. Table Engines and Row Formats

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, TABLE_COLLATION, ROW_FORMAT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('information_schema','mysql','performance_schema','sys')
AND TABLE_TYPE='BASE TABLE';
```

Flag: Non-InnoDB tables, COMPACT row format (should be DYNAMIC).

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
Query `mysql.innodb_table_stats.last_update` (when InnoDB last **recalculated stats**),
not `information_schema.TABLES.UPDATE_TIME` (last DML — doesn't reflect stats freshness):

```sql
SELECT database_name, table_name, last_update,
  DATEDIFF(NOW(), last_update) AS days_since_stats_update
FROM mysql.innodb_table_stats
WHERE database_name NOT IN ('mysql','sys')
AND (last_update IS NULL OR DATEDIFF(NOW(), last_update) > 7)
ORDER BY days_since_stats_update DESC;
```

Flag: 🟡 If stats are older than 7 days, recommend running `ANALYZE TABLE` on affected tables before the upgrade. Stale statistics can cause the 8.0 optimizer (more cost-based than 5.7) to choose suboptimal plans right after upgrade. `ANALYZE TABLE` alone refreshes statistics — do NOT run `OPTIMIZE TABLE` routinely: on Aurora's InnoDB it triggers a full table rebuild (`ALTER TABLE ... FORCE`) under a metadata lock, warranted only for genuine dead-row bloat (high `DATA_FREE`), not for refreshing stats.

Action: For each table with stale stats:

```sql
ANALYZE TABLE schema_name.table_name;
-- Only if the table ALSO has significant dead-row bloat (high DATA_FREE), and in a
-- maintenance window — this rebuilds the table under a metadata lock:
-- OPTIMIZE TABLE schema_name.table_name;
```

## Result Analysis

After running queries, generate:

1. Categorized findings (🔴/🟡/🟢)
2. For each finding: what was found, why it matters, action to take
3. Recommended parameter group for target version preserving current behavior
