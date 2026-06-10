# Apache Iceberg Integration with Flink on Managed Service for Apache Flink

## Overview

This guide covers building Apache Iceberg applications with Apache Flink on Amazon Managed Service for Apache Flink (MSF): table format selection, write APIs (append, upsert, dynamic, multi-table), distribution modes, read patterns, partitioning strategy, and DDL.

**Mandatory companion file — load before answering catalog or maintenance questions:** [iceberg-tuning-and-operations.md](iceberg-tuning-and-operations.md).

If the user asks about these topics, You MUST also load iceberg-tuning-and-operations.md:

* AWS Glue Catalog vs S3 Tables (which catalog to pick)
* Iceberg table maintenance (compaction, snapshot expiration, orphan cleanup)
* Small files problem
* Flink TableMaintenance API, JDBC locks, post-commit maintenance
* Glue auto-compaction, S3 Tables managed compaction
* Iceberg + Flink dependencies / Maven setup
* Iceberg anti-patterns and monitoring

This file (iceberg-connector-guide.md) does NOT contain the catalog decision matrix or maintenance approaches — those live exclusively in iceberg-tuning-and-operations.md. Answering a catalog or maintenance question from this file alone WILL miss required content.

Iceberg version guidance: Use Iceberg 1.10+ for Flink 1.20, which includes IcebergSink (SinkV2), the TableMaintenance streaming API, delete vectors, and the Dynamic Iceberg Sink. For Flink 2.2, use the corresponding Iceberg release that supports the `iceberg-flink-runtime-2.0` artifact.

## Table Format Version Selection

Iceberg supports three format versions. Choose based on your write pattern:

| Format Version | Use Case | Key Features |
|---|---|---|
| v1 | Append-only workloads | Basic table format, no row-level deletes |
| v2 | Upsert/CDC workloads | Equality deletes, position deletes, row-level operations |
| v3 | Upsert with optimized reads | Delete vectors (more efficient than equality deletes for read performance) |

Set the format version when creating the table:

```sql
-- SQL DDL
CREATE TABLE my_table (
    id BIGINT,
    data STRING,
    PRIMARY KEY (id) NOT ENFORCED
) WITH (
    'format-version' = '2',
    'write.upsert.enabled' = 'true'
);
```

```java
// DataStream API - table creation via Catalog
Map<String, String> tableProperties = new HashMap<>();
tableProperties.put("format-version", "2");
tableProperties.put("write.upsert.enabled", "true");
tableProperties.put("write.delete.mode", "merge-on-read");

catalog.createTable(tableId, schema, partitionSpec, tableProperties);
```

**Guidance:**

* Use v2 for any table that needs upserts, updates, or deletes
* v1 is sufficient for pure append workloads (event logs, clickstreams)
* v3 adds delete vectors which improve read performance for upsert tables, but check query engine compatibility

## Write Patterns

### Choosing a Write API

Iceberg provides two DataStream sink implementations and a SQL path:

| API | Class | When to Use |
|---|---|---|
| IcebergSink (SinkV2) | `IcebergSink` | New applications. Required for table maintenance topology. Supports upsert, branch writes, metrics. |
| FlinkSink (legacy) | `FlinkSink` | Existing applications not yet migrated. Still the default in SQL path unless opted in. |
| SQL INSERT INTO | Table API | SQL-first teams, multi-table routing with StatementSet, simpler pipelines. |
| DynamicIcebergSink | `DynamicIcebergSink` | Dynamic table routing, schema evolution, writing to multiple tables from one stream. |

To use IcebergSink (SinkV2) via SQL, set:

```sql
SET 'table.exec.iceberg.use-v2-sink' = 'true';
```

**Important difference:** IcebergSink uses `uidSuffix` for operator UIDs, while FlinkSink uses `uidPrefix`. When migrating, this affects state compatibility.

### Append Mode (DataStream)

```java
IcebergSink.forRowData(rowDataStream)
    .tableLoader(tableLoader)
    .set("write.format.default", "parquet")
    .set("write.target-file-size-bytes", "134217728")  // 128 MB
    .append();
```

### Upsert Mode (DataStream)

Upsert requires v2+ table format and equality field columns. Partition columns MUST be included in equality fields when using HASH distribution with partitioned tables.

```java
IcebergSink.forRowData(rowDataStream)
    .tableLoader(tableLoader)
    .upsert(true)
    .equalityFieldColumns(Arrays.asList("event_id", "event_date", "region"))
    .set("write.delete.mode", "merge-on-read")
    .set("write.update.mode", "merge-on-read")
    .set("write.merge.mode", "merge-on-read")
    .set("write.format.default", "parquet")
    .set("write.target-file-size-bytes", "134217728")
    .distributionMode(DistributionMode.HASH)
    .append();
```

**Critical upsert rules:**

* Table must use format-version 2 or 3
* Primary key / equality fields must be defined
* Partition columns must be included in equality fields for HASH distribution
* OVERWRITE and UPSERT are mutually exclusive
* Upsert generates equality delete files which accumulate and degrade read performance — compaction is essential
* **HASH distribution is required for correctness with upsert.** Without it (distribution mode NONE), Flink uses rebalance to distribute records across writer tasks. If multiple updates to the same key land on different writer tasks within the same checkpoint, the delete file written by one task cannot find the insert written by another, causing duplicate rows. HASH distribution ensures all records for the same equality fields go to the same writer task. This is a correctness requirement, not just a performance optimization.

### Upsert Mode (SQL)

```sql
CREATE TABLE orders (
    event_id STRING,
    event_date DATE,
    region STRING,
    amount DECIMAL(18, 2),
    PRIMARY KEY (event_id, event_date, region) NOT ENFORCED
) PARTITIONED BY (event_date, region)
WITH (
    'format-version' = '2',
    'write.upsert.enabled' = 'true',
    'write.delete.mode' = 'merge-on-read',
    'write.target-file-size-bytes' = '134217728'
);

-- Upsert via SQL hint (overrides table property per-query)
INSERT INTO orders /*+ OPTIONS('upsert-enabled'='true') */
SELECT * FROM kinesis_source WHERE event_type = 'ORDER';
```

### Multi-Table Routing with StatementSet (SQL)

StatementSet reads the source once and routes to multiple tables efficiently:

```java
StatementSet statementSet = tableEnv.createStatementSet();

statementSet.addInsertSql("INSERT INTO orders SELECT ... FROM kinesis_source WHERE event_type = 'ORDER'");
statementSet.addInsertSql("INSERT INTO users SELECT ... FROM kinesis_source WHERE event_type = 'USER'");
statementSet.addInsertSql("INSERT INTO clicks SELECT ... FROM kinesis_source WHERE event_type = 'CLICK'");

statementSet.execute();  // Single source read, three sinks
```

**Cross-table consistency warning:** Iceberg has no atomic multi-table commit. When a Flink job writes to multiple tables, each table commits independently at checkpoint boundaries. The commits happen sequentially, not atomically. If the job fails between committing table A and table B, downstream queries joining A and B see inconsistent state. Mitigation: each Iceberg snapshot records the Flink checkpoint ID in its summary (`flink.job-id` property). Downstream consumers can query snapshots by checkpoint ID across tables to get a consistent view, but this requires custom read-side logic.

### Dynamic Sink for Schema-Agnostic Routing

The DynamicIcebergSink routes records to tables dynamically, creating tables and evolving schemas automatically:

```java
DynamicIcebergSink.forInput(jsonStream)
    .generator(new MyRoutingGenerator())
    .catalogLoader(catalogLoader)
    .immediateTableUpdate(true)
    .cacheMaxSize(100)
    .cacheRefreshMs(60000)
    .set("write.format.default", "parquet")
    .set("format-version", "2")
    .set("write.target-file-size-bytes", "134217728")
    .append();
```

**Dynamic Sink supports:** adding new columns, widening column types, making required columns optional. It does NOT support dropping or renaming columns.

### Branch Writes

Write to a branch for staging data before merging to main:

```java
IcebergSink.forRowData(rowDataStream)
    .tableLoader(tableLoader)
    .toBranch("staging")
    .append();
```

### Distribution Modes

| Mode | When to Use | Trade-offs |
|---|---|---|
| NONE | Append-only, no partitioning | No shuffle overhead, but may create many small files per partition |
| HASH | Upsert with partitioned tables | Shuffles by partition key or equality fields. Limited by key cardinality. |
| RANGE (experimental) | Skewed data, high-cardinality partitions | Handles skew well, collects traffic statistics. Higher CPU overhead. |

HASH distribution limitation: writer parallelism is capped by the cardinality of the hash key. If you have 10 distinct partition values, only 10 writer tasks receive data regardless of total parallelism.

RANGE distribution handles skewed data (e.g., recent partitions have more traffic than old ones) and can cluster data on non-partition columns when a SortOrder is defined.

## Write Mode Trade-offs: Copy-on-Write vs Merge-on-Read

| Aspect | Copy-on-Write (CoW) | Merge-on-Read (MoR) |
|---|---|---|
| Write cost | High (rewrites entire data files) | Low (writes small delete files) |
| Read cost | Low (no merge logic at query time) | Higher (must merge delete files with data files) |
| Best for | Read-heavy analytical workloads | Write-heavy streaming/CDC workloads |
| Compaction need | Lower | Higher (delete files accumulate) |

**For streaming workloads on MSF, use Merge-on-Read.** It keeps write latency low and checkpoint times fast. Pair it with regular compaction to control read amplification.

### Equality Delete Considerations

Equality deletes are the only viable option for streaming upsert/CDC workloads (the writer doesn't know the physical file location of the row to delete). Key considerations:

* Delete files accumulate with every checkpoint that includes updates/deletes
* Query engines must merge delete files with data files at read time (read amplification)
* Some query engines have limited equality delete support (check your downstream consumers)
* Regular compaction is essential to merge delete files into data files and restore read performance
* Monitor the `equality_delete_file_count` and `equality_delete_record_count` in the `$partitions` metadata table

## Read Patterns

### Streaming Read (DataStream API)

Streaming reads discover new snapshots at a configurable interval. **Streaming reads only work for append-only tables** — tables with upserts (equality deletes) are NOT supported for streaming reads.

```java
IcebergSource<RowData> source = IcebergSource.forRowData()
    .tableLoader(tableLoader)
    .streaming(true)
    .streamingStartingStrategy(StreamingStartingStrategy.INCREMENTAL_FROM_LATEST_SNAPSHOT)
    .monitorInterval(Duration.ofSeconds(60))
    .build();

DataStream<RowData> stream = env.fromSource(
    source,
    WatermarkStrategy.<RowData>forBoundedOutOfOrderness(Duration.ofSeconds(30))
        .withIdleness(Duration.ofMinutes(1)),
    "Iceberg Source",
    TypeInformation.of(RowData.class)
);
```

**Starting strategies:**

* `INCREMENTAL_FROM_LATEST_SNAPSHOT` — Start from latest snapshot (inclusive), discover new appends
* `INCREMENTAL_FROM_EARLIEST_SNAPSHOT` — Start from earliest snapshot (inclusive)
* `TABLE_SCAN_THEN_INCREMENTAL` — Full table scan first, then switch to incremental
* `INCREMENTAL_FROM_SNAPSHOT_ID` — Start from a specific snapshot ID (inclusive)
* `INCREMENTAL_FROM_SNAPSHOT_TIMESTAMP` — Start from a specific timestamp (inclusive)

### Streaming Read (SQL)

```sql
SET table.dynamic-table-options.enabled = true;

-- Read incrementally from latest snapshot
SELECT * FROM my_table /*+ OPTIONS('streaming'='true', 'monitor-interval'='60s') */;

-- Read from a specific snapshot
SELECT * FROM my_table /*+ OPTIONS('streaming'='true', 'monitor-interval'='60s', 'start-snapshot-id'='12345') */;
```

### Batch Read with Time Travel (SQL)

```sql
SET execution.runtime-mode = batch;

-- Read current snapshot
SELECT * FROM my_table;

-- Read from a specific snapshot
SELECT * FROM my_table /*+ OPTIONS('snapshot-id'='12345') */;

-- Read from a specific timestamp
SELECT * FROM my_table /*+ OPTIONS('as-of-timestamp'='1672531200000') */;

-- Read from a branch or tag
SELECT * FROM my_table /*+ OPTIONS('branch'='staging') */;
SELECT * FROM my_table /*+ OPTIONS('tag'='v1.0') */;
```

### Watermark Generation from Iceberg Column Statistics

IcebergSource can generate watermarks from file-level column statistics, useful for windowed processing:

```java
IcebergSource.forRowData()
    .tableLoader(tableLoader)
    .watermarkColumn("event_time")  // timestamp, timestamptz, or long column
    .build();
```

When using watermark columns, set `read.split.open-file-cost` to a large value to prevent combining small files into a single split, which would increase out-of-orderness.

### HybridSource: Bootstrap from Iceberg, Then Stream from Kinesis

The FLIP-150 HybridSource pattern reads historical data from Iceberg (bounded), then seamlessly switches to real-time Kinesis (unbounded):

```java
// Source 1: Iceberg (bounded) - reads all historical data
IcebergSource<RowData> icebergSource = IcebergSource.forRowData()
    .tableLoader(tableLoader)
    .streaming(false)
    .build();

// Source 2: Kinesis (unbounded) - real-time streaming
KinesisStreamsSource<RowData> kinesisSource = KinesisStreamsSource.<RowData>builder()
    .setStreamArn(streamArn)
    .setDeserializationSchema(new JsonToRowDataDeserializer(schema))
    .setSourceConfig(sourceConfig)
    .build();

// Automatic switchover when Iceberg source completes
HybridSource<RowData> hybridSource = HybridSource
    .builder(icebergSource)
    .addSource(kinesisSource)
    .build();
```

Use cases: backfilling new streaming applications, recovering from extended downtime, migrating from batch to streaming.

### Inspecting Tables with Metadata Tables

Query Iceberg metadata tables for operational visibility:

```sql
-- View snapshots (check for flink.job-id in summary)
SELECT snapshot_id, committed_at, operation, summary FROM db.my_table$snapshots;

-- View current data files (detect small files)
SELECT file_path, record_count, file_size_in_bytes FROM db.my_table$files;

-- View partitions (check delete file accumulation)
SELECT partition, file_count, record_count,
       equality_delete_file_count, equality_delete_record_count
FROM db.my_table$partitions;

-- View manifests
SELECT path, added_data_files_count, deleted_data_files_count FROM db.my_table$manifests;

-- View table history
SELECT made_current_at, snapshot_id, is_current_ancestor FROM db.my_table$history;

-- View branch and tag references
SELECT name, type, snapshot_id FROM db.my_table$refs;
```

## Partitioning Strategy

### Guidelines

* **Partition tables with more than ~1 million records.** Unpartitioned large tables force full scans.
* **Use moderate cardinality.** Too high (e.g., per-sensor_id with 50,000 sensors) creates millions of tiny partitions that can't be compacted. Too low (e.g., single region) provides minimal pruning benefit.
* **Time-series data:** Partition by `day(event_time)` or `hour(event_time)`, not by raw timestamp.
* **Flink SQL limitation:** Flink DDL does not support hidden partitioning transforms like `day()`, `bucket()`, or `truncate()`. Use the DataStream/Catalog API for hidden partitions, or partition by a pre-computed column.

### Partition Evolution

Iceberg supports changing partition strategy without rewriting data:

```sql
ALTER TABLE my_table ADD PARTITION FIELD days(event_time);
```

New data uses the new scheme; old data remains readable under the old scheme. Queries automatically use the correct partition logic.

### Partition Columns in Equality Fields

When using upsert mode with HASH distribution on a partitioned table, the partition columns MUST be included in the equality fields. For example, if the table is partitioned by `(event_date, region)`, the equality fields must include both:

```java
.equalityFieldColumns(Arrays.asList("event_id", "event_date", "region"))
```

Failing to include partition columns causes incorrect upsert behavior — updates may not find the correct rows to delete.

## DDL Reference for Iceberg Tables in Flink SQL

### CREATE TABLE with Common Properties

```sql
CREATE TABLE `glue_catalog`.`my_db`.`my_table` (
    id BIGINT COMMENT 'unique id',
    event_time TIMESTAMP(6),
    data STRING NOT NULL,
    region STRING,
    event_date DATE,
    PRIMARY KEY (id, event_date, region) NOT ENFORCED
) PARTITIONED BY (event_date, region)
WITH (
    'format-version' = '2',
    'write.format.default' = 'parquet',
    'write.parquet.compression-codec' = 'snappy',
    'write.target-file-size-bytes' = '134217728',
    'write.upsert.enabled' = 'true',
    'write.delete.mode' = 'merge-on-read',
    'write.update.mode' = 'merge-on-read',
    'write.merge.mode' = 'merge-on-read'
);
```

### ALTER TABLE (Properties Only)

Flink only supports altering table properties, not columns or partitions:

```sql
ALTER TABLE my_table SET ('write.format.default' = 'orc');
ALTER TABLE my_table RENAME TO new_table_name;
```

### Flink DDL Limitations

* No hidden partitioning transforms (`day()`, `bucket()`, `truncate()`) in DDL — use DataStream API or pre-computed columns
* No computed columns
* No watermark definitions in DDL
* Column and partition changes not supported via ALTER TABLE
