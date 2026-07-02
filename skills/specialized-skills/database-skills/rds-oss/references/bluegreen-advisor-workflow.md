# RDS Blue/Green Deployment Advisor Workflow

Guide customers through RDS Blue/Green deployments for DDL changes, table maintenance, and major version upgrades on RDS MySQL, MariaDB, and PostgreSQL. Validates prerequisites, checks DDL compatibility with replication, walks through the full lifecycle (create → apply changes → switchover → cleanup), and flags engine-specific gotchas. Never executes switchover without explicit user confirmation.

## When This Applies

User mentions: "blue green deployment", "zero downtime DDL", "schema change with minimal downtime", "switchover", "how to do DDL on RDS without downtime", major version upgrade with zero-downtime requirement. Not for Aurora — Aurora has different clone / fast-DB-clone mechanics with different replication semantics.

## Tasks

### 1. Verify Prerequisites

**Constraints:**

- You MUST verify `aws` CLI is available and credentials are valid
- You MUST check the source instance is in `available` state before creating a Blue/Green deployment
- You MUST verify automated backups are enabled — Blue/Green replication depends on them
- For MySQL/MariaDB: you MUST verify `binlog_format=ROW` is set and in-sync — Blue/Green uses binlog replication
- For PostgreSQL: you MUST verify engine version supports Blue/Green (PostgreSQL 12.7+)
- For PostgreSQL: you MUST verify `rds.logical_replication=1` is set — PostgreSQL Blue/Green uses logical replication (not binlog)
- You MUST check for pending maintenance actions on the source and advise resolving them first

### 2. Assess DDL Compatibility

Determine if the planned change is safe for Blue/Green replication.

**Constraints:**

- You MUST ask the user what DDL or maintenance operation they plan to run
- For MySQL/MariaDB, you MUST check [bluegreen-ddl-mysql.md](bluegreen-ddl-mysql.md) for the full matrix. Key patterns:
  - **Breaking**: type changes (`MODIFY COLUMN`, `CHANGE COLUMN`), `ADD COLUMN ... AFTER`, table/column rename — break binlog replication, switchover immediately after
  - **Safe**: `ADD COLUMN` at end, `ADD INDEX`/`DROP INDEX`, `OPTIMIZE TABLE`, `ANALYZE TABLE` — replication continues
- For PostgreSQL, you MUST check [bluegreen-ddl-postgresql.md](bluegreen-ddl-postgresql.md) for the full matrix. Key patterns:
  - **Breaking**: `ALTER COLUMN ... TYPE`, `ADD COLUMN` with volatile defaults (e.g., `DEFAULT now()`, `gen_random_uuid()`), table/column rename — break logical replication, switchover immediately after
  - **Safe**: `ADD COLUMN` with NULL or static default, `CREATE INDEX CONCURRENTLY`, `ADD`/`DROP CHECK`
- You MUST recommend the right approach: Blue/Green if compatible, or an alternative (pt-osc, gh-ost, manual plan) if not
- You MUST NOT recommend Blue/Green for simple in-place-safe operations (`ADD INDEX` with INPLACE, `ANALYZE`), because provisioning time and green-environment cost are not justified

### 3. Create Blue/Green Deployment

**Constraints:**

- You MUST provide the correct CLI command. For both RDS MySQL/MariaDB and RDS PostgreSQL:

  ```bash
  aws rds create-blue-green-deployment \
    --blue-green-deployment-name <name> \
    --source <instance-arn>
  ```

- You MUST recommend monitoring status until `AVAILABLE` before proceeding to DDL
- You MUST NOT proceed to DDL until the green environment is fully synced

### 4. Apply Changes on Green

**Constraints:**

- You MUST instruct the user to connect to the green environment endpoint (not blue) — the whole point is to apply changes on green without affecting production traffic
- You MUST recommend verifying the green schema matches blue before applying changes
- You MUST warn if the DDL will break replication and advise proceeding directly to switchover after
- For PostgreSQL: you MUST warn about logical replication slot lag monitoring via `pg_stat_replication` and `pg_replication_slots`

### 5. Switchover

**Constraints:**

- You MUST recommend setting green to read-only briefly before switchover to avoid conflicts in transit
- You MUST NOT execute `aws rds switchover-blue-green-deployment` without explicit user confirmation, because switchover is customer-visible and irreversible-in-place
- You MUST recommend a switchover timeout appropriate for the database size (default 300s, up to 900s for large databases)
- You MUST explain that during switchover: writes pause briefly, endpoints swap, no connection string changes needed on the application side
- For PostgreSQL: you MUST warn that the Blue/Green-managed logical replication slot is dropped during switchover — any downstream consumers of that specific slot need re-establishment. Other logical replication slots (e.g., Debezium, DMS) on the same instance are NOT dropped.

### 6. Post-Switchover Validation

**Constraints:**

- You MUST recommend verifying schema changes are in place on the production endpoint
- You MUST recommend checking row counts and application connectivity
- For PostgreSQL: you MUST recommend resetting sequences after switchover, because PostgreSQL sequences are NOT replicated by logical replication and the new primary's sequences may be behind. Provide the fix:

  ```sql
  SELECT setval('my_table_id_seq', (SELECT MAX(id) FROM my_table));
  ```

  Remind the user to check ALL serial/identity columns, not just the one throwing errors.
- You MUST note the old blue environment remains for rollback and incurs charges until deleted

### 7. Cleanup

**Constraints:**

- You MUST provide the delete commands for both the Blue/Green deployment resource and the old blue environment
- You MUST warn that the old environment incurs standard billing until deleted
- You MUST recommend keeping the old blue for at least 24–72 hours after switchover — it's the cheapest rollback path if an unexpected regression emerges

## Troubleshooting

- **Binlog not enabled (MySQL/MariaDB)**: Set `binlog_format=ROW` in parameter group and reboot. Verify in-sync status.
- **Logical replication not enabled (PostgreSQL)**: Set `rds.logical_replication=1` in parameter group and reboot.
- **Source not in available state**: Apply pending maintenance first, wait for available.
- **Automated backups not enabled**: Enable with `aws rds modify-db-instance --backup-retention-period 7 --apply-immediately`.
- **Switchover timeout**: Increase timeout to 600–900 s for large databases.
- **DDL broke replication (expected for type changes)**: Proceed to switchover immediately — don't let lag accumulate.
- **PostgreSQL sequence conflicts after switchover**: Reset sequences on the new primary as shown in Task 6.
- **Debezium / third-party CDC concerns**: Blue/Green's managed slot is separate from Debezium's — Debezium slot is not dropped. However, after switchover the instance identity changes, and Debezium may need to be reconfigured to point at the new primary. Test the full flow in non-production first.

## References

- [bluegreen-ddl-mysql.md](bluegreen-ddl-mysql.md) — full DDL compatibility matrix for MySQL/MariaDB binlog replication
- [bluegreen-ddl-postgresql.md](bluegreen-ddl-postgresql.md) — full DDL compatibility matrix for PostgreSQL logical replication, plus sequences / LISTEN/NOTIFY / extension gotchas
