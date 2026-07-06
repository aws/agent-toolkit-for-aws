# Lambda — RDS SQL Server from Lambda in VPC

## Lambda in VPC checklist

Before writing code, confirm:

- [ ] Lambda configured with VPC: `--vpc-config SubnetIds=subnet-a,subnet-b SecurityGroupIds=sg-lambda`
- [ ] Subnets are **private** (RDS is private)
- [ ] Either: VPC endpoint for Secrets Manager in the same subnets, OR NAT gateway for internet access
- [ ] Lambda SG outbound allows TCP 443 (Secrets Manager) + TCP 1433 (RDS) — default "allow all outbound" works
- [ ] RDS SG inbound 1433 from Lambda SG
- [ ] Lambda execution role has `secretsmanager:GetSecretValue` + `kms:Decrypt` + VPC permissions
- [ ] Lambda timeout ≥ 15s for cold start + DB connect

## Why VPC endpoints matter

A Lambda in a VPC has no internet access by default. Calling Secrets Manager from inside the handler will hang until timeout because the default route has no IGW.

### Option A — VPC endpoint for Secrets Manager (recommended)

```bash
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxx \
  --service-name com.amazonaws.us-east-1.secretsmanager \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-priv-a subnet-priv-b \
  --security-group-ids sg-endpoint \
  --private-dns-enabled
```

Endpoint SG inbound: TCP 443 from Lambda SG.

With `--private-dns-enabled`, `secretsmanager.<region>.amazonaws.com` resolves to the endpoint's private IP automatically — no code changes.

### Option B — NAT gateway

Simpler if Lambda needs broad internet access (multiple AWS services, third-party APIs):

```bash
aws ec2 allocate-address --domain vpc
aws ec2 create-nat-gateway --subnet-id subnet-public-a --allocation-id eipalloc-xxxx

# Private subnet route table: 0.0.0.0/0 → NAT
aws ec2 create-route --route-table-id rtb-private \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id nat-xxxx
```

## Code — Python (pymssql)

Package pymssql in a layer for `manylinux2014_x86_64`:

```bash
mkdir -p python
pip install pymssql boto3 -t python/ \
  --platform manylinux2014_x86_64 --only-binary=:all:
zip -r layer.zip python/
aws lambda publish-layer-version --layer-name pymssql \
  --zip-file fileb://layer.zip \
  --compatible-runtimes python3.12 \
  --compatible-architectures x86_64
```

```python
# handler.py
import pymssql, boto3, json, os

sm = boto3.client("secretsmanager")
_creds = None

def get_creds():
    global _creds
    if _creds is None:
        _creds = json.loads(
            sm.get_secret_value(SecretId=os.environ["SECRET_ARN"])["SecretString"]
        )
    return _creds

def handler(event, context):
    c = get_creds()
    conn = pymssql.connect(
        server=c["host"], port="1433",
        user=c["username"], password=c["password"], database=c["dbname"],
        tds_version="7.3", encryption="require", login_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()[0]
        return {"statusCode": 200, "body": json.dumps({"users": count})}
    finally:
        conn.close()
```

Module-scope client and secret caching avoid re-initialization on warm invocations. Keep the connection *per invocation* unless using RDS Proxy (see below).

## Code — .NET

```csharp
using Microsoft.Data.SqlClient;
using Amazon.SecretsManager;
using Amazon.SecretsManager.Model;
using System.Text.Json;

public class Function {
    private static readonly AmazonSecretsManagerClient _sm = new();
    private static Lazy<Task<string>> _connStr = new(BuildConnStringAsync);

    public async Task<Dictionary<string, object>> FunctionHandler(object _, ILambdaContext ctx) {
        var cs = await _connStr.Value;
        using var conn = new SqlConnection(cs);
        await conn.OpenAsync();
        using var cmd = new SqlCommand("SELECT COUNT(*) FROM users", conn);
        var count = (int)await cmd.ExecuteScalarAsync();
        return new() { ["users"] = count };
    }

    private static async Task<string> BuildConnStringAsync() {
        var resp = await _sm.GetSecretValueAsync(new GetSecretValueRequest {
            SecretId = Environment.GetEnvironmentVariable("SECRET_ARN")
        });
        var c = JsonSerializer.Deserialize<DbCreds>(resp.SecretString);
        return $"Server={c.Host},1433;Database={c.DbName};" +
               $"User Id={c.Username};Password={c.Password};" +
               $"Encrypt=Mandatory;Connection Timeout=5;" +
               $"Min Pool Size=0;Max Pool Size=2;";
    }
    record DbCreds(string Host, string DbName, string Username, string Password);
}
```

Small `Max Pool Size` (2-5) per Lambda is important — Lambda's concurrency model means 1000 concurrent Lambda containers × 100 pool size would create 100,000 connections. RDS SQL Server `max_connections` is typically 32,767 but memory/CPU pressure kicks in well before that.

## Code — Node.js (tedious/mssql)

```javascript
const sql = require('mssql');
const { SecretsManagerClient, GetSecretValueCommand } =
  require("@aws-sdk/client-secrets-manager");

const sm = new SecretsManagerClient({});
let poolPromise = null;

async function getPool() {
  if (poolPromise) return poolPromise;
  poolPromise = (async () => {
    const { SecretString } = await sm.send(new GetSecretValueCommand({
      SecretId: process.env.SECRET_ARN,
    }));
    const c = JSON.parse(SecretString);
    return sql.connect({
      server: c.host, port: 1433,
      database: c.dbname, user: c.username, password: c.password,
      options: { encrypt: true, trustServerCertificate: false, connectTimeout: 5000 },
      pool: { max: 2, min: 0, idleTimeoutMillis: 10000 },
    });
  })();
  return poolPromise;
}

exports.handler = async (event) => {
  const pool = await getPool();
  const r = await pool.request().query("SELECT COUNT(*) AS n FROM users");
  return { statusCode: 200, body: JSON.stringify(r.recordset[0]) };
};
```

## Provisioned concurrency

Cold start + DB connect can be 2-5 seconds on Lambda. For latency-sensitive APIs:

```bash
aws lambda put-provisioned-concurrency-config \
  --function-name my-fn \
  --qualifier LIVE \
  --provisioned-concurrent-executions 10
```

Provisioned containers keep the secret cached and (with a pool) can keep warm connections. Pair with SnapStart (Java only, free) or regular provisioned concurrency for Python/Node/.NET.

## For high concurrency — use RDS Proxy

At high Lambda concurrency (thousands of simultaneous executions), RDS Proxy is almost mandatory. See `rds-proxy.md`. Without it you'll hit:

- RDS connection count limits
- CPU contention from connection setup
- Connection timeouts during traffic spikes

With RDS Proxy, Lambda connects to the proxy endpoint, not RDS directly. The proxy multiplexes connections.

## IAM role — full example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "VPC",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManager",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds/sqlserver/app-*"
    },
    {
      "Sid": "KMS",
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "arn:aws:kms:us-east-1:111122223333:key/<kms-key-id>"
    },
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:111122223333:*"
    }
  ]
}
```

The VPC permissions are required when the function is `--vpc-config`'d. Without them, deployment fails with `InvalidSubnetID.NotFound`.
