# Node.js — tedious (and mssql wrapper)

Two options:

- **`tedious`** — low-level pure-JS driver (no native deps). Direct control, works in Lambda out of the box.
- **`mssql`** — higher-level wrapper around tedious, adds connection pooling and a friendlier API.

Use `mssql` for most applications. Use raw `tedious` only when you need fine-grained control.

## Install

```bash
npm install tedious        # low-level
npm install mssql          # recommended — wrapper with pooling
```

## Minimal connection with mssql

```javascript
const sql = require('mssql');
const { SecretsManagerClient, GetSecretValueCommand } = require("@aws-sdk/client-secrets-manager");

async function connect() {
  const sm = new SecretsManagerClient({ region: "us-east-1" });
  const cmd = new GetSecretValueCommand({ SecretId: "rds/sqlserver/app" });
  const { SecretString } = await sm.send(cmd);
  const creds = JSON.parse(SecretString);

  const pool = await sql.connect({
    server: creds.host,
    port: 1433,
    database: creds.dbname,
    user: creds.username,
    password: creds.password,
    options: {
      encrypt: true,               // TLS required in prod
      trustServerCertificate: false,
      connectTimeout: 15000,       // ms
      requestTimeout: 15000,
    },
    pool: {
      max: 10,
      min: 0,
      idleTimeoutMillis: 30000,
    },
  });

  const result = await pool.request().query("SELECT @@VERSION AS v");
  console.log(result.recordset[0].v);
  return pool;
}
```

## Critical tedious/mssql gotchas

| Gotcha | Why |
|---|---|
| `encrypt: true` is default in tedious 16+; not in older versions | Check your version |
| `trustServerCertificate: false` requires RDS CA bundle | See below |
| `port: 1433` as number, NOT string (opposite of pymssql) | tedious parses to number |
| Pool `max` is per-process | Scale down for Lambda |
| Connection events — listen for `'error'` | Otherwise silent failures |

## TLS with cert validation

```javascript
const fs = require('fs');
const tls = require('tls');

const caBundle = fs.readFileSync('/etc/ssl/certs/global-bundle.pem', 'utf8');
const caList = caBundle.split(/-----END CERTIFICATE-----\n?/)
                       .filter(c => c.trim())
                       .map(c => c + '-----END CERTIFICATE-----\n');

const config = {
  server: creds.host, port: 1433,
  database: creds.dbname,
  user: creds.username, password: creds.password,
  options: {
    encrypt: true,
    trustServerCertificate: false,
    cryptoCredentialsDetails: {
      ca: caList,                  // RDS CA bundle
      minVersion: 'TLSv1.2',
    },
  },
};
```

## Windows auth (NTLM)

tedious has NTLM support (Kerberos is limited):

```javascript
const config = {
  server: "database-1.corp.example.com",
  port: 1433,
  database: "mydb",
  authentication: {
    type: "ntlm",
    options: {
      userName: "svc-app",
      password: "secret",
      domain: "CORP",
    },
  },
  options: { encrypt: true, trustServerCertificate: false },
};
```

For proper Kerberos, use a different stack (Java + JDBC, or .NET + IntegratedSecurity).

## Lambda pattern

Module-scope pool and secret caching:

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
      pool: { max: 2, min: 0, idleTimeoutMillis: 10000 },  // small — Lambda
    });
  })();
  return poolPromise;
}

exports.handler = async (event) => {
  const pool = await getPool();
  const result = await pool.request().query("SELECT 1 AS ok");
  return { statusCode: 200, body: JSON.stringify(result.recordset) };
};
```

Use `@aws-sdk/client-secrets-manager` (AWS SDK v3). AWS SDK v2 (`aws-sdk` package) is deprecated and should not be used for new Lambda code.

For high-concurrency Lambda, use RDS Proxy — see `rds-proxy.md`.

## ECS / EKS

For long-running Node.js services, use `mssql` with a larger pool:

```javascript
const pool = await sql.connect({
  server: creds.host, port: 1433,
  database: creds.dbname, user: creds.username, password: creds.password,
  options: { encrypt: true, trustServerCertificate: false },
  pool: {
    max: 20, min: 2,
    idleTimeoutMillis: 600000,    // 10 min
    acquireTimeoutMillis: 30000,
  },
});

// Handle pool errors
pool.on('error', err => {
  console.error('Pool error, reconnecting:', err);
});

// Health check endpoint
app.get('/health', async (req, res) => {
  try {
    await pool.request().query("SELECT 1");
    res.status(200).send("ok");
  } catch (e) {
    res.status(503).send("db unhealthy");
  }
});
```

## Secrets rotation

When Secrets Manager rotates the password, active connections fail with error 18456 (login failed). Handle it:

```javascript
pool.on('error', async err => {
  if (err.code === 'ELOGIN' || err.number === 18456) {
    console.log('Credentials rotated — rebuilding pool');
    await pool.close();
    poolPromise = null;      // reset the lazy init
  }
});
```

## Verify

```javascript
const r = await pool.request().query(`
  SELECT encrypt_option, auth_scheme, net_transport
  FROM sys.dm_exec_connections WHERE session_id = @@SPID
`);
console.log(r.recordset[0]);
```

## Raw tedious (without mssql wrapper)

When you need event-driven access:

```javascript
const { Connection, Request } = require('tedious');

const conn = new Connection({
  server: creds.host,
  options: {
    port: 1433, database: creds.dbname,
    encrypt: true, trustServerCertificate: false,
    connectTimeout: 15000,
  },
  authentication: {
    type: "default",
    options: { userName: creds.username, password: creds.password },
  },
});

conn.on('connect', err => {
  if (err) { console.error('connect failed', err); return; }
  const req = new Request("SELECT 1 AS n", (err, rowCount) => { /* done */ });
  req.on('row', cols => console.log(cols[0].value));
  conn.execSql(req);
});
conn.connect();
```

No built-in pool — wrap in `tarn.js` or switch to `mssql`.
