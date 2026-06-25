# RDS for Db2 — Drivers, Kerberos, Multi-Instance

Connecting from Python, Java, and laptop clients; Kerberos/Active Directory auth; managing multiple RDS for Db2 instances from the same shell.

## Python with SSL

```python
import ibm_db

conn_str = (
    "DATABASE=RDSADMIN;"
    "HOSTNAME=<rds-endpoint>;"
    "PORT=50443;"
    "PROTOCOL=TCPIP;"
    "UID=<master-user>;"
    "PWD=<password>;"
    "Security=SSL;"
    "SSLServerCertificate=/path/to/<region>-bundle.pem;"
)
conn = ibm_db.connect(conn_str, "", "")
```

Download the cert bundle first:

```bash
curl -sL https://truststore.pki.rds.amazonaws.com/<region>/<region>-bundle.pem -o ~/<region>-bundle.pem
```

## Java with SSL (no keystore)

Source: <https://aws.amazon.com/blogs/database/create-an-ssl-connection-to-amazon-rds-for-db2-in-java-without-keystore-or-keytool/>

With the IBM Db2 JDBC driver (`db2jcc4.jar`), point `sslTrustStoreLocation` at the PEM file — no keystore or keytool needed:

```java
Properties props = new Properties();
props.setProperty("user", "<master-user>");
props.setProperty("password", "<password>");
props.setProperty("sslConnection", "true");
props.setProperty("sslTrustStoreLocation", "/path/to/<region>-bundle.pem");

Connection conn = DriverManager.getConnection(
    "jdbc:db2://<rds-endpoint>:50443/RDSADMIN:sslConnection=true;",
    props
);
```

See `scripts/Db2SslTest.java` for a runnable end-to-end example.

## MacBook / laptop

Install IBM Db2 Data Server Driver Package (`dsdriver`) from IBM Fix Central or Passport Advantage:

```bash
source ~/dsdriver/bin/db2profile
db2 catalog tcpip node RDSNODE remote <rds-endpoint> server 50000
db2 catalog database <dbname> as RDSDB at node RDSNODE
db2 terminate
db2 connect to RDSDB user <master-user> using '<password>'
```

For SSL, download the bundle (same URL as above) and catalog with SSL parameters pointing to the PEM.

## Kerberos / Active Directory

For self-managed Active Directory join and Kerberos authentication — AD permission delegation, the Secrets Manager secret keys, the `--domain-fqdn/-ou/-auth-secret-arn/-dns-ips` join flags, the AD port matrix, and the JDBC Kerberos connection (`securityMechanism=11`) with the bundled `Db2KerberosConnection.java` / `db2-kerberos-test.sh` test — see `ad-kerberos.md`.

## Multi-instance workflow

`db2client-configure.sh` configures one instance at a time. Re-run for each:

```bash
# Configure instance 1
REGION=us-east-1 source db2client-configure.sh  # select end-to-end-trust

# Configure instance 2
REGION=us-east-1 source db2client-configure.sh  # select trp-test-by-ibm

# Switch between them in one session
db2_use end-to-end-trust
db2 "connect to RDSADMIN user admin using '$MASTER_USER_PASSWORD'"
db2 "select * from sysibm.sysdummy1"
db2 connect reset

db2_use trp-test-by-ibm
db2 "connect to RDSADMIN user admin using '$MASTER_USER_PASSWORD'"
db2 connect reset

db2_show_env   # confirm which instance is active
```

How `db2_use` actually works (important for understanding password rotation):

- Reads `~/.db2instances` (populated by `db2client-configure.sh` for each instance you registered).
- Calls `aws secretsmanager get-secret-value` against the instance's secret to fetch the **current** master password (automatically handles secret rotation).
- If no secret is associated, falls back to `~/.need_password`.
- If neither exists, prompts interactively.
- Rewrites `~/.db2env` with the active instance's DSN, user, password.
- Prints the two connect commands to run.

So after a password rotation in Secrets Manager, the only thing you need to do is re-run `db2_use <instance-id>` — the helper picks up the new password automatically. You do not need to re-run `db2client-configure.sh`.

## Files reference (quick)

| Path | Purpose |
|---|---|
| `~/functions.sh` | Helper functions |
| `~/db2client-configure.sh` | Re-run to refresh DSN setup |
| `~/CONN_HELP_README.txt` | Last configure's connect commands |
| `~/.db2env` | Active instance credentials (`chmod 600`) |
| `~/.db2instances` | Instance registry, no passwords (`chmod 600`) |
| `~/.need_password` | Passwords when not using Secrets Manager — dev/test only, never production (`chmod 600`) |
| `~/<region>-bundle.pem` | RDS SSL certificate bundle |
| `~/sqllib/cfg/db2dsdriver.cfg` | Db2 DSN config |
| `~/sqllib/cfg/db2cli.ini` | Db2 CLI config |
