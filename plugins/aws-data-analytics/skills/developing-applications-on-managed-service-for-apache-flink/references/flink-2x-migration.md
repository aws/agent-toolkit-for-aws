# Flink 2.x Migration Guide

## Overview

This guide covers migrating Flink applications from 1.x to 2.x. Key changes: Java 17 minimum (Java 8 and 11 no longer supported), major API removals, and serialization breaking changes affecting state compatibility.

**CRITICAL**: State migration from 1.x to 2.x fails for applications using Kryo or POJOs with collection fields. See [State Compatibility](#state-compatibility) before planning migrations.

## Major Breaking Changes Summary

| Category | Change | Impact |
|----------|--------|--------|
| Java | Java 8 and 11 removed, Java 17 default, Java 21 experimental (not supported in MSF) | Must upgrade runtime |
| Source API | `SourceFunction` removed | Must migrate to new Source API |
| Sink API | `SinkFunction`, `SinkV1` removed | Must migrate to Sink V2 API |
| Config | `flink-conf.yaml` removed | Must use `config.yaml` (standard YAML) |
| Time API | `Time` class deprecated | Use `java.time.Duration` |
| Serialization | Kryo 2.x → 5.x, new collection serializers | State incompatibility (see below) |
| DataSet API | Entire DataSet API removed | Migrate to DataStream or Table API/SQL |
| Scala API | Scala API removed entirely | Use Java API (callable from Scala) |
| Python | Python 3.8 removed, Python 3.12 default | Update Python runtime |
| DataStream | `IterativeStream`, `TimeCharacteristic` removed | Refactor required |

## Dependency Changes

### Version Updates Required

```xml
<properties>
    <!-- Core versions -->
    <flink.version>2.2.0</flink.version>
    <target.java.version>17</target.java.version>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
    
    <!-- Connector versions (use 2.x compatible) -->
    <kafka.version>4.0.1-2.0</kafka.version>
    <kinesis-streams.version>6.0.0-2.0</kinesis-streams.version>
    
    <!-- Updated dependencies -->
    <msk-iam-auth.version>2.3.5</msk-iam-auth.version>
    <aws.sdk.version>1.12.677</aws.sdk.version>
    <jackson.version>2.15.2</jackson.version>
    <lombok.version>1.18.36</lombok.version>
    <log4j.version>2.23.1</log4j.version>
    <maven.compiler.plugin.version>3.11.0</maven.compiler.plugin.version>
</properties>
```

### Logging Changes

Flink 2.x uses `log4j-slf4j-impl` instead of `slf4j-log4j12`.

> **Note:** If migrating from Flink 1.20, you likely already use `log4j-slf4j-impl`. This change only applies when migrating from Flink versions older than ~1.15 that used `slf4j-log4j12`.

```xml
<!-- Remove these -->
<!-- <artifactId>slf4j-log4j12</artifactId> -->

<!-- Use these -->
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-slf4j-impl</artifactId>
    <version>${log4j.version}</version>
</dependency>
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-api</artifactId>
    <version>${log4j.version}</version>
</dependency>
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-core</artifactId>
    <version>${log4j.version}</version>
</dependency>
```

### Glue Schema Registry Conflict

Exclude old flink-avro from Glue Schema Registry until it is updated for Flink 2.x:

```xml
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-avro</artifactId>
    <version>${flink.version}</version>
</dependency>
<dependency>
    <groupId>software.amazon.glue</groupId>
    <artifactId>schema-registry-flink-serde</artifactId>
    <version>1.1.15</version>
    <exclusions>
        <exclusion>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-avro</artifactId>
        </exclusion>
    </exclusions>
</dependency>
```

### Scope Changes for Standalone Deployment

For non-Managed Service for Apache Flink deployment, change scope from `provided` to `compile`:

```xml
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-streaming-java</artifactId>
    <version>${flink.version}</version>
    <scope>compile</scope> <!-- Required for CEP serialization in 2.x -->
</dependency>
```

## Code Changes

### Time API Migration

Replace `org.apache.flink.streaming.api.windowing.time.Time` with `java.time.Duration`:

```java
// Before (1.x)
import org.apache.flink.streaming.api.windowing.time.Time;
.window(TumblingProcessingTimeWindows.of(Time.seconds(10)))
.window(SlidingProcessingTimeWindows.of(Time.minutes(1), Time.seconds(1)))
.window(EventTimeSessionWindows.withGap(Time.seconds(30)))
.within(Time.seconds(10))

// After (2.x)
import java.time.Duration;
.window(TumblingProcessingTimeWindows.of(Duration.ofSeconds(10)))
.window(SlidingProcessingTimeWindows.of(Duration.ofMinutes(1), Duration.ofSeconds(1)))
.window(EventTimeSessionWindows.withGap(Duration.ofSeconds(30)))
.within(Duration.ofSeconds(10))
```

### Configuration API Migration

Replace string-based config with type-safe ConfigOptions:

```java
// Before (1.x)
config.setInteger("rest.port", 8081);
config.setBoolean("web.submit.enable", true);

// After (2.x)
import org.apache.flink.configuration.RestOptions;
import org.apache.flink.configuration.WebOptions;
config.set(RestOptions.PORT, 8081);
config.set(WebOptions.SUBMIT_ENABLE, true);
```

### Function Lifecycle Changes

`open()` method signature changed from `Configuration` to `OpenContext`:

```java
// Before (1.x)
@Override
public void open(Configuration parameters) {
    // initialization
}

// After (2.x)
@Override
public void open(org.apache.flink.api.common.functions.OpenContext openContext) throws Exception {
    // initialization
}
```

This change applies to every `RichFunction` subclass — `RichMapFunction`, `RichFlatMapFunction`, `RichFilterFunction`, `KeyedProcessFunction`, `BroadcastProcessFunction`, `KeyedBroadcastProcessFunction`, `ProcessWindowFunction`, async I/O `RichAsyncFunction`, etc. Any code that overrides `open(Configuration)` will fail to compile against Flink 2.2. `OpenContext` does not carry the legacy `Configuration` key/value bag — read runtime properties via the `KinesisAnalyticsRuntime.getApplicationProperties()` flow or pass them through your function's constructor.

The `open()` change is one of several Flink 2.x breaking API changes you'll likely hit during the same migration. See [Removed APIs and Migration Paths](#removed-apis-and-migration-paths) for the full table; the headline removals are:

- `SourceFunction` and `SinkFunction` are removed in favor of `Source` (FLIP-27) and `Sink` (FLIP-143) — `env.addSource()` / `stream.addSink()` no longer compile.
- `org.apache.flink.api.common.time.Time` is deprecated in favor of `java.time.Duration`. Anything that took `Time` (TTL, idleness, async I/O timeout) now takes `Duration`.
- `TimeCharacteristic` is removed — event-time is the only mode and `setStreamTimeCharacteristic()` is gone.
- `enableForceAvro()` and the convenience Kryo registration methods on `StreamExecutionEnvironment` are removed; use `env.getConfig()` equivalents.

### CEP Pattern Type Information

CEP requires explicit TypeInformation for pattern output:

```java
// Before (1.x)
CEP.pattern(stream, pattern)
    .inEventTime()
    .select(this::extractResult);

// After (2.x)
import org.apache.flink.api.common.typeinfo.TypeHint;
import org.apache.flink.api.common.typeinfo.TypeInformation;

CEP.pattern(stream, pattern)
    .inEventTime()
    .select(
        this::extractResult,
        TypeInformation.of(new TypeHint<ResultType>() {})
    );
```

### POJO Requirements

POJOs must implement Serializable with no-args constructor:

```java
// Before (1.x) - might work without these
@Data
@Builder
public class Event {
    private String id;
    private long timestamp;
}

// After (2.x) - required for proper serialization
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Event implements Serializable {
    private static final long serialVersionUID = 1L;
    private String id;
    private long timestamp;
}
```

### Removed Classes

- `org.apache.flink.streaming.api.TimeCharacteristic` - removed, event time is default
- `org.apache.flink.api.java.typeutils.runtime.kryo.Serializers` - Kryo serializer classes removed
- `flink-java` module removed entirely

## State Compatibility

### Breaking Changes Summary

Three serialization incompatibilities prevent state migration from 1.x to 2.x:

| Issue | Root Cause | Affected Patterns | Error Signature |
|-------|-----------|-------------------|-----------------|
| Kryo reference tracking | Kryo 2.x → 5.x upgrade | `registerTypeWithKryoSerializer()` | `IndexOutOfBoundsException: Index 116 out of bounds for length 1` |
| Kryo CollectionSerializer | Kryo's internal collection format changed | Generic collections: `List<T>`, `Map<K,V>`, `Set<T>` in state | `ClassNotFoundException: value2` (data misinterpreted as class names) |
| PojoSerializer collection handling | TypeExtractor selects different serializers (FLINK-34037) | POJO fields: List, Map, Set, Collection, Queue, Deque | `StateMigrationException: PojoSerializer@8bf85b5d incompatible with @3282ee3` |

### Compatible Patterns (State Migrates Successfully)

**Serialization Methods:**

- **Avro serialization** with explicit `AvroTypeInfo` - schema-based, independent of Flink's type system
- **Protobuf serialization** - schema-based, bypasses TypeExtractor
- **Custom TypeSerializer** implementations - user-controlled serialization
- **Simple POJOs** without collection fields - no TypeExtractor collection handling
- **Flink Tuples** - direct field access, no reflection
- **Primitive types** - fastest, no serialization changes

**State Types (all compatible with above serializers):**

- ValueState, MapState, ListState, ReducingState, AggregatingState
- BroadcastState with control streams
- Operator state (even-split and union redistribution)
- Window state (tumbling, sliding, session windows)
- Timer state (event-time and processing-time)

**Connectors:**

- Kinesis connector state (v5.0+ only — see note below; default polling and Enhanced Fan-Out)
- Kafka connector state (offsets, partition tracking)

**CRITICAL — Kinesis Connector Version Prerequisite:** KDS connector versions below 5.0 maintain state that is incompatible with the Flink 2.2 Kinesis connector (v6.0.0-2.0). You must migrate to connector v5.0+ on Flink 1.x before upgrading to Flink 2.x. See `kinesis-connector-guide.md` for migration paths and the [AWS blog post](https://aws.amazon.com/blogs/big-data/introducing-the-new-amazon-kinesis-source-connector-for-apache-flink/) for details.

**Table API/SQL (with caveat):**

- All tested patterns compatible: GROUP BY, window aggregations (TUMBLE, HOP, SESSION)
- Stream joins (INNER, LEFT OUTER), Top-N, deduplication
- DISTINCT aggregations, OVER windows
- Table API provides alternative migration path avoiding DataStream serialization issues
- **Caveat:** Apache Flink does not guarantee state compatibility between major versions for Table API applications. Always test in a non-production environment first.

### Incompatible Patterns (State Migration Fails)

**Direct Kryo Usage:**

```java
// INCOMPATIBLE - Kryo 2.x → 5.x reference tracking changed
env.getConfig().registerTypeWithKryoSerializer(MyType.class, MyKryoSerializer.class);
```

**Generic Collections in State:**

```java
// INCOMPATIBLE - Kryo CollectionSerializer format changed
ValueState<List<String>> listState;
ValueState<Map<String, Integer>> mapState;
ValueState<Set<Long>> setState;
```

**POJOs with Collection Fields:**

```java
// INCOMPATIBLE - TypeExtractor selects different collection serializers
public class UserSession {
    public String userId;
    public List<String> eventTypes;        // BREAKS
    public Map<String, Integer> counts;    // BREAKS
    public Set<String> visitedPages;       // BREAKS
    public Queue<Event> eventQueue;        // BREAKS
}
```

**Scala Case Classes:**

```scala
// INCOMPATIBLE - Serialized via Kryo in Flink 1.x, Kryo v2→v5 binary format change breaks state
case class UserEvent(userId: String, eventType: String, timestamp: Long)
```

**Java Records:**

```java
// INCOMPATIBLE - Typically fall back to Kryo serialization in Flink 1.x
// Verify by testing with env.getConfig().disableGenericTypes()
public record UserEvent(String userId, String eventType, long timestamp) {}
```

**Third-Party Library Types:**

```java
// INCOMPATIBLE - Types without a registered custom serializer fall back to Kryo
// The Kryo v2→v5 binary format change breaks all Kryo-serialized state
ValueState<ThirdPartyType> state; // Any type from external libraries using Kryo fallback
```

**Any Type Using Kryo Fallback:**
If Flink cannot handle a type with a built-in or registered serializer, it falls back to Kryo. All Kryo-serialized state from 1.x is incompatible with 2.2. Use `env.getConfig().disableGenericTypes()` during development to detect Kryo fallback.

### Failure Behavior and Detection

**Failure Path:**

1. Managed Service for Apache Flink application update completes successfully (no errors during deployment)
2. Job transitions to RUNNING state
3. State restoration begins during operator initialization
4. Deserialization fails with serializer mismatch
5. Job transitions to FAILED state
6. Restart strategy triggers automatic restart
7. **Infinite restart loop** - same failure repeats until manual intervention

#### Critical: No Sync API Feedback

- Update API returns success before state restoration
- Failures occur during state restoration path (outside async workflow scope)
- State restoration duration varies (seconds to tens of minutes based on state size)
- **Only visible through metrics**: downtime, restart count, uptime

**Error Signatures to Watch For:**

*Kryo Reference Tracking:*

```
com.esotericsoftware.kryo.KryoException: Unable to resolve reference for String with id: 116
Caused by: java.lang.IndexOutOfBoundsException: Index 116 out of bounds for length 1
```

*Kryo CollectionSerializer:*

```
com.esotericsoftware.kryo.KryoException: Unable to find class: value2
Caused by: java.lang.ClassNotFoundException: value2
```

*PojoSerializer Collection Handling:*

```
org.apache.flink.util.StateMigrationException: The new state serializer 
(org.apache.flink.api.java.typeutils.runtime.PojoSerializer@8bf85b5d) must not be 
incompatible with the old state serializer 
(org.apache.flink.api.java.typeutils.runtime.PojoSerializer@3282ee3)
```

### Pre-Migration Assessment

**Identify Incompatible Patterns:**

1. **Search for Kryo registration:**

```java
grep -r "registerTypeWithKryoSerializer" src/
grep -r "registerKryoType" src/
```

1. **Search for collection fields in POJOs:**

```java
// Look for POJOs with List, Map, Set, Collection, Queue, Deque fields
// that are used in state (ValueState, MapState, etc.)
```

1. **Search for generic collection state:**

```java
grep -r "ValueState<List" src/
grep -r "ValueState<Map" src/
grep -r "ValueState<Set" src/
```

1. **Check for Kryo fallback warnings in logs:**

```
"Class ... cannot be used as a POJO type because not all fields are valid POJO fields"
```

### Migration Strategies for Incompatible Apps

#### Strategy 1: Parallel Deployment (Zero Downtime)

- Deploy Flink 2.x application alongside 1.x
- Let 2.x rebuild state from scratch while 1.x continues processing
- Switch traffic once 2.x state is fully built
- Best for: Applications that can tolerate dual processing temporarily

#### Strategy 2: State Processor API (State Transformation)

- Use State Processor API to read 1.x savepoint
- Transform state serialization to 2.x-compatible format (Avro/Protobuf)
- Write new savepoint for 2.x restoration
- Best for: Large state that cannot be rebuilt quickly

#### Strategy 3: Reprocess from Source (Clean Start)

- Take final savepoint from 1.x for audit/rollback
- Deploy 2.x with refactored serialization (Avro/Protobuf)
- Reprocess historical data from Kinesis/Kafka/S3
- Best for: Applications with replayable sources and acceptable rebuild time

#### Strategy 4: Refactor Before Migration (Recommended)

- Refactor 1.x application to use compatible serialization (Avro/Protobuf)
- Deploy refactored 1.x, let it checkpoint with new serialization
- Then migrate to 2.x with state preservation
- Best for: Minimizing risk and ensuring future compatibility

### Best Practices for Migration-Safe Applications

**Use Schema-Based Serialization:**

```java
// RECOMMENDED: Avro with explicit TypeInformation
import org.apache.flink.formats.avro.typeutils.AvroTypeInfo;

ValueStateDescriptor<UserEvent> descriptor = new ValueStateDescriptor<>(
    "user-events",
    AvroTypeInfo.of(UserEvent.class)
);
```

**Avoid Collection Fields in POJOs:**

```java
// INSTEAD OF:
public class UserSession {
    public List<String> events; // BREAKS on migration
}

// USE:
public class UserSession {
    public String eventsJson; // Serialize collections as strings
    // Or use Avro schema with array types
}
```

**Use MapState Instead of Collections:**

```java
// INSTEAD OF:
ValueState<Map<String, Integer>> mapState; // BREAKS

// USE:
MapState<String, Integer> mapState; // Compatible - Flink's built-in state type
```

**Detect Kryo Fallbacks During Development:**

```java
// Add during development to catch serialization issues early
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
env.getConfig().disableGenericTypes(); // Throws exception if Kryo would be used
```

## MSF Upgrade Workflow

### Understanding Migration Paths

Your upgrade experience depends on your application's compatibility with Flink 2.2:

**Path 1: Compatible binary and state** — Invoke the Upgrade operation. Application transitions RUNNING → UPDATING → RUNNING with full state preservation. Same experience as minor version migrations. Best for stateless applications or those using compatible serialization (Avro, Protobuf, simple POJOs without collections).

**Path 2: Binary incompatibilities** — Upgrade operation fails and surfaces the incompatibility through Operations API and logs. With auto-rollback enabled, the application automatically rolls back within minutes. With auto-rollback disabled, the application remains running without processing data until you manually roll back. Fix the binary issues, then re-attempt for a Path 1 experience.

**Path 3: Incompatible application state** — Upgrade appears to succeed initially, but the application enters restart loops within seconds as state restoration fails. Detect via CloudWatch metrics (`numRestarts` increasing, `runningTime` not increasing). Manually invoke the Rollback operation, then review the State Compatibility section above.

### Upgrade Phases

#### Phase 1: Preparation

1. Update application code for Flink 2.2 compatibility (dependencies, removed APIs, Java 17)
2. Build the new JAR and upload to S3 with a different file name (e.g., `my-app-flink-2.2.jar`)

#### Phase 2: Enable auto-rollback

Check and enable auto-rollback before upgrading:

```bash
# Check auto-rollback status
aws kinesisanalyticsv2 describe-application \
    --application-name MyApplication \
    --query 'ApplicationDetail.ApplicationConfigurationDescription.ApplicationSystemRollbackConfigurationDescription.RollbackEnabled'

# Enable if not already enabled
aws kinesisanalyticsv2 update-application \
    --application-name MyApplication \
    --current-application-version-id <version-id> \
    --application-configuration-update '{
        "ApplicationSystemRollbackConfigurationUpdate": {
            "RollbackEnabledUpdate": true
        }
    }'
```

#### Phase 3: Take snapshot

If automatic snapshots are enabled, you can skip this. Otherwise, take a snapshot before upgrading:

```bash
aws kinesisanalyticsv2 create-application-snapshot \
    --application-name MyApplication \
    --snapshot-name pre-flink-2.2-upgrade

# Wait until READY
aws kinesisanalyticsv2 describe-application-snapshot \
    --application-name MyApplication \
    --snapshot-name pre-flink-2.2-upgrade
```

#### Phase 4: Upgrade application

You can upgrade from RUNNING or READY state using the UpdateApplication API:

```bash
aws kinesisanalyticsv2 update-application \
    --application-name MyApplication \
    --current-application-version-id <version-id> \
    --runtime-environment-update FLINK-2_2 \
    --application-configuration-update '{
        "ApplicationCodeConfigurationUpdate": {
            "CodeContentUpdate": {
                "S3ContentLocationUpdate": {
                    "FileKeyUpdate": "my-app-flink-2.2.jar"
                }
            }
        }
    }'
```

CloudFormation also supports in-place upgrades — update the `RuntimeEnvironment` field and CloudFormation will update in place without deleting and recreating the application (preserving snapshots and history).

#### Phase 5: Monitor upgrade

- Use the Operations API to check upgrade status and surface binary incompatibilities
- If the application is RUNNING but still on the older runtime, auto-rollback kicked in — check Operations API for the failure reason
- Monitor CloudWatch metrics:
  - `numRestarts`: should be zero after upgrade
  - `runningTime`: should be steadily increasing (replaces deprecated `uptime`)
  - `lastCheckpointDuration`: should be similar to pre-upgrade values
  - `numberOfFailedCheckpoints`: should remain at 0

#### Phase 6: Validate (run 24+ hours)

- Verify data flowing through sources and sinks
- Compare output with pre-upgrade baseline
- Monitor latency, throughput, checkpoint duration/size, memory/CPU utilization

### Rollback Procedures

**Automatic rollback:** If auto-rollback is enabled and the upgrade fails during startup, MSF automatically reverts to the previous version.

**Manual rollback** (for applications running but unhealthy):

```bash
aws kinesisanalyticsv2 rollback-application \
    --application-name MyApplication \
    --current-application-version-id <version-id>
```

Rollback restores the previous Flink version, previous JAR, and restarts from the last snapshot taken before the upgrade. You cannot restore a Flink 2.2 snapshot on Flink 1.x.

### Rebuild State (for incompatible state)

If state is incompatible and cannot be migrated, start fresh:

```bash
aws kinesisanalyticsv2 start-application \
    --application-name MyApplication \
    --run-configuration '{
        "ApplicationRestoreConfiguration": {
            "ApplicationRestoreType": "SKIP_RESTORE_FROM_SNAPSHOT"
        }
    }'
```

## Build Process

Set Java 17 before building:

```bash
# Set JAVA_HOME to your Java 17 installation path before building
export JAVA_HOME=<path-to-java-17>
mvn clean package -DskipTests
```

## Removed APIs and Migration Paths

### DataSet API Removal

The entire DataSet API for batch processing has been removed. All batch processing must use the unified DataStream API or Table API/SQL:

```java
// REMOVED - DataSet API
ExecutionEnvironment env = ExecutionEnvironment.getExecutionEnvironment();
DataSet<String> data = env.readTextFile("input.txt");

// USE instead - DataStream API or Table API/SQL
StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
// Use DataStream API for batch with bounded sources, or Table API/SQL
```

### Scala API Removal

The Flink Scala API has been removed entirely. Scala-specific wrappers and implicit conversions are no longer available. Use Flink's Java API from Scala code instead.

### Source API Migration

`SourceFunction` is completely removed. Migrate to the new Source API:

```java
// REMOVED in 2.x
env.addSource(new MySourceFunction<>());

// USE instead - new Source API
env.fromSource(
    mySource,
    WatermarkStrategy.forMonotonousTimestamps(),
    "source-name"
);
```

### Sink API Migration

`SinkFunction` and `SinkV1` are removed. Migrate to Sink V2:

```java
// REMOVED in 2.x
stream.addSink(new MySinkFunction<>());

// USE instead - Sink V2 API
stream.sinkTo(mySinkV2);
```

### DataStream API Removals

```java
// REMOVED - IterativeStream (feedback loops)
stream.iterate();
stream.iterate(5000);

// REMOVED - TimeCharacteristic (event time is now default)
env.setStreamTimeCharacteristic(TimeCharacteristic.EventTime);

// REMOVED - keyBy with field positions/names
stream.keyBy(0);           // Use KeySelector instead
stream.keyBy("fieldName"); // Use KeySelector instead

// REMOVED - partitionCustom with field positions
stream.partitionCustom(partitioner, 0);

// REMOVED - legacy file methods
env.readTextFile("path");
stream.writeAsText("path");
stream.writeAsCsv("path");

// REMOVED - legacy window methods
stream.timeWindowAll(Time.seconds(10));
```

### Configuration API Removals

```java
// REMOVED - string-based configuration methods
config.setInteger("key", value);
config.getInteger("key", default);
config.setBoolean("key", value);
// ... all primitive setters/getters with string keys

// REMOVED - Kryo registration methods from StreamExecutionEnvironment
env.registerTypeWithKryoSerializer(MyClass.class, MySerializer.class);
env.addDefaultKryoSerializer(MyClass.class, MySerializer.class);
env.registerType(MyClass.class);

// REMOVED - legacy state backend setter
env.setStateBackend(stateBackend);

// REMOVED - restart strategy methods
env.setRestartStrategy(restartStrategy);
env.getRestartStrategy();
env.setNumberOfExecutionRetries(3);
```

### Configuration File Migration

Legacy `flink-conf.yaml` is no longer supported. Use `config.yaml` with standard YAML format:

```yaml
# config.yaml (new format)
jobmanager:
  rpc:
    address: localhost
    port: 6123
  memory:
    process:
      size: 1600m

taskmanager:
  memory:
    process:
      size: 1728m
  numberOfTaskSlots: 4

parallelism:
  default: 4
```

A migration tool is provided: see Flink documentation for "Migrate from flink-conf.yaml to config.yaml".

### Window Assigner Changes

Window assigners now use `Duration` instead of `Time`:

```java
// REMOVED - Time-based factory methods
TumblingEventTimeWindows.of(Time.seconds(10));
SlidingProcessingTimeWindows.of(Time.minutes(1), Time.seconds(10));
EventTimeSessionWindows.withGap(Time.minutes(5));

// USE instead
TumblingEventTimeWindows.of(Duration.ofSeconds(10));
SlidingProcessingTimeWindows.of(Duration.ofMinutes(1), Duration.ofSeconds(10));
EventTimeSessionWindows.withGap(Duration.ofMinutes(5));
```

### Connector Compatibility

First-party connectors require 2.x compatible versions. Check connector documentation for migration status:

| Connector | Flink 1.20 Version | Flink 2.0+ Version | Notes |
|-----------|--------------------|--------------------|-------|
| Apache Kafka | `flink-connector-kafka` 3.4.0-1.20 | `flink-connector-kafka` 4.0.1-2.0 | Recommended for Flink 2.2 |
| Kinesis Data Streams (source) | `flink-connector-aws-kinesis-streams` 5.1.0-1.20 (or legacy `flink-connector-kinesis` 5.0.0-1.20) | `flink-connector-aws-kinesis-streams` 6.0.0-2.0 | Must be on v5.0+ before upgrade |
| Kinesis Data Streams (sink) | `flink-connector-aws-kinesis-streams` 5.1.0-1.20 | `flink-connector-aws-kinesis-streams` 6.0.0-2.0 | Recommended for Flink 2.2 |
| Amazon Data Firehose | `flink-connector-aws-kinesis-firehose` 5.1.0-1.20 | `flink-connector-aws-kinesis-firehose` 6.0.0-2.0 | Compatible with Flink 2.0 |
| Amazon DynamoDB | `flink-connector-dynamodb` 5.1.0-1.20 | `flink-connector-dynamodb` 6.0.0-2.0 | Compatible with Flink 2.0 |
| Amazon SQS | `flink-connector-sqs` 5.1.0-1.20 | `flink-connector-sqs` 6.0.0-2.0 | Compatible with Flink 2.0 |
| FileSystem (S3, HDFS) | Bundled with Flink | Bundled with Flink | Always available |
| JDBC | `flink-connector-jdbc` 3.3.0-1.20 | Not yet released for 2.x | No Flink 2.x-compatible release |
| OpenSearch | `flink-connector-opensearch` 1.2.0-1.19 | Not yet released for 2.x | No Flink 2.x-compatible release |
| Elasticsearch | Legacy connector only | Not yet released for 2.x | Consider migrating to OpenSearch connector |
| Amazon Managed Service for Prometheus | `flink-connector-prometheus` 1.0.0-1.20 | Not yet released for 2.x | No Flink 2.x-compatible release |

Note: Some connectors were renamed between major versions (e.g., Firehose connector). Always check the MSF connector documentation for exact artifact names.

## New Features in 2.x

### Disaggregated State Management

Flink 2.x introduces ForSt (disaggregated state backend) for cloud-native deployments:

- Leverages distributed file systems as primary storage
- Asynchronous execution model for better performance
- Fast rescaling for large state (hundreds of TB)
- Reduced local disk requirements

### DataStream V2 API (Experimental)

New DataStream API with improved design (not yet production-ready):

- Cleaner separation of concerns
- Better state management primitives
- Improved type safety

### SQL and Table API Enhancements

| Feature | Description |
|---------|-------------|
| VARIANT data type | Native support for semi-structured data (JSON) without repeated string parsing |
| Delta Join | Reduces state for streaming joins by maintaining only latest version per key (requires external infrastructure like Apache Fluss) |
| StreamingMultiJoinOperator | Executes multi-way joins as a single operator, eliminating intermediate materialization |
| ProcessTableFunction (PTF) | Stateful, event-driven logic directly in SQL with per-key state and timers |
| ML_PREDICT function | Call registered ML models on streaming/batch tables from SQL (requires bundling a ModelProvider implementation) |
| Model DDL | Define ML models as first-class catalog objects using `CREATE MODEL` statements |
| Vector Search | SQL API for searching vector databases (requires custom VectorSearchTableSource implementation) |
| C-style escape strings | Supported in SQL |
| QUALIFY clause | Filter window function outputs |

### DataStream API

| Feature | Description |
|---------|-------------|
| FLIP-27 Source API | New unified source interface replacing legacy `SourceFunction` |
| FLIP-143 Sink API | New unified sink interface replacing legacy `SinkFunction` |
| Async Python DataStream | Non-blocking I/O in Python DataStream API using `AsyncFunction` |

### Runtime

- RocksDB upgraded to 8.10.0 with improved I/O performance
- Dedicated serializers for Map, List, Set (replacing Kryo-based serialization)
- Python 3.12 support

## Quick Reference: Breaking Changes

| Category | 1.x | 2.x |
|----------|-----|-----|
| Java version | 8, 11+ | 17+ (21 experimental, not supported in MSF) |
| Python version | 3.8+ | 3.12 (3.8 removed) |
| Scala API | Available | Removed (use Java API from Scala) |
| DataSet API | Available | Removed (use DataStream or Table API) |
| Config file | `flink-conf.yaml` | `config.yaml` (standard YAML) |
| Source API | `SourceFunction` | New Source API only |
| Sink API | `SinkFunction`, `SinkV1` | Sink V2 only |
| Time API | `Time.seconds(n)` | `Duration.ofSeconds(n)` |
| Config API | `config.setInteger("key", val)` | `config.set(ConfigOption, val)` |
| Function open() | `open(Configuration)` | `open(OpenContext)` |
| Logging bridge | `slf4j-log4j12` | `log4j-slf4j-impl` |
| CEP select | Implicit type inference | Explicit `TypeInformation` required |
| Kryo version | 2.x | 5.x (incompatible state format) |
| Collection serializers | Kryo-based | Dedicated serializers (FLINK-34123) |
| TimeCharacteristic | Configurable | Removed (event time default) |
| IterativeStream | Supported | Removed |
| keyBy(int) | Supported | Removed (use KeySelector) |
| Scala case classes state | Kryo v2 serialized | Incompatible (Kryo v5) |
| Java records state | Kryo v2 fallback | Incompatible (Kryo v5) |
| MSF filesystem | Writable | Read-only (except `/tmp`) |
| MSF IMDS | All endpoints | Credential endpoints only |
| CloudFormation upgrade | Delete and recreate | In-place `RuntimeEnvironment` update |

## MSF Behavioral Changes in Flink 2.2

### Metrics Changes

| Change | Details |
|--------|---------|
| `fullRestarts` removed | Use `numRestarts` instead |
| `uptime` deprecated | Use `runningTime` instead |
| `downtime` deprecated | Use `restartingTime`, `cancellingTime`, `failingTime` instead |
| `bytesRequestedPerFetch` removed | Removed in KDS connector v6.0.0 |

### Read-Only Root Filesystem

To improve security, any file write outside of `/tmp` (the default Flink working directory) will fail with `java.io.FileNotFoundException: /{path}/{filename} (Read-only file system)`. This can come from your code directly or from libraries in your dependencies. Override direct filesystem paths to `/tmp/` in your code, and use library configuration overrides to redirect indirect filesystem operations to `/tmp/`.

### Non-Credential IMDS Calls Blocked

Only credential-related IMDS endpoints are allowed (`/latest/meta-data/iam/security-credentials/` and `/latest/dynamic/instance-identity/document`). Applications using other IMDS calls (e.g., `EC2MetadataUtils.getInstanceId()`, `getInstanceType()`, `getLocalHostName()`, `getAvailabilityZone()`) will receive HTTP 4xx errors. Refactor to use environment variables or application configuration instead.

### Programmatic Configuration Handling

MSF Flink 2.2 now throws an exception when you attempt to modify configs not supported by MSF through `env.getConfig().set()` or similar APIs. Supported config changes can still be requested through support tickets.

### Known Issues

**MSF Studio not supported:** Flink 2.2 in MSF does not support Studio (notebook) applications.

**Kinesis EFO resharding bug (FLINK-37648):** Applications using `KinesisStreamsSource` with EFO (SubscribeToShard) may fail when Kinesis streams undergo resharding.

**Kinesis EFO + Sink deadlock (FLINK-34071):** Applications using `KinesisStreamsSource` with EFO together with `KinesisStreamsSink` may experience deadlocks under backpressure, resulting in complete stop of data processing. Recovery requires a force stop and restart.

## Not Supported Features in Managed Service for Apache Flink

The following Flink 2.2 features are not currently supported in Managed Service for Apache Flink as they are still considered experimental in Apache Flink:

- Materialized Tables
- ForSt State Backend (disaggregated state storage)
- Java 21
- Custom metric reporters/telemetry configurations

For details on which features are supported in Managed Service for Apache Flink, refer to  [Apache Flink 2.2 features supported](https://docs.aws.amazon.com/managed-flink/latest/java/flink-2-2.html#flink-2-2-supported-features).

## References

- [Flink 2.0 Release Announcement](https://flink.apache.org/2025/03/24/apache-flink-2.0.0-a-new-era-of-real-time-data-processing/)
- [FLINK-34037](https://issues.apache.org/jira/browse/FLINK-34037) - Serialization configuration changes
- [FLINK-34123](https://issues.apache.org/jira/browse/FLINK-34123) - Collection serializer changes
- [FLIP-398](https://cwiki.apache.org/confluence/display/FLINK/FLIP-398) - Serialization improvements
