# Kinesis Connector Guide

This guide covers Kinesis connector configuration for Amazon Managed Service for Apache Flink applications.

## Maven Dependencies

**CRITICAL:** Use the correct Kinesis connector dependency from the official Apache Flink project:

```xml
<dependency>
    <groupId>org.apache.flink</groupId>
    <artifactId>flink-connector-aws-kinesis-streams</artifactId>
    <version>${kinesis-streams.version}</version>
</dependency>
```

Where `kinesis-streams.version` should match your Flink version (e.g., `5.1.0-1.20` for Flink 1.20, `6.0.0-2.0` for Flink 2.2). See `dependency-management.md` for the full version mapping.

## Kinesis Source Configuration

When creating a Kinesis source, use the `KinesisStreamsSource` builder pattern. This API is the same for both Flink 1.20 and 2.2.

### Correct API Pattern

```java
import org.apache.flink.configuration.Configuration;
import org.apache.flink.connector.kinesis.source.config.KinesisSourceConfigOptions;

Map<String, Properties> applicationProperties = loadApplicationProperties(env);
Properties inputConfig = applicationProperties.get("input.kinesis.config");
Map<String, String> configMap = new HashMap<>();
inputConfig.forEach((k, v) -> configMap.put(k.toString(), v.toString()));
Configuration sourceConfig = Configuration.fromMap(configMap);
String inputStreamArn = inputConfig.getProperty("stream.arn");

KinesisStreamsSource<Event> source = KinesisStreamsSource.<Event>builder()
    .setStreamArn(inputStreamArn)
    .setDeserializationSchema(new EventDeserializationSchema())
    .setSourceConfig(sourceConfig)
    .build();

DataStream<Event> events = env
        .fromSource(source, 
                    WatermarkStrategy.<Event>forBoundedOutOfOrderness(Duration.ofSeconds(5))
                            .withTimestampAssigner((event, timestamp) -> event.getTimestamp())
                            .withIdleness(Duration.ofSeconds(10)),  // CRITICAL for low-throughput streams
                    "kinesis-source",
                    org.apache.flink.api.common.typeinfo.TypeInformation.of(Event.class))
        .name("kinesis-source")
        .uid("kinesis-source-uid")
        .filter(event -> event != null)
        .name("filter-null-events")
        .uid("filter-null-events-uid");
```

### Key Configuration Methods

- `.setStreamArn(String)` - Set the stream ARN (preferred over stream name)
- `.setDeserializationSchema(DeserializationSchema<T>)` - Set how to deserialize records
- `.setSourceConfig(Configuration)` - Set Kinesis client configuration
- `.build()` - Build the source

## Kinesis Sink Configuration

For Kinesis sinks, use the `KinesisStreamsSink` builder:

```java
Properties outputConfig = applicationProperties.get("output.kinesis.config");
String outputStreamArn = outputConfig.getProperty("stream.arn");

KinesisStreamsSink<Event> sink = KinesisStreamsSink.<Event>builder()
    .setStreamArn(outputStreamArn)
    .setSerializationSchema(new EventSerializationSchema())
    .setPartitionKeyGenerator(event -> String.valueOf(event.hashCode()))
    .setKinesisClientProperties(outputConfig)
    .build();

events.sinkTo(sink)
        .name("kinesis-sink")
        .uid("kinesis-sink-uid");
```

### Key Sink Methods

- `.setStreamArn(String)` - Set the destination stream ARN
- `.setSerializationSchema(SerializationSchema<T>)` - Set how to serialize records
- `.setPartitionKeyGenerator(PartitionKeyGenerator<T>)` - Set partition key logic
- `.build()` - Build the sink

## Polling Configuration and Throttling

The Kinesis `GetRecords` API has a hard limit of 5 calls per second per shard, shared across all consumers reading from that shard. The Flink Kinesis connector's default polling behavior can be aggressive and lead to `ReadProvisionedThroughputExceeded` or `LimitExceededException` errors, especially when multiple consumers share a stream or when polling intervals are too short.

**Key polling configuration options** (see [KinesisSourceConfigOptions Javadoc](https://www.javadoc.io/static/org.apache.flink/flink-connector-aws-kinesis-streams/6.0.0-2.0/org/apache/flink/connector/kinesis/source/config/KinesisSourceConfigOptions.html)):

| Config Option | Description | Default | Recommendation |
|---|---|---|---|
| `SHARD_GET_RECORDS_MAX` | Max records per `GetRecords` call | 10,000 (but Kinesis limit is 10,000 records / 10 MB per call; throttling occurs at 1,000 records for some stream configurations) | Lower to 1,000 or less if seeing throttling |
| `READER_EMPTY_RECORDS_FETCH_INTERVAL` | Interval between polling calls when no records are returned | 200ms (5 calls/sec) | Increase to 500ms–1s if sharing shards with other consumers or if the default rate exceeds the per-shard limit |
| `SHARD_DISCOVERY_INTERVAL` | Interval for discovering new shards via `ListShards` | 10s | Increase if `ListShards` rate limiting is observed |

**Tuning polling to avoid throttling:**

```java
Configuration sourceConfig = new Configuration();

// Reduce max records per GetRecords call to stay within Kinesis limits
sourceConfig.set(KinesisSourceConfigOptions.SHARD_GET_RECORDS_MAX, 1000);

// Increase polling interval to reduce GetRecords call rate
// Default is 200ms (5 calls/sec) — increase if sharing shards with other consumers
sourceConfig.set(KinesisSourceConfigOptions.READER_EMPTY_RECORDS_FETCH_INTERVAL, Duration.ofMillis(500));

KinesisStreamsSource<String> source = KinesisStreamsSource.<String>builder()
    .setStreamArn("arn:aws:kinesis:us-east-1:123456789012:stream/my-stream")
    .setDeserializationSchema(new SimpleStringSchema())
    .setSourceConfig(sourceConfig)
    .build();
```

**When polling tuning is sufficient (vs switching to EFO):**

- Single consumer reading from the stream: tune polling — EFO is unnecessary cost since there is no shared-quota contention.
- 2+ consumers and still seeing `ReadProvisionedThroughputExceeded` after raising `READER_EMPTY_RECORDS_FETCH_INTERVAL`: switch to EFO. Tuning polling intervals across multiple consumers is fragile; EFO eliminates the shared quota entirely.
- Polling interval increase introduces unacceptable latency: switch to EFO (HTTP/2 push has no polling delay).
- You expect to scale to more consumers later: prefer EFO upfront.

See [kinesis-efo-guide.md](kinesis-efo-guide.md) for EFO configuration, consumer lifecycle, and the full when-to-use-EFO checklist.

**Diagnosing polling throttling:**

- Check CloudWatch metric `ReadProvisionedThroughputExceeded` on the Kinesis stream — sustained values > 0 indicate throttling.
- Check Managed Service for Apache Flink CloudWatch logs for `LimitExceededException` errors.
- Monitor `GetRecords.Latency` and `GetRecords.Success` metrics to correlate throttling with read performance.

## Migrating from Legacy Kinesis Consumer to KinesisStreamsSource

**CRITICAL for Flink 2.x upgrades:** KDS connector versions below 5.0 have state that is incompatible with the Flink 2.2 connector (v6.0.0-2.0). You must migrate to connector v5.0+ on Flink 1.x before upgrading to Flink 2.x. See the [AWS blog post on the Kinesis source connector](https://aws.amazon.com/blogs/big-data/introducing-the-new-amazon-kinesis-source-connector-for-apache-flink/) for full details.

The legacy `FlinkKinesisConsumer` uses the removed `SourceFunction` interface and will not work with Flink 2.x. The `KinesisStreamsSource` uses the FLIP-27 Source API.

### Migration Paths

**DataStream API with operator UIDs defined:**

1. Update dependencies: replace `flink-connector-kinesis` with `flink-connector-aws-kinesis-streams` v5.0.0+
2. Replace `FlinkKinesisConsumer` with `KinesisStreamsSource` builder pattern
3. Change the UID of the source operator to a new string (this selectively resets source state while preserving all other operator state)
4. Configure starting position with `AT_TIMESTAMP` set to just before deployment time
5. Deploy with `allowNonRestoredState = true`

**Table API/SQL or DataStream without operator UIDs:**

1. Update dependencies and code as above
2. Deploy with `SKIP_RESTORE_FROM_SNAPSHOT` since Flink cannot map old operator state to new operators
3. After the application is running, switch back to `RESTORE_FROM_LATEST_SNAPSHOT` for future restarts

### Key Differences from Legacy Connector

| Feature | Legacy `FlinkKinesisConsumer` | New `KinesisStreamsSource` |
|---------|-------------------------------|---------------------------|
| Interface | `SourceFunction` (removed in 2.x) | FLIP-27 Source API |
| Stream identifier | Stream name | Stream ARN (cross-region/account support) |
| Watermarks | Implicit defaults | Explicit `WatermarkStrategy` required |
| Ordering on reshard | Not guaranteed | Guaranteed via parent-child shard lineage |
| Shard assigner | Even shard distribution | Uniform partition-key distribution |
| AWS SDK | v1 | v2 (non-blocking I/O) |
| JAR size | ~60 MB | ~200 KB |
| KCL/KPL dependency | Included | Removed (no built-in KPL de-aggregation) |

### State Compatibility Warning

The saved state from `FlinkKinesisConsumer` is not compatible with `KinesisStreamsSource`. You cannot restore source position from a snapshot taken with the legacy connector. Plan for either selective state reset (with UIDs) or full state reset (without UIDs) as described above.

## Authentication

In Managed Service for Apache Flink, authentication to Kinesis is handled automatically via the application's IAM execution role. No explicit credentials configuration is needed in the code.
