# RDS Pre-Upgrade Checklist — MySQL, MariaDB, PostgreSQL

## Step 1: Take a Manual Snapshot

Create a snapshot before starting. This is your rollback safety net regardless of upgrade method:

```bash
aws rds create-db-snapshot \
  --db-instance-identifier <instance-id> \
  --db-snapshot-identifier <instance-id>-pre-upgrade-snapshot \
  --region <region>
```

## Step 2: Check Automated Backup Status

Automated backups are NOT required for in-place upgrades. However:

- If automated backups ARE enabled, RDS automatically takes a pre-upgrade snapshot before starting the upgrade. This is a safety net you get for free.
- If automated backups are NOT enabled, RDS skips the pre-upgrade snapshot and proceeds directly. You lose that automatic rollback point.
- Automated backups ARE required for Blue/Green deployments (replication depends on them).

```bash
aws rds describe-db-instances \
  --db-instance-identifier <instance-id> \
  --query "DBInstances[0].BackupRetentionPeriod" \
  --region <region>
```

If `0` and you want the automatic pre-upgrade snapshot (recommended):

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --backup-retention-period 7 \
  --apply-immediately \
  --region <region>
```

## Step 3: Check for Pending Maintenance

Pending maintenance actions can block upgrades. Apply them first:

```bash
aws rds describe-pending-maintenance-actions \
  --resource-identifier <instance-arn> \
  --region <region>
```

## Step 4: Run the RDS Pre-Upgrade Validation

For MySQL 5.7 to 8.0 major upgrades, RDS automatically runs a prechecks script as part of the upgrade process. If prechecks fail, the upgrade is aborted and the instance stays on the current version.

You can preview what the prechecker will find by running it yourself before initiating the upgrade. Connect to the database and run:

```sql
-- MySQL: check for issues the RDS prechecker will flag
CALL mysql.rds_upgrade_prechecks();
```

If this procedure is not available, the key checks the prechecker runs are:

- Reserved keywords used as identifiers (table names, column names)
- Orphaned InnoDB tables (`.frm` without `.ibd`)
- Tables using non-native partitioning
- Triggers or events with null definers
- Incompatible data types or character sets

Review the output and fix any issues BEFORE initiating the upgrade.

## Step 5: Check for Reserved Keywords

MySQL 8.0 added new reserved keywords. If your schema uses any of these as unquoted identifiers, the upgrade prechecker will flag them:

`CUME_DIST`, `DENSE_RANK`, `EMPTY`, `EXCEPT`, `FIRST_VALUE`, `GROUPING`, `GROUPS`, `JSON_TABLE`, `LAG`, `LAST_VALUE`, `LATERAL`, `LEAD`, `NTH_VALUE`, `NTILE`, `OF`, `OVER`, `PERCENT_RANK`, `RANK`, `RECURSIVE`, `ROW`, `ROWS`, `ROW_NUMBER`, `SYSTEM`, `WINDOW`

Fix by quoting with backticks or renaming before the upgrade.

## Step 6: Create a Target Parameter Group (Optional)

If you don't create a custom parameter group, RDS will assign the default parameter group for the target version family (e.g., `default.mysql8.0`). This uses MySQL 8.0 defaults which differ from 5.7 in several ways.

If you want to preserve current behavior, create a custom parameter group:

```bash
aws rds create-db-parameter-group \
  --db-parameter-group-name mysql80-from-57 \
  --db-parameter-group-family mysql8.0 \
  --description "MySQL 8.0 preserving 5.7 behavior" \
  --region <region>
```

Key parameters to preserve (MySQL 5.7 to 8.0):

| Parameter | 5.7 Default | 8.0 Default | Action |
|-----------|-------------|-------------|--------|
| character_set_server | latin1 | utf8mb4 | Set to latin1 if needed |
| collation_server | latin1_swedish_ci | utf8mb4_0900_ai_ci | Set to match |
| sql_mode | empty | STRICT_TRANS_TABLES,... | Set empty if app relies on permissive mode |
| innodb_strict_mode | OFF | ON | Set OFF if needed |
| log_error_verbosity | N/A (was log_warnings) | 2 | Set to match old log_warnings value |

Note: `query_cache_type` and `query_cache_size` are removed in 8.0 — no parameter to set. If your app relied on query cache, handle at the application layer.

## Step 7: Test on a Snapshot-Restored Instance

Restore your snapshot and upgrade the test instance to validate:

```bash
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier <instance-id>-upgrade-test \
  --db-snapshot-identifier <instance-id>-pre-upgrade-snapshot \
  --db-instance-class <same-class> \
  --region <region>
```

Then upgrade the test instance:

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id>-upgrade-test \
  --engine-version <target-version> \
  --allow-major-version-upgrade \
  --apply-immediately \
  --region <region>
```

After the test instance is upgraded and available:

1. Validate database operations — connect, run key queries, check schema integrity
2. Verify application connectivity — point your application (or a test instance of it) at the upgraded test database and confirm the application driver works correctly with the new engine version. Auth plugin changes (e.g., `caching_sha2_password` in MySQL 8.0), TLS requirements, and connection string parameters may behave differently.

## Step 8: Consider Blue/Green Deployment

For production instances, Blue/Green is safer than in-place:

- Creates a staging copy on the target version
- Keeps it in sync via replication
- Switchover with typically under 1 minute of downtime

Requirements: automated backups enabled, binlog_format=ROW (MySQL/MariaDB), engine version supports Blue/Green (MySQL 5.7+, MariaDB 10.4+, PostgreSQL 12.7+).

## Step 9: Review Target Version Release Notes

Before upgrading, review the release notes for the target version to understand behavioral changes, new features, and deprecations. Key changes to watch for are called out below by engine.

**MySQL** (e.g., 5.7 → 8.0):

- New data dictionary (no more `.frm` files)
- New TempTable engine replaces MEMORY for internal temp tables
- GROUP BY no longer implicitly sorts results
- Query cache removed entirely
- Default auth plugin changed to `caching_sha2_password`
- Release notes: https://dev.mysql.com/doc/relnotes/mysql/8.0/en/

**MariaDB** (e.g., 10.6 → 10.11 or 11.4):

- Each major version introduces new SQL features, optimizer changes, and storage engine updates
- Check for deprecated features being removed in the target version
- Release notes: https://mariadb.com/kb/en/release-notes/

**PostgreSQL** (e.g., 14 → 15 or 16):

- Each major version refines the planner cost model, which can change query plans
- New features like Memoize (PG 14), work_mem changes (PG 15), subquery decorrelation (PG 16)
- Extension compatibility may change between major versions
- Release notes: https://www.postgresql.org/docs/release/

You SHOULD read the "Incompatible Changes" or "Removed Features" section of the target version's release notes before proceeding.

## Step 10: Notify Stakeholders

Before executing:

- Notify application teams about the maintenance window
- Confirm connection strings don't hardcode the engine version
- Verify application compatibility with the target version
- For MySQL 5.7 to 8.0: warn about GROUP BY implicit sort removal, strict mode default, auth plugin changes
