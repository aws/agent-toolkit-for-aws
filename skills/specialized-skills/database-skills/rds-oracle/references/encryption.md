# RDS for Oracle — Encryption (SSL/TLS and NNE)

RDS Oracle supports two transport-encryption methods. **You cannot use both on the same instance.** If SSL is enabled, disable NNE first, and vice versa. Both are available on all licensed editions of Oracle 19c and 21c on RDS.

Source: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.Oracle.Options.SSL.html

## Option 1 — Native Network Encryption (NNE) — transparent

No client-side cert needed. Add the `NATIVE_NETWORK_ENCRYPTION` option to an RDS option group:

| Parameter | Value |
|---|---|
| SQLNET.ENCRYPTION_SERVER | REQUIRED |
| SQLNET.ENCRYPTION_TYPES_SERVER | AES256 |
| SQLNET.CRYPTO_CHECKSUM_SERVER | REQUIRED |
| SQLNET.CRYPTO_CHECKSUM_TYPES_SERVER | SHA256 |

### Terraform

```hcl
resource "aws_db_option_group" "oracle_nne" {
  name                 = "oracle-nne"
  engine_name          = "oracle-ee"
  major_engine_version = "19"

  option {
    option_name = "NATIVE_NETWORK_ENCRYPTION"
    option_settings {
      name  = "SQLNET.ENCRYPTION_SERVER"
      value = "REQUIRED"
    }
    option_settings {
      name  = "SQLNET.ENCRYPTION_TYPES_SERVER"
      value = "AES256"
    }
    option_settings {
      name  = "SQLNET.CRYPTO_CHECKSUM_SERVER"
      value = "REQUIRED"
    }
    option_settings {
      name  = "SQLNET.CRYPTO_CHECKSUM_TYPES_SERVER"
      value = "SHA256"
    }
  }
}
```

Clients connect normally on port 1521. Encryption is applied transparently.

## Option 2 — TLS (certificate-based, port 2484)

Add the `SSL` option to an RDS option group with port 2484:

```hcl
resource "aws_db_option_group" "oracle_tls" {
  name                 = "oracle-tls"
  engine_name          = "oracle-ee"
  major_engine_version = "19"

  option {
    option_name = "SSL"
    port        = 2484

    option_settings {
      name  = "SQLNET.SSL_VERSION"
      value = "1.2"
    }
  }
}
```

When SSL is enabled, RDS opens a **second port** (default 2484) for encrypted connections. Port 1521 remains open for clear-text. This lets both run simultaneously.

## Cipher suites (FIPS and FedRAMP)

Default: `SSL_RSA_WITH_AES_256_CBC_SHA`. For stronger security or FedRAMP, set `SQLNET.CIPHER_SUITE`:

| Cipher Suite | TLS | FIPS | FedRAMP |
|---|---|---|---|
| SSL_RSA_WITH_AES_256_CBC_SHA (default) | 1.0, 1.2 | Yes | No |
| SSL_RSA_WITH_AES_256_CBC_SHA256 | 1.2 | Yes | No |
| SSL_RSA_WITH_AES_256_GCM_SHA384 | 1.2 | Yes | No |
| **TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384** | 1.2 | Yes | Yes |
| TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 | 1.2 | Yes | Yes |
| TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384 | 1.2 | Yes | Yes |
| TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256 | 1.2 | Yes | Yes |
| TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384 | 1.2 | Yes | Yes |
| TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384 | 1.2 | Yes | Yes |

For **FedRAMP compliance**, pick one of the `TLS_ECDHE_*` suites.

## Certificate types

RDS supports RSA and ECDSA certificates. The cipher suite **must match** the certificate type:

- **RSA certs** (`rds-ca-2019`, `rds-ca-rsa2048-g1`, `rds-ca-rsa4096-g1`) → use `SSL_RSA_*` or `TLS_ECDHE_RSA_*` suites.
- **ECDSA certs** (`rds-ca-ecc384-g1`) → use `TLS_ECDHE_ECDSA_*` suites only.

Mismatch → connection fails at TLS handshake.

## FIPS 140-2

Enable by setting `FIPS.SSLFIPS_140 = TRUE` in the `SSL` option. All suites in the table above are FIPS-compliant.

## Download the RDS CA bundle

```bash
# Global (all RDS regions)
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem

# Region-specific
curl -o rds-ca-bundle.pem https://truststore.pki.rds.amazonaws.com/<region>/<region>-bundle.pem
```

## Python — TLS thin mode

```python
import oracledb

conn = oracledb.connect(
    user="dbadmin",
    password="<from-secrets-manager>",
    dsn="tcps://mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:2484/ORCL",
    ssl_server_dn_match=True,
    wallet_location="/path/to/certs-dir",   # directory containing global-bundle.pem
)
```

For thick mode:

```python
conn = oracledb.connect(
    user="dbadmin", password="<from-secrets-manager>",
    dsn="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=<endpoint>)(PORT=2484))(CONNECT_DATA=(SERVICE_NAME=ORCL))(SECURITY=(SSL_SERVER_DN_MATCH=ON)))",
    wallet_location="/path/to/wallet",      # directory with ewallet.p12, cwallet.sso
)
```

## Java — TLS thin mode

```java
System.setProperty("javax.net.ssl.trustStore", "/path/to/truststore.jks");
System.setProperty("javax.net.ssl.trustStorePassword", "changeit");

String url = "jdbc:oracle:thin:@(DESCRIPTION="
           + "(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))"
           + "(CONNECT_DATA=(SERVICE_NAME=ORCL))"
           + "(SECURITY=(SSL_SERVER_DN_MATCH=ON)))";

Connection conn = DriverManager.getConnection(url, "dbadmin", "secret");
```

### Build the Java truststore

The RDS bundle has many certs. `keytool -importcert` only imports the first, so split and loop:

```bash
csplit -z -f /tmp/rds-cert- -b '%02d.pem' global-bundle.pem '/-----BEGIN CERTIFICATE-----/' '{*}'
for f in /tmp/rds-cert-*.pem; do
  keytool -importcert -alias "rds-$(basename "$f" .pem)" \
    -file "$f" -keystore truststore.jks -storepass changeit -noprompt
done
rm -f /tmp/rds-cert-*.pem
```

## Node.js — TLS thin mode

```bash
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

## .NET — TLS

```csharp
var connString = "User Id=dbadmin;Password=<from-secrets-manager>;"
  + "Data Source=(DESCRIPTION="
      + "(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))"
      + "(CONNECT_DATA=(SERVICE_NAME=ORCL)));"
  + "SSL Server Cert DN=CN=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com;";
```

Trust the RDS CA via OS trust store:

```bash
sudo curl -o /usr/local/share/ca-certificates/rds-ca.crt \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
sudo update-ca-certificates
```

## Verify encryption is active

```sql
-- Protocol — 'tcps' for TLS
SELECT SYS_CONTEXT('USERENV','NETWORK_PROTOCOL') FROM dual;

-- Algorithm in use for NNE
SELECT network_service_banner FROM v$session_connect_info
WHERE sid = SYS_CONTEXT('USERENV','SID');
```

Or run `scripts/check_ssl_status.sql` from the bundled scripts.

## Common TLS errors

- **`ORA-29024: Certificate validation failure`** — the RDS CA bundle isn't imported into the client's trust store. Import all certs (see Java section above for the split-and-loop pattern).
- **`ORA-28860: Fatal SSL error`** — TLS version or cipher mismatch. Check `SQLNET.SSL_VERSION = 1.2` and that the client supports TLS 1.2.
- **Connects without SSL but fails with TCPS** — using port 1521 (clear-text) instead of 2484 (TLS), or the option group wasn't applied (and the instance wasn't rebooted if required).
