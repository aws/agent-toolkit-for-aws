# Java — mssql-jdbc

Use the official Microsoft JDBC driver `com.microsoft.sqlserver:mssql-jdbc`. There is no other JDBC driver that is maintained for SQL Server on AWS.

## Install

### Maven

```xml
<dependency>
    <groupId>com.microsoft.sqlserver</groupId>
    <artifactId>mssql-jdbc</artifactId>
    <version>12.6.1.jre11</version>
</dependency>
```

Match the `jreN` suffix to your runtime:

- `jre8` — Java 8
- `jre11` — Java 11
- `jre17` — Java 17/21

### Gradle

```groovy
implementation 'com.microsoft.sqlserver:mssql-jdbc:12.6.1.jre11'
```

## Minimal connection

```java
import java.sql.Connection;
import java.sql.DriverManager;

String url = "jdbc:sqlserver://mydb.xxxx.us-east-1.rds.amazonaws.com:1433;"
           + "databaseName=mydb;"
           + "user=admin;password=secret;"
           + "encrypt=true;"
           + "trustServerCertificate=false;"
           + "hostNameInCertificate=*.rds.amazonaws.com;";

try (Connection conn = DriverManager.getConnection(url)) {
    // ...
}
```

## JDBC URL essentials

| Property | Value | Note |
|---|---|---|
| Host | `mydb.xxxx.us-east-1.rds.amazonaws.com` | Colon, not comma (Java convention) |
| `databaseName` | target database | Required |
| `encrypt` | `true` | Required for production |
| `trustServerCertificate` | `false` | Force cert validation |
| `hostNameInCertificate` | `*.rds.amazonaws.com` | Match wildcard cert |
| `loginTimeout` | `30` | Seconds |
| `socketTimeout` | `30000` | Milliseconds (note unit diff) |

## RDS CA bundle for Java

Download and import into a Java truststore:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem

# Split PEM into individual certs (keytool only imports the first cert from a multi-cert PEM)
csplit -s -z -f rds- -b '%02d.pem' global-bundle.pem '/-----BEGIN CERTIFICATE-----/' '{*}'

# Create truststore and import each cert
for f in rds-*.pem; do
  keytool -import -trustcacerts -alias "$f" -file "$f" \
    -keystore rds-truststore.jks -storepass changeit -noprompt
done
```

Pass to the JVM:

```bash
java -Djavax.net.ssl.trustStore=/path/to/rds-truststore.jks \
     -Djavax.net.ssl.trustStorePassword=changeit \
     -jar app.jar
```

Or programmatically in code (less common). Without this, `trustServerCertificate=false` will fail — see `encryption.md`.

## Windows auth (Kerberos)

```java
String url = "jdbc:sqlserver://database-1.corp.example.com:1433;"
           + "databaseName=mydb;"
           + "integratedSecurity=true;"
           + "authenticationScheme=JavaKerberos;"
           + "encrypt=true;";
```

Requires a Kerberos `krb5.conf` pointing at the domain KDC:

```
[libdefaults]
    default_realm = CORP.EXAMPLE.COM
    dns_lookup_realm = true
    dns_lookup_kdc = true

[realms]
    CORP.EXAMPLE.COM = {
        kdc = dc1.corp.example.com
    }
```

Point the JVM at it:

```bash
java -Djava.security.krb5.conf=/etc/krb5.conf -jar app.jar
```

Keytab-based auth (no password in config):

```bash
java -Djava.security.krb5.conf=/etc/krb5.conf \
     -Djavax.security.auth.useSubjectCredsOnly=false \
     -Djava.security.auth.login.config=jaas.conf \
     -jar app.jar
```

`jaas.conf`:

```
SQLJDBCDriver {
    com.sun.security.auth.module.Krb5LoginModule required
    useKeyTab=true
    keyTab="/path/to/svc-app.keytab"
    principal="svc-app@CORP.EXAMPLE.COM"
    doNotPrompt=true;
};
```

## HikariCP connection pool

Production standard for Java connection pooling:

```xml
<dependency>
    <groupId>com.zaxxer</groupId>
    <artifactId>HikariCP</artifactId>
    <version>5.1.0</version>
</dependency>
```

```java
HikariConfig config = new HikariConfig();
config.setJdbcUrl("jdbc:sqlserver://mydb.xxxx.us-east-1.rds.amazonaws.com:1433;"
                + "databaseName=mydb;encrypt=true;trustServerCertificate=false;");
config.setUsername(creds.getUsername());
config.setPassword(creds.getPassword());
config.setMaximumPoolSize(10);
config.setMinimumIdle(2);
config.setConnectionTimeout(30000);
config.setIdleTimeout(600000);
config.setMaxLifetime(1800000);              // 30 min — handles Multi-AZ failover
config.setConnectionTestQuery("SELECT 1");
config.setValidationTimeout(5000);

HikariDataSource ds = new HikariDataSource(config);
```

`maxLifetime` less than RDS connection max (default 8 hours) prevents stale connections after Multi-AZ failover.

## Secrets Manager

```java
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;

SecretsManagerClient sm = SecretsManagerClient.create();
GetSecretValueRequest req = GetSecretValueRequest.builder()
    .secretId("rds/sqlserver/app").build();
String json = sm.getSecretValue(req).secretString();
// Parse json: {host, port, username, password, dbname, engine}
```

Spring Boot: use `spring-cloud-aws-starter-secrets-manager` to bind secrets to `application.yml` properties directly.

## ECS Fargate

Lambda-style credential caching (outside the handler) isn't applicable — ECS tasks are long-running. Use HikariCP + Secrets Manager resolver pattern:

```java
// Fetch secret once at startup
DbCreds creds = fetchSecret("rds/sqlserver/app");
HikariDataSource ds = buildPool(creds);

// On rotation, the pool's connectionTestQuery will fail — HikariCP evicts
// and creates fresh connections. But the secret value must be re-fetched.
// Consider wrapping in a resilience4j CircuitBreaker or setting `maxLifetime`
// shorter than the rotation interval.
```

## Verify

```sql
SELECT encrypt_option, auth_scheme, net_transport, client_interface_name
FROM sys.dm_exec_connections WHERE session_id = @@SPID
-- client_interface_name for mssql-jdbc: "Microsoft JDBC Driver 12.6 for SQL Server"
```
