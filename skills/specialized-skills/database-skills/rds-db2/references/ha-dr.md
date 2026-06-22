# RDS for Db2 — High Availability and Disaster Recovery Reference

Source blog: https://aws.amazon.com/blogs/database/configure-amazon-rds-for-db2-standby-replicas-for-high-availability-and-faster-disaster-recovery/

---

## Multi-AZ (in-region HA)

- Synchronous block-level replication to a standby in a different AZ within the same Region
- Automatic failover in ~60 seconds if primary fails
- CNAME endpoint automatically redirects to promoted standby — same endpoint, reconnect required
- RPO: 0 | RTO: 1–2 minutes
- Enable at creation or via modify:

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --multi-az \
  --apply-immediately
```

---

## Standby Replica (cross-region DR)

Uses IBM Db2 HADR in **SUPERASYNC** mode. Asynchronous replication — some data loss possible.

- Up to 3 standby replicas per primary (same or different Region)
- Cannot serve reads while in standby mode — promote to standalone for read/write
- License: only 2 vCPUs per replica regardless of instance size
- Supports Db2 11.5 (both AE and SE, BYOL and Marketplace)

### RPO / RTO comparison

| Feature | RPO | RTO |
|---|---|---|
| Multi-AZ | 0 | 1–2 min |
| Standby replica (in-region or cross-region) | Seconds | Minutes |
| PiTR (in-region) | ~5 min | Hours |
| PiTR (cross-region) | ~25 min | Hours |

### Prerequisites

- Automated backups enabled on primary
- Custom parameter group in target region (BYOL: `customer_id` and `site_id` required)
- KMS multi-region key, or create new KMS key in secondary region
- All databases on primary must be in active state before creating replica
- All `rdsadmin` stored procedure operations (create/drop/restore/rollforward) must complete before creating replica
- After replica is created, **cannot add new databases** to primary without first removing the replica

### Create standby replica (console)

RDS Console → Databases → select instance → Actions → Create replica → Replica mode: Standby → choose region

### Create standby replica (CLI)

```bash
aws rds create-db-instance-read-replica \
  --db-instance-identifier <replica-name> \
  --source-db-instance-identifier arn:aws:rds:<source-region>:<account>:db:<primary-name> \
  --db-parameter-group-name <param-group-in-dr-region> \
  --replica-mode mounted \
  --kms-key-id <kms-key-arn> \
  --region <dr-region>
```

### Promote standby replica

```bash
# Console: Databases → select replica → Actions → Promote
aws rds promote-read-replica \
  --db-instance-identifier <replica-name> \
  --region <dr-region>
```

After promotion, connect to the promoted instance:

```bash
db2 catalog TCPIP node <node_name> remote <promoted-endpoint> server <port>
db2 catalog database <dbname> as <alias> at node <node_name>
db2 connect to <dbname> user <master-user> using '<password>'
```

### Monitor replication lag

```bash
# CloudWatch metric: ReplicaLag (seconds)
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name ReplicaLag \
  --dimensions Name=DBInstanceIdentifier,Value=<replica-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average
```

Set a CloudWatch alarm when ReplicaLag exceeds your RTO threshold.

### Important replication behaviors

- Local users are replicated to replicas; master user is NOT replicated (can be modified on replica)
- Database configurations ARE replicated
- NOT replicated: storage access aliases, non-inline LOBs, external stored procedure binaries
- LOAD command runs in non-recoverable mode — data loaded via LOAD is NOT replicated
- When replica is created, `BLOCKNONLOGGED` and `LOGINDEXBUILD` are set to YES on primary automatically

### Delete standby replica

```bash
aws rds delete-db-instance \
  --db-instance-identifier <replica-name> \
  --skip-final-snapshot \
  --region <dr-region>
```

---

## Switch MAZ instance (failover)

Force a failover to the standby (Multi-AZ):

```bash
aws rds reboot-db-instance \
  --db-instance-identifier <instance-id> \
  --force-failover
```

---

## Colocate applications with the active AZ

After a Multi-AZ failover, the primary moves to the standby's AZ. To minimize latency, deploy application servers in the same AZ as the current primary.

Check current AZ of the primary:

```bash
aws rds describe-db-instances \
  --db-instance-identifier <instance-id> \
  --query 'DBInstances[0].AvailabilityZone' \
  --output text
```

Use Amazon Route 53 ARC (Application Recovery Controller) to automate traffic routing without changing application endpoints. See: https://aws.amazon.com/blogs/database/configure-amazon-rds-for-db2-standby-replicas-for-high-availability-and-faster-disaster-recovery/

For the full application-tier colocation pattern — an Auto Scaling group spanning both AZs behind an ALB, EventBridge `failover`-event alerting, and connecting via the RDS endpoint rather than IPs — see `colocation.md`.

---

## Read Replica

RDS for Db2 supports read replicas as a separate feature. Read replicas allow read-only workloads to be offloaded from the primary instance. Standby replicas (DR replicas in mounted/HADR mode) cannot serve reads while in standby mode — they must be promoted to a standalone instance for read/write operations.
