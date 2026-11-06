# Authorization — Database Users, Grants, Profiles, OCI IAM Mapping, RAC

Database users, grants, profiles, and OCI IAM schema mappings for ODB@AWS. There is no `aws rds create-db-instance` / parameter-group workflow — user management happens in SQL, connected as SYS/SYSTEM (ExaDB-D) or ADMIN (Autonomous DB).

## Exadata Database Service — Application Users

Connect as SYS or SYSTEM via SQL*Plus / SQLcl:

```sql
CREATE USER app_user IDENTIFIED BY "<password>"
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp
  QUOTA UNLIMITED ON users;

-- Least-privilege
GRANT CREATE SESSION TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON schema.table_name TO app_user;

-- Or group via a role
CREATE ROLE app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON schema.table_name TO app_role;
GRANT app_role TO app_user;
```

### Password profile

```sql
CREATE PROFILE app_profile LIMIT
  FAILED_LOGIN_ATTEMPTS 5
  PASSWORD_LOCK_TIME 1/24      -- 1 hour lockout
  PASSWORD_LIFE_TIME 90
  PASSWORD_REUSE_TIME 365
  PASSWORD_REUSE_MAX 12
  SESSIONS_PER_USER 50
  IDLE_TIME 30;

ALTER USER app_user PROFILE app_profile;
```

### Read-only user

```sql
CREATE USER readonly_user IDENTIFIED BY "<password>"
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp;

GRANT CREATE SESSION TO readonly_user;
GRANT SELECT ON schema.table1 TO readonly_user;
GRANT SELECT ON schema.table2 TO readonly_user;
-- Avoid SELECT ANY TABLE unless absolutely necessary
```

## Autonomous Database — ADMIN and Application Users

`ADMIN` is created automatically at provisioning and cannot be dropped or locked. Reset password via OCI console or:

```bash
oci db autonomous-database update \
  --autonomous-database-id <ocid> \
  --admin-password "<new-password>"
```

Create application users as ADMIN:

```sql
CREATE USER app_user IDENTIFIED BY "<password>";
GRANT DWROLE TO app_user;                       -- data-warehouse
-- or
GRANT CONNECT, RESOURCE TO app_user;            -- transaction processing
ALTER USER app_user QUOTA UNLIMITED ON DATA;
```

### Service names on Autonomous DB

Workload type picks the service name:

| Service | Purpose |
|---|---|
| `<db>_high` | Highest resources; parallel queries |
| `<db>_medium` | Balanced |
| `<db>_low` | Serial queries; lowest resources |
| `<db>_tp` | Transaction processing |
| `<db>_tpurgent` | Urgent transaction processing |

## OCI IAM User-to-Schema Mapping

Map OCI IAM users or groups to Oracle schemas for centralized identity.

### Individual

```sql
CREATE USER oci_user IDENTIFIED GLOBALLY AS 'OCI_IAM_USER_OCID';
GRANT CREATE SESSION TO oci_user;
GRANT app_role TO oci_user;
```

### Group (shared schema)

```sql
CREATE USER shared_app_user IDENTIFIED GLOBALLY AS 'OCI_IAM_GROUP_OCID';
GRANT CREATE SESSION TO shared_app_user;
GRANT app_role TO shared_app_user;
```

### Verify

```sql
SELECT username, authentication_type, external_name
FROM dba_users
WHERE authentication_type = 'GLOBAL';
```

The OCID in `IDENTIFIED GLOBALLY AS` MUST exactly match the OCI IAM user or group OCID. Group membership changes take effect on next login — no database restart needed.

For the full OCI IAM auth flow, see **auth-oci-iam.md** (loaded reference).

## RAC Considerations

### Service names (never SIDs)

Always use service names with SCAN hostnames. SIDs bypass SCAN load balancing.

SCAN format: `<cluster-prefix>-scan.<subnet-domain>.<vcn-domain>.oraclevcn.com`.

### HA TNS descriptor

```
(DESCRIPTION=
  (ADDRESS_LIST=
    (LOAD_BALANCE=ON)
    (FAILOVER=ON)
    (ADDRESS=(PROTOCOL=TCPS)(HOST=cluster-abc-scan.sub1.vcn1.oraclevcn.com)(PORT=2484)))
  (CONNECT_DATA=
    (SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com)
    (SERVER=DEDICATED))
  (SECURITY=(SSL_SERVER_DN_MATCH=TRUE)))
```

### Fast Connection Failover (FCF)

Java + UCP:

```java
pds.setFastConnectionFailoverEnabled(true);
pds.setONSConfiguration("nodes=<ons-host>:<ons-port>");
```

Python + SQLAlchemy:

```python
engine = create_engine(..., pool_pre_ping=True, pool_recycle=1800)
```

### Parallel queries

Work across RAC nodes automatically. Autonomous DB: use `_high`. ExaDB-D: configure parallel degree in the service definition.

## Audit and Monitoring

Enable Oracle Database auditing for sensitive operations and forward logs to AWS for retention and alerting.

```sql
-- Unified Audit (Oracle 12c+, works on both ExaDB-D and Autonomous DB)
CREATE AUDIT POLICY app_dml_audit_pol
  ACTIONS SELECT, INSERT, UPDATE, DELETE
  ON schema.sensitive_table;

AUDIT POLICY app_dml_audit_pol BY app_user;

-- Audit failed logins
CREATE AUDIT POLICY failed_login_pol
  ACTIONS LOGON;

AUDIT POLICY failed_login_pol WHENEVER NOT SUCCESSFUL;
```

Forward Oracle audit logs to CloudWatch via the OCI Logging integration or a sidecar collector. Encrypt the CloudWatch log group with a customer-managed KMS key. Retain audit logs for at least 90 days. Alert on:

- Failed login attempts above a threshold (potential brute force)
- DDL changes on application-critical tables
- Password changes on privileged accounts (SYS, SYSTEM, ADMIN)

## Critical Rules

- Never grant DBA to application users.
- Group privileges via roles.
- Set password profiles for all non-SYS accounts.
- Store passwords in AWS Secrets Manager.
- Use service names, never SIDs.
- Use `LOAD_BALANCE=ON` and `FAILOVER=ON` in TNS descriptors.
- Enable FCF for Java + UCP on RAC.
- Set `pool_pre_ping=True` in SQLAlchemy to detect stale connections after RAC service relocation.
- Users on RAC are cluster-wide — create once, available on all nodes.
