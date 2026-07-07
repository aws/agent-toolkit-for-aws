# EC2 — RDS SQL Server from EC2 in the same VPC

Simplest connection pattern. EC2 and RDS in the same VPC (or peered VPCs).

## Networking

### Security groups

Two SGs, referenced by ID:

```bash
# RDS SG (e.g. sg-rds-sqlserver) — inbound
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-sqlserver \
  --protocol tcp --port 1433 \
  --source-group sg-app-ec2 \
  --region us-east-1

# EC2 SG (sg-app-ec2) — outbound is default allow-all,
# no change needed unless custom SG
```

Using SG IDs (`--source-group sg-xxx`) works only within the same VPC. For cross-VPC, see `networking.md`.

### Subnets

EC2 and RDS can be in different subnets of the same VPC as long as:

- Route tables connect them (default VPC routing covers this)
- NACLs don't block 1433 in either direction

### DNS

The RDS endpoint `mydb.xxxx.us-east-1.rds.amazonaws.com` resolves to a private IP inside the VPC. Verify:

```bash
nslookup mydb.xxxx.us-east-1.rds.amazonaws.com
# Should return 10.x.x.x or similar private IP
```

If it returns the public IP, your VPC has `enableDnsSupport=false` or you've disabled the private DNS override.

## Connection examples

### Linux EC2 (Amazon Linux 2023) — Python + pymssql

```bash
sudo yum install -y python3-pip gcc-c++ freetds-devel
pip3 install pymssql boto3
```

```python
import pymssql, boto3, json

sm = boto3.client("secretsmanager", region_name="us-east-1")
c = json.loads(sm.get_secret_value(SecretId="rds/sqlserver/app")["SecretString"])

conn = pymssql.connect(
    server=c["host"], port="1433",
    user=c["username"], password=c["password"], database=c["dbname"],
    tds_version="7.3", encryption="require",
)
```

IAM instance profile must have `secretsmanager:GetSecretValue` on the secret ARN (and `kms:Decrypt` if CMK).

### Windows EC2 — .NET

Installed .NET + AWS CLI. Domain-join if using Windows auth (see `ad-kerberos.md`).

```csharp
// Use instance profile — AWS SDK picks it up automatically
var sm = new AmazonSecretsManagerClient();
var resp = await sm.GetSecretValueAsync(new GetSecretValueRequest {
    SecretId = "rds/sqlserver/app" });
var c = JsonSerializer.Deserialize<DbCreds>(resp.SecretString);

var connStr = $"Server={c.Host},1433;Database={c.DbName};" +
              $"User Id={c.Username};Password={c.Password};Encrypt=Mandatory;";
```

### Java (mssql-jdbc)

```java
SecretsManagerClient sm = SecretsManagerClient.create();
String json = sm.getSecretValue(
    GetSecretValueRequest.builder().secretId("rds/sqlserver/app").build()
).secretString();
// ...parse and build JDBC URL
```

## IAM permissions for EC2 instance profile

Minimum for SQL auth + Secrets Manager:

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

Do NOT use `rds-db:connect` — that's for IAM auth on Postgres/MySQL, not SQL Server. For IAM auth on SQL Server you need RDS Proxy — see `rds-proxy.md`.

## Multi-AZ failover

Connection strings pointing at the RDS endpoint (not IP) automatically redirect to the new primary after failover (typically 60-120 seconds).

Tune driver timeouts to handle the gap:

- **pymssql**: `login_timeout=10`
- **.NET**: `Connection Timeout=30;MultiSubnetFailover=True`
- **JDBC (HikariCP)**: `maxLifetime < 1800000` + `validationTimeout=5000`
- **tedious**: `connectTimeout: 30000` in ms

Add `pool_pre_ping` (SQLAlchemy) or `connectionTestQuery: "SELECT 1"` (HikariCP) to evict stale connections.

## Deployment checklist

- [ ] EC2 in the same VPC as RDS (or peered)
- [ ] EC2 IAM instance profile has `secretsmanager:GetSecretValue` + `kms:Decrypt`
- [ ] RDS SG inbound 1433 from EC2 SG (by SG ID)
- [ ] RDS endpoint resolves to private IP (VPC has `enableDnsSupport=true`)
- [ ] Driver and CA bundle installed
- [ ] Connection string uses `encrypt=true` / `Encrypt=Mandatory` / `encryption="require"`
- [ ] Secrets Manager secret exists with correct JSON structure

## Verify

From EC2 shell:

```bash
# TCP reachability
nc -zv mydb.xxxx.us-east-1.rds.amazonaws.com 1433
# Connection opens → OK

# SQL query
python3 -c "
import pymssql, json, boto3
c = json.loads(boto3.client('secretsmanager').get_secret_value(SecretId='rds/sqlserver/app')['SecretString'])
conn = pymssql.connect(server=c['host'], port='1433', user=c['username'], password=c['password'], database=c['dbname'], tds_version='7.3', encryption='require')
cur = conn.cursor()
cur.execute('SELECT encrypt_option, auth_scheme FROM sys.dm_exec_connections WHERE session_id=@@SPID')
print(cur.fetchone())
"
```

Expected: `(True, 'SQL')` — encrypted + SQL auth.
