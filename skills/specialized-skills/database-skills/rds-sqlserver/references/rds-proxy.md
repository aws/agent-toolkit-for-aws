# RDS Proxy for SQL Server — IAM auth and connection pooling

RDS Proxy sits between your apps and RDS SQL Server, providing:

- **Connection pooling** at the proxy layer (reduces connection storms from Lambda/ECS/etc.)
- **IAM authentication** — generate short-lived tokens instead of using passwords directly
- **Improved resilience** — retain connections during Multi-AZ failovers (up to 66% faster)
- **Credentials managed by proxy** — apps don't touch DB passwords

## Prerequisites

- RDS SQL Server instance (any edition)
- Secrets Manager secret with the standard RDS JSON format
- IAM role allowing the proxy to read the secret
- VPC with subnets in at least 2 AZs for HA

## Create the proxy

### 1. IAM role for the proxy

```bash
# Trust policy
aws iam create-role \
  --role-name rds-proxy-sqlserver-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "rds.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Permissions — get secret + decrypt
aws iam put-role-policy \
  --role-name rds-proxy-sqlserver-role \
  --policy-name secret-access \
  --policy-document '{
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
  }'
```

### 2. Create the proxy

```bash
aws rds create-db-proxy \
  --db-proxy-name mydb-proxy \
  --engine-family SQLSERVER \
  --auth '[{
    "AuthScheme": "SECRETS",
    "SecretArn": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-AbCdEf",
    "IAMAuth": "REQUIRED",
    "ClientPasswordAuthType": "SQL_SERVER_AUTHENTICATION"
  }]' \
  --role-arn arn:aws:iam::111122223333:role/rds-proxy-sqlserver-role \
  --vpc-subnet-ids subnet-priv-a subnet-priv-b \
  --vpc-security-group-ids sg-rds-proxy \
  --require-tls
```

Important:

- `--engine-family SQLSERVER` — must specify
- `IAMAuth: REQUIRED` — clients must use IAM tokens (vs `DISABLED` for password passthrough)
- `--require-tls` — enforce TLS to the proxy

### 3. Register the DB instance

```bash
aws rds register-db-proxy-targets \
  --db-proxy-name mydb-proxy \
  --db-instance-identifiers mydb
```

Wait for the proxy to become `AVAILABLE`:

```bash
aws rds describe-db-proxies --db-proxy-name mydb-proxy \
  --query 'DBProxies[0].Status'
```

### 4. Security groups

- **Proxy SG** (sg-rds-proxy): inbound 1433 from app SG; outbound 1433 to RDS SG
- **RDS SG**: inbound 1433 from proxy SG (no longer need direct app → RDS path)
- **App SG**: outbound 1433 to proxy SG

## Use IAM auth from apps

### Python

```python
import boto3, pymssql

rds = boto3.client("rds", region_name="us-east-1")
proxy_endpoint = "mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com"

# Token lasts 15 minutes
token = rds.generate_db_auth_token(
    DBHostname=proxy_endpoint,
    Port=1433,
    DBUsername="app_user",       # SQL login name, not IAM user
    Region="us-east-1",
)

conn = pymssql.connect(
    server=proxy_endpoint,
    port="1433",
    user="app_user",
    password=token,              # IAM token as password
    database="mydb",
    tds_version="7.3",
    encryption="require",
)
```

### .NET

```csharp
using Amazon.RDS;
using Amazon.RDS.Util;

var token = RDSAuthTokenGenerator.GenerateAuthToken(
    RegionEndpoint.USEast1,
    "mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com",
    1433,
    "app_user"
);

var connStr = $"Server=mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com,1433;" +
              $"Database=mydb;User Id=app_user;Password={token};" +
              $"Encrypt=Mandatory;";
```

### Java

```java
RdsUtilities utilities = RdsUtilities.builder()
    .region(Region.US_EAST_1)
    .credentialsProvider(DefaultCredentialsProvider.create())
    .build();

String token = utilities.generateAuthenticationToken(builder -> builder
    .hostname("mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com")
    .port(1433)
    .username("app_user")
);

String url = "jdbc:sqlserver://mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com:1433;"
           + "databaseName=mydb;encrypt=true;";
Properties props = new Properties();
props.setProperty("user", "app_user");
props.setProperty("password", token);
```

### Node.js

```javascript
const { Signer } = require("@aws-sdk/rds-signer");

const signer = new Signer({
  region: "us-east-1",
  hostname: "mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com",
  port: 1433,
  username: "app_user",
});

const token = await signer.getAuthToken();

const pool = await sql.connect({
  server: "mydb-proxy.proxy-xxxx.us-east-1.rds.amazonaws.com",
  port: 1433,
  database: "mydb",
  user: "app_user", password: token,
  options: { encrypt: true, trustServerCertificate: false },
});
```

## IAM permissions on the app

The app's IAM role (instance profile / task role / Lambda execution role) needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["rds-db:connect"],
    "Resource": "arn:aws:rds-db:us-east-1:111122223333:dbuser:prx-0123456789abcdef0/app_user"
  }]
}
```

The resource ARN format is `arn:aws:rds-db:<region>:<account>:dbuser:<proxy-resource-id>/<db-user>`. Get the proxy resource ID from:

```bash
aws rds describe-db-proxies --db-proxy-name mydb-proxy \
  --query 'DBProxies[0].DBProxyArn'
```

## Token lifecycle

- Tokens expire after **15 minutes**
- Generate a fresh token for each new connection
- Already-authenticated connections stay valid until idle timeout
- For connection pools: regenerate the token on reconnect (wrap `getPool()` around token generation)

## Password passthrough (alternative — no IAM)

If you want RDS Proxy's pooling benefits without IAM tokens, set `IAMAuth: DISABLED`:

```bash
aws rds create-db-proxy ... \
  --auth '[{
    "AuthScheme": "SECRETS",
    "SecretArn": "arn:...",
    "IAMAuth": "DISABLED",
    "ClientPasswordAuthType": "SQL_SERVER_AUTHENTICATION"
  }]'
```

App connects with the SQL user and password from Secrets Manager (fetched normally). Proxy forwards to RDS using its own credentials from the secret. Apps still benefit from pooling and failover resilience.

## Connection pooling at proxy

Tune via `MaxConnectionsPercent` and `MaxIdleConnectionsPercent`:

```bash
aws rds modify-db-proxy-target-group \
  --db-proxy-name mydb-proxy \
  --target-group-name default \
  --connection-pool-config '{
    "MaxConnectionsPercent": 80,
    "MaxIdleConnectionsPercent": 50,
    "ConnectionBorrowTimeout": 120,
    "SessionPinningFilters": []
  }'
```

Percentages are of RDS's configured max connections. With MaxConnectionsPercent=80 and RDS max_connections=32000, proxy uses up to 25,600 connections.

## Session pinning — SQL Server specific

When a client uses session-state features, the proxy must **pin** the client to a specific backend connection for correctness. Common SQL Server pinning triggers:

- `SET` statements (session variables, options)
- Cursors with server-side cursors
- Temporary tables (`#temp`)
- `sp_set_session_context`
- Prepared statements

Pinned sessions don't benefit from pooling. Check pinning metrics in CloudWatch:

```
AWS/RDS namespace
DatabaseConnectionsCurrentlySessionPinned
```

If pinning is high, review app code for unnecessary session state. Use `TRUNCATE` + temporary tables → permanent tables where possible.

## When NOT to use RDS Proxy

- Very simple apps with predictable, low connection counts
- Apps that make heavy use of session state (can't benefit from pooling due to pinning)
- Small instances where proxy cost (per-vCPU hourly) outweighs the benefit

Check the [pricing page](https://aws.amazon.com/rds/proxy/pricing/) — for small apps, RDS Proxy is cost-additive; for Lambda-heavy workloads, it prevents connection storms and is usually net-positive.

## Monitor

Key CloudWatch metrics:

- `DatabaseConnections` (at proxy target group)
- `DatabaseConnectionsCurrentlySessionPinned`
- `QueryDatabaseResponseLatency`
- `ClientConnections` / `ClientConnectionsSetupFailedAuth`

## Verify

```python
# Connect via proxy, then:
cur = conn.cursor()
cur.execute("SELECT @@SERVERNAME, system_user, auth_scheme FROM sys.dm_exec_connections WHERE session_id=@@SPID")
print(cur.fetchone())
# Returns the actual RDS server name (proxy is transparent), app_user, SQL (IAM tokens go in as SQL passwords)
```
