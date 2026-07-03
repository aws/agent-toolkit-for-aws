# RDS for Oracle — Node.js

Driver: **`node-oracledb`** ≥ 6.x. Thin mode is default — no Oracle Instant Client needed.

```bash
npm install oracledb
```

## Basic connection (thin mode)

```javascript
const oracledb = require('oracledb');

async function run() {
  const conn = await oracledb.getConnection({
    user: 'dbadmin',
    password: '<from-secrets-manager>',  // fetch at runtime; see connection-auth.md section (b) — via AWS Secrets Manager
    connectString: 'mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL'
  });
  const result = await conn.execute('SELECT sysdate FROM dual');
  console.log(result.rows[0]);
  await conn.close();
}

run();
```

No `oracledb.initOracleClient()` call needed for thin mode.

## Connect string formats

```javascript
// Easy Connect
const connectString = 'hostname:1521/ORCL';

// Full descriptor
const connectString = `(DESCRIPTION=
  (ADDRESS=(PROTOCOL=TCP)(HOST=hostname)(PORT=1521))
  (CONNECT_DATA=(SERVICE_NAME=ORCL)))`;

// Route 53 CNAME
const connectString = 'mydb.example.internal:1521/ORCL';
```

## Thick mode (only when needed)

Required for Kerberos with in-memory tickets, LDAP, Oracle Wallet-based auth. Requires Oracle Instant Client.

```javascript
oracledb.initOracleClient({ libDir: '/path/to/instantclient' });
```

## Connection pooling

```javascript
const oracledb = require('oracledb');

async function init() {
  await oracledb.createPool({
    user: 'dbadmin',
    password: '<from-secrets-manager>',
    connectString: 'mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL',
    poolMin: 2,
    poolMax: 10,
    poolIncrement: 1,
    poolTimeout: 60,
    queueTimeout: 5000,
  });
}

async function query() {
  const conn = await oracledb.getConnection();   // default pool
  try {
    const result = await conn.execute('SELECT sysdate FROM dual');
    return result.rows[0];
  } finally {
    await conn.close();   // returns to pool
  }
}

async function shutdown() {
  await oracledb.getPool().close(0);
}
```

`conn.close()` in a `finally` block is essential — missing it leaks connections.

### Pool with Secrets Manager (AWS SDK v3)

```javascript
const oracledb = require('oracledb');
const { SecretsManagerClient, GetSecretValueCommand } = require('@aws-sdk/client-secrets-manager');

async function createPoolFromSecret(secretName, region = 'us-east-1') {
  const client = new SecretsManagerClient({ region });
  const resp = await client.send(new GetSecretValueCommand({ SecretId: secretName }));
  const secret = JSON.parse(resp.SecretString);

  await oracledb.createPool({
    user: secret.username,
    password: secret.password,
    connectString: `${secret.host}:${secret.port}/${secret.dbname}`,
    poolMin: 2, poolMax: 10, poolIncrement: 1,
  });
}
```

Use the v3 SDK (`@aws-sdk/client-secrets-manager`), not the legacy `aws-sdk` v2.

### Pool sizing

| Workload | poolMin | poolMax | poolIncrement |
|---|---|---|---|
| Low | 1 | 5 | 1 |
| Medium | 2 | 10 | 1 |
| High | 5 | 20 | 2 |

`poolMax` ≤ RDS `max_connections` / number of app instances.

## Express app example

```javascript
const express = require('express');
const oracledb = require('oracledb');
const app = express();

async function init() {
  await oracledb.createPool({
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    connectString: process.env.DB_CONNECT_STRING,
    poolMin: 2, poolMax: 10,
  });
}

app.get('/users', async (req, res) => {
  const conn = await oracledb.getConnection();
  try {
    const result = await conn.execute('SELECT id, name FROM users WHERE ROWNUM <= 100');
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  } finally {
    await conn.close();
  }
});

init().then(() => app.listen(3000));
```

## Lambda pattern

Pool initialized at module scope (outside the handler) so it's reused across warm invocations:

```javascript
const oracledb = require('oracledb');
const { SecretsManagerClient, GetSecretValueCommand } = require('@aws-sdk/client-secrets-manager');

let pool;

async function initPool() {
  if (pool) return;
  const client = new SecretsManagerClient({});
  const resp = await client.send(new GetSecretValueCommand({ SecretId: process.env.SECRET_NAME }));
  const secret = JSON.parse(resp.SecretString);

  pool = await oracledb.createPool({
    user: secret.username,
    password: secret.password,
    connectString: `${secret.host}:${secret.port}/${secret.dbname}`,
    poolMin: 1, poolMax: 2,    // per Lambda instance
  });
}

exports.handler = async (event) => {
  await initPool();
  const conn = await oracledb.getConnection();
  try {
    const result = await conn.execute('SELECT sysdate FROM dual');
    return { statusCode: 200, body: JSON.stringify(result.rows) };
  } finally {
    await conn.close();
  }
};
```

Keep `poolMax` low (1-2) — total Oracle connections = concurrent Lambda instances × `poolMax`.

## TLS/TCPS thin mode

Node.js does not trust the RDS CA by default. Export `NODE_EXTRA_CA_CERTS`:

```bash
curl -o /path/to/global-bundle.pem \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
export NODE_EXTRA_CA_CERTS=/path/to/global-bundle.pem
```

```javascript
const conn = await oracledb.getConnection({
  user: 'dbadmin',
  password: '<from-secrets-manager>',
  connectString: `(DESCRIPTION=
    (ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))
    (CONNECT_DATA=(SERVICE_NAME=ORCL))
    (SECURITY=(SSL_SERVER_DN_MATCH=YES)))`,
  sslServerCertDN: 'CN=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com'
});
```

## Error handling

```javascript
try {
  const conn = await oracledb.getConnection({ /* ... */ });
} catch (err) {
  switch (err.errorNum) {
    case 12170: console.error('TNS connect timeout — check SGs and network'); break;
    case 1017:  console.error('Invalid username/password'); break;
    case 12541: console.error('No listener — check RDS endpoint/port'); break;
    case 12514: console.error('Service name mismatch'); break;
    default:    console.error(`ORA-${err.errorNum}: ${err.message}`);
  }
}
```
