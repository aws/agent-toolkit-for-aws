# SSL/TLS Encryption — RDS SQL Server

## Defaults

RDS SQL Server ships with a self-signed certificate for the instance. By default:

- RDS **accepts** TLS connections on 1433
- RDS **does not require** TLS — connections can be plaintext unless the client opts in
- The parameter `rds.force_ssl` is **0 by default** (SQL Server doesn't have this parameter like PostgreSQL does)

To force TLS, use the `FORCE_ENCRYPTION` option group setting (see below).

## TLS versions

| TLS Version | RDS SQL Server Support |
|---|---|
| TLS 1.0 | Deprecated, still accepted on older engine versions |
| TLS 1.1 | Deprecated, still accepted on older engine versions |
| **TLS 1.2** | **Required minimum for production** |
| TLS 1.3 | Supported on SQL Server 2022+ |

Force minimum TLS 1.2 via option group (see "Enforce encryption" below).

## Client-side encryption config

Every driver has its own way to express "force TLS + validate cert":

| Driver | Setting | Notes |
|---|---|---|
| pymssql | `encryption="require"` | Not `"request"` — that's opportunistic |
| pyodbc | `Encrypt=Yes;TrustServerCertificate=No` | In connection string |
| .NET SqlClient | `Encrypt=Mandatory;TrustServerCertificate=False` | 5.x defaults to Mandatory/False |
| Java JDBC | `encrypt=true;trustServerCertificate=false;hostNameInCertificate=*.rds.amazonaws.com` | hostname helps wildcard |
| tedious/mssql | `options: { encrypt: true, trustServerCertificate: false }` | 16+ defaults encrypt:true |

## Certificate validation

The RDS certificate is issued by Amazon RDS's internal CA. Clients need the RDS CA bundle to validate it.

### Download bundle

```bash
curl -o global-bundle.pem \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

This bundle contains all regional RDS CAs. For a single region you can use the per-region bundle from the same truststore URL.

### Install in OS trust store (Linux)

```bash
sudo cp global-bundle.pem /etc/ssl/certs/rds-global-bundle.pem
sudo update-ca-certificates   # Debian/Ubuntu
# Or: sudo update-ca-trust    # RHEL/CentOS
```

Drivers that use the OS trust store (pymssql, pyodbc) will now validate.

### Java — per-app truststore

```bash
# Split PEM — keytool imports only the first cert from a multi-cert PEM
csplit -s -z -f rds- -b '%02d.pem' global-bundle.pem '/-----BEGIN CERTIFICATE-----/' '{*}'

# Import each cert
for f in rds-*.pem; do
  keytool -import -trustcacerts -alias "rds-$(basename $f .pem)" \
    -file "$f" -keystore rds-truststore.jks \
    -storepass changeit -noprompt
done
```

```bash
java -Djavax.net.ssl.trustStore=/path/to/rds-truststore.jks \
     -Djavax.net.ssl.trustStorePassword=changeit \
     -jar app.jar
```

### .NET — Windows cert store

On Windows, import `global-bundle.pem` into the **Trusted Root Certification Authorities** store:

```powershell
Import-Certificate -FilePath global-bundle.pem `
  -CertStoreLocation Cert:\LocalMachine\Root
```

On Linux .NET, install in OS store as above.

### Node.js — pass CA explicitly

```javascript
const fs = require('fs');
const caBundle = fs.readFileSync('/etc/ssl/certs/global-bundle.pem', 'utf8');
const caList = caBundle.split(/-----END CERTIFICATE-----\n?/)
                       .filter(c => c.trim())
                       .map(c => c + '-----END CERTIFICATE-----\n');

const config = {
  server: creds.host, port: 1433,
  options: {
    encrypt: true,
    trustServerCertificate: false,
    cryptoCredentialsDetails: { ca: caList, minVersion: 'TLSv1.2' },
  },
};
```

## Enforce encryption on RDS

Create an option group with `SQLSERVER_FORCE_TLS_VERSION` and/or `FORCE_ENCRYPTION`:

```bash
# Create option group
aws rds create-option-group \
  --option-group-name sqlserver-tls12 \
  --engine-name sqlserver-se \
  --major-engine-version 16.00 \
  --option-group-description "Force TLS 1.2+"

# Add force-encryption option
aws rds add-option-to-option-group \
  --option-group-name sqlserver-tls12 \
  --options "OptionName=SQLSERVER_FORCE_TLS_VERSION,OptionSettings=[{Name=TLS_VERSION,Value=1.2}]" \
  --apply-immediately

# Apply to instance
aws rds modify-db-instance \
  --db-instance-identifier mydb \
  --option-group-name sqlserver-tls12 \
  --apply-immediately
```

After this, TLS 1.2+ is the minimum accepted by the server. Plaintext or TLS 1.0/1.1 connections will fail.

## Verify encryption at runtime

```sql
SELECT
  encrypt_option,       -- TRUE if TLS is active
  auth_scheme,          -- SQL, KERBEROS, NTLM
  net_transport,
  protocol_type,
  protocol_version      -- 1946157060 = TDS 7.4; 1936879620 = TDS 7.3
FROM sys.dm_exec_connections
WHERE session_id = @@SPID
```

`encrypt_option = 1` (or `TRUE`) means the connection is encrypted. If `0`, the client didn't request TLS (or couldn't negotiate it).

## Certificate rotation

RDS uses the `rds-ca-rsa2048-g1` CA by default (2024+). Previous CAs (`rds-ca-2019`, `rds-ca-2015`) have expired.

To check your instance:

```bash
aws rds describe-db-instances \
  --db-instance-identifier mydb \
  --query 'DBInstances[0].CACertificateIdentifier'
# Expected: rds-ca-rsa2048-g1
```

To rotate (no restart required for 2019→rsa2048-g1):

```bash
aws rds modify-db-instance \
  --db-instance-identifier mydb \
  --ca-certificate-identifier rds-ca-rsa2048-g1 \
  --apply-immediately
```

After rotation, clients that don't have the current CA bundle will fail TLS handshake. Roll out updated `global-bundle.pem` to clients BEFORE rotating.

### Available CAs

- `rds-ca-rsa2048-g1` — default, RSA 2048-bit, expires 2061
- `rds-ca-rsa4096-g1` — RSA 4096-bit for stricter compliance
- `rds-ca-ecc384-g1` — ECDSA P-384 (smaller, faster, requires TLS_ECDHE_ECDSA cipher suites)

`global-bundle.pem` contains all of these — rotating between them doesn't require a different bundle.

## Common errors

### "A connection was successfully established with the server, but then an error occurred during the pre-login handshake"

Caused by:

- TLS version mismatch (client < 1.2, server requires 1.2+)
- Cert chain not trusted (CA bundle missing from client)
- Network tampering (rare — check for corporate TLS proxies)

Fix: install CA bundle, upgrade client (SSMS 18.x+, drivers to current versions).

### `SSL Provider: The target principal name is incorrect`

Client verifying CN against hostname. Either:

- Connect to the exact hostname the cert was issued for (`mydb.xxxx.us-east-1.rds.amazonaws.com`), OR
- Set `hostNameInCertificate=*.rds.amazonaws.com` (Java) / equivalent

Common through SSM tunnel (CN won't match `localhost`) — see `ssm-tunneling.md`.

### `Could not establish trust relationship for the SSL/TLS secure channel`

.NET-specific. Either:

- Install RDS CA bundle in Trusted Root
- Set `TrustServerCertificate=True` (dev only — don't use in prod)

### SSMS pre-login failure

Upgrade SSMS to 18.x or later. SSMS 17 and earlier use TLS 1.0 by default and will fail against a server forcing TLS 1.2+.

## Don't do

- Don't set `TrustServerCertificate=True` in production — it bypasses cert validation
- Don't disable `rds.force_ssl` by removing the option group; use it to enforce, not relax
- Don't embed the CA bundle in the application code — distribute via package or OS trust store
