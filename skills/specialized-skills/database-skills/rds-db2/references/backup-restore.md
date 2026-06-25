# RDS for Db2 — Backup and Restore Reference

Source blog: https://aws.amazon.com/blogs/database/restore-self-managed-db2-linux-databases-in-amazon-rds-for-db2/

---

## Snapshot backup (automated / manual)

### Automated backups

RDS for Db2 takes daily automated backups during the backup window. Retention period: 0–35 days.

Enable/configure via console or CLI:

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --backup-retention-period 7 \
  --preferred-backup-window "02:00-03:00"
```

### Manual snapshot

```bash
aws rds create-db-snapshot \
  --db-instance-identifier <instance-id> \
  --db-snapshot-identifier <snapshot-name>
```

Restore from snapshot:

```bash
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier <new-instance-id> \
  --db-snapshot-identifier <snapshot-name>
```

Snapshots capture the entire RDS instance (all databases). They are stored in S3 managed by RDS (not your bucket).

---

## Enable S3 integration for backup/restore

RDS for Db2 requires an IAM role with S3 access to use `rdsadmin.restore_database` and `rdsadmin.backup_database`.

### Create IAM role

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket", "s3:PutObject", "s3:DeleteObject"],
    "Resource": [
      "arn:aws:s3:::<bucket-name>",
      "arn:aws:s3:::<bucket-name>/*"
    ]
  }]
}
```

Trust policy must allow `rds.amazonaws.com`. Because RDS (a service) assumes this role on your behalf, guard it against the confused-deputy problem with the `aws:SourceAccount` and `aws:SourceArn` condition keys:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "rds.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "<account-id>" },
      "ArnLike": { "aws:SourceArn": "arn:aws:rds:<region>:<account-id>:db:*" }
    }
  }]
}
```

### Associate role with RDS instance

```bash
aws rds add-role-to-db-instance \
  --db-instance-identifier <instance-id> \
  --role-arn arn:aws:iam::<account>:role/<role-name> \
  --feature-name S3_INTEGRATION
```

---

## Database backup to S3

### Create storage access alias (required before backup/restore)

On EC2 with IAM role (no credentials needed):

```sql
db2 "CATALOG STORAGE ACCESS ALIAS db2S3 VENDOR S3 
     SERVER https://s3.<region>.amazonaws.com 
     CONTAINER <bucket-name> 
     DBUSER <masterUserName>"
```

With explicit credentials (self-managed Db2):

```sql
db2 "CATALOG STORAGE ACCESS ALIAS db2S3 VENDOR S3 
     SERVER s3.<region>.amazonaws.com 
     USER $AWS_ACCESS_KEY_ID 
     PASSWORD $AWS_SECRET_ACCESS_KEY 
     CONTAINER <bucket-name> 
     DBUSER <masterUserName> 
     TOKEN $AWS_SESSION_TOKEN"
```

### Take multi-part backup to S3

Use multiple paths for parallel backup (recommended — improves restore performance):

```bash
# 5 parallel streams → produces .001 .002 .003 .004 .005
db2 backup database <DBNAME> to DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3, DB2REMOTE://db2S3

# For smaller databases, still use multi-part (minimum 5, up to 20 for large DBs)
# Single-part backup is NOT recommended — S3 streaming is less efficient
```

### Take backup to local filesystem (then copy to S3)

```bash
# Multi-part to local disk
db2 backup database <DBNAME> to /backup, /backup, /backup, /backup, /backup

# Copy to S3
aws s3 cp /backup/ s3://<bucket>/<prefix>/ --recursive
```

---

## Restore database from S3 to RDS

### Prerequisites

- S3 integration IAM role associated with the RDS instance
- Backup files in S3 (multi-part recommended)
- `USE_STREAMING_RESTORE = TRUE` for best performance

### Set restore performance parameters

```sql
call rdsadmin.set_configuration('RESTORE_DATABASE_NUM_BUFFERS', '100');
call rdsadmin.set_configuration('RESTORE_DATABASE_PARALLELISM', '10');
call rdsadmin.set_configuration('RESTORE_DATABASE_NUM_MULTI_PATHS', '5');
call rdsadmin.set_configuration('USE_STREAMING_RESTORE', 'TRUE');
```

### Offline restore

```sql
call rdsadmin.restore_database(
  '<DBNAME>',          -- target database name
  'OFFLINE',           -- backup type
  '<s3-prefix>',       -- common prefix of backup files (excluding .001, .002, etc.)
  '<bucket-name>',     -- S3 bucket
  '<region>'           -- AWS region
);
```

### Online restore (with rollforward)

```sql
call rdsadmin.restore_database(
  '<DBNAME>',
  'ONLINE',
  '<s3-prefix>',
  '<bucket-name>',
  '<region>'
);
-- Database is now in rollforward-pending state
```

Apply archive logs:

```sql
call rdsadmin.rollforward_database(
  '<DBNAME>',
  '<log-s3-prefix>',   -- prefix for archive log files in S3
  '<bucket-name>',
  '<region>'
);
-- Repeat as needed until all logs applied
```

Complete rollforward (makes database connectable):

```sql
call rdsadmin.complete_rollforward('<DBNAME>');
```

---

## Point-in-Time Restore (PiTR)

PiTR uses automated backups + transaction logs. Available within the backup retention window.

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier <source-instance-id> \
  --target-db-instance-identifier <new-instance-id> \
  --restore-time 2024-01-15T08:00:00Z
```

| PiTR type | RPO | RTO |
|---|---|---|
| In-region automated backups | ~5 minutes | Hours |
| Cross-region automated backups | ~25 minutes | Hours |

Enable cross-region automated backups:

```bash
aws rds create-db-instance-automated-backup-replication \
  --source-db-instance-arn arn:aws:rds:<source-region>:<account>:db:<instance-id> \
  --backup-retention-period 7 \
  --region <destination-region>
```

---

## Monitor backup/restore task status

```sql
-- Connect to RDSADMIN first
db2 connect to RDSADMIN user <master-user> using '<password>'

-- Check task status
SELECT VARCHAR(task_type,25) AS task_type,
       VARCHAR(lifecycle,15) AS lifecycle,
       created_at,
       completed_work_bytes
FROM TABLE(rdsadmin.get_task_status(null,null,null)) AS r
ORDER BY created_at DESC;

-- Check task output (most recent)
SELECT VARCHAR(r.task_type,25) AS task_type,
       VARCHAR(r.lifecycle,15) AS lifecycle,
       VARCHAR(bson_to_json(task_input_params),256) AS input_params,
       VARCHAR(r.task_output,1024) AS task_output
FROM TABLE(rdsadmin.get_task_status(null,null,null)) AS r
ORDER BY created_at DESC FETCH FIRST 1 ROW ONLY;
```

Helper function (if `functions.sh` is sourced):

```bash
get_task_status
get_task_output
```
