# Connect — CLI and GUI Tools (SQL*Plus, SQLcl, SQL Developer, DBeaver, Toad)

## Prerequisite — no direct laptop path

ODB@AWS has no public endpoint. Laptop/workstation clients MUST use a bastion + tunnel or run the tool on an EC2 in the peered VPC. Follow **connect-ssh-tunnel.md** (loaded reference) for tunnel setup before the sections below.

## SQL*Plus

Requires Oracle Instant Client.

```bash
# TCP
sqlplus app_user/<password>@"cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com"

# TCPS with wallet
export TNS_ADMIN=/opt/oracle/wallet
sqlplus app_user/<password>@mydb_high

# As SYSDBA on ExaDB-D
sqlplus sys/<password>@"cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com" as sysdba
```

## SQLcl

Java-based; includes its own JDBC driver. No Instant Client install needed.

```bash
# TCP
sql app_user/<password>@"cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com"

# TCPS with wallet
export TNS_ADMIN=/opt/oracle/wallet
sql app_user/<password>@mydb_high

# /nolog pattern with cloud config
sql /nolog
SQL> set cloudconfig /path/to/wallet.zip
SQL> connect app_user/<password>@mydb_high
```

## SQL Developer

Three access methods; the first is preferred.

### 1. Built-in SSH tunnel (preferred — DN match works)

1. New Connection → **SSH** tab → Use SSH Tunnel → enter bastion host, port 22, `ec2-user`, browse to `.pem` key file.
2. **Main** tab → Connection Type **Basic** → Hostname = real SCAN hostname, Port = 1521, Service Name = `orclpdb1.sub1.vcn1.oraclevcn.com`.
3. Test Connection.

For TCPS with built-in tunnel, use **Custom JDBC URL**:
```
jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=<scan-hostname>)(PORT=2484))(CONNECT_DATA=(SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com))(SECURITY=(SSL_SERVER_DN_MATCH=TRUE)))
```
Configure wallet JVM options in `sqldeveloper.conf`:
```
AddVMOption -Doracle.net.tns_admin=/opt/oracle/wallet
AddVMOption -Djavax.net.ssl.trustStore=/opt/oracle/wallet/truststore.jks
AddVMOption -Djavax.net.ssl.trustStorePassword=<password>
```

### 2. External SSM/SSH tunnel + `localhost`

After starting an external tunnel (see **connect-ssh-tunnel.md** (loaded reference)):
- Connection Type **Basic** → Hostname = `localhost`, Port = forwarded local port.
- For TCPS over external tunnel: use Custom JDBC URL with `SSL_SERVER_DN_MATCH=FALSE` — the cert CN is the SCAN hostname, not `localhost`.

### 3. Cloud Wallet (Autonomous DB)

- Connection Type **Cloud Wallet** → browse to wallet ZIP → pick TNS alias (e.g., `mydb_high`). Works over the built-in SSH tunnel.

## DBeaver

### Driver setup

1. Database → Driver Manager → Oracle → add `ojdbc11.jar`, `oraclepki.jar`, `osdt_core.jar`, `osdt_cert.jar`.

### Built-in SSH tunnel (preferred)

1. New Connection → Oracle → **SSH** tab → Use SSH Tunnel → bastion host, port 22, `ec2-user`, public-key auth pointing at `.pem`.
2. **Main** tab → Connection Type **Custom** → Host = real SCAN hostname, Port = 1521 or 2484, Database/Service = `orclpdb1.sub1.vcn1.oraclevcn.com`.
3. For TCPS, **Driver Properties**:
   - `oracle.net.tns_admin=/opt/oracle/wallet`
   - `javax.net.ssl.trustStore=/opt/oracle/wallet/truststore.jks`
   - `javax.net.ssl.trustStorePassword=<password>`
   - `oracle.net.ssl_server_dn_match=true`

### External tunnel alternative

JDBC URL: `jdbc:oracle:thin:@//localhost:1521/orclpdb1.sub1.vcn1.oraclevcn.com`.

For TCPS over external tunnel: `jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=localhost)(PORT=2484))(CONNECT_DATA=(SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com))(SECURITY=(SSL_SERVER_DN_MATCH=FALSE)))`.

### Wallet via dbeaver.ini

```
-Doracle.net.tns_admin=/opt/oracle/wallet
-Djavax.net.ssl.trustStore=/opt/oracle/wallet/truststore.jks
-Djavax.net.ssl.trustStorePassword=<password>
```

## Toad for Oracle

Toad has no built-in SSH tunnel. Use an external SSM/SSH tunnel and connect to `localhost`, or install Toad on a Windows EC2 in the peered VPC and use RDP.

For TCPS over external tunnel:
- Set `TNS_ADMIN` to the wallet directory before launching Toad.
- Add a custom `tnsnames.ora` entry pointing to `localhost:2484`.
- Set `SSL_SERVER_DN_MATCH=FALSE` in `sqlnet.ora`.

## Critical Rules

- No direct laptop connection — always tunnel or run the tool on an EC2 in the peered VPC.
- Use service names (never SIDs) in connection strings.
- Built-in SSH tunnel in SQL Developer / DBeaver preserves DN match because the client resolves the real SCAN hostname through the tunnel.
- External tunnel requires `SSL_SERVER_DN_MATCH=FALSE` for TCPS; use this only for developer access, not production.
- Never store wallet passwords in GUI tool profiles on shared machines.
- Set `TNS_ADMIN` for SQL*Plus / SQLcl; SQLcl is Java-based and needs no Oracle Client.
