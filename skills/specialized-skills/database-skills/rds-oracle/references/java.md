# RDS for Oracle — Java

Use the Oracle JDBC Thin driver `ojdbc11.jar` (Java 11+). No Oracle Client required.

## Maven

```xml
<dependency>
  <groupId>com.oracle.database.jdbc</groupId>
  <artifactId>ojdbc11</artifactId>
  <version>23.4.0.24.05</version>
</dependency>
<!-- Oracle Universal Connection Pool (optional) -->
<dependency>
  <groupId>com.oracle.database.jdbc</groupId>
  <artifactId>ucp</artifactId>
  <version>23.4.0.24.05</version>
</dependency>
```

## Basic JDBC connection

```java
import java.sql.*;

public class OracleRDS {
  public static void main(String[] args) throws Exception {
    String url = "jdbc:oracle:thin:@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL";
    try (Connection conn = DriverManager.getConnection(url, "dbadmin", "<from-secrets-manager>");
         Statement stmt = conn.createStatement();
         ResultSet rs = stmt.executeQuery("SELECT sysdate FROM dual")) {
      while (rs.next()) System.out.println(rs.getString(1));
    }
  }
}
```

## JDBC URL formats

```java
// Easy Connect
String url = "jdbc:oracle:thin:@hostname:1521/ORCL";

// TNS descriptor (useful for CMAN, failover, TCPS)
String url = "jdbc:oracle:thin:@(DESCRIPTION="
           + "(ADDRESS=(PROTOCOL=TCP)(HOST=hostname)(PORT=1521))"
           + "(CONNECT_DATA=(SERVICE_NAME=ORCL)))";

// Route 53 CNAME
String url = "jdbc:oracle:thin:@mydb.example.internal:1521/ORCL";
```

## HikariCP (Spring Boot)

Standard Spring Boot setup:

```java
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

HikariConfig cfg = new HikariConfig();
cfg.setJdbcUrl("jdbc:oracle:thin:@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL");
cfg.setUsername("dbadmin");
// Password is fetched from AWS Secrets Manager at runtime; see connection-auth.md section (b) — via AWS Secrets Manager
cfg.setPassword("<from-secrets-manager>");
cfg.setMaximumPoolSize(10);
cfg.setMinimumIdle(2);
cfg.setConnectionTestQuery("SELECT 1 FROM dual");   // Oracle needs a non-trivial test query
cfg.setValidationTimeout(5_000);
cfg.setConnectionTimeout(10_000);

HikariDataSource ds = new HikariDataSource(cfg);
```

`application.yml`:

```yaml
spring:
  datasource:
    url: jdbc:oracle:thin:@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL
    username: ${DB_USER}
    password: ${DB_PASSWORD}
    driver-class-name: oracle.jdbc.OracleDriver
    hikari:
      maximum-pool-size: 10
      minimum-idle: 2
      connection-test-query: SELECT 1 FROM dual
```

## Oracle UCP (alternative)

Oracle's native connection pool:

```java
import oracle.ucp.jdbc.PoolDataSource;
import oracle.ucp.jdbc.PoolDataSourceFactory;

PoolDataSource pds = PoolDataSourceFactory.getPoolDataSource();
pds.setConnectionFactoryClassName("oracle.jdbc.pool.OracleDataSource");
pds.setURL("jdbc:oracle:thin:@mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com:1521/ORCL");
pds.setUser("dbadmin");
pds.setPassword("<from-secrets-manager>");
pds.setInitialPoolSize(2);
pds.setMinPoolSize(2);
pds.setMaxPoolSize(10);
pds.setConnectionWaitTimeout(5);
pds.setInactiveConnectionTimeout(60);
pds.setValidateConnectionOnBorrow(true);
pds.setSQLForValidateConnection("SELECT 1 FROM dual");

try (Connection conn = pds.getConnection()) { /* ... */ }
```

## Secrets Manager integration

```java
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.zaxxer.hikari.*;

public static HikariDataSource fromSecret(String secretName) throws Exception {
  SecretsManagerClient sm = SecretsManagerClient.create();
  String json = sm.getSecretValue(
      GetSecretValueRequest.builder().secretId(secretName).build()
  ).secretString();
  JsonObject s = JsonParser.parseString(json).getAsJsonObject();

  HikariConfig cfg = new HikariConfig();
  cfg.setJdbcUrl(String.format("jdbc:oracle:thin:@%s:%d/%s",
      s.get("host").getAsString(), s.get("port").getAsInt(), s.get("dbname").getAsString()));
  cfg.setUsername(s.get("username").getAsString());
  cfg.setPassword(s.get("password").getAsString());
  cfg.setConnectionTestQuery("SELECT 1 FROM dual");
  cfg.setMaximumPoolSize(10);
  return new HikariDataSource(cfg);
}
```

Task/execution role needs `secretsmanager:GetSecretValue` on the secret ARN (+ `kms:Decrypt` on the CMK if customer-managed).

## TLS/TCPS thin mode

```java
String url = "jdbc:oracle:thin:@(DESCRIPTION="
           + "(ADDRESS=(PROTOCOL=TCPS)(HOST=mydb.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com)(PORT=2484))"
           + "(CONNECT_DATA=(SERVICE_NAME=ORCL)))";

Properties props = new Properties();
props.setProperty("user", "dbadmin");
props.setProperty("password", "<from-secrets-manager>");
props.setProperty("oracle.net.ssl_server_dn_match", "true");
props.setProperty("javax.net.ssl.trustStore", "/path/to/truststore.jks");
props.setProperty("javax.net.ssl.trustStorePassword", "changeit");

Connection conn = DriverManager.getConnection(url, props);
```

Create the truststore from the RDS CA bundle:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
csplit -z -f /tmp/cert- -b '%02d.pem' global-bundle.pem '/-----BEGIN CERTIFICATE-----/' '{*}'
for f in /tmp/cert-*.pem; do
  keytool -importcert -alias "rds-$(basename "$f" .pem)" -file "$f" \
    -keystore truststore.jks -storepass changeit -noprompt
done
rm -f /tmp/cert-*.pem
```

## Pool sizing

| Workload | initial | min | max |
|---|---|---|---|
| Low | 1 | 1 | 5 |
| Medium | 2 | 2 | 10 |
| High | 5 | 5 | 20 |

`max` ≤ RDS `max_connections` / number of app instances. For auto-scaled ECS/EKS, budget for the scale-out ceiling.

## Error handling

```java
try (Connection conn = DriverManager.getConnection(url, user, password)) {
  /* ... */
} catch (SQLException e) {
  switch (e.getErrorCode()) {
    case 12170: System.err.println("TNS connect timeout — check SGs and network"); break;
    case 1017:  System.err.println("Invalid username/password"); break;
    case 12541: System.err.println("No listener — check RDS endpoint/port"); break;
    case 12514: System.err.println("Service name mismatch"); break;
    default:    System.err.println("ORA-" + e.getErrorCode() + ": " + e.getMessage());
  }
}
```
