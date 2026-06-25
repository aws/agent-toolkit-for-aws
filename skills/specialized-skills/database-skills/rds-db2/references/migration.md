# RDS for Db2 — Migration Reference

Source blogs:

- https://aws.amazon.com/blogs/database/data-migration-strategies-to-amazon-rds-for-db2/
- https://aws.amazon.com/blogs/database/restore-self-managed-db2-linux-databases-in-amazon-rds-for-db2/
- https://aws.amazon.com/blogs/database/near-zero-downtime-migrations-from-self-managed-db2-on-aix-or-windows-to-amazon-rds-for-db2-using-ibm-q-replication/
- https://aws.amazon.com/blogs/database/performance-optimization-of-full-load-and-ongoing-replication-tasks-from-self-managed-db2-to-amazon-rds-for-db2/

---

## Migration strategy overview

| Strategy | Source OS | Method | Downtime |
|---|---|---|---|
| Rehost | Linux (LE) | Db2 backup/restore or Db2MT | Offline: full downtime; Online: minimal |
| Replatform | AIX, Windows, z/OS, zLinux | Db2MT + DMS or Q Replication | Near-zero with replication |

**Rehost** (Linux → Linux): Faster, no data conversion. Use Db2 native backup/restore or Db2MT.
**Replatform** (AIX/Windows/z/OS → Linux): Requires data conversion. Use Db2MT for metadata + data, then DMS or Q Replication for CDC.

---

## Migration precheck tool

Source: https://aws.amazon.com/blogs/database/restore-self-managed-db2-linux-databases-in-amazon-rds-for-db2/

Run before the final backup. Catches blocking issues early.

```bash
# Direct (local)
curl -sL https://bit.ly/precheckdb2migration | bash

# Download + run
curl -sL https://bit.ly/precheckdb2migration -o db2_migration_prereq_check.sh
chmod +x db2_migration_prereq_check.sh
./db2_migration_prereq_check.sh

# Remote (from Db2 client)
export DB2USER=<db2-user> DB2PASSWORD=<db2-password> DBNAME=<db-name>
./db2_migration_prereq_check.sh --verbose

# Non-interactive (CI/CD)
DB2_INSTANCES=db2inst1 ./db2_migration_prereq_check.sh
```

### Key checks performed

| Check | Common failure / fix |
|---|---|
| `db2updv115` | Must be run on source DB before backup — most common restore failure |
| InDoubt transactions | `db2 list indoubt transactions with prompting` |
| Invalid objects | `db2 "call SYSPROC.ADMIN_REVALIDATE_DB_OBJECTS()"` |
| Tablespace state | All must be Normal |
| Non-fenced routines | Convert all to fenced — non-fenced not permitted in RDS |
| Automatic storage | At least one storage group must exist |
| Database config | Backup/rollforward/restore/upgrade pending must all be No |
| Log files | Circular ≤254, archive ≤4096 |

### Readiness levels

- **READY FOR MIGRATION** — all checks passed
- **REVIEW REQUIRED** — warnings found, manual review needed
- **NOT READY FOR MIGRATION** — critical failures, must fix before proceeding

---

## Rehost: one-time migration (Linux → RDS)

### Using Db2 backup + restore stored procedure

Take a multi-part backup (parallel streams improve S3 restore performance):

```bash
db2 backup database <DBNAME> to /backup, /backup, /backup, /backup, /backup
# Produces .001 .002 .003 .004 .005 parts
```

Copy to S3 (create storage alias first):

```bash
# On EC2 with IAM role — no credentials needed:
db2 "CATALOG STORAGE ACCESS ALIAS db2S3 VENDOR S3 SERVER https://s3.<region>.amazonaws.com CONTAINER <bucket> DBUSER <masterUser>"

# Self-managed Db2 with long-term credentials:
db2 "CATALOG STORAGE ACCESS ALIAS db2S3 VENDOR S3 SERVER s3.<region>.amazonaws.com USER $AWS_ACCESS_KEY_ID PASSWORD $AWS_SECRET_ACCESS_KEY CONTAINER <bucket> DBUSER <masterUser>"

# Backup directly to S3:
db2 backup database <DBNAME> to DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3
```

Restore on RDS for Db2:

```sql
call rdsadmin.restore_database('<DBNAME>', 'OFFLINE', '<s3-prefix>', '<bucket>', '<region>');
```

The `s3_prefix` is the common part of the backup image filenames excluding `.001`, `.002`, etc.

### Performance tuning for restore

```sql
call rdsadmin.set_configuration('RESTORE_DATABASE_NUM_BUFFERS', '100');
call rdsadmin.set_configuration('RESTORE_DATABASE_PARALLELISM', '10');
call rdsadmin.set_configuration('RESTORE_DATABASE_NUM_MULTI_PATHS', '5');
call rdsadmin.set_configuration('USE_STREAMING_RESTORE', 'TRUE');
```

---

## Rehost: online migration with log replication (Linux → RDS)

1. Take online backup to S3 (same as above but `backup_type = 'ONLINE'`)
2. Restore on RDS:

   ```sql
   call rdsadmin.restore_database('<DBNAME>', 'ONLINE', '<s3-prefix>', '<bucket>', '<region>');
   ```

3. Copy archive logs to S3 and apply:

   ```sql
   call rdsadmin.rollforward_database('<DBNAME>', '<log-s3-prefix>', '<bucket>', '<region>');
   ```

4. Repeat step 3 until all logs applied, then complete:

   ```sql
   call rdsadmin.complete_rollforward('<DBNAME>');
   ```

---

## Replatform: AIX/Windows → RDS (near-zero downtime with Q Replication)

Source: https://aws.amazon.com/blogs/database/near-zero-downtime-migrations-from-self-managed-db2-on-aix-or-windows-to-amazon-rds-for-db2-using-ibm-q-replication/

### Architecture

- EC2 instance hosts Q Replication server (IBM MQ + Db2 + IIDR)
- Q Capture reads source Db2 recovery logs
- Q Apply writes to RDS for Db2 target
- Db2MT handles initial data load from AIX/Windows to S3, then RDS loads from S3

### High-level steps

1. Set up EC2 with IBM MQ, Db2 client, and IIDR Q Replication
2. Catalog source and target databases with different aliases
3. Create MQ queues (RESTARTQ, ADMINQ, DATAQ1 with MAXDEPTH=99999999)
4. Create Q Replication control tables on RDS (requires RDSADMIN stored procedures for tablespaces):

   ```sql
   call rdsadmin.create_bufferpool('<DBNAME>', 'BPQASN', 10000, 'Y', 'Y', 8192);
   call rdsadmin.create_tablespace('<DBNAME>', 'QAQASN', 'BPQASN', 8192);
   ```

5. Create subscriptions with `HAS LOAD PHASE N` (Db2MT handles the load)
6. Start Capture and Apply to verify subscriptions activate
7. Record the start time of earliest in-flight transaction
8. Run Db2MT for initial data load to S3 → RDS
9. Restart Q Capture from before the Db2MT start time to catch up changes
10. Monitor `QASN.IBMQREP_APPLYMON.OLDEST_TRANS` — when it approaches current time, cutover

### Monitor replication lag

```sql
SELECT MONITOR_TIME, END2END_LATENCY, ROWS_APPLIED, OLDEST_TRANS
FROM QASN.IBMQREP_APPLYMON
ORDER BY MONITOR_TIME DESC FETCH FIRST 20 ROWS ONLY WITH UR;
```

---

## AWS DMS for migration

- Supports Db2 as source and RDS for Db2 as target.
- Supports **full load + CDC** for LUW sources.
- Does **NOT** support CDC from Db2 for z/OS (full load only from z/OS).
- No bulk load (uses inserts) — slower than native tools for very large tables.

## Lift and shift (same as rehost)

Use Db2 backup/restore via Db2MT or `rdsadmin.restore_database`. Fastest path when source is Linux LE.

## Zero downtime upgrade

Online restore + rollforward:

1. Take online backup of source
2. Restore to RDS (stays in rollforward-pending)
3. Continuously apply archive logs with `rdsadmin.rollforward_database`
4. At cutover, `rdsadmin.complete_rollforward`
5. Redirect apps to RDS endpoint

Alternative: Q Replication for continuous sync with a brief cutover window.

## AS/400 (IBM i) → RDS Db2

Use **AWS Mainframe Modernization Data Replication with Precisely** (from AWS Marketplace): IBM i source, RDS for Db2 target, initial load + CDC. Initial load uses inserts; pre-load large tables via Db2 federation or export/import, then start CDC from a timestamp.

## POWER/AIX → RDS Db2

Db2MT for metadata extraction and data unload to S3, then load into RDS. For near-zero downtime add Q Replication for CDC — see the Q Replication section above.

## Strategy decision tree

1. **Source Linux LE?** Rehost. Acceptable downtime → offline restore. None → online restore + rollforward or Q Replication.
2. **Source AIX/Windows?** Downtime OK → Db2MT one-time. None → Db2MT + Q Replication.
3. **Source z/OS?** See `mainframe-migration.md`. DMS (full load) or Qlik/Precisely/Q Replication (CDC).
4. **Source AS/400?** Precisely Mainframe Modernization Data Replication.
