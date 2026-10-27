# Iceberg Tuning and Operations on Managed Service for Apache Flink

## Overview

This guide covers production tuning and operational concerns for Apache Iceberg tables written by Flink applications on Amazon Managed Service for Apache Flink (MSF): the small files problem, table maintenance (compaction, snapshot expiration, orphan file cleanup), catalog choice between AWS Glue and S3 Tables, monitoring, dependency management, and common anti-patterns.

For Iceberg write APIs, read patterns, partitioning, and DDL, see [iceberg-connector-guide.md](iceberg-connector-guide.md).

## The Small Files Problem

This is the #1 production issue with streaming Iceberg workloads. Understanding the math is critical.

### Three Root Causes of Small Files

**1. High commit rate (checkpoint interval):** Iceberg commits happen at Flink checkpoint boundaries. Files are closed at checkpoint boundaries regardless of whether they've reached the target size. The checkpoint interval is the single biggest lever for controlling file count.

```
Files per commit (worst case) = writer_parallelism × active_partitions
Files per day = (86400 / checkpoint_interval_seconds) × files_per_commit
```

Example with 60-second checkpoints, 4 writer tasks, 10 active partitions:

- 1,440 checkpoints/day × 4 × 10 = 57,600 files/day
- After 7 days: 403,200 files, each potentially only 1-10 MB

With a 10-second checkpoint interval, that becomes 345,600 files/day.

**2. MoR delete files from upserts:** Each upsert within a checkpoint generates both a data file (the new row) and an equality delete file (marking the old row for deletion). Upsert workloads create roughly 2× the files of append-only workloads. These delete files are typically tiny (just the equality field values) but accumulate and must be merged at read time.

**3. No shuffle before writing (distribution mode NONE):** Without distribution, each writer task creates one file per partition it touches per checkpoint. If data arrives in random order across all partitions, every writer touches every partition. With N writer tasks and M active partitions, you get up to N × M files per commit. HASH distribution routes each partition's data to a single writer, reducing to M files per commit — but is limited by partition cardinality (if you have 5 partitions, only 5 of 20 writer tasks get data). RANGE distribution addresses this by using traffic statistics to balance load across writers regardless of cardinality.

### Impact

- **Query planning:** Must read metadata for every file. 100,000 files can take 30-60 seconds just to plan a query.
- **Query execution:** Each file requires a separate S3 GET request. More files = more requests = higher latency and cost.
- **Metadata bloat:** Each commit generates manifest files. Thousands of commits create thousands of manifests tracking overlapping file sets.

### Mitigation Strategies

Apply these together — none is sufficient on its own for production streaming workloads.

1. **Increase checkpoint interval:** The single most effective lever. A 60-second interval creates 24x fewer files than a 2.5-second interval. On MSF, configure this at the application level (not in code):

   ```typescript
   // CDK
   checkpointConfiguration: {
       configurationType: 'CUSTOM',
       checkpointingEnabled: true,
       checkpointInterval: 60000,       // 60 seconds
       minPauseBetweenCheckpoints: 30000, // 30 seconds
   }
   ```

2. **Use table maintenance (compaction):** Merge small files into larger ones. See the Table Maintenance section below. This is required for production streaming Iceberg, not optional.

3. **Target file size:** Set `write.target-file-size-bytes` to 128-256 MB. The writer will try to reach this size before closing a file, but checkpoint boundaries force file closure regardless.

4. **Use RANGE or HASH distribution to reduce per-writer file creation:** RANGE distribution is recommended for skewed data; HASH distribution is required for upsert correctness on partitioned tables. Without a distribution mode, every writer can write to every partition, multiplying file count by writer parallelism. See the Distribution Modes section in [iceberg-connector-guide.md](iceberg-connector-guide.md) for details.

5. **Monitor actively:** Query the `$files` metadata table to track file sizes and counts. Alert when average file size drops below 32 MB or file count per partition exceeds 100.

### Snapshot Retention for Streaming

Default retention policies are designed for batch workloads. For streaming:

- Use **count-based retention** (e.g., retain last 100-1000 snapshots) rather than time-based (e.g., 7 days)
- A streaming job creating snapshots every 60 seconds generates 10,080 snapshots per week
- Keep active storage ratio above 85% (current data / total stored data)
- Compacted files leave behind orphaned old files — aggressive snapshot expiration is needed to clean them up
- **Long retention defeats the purpose of compaction.** Old data files cannot be physically removed (via `DeleteOrphanFiles`) while *any* retained snapshot still references them. A 7-day retention on a 60-second checkpoint job pins the post-compaction "old" files in S3 for the full 7 days, so storage footprint stays inflated even after compaction runs and you keep paying for the same bytes twice. Count-based retention solves this directly — once the retained snapshots roll past, compaction can actually reclaim space.

## Table Maintenance

### Overview

Iceberg tables require ongoing maintenance for production health. The three core operations, in correct execution order:

1. **Compact data files** (RewriteDataFiles) — Merge small files into larger ones
2. **Expire snapshots** (ExpireSnapshots) — Remove old table versions, orphaning old files
3. **Delete orphan files** (DeleteOrphanFiles) — Clean up files no longer referenced by any snapshot

**Running these out of order can cause data loss or corruption.** For example, expiring snapshots before compaction can orphan files that are still needed.

After all three, optionally:
4. **Rewrite manifests** — Consolidate metadata structure (not available in Flink streaming maintenance API, use Spark or batch Flink)

### Three Distinct Maintenance Approaches on AWS

There are exactly three ways to run maintenance for Iceberg tables written by Flink on AWS. The first decision is your catalog (S3 Tables vs Glue), and if you pick Glue, the second decision is which maintenance mechanism to use:

| Approach | Catalog | Compaction | Snapshot expiration | Orphan cleanup | Operational overhead | Control |
|---|---|---|---|---|---|---|
| **1. S3 Tables (fully managed)** | S3 Tables | Automatic | Automatic | Automatic | None | Low — service overrides some table properties |
| **2. Glue + Glue auto-compaction** | Glue | Managed by Glue | You handle (Flink or external) | You handle (Flink or external) | Medium — only snapshot/orphan cleanup to run | Medium — Glue manages compaction thresholds |
| **3. Glue + Flink embedded maintenance** | Glue | Flink job topology | Flink job topology | Flink job topology | High — RDS for JDBC locks, VPC config | Full — every parameter is yours to tune |

**Key constraints (do not violate):**

- S3 Tables: do NOT add Flink embedded maintenance or external compaction. Concurrent maintenance causes commit conflicts.
- Glue: do NOT combine Glue auto-compaction with Flink embedded compaction on the same table. Pick one compaction mechanism. (You can still pair Glue auto-compaction with Flink embedded snapshot expiration and orphan cleanup — those are not redundant.)

**Quick picker:**

- Want zero maintenance work and accept S3 Tables' constraints? → S3 Tables
- Want Glue catalog (broader query engine support, full table-property control) but don't want to operate compaction yourself? → Glue + Glue auto-compaction
- Need to control compaction strategy, scheduling, and partial-progress behavior precisely? → Glue + Flink embedded maintenance

These approaches are detailed in the next section, followed by the Flink TableMaintenance API used by Glue + Flink embedded maintenance (and for the snapshot/orphan portions of Glue + Glue auto-compaction).

### The Three Alternatives in Detail

Each of the three approaches introduced above is described below with its specific behaviors and pitfalls.

**S3 Tables (fully managed):**

- Compaction is automatic and enabled by default. Target file size: 512 MB (configurable 64-512 MB). Strategies: auto (default), binpack, sort, z-order.
- Compaction applies delete file effects — merges equality/position deletes into data files automatically.
- Snapshot management is automatic: defaults to min 1 snapshot, max 120 hours age. Configurable via `PutTableMaintenanceConfiguration` API.
- Unreferenced file removal is automatic.
- Do NOT run Flink embedded maintenance or external compaction alongside S3 Tables — it will cause commit conflicts with the service's own maintenance.
- Limitation: S3 Tables overrides some table properties. S3 Tables snapshot management does NOT respect Iceberg table properties set via `ALTER TABLE SET TBLPROPERTIES` (e.g., branch/tag retention). If you set such properties, S3 Tables disables its own snapshot management and you must handle it yourself.
- Transient commit conflicts between S3 Tables compaction and your streaming writer are normal — S3 Tables handles retry internally, but you may see transient errors in Flink logs.

**Glue Catalog with Glue Auto-Compaction (managed compaction, manual snapshot/orphan cleanup):**

- AWS Glue Data Catalog supports automatic compaction for Iceberg tables. It monitors partitions and triggers compaction when thresholds are met (e.g., >100 files smaller than 75% of target size).
- Supports both CoW and MoR tables, including compacting delete files.
- Commits partial progress regularly.
- You still need to handle snapshot expiration and orphan file cleanup yourself — use Flink's TableMaintenance API for those, or schedule external jobs.
- Concurrent write conflicts between Glue compaction and your streaming writer are possible. Glue handles retries, but your Flink job should tolerate transient commit failures.

**Glue Catalog with Flink Embedded Maintenance (full control):**

- Full control over all three operations: compaction, snapshot expiration, orphan cleanup.
- Runs inside the Flink job topology, coordinated by distributed locks (JDBC/ZK). No external compaction conflicts.
- Requires infrastructure: RDS PostgreSQL instance for JDBC locks, VPC configuration for the Flink app.
- Most flexible but most operational overhead.
- Do NOT combine with Glue auto-compaction — pick one compaction approach to avoid conflicts.

**Decision guide (recap):**

- Want zero maintenance overhead? → S3 Tables (Approach 1)
- Want managed compaction but keep Glue catalog flexibility? → Glue auto-compaction + Flink for snapshot/orphan cleanup (Approach 2)
- Need full control over maintenance scheduling and parameters? → Flink embedded maintenance with JDBC locks on Glue Catalog (Approach 3)

### Flink Streaming Maintenance (TableMaintenance API)

The TableMaintenance API (Iceberg 1.10+) runs maintenance as part of the Flink job topology, triggered by post-commit events. Requires IcebergSink (SinkV2).

Store the JDBC lock-database credentials in AWS Secrets Manager and look them up at job startup. **Never hardcode credentials in application code, runtime properties, or `setup.sql`/JAR resources.** Connect to the lock database over TLS — the JDBC URL must include `ssl=true` so the connection is encrypted in transit. Certificate verification (`sslmode=verify-full`) on MSF requires a custom `SSLSocketFactory` that loads the CA bundle from the classpath, since MSF doesn't expose a stable filesystem path for `sslrootcert`; see [cdc-connector-guide.md](cdc-connector-guide.md#tls--ssl-to-the-database) for the constraints. See [cdc-connector-guide.md](cdc-connector-guide.md#database-credentials-and-secrets-management) for the full Secrets Manager pattern; the Iceberg lock-DB credentials should follow the same approach.

```java
// Resolve credentials from AWS Secrets Manager — see cdc-connector-guide.md for the
// full SecretsManagerClient pattern and IAM grant.
DbCreds lockDbCreds = loadDbCreds(cdcConfig.getProperty("iceberg.lock.secret.id"));

Map<String, String> jdbcProps = new HashMap<>();
jdbcProps.put("jdbc.user", lockDbCreds.username);
jdbcProps.put("jdbc.password", lockDbCreds.password);
jdbcProps.put("flink-maintenance.lock.jdbc.init-lock-tables", "true");

TriggerLockFactory lockFactory = new JdbcLockFactory(
    "jdbc:postgresql://rds-endpoint:5432/iceberg_locks?ssl=true",
    "catalog.database.table",  // Unique lock ID per table
    jdbcProps
);

TableMaintenance.forTable(env, tableLoader, lockFactory)
    .uidSuffix("my-maintenance")
    .rateLimit(Duration.ofMinutes(10))        // Min interval between executions
    .lockCheckDelay(Duration.ofSeconds(30))   // Delay before checking lock availability
    .add(ExpireSnapshots.builder()
        .scheduleOnCommitCount(10)            // Trigger after every 10 commits
        .maxSnapshotAge(Duration.ofHours(24))
        .retainLast(5)
        .deleteBatchSize(1000))
    .add(RewriteDataFiles.builder()
        .scheduleOnDataFileCount(20)          // Trigger when 20+ small files exist
        .targetFileSizeBytes(256 * 1024 * 1024)  // 256 MB target
        .minFileSizeBytes(32 * 1024 * 1024)      // Files below 32 MB are candidates
        .partialProgressEnabled(true)             // Commit progress incrementally
        .partialProgressMaxCommits(5)
        .maxRewriteBytes(2L * 1024 * 1024 * 1024))  // Cap at 2 GB per run
    .add(DeleteOrphanFiles.builder()
        .scheduleOnCommitCount(50)            // Less frequent than compaction
        .minAge(Duration.ofDays(3)))          // Only delete files older than 3 days
    .append();
```

### Post-Commit Maintenance via IcebergSink Configuration

Alternative to the explicit TableMaintenance API — configure maintenance directly on the sink:

```java
Map<String, String> flinkConf = new HashMap<>();
flinkConf.put(FlinkWriteOptions.COMPACTION_ENABLE.key(), "true");
flinkConf.put(LockConfig.LOCK_TYPE_OPTION.key(), LockConfig.JdbcLockConfig.JDBC);
flinkConf.put(LockConfig.JdbcLockConfig.JDBC_URI_OPTION.key(),
    "jdbc:postgresql://host:5432/iceberg?ssl=true");
flinkConf.put(LockConfig.LOCK_ID_OPTION.key(), "catalog.db.table");
// Lock-DB user/password must be supplied via Secrets Manager — do not hardcode.
// e.g.: flinkConf.put(LockConfig.JdbcLockConfig.JDBC_USER_OPTION.key(), lockDbCreds.username);

IcebergSink.forRowData(dataStream)
    .tableLoader(tableLoader)
    .setAll(flinkConf)
    .append();
```

Or via SQL:

```sql
SET 'table.exec.iceberg.use-v2-sink' = 'true';
SET 'compaction-enabled' = 'true';
SET 'flink-maintenance.lock.type' = 'jdbc';
SET 'flink-maintenance.lock.lock-id' = 'catalog.db.table';
SET 'flink-maintenance.lock.jdbc.uri' = 'jdbc:postgresql://host:5432/iceberg?ssl=true';
SET 'flink-maintenance.lock.jdbc.init-lock-tables' = 'true';
-- jdbc.user / jdbc.password must come from a Secrets Manager lookup performed
-- in main() and templated into the SET statement before submission. Do NOT
-- store them in MSF runtime properties (even via {{resolve:secretsmanager:...}}
-- dynamic references) — they would land as plaintext on the deployed property
-- surface. See cdc-connector-guide.md → Database Credentials and Secrets Management.

INSERT INTO my_table SELECT ...;
```

### Lock Factory Options

Maintenance requires distributed locks to prevent concurrent operations on the same table:

| Lock Type | When to Use | Infrastructure Required |
|---|---|---|
| JDBC (PostgreSQL) | Most MSF deployments | RDS PostgreSQL instance, VPC for Flink app |
| ZooKeeper | If ZK is already available | ZooKeeper cluster |

JDBC lock factory with auto-table creation:

```java
// Resolve lock-DB credentials from Secrets Manager — do not hardcode (see
// cdc-connector-guide.md → Database Credentials and Secrets Management).
DbCreds lockDbCreds = loadDbCreds(cdcConfig.getProperty("iceberg.lock.secret.id"));

Map<String, String> jdbcProps = new HashMap<>();
jdbcProps.put("jdbc.user", lockDbCreds.username);
jdbcProps.put("jdbc.password", lockDbCreds.password);
jdbcProps.put("flink-maintenance.lock.jdbc.init-lock-tables", "true");

// jdbcUrl should enforce TLS: jdbc:postgresql://host:5432/db?ssl=true
// (sslmode=verify-full requires a custom SSLSocketFactory on MSF — see
// cdc-connector-guide.md → TLS / SSL to the database)
TriggerLockFactory lockFactory = new JdbcLockFactory(jdbcUrl, lockId, jdbcProps);
lockFactory.open();  // Initialize lock tables
```

### Scheduling Triggers

Choose triggers based on your workload:

| Trigger | Method | Best For |
|---|---|---|
| Commit count | `scheduleOnCommitCount(N)` | Write-heavy tables with frequent commits |
| Data file count | `scheduleOnDataFileCount(N)` | Fine-grained control over small file accumulation |
| Data file size | `scheduleOnDataFileSize(bytes)` | Size-based thresholds |
| Delete file count | `scheduleOnEqDeleteFileCount(N)` | Upsert tables with equality delete accumulation |
| Time interval | `scheduleOnInterval(Duration)` | Regular cadence regardless of write activity |

### Maintenance Troubleshooting

- **OutOfMemoryError during file deletion:** Reduce `deleteBatchSize` (e.g., from 1000 to 500)
- **Lock conflicts between jobs:** Increase `lockCheckDelay` and `rateLimit`
- **Compaction can't keep up:** Enable `partialProgressEnabled`, set `maxRewriteBytes` to cap work per run, increase compaction parallelism
- **Orphan file cleanup safety:** The Flink streaming writer stores uncommitted data as temporary files. Set `minAge` to at least 3 days to avoid deleting files from in-progress checkpoints. Also keep the last snapshot created by the Flink job (identifiable by `flink.job-id` in snapshot summary).

## Catalog Configuration on AWS

### AWS Glue Catalog (DataStream API)

```java
Map<String, String> catalogProps = new HashMap<>();
catalogProps.put("catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog");
catalogProps.put("io-impl", "org.apache.iceberg.aws.s3.S3FileIO");
catalogProps.put("warehouse", "s3://my-bucket/warehouse");
catalogProps.put("client.region", "us-east-1");
catalogProps.put("glue.region", "us-east-1");

CatalogLoader catalogLoader = CatalogLoader.custom(
    "glue_catalog", catalogProps, new Configuration(),
    "org.apache.iceberg.aws.glue.GlueCatalog"
);
```

### AWS Glue Catalog (SQL)

```sql
CREATE CATALOG glue_catalog WITH (
    'type' = 'iceberg',
    'catalog-impl' = 'org.apache.iceberg.aws.glue.GlueCatalog',
    'io-impl' = 'org.apache.iceberg.aws.s3.S3FileIO',
    'warehouse' = 's3://my-bucket/warehouse',
    'glue.skip-archive' = 'true',
    'glue.skip-name-validation' = 'true'
);
```

### S3 Tables Catalog (DataStream API)

```java
Map<String, String> catalogProps = new HashMap<>();
catalogProps.put("catalog-impl", "software.amazon.s3tables.iceberg.S3TablesCatalog");
catalogProps.put("warehouse", s3TableBucketArn);  // ARN, not S3 path
catalogProps.put("client.region", "us-east-1");
catalogProps.put("s3tables.catalog.client.region", "us-east-1");

CatalogLoader catalogLoader = CatalogLoader.custom(
    "s3tables_catalog", catalogProps, new Configuration(),
    "software.amazon.s3tables.iceberg.S3TablesCatalog"
);
```

### S3 Tables Catalog (SQL)

```sql
CREATE CATALOG s3tables_catalog WITH (
    'type' = 'iceberg',
    'catalog-impl' = 'software.amazon.s3tables.iceberg.S3TablesCatalog',
    'warehouse' = 'arn:aws:s3tables:us-east-1:123456789012:bucket/my-table-bucket',
    'client.region' = 'us-east-1'
);
```

### Glue vs S3 Tables Decision Guide

| Aspect | Glue Catalog | S3 Tables |
|---|---|---|
| Compaction | Manual (Flink embedded or Glue auto-compaction) | Automatic (binpack, sort, z-order strategies; target 64-512 MB) |
| Snapshot expiration | Manual (Flink embedded or external jobs) | Automatic (default: min 1 snapshot, max 120h age; configurable) |
| Orphan file cleanup | Manual | Automatic |
| Delete file compaction | Glue auto-compaction handles MoR delete files; or Flink embedded | Automatic (applies delete effects during compaction) |
| Query engine support | Broad (Athena, Spark, Trino, Redshift, EMR) | Growing support |
| Storage | Standard S3 bucket (you manage lifecycle, encryption) | S3 Table Bucket (managed) |
| Cost | S3 storage + Glue API calls + compute for maintenance | S3 Tables pricing (includes maintenance compute) |
| Control | Full control over table properties, maintenance scheduling, retention | Less control; S3 Tables overrides some Iceberg table properties |
| Branch/tag retention | Fully supported via Iceberg table properties | Setting branch/tag retention disables S3 Tables snapshot management |

**Rule:** Do NOT enable Flink embedded maintenance or external compaction when using S3 Tables — it handles this automatically and concurrent maintenance causes commit conflicts.

### Flink Connector-Style Catalog (SQL)

For simple use cases, create Iceberg tables directly without a named catalog:

```sql
CREATE TABLE my_table (
    id BIGINT,
    data STRING
) WITH (
    'connector' = 'iceberg',
    'catalog-name' = 'glue_prod',
    'catalog-impl' = 'org.apache.iceberg.aws.glue.GlueCatalog',
    'warehouse' = 's3://my-bucket/warehouse'
);
```

This creates a Flink table in the default Flink catalog that maps to the underlying Iceberg table. The Iceberg catalog is configured inline via table properties.

## Monitoring Iceberg Workloads

### Key Sink Metrics

IcebergSink exposes Flink metrics under `IcebergStreamWriter` and `IcebergFilesCommitter` sub-groups:

| Metric | Type | What to Monitor |
|---|---|---|
| `elapsedSecondsSinceLastSuccessfulCommit` | Gauge | **Primary alerting metric.** If checkpoint interval is 60s, alert when this exceeds 600s (10 minutes). Detects failed or missing Iceberg commits. |
| `lastFlushDurationMs` | Gauge | Time to flush and upload files during checkpoint. Increasing values indicate growing file counts or S3 latency. |
| `lastCommitDurationMs` | Gauge | Time for the Iceberg table commit. Increasing values indicate metadata bloat. |
| `committedDataFilesCount` | Counter | Track rate of file creation. High rates indicate small file accumulation. |
| `committedDeleteFilesCount` | Counter | Track delete file accumulation in upsert workloads. |
| `dataFilesSizeHistogram` | Histogram | Distribution of data file sizes. Median should be near target file size. |

### Metadata Table Monitoring Queries

Run these periodically (e.g., via Athena) to assess table health:

```sql
-- Small files detection: count files below 32 MB
SELECT COUNT(*) as small_file_count,
       AVG(file_size_in_bytes) as avg_size,
       MIN(file_size_in_bytes) as min_size
FROM db.my_table$files
WHERE file_size_in_bytes < 33554432;

-- Delete file accumulation per partition
SELECT partition,
       equality_delete_file_count,
       equality_delete_record_count,
       file_count
FROM db.my_table$partitions
WHERE equality_delete_file_count > 10;

-- Snapshot velocity (how fast are we creating snapshots)
SELECT COUNT(*) as snapshot_count
FROM db.my_table$snapshots
WHERE committed_at > CURRENT_TIMESTAMP - INTERVAL '1' HOUR;
```

## Dependency Management for Iceberg on MSF

### Maven Dependencies (Flink 1.20)

```xml
<properties>
    <flink.version>1.20.3</flink.version>
    <iceberg.version>1.10.0</iceberg.version>
    <aws.sdk.version>2.33.0</aws.sdk.version>
    <hadoop.version>3.4.0</hadoop.version>
</properties>

<dependencies>
    <!-- Iceberg Flink Runtime (shaded bundle) -->
    <dependency>
        <groupId>org.apache.iceberg</groupId>
        <artifactId>iceberg-flink-runtime-1.20</artifactId>
        <version>${iceberg.version}</version>
    </dependency>

    <!-- Iceberg AWS Bundle (Glue Catalog, S3FileIO) -->
    <dependency>
        <groupId>org.apache.iceberg</groupId>
        <artifactId>iceberg-aws-bundle</artifactId>
        <version>${iceberg.version}</version>
    </dependency>

    <!-- S3 Tables Catalog (only if using S3 Tables) -->
    <dependency>
        <groupId>software.amazon.s3tables</groupId>
        <artifactId>s3-tables-catalog-for-iceberg</artifactId>
        <version>0.1.8</version>
    </dependency>

    <!-- Hadoop Common — required by Iceberg's CatalogLoader API
         (org.apache.hadoop.conf.Configuration is referenced by
         CatalogLoader.custom(name, props, new Configuration(), implClass)
         at compile and run time). Neither iceberg-flink-runtime-* nor
         iceberg-aws-bundle brings it transitively (they are shaded uber-jars),
         and MSF does not ship hadoop-common on the application classpath.
         Compile scope so it ends up in the shaded JAR under the
         shaded.org.apache.hadoop.conf relocation.

         Exclusions: hadoop-common transitively pulls slf4j-reload4j, reload4j,
         and log4j 1.x. These conflict with log4j-slf4j-impl (Log4j 2.x) that
         the MSF runtime expects; without these exclusions you get duplicate
         SLF4J bindings and classloading failures at startup. -->
    <dependency>
        <groupId>org.apache.hadoop</groupId>
        <artifactId>hadoop-common</artifactId>
        <version>${hadoop.version}</version>
        <exclusions>
            <exclusion>
                <groupId>org.slf4j</groupId>
                <artifactId>slf4j-reload4j</artifactId>
            </exclusion>
            <exclusion>
                <groupId>ch.qos.reload4j</groupId>
                <artifactId>reload4j</artifactId>
            </exclusion>
            <exclusion>
                <groupId>log4j</groupId>
                <artifactId>log4j</artifactId>
            </exclusion>
        </exclusions>
    </dependency>

    <!-- Kinesis Connector -->
    <dependency>
        <groupId>org.apache.flink</groupId>
        <artifactId>flink-connector-aws-kinesis-streams</artifactId>
        <version>5.0.0-1.20</version>
    </dependency>

    <!-- Flink Table API (required for SQL path) -->
    <dependency>
        <groupId>org.apache.flink</groupId>
        <artifactId>flink-table-api-java-bridge</artifactId>
        <version>${flink.version}</version>
        <scope>provided</scope>
    </dependency>

    <!-- MSF Runtime -->
    <dependency>
        <groupId>com.amazonaws</groupId>
        <artifactId>aws-kinesisanalytics-runtime</artifactId>
        <version>1.2.0</version>
        <scope>provided</scope>
    </dependency>
</dependencies>
```

### Critical Shade Plugin Configuration

MSF bundles its own Hadoop and AWS SDK classes. You MUST relocate conflicting classes to avoid classpath conflicts:

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-shade-plugin</artifactId>
    <configuration>
        <relocations>
            <!-- Relocate Hadoop conf to avoid conflict with flink-s3-fs-hadoop -->
            <relocation>
                <pattern>org.apache.hadoop.conf</pattern>
                <shadedPattern>shaded.org.apache.hadoop.conf</shadedPattern>
            </relocation>
            <!-- Relocate AWS SDK v2 to avoid conflict with MSF's bundled SDK -->
            <relocation>
                <pattern>software.amazon.awssdk</pattern>
                <shadedPattern>shaded.software.amazon.awssdk</shadedPattern>
            </relocation>
        </relocations>
        <transformers>
            <!-- CRITICAL: Required for SPI service discovery (Iceberg FileIO, Catalog) -->
            <transformer implementation="org.apache.maven.plugins.shade.resource.ServicesResourceTransformer"/>
            <transformer implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer">
                <mainClass>com.example.MyFlinkJob</mainClass>
            </transformer>
        </transformers>
    </configuration>
</plugin>
```

**The `ServicesResourceTransformer` is essential.** Without it, Iceberg's SPI-based service discovery (for FileIO implementations, catalog implementations) will fail at runtime with ClassNotFoundException.

**The `org.apache.hadoop.conf` relocation requires `hadoop-common` as a compile-scope dependency.** The relocation rewrites references in your shaded JAR from `org.apache.hadoop.conf.*` to `shaded.org.apache.hadoop.conf.*` so they don't collide with classes loaded by `flink-s3-fs-hadoop` on MSF — but the relocation only has anything to rewrite if `hadoop-common` is actually in the shade input. If you call `CatalogLoader.custom(name, props, new Configuration(), implClass)` (or otherwise reference `org.apache.hadoop.conf.Configuration`) without adding `hadoop-common` to the pom, compilation fails with `package org.apache.hadoop.conf does not exist`. Adding `hadoop-common` and applying the relocation are a pair: the dep brings the class in, the relocation keeps it from colliding with the MSF-bundled copy.

## Common Anti-Patterns

1. **No compaction strategy for streaming writes.** Small files accumulate silently until queries become unusable. Always pair streaming writes with maintenance (S3 Tables auto-maintenance, Glue auto-compaction, or Flink embedded maintenance).

2. **Time-based snapshot retention for streaming.** "Keep 7 days" means 600,000+ snapshots at 60-second intervals. Use count-based retention.

3. **Enabling maintenance with S3 Tables.** S3 Tables handles compaction, snapshot management, and orphan cleanup automatically. Running Flink embedded maintenance or external compaction alongside it causes commit conflicts.

4. **Missing partition columns in equality fields.** Causes incorrect upsert behavior with HASH distribution on partitioned tables.

5. **Configuring checkpoints in application code for MSF.** MSF manages checkpointing. Only configure checkpoints in code for local development.

6. **Using FlinkSink when maintenance is needed.** The TableMaintenance API requires IcebergSink (SinkV2). FlinkSink does not support post-commit maintenance topology.

7. **Streaming reads from upsert tables.** IcebergSource streaming mode only supports append-only tables. Tables with equality deletes are not supported for streaming reads.

8. **Running maintenance operations out of order.** The correct order is: compact → expire snapshots → delete orphans → rewrite manifests. Running orphan cleanup before snapshot expiration can delete files still referenced by active snapshots.

9. **High-cardinality partitioning.** Partitioning by a column with millions of distinct values creates millions of tiny partitions that can't be compacted within partition boundaries.

10. **Missing `ServicesResourceTransformer` in shade plugin.** Causes runtime ClassNotFoundException for Iceberg FileIO and Catalog implementations on MSF.

11. **Using distribution mode NONE with upsert.** Without HASH distribution, Flink uses rebalance to distribute records across writer tasks. Multiple updates to the same key within a checkpoint can land on different writers, causing the delete file on one writer to miss the insert on another — resulting in duplicate rows. Always use `distributionMode(DistributionMode.HASH)` for upsert workloads.

12. **Assuming multi-table writes are atomic.** Iceberg commits are per-table. When writing to multiple tables via StatementSet, each table commits independently. Failure between commits leaves tables in inconsistent state. Design downstream consumers to tolerate this, or use snapshot correlation via `flink.job-id` in snapshot summary.

13. **Combining Glue auto-compaction with Flink embedded compaction.** Both will attempt to compact the same files, causing commit conflicts and wasted compute. Pick one compaction approach per table.
