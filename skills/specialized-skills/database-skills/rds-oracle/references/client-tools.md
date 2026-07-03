# RDS for Oracle — Client Tools

GUI and CLI tools. See `connection-auth.md` for driver choice per tool.

## SQL Developer

Free Oracle GUI. Uses JDBC Thin driver internally — no Oracle Client needed unless you use advanced features (Oracle Wallet, Kerberos with file-based tickets).

### Basic connection

1. Open SQL Developer → click **+** (new connection).
2. **Connection Type**: Basic
3. **Name**: any friendly name
4. **Username**: `admin`
5. **Password**: your password (or leave blank if using Kerberos)
6. **Hostname**: `mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com`
7. **Port**: `1521`
8. **Service Name**: `ORCL` (select **Service Name** radio, not SID)
9. Click **Test** → should say "Success"
10. **Connect**

### SSL/TLS connection

1. New Connection → **Connection Type**: Advanced
2. Custom JDBC URL:

   ```
   jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))(CONNECT_DATA=(SERVICE_NAME=ORCL)))
   ```

3. **Advanced** tab → properties:

   ```
   javax.net.ssl.trustStore=/path/to/truststore.jks
   javax.net.ssl.trustStorePassword=changeit
   oracle.net.ssl_server_dn_match=true
   ```

Build the truststore from the RDS CA bundle (`keytool` only imports the first cert, so split and loop):

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
csplit -z -f /tmp/rds-cert- -b '%02d.pem' global-bundle.pem '/-----BEGIN CERTIFICATE-----/' '{*}'
for f in /tmp/rds-cert-*.pem; do
  keytool -importcert -alias "rds-$(basename "$f" .pem)" -file "$f" \
    -keystore truststore.jks -storepass changeit -noprompt
done
rm -f /tmp/rds-cert-*.pem
```

### Kerberos connection

SQL Developer does NOT support Windows in-memory tickets (`OSMSFT:`). Use a file-based cache.

1. `okinit joedoe@AD.MYAWS.COM` — generate ticket file.
2. Tools → Preferences → Database → **Advanced**:
   - **Kerberos Configuration File**: `/etc/krb5.conf` (or `C:\Oracle_Home\krb5.conf`)
   - **Kerberos Credential Cache**: `/tmp/kerbcache`
3. New Connection → **Authentication Type: Kerberos**, hostname/port/service as normal, username/password blank.

### Built-in SSH tunnel

SQL Developer 23+ has native SSH tunnel support. Requires the bastion to accept **SSH (port 22)** inbound. For SSM-only bastions, use the separate-terminal `aws ssm start-session` approach from `ssm-tunneling.md`.

### Troubleshooting

| Issue | Fix |
|---|---|
| "Network Adapter could not establish connection" | Check hostname, port, SGs. `nc -zv <host> 1521` from same network |
| `ORA-12505` | Switch from SID to Service Name in the connection dialog |
| `ORA-28040` No matching auth protocol | Update SQL Developer (older versions lack newer protocols) |
| Kerberos "Unable to obtain Principal Name" | Ticket expired — `okinit` again; verify `krb5.conf` path |
| SSL "PKIX path building failed" | Truststore missing or wrong path — re-import RDS CA |

## Toad for Oracle

Commercial Oracle GUI. **Always requires Oracle Client (thick mode)** — Toad cannot do thin.

Install Oracle Instant Client, set `ORACLE_HOME` and `PATH`/`LD_LIBRARY_PATH`, and Toad auto-detects.

### Basic connection

1. Session → New Connection
2. **User**: `admin`, **Password**: your password
3. **Database** (one of):
   - Direct: `mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL`
   - Or TNS alias if `tnsnames.ora` is configured
4. **Connect As**: **Normal** (never SYSDBA — RDS doesn't allow SYS)
5. **Connect**

### `tnsnames.ora` for Toad

`$ORACLE_HOME/network/admin/tnsnames.ora`:

```
MYDB_RDS =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT = 1521))
    (CONNECT_DATA = (SERVICE_NAME = ORCL)))
```

Then select `MYDB_RDS` from the Database dropdown.

### NNE vs TLS

- **NNE**: no Toad config — transparent once the option group is applied.
- **TLS (TCPS 2484)**: requires Oracle Wallet.

  ```bash
  orapki wallet create -wallet /path/to/wallet -pwd WalletPass123 -auto_login
  orapki wallet add -wallet /path/to/wallet -trusted_cert \
    -cert global-bundle.pem -pwd WalletPass123
  ```

  `sqlnet.ora`:

  ```
  WALLET_LOCATION = (SOURCE = (METHOD = FILE) (METHOD_DATA = (DIRECTORY = /path/to/wallet)))
  SSL_SERVER_DN_MATCH = YES
  ```

  `tnsnames.ora` entry with `PROTOCOL = TCPS` on port 2484.

### Kerberos

`sqlnet.ora`:

```
SQLNET.AUTHENTICATION_SERVICES = (KERBEROS5PRE,KERBEROS5)
SQLNET.KERBEROS5_CONF = /etc/krb5.conf
SQLNET.KERBEROS5_CONF_MIT = TRUE
SQLNET.KERBEROS5_CC_NAME = /tmp/kerbcache
```

`okinit joedoe@AD.MYAWS.COM`, then in Toad leave **User** blank, **Connect As: Normal**.

### Troubleshooting

| Issue | Fix |
|---|---|
| "Cannot find Oracle Client" | Install Instant Client; set `ORACLE_HOME` and `PATH`; restart Toad |
| `ORA-12154` TNS could not resolve | Check `tnsnames.ora` path; set `TNS_ADMIN` |
| `ORA-12170` timeout | SG not allowing traffic; `tnsping <host>:1521/ORCL` |
| `ORA-28040` | Client too old; upgrade Instant Client |

## SQLcl

Oracle's modern CLI. **Thin mode native** — no Oracle Client needed. Java 11+ required.

```bash
brew install --cask sqlcl   # macOS
```

### Basic connection (never pass password on CLI)

```bash
sql admin@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL
# prompts for password
```

### TLS connection

```bash
export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/path/to/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"
sql admin@"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))(CONNECT_DATA=(SERVICE_NAME=ORCL)))"
```

### Kerberos

Requires thick mode (Oracle Client). Set `ORACLE_HOME`, `okinit <user@REALM>`, then:

```bash
sql /@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL
```

### Verification queries

```sql
-- Check encryption
SELECT network_service_banner FROM v$session_connect_info
WHERE sid = SYS_CONTEXT('USERENV','SID');

-- Check auth method
SELECT SYS_CONTEXT('USERENV','AUTHENTICATION_METHOD') AS auth_method,
       SYS_CONTEXT('USERENV','AUTHENTICATION_TYPE') AS auth_type
FROM dual;

-- Current user + service
SELECT USER, SYS_CONTEXT('USERENV','DB_NAME') AS db_name,
       SYS_CONTEXT('USERENV','SERVICE_NAME') AS service_name
FROM dual;
```

## sqlplus

Classic CLI. Always thick mode (Instant Client).

```bash
# Amazon Linux 2 (el7)
sudo yum install -y oracle-instantclient-release-el7
sudo yum install -y oracle-instantclient-sqlplus oracle-instantclient-basic

# macOS
brew tap InstantClientTap/instantclient
brew install instantclient-sqlplus instantclient-basic
```

### Basic connection (never pass password on CLI)

```bash
sqlplus /nolog
SQL> CONNECT admin@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL
```

TLS: use a full TCPS descriptor after `CONNECT admin@"(DESCRIPTION=...)`" with Oracle Wallet configured in `sqlnet.ora`.

Kerberos: `okinit <user@REALM>` then `sqlplus /@<host>:1521/ORCL`.

### Troubleshooting

| Issue | Fix |
|---|---|
| `SP2-0667: Message file sp1<lang>.msb not found` | `ORACLE_HOME` not set |
| `ORA-12162: net service name incorrectly specified` | Missing `/service_name` in Easy Connect |
| "Error 46 initializing SQL*Plus" | Oracle Client libs not in `LD_LIBRARY_PATH` (Linux) or `PATH` (Windows) |

## DBeaver

Free multi-DB GUI. Uses Oracle JDBC Thin (auto-downloads on first Oracle connection).

### Basic connection

1. Database → New Database Connection → Oracle
2. **Host**: `mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com`
3. **Port**: `1521`
4. **Database**: `ORCL` (Service Name)
5. **Authentication**: Database Native
6. **Username**: `admin`, **Password**: your password
7. Test Connection (driver downloads on first use) → Finish

### SSL/TLS

Edit Connection → **SSL** tab → Use SSL → CA Certificate: `global-bundle.pem`. Or set driver properties:

```
javax.net.ssl.trustStore=/path/to/truststore.jks
javax.net.ssl.trustStorePassword=changeit
```

Built-in SSH tunnel: DBeaver → Edit Connection → **SSH** tab.

### Troubleshooting

| Issue | Fix |
|---|---|
| "Driver download failed" | Check internet; or add `ojdbc11.jar` manually in Driver Manager |
| `ORA-12505` | Switch SID → Service Name |
| "Connection reset" on TLS | Set `oracle.net.ssl_version=1.2` in driver properties |
