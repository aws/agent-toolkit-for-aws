# RDS for Oracle — Connection Auth

Authentication patterns and quick cross-language connection overview. Language-specific deep-dives in `python.md`, `java.md`, `nodejs.md`, `dotnet.md`.

## Two supported auth methods

1. **Username/password** — stored in the DB or fetched from AWS Secrets Manager at runtime.
2. **Kerberos** — external auth via AWS Managed Microsoft AD, `IDENTIFIED EXTERNALLY`.

Never log in as **SYS** or **SYSTEM** on RDS Oracle — those are reserved. Use the master user created at DB setup.

## a) Username/password direct

Even in development, prefer fetching credentials from AWS Secrets Manager at runtime to avoid accidental leakage in source control or logs. Direct credential use is strongly discouraged; production MUST use Secrets Manager.

## b) Username/password via AWS Secrets Manager (recommended)

Store creds in a JSON secret matching the RDS format:

```json
{
  "username": "dbadmin",
  "password": "your-password",
  "engine": "oracle",
  "host": "mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com",
  "port": 1521,
  "dbname": "ORCL"
}
```

Create the secret once (store the JSON above; never commit it to source control):

```bash
aws secretsmanager create-secret \
  --name oracle/myapp/db-creds \
  --secret-string file://db-creds.json
```

Fetch at runtime. Python example:

```python
import json, boto3, oracledb

def get_connection(secret_name: str, region: str = "us-east-1") -> oracledb.Connection:
    client = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(client.get_secret_value(SecretId=secret_name)["SecretString"])
    dsn = f'{secret["host"]}:{secret["port"]}/{secret["dbname"]}'
    return oracledb.connect(user=secret["username"], password=secret["password"], dsn=dsn)
```

IAM policy for the app's role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:<secret-name>*"
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>",
      "Condition": { "StringEquals": { "kms:ViaService": "secretsmanager.<region>.amazonaws.com" } }
    }
  ]
}
```

`kms:Decrypt` is required when the secret uses a customer-managed KMS key (default `aws/secretsmanager` doesn't need it but add it for best practice).

**Rotation**: enable automatic rotation on the secret. RDS for Oracle supports single-user and multi-user rotation strategies. Always fetch fresh — don't cache long-term.

## c) Kerberos with AWS Managed Microsoft AD

Users connect without passwords, using their Active Directory identity.

### Prerequisites

- AWS Managed Microsoft AD (AWS Directory Service) — same account or shared via RAM
- For on-prem AD users: one-way forest trust on-prem → AWS Managed AD
- IAM role with `AmazonRDSDirectoryServiceAccess` managed policy
- RDS Oracle with "Password and Kerberos authentication" enabled

### Step 1 — create the IAM role

```bash
aws iam create-role \
  --role-name rds-directoryservice-kerberos-access-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect":"Allow","Principal":{"Service":"rds.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }'

aws iam attach-role-policy \
  --role-name rds-directoryservice-kerberos-access-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonRDSDirectoryServiceAccess
```

### Step 2 — join RDS to the directory

```bash
# New instance
aws rds create-db-instance \
  --db-instance-identifier my-oracle-kerberos \
  --db-instance-class db.r5.large \
  --engine oracle-ee \
  --license-model bring-your-own-license \
  --master-username admin --master-user-password <pw> \
  --allocated-storage 100 \
  --db-subnet-group-name my-db-subnet-group \
  --vpc-security-group-ids sg-xxxxxxxx \
  --port 1521 \
  --storage-encrypted --kms-key-id <kms-key-arn> \
  --domain d-xxxxxxxxxx \
  --domain-iam-role-name rds-directoryservice-kerberos-access-role

# Or modify existing
aws rds modify-db-instance \
  --db-instance-identifier my-oracle-instance \
  --domain d-xxxxxxxxxx \
  --domain-iam-role-name rds-directoryservice-kerberos-access-role \
  --apply-immediately
```

### Step 3 — verify kerberos-enabled

```bash
aws rds describe-db-instances \
  --db-instance-identifier my-oracle-kerberos \
  --query 'DBInstances[*].DomainMemberships' --output table
```

Status should show **`kerberos-enabled`**.

### Step 4 — create the DB user (UPPERCASE, IDENTIFIED EXTERNALLY)

```sql
-- For an on-prem AD user joedoe@onprem.local
CREATE USER "JOEDOE@ONPREM.LOCAL" IDENTIFIED EXTERNALLY;
GRANT CREATE SESSION TO "JOEDOE@ONPREM.LOCAL";

-- For an AWS Managed AD user
CREATE USER "JOEDOE@AD.MYAWS.COM" IDENTIFIED EXTERNALLY;
GRANT CREATE SESSION TO "JOEDOE@AD.MYAWS.COM";
```

Username **must be uppercase** and the realm suffix is required.

### Step 5 — client config

`krb5.conf` (`/etc/krb5.conf` Linux, `C:\Oracle_Home\krb5.conf` Windows):

```ini
[libdefaults]
  default_realm = ONPREM.LOCAL
  default_ccache_name = /tmp/kerbcache

[realms]
  AD.MYAWS.COM = { kdc = ad.myaws.com; admin_server = ad.myaws.com }
  ONPREM.LOCAL = { kdc = onprem.local; admin_server = onprem.local }

[domain_realm]
  .ad.myaws.com = AD.MYAWS.COM
  .onprem.local = ONPREM.LOCAL
```

`sqlnet.ora`:

```
SQLNET.AUTHENTICATION_SERVICES = (KERBEROS5PRE,KERBEROS5)
SQLNET.KERBEROS5_CONF = /etc/krb5.conf
SQLNET.KERBEROS5_CONF_MIT = TRUE
SQLNET.KERBEROS5_CC_NAME = /tmp/kerbcache
SQLNET.FALLBACK_AUTHENTICATION = TRUE
```

On Windows, use `OSMSFT:` for `KERBEROS5_CC_NAME` to use the Windows in-memory ticket. **SQL Developer does NOT support `OSMSFT:`** — it requires a ticket file from `okinit`.

### Step 6 — connect

```bash
# Generate ticket (Linux)
okinit joedoe@ONPREM.LOCAL

# sqlplus — no password
sqlplus /@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL

# SQL Developer: Authentication Type = Kerberos, no password, hostname/port/service as usual
```

## Quick pick — which driver for my language?

| Language | Driver | Mode | Notes |
|---|---|---|---|
| Python | `oracledb` ≥ 6.0 | thin (default) | cx_Oracle is legacy — migrate |
| Java | `ojdbc11.jar` (23.x) | thin | UCP or HikariCP for pooling |
| Java Spring Boot | `ojdbc11` + HikariCP | thin | built into Spring Boot defaults |
| Node.js | `node-oracledb` ≥ 6 | thin (default) | module-level `createPool` for Lambda |
| .NET | `Oracle.ManagedDataAccess.Core` | thin | built-in pooling, cross-platform |
| SQL Developer / DBeaver | ojdbc (bundled) | thin | GUI tools |
| Toad for Oracle | Oracle Instant Client | thick | Toad cannot do thin mode |
| sqlplus | Oracle Instant Client | thick | classic CLI |
| SQLcl | bundled ojdbc | thin (default) | Java 11+ required |

See the language-specific references for code examples and pooling.

## Thin vs thick mode

**Prefer thin mode**. It avoids the Oracle Client install entirely. Oracle is deprecating thick mode (OCI).

Thick mode is only needed for:

- Kerberos with in-memory tickets (on Windows, for sqlplus — not SQL Developer)
- LDAP directory service
- Oracle Wallet-based (sqlnet.ora) Advanced Security
- Advanced Queuing (AQ)

For everything else (including TLS, Secrets Manager), thin mode is sufficient.
