# RDS for Oracle — .NET

Driver: **`Oracle.ManagedDataAccess.Core`** (ODP.NET Core). Fully managed, cross-platform, no Oracle Client required.

```bash
dotnet add package Oracle.ManagedDataAccess.Core
```

## Basic connection

```csharp
using Oracle.ManagedDataAccess.Client;

// Password is fetched from AWS Secrets Manager at runtime; see connection-auth.md section (b) — via AWS Secrets Manager
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;" +
    "Data Source=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL;";

using var conn = new OracleConnection(connString);
conn.Open();

using var cmd = conn.CreateCommand();
cmd.CommandText = "SELECT sysdate FROM dual";
var result = cmd.ExecuteScalar();
Console.WriteLine(result);
```

## Connection string formats

```csharp
// Easy Connect
var ds = "mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL";

// TNS descriptor (CMAN, failover, TCPS)
var ds = "(DESCRIPTION="
       + "(ADDRESS=(PROTOCOL=TCP)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=1521))"
       + "(CONNECT_DATA=(SERVICE_NAME=ORCL)))";

// Full with options
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;" +
    "Data Source=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL;" +
    "Connection Timeout=15;";
```

## Pooling (built-in, on by default)

Configure via connection string:

```csharp
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;" +
    "Data Source=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL;" +
    "Min Pool Size=2;" +
    "Max Pool Size=10;" +
    "Connection Lifetime=300;" +       // max connection age in seconds
    "Connection Timeout=15;" +          // seconds to wait for a pool connection
    "Incr Pool Size=1;" +
    "Decr Pool Size=1;" +
    "Validate Connection=true;";

using var conn = new OracleConnection(connString);
conn.Open();    // gets from pool
// Dispose returns to pool
```

### Pool sizing

| Workload | Min Pool Size | Max Pool Size |
|---|---|---|
| Low | 1 | 5 |
| Medium | 2 | 10 |
| High | 5 | 20 |

`Max Pool Size` ≤ RDS `max_connections` / number of app instances.

## Secrets Manager

```bash
dotnet add package AWSSDK.SecretsManager
```

```csharp
using Amazon.SecretsManager;
using Amazon.SecretsManager.Model;
using Oracle.ManagedDataAccess.Client;
using System.Text.Json;

async Task<OracleConnection> OpenFromSecret(string secretName) {
    var client = new AmazonSecretsManagerClient();
    var resp = await client.GetSecretValueAsync(
        new GetSecretValueRequest { SecretId = secretName });
    var s = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(resp.SecretString)!;

    var cs = $"User Id={s["username"]};Password={s["password"]};" +
        $"Data Source={s["host"]}:{s["port"]}/{s["dbname"]};" +
        "Min Pool Size=2;Max Pool Size=10;Validate Connection=true;";
    var conn = new OracleConnection(cs);
    await conn.OpenAsync();
    return conn;
}
```

## TLS/TCPS (port 2484)

```csharp
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;" +
    "Data Source=(DESCRIPTION=" +
        "(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))" +
        "(CONNECT_DATA=(SERVICE_NAME=ORCL)));" +
    "SSL Server Cert DN=CN=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com;";
```

ODP.NET Core uses the OS trust store on Linux. Import the RDS CA bundle:

```bash
sudo curl -o /usr/local/share/ca-certificates/rds-ca.crt \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
sudo update-ca-certificates
```

Alternatively, specify a wallet directory:

```csharp
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;" +
    "Data Source=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:2484/ORCL;" +
    "Wallet Location=/path/to/wallet;";
```

## ASP.NET Core / DI

`Program.cs`:

```csharp
builder.Services.AddScoped<OracleConnection>(sp =>
{
    var cs = builder.Configuration.GetConnectionString("OracleRDS");
    return new OracleConnection(cs);
});
```

`appsettings.json`:

```json
{
  "ConnectionStrings": {
    "OracleRDS": "User Id=dbadmin;Password=<from-secrets-manager>;Data Source=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL;Min Pool Size=2;Max Pool Size=10;Validate Connection=true;"
  }
}
```

For rotation-safe production: load from Secrets Manager in startup, build the connection string, register as scoped.

## Lambda (.NET)

```csharp
using Amazon.Lambda.Core;
using Amazon.SecretsManager;
using Amazon.SecretsManager.Model;
using Oracle.ManagedDataAccess.Client;
using System.Text.Json;

public class Function {
    private static OracleConnection? _conn;

    public async Task<string> Handler(object input, ILambdaContext ctx) {
        if (_conn == null || _conn.State != System.Data.ConnectionState.Open) {
            _conn?.Dispose();
            var client = new AmazonSecretsManagerClient();
            var resp = await client.GetSecretValueAsync(
                new GetSecretValueRequest { SecretId = Environment.GetEnvironmentVariable("SECRET_NAME") });
            var s = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(resp.SecretString)!;
            var cs = $"User Id={s["username"]};Password={s["password"]};" +
                $"Data Source={s["host"]}:{s["port"]}/{s["dbname"]};";
            _conn = new OracleConnection(cs);
            await _conn.OpenAsync();
        }

        using var cmd = _conn.CreateCommand();
        cmd.CommandText = "SELECT sysdate FROM dual";
        var r = await cmd.ExecuteScalarAsync();
        return r?.ToString() ?? "null";
    }
}
```

## Dockerfile

```dockerfile
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=build /app/publish .
# ODP.NET Core is fully managed — no Oracle Client needed
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

## Error handling

```csharp
try {
    using var conn = new OracleConnection(connString);
    conn.Open();
} catch (OracleException ex) {
    switch (ex.Number) {
        case 12170: Console.Error.WriteLine("TNS connect timeout — check SGs and network"); break;
        case 1017:  Console.Error.WriteLine("Invalid username/password"); break;
        case 12541: Console.Error.WriteLine("No listener — check endpoint/port"); break;
        case 12514: Console.Error.WriteLine("Service name mismatch"); break;
        default:    Console.Error.WriteLine($"ORA-{ex.Number}: {ex.Message}"); break;
    }
}
```
