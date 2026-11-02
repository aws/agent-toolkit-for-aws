# Flink CDC Connector Guide

This guide covers Change Data Capture (CDC) connector configuration for Apache Flink applications on Amazon Managed Service for Apache Flink. Flink CDC enables reading snapshot and incremental change data from databases without requiring Kafka or Kafka Connect — Debezium runs embedded within the Flink application.

## Overview

Flink CDC is a streaming data integration tool built on Apache Flink that captures database changes in real time. It supports two usage modes:

1. **Source Connectors** (DataStream API / Table API / SQL): Individual CDC source connectors for reading changes from a single database table or set of tables into a Flink job for custom processing. **This is the supported approach for MSF.**
2. **Pipeline API** (YAML-based, Flink CDC 3.x): End-to-end data integration pipelines defined in YAML for whole-database synchronization with schema evolution, routing, and transforms. **This does NOT run on MSF** — it requires the `flink-cdc.sh` CLI which is only available on self-managed Flink clusters.

For MSF deployments, use the Source Connector approach via DataStream API or Table API/SQL.

## Version Compatibility

**CRITICAL:** Flink CDC versions must match your Flink version. Use this mapping for MSF-supported Flink versions:

| Flink CDC Release | Flink 1.20 coordinate | Flink 2.2 coordinate | Notes |
|---|---|---|---|
| `3.6.x` | `3.6.0-1.20` | `3.6.0-2.2` | Recommended for new projects. Per-Flink-version artifacts. |
| `3.5.x` | `3.5.0` | ❌ | Flink 1.20 only. Single unsuffixed artifact. |
| `3.4.x` | `3.4.0` | ❌ | Flink 1.20 only. Single unsuffixed artifact. |
| `3.3.x` | `3.3.0` | ❌ | Flink 1.20 only (also supports 1.18, 1.19). Single unsuffixed artifact. |

For Flink 2.2 on MSF, you must use Flink CDC 3.6.x.

**IMPORTANT — version coordinate change in 3.6.x:** Starting with the 3.6.x line, Flink CDC publishes **per-Flink-version artifacts** on Maven Central. The plain `3.6.0` GAV does NOT exist — only `3.6.0-1.20` and `3.6.0-2.2`. Earlier versions (3.5.x and below) used a single artifact compatible with multiple Flink minors. Always copy the coordinate from the table above; do not assume an unsuffixed `3.6.0` will resolve.

## Supported Database Sources

| Connector | Databases | Key Mechanism |
|---|---|---|
| `mysql-cdc` | MySQL 5.6–8.0.x, Aurora MySQL, RDS MySQL, MariaDB 10.x | Binlog |
| `postgres-cdc` | PostgreSQL 9.6–14, Aurora PostgreSQL, RDS PostgreSQL | WAL / Logical Replication |
| `oracle-cdc` | Oracle 11, 12, 19, 21 | LogMiner or XStream |
| `sqlserver-cdc` | SQL Server 2012–2019 | CT (Change Tracking) |
| `mongodb-cdc` | MongoDB 3.6+ (replica set or sharded) | Change Streams |
| `db2-cdc` | Db2 11.5 | ASN Capture |

All connectors except MongoDB use Debezium under the hood.

## Maven Dependencies

Add the CDC connector for your database. The artifact version corresponds to the Flink CDC release, not the Flink version:

```xml
<!-- MySQL CDC Source -->
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-mysql-cdc</artifactId>
    <version>${flink-cdc.version}</version>
</dependency>

<!-- PostgreSQL CDC Source -->
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-postgres-cdc</artifactId>
    <version>${flink-cdc.version}</version>
</dependency>

<!-- Oracle CDC Source -->
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-oracle-cdc</artifactId>
    <version>${flink-cdc.version}</version>
</dependency>

<!-- SQL Server CDC Source -->
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-sqlserver-cdc</artifactId>
    <version>${flink-cdc.version}</version>
</dependency>

<!-- MongoDB CDC Source -->
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-mongodb-cdc</artifactId>
    <version>${flink-cdc.version}</version>
</dependency>
```

Set `flink-cdc.version` to the per-Flink-version coordinate from the table above:

```xml
<!-- Flink 1.20 -->
<flink-cdc.version>3.6.0-1.20</flink-cdc.version>
<!-- or for Flink 2.2 -->
<flink-cdc.version>3.6.0-2.2</flink-cdc.version>
```

Starting with 3.6.x, Flink CDC publishes per-Flink-version artifacts; the unsuffixed `3.6.0` GAV does not exist on Maven Central. For 3.5.x and earlier (Flink 1.20 only), use the unsuffixed coordinate (e.g., `3.5.0`). See `dependency-management.md` for the full pom.xml template.

**Note:** The MySQL JDBC driver is GPL-licensed and not bundled in the CDC connector JAR. You must add it separately:

```xml
<dependency>
    <groupId>com.mysql</groupId>
    <artifactId>mysql-connector-j</artifactId>
    <version>8.0.33</version>
</dependency>
```

## Database Credentials and Secrets Management

**Secrets Manager is the only supported credential source for CDC on MSF.** Database passwords must be fetched in application code at job startup. Do not put credentials into MSF runtime properties.

The supported pattern is to keep only non-sensitive values plus a **secret ID** in MSF runtime properties, and look up the actual credentials with the AWS SDK in `main()` before constructing the source.

### Fetch from Secrets Manager in application code

Add the AWS SDK Secrets Manager dependency:

```xml
<dependency>
    <groupId>software.amazon.awssdk</groupId>
    <artifactId>secretsmanager</artifactId>
    <version>2.25.0</version>
</dependency>
```

Resolve the secret at job startup and pass the values into the builder:

```java
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

private static DbCreds loadDbCreds(String secretId) throws Exception {
    try (SecretsManagerClient sm = SecretsManagerClient.create()) {
        String json = sm.getSecretValue(
            GetSecretValueRequest.builder().secretId(secretId).build()
        ).secretString();
        JsonNode node = new ObjectMapper().readTree(json);
        return new DbCreds(node.get("username").asText(), node.get("password").asText());
    }
}

// In main(), before building the source:
DbCreds creds = loadDbCreds(cdcConfig.getProperty("secret.id"));

MySqlSource<String> mySqlSource = MySqlSource.<String>builder()
    .hostname(cdcConfig.getProperty("hostname"))
    .port(Integer.parseInt(cdcConfig.getProperty("port", "3306")))
    .databaseList(cdcConfig.getProperty("database"))
    .tableList(cdcConfig.getProperty("database") + "\\." + cdcConfig.getProperty("table"))
    // Load from SecretsManager
    .username(creds.username)
    .password(creds.password)
    // ...
    .build();
```

MSF runtime properties only carry the non-sensitive values plus the secret ID:

```json
[{
  "PropertyGroupId": "cdc.mysql.config",
  "PropertyMap": {
    "hostname": "my-aurora-cluster.cluster-xxxx.us-east-1.rds.amazonaws.com",
    "port": "3306",
    "database": "ecommerce",
    "table": "orders",
    "secret.id": "cdc-db-credentials",
    "server-id": "5400-5404"
  }
}]
```

The secret itself can still be created via CloudFormation/CDK/Terraform — only the *consumption* of the resolved value has to stay out of MSF properties:

### IAM permissions for the MSF execution role

Grant only the specific secret(s) the application uses; do not use `secretsmanager:*` or `Resource: "*"`.

```yaml
- Effect: Allow
  Action:
    - secretsmanager:GetSecretValue
  Resource:
    - !Sub "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:cdc-db-credentials-*"
```

The trailing `-*` covers the random 6-character suffix Secrets Manager appends to secret ARNs. If you encrypt the secret with a customer-managed KMS key, also grant `kms:Decrypt` on that key ARN.

### TLS / SSL to the database

Enable TLS for every CDC connection so traffic between the MSF application and the database is encrypted in transit. The default mode for CDC on MSF is **encryption without certificate verification** (`require` for Postgres, `REQUIRED` for MySQL). MSF does not give you a stable filesystem path to drop a CA bundle on — `${user.dir}` resolves to a runtime working directory that is not the JAR location, and there is no host filesystem you can pre-populate at deploy time. The conventional Postgres/MySQL "extract the bundle to a known path and point `sslrootcert`/`trustCertificateKeyStoreUrl` at it" pattern does not work: even when the file is extracted from the JAR to `/tmp` at startup, the Debezium connectors run their internal JDBC connections from a different JVM context inside the connector, so the file lookup fails (verified: `Could not open SSL root certificate file /tmp/rds-ca-...pem`). The only way to get verify-* working on MSF is to register a custom `SSLSocketFactory` per JDBC driver that loads the bundle from the classpath, which is enough additional surface that it's an opt-in for high-MITM-risk environments rather than a default.

The defense-in-depth layers that **do** apply on MSF without a CA bundle:

- **Network isolation.** MSF runs in your VPC; restrict the database security group to accept connections only from the MSF application's security group. This is the primary control against MITM: an attacker would need to be on the network path inside your VPC, not just anywhere on the internet.
- **TLS in transit.** Even without certificate verification, the connection is encrypted, which protects credentials and replication payload from passive observation.
- **Database-side enforcement.** Set `rds.force_ssl = 1` (RDS/Aurora PostgreSQL parameter group) or `require_secure_transport = ON` (Aurora MySQL) so the database refuses any non-TLS connection. This catches client-side misconfigurations that would otherwise fall back to plaintext.

**MySQL / Aurora MySQL.** Use `sslMode=REQUIRED` on Connector/J (8.0.13+) and `database.ssl.mode=required` on Debezium. This requires TLS, skips peer certificate verification.

```java
Properties jdbcProps = new Properties();
jdbcProps.setProperty("sslMode", "REQUIRED");

Properties debeziumProps = new Properties();
debeziumProps.setProperty("database.ssl.mode", "required");

MySqlSource<String> source = MySqlSource.<String>builder()
    // host/port/user/pwd/databaseList/tableList/serverId/...
    .jdbcProperties(jdbcProps)
    .debeziumProperties(debeziumProps)
    .deserializer(new JsonDebeziumDeserializationSchema())
    .build();
```

**PostgreSQL / Aurora PostgreSQL.** Use Debezium's `database.sslmode=require`. This requires TLS, skips peer certificate verification.

```java
Properties debeziumProps = new Properties();
debeziumProps.setProperty("database.sslmode", "require");
// publication.* and other Debezium props as before

PostgresIncrementalSource<String> pg = PostgresIncrementalSource.<String>builder()
    // host/port/user/pwd/database/schemaList/tableList/slotName/...
    .debeziumProperties(debeziumProps)
    .deserializer(new JsonDebeziumDeserializationSchema())
    .build();
```

#### Stronger verification (verify-ca / verify-full / VERIFY_IDENTITY)

If `require` is not sufficient and you need chain validation, the implementation path is:

1. Bundle the RDS combined CA (`global-bundle.pem`) as a classpath resource in your application JAR (e.g., `src/main/resources/rds-ca-bundle.pem`).
2. Build an `SSLContext` from that resource at job startup, using `getClass().getResourceAsStream(...)` and a `KeyStore` populated from the PEM.
3. Register a custom `SSLSocketFactory` that returns sockets from that context, and reference it by class name in the connector config — Postgres uses `database.sslfactory=<your.class.Name>`, MySQL Connector/J uses the `socketFactory` JDBC URL parameter (or a custom `TrustManager` wired into a `KeyStore` URL the driver can resolve from the classpath).
4. Set `database.sslmode=verify-full` (Postgres) or `sslMode=VERIFY_IDENTITY` (MySQL) on top of the custom factory.

This is non-trivial because each JDBC driver has its own `SSLSocketFactory`/`TrustManager` plug point and the Debezium connector instantiates JDBC connections from inside the source operator, which means the factory class has to be on the classpath of every TaskManager and resolve the bundle without filesystem assumptions. Treat this as opt-in for high-assurance environments; it is not the default for CDC on MSF.

For RDS/Aurora, also enforce TLS at the database side (`rds.force_ssl = 1` in the RDS PostgreSQL parameter group; `require_secure_transport = ON` for Aurora MySQL). With `force_ssl = 1` the database refuses any non-TLS connection, which prevents accidentally falling back to plaintext if the client config is wrong.

## Critical: Incremental Source vs Legacy Source on Flink 2.x

Each Flink CDC artifact (`flink-connector-mysql-cdc`, `flink-connector-postgres-cdc`, etc.) ships **two parallel APIs in the same JAR**. Picking the wrong one is the most common reason CDC jobs don't compile or don't run on Flink 2.x.

**Legacy `SourceFunction`-based source** — older, single-threaded, locking snapshot for MySQL.

| Database | Class | Builder return type |
|---|---|---|
| MySQL | `org.apache.flink.cdc.connectors.mysql.MySqlSource` | `.builder()` returns a `DebeziumSourceFunction<T>` |
| Postgres | `org.apache.flink.cdc.connectors.postgres.PostgreSQLSource` | `.builder()` returns a `DebeziumSourceFunction<T>` |

**Not usable on Flink 2.x.** `SourceFunction` and `env.addSource(...)` were removed in Flink 2.0. The class is still in the artifact for backward compatibility with Flink 1.x consumers, but you cannot wire its output into a Flink 2.x job. Several builder methods on the legacy classes (e.g., Postgres `publicationName(...)`) do **not** exist on the incremental builders — if you copy a snippet that calls them, it won't compile against `3.6.0-2.2`.

**Incremental Source (FLIP-27)** — lock-free parallel snapshot, chunk-level checkpointing.

| Database | Class | Builder return type |
|---|---|---|
| MySQL | `org.apache.flink.cdc.connectors.mysql.source.MySqlSource` | `.<T>builder()` returns `MySqlSourceBuilder<T>`; `build()` returns `MySqlSource<T>` |
| Postgres | `org.apache.flink.cdc.connectors.postgres.source.PostgresSourceBuilder.PostgresIncrementalSource` | `.<T>builder()` returns `PostgresSourceBuilder<T>`; `build()` returns `PostgresIncrementalSource<T>` |

**Required on Flink 2.x.** Used with `env.fromSource(...)`. Use this for all new development on any Flink version.

Two asymmetries to be aware of:

- **Class naming.** MySQL has the same class name `MySqlSource` in two packages — disambiguate by package. Postgres uses different class names (`PostgreSQLSource` legacy vs `PostgresIncrementalSource` incremental), and the incremental class is technically an inner class of `PostgresSourceBuilder`, so the entry-point spelling is unusual: `PostgresIncrementalSource.<T>builder()`.
- **Setter coverage.** The two incremental builders share most options (host/port/user/pwd/database, schema/table list, splitSize, chunkKeyColumn, splitMetaGroupSize, distributionFactor{Upper,Lower}, fetchSize, connectTimeout, connectMaxRetries, connectionPoolSize, startupOptions, debeziumProperties, deserializer, heartbeatInterval, closeIdleReaders, skipSnapshotBackfill, scanNewlyAddedTableEnabled, assignUnboundedChunkFirst, includeSchemaChanges, serverTimeZone), but **the surfaces are not identical**. MySQL has `serverId(...)`, `databaseList(...)`, `jdbcProperties(...)`, `useLegacyJsonFormat(...)`, `parseOnLineSchemaChanges(...)`. Postgres has `slotName(...)`, `decodingPluginName(...)`, `lsnCommitCheckpointsDelay(...)`, `includePartitionedTables(...)`, `includeDatabaseInTableId(...)`. Some knobs that were first-class methods on the legacy Postgres builder (e.g., `publicationName(...)`) are **only** reachable through `debeziumProperties(...)` on the incremental builder.

Always import from the connector's `.source` sub-package, never from the top-level package.

## MySQL CDC Source Configuration

### Database Prerequisites

Before using the MySQL CDC connector, the source database must be configured:

1. **Enable binlog in ROW format** (required):

   ```sql
   -- Verify binlog is enabled and in ROW format
   SHOW VARIABLES LIKE 'log_bin';        -- Must be ON
   SHOW VARIABLES LIKE 'binlog_format';  -- Must be ROW
   ```

2. **Create a dedicated CDC user** with minimal required permissions:

   ```sql
   CREATE USER 'flink_cdc'@'%' IDENTIFIED BY '<password>';
   GRANT SELECT, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'flink_cdc'@'%';
   FLUSH PRIVILEGES;
   ```

   Note: `RELOAD` permission is NOT required when incremental snapshot is enabled (the default).

3. **For Aurora MySQL / RDS MySQL**: Binlog is enabled by default. Ensure the parameter group has `binlog_format = ROW`. For Aurora, set `binlog_replication_globaldb` to `1` if using Global Database.

4. **Recommended: Enable GTID mode** for high availability failover:

   ```
   gtid_mode = on
   enforce_gtid_consistency = on
   ```

### DataStream API Pattern

```java
// CORRECT — incremental Source (FLIP-27), usable on Flink 2.x via env.fromSource(...)
import org.apache.flink.cdc.connectors.mysql.source.MySqlSource;
// WRONG — legacy SourceFunction, not usable on Flink 2.x:
// import org.apache.flink.cdc.connectors.mysql.MySqlSource;
import org.apache.flink.cdc.debezium.JsonDebeziumDeserializationSchema;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;

// Load connection config from MSF application properties
Map<String, Properties> applicationProperties = loadApplicationProperties(env);
Properties cdcConfig = applicationProperties.get("cdc.mysql.config");

MySqlSource<String> mySqlSource = MySqlSource.<String>builder()
    .hostname(cdcConfig.getProperty("hostname"))
    .port(Integer.parseInt(cdcConfig.getProperty("port", "3306")))
    .databaseList(cdcConfig.getProperty("database"))
    .tableList(cdcConfig.getProperty("database") + "\\." + cdcConfig.getProperty("table"))
    // Load from SecretsManager
    .username(creds.username)
    .password(creds.password)
    .serverId(cdcConfig.getProperty("server-id", "5400-5404"))
    .deserializer(new JsonDebeziumDeserializationSchema())
    .build();

DataStream<String> cdcStream = env
    .fromSource(mySqlSource, WatermarkStrategy.noWatermarks(), "mysql-cdc-source")
    .uid("mysql-cdc-source-uid");
```

### Key MySQL CDC Configuration Options

| Option | Required | Default | Description |
|---|---|---|---|
| `hostname` | Yes | — | MySQL server hostname or IP |
| `port` | No | 3306 | MySQL server port |
| `username` | Yes | — | MySQL user with replication permissions |
| `password` | Yes | — | MySQL user password |
| `database-name` | Yes | — | Database name (supports regex for multi-database) |
| `table-name` | Yes | — | Table name (supports regex, format: `db\.table`) |
| `server-id` | Recommended | Random 5400-6400 | Unique server ID or range (e.g., `5400-5404` for parallelism 4) |
| `scan.incremental.snapshot.enabled` | No | `true` | Enable lock-free parallel snapshot reading |
| `scan.incremental.snapshot.chunk.size` | No | 8096 | Rows per snapshot chunk |
| `scan.startup.mode` | No | `initial` | Startup mode: `initial`, `earliest-offset`, `latest-offset`, `specific-offset`, `timestamp` |
| `server-time-zone` | No | System default | MySQL server timezone (e.g., `UTC`) |
| `heartbeat.interval` | No | `30s` | Heartbeat interval for binlog position tracking |

### CRITICAL: Server ID Configuration

Every MySQL CDC reader needs a globally unique server ID across all clients connected to the MySQL cluster. When running with parallelism > 1 and incremental snapshot enabled, you must specify a server ID range:

```java
// For parallelism of 4, provide a range of at least 4 IDs
.serverId("5400-5404")
```

If multiple Flink CDC jobs read from the same MySQL instance, their server ID ranges must not overlap. Overlapping server IDs cause the error: `A slave with the same server_uuid/server_id as this slave has connected to the master`.

## PostgreSQL CDC Source Configuration

### Database Prerequisites

1. **Set WAL level to logical** (requires restart):

   ```sql
   -- Check current setting
   SHOW wal_level;  -- Must be 'logical'
   
   -- For RDS/Aurora PostgreSQL: set rds.logical_replication = 1 in parameter group
   ```

2. **Set table replica identity to FULL** (required for UPDATE/DELETE events):

   ```sql
   ALTER TABLE my_schema.my_table REPLICA IDENTITY FULL;
   ```

   Without `FULL`, Debezium cannot capture the before-image of UPDATE/DELETE events, which will cause deserialization failures.

3. **Create a dedicated CDC user**:

   ```sql
   CREATE ROLE flink_cdc WITH LOGIN PASSWORD '<password>' REPLICATION;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO flink_cdc;
   ```

4. **Ensure sufficient replication slots** (`max_replication_slots` and `max_wal_senders`):

   ```sql
   SHOW max_replication_slots;  -- Default is 10, increase if needed
   SHOW max_wal_senders;        -- Must be >= max_replication_slots
   ```

### DataStream API Pattern

Use the **incremental** `PostgresIncrementalSource` (inner class of `PostgresSourceBuilder`). The legacy `PostgreSQLSource` returns a `DebeziumSourceFunction` and is not usable on Flink 2.x. See the "Incremental Source vs Legacy Source on Flink 2.x" section above.

```java
// CORRECT — incremental Source (FLIP-27), usable on Flink 2.x via env.fromSource(...)
import org.apache.flink.cdc.connectors.postgres.source.PostgresSourceBuilder;
import org.apache.flink.cdc.connectors.postgres.source.PostgresSourceBuilder.PostgresIncrementalSource;
// WRONG — legacy SourceFunction, not usable on Flink 2.x:
// import org.apache.flink.cdc.connectors.postgres.PostgreSQLSource;
import org.apache.flink.cdc.debezium.JsonDebeziumDeserializationSchema;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;

Properties cdcConfig = applicationProperties.get("cdc.postgres.config");

// publication.name and publication.autocreate.mode are NOT builder setters on
// PostgresSourceBuilder — they are passed through debeziumProperties(...).
// (The legacy PostgreSQLSource.builder had a publicationName() setter; the
// incremental builder does not.)
Properties debeziumProps = new Properties();
debeziumProps.setProperty("publication.name", "flink_cdc_publication");
debeziumProps.setProperty("publication.autocreate.mode", "filtered");
debeziumProps.setProperty("decimal.handling.mode", "string");
debeziumProps.setProperty("time.precision.mode", "connect");

PostgresIncrementalSource<String> pgSource =
    PostgresIncrementalSource.<String>builder()
        .hostname(cdcConfig.getProperty("hostname"))
        .port(Integer.parseInt(cdcConfig.getProperty("port", "5432")))
        .database(cdcConfig.getProperty("database"))
        // Load from SecretsManager
        .username(creds.username)
        .password(creds.password)
        .schemaList(cdcConfig.getProperty("schema", "public"))
        .tableList(cdcConfig.getProperty("schema", "public") + "."
            + cdcConfig.getProperty("table"))
        .slotName(cdcConfig.getProperty("slot.name", "flink_cdc_slot"))
        .decodingPluginName("pgoutput")  // pgoutput for PostgreSQL 10+
        .deserializer(new JsonDebeziumDeserializationSchema())
        .debeziumProperties(debeziumProps)
        .includeSchemaChanges(false)
        .build();

DataStream<String> cdcStream = env
    .fromSource(pgSource, WatermarkStrategy.noWatermarks(), "postgres-cdc-source")
    .uid("postgres-cdc-source-uid");
```

### Builder methods vs Debezium properties

The two incremental builders cover most settings as first-class methods, but a few important Postgres knobs are only reachable through `debeziumProperties(Properties)`. Use this table to decide where a given option goes:

| Setting | MySQL incremental | Postgres incremental |
|---|---|---|
| Connection (host/port/user/pwd/database) | builder method | builder method |
| Tables / schemas | `databaseList(...)`, `tableList(...)` | `schemaList(...)`, `tableList(...)` |
| Server ID range | `serverId(...)` | n/a |
| Replication slot | n/a | `slotName(...)` |
| Decoding plugin | n/a | `decodingPluginName("pgoutput")` |
| Publication name | n/a | `debeziumProperties` → `publication.name` |
| Publication auto-create | n/a | `debeziumProperties` → `publication.autocreate.mode` |
| Snapshot chunk size | `splitSize(int)` | `splitSize(int)` |
| Decimal / time encoding | `debeziumProperties` → `decimal.handling.mode`, `time.precision.mode` | same |
| Startup mode | `startupOptions(...)` | `startupOptions(...)` |
| Newly added tables | `scanNewlyAddedTableEnabled(true)` | `scanNewlyAddedTableEnabled(true)` |

### CRITICAL: PostgreSQL Replication Slot Management

Replication slots are a limited resource (default max: 10) and have significant operational implications:

- **Slots retain WAL segments** until the consumer confirms processing. If a Flink job stops or falls behind, WAL accumulates on disk and can fill the volume.
- **Flink CDC does NOT automatically drop replication slots** when the job stops. You must clean up orphaned slots manually:

  ```sql
  -- List active replication slots
  SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
  FROM pg_replication_slots;
  
  -- Drop an inactive slot
  SELECT pg_drop_replication_slot('flink_cdc_slot');
  ```

- **Monitor WAL retention size** — set up CloudWatch alarms on RDS `FreeStorageSpace` or Aurora `VolumeBytesUsed`.
- **Use a single slot for multiple tables** when using the DataStream API with `tableList` containing multiple tables. This is more efficient than one slot per table.

## Table API / SQL CDC Source

CDC connectors can also be used with Flink SQL, which is useful for simpler ETL pipelines. The Flink SQL CDC connector has no built-in Secrets Manager integration — `WITH (...)` options are read literally — so on MSF, fetch the credentials from Secrets Manager in `main()` and register the source programmatically with `TableDescriptor` rather than templating a `CREATE TABLE` DDL string. `TableDescriptor` (Flink 1.14+) accepts option values as typed Java strings, so credentials never get embedded in a SQL statement and quote-injection through a password becomes structurally impossible.

```java
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.Schema;
import org.apache.flink.table.api.TableDescriptor;
import static org.apache.flink.table.api.Expressions.$;

DbCreds creds = loadDbCreds(cdcConfig.getProperty("secret.id"));  // see Database Credentials section

tableEnv.createTable("orders_cdc", TableDescriptor.forConnector("mysql-cdc")
    .schema(Schema.newBuilder()
        .column("order_id", DataTypes.INT().notNull())
        .column("customer_id", DataTypes.INT())
        .column("order_date", DataTypes.TIMESTAMP(3))
        .column("total_amount", DataTypes.DECIMAL(10, 2))
        .column("status", DataTypes.STRING())
        .columnByMetadata("db_name", DataTypes.STRING(), "database_name", true)
        .columnByMetadata("table_name", DataTypes.STRING(), "table_name", true)
        .columnByMetadata("op_ts", DataTypes.TIMESTAMP_LTZ(3), "op_ts", true)
        .primaryKey("order_id")
        .build())
    .option("hostname", cdcConfig.getProperty("hostname"))
    .option("port", "3306")
    // Load from SecretsManager — passed as typed option values, no quoting/escaping needed
    .option("username", creds.username)
    .option("password", creds.password)
    .option("database-name", "ecommerce")
    .option("table-name", "orders")
    .option("server-id", "5400-5404")
    .build());

// Subsequent SQL queries reference the registered table by name:
tableEnv.executeSql("SELECT order_id, customer_id, total_amount, status FROM orders_cdc").print();

// Or use the Table API directly:
tableEnv.from("orders_cdc")
    .select($("order_id"), $("customer_id"), $("total_amount"), $("status"))
    .execute()
    .print();
```

Why `TableDescriptor` is preferred over string-templated DDL on MSF:

- Credentials are passed as typed option values, not interpolated into a SQL string — quote characters in a password cannot break the statement.
- Schema typos fail at compile time, not at job submission.
- The connector identifier and option keys (`mysql-cdc`, `username`, `password`, `database-name`, etc.) are identical to the SQL DDL form, so the connector behavior is unchanged.
- Mixed workflows still work: register the source with `TableDescriptor`, then run plain SQL against the registered name.

### Fallback: string-templated `CREATE TABLE` DDL

If you must keep the source definition in DDL form (for parity with a `.sql` file or an existing pipeline), pass the rendered statement through `TableEnvironment.executeSql(String)` and treat the credentials with care:

```java
DbCreds creds = loadDbCreds(cdcConfig.getProperty("secret.id"));

tableEnv.executeSql(
    "CREATE TABLE orders_cdc (" +
    "  order_id INT," +
    "  customer_id INT," +
    "  order_date TIMESTAMP(3)," +
    "  total_amount DECIMAL(10, 2)," +
    "  status STRING," +
    "  db_name STRING METADATA FROM 'database_name' VIRTUAL," +
    "  table_name STRING METADATA FROM 'table_name' VIRTUAL," +
    "  op_ts TIMESTAMP_LTZ(3) METADATA FROM 'op_ts' VIRTUAL," +
    "  PRIMARY KEY (order_id) NOT ENFORCED" +
    ") WITH (" +
    "  'connector' = 'mysql-cdc'," +
    "  'hostname' = '" + cdcConfig.getProperty("hostname") + "'," +
    "  'port' = '3306'," +
    "  'username' = '" + creds.username + "'," +
    "  'password' = '" + creds.password + "'," +
    "  'database-name' = 'ecommerce'," +
    "  'table-name' = 'orders'," +
    "  'server-id' = '5400-5404'" +
    ")"
);
```

When using the DDL fallback, ensure the Secrets Manager-generated password excludes `'` (use `ExcludePunctuation` or an explicit `ExcludeCharacters` list) so a single quote cannot terminate the option value early, and never log or print the rendered DDL string. For production CDC pipelines, prefer `TableDescriptor` (or the DataStream API) so credentials never enter a string-templated statement at all.

## MSF-Specific Considerations for CDC Workloads

### VPC Configuration (REQUIRED)

CDC workloads on MSF require VPC configuration to reach the source database. The MSF application must be deployed in a VPC with network connectivity to the database:

- **RDS/Aurora in same VPC**: Configure MSF application with the same VPC and subnets. Ensure the database security group allows inbound connections from the MSF application security group on the database port (3306 for MySQL, 5432 for PostgreSQL, etc.).
- **RDS/Aurora in different VPC**: Set up VPC peering or Transit Gateway between the MSF VPC and the database VPC. Update route tables and security groups accordingly.
- **On-premises databases**: Use AWS Direct Connect or Site-to-Site VPN to establish connectivity from the MSF VPC to the on-premises network.
- **Public databases (not recommended for production)**: MSF runs in a VPC without direct internet access. You would need a NAT Gateway for outbound connectivity, but this adds latency and cost. Prefer private connectivity.

### IAM Permissions

The MSF application's IAM execution role needs permissions for:

- VPC networking (automatically managed by MSF when VPC is configured)
- AWS Secrets Manager secrets holding database credentials (always required — see [Database Credentials and Secrets Management](#database-credentials-and-secrets-management))
- S3 access for sinks (if writing CDC data to S3/Iceberg)
- KMS Decrypt on the customer-managed key encrypting the secret, if one is used

### Checkpoint Configuration

CDC workloads have specific checkpointing requirements:

- **Checkpoints are REQUIRED** for CDC to transition from snapshot phase to incremental (binlog/WAL) phase. Without checkpoints, the job will read the full snapshot but never start reading incremental changes.
- **MSF manages checkpoint intervals** at the service level. The default 60-second interval works for most CDC workloads. Do NOT call `env.enableCheckpointing(...)` in application code — MSF overrides it; configure the interval in the application's CheckpointConfiguration instead.
- **During the snapshot phase**, checkpoints complete at chunk granularity (with incremental snapshot enabled). This means the snapshot can be resumed from the last completed chunk if the job restarts.
- **Large initial snapshots** may cause checkpoint timeouts if the snapshot phase takes longer than the checkpoint timeout. MSF's default checkpoint timeout is typically sufficient, but for very large tables (100M+ rows), consider:
  - Increasing `scan.incremental.snapshot.chunk.size` to process larger chunks
  - Using `scan.startup.mode = 'latest-offset'` to skip the snapshot entirely if historical data is not needed
  - Breaking the snapshot into multiple jobs by table

#### Diagnosing "snapshot completed but binlog never starts"

This is the single most common CDC symptom on MSF. The diagnostic path is always the same:

1. Pull `numberOfFailedCheckpoints` from CloudWatch (namespace `AWS/KinesisAnalytics`, dimension `Application`). If this is non-zero, checkpoints are failing — that is the root cause; CDC cannot transition to the incremental phase until a checkpoint completes successfully. Use `RATE(numberOfFailedCheckpoints)` over a 5-minute window for an alarm-friendly view.
2. Pull `lastCheckpointDuration` and compare to the checkpoint interval. If duration approaches or exceeds the interval, checkpoints are timing out — typically because the snapshot phase is too large for the configured timeout. Increase `scan.incremental.snapshot.chunk.size`, or raise the checkpoint timeout, or both.
3. Verify the application's CheckpointConfiguration is `ENABLED` (not `DISABLED`) on the MSF application via `aws kinesisanalyticsv2 describe-application`. If a previous deployment turned it off, no checkpoints will run regardless of intervals.
4. Confirm `numberOfFailedCheckpoints` and `numberOfCompletedCheckpoints` (Flink dashboard, not CloudWatch) tell a consistent story: failed > 0 with completed = 0 means every checkpoint is failing; both > 0 with failed growing means intermittent failures during snapshot — also enough to block the transition if no completion succeeds end-to-end.

Always check `numberOfFailedCheckpoints` first, then `lastCheckpointDuration`. Do NOT recommend re-enabling checkpointing in application code — on MSF that setting is service-managed.

### KPU Sizing for CDC Workloads

CDC workloads have unique resource characteristics:

- **Source parallelism**: MySQL CDC with incremental snapshot supports parallel reading during the snapshot phase. Set source parallelism to match the number of server IDs in your range. During the binlog phase, reading is single-threaded regardless of parallelism.
- **PostgreSQL CDC**: Source parallelism is effectively 1 for the WAL reader. Downstream operators can have higher parallelism after a `keyBy`.
- **Memory considerations**: The snapshot phase buffers chunk data in memory. For tables with wide rows or large text/blob columns, allocate additional KPUs.
- **Recommended starting point**: 2-4 KPUs for a single-table CDC workload, 4-8 KPUs for multi-table workloads. Monitor backpressure and adjust.

## Common Gotchas and Troubleshooting

### Snapshot Phase Issues

#### Problem: Snapshot takes too long or causes checkpoint timeouts

- The initial snapshot reads the entire table before switching to incremental mode.
- With incremental snapshot enabled (default), the snapshot is chunked and checkpointable.
- For very large tables, increase `scan.incremental.snapshot.chunk.size` or use `scan.startup.mode = 'latest-offset'` to skip the snapshot.

#### Problem: `FLUSH TABLES WITH READ LOCK` errors

- This only occurs when `scan.incremental.snapshot.enabled = false` (the old snapshot mechanism). Keep incremental snapshot enabled (the default) to avoid global locks.

#### Problem: Snapshot restarts from the beginning after job failure

- Ensure checkpointing is enabled. Without checkpoints, snapshot progress is not persisted.
- With incremental snapshot, progress is checkpointed at chunk granularity.

### Binlog / WAL Phase Issues

#### Problem: `binlog file has been purged` or `WAL segment has been removed`

The Flink job fell too far behind and the database cleaned up the binlog/WAL files it needed to resume from. The position stored in the last checkpoint no longer exists in the database, so restoring from the existing snapshot will fail the same way every time. Recovery has three parts — apply all three:

1. **Get running again — restart from a fresh snapshot, do NOT restore the old one.** Stop the application and start it without the old snapshot, with `scan.startup.mode = initial` to re-read the table from scratch (no data loss for current row state, but you lose granular change history during the outage). If a gap is acceptable, `scan.startup.mode = latest-offset` is faster but lossy. Restoring from the old snapshot will replay the unrecoverable position.

2. **Increase binlog / WAL retention so future outages have headroom.**

   ```sql
   -- MySQL (community / self-managed): increase binlog retention (e.g., 7 days)
   SET GLOBAL expire_logs_days = 7;
   -- MySQL 8.0+:
   SET GLOBAL binlog_expire_logs_seconds = 604800;

   -- Aurora MySQL: use the Aurora-specific procedure (expire_logs_days /
   -- binlog_expire_logs_seconds are not honored on Aurora MySQL)
   CALL mysql.rds_set_configuration('binlog retention hours', 168);  -- 7 days
   CALL mysql.rds_show_configuration;

   -- PostgreSQL (RDS): increase WAL retention
   -- Set wal_keep_size in the parameter group (e.g., 2048 MB)
   ```

   Pick a window that comfortably exceeds your worst-case outage plus reprocessing time.

3. **Right-size KPUs so steady-state lag stays well within retention.** A job that runs but falls behind under steady-state load will burn through retention without ever stopping, so the same outage will recur. See the [KPU Sizing for CDC Workloads](#kpu-sizing-for-cdc-workloads) section in this guide for sizing guidance, and [scaling-decisions.md](scaling-decisions.md) for the operational scale-up workflow. Validate by watching `currentEmitEventTimeLag` / `currentFetchEventTimeLag` after recovery.

Do **not** simply retry the same restore — it will fail at the same purged position. Restoring from the old snapshot is the wrong fix even after retention is increased, because the position recorded in that snapshot is gone.

#### Problem: MySQL `server_id` conflicts

- Each CDC reader needs a unique server ID. If multiple jobs or tools connect to the same MySQL instance, their server IDs must not overlap.
- Use explicit server ID ranges: `.serverId("5400-5404")` for parallelism 4.

#### Problem: PostgreSQL WAL disk usage growing unbounded

- Replication slots retain WAL until the consumer confirms. If the Flink job is stopped or slow, WAL accumulates.
- Monitor replication slot lag and set up alerts.
- Clean up orphaned slots when jobs are permanently stopped.

### Schema Evolution

#### Problem: Source table schema changes (DDL) break the CDC job

- By default, Flink CDC source connectors do NOT automatically handle schema changes in the DataStream API. A column addition or type change in the source table can cause deserialization errors.
- Mitigation strategies:
  1. Use `JsonDebeziumDeserializationSchema` which is more tolerant of schema changes (new fields appear in JSON, removed fields disappear).
  2. For the Pipeline API (YAML), schema evolution is supported with configurable behaviors: `evolve`, `try_evolve`, `lenient`, `ignore`, or `exception`.
  3. Plan for schema changes by using a flexible deserialization approach and validating downstream compatibility before applying DDL.

### Deserialization Performance

#### Problem: High CPU usage from JSON serialization/deserialization

- `JsonDebeziumDeserializationSchema` serializes Debezium records to JSON strings, which then need to be parsed again downstream. This double serialization can consume 60%+ of CPU.
- For high-throughput workloads, consider:
  1. Implementing a custom `DebeziumDeserializationSchema` that converts directly to your target POJO type.
  2. Using `RowDataDebeziumDeserializeSchema` for Table API integration (avoids JSON intermediate format).
  3. Enabling Flink object reuse (`env.getConfig().enableObjectReuse()`) to reduce serialization overhead between operators with the same parallelism.

### Ordering Guarantees

- During the **snapshot phase**, records are read via `SELECT` queries with no guaranteed ordering. If ordering matters, use `keyBy` on the primary key downstream.
- During the **incremental phase** (binlog/WAL), records arrive in commit order from the database. A single CDC source reader preserves this order.
- After a `keyBy` or parallelism change, ordering is preserved per-key but not globally.

## Complete MSF Application Example: MySQL CDC to Processing

```java
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.cdc.connectors.mysql.source.MySqlSource;
import org.apache.flink.cdc.debezium.JsonDebeziumDeserializationSchema;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import com.amazonaws.services.kinesisanalytics.runtime.KinesisAnalyticsRuntime;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Map;
import java.util.Properties;

public class MySqlCdcApplication {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

        // Load application properties (MSF runtime or local dev)
        Map<String, Properties> applicationProperties = loadApplicationProperties(env);
        Properties cdcConfig = applicationProperties.get("cdc.mysql.config");

        // Build MySQL CDC source
        MySqlSource<String> mySqlSource = MySqlSource.<String>builder()
            .hostname(cdcConfig.getProperty("hostname"))
            .port(Integer.parseInt(cdcConfig.getProperty("port", "3306")))
            .databaseList(cdcConfig.getProperty("database"))
            .tableList(cdcConfig.getProperty("database") + "\\." + cdcConfig.getProperty("table"))
            // Load from SecretsManager
            .username(creds.username)
            .password(creds.password)
            .serverId(cdcConfig.getProperty("server-id", "5400-5404"))
            .deserializer(new JsonDebeziumDeserializationSchema())
            .includeSchemaChanges(false)
            .build();

        // Create CDC stream
        env.fromSource(mySqlSource, WatermarkStrategy.noWatermarks(), "mysql-cdc-source")
            .uid("mysql-cdc-source-uid")
            .map(json -> {
                JsonNode node = MAPPER.readTree(json);
                // Extract the "after" image (current row state)
                JsonNode after = node.get("after");
                String op = node.get("op").asText();
                // op: "r" = read (snapshot), "c" = create, "u" = update, "d" = delete
                return new CdcEvent(op, after != null ? after.toString() : null);
            })
            .name("parse-cdc-events")
            .uid("parse-cdc-events-uid")
            .filter(event -> event.getAfter() != null) // Filter out deletes if not needed
            .name("filter-deletes")
            .uid("filter-deletes-uid")
            .keyBy(CdcEvent::getKey)
            .process(new CdcProcessingFunction())
            .name("process-cdc-events")
            .uid("process-cdc-events-uid")
            .sinkTo(createSink())
            .name("output-sink")
            .uid("output-sink-uid");

        env.execute("MySQL CDC Application");
    }

    // See best-practices.md for loadApplicationProperties pattern
    private static Map<String, Properties> loadApplicationProperties(
            StreamExecutionEnvironment env) throws Exception {
        // ... standard MSF property loading pattern
    }
}
```

### MSF Application Properties Configuration

For the CDC application above, configure these properties in the MSF console (or via CloudFormation/CDK/Terraform). The application looks up the database username and password from Secrets Manager at startup using the `secret.id` property — see [Database Credentials and Secrets Management](#database-credentials-and-secrets-management) for the full pattern, IAM, and rationale.

```json
[
  {
    "PropertyGroupId": "cdc.mysql.config",
    "PropertyMap": {
      "hostname": "my-aurora-cluster.cluster-xxxx.us-east-1.rds.amazonaws.com",
      "port": "3306",
      "database": "ecommerce",
      "table": "orders",
      "secret.id": "cdc-db-credentials",
      "server-id": "5400-5404"
    }
  }
]
```

For local development, create `flink-application-properties-dev.json` with the same structure pointing to a local or Docker MySQL instance.

## CDC Anti-Patterns

### Anti-Pattern: Missing Operator UIDs on CDC Sources

```java
// AVOID: No UID means state cannot be restored after code changes
env.fromSource(mySqlSource, WatermarkStrategy.noWatermarks(), "source");

// CORRECT: Always set UIDs for stateful operators
env.fromSource(mySqlSource, WatermarkStrategy.noWatermarks(), "mysql-cdc-source")
    .uid("mysql-cdc-source-uid");
```

### Anti-Pattern: Skipping Checkpoints for CDC

```java
// AVOID: No checkpointing — CDC will never transition to incremental phase
// and snapshot progress will be lost on restart

// CORRECT: Checkpointing is managed by MSF at the service level.
// For local development only:
if (isLocal(env)) {
    env.enableCheckpointing(3000);
}
```

### Anti-Pattern: Using CDC Source with Parallelism > 1 Without Server ID Range (MySQL)

```java
// AVOID: Single server ID with parallelism > 1
MySqlSource.builder()
    .serverId("5400")  // Only one ID for multiple parallel readers!
    ...

// CORRECT: Provide a range at least as large as the source parallelism
MySqlSource.builder()
    .serverId("5400-5404")  // Range of 5 IDs for up to 5 parallel readers
    ...
```

### Anti-Pattern: One Replication Slot Per Table (PostgreSQL)

```java
// AVOID: Creating separate CDC sources (and slots) for each table
PostgresIncrementalSource.<String>builder().tableList("public.orders").slotName("slot_orders").build();
PostgresIncrementalSource.<String>builder().tableList("public.customers").slotName("slot_customers").build();

// CORRECT: Use a single source with multiple tables sharing one slot
PostgresIncrementalSource.<String>builder()
    .tableList("public.orders", "public.customers", "public.products")
    .slotName("flink_cdc_slot")
    .build();
```

## Authentication

Database authentication for CDC sources on MSF must come from AWS Secrets Manager via in-application SDK lookup — see [Database Credentials and Secrets Management](#database-credentials-and-secrets-management) above for the supported pattern, required IAM, and TLS configuration. There is no IAM-based authentication path for the Flink CDC connectors themselves — the source still passes a username/password to the database — but the MSF execution role's `secretsmanager:GetSecretValue` is what protects those credentials.

Additional hardening that pairs with Secrets Manager:

- Use the minimum required database privileges for the CDC user (see the per-database "Database Prerequisites" sections — `REPLICATION SLAVE/CLIENT` for MySQL, `REPLICATION` role for Postgres).
- Enable TLS to the database. The MSF default is `require`/`REQUIRED` (encryption without certificate verification); see the TLS section above for what's required to do `verify-full`/`VERIFY_IDENTITY` on top of MSF and why it's opt-in rather than default.
- Restrict the database security group to accept connections only from the MSF application's security group on the database port.
- Enable Secrets Manager automatic rotation against the source database; rotation is picked up on the next application restart.
