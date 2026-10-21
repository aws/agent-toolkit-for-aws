# Auth — Wallet, TCPS, and Password + Secrets Manager

## When a Wallet Is Required

- **Autonomous Database on Dedicated Exadata Infrastructure** — mandatory (mTLS).
- **Exadata Database Service (ExaDB-D)** — required for TCPS; strongly recommended.
- **Plain TCP on ExaDB-D** — no wallet needed, but TCPS is recommended for defense in depth.

## Downloading the Wallet

- **Autonomous DB**: OCI Console → Autonomous Database → your database → **DB Connection** → Download Wallet. Set a wallet password and store it in Secrets Manager.
- **Exadata DB Service**: OCI Console → VM Cluster → your cluster → the database → **DB Connection** → Download.

## Wallet Contents

After unzipping:

```
wallet/
├── cwallet.sso        Auto-login wallet (thin-mode Python / Node use this)
├── ewallet.p12        Password-protected PKCS#12
├── keystore.jks       Java KeyStore (mTLS)
├── truststore.jks     Java TrustStore (JDBC)
├── ojdbc.properties   JDBC properties
├── sqlnet.ora         Oracle Net config
└── tnsnames.ora       TNS aliases
```

## Wallet Layout by Client

| Client | Needs | Parameters |
|---|---|---|
| python-oracledb thin | `cwallet.sso`, `tnsnames.ora`, `sqlnet.ora` | `config_dir` + `wallet_location` + `wallet_password` |
| node-oracledb thin | `cwallet.sso`, `tnsnames.ora`, `sqlnet.ora` | `configDir` + `walletLocation` + `walletPassword` |
| JDBC | `tnsnames.ora`, `truststore.jks` (+ `keystore.jks` for mTLS) | `oracle.net.tns_admin`, `javax.net.ssl.trustStore*`, `javax.net.ssl.keyStore*` |
| SQL*Plus / SQLcl | full wallet | `TNS_ADMIN` env var |

See **connect-python.md** (loaded reference) and **connect-java.md** (loaded reference) for concrete code.

## Wallet Distribution by Runtime

| Runtime | Method | Notes |
|---|---|---|
| EC2 / on-prem | Filesystem (`/opt/oracle/wallet/`) | `chmod 600 cwallet.sso ewallet.p12` |
| ECS / Fargate | S3 → init container, or Secrets Manager binary secret → sidecar | Mount to `/opt/oracle/wallet/` |
| Lambda | Secrets Manager binary secret → `/tmp` on cold start | Do not put wallets in the deployment package |
| EKS | Kubernetes Secret or CSI Secrets Store driver | Mount as volume |

## Password Authentication

### Create the database user

ExaDB-D (connect as SYS/SYSTEM):

```sql
CREATE USER app_user IDENTIFIED BY "<password>"
  DEFAULT TABLESPACE users
  TEMPORARY TABLESPACE temp
  QUOTA UNLIMITED ON users;

GRANT CREATE SESSION TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON schema.table_name TO app_user;
```

Autonomous DB (connect as ADMIN):

```sql
CREATE USER app_user IDENTIFIED BY "<password>";
GRANT DWROLE TO app_user;  -- or CONNECT, RESOURCE for TP workloads
ALTER USER app_user QUOTA UNLIMITED ON DATA;
```

### Store credentials in AWS Secrets Manager

> **Warning:** Passing `--secret-string` on the command line records credentials in bash history. Prefer: `aws secretsmanager create-secret --name odb/myapp/credentials --secret-string file:///dev/stdin` and paste the JSON, or use `--cli-input-json` with a temporary file (`chmod 600`, delete after use).

```bash
aws secretsmanager create-secret \
  --name odb/myapp/credentials \
  --secret-string '{
    "username": "app_user",
    "password": "<password>",
    "host": "cluster-abc-scan.sub1.vcn1.oraclevcn.com",
    "port": "2484",
    "service_name": "orclpdb1.sub1.vcn1.oraclevcn.com",
    "wallet_password": "<wallet-password>"
  }' \
  --region us-east-1
```

### Retrieve in application code

Python:

```python
import json, boto3

def get_secret(secret_id):
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_id)
    return json.loads(response["SecretString"])
```

Java (AWS SDK v2):

```java
SecretsManagerClient client = SecretsManagerClient.create();
var resp = client.getSecretValue(GetSecretValueRequest.builder()
    .secretId("odb/myapp/credentials").build());
// Parse JSON as usual
```

### Rotation

Enable Secrets Manager automatic rotation with a Lambda rotator that runs `ALTER USER app_user IDENTIFIED BY "<new-password>"` and updates the secret.

```bash
aws secretsmanager rotate-secret \
  --secret-id odb/myapp/credentials \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:rotate-odb \
  --rotation-rules AutomaticallyAfterDays=30 \
  --region us-east-1
```

## sqlnet.ora Notes

Default `sqlnet.ora` in the wallet:

```
WALLET_LOCATION = (SOURCE = (METHOD = file) (METHOD_DATA = (DIRECTORY="?/network/admin")))
SSL_SERVER_DN_MATCH=yes
```

Thin-mode drivers override the wallet path via `config_dir`/`wallet_location` parameters. Thick-mode and JDBC clients respect the `DIRECTORY` value — either edit it, or set `TNS_ADMIN` to the wallet directory, which overrides `sqlnet.ora`.

## Security Rules

- Never commit wallet files to source control — add to `.gitignore`.
- Store wallet passwords in Secrets Manager (not env vars).
- Restrict filesystem permissions: `chmod 600 cwallet.sso ewallet.p12`.
- Rotate wallets before certificate expiry — check expiry in the OCI console.
- Prefer Secrets Manager binary secret over S3 for container wallet distribution.
- There is **no AWS IAM database authentication** for ODB@AWS — do not emit `generate-db-auth-token` patterns.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Missing `cwallet.sso` | ORA-28759 | Ensure full wallet is extracted |
| Wrong `config_dir` | ORA-12154 | Point at a dir containing `tnsnames.ora` |
| Wallet password wrong | ORA-28759 | Verify in Secrets Manager |
| Wallet committed to git | Security breach | Remove, rotate, add to `.gitignore` |
| Lambda wallet in deployment package | Read-only path issues | Use Secrets Manager binary → `/tmp` |
