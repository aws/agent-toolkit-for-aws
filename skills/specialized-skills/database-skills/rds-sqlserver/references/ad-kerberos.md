# Active Directory and Kerberos — RDS SQL Server Windows auth

Windows authentication on RDS SQL Server requires:

1. RDS domain-joined to AWS Managed Microsoft AD (recommended) or self-managed AD
2. RDS instance on Enterprise Edition or Standard Edition (not Web/Express)
3. CNAME registered in AD DNS pointing to the RDS endpoint
4. Clients running on domain-joined hosts (or using Kerberos keytab)

## Choose the domain

### AWS Managed Microsoft AD (recommended)

- Fully managed by AWS
- Multi-AZ by default
- RDS integration is turnkey — automatic SPN registration, DNS CNAMEs
- Same directory can serve EC2, RDS, FSx, WorkSpaces

```bash
aws ds create-microsoft-ad \
  --name corp.example.com \
  --short-name CORP \
  --password '<directory-password>' \
  --vpc-settings "VpcId=vpc-xxxx,SubnetIds=subnet-a,subnet-b" \
  --edition Standard
```

Get the Directory ID from the output (format: `d-xxxxxxxxxx`).

### Self-managed AD

Run your own AD on EC2 (or connect to on-prem AD via TGW/VPN). More complex — no automatic SPN management.

For self-managed AD, RDS needs:

- Trust relationship between Managed AD and self-managed AD, OR
- Direct domain join via RDS AD Connector

See AWS docs: "Using Windows Authentication with an Amazon RDS for SQL Server DB instance"

## Create an IAM role for RDS to access AD

```bash
aws iam create-role \
  --role-name rds-directory-access-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "rds.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name rds-directory-access-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonRDSDirectoryServiceAccess
```

The managed policy `AmazonRDSDirectoryServiceAccess` grants the minimum permissions RDS needs to interact with Directory Service for domain join.

## Domain-join the RDS instance

### New instance

```bash
aws rds create-db-instance \
  --db-instance-identifier mydb \
  --engine sqlserver-se \
  --engine-version 16.00.4085.2.v1 \
  --master-username admin \
  --master-user-password '<master-pw>' \
  --allocated-storage 100 \
  --db-instance-class db.m6i.large \
  --domain d-xxxxxxxxxx \
  --domain-iam-role-name rds-directory-access-role
```

### Existing instance

```bash
aws rds modify-db-instance \
  --db-instance-identifier mydb \
  --domain d-xxxxxxxxxx \
  --domain-iam-role-name rds-directory-access-role \
  --apply-immediately
```

Check domain membership status:

```bash
aws rds describe-db-instances \
  --db-instance-identifier mydb \
  --query 'DBInstances[0].DomainMemberships'
```

Statuses:

- `pending` → in progress
- `joined` → ready for Windows auth
- `failed` → check CloudWatch Logs `rdsadmin/error` for cause
- `kerberos-enabled` → all good (newer field name)

## Create SQL logins for AD users/groups

Connect as master user (SQL auth) and create a SQL login mapped to the Windows account:

```sql
-- For individual AD user (UPPERCASE is Microsoft best practice)
CREATE LOGIN [CORP\JOE.DOE] FROM WINDOWS;

-- For AD group (preferred — no maintenance when people join/leave)
CREATE LOGIN [CORP\DBA_TEAM] FROM WINDOWS;

-- Grant DB access
USE mydb;
CREATE USER [CORP\DBA_TEAM] FOR LOGIN [CORP\DBA_TEAM];
ALTER ROLE db_datareader ADD MEMBER [CORP\DBA_TEAM];
ALTER ROLE db_datawriter ADD MEMBER [CORP\DBA_TEAM];
```

**Case matters in some SQL configurations** — use UPPERCASE consistently. `CORP\joe.doe` and `CORP\JOE.DOE` can be different logins depending on server collation.

## The CNAME — critical for Kerberos

Kerberos requires the client to request a ticket for a service principal name (SPN). RDS has SPNs registered only for the domain CNAME format, not the RDS endpoint.

**You MUST connect to the CNAME, not the RDS endpoint.**

### CNAME format for AWS Managed Microsoft AD

`<db-instance-identifier>.<domain-fqdn>`

Example: if RDS instance is `mydb` and domain is `corp.example.com`, CNAME is:
`mydb.corp.example.com`

AWS Managed Microsoft AD **automatically** creates this CNAME in AD DNS when you domain-join. No manual step needed.

### Verify the CNAME resolves

From a domain-joined client:

```powershell
Resolve-DnsName mydb.corp.example.com
# Should return a CNAME to mydb.xxxx.us-east-1.rds.amazonaws.com,
# which then resolves to the private IP
```

### Verify the SPN exists

```powershell
setspn -L <rds-service-account>
# Should show MSSQLSvc/mydb.corp.example.com:1433
# and       MSSQLSvc/mydb.corp.example.com
```

### If the CNAME doesn't resolve

- Check DNS resolver: client's DNS must point at AD domain controllers, not public DNS
- For self-managed AD, create the CNAME manually:

```powershell
Add-DnsServerResourceRecordCName `
  -Name mydb `
  -ZoneName corp.example.com `
  -HostNameAlias mydb.xxxx.us-east-1.rds.amazonaws.com
```

## Client connection examples

### SSMS

- Server name: `mydb.corp.example.com,1433`  (**CNAME**, not RDS endpoint)
- Authentication: Windows Authentication
- SSMS uses the currently logged-in Windows user's Kerberos ticket

### .NET / SqlClient

```csharp
var connStr = "Server=mydb.corp.example.com,1433;" +
              "Database=mydb;" +
              "Integrated Security=True;" +
              "Encrypt=Mandatory;";
```

### Java / JDBC

```java
String url = "jdbc:sqlserver://mydb.corp.example.com:1433;"
           + "databaseName=mydb;"
           + "integratedSecurity=true;"
           + "authenticationScheme=JavaKerberos;"
           + "encrypt=true;";
```

### Python / pyodbc

```python
# pyodbc — on domain-joined Windows or Linux with krb5 + keytab
conn = pyodbc.connect(
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=mydb.corp.example.com,1433;"
    "Database=mydb;"
    "Trusted_Connection=Yes;"
    "Encrypt=Yes;"
)
```

**pymssql does NOT support Kerberos** — use pyodbc.

## auth_scheme shows NTLM instead of KERBEROS — common cause

Most common reason Kerberos falls back to NTLM:

1. **Client connected to RDS endpoint, not CNAME**
   - `mydb.xxxx.us-east-1.rds.amazonaws.com` has no SPN → Kerberos fails → NTLM fallback
   - Fix: connect to the CNAME

2. **SPN missing for the CNAME**
   - Usually only an issue with self-managed AD
   - Fix: `setspn -A MSSQLSvc/mydb.corp.example.com:1433 <service-account>`

3. **Client can't reach KDC (AD domain controller)**
   - Check port 88 (Kerberos), 389 (LDAP), 464 (kpasswd) to DCs
   - Fix: SG/firewall rules to DCs

4. **Client has no TGT**
   - Windows: `klist` — should show a TGT. If not, `kinit` or log off/on
   - Linux: check `/var/kerberos/krb5/user/` or `KRB5CCNAME` env var

Verify:

```sql
SELECT auth_scheme, client_net_address
FROM sys.dm_exec_connections WHERE session_id = @@SPID
```

`auth_scheme = KERBEROS` — success. `NTLM` — fall through to one of the above causes.

## Cannot generate SSPI context — common causes

Error: `The target principal name is incorrect. Cannot generate SSPI context`.

Root causes (diagnose in this order):

1. **CNAME doesn't resolve from the client** → DNS issue
2. **CNAME resolves but SPN not registered** → `setspn -L` missing entry
3. **Client clock skew > 5 min from DC** → NTP issue
4. **Firewall blocks Kerberos (port 88)** → SG or corporate firewall

Run `klist` (Windows) or `klist -e` (Linux) to see if you have a ticket for `MSSQLSvc/mydb.corp.example.com:1433`.

## Never test Windows auth via SSM send-command

SSM runs as the EC2 LocalSystem account, not the user's AD identity. Testing `Integrated Security=True` via SSM:

- Authenticates as the machine account (if domain-joined) or fails
- Tells you nothing about whether a user's Windows login works

For Windows auth testing: RDP into a domain-joined EC2 as the actual user and run SSMS or `sqlcmd -E`.

## Verify end-to-end

```sql
-- Connect as CORP\JOE.DOE via SSMS with Windows auth
SELECT
  system_user,       -- CORP\JOE.DOE
  auth_scheme,       -- KERBEROS (not NTLM)
  net_transport,
  client_net_address
FROM sys.dm_exec_connections WHERE session_id = @@SPID
```
