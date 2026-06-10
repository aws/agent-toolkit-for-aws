# Job Graph Anti-Patterns Guide

## Overview

This guide covers common job graph anti-patterns for Managed Service for Apache Flink applications: data skew detection and mitigation, the monolith job anti-pattern, and the high fan-out anti-pattern. Use it when diagnosing performance problems or deciding whether to split a large application.

For operator chaining, operator-to-task-slot mapping, and task slot overload guidance, see [job-graph-architecture.md](job-graph-architecture.md).

## Data Skew Detection and Mitigation

### Identifying Skew via Flink Web UI

Data skew occurs when some subtasks of a keyed operator receive significantly more data than others. This causes the overloaded subtasks to become bottlenecks while other subtasks sit idle.

**How to detect skew in the Flink Web UI:**

1. Open the running job → click on a keyed operator (any operator after a `keyBy`)
2. Select the "Subtasks" tab
3. Compare these columns across subtasks:
   - `Bytes Received`: should be roughly equal across subtasks
   - `Records Received`: should be roughly equal across subtasks
   - `Busy Time (ms/s)`: skewed subtasks show much higher values
4. If the max value is more than 3× the median, the operator has significant skew

A subtask processing 10× more records than its peers will become the throughput bottleneck for the entire operator, regardless of how many other subtasks are idle.

### Programmatic Detection

For automated checks (alarms, scheduled diagnostics), pull the same per-subtask data without the UI:

- **Flink Dashboard REST API** — `/jobs/$JOB_ID/vertices/$VERTEX_ID/subtasks` returns the same `read-records` / `read-bytes` / `busyTimeMsPerSecond` per-subtask values shown in the UI. See the table in [first-fault-isolation.md](first-fault-isolation.md) for related per-vertex endpoints (backpressure, watermarks). Useful for scripted skew detection where the rule of thumb is `max / median > 3`.
- **CloudWatch metrics at the `PARALLELISM` dimension level** — set `MonitoringConfiguration.MetricsLevel` to `PARALLELISM` (or `OPERATOR`) so per-subtask metrics flow to CloudWatch with a `subtaskIndex` dimension. You can then alarm on per-subtask `numRecordsInPerSecond` variance. Note that higher metric levels increase CloudWatch metric cardinality and cost — see the metric-level guidance in [monitoring-and-metrics.md](monitoring-and-metrics.md) before enabling on a high-parallelism job.

Confirm and quantify skew before changing parallelism. Lowering parallelism is a valid mitigation only after the per-subtask numbers above show that most subtasks are idle while a few are saturated; doing it preemptively can mask the underlying hot-key problem.

### Diagnostic Checklist for Uneven Processing

1. **Key distribution**: Check for "hot" keys concentrating traffic on a few subtasks. Query source data for key cardinality and frequency distribution.
2. **Partition assignment**: Check if Kinesis shards/Kafka partitions are evenly sized. Uneven source partitions propagate imbalance downstream.
3. **Hash collisions**: Poor `hashCode()` implementations can map many distinct keys to the same subtask. Verify custom key types distribute evenly.
4. **Key cardinality vs parallelism**: Ensure key cardinality is at least 10× the operator parallelism for reasonable distribution.
5. **Temporal skew**: Some keys may be hot only during certain time windows. Check if skew is sustained or periodic.

### Warning: High Core Counts + Kryo Serialization + Data Skew

Running Managed Service for Apache Flink applications with high KPU counts (e.g., 64+ KPUs) combined with Kryo serialization and data skew creates a compounding performance problem:

- **Kryo serialization** is slower and produces larger serialized objects than POJO or Avro serialization. This increases network transfer time during shuffles (`keyBy`, `rebalance`).
- **Data skew** concentrates traffic on a few subtasks, which must deserialize a disproportionate share of Kryo-encoded records.
- **High parallelism** amplifies the shuffle: with 64 subtasks, each record after a `keyBy` is serialized, sent over the network, and deserialized. The skewed subtasks become CPU-bound on Kryo deserialization.

**Remediation:**

- Switch from Kryo to POJO serialization by ensuring your data classes follow Flink's POJO rules (public class, public no-arg constructor, public fields or getters/setters). Check logs for `"Class ... cannot be used as a POJO type"` to find Kryo fallbacks.
- If POJO is not feasible, use Avro serialization with a defined schema.
- Address the skew itself: add a salt/prefix to hot keys to spread them across subtasks, then aggregate in a second pass.
- Only after skew is confirmed and quantified per the steps above, consider reducing parallelism for the skewed operator if most subtasks are idle while a few are saturated. Do not lower parallelism preemptively — it masks the underlying hot-key problem and can hurt unrelated operators in the same job.

## Monolith Job Anti-Pattern

### Indicators of a Monolith Job

A monolith Flink job tries to do too much in a single application. Watch for these indicators:

- **Excessive operator count**: More than 100–150 distinct operators in the job graph. Each operator adds state management, checkpoint overhead, and metric cardinality.
- **Unrelated business logic paths**: The job reads from multiple sources and processes them through independent pipelines that never join or share state. These are separate applications forced into one deployment.
- **Parallelism exceeding 100 per KPU**: When the application needs very high parallelism to keep up, it often means multiple workloads with different throughput requirements are bundled together.
- **Mixed SLA requirements**: Part of the job needs sub-second latency while another part is a batch-like hourly aggregation. These cannot be optimally tuned in a single application.
- **Frequent full-job restarts for partial changes**: A code change to one processing path requires restarting the entire application, including unrelated paths that lose their state or must restore from checkpoint.

### Criteria for Splitting

Split a monolith job when any of these conditions are met:

1. **Independent processing paths**: Two or more pipelines in the job share no state and no data exchange. They are logically separate applications.
2. **Different scaling requirements**: One path needs 32 KPUs to handle peak traffic while another needs only 4. Bundling them wastes resources on the smaller path or under-provisions the larger one.
3. **Different SLA requirements**: One path has a strict latency SLA (< 1 second end-to-end) while another is latency-tolerant (minutes). Checkpoint intervals, parallelism, and resource allocation cannot be optimized for both simultaneously.
4. **Blast radius reduction**: A failure or bug in one processing path should not take down unrelated paths. Separate applications isolate failures.
5. **Independent deployment cycles**: Different teams own different processing paths and need to deploy changes independently.

### Splitting Patterns

**Pattern: Shared Kinesis stream as intermediate topic** — Split the monolith into a producer job and consumer jobs connected by a Kinesis Data Stream. Each job scales independently; if the consumer fails, the producer continues and the consumer replays on recovery.

**Pattern: Idempotent sinks for exactly-once across jobs** — Each job maintains its own checkpoint. Use idempotent sinks (upsert to DynamoDB, deduplication keys) to handle duplicates at the boundary. The intermediate stream provides at-least-once delivery.

### Trade-Offs of Job Splitting

| Factor | Monolith | Split Jobs |
|--------|----------|------------|
| Blast radius | One failure affects everything | Failures isolated |
| Latency | Lower (no intermediate hop) | Higher (extra serialization) |
| Scaling | One-size-fits-all KPU allocation | Each job sized independently |
| Deployment | Full restart for any change | Only affected job restarts |
| Cost | Single application | Multiple applications + intermediate stream costs |

**General guidance**: Split when the monolith causes operational pain (frequent restarts, resource waste, mixed SLAs). For small applications with < 50 operators and uniform requirements, a single job is simpler.

## High Fan-Out Anti-Pattern

### The One-Sink-Per-Shard/Partition Pattern

A common mistake is creating a separate sink operator for each output shard or partition. For example, a developer routing events to 64 Kinesis shards might create 64 individual `KinesisStreamsSink` instances, each writing to a specific shard:

```java
// AVOID: Creating one sink per shard
for (int i = 0; i < 64; i++) {
    final int shardIndex = i;
    events.filter(e -> e.getShardKey() % 64 == shardIndex)
          .sinkTo(createKinesisSink("output-stream"))
          .uid("sink-shard-" + shardIndex);
}
```

This creates 64 sink operators in the job graph, each with its own parallelism, state, checkpoint overhead, and connection pool. The job graph balloons in complexity.

### Resource and Performance Consequences

Excessive sink operators cause cascading problems: thread exhaustion (each sink has its own thread pool), connection pool saturation (hundreds of concurrent connections per TaskManager), checkpoint size inflation (each sink maintains its own state), metric cardinality explosion (64 sinks = 64× the metrics), and operator-to-task-slot overload (pushing toward the >200 operator threshold discussed in [job-graph-architecture.md](job-graph-architecture.md)).

### Alternative Patterns

**Use a single partitioned sink with a partition key generator:**

```java
// RECOMMENDED: Single sink with built-in partitioning
KinesisStreamsSink<Event> sink = KinesisStreamsSink.<Event>builder()
    .setStreamName("output-stream")
    .setSerializationSchema(new EventSerializationSchema())
    .setPartitionKeyGenerator(event -> event.getPartitionKey())
    .build();

events.sinkTo(sink)
    .setParallelism(16)  // Match KPU count, not shard count
    .uid("kinesis-sink-uid");
```

The Kinesis sink handles partitioning internally using the partition key generator. One sink operator distributes records across all shards without creating separate operators per shard. **Set the parallelism to match your KPU count, not your shard/partition count** — the sink will still write to every shard regardless of operator parallelism, because Kinesis routes by partition-key hash, not by sender.

The same principle applies to Kafka sinks — use a single `KafkaSink` with a `KafkaRecordSerializationSchema` that sets the partition (or relies on the configured `Partitioner`), rather than creating one sink per partition. Same applies to JDBC, DynamoDB, and most other Flink sinks: one sink + a routing function inside the sink, not one sink per output bucket.

**Stay within the rule-of-thumb upper bound of 2–4 sink operators per KPU** — see the table in the next section for sizing. Crossing this number is a strong sign you're hitting the high fan-out anti-pattern even if no single sink is per-shard.

### Maximum Recommended Sink Count

**Rule of thumb: no more than 2–4 sink operators per KPU.**

| KPU Count | Max Recommended Sinks | Reasoning |
|-----------|----------------------|-----------|
| 4 | 8–16 | Each sink adds connection overhead and checkpoint state |
| 16 | 32–64 | Beyond this, connection pool and thread pressure becomes significant |
| 32 | 64–128 | At this scale, prefer fewer sinks with built-in partitioning |

If the application genuinely needs to write to many distinct destinations (different streams, different tables), consider:

- Using a single sink with a routing function that directs records to different targets based on record content
- Splitting into multiple jobs, each responsible for a subset of destinations (see Monolith Job Anti-Pattern above)
- Using side outputs to route records to a small number of categorized sinks rather than one per destination
