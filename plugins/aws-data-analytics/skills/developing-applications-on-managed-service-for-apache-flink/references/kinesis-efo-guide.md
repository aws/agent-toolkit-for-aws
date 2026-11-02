# Enhanced Fan-Out (EFO) Configuration Guide

## Overview

This guide covers Enhanced Fan-Out (EFO) configuration for Kinesis sources in Managed Service for Apache Flink applications, including when to use EFO, source configuration, consumer lifecycle management, parallelism and shard count considerations, auto-scaling interaction, and troubleshooting.

For Kinesis source/sink configuration, authentication, and legacy consumer migration, see [kinesis-connector-guide.md](kinesis-connector-guide.md).

## When to Use EFO vs Standard Polling

Use Enhanced Fan-Out when:

- Multiple consumers read from the same Kinesis stream (EFO gives each consumer dedicated 2 MB/s per shard, vs shared 2 MB/s with polling)
- You need sub-200ms read latency (EFO uses HTTP/2 push, polling has up to 200ms delay per `GetRecords` call)
- Your application cannot tolerate `ReadProvisionedThroughputExceeded` throttling from competing consumers
- You are hitting the 5 `GetRecords` calls per second per shard limit due to multiple consumers or aggressive polling intervals

Standard polling is sufficient when:

- Your Flink application is the only consumer on the stream
- Latency requirements are relaxed (200ms+ acceptable)
- You want to minimize cost (EFO incurs additional per-consumer, per-shard-hour charges)

For polling configuration tuning, the 5 `GetRecords` calls/sec per shard limit, and diagnosing `ReadProvisionedThroughputExceeded`, see the "Polling Configuration and Throttling" section in [kinesis-connector-guide.md](kinesis-connector-guide.md). EFO is the right answer when polling tuning is not enough; the connector guide explains when to choose which.

## EFO Source Configuration

Enable EFO by setting `READER_TYPE` and `EFO_CONSUMER_NAME` in the source configuration:

```java
import org.apache.flink.connector.kinesis.source.KinesisStreamsSource;
import org.apache.flink.connector.kinesis.source.config.KinesisSourceConfigOptions;
import org.apache.flink.configuration.Configuration;

Configuration sourceConfig = new Configuration();
sourceConfig.set(KinesisSourceConfigOptions.READER_TYPE, KinesisSourceConfigOptions.ReaderType.EFO);
sourceConfig.set(KinesisSourceConfigOptions.EFO_CONSUMER_NAME, "my-flink-efo-consumer");

KinesisStreamsSource<String> source = KinesisStreamsSource.<String>builder()
    .setStreamArn("arn:aws:kinesis:us-east-1:123456789012:stream/my-stream")
    .setDeserializationSchema(new SimpleStringSchema())
    .setSourceConfig(sourceConfig)
    .build();

// Recommended: set parallelism >= shard count for optimal per-shard throughput isolation
env.fromSource(source,
        WatermarkStrategy.<String>forBoundedOutOfOrderness(Duration.ofSeconds(5))
            .withIdleness(Duration.ofSeconds(10)),
        "kinesis-efo-source")
    .setParallelism(shardCount)  // match or exceed shard count
    .uid("kinesis-efo-source-uid");
```

The consumer name must be unique per stream but can be reused across different streams. Reusing an existing consumer name on the same stream will terminate the previous subscription.

## Consumer Lifecycle Management

By default (`JOB_MANAGED`), the `KinesisStreamsSource` automatically registers the stream consumer on job start and deregisters on graceful stop. For environments where you want external control:

- `JOB_MANAGED` (default): Flink registers/deregisters the consumer automatically. Preferred for most Managed Service for Apache Flink applications.
- `SELF_MANAGED`: You register the consumer externally via AWS CLI (`aws kinesis register-stream-consumer`) or SDK, then provide the consumer ARN to the job. Use this when multiple jobs share a consumer or when you need to control the consumer lifecycle independently.

## Source Parallelism and Shard Count

Source parallelism should ideally match or exceed the Kinesis shard count when using EFO for optimal throughput. If parallelism is less than the shard count, some subtasks handle multiple shards — this still works but reduces the throughput benefit of EFO. If parallelism exceeds the shard count, idle subtasks will block watermark generation unless `withIdleness()` is configured on the `WatermarkStrategy`.

| Scenario | Parallelism vs Shards | Effect |
|---|---|---|
| Parallelism = shard count | 1:1 mapping | Optimal — each subtask gets dedicated 2 MB/s |
| Parallelism < shard count | Some subtasks handle multiple shards | Works but reduces per-shard throughput isolation |
| Parallelism > shard count | Idle subtasks | Requires `withIdleness()` or watermarks stall |

## EFO Interaction with Managed Service for Apache Flink Auto-Scaling and KPU Allocation

When Managed Service for Apache Flink auto-scaling adjusts KPU count, the total parallelism changes. This affects EFO consumers:

- Scaling up increases parallelism, potentially creating idle subtasks if parallelism exceeds shard count — ensure `withIdleness()` is set
- Scaling down reduces parallelism, causing subtasks to handle more shards — EFO still provides dedicated throughput per shard but each subtask processes more data
- During scaling events, the EFO consumer subscription is re-established automatically; expect brief transient errors in logs (this is normal)
- Set Managed Service for Apache Flink auto-scaling min KPU to ensure parallelism never drops below shard count for optimal EFO throughput

## Troubleshooting EFO

**Consumer registration errors (`LimitExceededException`)**:

- Kinesis limits concurrent consumer registrations to 5 in `CREATING` state per account. If you see this during job startup, the consumer will retry automatically. For persistent failures, check if other applications are registering consumers simultaneously.
- Maximum consumers per stream: 20 (Provisioned/On-demand Standard) or 50 (On-demand Advantage). Verify you haven't hit the limit with `aws kinesis list-stream-consumers`.

**Throughput exceptions (`SubscribeToShard` failures)**:

- Each EFO consumer gets dedicated 2 MB/s per shard. If you see throughput errors, verify the consumer is properly registered (`ACTIVE` status) using `aws kinesis describe-stream-consumer`.
- Transient `SubscribeToShard` errors are expected — subscriptions last 5 minutes and are automatically re-acquired.

**IAM permissions for EFO**:
The Managed Service for Apache Flink application's IAM execution role needs these additional permissions beyond standard Kinesis read access:

```json
{
    "Effect": "Allow",
    "Action": [
        "kinesis:RegisterStreamConsumer",
        "kinesis:DeregisterStreamConsumer",
        "kinesis:DescribeStreamConsumer",
        "kinesis:SubscribeToShard"
    ],
    "Resource": [
        "arn:aws:kinesis:us-east-1:123456789012:stream/my-stream",
        "arn:aws:kinesis:us-east-1:123456789012:stream/my-stream/consumer/*"
    ]
}
```

Note the consumer resource ARN (`stream/*/consumer/*`) — `SubscribeToShard` and `DescribeStreamConsumer` require permissions on the consumer resource, not just the stream.

**Retry strategy tuning**:
If `DescribeStreamConsumer` calls fail during startup (common when the consumer was just registered and is still in `CREATING` state), tune the dedicated retry strategy:

```java
sourceConfig.set(KinesisSourceConfigOptions.EFO_DESCRIBE_CONSUMER_RETRY_STRATEGY_MAX_ATTEMPTS, 30);
sourceConfig.set(KinesisSourceConfigOptions.EFO_DESCRIBE_CONSUMER_RETRY_STRATEGY_MIN_DELAY, Duration.ofSeconds(2));
sourceConfig.set(KinesisSourceConfigOptions.EFO_DESCRIBE_CONSUMER_RETRY_STRATEGY_MAX_DELAY, Duration.ofSeconds(10));
```
