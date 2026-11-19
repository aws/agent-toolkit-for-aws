# Connect — Java (JDBC, Spring Boot, HikariCP, UCP)

## Driver

Use `ojdbc11.jar` for Java 11+. Use `ojdbc8.jar` only on Java 8. Never `ojdbc6` or `ojdbc7` — they lack modern TLS and auth protocols and will fail with ORA-28040.

For TCPS add: `oraclepki.jar`, `osdt_core.jar`, `osdt_cert.jar`.

### Maven

```xml
<dependency>
  <groupId>com.oracle.database.jdbc</groupId>
  <artifactId>ojdbc11</artifactId>
  <version>23.6.0.24.10</version>
</dependency>
<dependency>
  <groupId>com.oracle.database.security</groupId>
  <artifactId>oraclepki</artifactId>
  <version>23.6.0.24.10</version>
</dependency>
<dependency>
  <groupId>com.oracle.database.security</groupId>
  <artifactId>osdt_core</artifactId>
  <version>23.6.0.24.10</version>
</dependency>
<dependency>
  <groupId>com.oracle.database.security</groupId>
  <artifactId>osdt_cert</artifactId>
  <version>23.6.0.24.10</version>
</dependency>
```

## TCP — Easy Connect

```java
String url = "jdbc:oracle:thin:@//cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com";
Connection conn = DriverManager.getConnection(url, "app_user", password);
```

## TCP — TNS Descriptor (recommended for HA)

```java
String url = "jdbc:oracle:thin:@(DESCRIPTION="
  + "(ADDRESS_LIST=(LOAD_BALANCE=ON)(FAILOVER=ON)"
  + "(ADDRESS=(PROTOCOL=TCP)(HOST=cluster-abc-scan.sub1.vcn1.oraclevcn.com)(PORT=1521)))"
  + "(CONNECT_DATA=(SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com)))";
Connection conn = DriverManager.getConnection(url, "app_user", password);
```

## TCPS with Wallet

Set system properties before creating the connection:

```java
System.setProperty("oracle.net.tns_admin", "/opt/oracle/wallet");
System.setProperty("javax.net.ssl.trustStore", "/opt/oracle/wallet/truststore.jks");
System.setProperty("javax.net.ssl.trustStorePassword", truststorePassword);
System.setProperty("oracle.net.ssl_server_dn_match", "true");
```

Connection URL:

```java
String url = "jdbc:oracle:thin:@(DESCRIPTION="
  + "(ADDRESS_LIST=(LOAD_BALANCE=ON)"
  + "(ADDRESS=(PROTOCOL=TCPS)(HOST=cluster-abc-scan.sub1.vcn1.oraclevcn.com)(PORT=2484)))"
  + "(CONNECT_DATA=(SERVICE_NAME=orclpdb1.sub1.vcn1.oraclevcn.com))"
  + "(SECURITY=(SSL_SERVER_DN_MATCH=TRUE)))";
```

Or use a TNS alias: `jdbc:oracle:thin:@mydb_high`.

## HikariCP

```java
HikariConfig config = new HikariConfig();
config.setJdbcUrl("jdbc:oracle:thin:@mydb_high");
config.setUsername("app_user");
config.setPassword(password);  // from Secrets Manager
config.setMaximumPoolSize(10);
config.setMinimumIdle(2);
config.setIdleTimeout(300_000);
config.setConnectionTimeout(10_000);
config.setMaxLifetime(1_800_000);
config.addDataSourceProperty("oracle.net.tns_admin", "/opt/oracle/wallet");
HikariDataSource ds = new HikariDataSource(config);
```

## Oracle UCP (Fast Connection Failover for RAC)

```java
PoolDataSource pds = PoolDataSourceFactory.getPoolDataSource();
pds.setConnectionFactoryClassName("oracle.jdbc.pool.OracleDataSource");
pds.setURL("jdbc:oracle:thin:@mydb_high");
pds.setUser("app_user");
pds.setPassword(password);
pds.setMinPoolSize(2);
pds.setMaxPoolSize(10);
pds.setInactiveConnectionTimeout(300);
pds.setFastConnectionFailoverEnabled(true);
```

## Spring Boot — application.yml (TCP)

```yaml
spring:
  datasource:
    url: jdbc:oracle:thin:@//cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com
    username: app_user
    password: ${DB_PASSWORD}
    driver-class-name: oracle.jdbc.OracleDriver
    hikari:
      maximum-pool-size: 10
      minimum-idle: 2
      idle-timeout: 300000
      connection-timeout: 10000
      max-lifetime: 1800000
```

## Spring Boot — application.yml (TCPS + Wallet)

```yaml
spring:
  datasource:
    url: jdbc:oracle:thin:@mydb_high
    username: app_user
    password: ${DB_PASSWORD}
    driver-class-name: oracle.jdbc.OracleDriver
    hikari:
      maximum-pool-size: 10
      minimum-idle: 2
      data-source-properties:
        oracle.net.tns_admin: /opt/oracle/wallet
        javax.net.ssl.trustStore: /opt/oracle/wallet/truststore.jks
        javax.net.ssl.trustStorePassword: ${TRUSTSTORE_PASSWORD}
        oracle.net.ssl_server_dn_match: "true"
```

### Secrets Manager integration

Use Spring Cloud AWS:

```yaml
spring:
  config:
    import: aws-secretsmanager:odb/myapp/credentials
```

## Critical Rules

- Always use service names, never SIDs.
- TCPS requires: `oracle.net.tns_admin` + truststore + `ssl_server_dn_match=true`.
- For HA, use TNS descriptor with `LOAD_BALANCE=ON` `FAILOVER=ON`.
- For RAC, enable Fast Connection Failover (FCF) via UCP.
- Never hardcode passwords — pull from Secrets Manager.
- Never commit wallet files to source control; mount them via container volume or Secrets Manager binary secret.
