# Troubleshooting — RDS SQL Server Connection Errors

## How to diagnose (order matters)

1. **TCP reachability** — can you open a socket?
2. **TLS handshake** — does the cert chain validate?
3. **Login** — does authentication succeed?
4. **Post-login** — does the query work?

Most issues are at layer 1 (network). Start with `nc` / `Test-NetConnection` before worrying about drivers.

## Login failed for user (error 18456)

The most common SQL Server error. State codes tell you why (visible only in SQL Server's own error log):

| State | Meaning | Typical fix |
|---|---|---|
| 2, 5 | Invalid userid | Login doesn't exist — `SELECT * FROM sys.server_principals WHERE name = 'user'` |
| 6 | Windows login used as SQL | Use Windows auth, or create SQL login |
| 7 | Login disabled | `ALTER LOGIN [x] ENABLE` |
| 8 | Incorrect password | Fetch current password from Secrets Manager; check for rotation |
| 9 | Invalid password (bad chars) | Password has chars the client couldn't transmit (check encoding) |
| 11, 12 | Valid login but server access failure | Login doesn't have login permission — `GRANT CONNECT SQL TO [login]` |
| 18 | Change password required | Login must change on next logon (policy) |
| 38, 40 | DB not found / not accessible | Wrong `Database=` or user has no access to that DB |
| 58 | Not configured for Windows auth (using Kerberos/NTLM on SQL-only server) | Enable Windows auth on RDS (domain join) |

To read the SQL Server error log from RDS:

```bash
aws rds describe-db-log-files \
  --db-instance-identifier mydb \
  --filename-contains error

aws rds download-db-log-file-portion \
  --db-instance-identifier mydb \
  --log-file-name "log/ERROR" \
  --output text --query 'LogFileData' > error-log.txt
grep "18456" error-log.txt   # find login failures with state
```

### Rotation-related 18456

When Secrets Manager rotates the password, existing app connections (using cached creds) fail at next use. Symptoms:

- Intermittent 18456 after 30-day rotation schedule
- All replicas hit it around the same time
- Fresh invocations succeed (they fetch the new secret)

Fix: re-fetch the secret on 18456 and rebuild the connection pool.

```python
# SQLAlchemy pattern
from sqlalchemy import event

@event.listens_for(engine, "handle_error")
def on_error(ctx):
    if "18456" in str(ctx.original_exception):
        _creds_cache.invalidate()   # force re-fetch on next connection
```

## Cannot generate SSPI context

Kerberos authentication handshake failure. See `ad-kerberos.md` for full details. Quick diagnosis:

```powershell
# Client-side (Windows) — do you have a TGT?
klist
# Look for: MSSQLSvc/mydb.corp.example.com:1433

# Does the CNAME resolve?
Resolve-DnsName mydb.corp.example.com

# Does the SPN exist?
setspn -L <service-account>
```

Most common causes (in order):

1. **Connected to RDS endpoint, not CNAME** → no SPN for endpoint → Kerberos fails
2. **CNAME doesn't resolve** → DNS problem
3. **SPN missing** → self-managed AD needs manual setspn
4. **Clock skew > 5 min** from DC → NTP issue

## auth_scheme shows NTLM instead of KERBEROS

Kerberos attempted, fell back to NTLM. Same root cause analysis as SSPI errors:

- Most likely: client connected to RDS endpoint rather than the CNAME
- Fix: use CNAME
- Verify after fix:

```sql
SELECT auth_scheme FROM sys.dm_exec_connections WHERE session_id = @@SPID
-- Expected: KERBEROS
```

## Connection timeout (no specific error)

The TCP connection couldn't be established. Check in order:

### 1. Security groups

```bash
# RDS SG — inbound rules
aws ec2 describe-security-groups --group-ids sg-rds-sqlserver \
  --query 'SecurityGroups[0].IpPermissions'
# Should show TCP 1433 with the app SG or client CIDR as source
```

Same VPC → use SG ID. Cross-VPC → use CIDR (SG refs don't cross VPC boundary).

### 2. Route tables

For cross-VPC connections:

```bash
aws ec2 describe-route-tables --route-table-ids rtb-xxxx \
  --query 'RouteTables[0].Routes'
# Must have a route to the RDS VPC CIDR via TGW/peering
```

### 3. NACLs (stateless — often forgotten)

```bash
aws ec2 describe-network-acls --filters Name=vpc-id,Values=vpc-xxxx
```

Check:

- Inbound: allow 1433
- Outbound: allow ephemeral ports 1024-65535 (return traffic)

### 4. RDS instance state

```bash
aws rds describe-db-instances --db-instance-identifier mydb \
  --query 'DBInstances[0].DBInstanceStatus'
# Expected: available
```

If `modifying`, `rebooting`, `storage-full`, `failed` → check events for cause.

### 5. Lambda in VPC

Lambda without NAT/VPC endpoint can't reach Secrets Manager → hangs on `get_secret_value` before even attempting RDS. Check `lambda-vpc.md`.

## Certificate validation errors

### `.NET — Could not establish trust relationship for the SSL/TLS secure channel`

Install RDS CA bundle:

```powershell
Import-Certificate -FilePath global-bundle.pem `
  -CertStoreLocation Cert:\LocalMachine\Root
```

### `Java — PKIX path building failed`

Client doesn't have RDS CA in truststore. See `encryption.md` for split-and-import pattern. The common mistake is using `keytool -import` on the multi-cert `global-bundle.pem` — keytool imports only the **first** cert.

### `Python — SSL: CERTIFICATE_VERIFY_FAILED`

Set `SSL_CERT_FILE=/path/to/global-bundle.pem` env var before connecting. For pymssql, also install the bundle in the system cert store.

### `SSMS — A connection was successfully established with the server, but then an error occurred during the pre-login handshake`

TLS version mismatch (client < 1.2, server requires 1.2+). Upgrade SSMS to 18.x or newer. Same error can be cert trust — check both.

## SSL_SERVER_DN_MATCH errors through SSM tunnel

Cert CN is the RDS endpoint, but client connects to `localhost` through the tunnel. Two options:

### Dev only — trust without CN check

```
Server=localhost,11433;...;TrustServerCertificate=True;
```

```python
# pymssql
conn = pymssql.connect(..., encryption="request")  # less strict than "require"
```

### Better — for any non-trivial use

Don't tunnel for production. Use VPC-resident compute (EC2/ECS/Lambda) with the real endpoint.

## pymssql-specific errors

### `pymssql.OperationalError: (20002, b'DB-Lib error message 20002, severity 9: Adaptive Server connection failed')`

Generic — check:

- `port="1433"` is a string, not int
- `tds_version="7.3"` is set (default 4.2 fails on modern RDS)
- `encryption="require"` (or force the server side to not require TLS for testing)

### `pymssql.InterfaceError: Connection to the database failed for an unknown reason`

Usually TLS handshake failure. Install `global-bundle.pem` in OS cert store.

### `ImportError: DLL load failed` on Windows

pymssql wheel missing FreeTDS. Switch to pyodbc on Windows.

## .NET-specific errors

### `A connection was successfully established... but then error occurred during pre-login handshake`

Either TLS version or cert trust:

- `.NET Framework < 4.7` defaults to TLS 1.0 → upgrade Framework or set `ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12`
- Cert chain — install CA bundle

### `The target principal name is incorrect. Cannot generate SSPI context`

Windows auth — see SSPI section above.

### `Login timeout expired`

Connection timeout too short or network slow. Default is 15 seconds. Increase:
`Server=...;Connection Timeout=30;`

## Java / JDBC errors

### `com.microsoft.sqlserver.jdbc.SQLServerException: The driver could not establish a secure connection`

TLS issue. Either:

- JDK version doesn't support TLS 1.2 — use JDK 11+
- Truststore missing CA — build truststore from global-bundle.pem
- JDK FIPS settings blocking RSA cipher — check `java.security` file

### `PKIX path building failed`

Truststore doesn't trust the RDS CA. Rebuild truststore with `keytool -import` on each cert from `global-bundle.pem` (split first — see `encryption.md`).

### `Connection timed out: no further information`

Network. Same TCP reachability checks as above.

## Node.js / tedious errors

### `ConnectionError: Failed to connect to ... in 15000ms`

Default connect timeout too short. Increase:

```javascript
options: { connectTimeout: 30000 }
```

### `TypeError: Cannot read property 'Length' of undefined`

Usually parse error on pre-login response. Often means plaintext connection to server that requires TLS, or vice versa. Check `options.encrypt` matches server config.

### `RequestError: Invalid object name`

Post-login — database/schema/table doesn't exist or user lacks permission. Not a connection issue.

## Access denied to Secrets Manager from Lambda

Lambda in VPC can't reach Secrets Manager endpoint:

- No NAT gateway AND no VPC endpoint for secretsmanager
- Create VPC endpoint (interface) in Lambda's subnets — see `networking.md`

Or Lambda execution role missing permission:

- `secretsmanager:GetSecretValue` on the secret ARN
- `kms:Decrypt` on the CMK (if customer-managed)

## Secrets not resolving in ECS task

ECS `secrets` in container definition uses the **execution role**, not the task role:

```json
{
  "executionRoleArn": "arn:aws:iam::111122223333:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::111122223333:role/app-task-role",
  "containerDefinitions": [{
    "secrets": [{"name": "DB_SECRET", "valueFrom": "arn:aws:secretsmanager:..."}]
  }]
}
```

The **execution role** needs `secretsmanager:GetSecretValue` + `kms:Decrypt`. Most common ECS secrets misconfiguration.

## Scripts for diagnosis

The skill ships with:

- `scripts/test_connection.py` — TCP + TLS + full login test (Linux/macOS from EC2 or laptop)
- `scripts/test_connection.ps1` — Same but PowerShell (Windows EC2 via SSM or local)
- `scripts/validate_ad_network.ps1` — AD domain + Kerberos diagnostics (Windows, domain-joined)

Run from the **source** of the connection, not from your laptop (unless laptop is the source).

```bash
python3 test_connection.py --server mydb.xxxx.us-east-1.rds.amazonaws.com \
  --user admin --password "$PW" --database mydb
```

## Verify connection state from SQL

After any successful connection, run:

```sql
SELECT
  session_id,
  login_name,                     -- who's authenticated
  auth_scheme,                    -- SQL, KERBEROS, NTLM
  encrypt_option,                 -- TRUE = TLS
  client_net_address,             -- client IP (proxy IP if using RDS Proxy)
  net_transport,
  client_interface_name,          -- driver name/version
  protocol_type
FROM sys.dm_exec_connections
WHERE session_id = @@SPID
```

This is the fastest way to confirm:

- Authentication worked and of what type
- Encryption is active
- Which driver is connected
- Whether you're going through a proxy

## Nothing works — escalation checklist

When all obvious paths have been tried:

- [ ] RDS instance `DBInstanceStatus == available`
- [ ] RDS engine version supported (modern SQL Server — 2019+)
- [ ] CloudWatch logs `rdsadmin/error` for server-side errors
- [ ] `aws rds describe-events --source-identifier mydb --source-type db-instance` for recent events
- [ ] Security group inbound: TCP 1433 from the right source (SG-ID same-VPC, CIDR cross-VPC)
- [ ] VPC has `enableDnsSupport=true` and `enableDnsHostnames=true`
- [ ] Client IAM permissions: `secretsmanager:GetSecretValue`, `kms:Decrypt`
- [ ] Client can resolve endpoint to private IP (nslookup returns 10.x.x.x)
- [ ] Client can reach port: `nc -zv <endpoint> 1433`
- [ ] Client has RDS CA bundle (or equivalent) in trust store
- [ ] Connection string uses correct driver-specific encrypt setting
- [ ] If Windows auth: client is on a domain-joined host, CNAME resolves, SPN exists, `klist` shows TGT
