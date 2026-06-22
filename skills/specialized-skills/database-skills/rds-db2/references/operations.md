# RDS for Db2 — Operations Reference

---

## Scale compute (up/down)

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --db-instance-class db.m6i.2xlarge \
  --apply-immediately
```

Instance classes: `db.t3.*` (burstable), `db.m6i.*` (general purpose), `db.r6i.*` (memory optimized), `db.x2iedn.*` (memory optimized, up to 128 vCPU / 4 TiB RAM).

Scaling compute causes a brief outage (Multi-AZ minimizes this to ~60 seconds).

---

## Scale storage

Storage can be scaled **up** but **not down**. To reduce storage, you must create a new instance and migrate data.

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --allocated-storage 500 \
  --apply-immediately
```

Enable storage autoscaling:

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --max-allocated-storage 1000
```

---

## Parameter groups

### View modifiable parameters

```bash
aws rds describe-db-parameters \
  --db-parameter-group-name <param-group-name> \
  --query 'Parameters[?IsModifiable==`true`].[ParameterName,ParameterValue,Description]' \
  --output table
```

### Modify a parameter

```bash
aws rds modify-db-parameter-group \
  --db-parameter-group-name <param-group-name> \
  --parameters "ParameterName=<name>,ParameterValue=<value>,ApplyMethod=immediate"
```

### Non-modifiable instance-level parameters

Parameters that are managed by RDS and cannot be changed:

- `db2comm` (always TCPIP)
- `svcename` (managed by RDS)
- `diagpath` (managed by RDS)
- `notifylevel` (managed by RDS)
- Instance owner and home directory settings

### Find Db2 registry variables modifiable in RDS

```sql
-- Connect to RDSADMIN
SELECT name, value, deferred
FROM TABLE(rdsadmin.list_db_registry_variables()) AS t;
```

Modify a registry variable:

```sql
call rdsadmin.set_db_registry_variable('<VAR_NAME>', '<VALUE>');
```

---

## RDSADMIN stored procedures

Key stored procedures available to the master user:

| Procedure | Purpose |
|---|---|
| `rdsadmin.create_database(dbname, pagesize, codeset, territory, collation)` | Create a new database |
| `rdsadmin.drop_database(dbname)` | Drop a database |
| `rdsadmin.restore_database(dbname, type, prefix, bucket, region)` | Restore from S3 |
| `rdsadmin.rollforward_database(dbname, log_prefix, bucket, region)` | Apply archive logs |
| `rdsadmin.complete_rollforward(dbname)` | Complete rollforward, make DB connectable |
| `rdsadmin.backup_database(dbname, prefix, bucket, region)` | Backup to S3 |
| `rdsadmin.grant_db_authority(dbname, username, authority)` | Grant DBADM authority to a user |
| `rdsadmin.revoke_db_authority(dbname, username, authority)` | Revoke DBADM authority |
| `rdsadmin.create_bufferpool(dbname, bpname, size, automatic, extended, pagesize)` | Create bufferpool |
| `rdsadmin.create_tablespace(dbname, tsname, bpname, pagesize)` | Create tablespace |
| `rdsadmin.update_db_param(dbname, param, value, deferred)` | Update database config parameter |
| `rdsadmin.set_configuration(key, value)` | Set RDS-level configuration |
| `rdsadmin.get_task_status(...)` | Monitor async task progress |
| `rdsadmin.list_databases()` | List all databases on the instance |
| `rdsadmin.list_db_registry_variables()` | List Db2 registry variables |
| `rdsadmin.set_db_registry_variable(name, value)` | Set a Db2 registry variable |

---

## Load data from S3

RDS for Db2 supports loading data directly from S3 using `DB2REMOTE` identifiers.

### Create storage access alias

```sql
-- On RDS for Db2 (IAM role handles auth — no credentials needed):
db2 "CATALOG STORAGE ACCESS ALIAS myS3 VENDOR S3 
     SERVER https://s3.<region>.amazonaws.com 
     CONTAINER <bucket-name> 
     DBUSER <masterUserName>"
```

### Load from S3

```sql
CALL SYSPROC.ADMIN_CMD('LOAD FROM DB2REMOTE://myS3/<path/to/file.ixf> OF IXF INSERT INTO <schema>.<table>');
```

Or using LOAD CLIENT from a connected Db2 client:

```bash
db2 "LOAD CLIENT FROM /local/path/file.ixf OF IXF INSERT INTO <schema>.<table>"
```

---

## Monitoring

### Enable Enhanced Monitoring

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --monitoring-interval 60 \
  --monitoring-role-arn arn:aws:iam::<account>:role/rds-monitoring-role
```

Enhanced monitoring data goes to CloudWatch Logs group `RDSOSMetrics`. Metrics include CPU, memory, disk I/O, network at OS level (1–60 second granularity).

### Enable db2diag logs to CloudWatch

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --cloudwatch-logs-export-configuration '{"EnableLogTypes":["diag"]}'
```

Logs appear in CloudWatch Logs group `/aws/rds/instance/<instance-id>/diag`.

**Encrypt the log group.** db2diag logs can contain sensitive diagnostic data, so
encrypt the CloudWatch Logs group with a KMS key:

```bash
aws logs associate-kms-key \
  --log-group-name /aws/rds/instance/<instance-id>/diag \
  --kms-key-id <kms-key-arn>
```

### Download db2diag logs to laptop

```bash
# List available log files
aws rds describe-db-log-files \
  --db-instance-identifier <instance-id>

# Download a specific log file
aws rds download-db-log-file-portion \
  --db-instance-identifier <instance-id> \
  --log-file-name <log-file-name> \
  --output text > db2diag.log
```

### Create CloudWatch dashboard from Enhanced Monitoring

Enhanced monitoring data is in CloudWatch Logs (not CloudWatch Metrics directly). Use CloudWatch Logs Insights to query and build dashboards:

```
fields @timestamp, cpuUtilization.total, memory.free
| filter @logStream like /RDSOSMetrics/
| sort @timestamp desc
| limit 100
```

Or use the RDS console → Monitoring tab → Enhanced monitoring for a built-in view.

### Run basic monitoring from Db2 client

```sql
-- Active connections
SELECT application_name, application_id, connection_start_time
FROM TABLE(MON_GET_CONNECTION(CAST(NULL AS BIGINT), -1)) AS t;

-- Database memory usage
SELECT pool_id, pool_cur_size, pool_config_size
FROM TABLE(MON_GET_MEMORY_POOL(NULL, -1)) AS t;

-- Top SQL by CPU
SELECT substr(stmt_text,1,80) AS sql, total_cpu_time, num_executions
FROM TABLE(MON_GET_PKG_CACHE_STMT(NULL, NULL, NULL, -1)) AS t
ORDER BY total_cpu_time DESC FETCH FIRST 10 ROWS ONLY;
```

---

## Enable Audit

RDS for Db2 audit logging is configured through an RDS **option group** with the `DB2_AUDIT` option (backed by an IAM role and an S3 bucket), followed by the in-database `CREATE AUDIT POLICY` / `AUDIT DATABASE USING POLICY` flow. For the full sourced procedure, see `db2-audit.md`.

---

## Performance benchmarks with HammerDB

Source: https://aws.amazon.com/blogs/database/use-hammerdb-to-run-performance-tests-on-amazon-rds-for-db2/

HammerDB supports TPC-C and TPC-H workloads against Db2. Install HammerDB on an EC2 instance in the same VPC as the RDS instance. Configure the Db2 driver with the RDS endpoint, port, and credentials. Run TPC-C for OLTP benchmarks and TPC-H for analytical workloads.

---

## Enable standby replica (see ha-dr.md)

See `ha-dr.md` for full standby replica setup.

---

## Enable read replica

RDS for Db2 supports read replicas as a separate feature for offloading read workloads. See `ha-dr.md` for details. Note that standby replicas (DR replicas in mounted/HADR mode) cannot serve reads while in standby mode.
