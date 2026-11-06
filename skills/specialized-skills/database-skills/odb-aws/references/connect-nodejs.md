# Connect — Node.js (node-oracledb)

Use **node-oracledb 6.x+**. Thin mode is default — no Oracle Client install needed.

```bash
npm install oracledb
```

## TCP

```javascript
const oracledb = require('oracledb');

const conn = await oracledb.getConnection({
  user: "app_user",
  password: password,  // from Secrets Manager — never hardcode
  connectString: "cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com",
});
```

## TCPS with Wallet

```javascript
// Never commit wallet files to source control
const conn = await oracledb.getConnection({
  user: "app_user",
  password: password,
  connectString: "mydb_high",  // TNS alias from wallet tnsnames.ora
  configDir: "/opt/oracle/wallet",
  walletLocation: "/opt/oracle/wallet",
  walletPassword: walletPassword,
});
```

## Connection Pooling

```javascript
const pool = await oracledb.createPool({
  user: "app_user",
  password: password,
  connectString: "mydb_high",
  configDir: "/opt/oracle/wallet",
  walletLocation: "/opt/oracle/wallet",
  walletPassword: walletPassword,
  poolMin: 2,
  poolMax: 10,
  poolIncrement: 1,
  poolTimeout: 300,  // idle timeout (seconds)
});

const conn = await pool.getConnection();
try {
  const result = await conn.execute("SELECT 1 FROM DUAL");
  console.log(result.rows);
} finally {
  await conn.close();
}
```

## Retrieving Secrets

```javascript
const { SecretsManagerClient, GetSecretValueCommand } =
  require("@aws-sdk/client-secrets-manager");

const client = new SecretsManagerClient({});
const response = await client.send(
  new GetSecretValueCommand({ SecretId: "odb/myapp/credentials" })
);
const secret = JSON.parse(response.SecretString);

const conn = await oracledb.getConnection({
  user: secret.username,
  password: secret.password,
  connectString: `${secret.host}:${secret.port}/${secret.service_name}`,
  walletPassword: secret.wallet_password,
  configDir: "/opt/oracle/wallet",
  walletLocation: "/opt/oracle/wallet",
});
```

## Critical Rules

- Use `connectString` (not `connectionString`).
- For TCPS, `configDir` and `walletLocation` are both required.
- For Lambda, do NOT use a connection pool — single connection per warm instance, reused via a module-level variable. See **compute-runtimes.md** (loaded reference).
- Never hardcode passwords or wallet passwords.
- Never commit wallet files to source control.
