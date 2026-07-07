# Connection Auth — SQL Auth, Secrets Manager, Credentials

## Overview

Authentication options on RDS SQL Server:

| Auth type | Requires | Drivers that support | When to use |
|---|---|---|---|
| **SQL auth** | Username + password in SQL Server | All (pymssql, pyodbc, .NET, JDBC, tedious) | Default choice |
| Windows auth (Kerberos) | Domain join + AD DNS CNAME | pyodbc, .NET, JDBC (+ Kerberos) | Enterprise AD shops |
| Windows auth (NTLM) | Domain join (weaker) | pyodbc, .NET, JDBC, tedious | Fallback only |
| **IAM auth** | RDS Proxy + tokens | All | Serverless, per-identity audit |

For Windows auth details, see `ad-kerberos.md`. For IAM auth via RDS Proxy, see `rds-proxy.md`.

## SQL auth — master user

During RDS provisioning, a master user is created:

```bash
aws rds create-db-instance \
  --db-instance-identifier mydb \
  --engine sqlserver-se \
  --master-username admin \
  --master-user-password '<strong-pw>' \
  --allocated-storage 100 \
  --db-instance-class db.m6i.large \
  --region us-east-1
```

The master user has `processadmin`, `securityadmin`, `dbcreator`, and `serveradmin` roles. It does NOT have `sysadmin` (SA) because RDS restricts that.

## SQL auth — application users

Best practice: don't use the master user for applications. Create scoped logins:

```sql
-- As master user, create app login
CREATE LOGIN app_user WITH PASSWORD = 'strong-password-here';

-- Create user in app database
USE mydb;
CREATE USER app_user FOR LOGIN app_user;

-- Grant minimum privileges
ALTER ROLE db_datareader ADD MEMBER app_user;
ALTER ROLE db_datawriter ADD MEMBER app_user;
GRANT EXECUTE ON SCHEMA::dbo TO app_user;   -- stored procs
```

## Password policy

RDS SQL Server enforces Windows password policy by default:

- Minimum 8 chars
- Must have 3 of: uppercase, lowercase, digit, special char
- Cannot contain the login name

To disable for a login (not recommended):

```sql
ALTER LOGIN app_user WITH CHECK_POLICY = OFF, CHECK_EXPIRATION = OFF;
```

## Secrets Manager — storing credentials

Store credentials as a JSON secret matching the RDS format:

```bash
aws secretsmanager create-secret \
  --name rds/sqlserver/app \
  --description "App credentials for RDS SQL Server prod" \
  --secret-string '{
    "engine": "sqlserver",
    "host": "mydb.xxxx.us-east-1.rds.amazonaws.com",
    "port": 1433,
    "username": "app_user",
    "password": "strong-password-here",
    "dbname": "mydb"
  }'
```

Using this standard JSON shape makes Secrets Manager rotation work out of the box.

## Automatic rotation

Enable automatic rotation using AWS-managed Lambda rotation functions:

```bash
aws secretsmanager rotate-secret \
  --secret-id rds/sqlserver/app \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:111122223333:function:SecretsManagerRDSMSSQLRotationSingleUser \
  --rotation-rules '{"AutomaticallyAfterDays":30}'
```

Two rotation strategies:

- **Single-user rotation** — same login, rotate password. Simple. Apps must handle reconnect on 18456.
- **Alternating-users rotation** — two logins (`app_user_a`, `app_user_b`). Rotate one while the other is in use. Zero-downtime but more complex setup.

For alternating users, create both logins first:

```sql
CREATE LOGIN app_user_a WITH PASSWORD = '...';
CREATE LOGIN app_user_b WITH PASSWORD = '...';
USE mydb;
CREATE USER app_user_a FOR LOGIN app_user_a;
CREATE USER app_user_b FOR LOGIN app_user_b;
ALTER ROLE db_datareader ADD MEMBER app_user_a;
ALTER ROLE db_datareader ADD MEMBER app_user_b;
-- grant same perms to both
```

## Fetching the secret in code

### Python

```python
import boto3, json
sm = boto3.client("secretsmanager", region_name="us-east-1")
c = json.loads(sm.get_secret_value(SecretId="rds/sqlserver/app")["SecretString"])

import pymssql
conn = pymssql.connect(
    server=c["host"], port=str(c["port"]),
    user=c["username"], password=c["password"], database=c["dbname"],
    tds_version="7.3", encryption="require",
)
```

### .NET

```csharp
var sm = new AmazonSecretsManagerClient(RegionEndpoint.USEast1);
var r = await sm.GetSecretValueAsync(new() { SecretId = "rds/sqlserver/app" });
var c = JsonSerializer.Deserialize<DbCreds>(r.SecretString);

var connStr = $"Server={c.Host},{c.Port};Database={c.DbName};" +
              $"User Id={c.Username};Password={c.Password};Encrypt=Mandatory;";
```

### Java

```java
SecretsManagerClient sm = SecretsManagerClient.create();
String json = sm.getSecretValue(
    GetSecretValueRequest.builder().secretId("rds/sqlserver/app").build()
).secretString();
JsonNode c = new ObjectMapper().readTree(json);
String url = String.format(
    "jdbc:sqlserver://%s:%d;databaseName=%s;encrypt=true",
    c.get("host").asText(), c.get("port").asInt(), c.get("dbname").asText()
);
```

### Node.js (AWS SDK v3)

```javascript
const { SecretsManagerClient, GetSecretValueCommand } =
  require("@aws-sdk/client-secrets-manager");
const sm = new SecretsManagerClient({});
const { SecretString } = await sm.send(new GetSecretValueCommand({
  SecretId: "rds/sqlserver/app"
}));
const c = JSON.parse(SecretString);
```

## Caching secrets

Don't call `GetSecretValue` on every DB call — it's an AWS API call with latency and cost.

- **Lambda**: cache at module scope. Re-fetch on 18456.
- **ECS/EC2/EKS**: cache in memory with TTL (5-30 min), OR use the Secrets Manager caching library:
  - Python: `aws-secretsmanager-caching`
  - Java: `com.amazonaws:aws-secretsmanager-caching-java`
  - .NET: `AWSSDK.SecretsManager.Caching`
  - Node.js: custom — set a 15-min cache + refresh on failure

### Handling rotation — reconnect on 18456

When a secret rotates, existing pool connections fail with `18456` on the next use. Handle it:

```python
# SQLAlchemy approach
from sqlalchemy import event

@event.listens_for(engine, "handle_error")
def handle_error(exception_context):
    exc = exception_context.original_exception
    if "18456" in str(exc) or "Login failed" in str(exc):
        # Dispose pool and re-fetch secret
        _creds_cache.invalidate()
        exception_context.chained_exception = None
```

Or simpler: set `pool_recycle` to the rotation interval (e.g. 30 days × 0.9 = recycle every 27 days).

## IAM policy for apps

Minimum permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-*"
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "arn:aws:kms:us-east-1:111122223333:key/<kms-key-id>",
      "Condition": {
        "StringEquals": {"kms:ViaService": "secretsmanager.us-east-1.amazonaws.com"}
      }
    }
  ]
}
```

The `kms:ViaService` condition scopes KMS decrypt to Secrets Manager calls — defense in depth.

## Parameter Store (SSM) — alternative for non-rotating secrets

For config values and non-credential secrets, AWS Systems Manager Parameter Store is cheaper than Secrets Manager (free for standard parameters).

```bash
aws ssm put-parameter --name "/app/db/host" \
  --value "mydb.xxxx.us-east-1.rds.amazonaws.com" --type String
aws ssm put-parameter --name "/app/db/username" \
  --value "app_user" --type SecureString
```

Not recommended for passwords you want rotated — Parameter Store doesn't have built-in rotation like Secrets Manager does.

## Verify auth is working

```sql
SELECT
  system_user,                    -- current login
  original_login_name,            -- original login (before any SETUSER)
  auth_scheme,                    -- SQL / KERBEROS / NTLM
  session_id = @@SPID
FROM sys.dm_exec_connections
WHERE session_id = @@SPID;
```

For SQL auth, `auth_scheme` will be `SQL`. `KERBEROS` / `NTLM` indicates Windows auth — see `ad-kerberos.md`.
