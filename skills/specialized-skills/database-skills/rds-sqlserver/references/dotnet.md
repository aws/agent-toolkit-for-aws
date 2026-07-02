# .NET — Microsoft.Data.SqlClient

Use `Microsoft.Data.SqlClient` for all new .NET code. `System.Data.SqlClient` is legacy (.NET Framework only) and does not get new features or security fixes.

## Install

```bash
dotnet add package Microsoft.Data.SqlClient --version 5.*
```

## Minimal connection

```csharp
using Microsoft.Data.SqlClient;

var connStr = "Server=mydb.xxxx.us-east-1.rds.amazonaws.com,1433;" +
              "Database=mydb;User Id=admin;Password=secret;" +
              "Encrypt=Mandatory;TrustServerCertificate=False;";

using var conn = new SqlConnection(connStr);
await conn.OpenAsync();

using var cmd = new SqlCommand("SELECT @@VERSION", conn);
var version = (string)await cmd.ExecuteScalarAsync();
```

## Connection string essentials

| Key | Required value | Why |
|---|---|---|
| `Server` | `<rds-endpoint>,1433` | **Comma** between host and port, not colon |
| `Database` | target database | Required to bypass master |
| `Encrypt` | `Mandatory` (5.x+ default) | TLS required |
| `TrustServerCertificate` | `False` | Force cert validation — don't disable in prod |
| `Connection Timeout` | `30` | Network connection timeout (not command timeout) |
| `MultiSubnetFailover` | `True` | For Multi-AZ — parallelize to both IPs during failover |

### Default behavior changes in SqlClient 5.x

- `Encrypt` defaults to `Mandatory` (was `False` in 4.x)
- `TrustServerCertificate` defaults to `False`
- Connection will fail if the server cert can't be validated

If you see `A connection was successfully established... but an error occurred during the pre-login handshake`, the server cert chain isn't trusted on the client — see `encryption.md` for CA bundle setup.

## Windows auth (Kerberos)

Connect to the CNAME, not the RDS endpoint:

```csharp
var connStr = "Server=database-1.corp.example.com,1433;" +    // CNAME
              "Database=mydb;" +
              "Integrated Security=True;" +
              "Encrypt=Mandatory;";

using var conn = new SqlConnection(connStr);
await conn.OpenAsync();
```

Verify:

```sql
SELECT auth_scheme FROM sys.dm_exec_connections WHERE session_id = @@SPID
-- Expected: KERBEROS
```

If you get `NTLM` instead: connect to the CNAME (not RDS endpoint), confirm SPN exists in AD for the CNAME. See `ad-kerberos.md`.

### Container / ECS Fargate running domain-joined

.NET on Windows containers can use Kerberos via gMSA (Group Managed Service Account). See `ecs-fargate-vpc.md`. .NET on Linux containers requires explicit ticket management:

```csharp
// Before opening connection, obtain TGT
// kinit with keytab OR mount a Kerberos credentials cache (KRB5CCNAME)
```

## Secrets Manager

```csharp
using Amazon.SecretsManager;
using Amazon.SecretsManager.Model;

var sm = new AmazonSecretsManagerClient(Amazon.RegionEndpoint.USEast1);
var resp = await sm.GetSecretValueAsync(new GetSecretValueRequest {
    SecretId = "rds/sqlserver/app"
});
var creds = JsonSerializer.Deserialize<DbCreds>(resp.SecretString);

var connStr = $"Server={creds.Host},{creds.Port};" +
              $"Database={creds.DbName};" +
              $"User Id={creds.Username};Password={creds.Password};" +
              $"Encrypt=Mandatory;";

record DbCreds(string Host, int Port, string Username, string Password, string DbName);
```

### Caching the secret

Don't call `GetSecretValueAsync` on every database call. Cache it in memory with a TTL, or use AWS Secrets Manager Caching library:

```bash
dotnet add package AWSSDK.SecretsManager.Caching
```

## Connection pooling

ADO.NET has built-in pooling — enabled by default. Tune in the connection string:

```csharp
var connStr = "Server=mydb.xxxx.us-east-1.rds.amazonaws.com,1433;" +
              "Database=mydb;User Id=admin;Password=secret;" +
              "Encrypt=Mandatory;" +
              "Min Pool Size=5;" +        // always have 5 ready
              "Max Pool Size=100;" +       // cap at 100 per process
              "Connection Lifetime=300;";  // recycle after 5 min (Multi-AZ safety)
```

Pools are per process + per unique connection string. If you're running many replicas of a web app, total connections = replicas × Max Pool Size.

## Async and cancellation

Always use `async` methods and pass a `CancellationToken`:

```csharp
using var conn = new SqlConnection(connStr);
await conn.OpenAsync(cancellationToken);

using var cmd = new SqlCommand("SELECT * FROM users WHERE id = @id", conn);
cmd.Parameters.AddWithValue("@id", userId);

using var reader = await cmd.ExecuteReaderAsync(cancellationToken);
while (await reader.ReadAsync(cancellationToken)) { /* ... */ }
```

Synchronous calls (`conn.Open()`) block the thread pool — costly in high-throughput apps.

## Lambda (.NET)

Use Amazon.Lambda.RuntimeSupport for .NET runtimes:

```csharp
using Amazon.Lambda.Core;

[assembly: LambdaSerializer(typeof(DefaultLambdaJsonSerializer))]

public class Function {
    // Module-scope — reused across warm invocations
    private static readonly AmazonSecretsManagerClient _sm = new(Amazon.RegionEndpoint.USEast1);
    private static Lazy<Task<string>> _connStr = new(BuildConnStringAsync);

    public async Task<string> FunctionHandler(Dictionary<string, string> input, ILambdaContext ctx) {
        var cs = await _connStr.Value;
        using var conn = new SqlConnection(cs);
        await conn.OpenAsync();
        // ...
        return "ok";
    }

    static async Task<string> BuildConnStringAsync() {
        var r = await _sm.GetSecretValueAsync(new() { SecretId = "rds/sqlserver/app" });
        var c = JsonSerializer.Deserialize<DbCreds>(r.SecretString);
        return $"Server={c.Host},1433;Database={c.DbName};" +
               $"User Id={c.Username};Password={c.Password};Encrypt=Mandatory;";
    }
    record DbCreds(string Host, string Username, string Password, string DbName);
}
```

Small `Max Pool Size` (e.g. 2) per Lambda — Lambda's concurrency model means many containers × large pool = too many connections to RDS. Use RDS Proxy for serverless-scale apps.

## Verify

```sql
SELECT
  encrypt_option,     -- TRUE = TLS
  auth_scheme,        -- SQL, KERBEROS, NTLM
  net_transport,
  protocol_type
FROM sys.dm_exec_connections WHERE session_id = @@SPID
```
