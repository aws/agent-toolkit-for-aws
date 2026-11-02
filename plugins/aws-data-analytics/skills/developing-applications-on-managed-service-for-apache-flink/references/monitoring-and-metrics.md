# Monitoring and Metrics Guide

## Overview

This guide covers CloudWatch metrics analysis and custom metrics emission for Amazon Managed Service for Apache Flink applications. Use it when setting up monitoring for a new application, interpreting metric behavior on an existing one, or adding application-specific business metrics via the Flink MetricGroup API.

## Key CloudWatch Metrics for Managed Service for Apache Flink

### Core Metrics Reference

Managed Service for Apache Flink publishes metrics to CloudWatch under the `AWS/KinesisAnalytics` namespace. The following table lists the key metrics, what they measure, and expected healthy ranges for a well-tuned application.

| Metric | Unit | Description | Level | Healthy Range | Notes |
|--------|------|-------------|-------|---------------|-------|
| `cpuUtilization` | Percentage | Percentage of CPU used per TaskManager JVM process. Managed Service for Apache Flink publishes one sample per TaskManager per reporting interval. | Application | 20–70% (per TM) | Use `Maximum` for hottest TaskManager, `Average` for mean across all. Only accounts for TaskManager JVM CPU, not other container processes. Sustained > 70% indicates CPU-bound; consider adding KPUs. |
| `containerCPUUtilization` | Percentage | CPU utilization across task manager containers. Publishes samples per TaskManager per minute. | Application | 20–75% (per container) | More complete than `cpuUtilization` — includes all processes in the container, not just the JVM. Use this to detect CPU exhaustion at the container level. |
| `heapMemoryUtilization` | Percentage | JVM heap memory used per TaskManager. Managed Service for Apache Flink publishes one sample per TaskManager per reporting interval. | Application | 30–75% (per TM) | Use `Maximum` for hottest TaskManager, `Average` for mean. Only accounts for TaskManager JVM heap. Graduated thresholds: healthy ≤ 75%; sustained > 80% warrants investigation and scale-up; > 90% is critical (alarm). See [Recommended Alarms](#recommended-alarms-and-thresholds). |
| `containerMemoryUtilization` | Percentage | Memory utilization across task manager containers. Publishes 2× samples per TaskManager per minute. | Application | Below 85% | More complete than `heapMemoryUtilization` — includes working set memory. Better tracker of total memory exhaustion; upon exhaustion, results in OOM for the TaskManager pod. |
| `containerDiskUtilization` | Percentage | Disk utilization across task manager containers. Publishes 2× samples per TaskManager per minute. | Application | Below 80% | Represents utilization of the filesystem on which the container root volume is set up. |
| `oldGenerationGCCount` | Count | Total number of old-generation (full) GC operations across all task managers | Application | < 2 per minute | Frequent full GCs indicate heap pressure or memory leaks. Monitor `RATE(oldGenerationGCCount)` for trend. |
| `oldGenerationGCTime` | Milliseconds | Total time spent in old-generation GC operations | Application | < 500 ms per minute | High values cause latency spikes and checkpoint delays. AWS recommends alarming on `(oldGenerationGCTime * 100) / 60000` as a percentage of wall-clock time. |
| `threadsCount` | Count | Total number of live JVM threads used by the application | Application | Stable, proportional to parallelism | Not the same as application parallelism. Sudden increases may indicate thread leaks from custom connectors. |
| `lastCheckpointDuration` | Milliseconds | Time to complete the most recent checkpoint | Application | < 50% of checkpoint interval | Approaching the interval signals checkpoint pressure. Monitor `RATE(lastCheckpointDuration)` for trends. |
| `lastCheckpointSize` | Bytes | Total size of the most recent checkpoint | Application | Stable or slowly growing | Rapid growth indicates unbounded state accumulation. Monitor `RATE(lastCheckpointSize)` for trends. |
| `numberOfFailedCheckpoints` | Count | Cumulative count of failed checkpoints | Application | 0 | Any non-zero value warrants investigation. AWS recommends monitoring `RATE(numberOfFailedCheckpoints)` to alarm on the gradient, not absolute values. |
| `downtime` | Milliseconds | Time the application has been in a failing/recovering state | Application | 0 | **Flink 2.2: Deprecated** — use `restartingTime`, `cancellingTime`, `failingTime` instead. Returns 0 for running jobs, -1 for completed jobs. Any other value means the job is not running. |
| `uptime` | Milliseconds | Time since the last successful restart | Application | Continuously increasing | **Flink 2.2: Deprecated** — use `runningTime` instead. Returns -1 for completed jobs. Resets indicate restarts; frequent resets signal instability. |
| `fullRestarts` | Count | Total number of full restarts since job submission | Application | Low and stable | **Flink 2.2: Removed** — use `numRestarts` instead. Does not measure fine-grained restarts. Restarts can occur during internal Managed Service for Apache Flink maintenance; higher than normal indicates a problem. |
| `KPUs` | Count | Total number of KPUs used by the application | Application | N/A | Receives one sample per billing period (one hour). Use `MAX` or `AVG` over a period of at least 1 hour. Includes the orchestration KPU. |

#### Throughput Metrics

These metrics are available at Application, Operator, Task, and Parallelism levels. They have a special reporting behavior: Managed Service for Apache Flink takes **4 metric snapshots per minute**. When using the `SUM` statistic over a period, you must divide by 4 to get the correct value (metric math: `m1/4`).

| Metric | Unit | Description | Level | Notes |
|--------|------|-------------|-------|-------|
| `numRecordsIn` | Count | Total number of records received | Application, Operator, Task, Parallelism | When using `SUM` statistic, apply metric math `m1/4` because Managed Service for Apache Flink takes 4 snapshots per minute. |
| `numRecordsInPerSecond` | Count/Second | Records received per second | Application, Operator, Task, Parallelism | Same 4-snapshot-per-minute behavior — use `m1/4` with `SUM`. Healthy when matching expected input rate; drops indicate source issues or backpressure. |
| `numRecordsOut` | Count | Total number of records emitted | Application, Operator, Task, Parallelism | Same `m1/4` math applies with `SUM`. |
| `numRecordsOutPerSecond` | Count/Second | Records emitted per second | Application, Operator, Task, Parallelism | Same `m1/4` math applies with `SUM`. AWS recommends alarming when this falls below a minimum threshold. |
| `numLateRecordsDropped` | Count | Records dropped due to arriving late | Application, Operator, Task, Parallelism | Same `m1/4` math applies with `SUM`. |

**Important**: Select the metric at the correct Level. If you're tracking the metric for an Operator, you need to select the corresponding operator-level metric, not the application-level one.

#### Operator Performance Metrics

These metrics are available at Task, Operator, and Parallelism levels. They are available for Flink version 1.13 and later.

| Metric | Unit | Description | Level | Healthy Range | Notes |
|--------|------|-------------|-------|---------------|-------|
| `backPressuredTimeMsPerSecond` | Milliseconds | Time an operator spends backpressured per second | Task, Operator, Parallelism | < 100 ms/s | Sustained > 100 ms/s means a downstream operator cannot keep up. Available for Flink 1.13+. |
| `busyTimeMsPerSecond` | Milliseconds | Time an operator spends processing records per second | Task, Operator, Parallelism | < 800 ms/s | Approaching 1000 means the operator is fully saturated. Can be NaN if the value could not be calculated. Available for Flink 1.13+. |
| `idleTimeMsPerSecond` | Milliseconds | Time an operator is idle (no data to process) per second | Task, Operator, Parallelism | Varies by workload | Idle time excludes backpressured time — if the task is backpressured it is not idle. Available for Flink 1.13+. |

#### Watermark Metrics

| Metric | Unit | Description | Level | Notes |
|--------|------|-------------|-------|-------|
| `currentInputWatermark` | Milliseconds | The last watermark this application/operator/task/thread has received (epoch ms) | Application, Operator, Task, Parallelism | Large lag from wall-clock time indicates late data or watermark misconfiguration. Only emitted for dimensions with two inputs; represents the minimum of the last received watermarks. |
| `currentOutputWatermark` | Milliseconds | The last watermark this application/operator/task/thread has emitted (epoch ms) | Application, Operator, Task, Parallelism | AWS recommends monitoring `currentOutputWatermark - currentInputWatermark` to detect watermark drift. |

#### Managed Memory Metrics (Flink 1.13+)

These metrics relate to memory managed by Flink outside the Java heap, used for the RocksDB state backend.

| Metric | Unit | Description | Level | Notes |
|--------|------|-------------|-------|-------|
| `managedMemoryUsed` | Bytes | Amount of managed memory currently used | Application, Operator, Task, Parallelism | Available for Flink 1.13+. |
| `managedMemoryTotal` | Bytes | Total amount of managed memory | Application, Operator, Task, Parallelism | Available for Flink 1.13+. |
| `managedMemoryUtilization` | Percentage | Derived by `managedMemoryUsed / managedMemoryTotal` | Application, Operator, Task, Parallelism | Available for Flink 1.13+. Important for RocksDB state backend users. |

#### Kinesis Source Metrics

| Metric | Unit | Description | Level | Notes |
|--------|------|-------------|-------|-------|
| `millisBehindLatest` | Milliseconds | Consumer lag — how far behind the head of the stream the consumer is | Application (for Stream), Parallelism (for ShardId) | A value of 0 means caught up. A value of -1 means not yet reported. Growing lag means the application cannot keep up with input rate. Healthy: < 60,000 (1 min). |
| `bytesRequestedPerFetch` | Bytes | Bytes requested in a single call to `getRecords` | Application (for Stream), Parallelism (for ShardId) | **Flink 2.2: Removed** in KDS connector v6.0.0-2.0. Only available with legacy connector versions. |

#### Kafka Source Metrics

| Metric | Unit | Description | Level | Notes |
|--------|------|-------------|-------|-------|
| `records_lag_max` | Count | Maximum lag in number of records for any partition in this window | Application, Operator, Task, Parallelism | Use this for Kafka sources the same way `millisBehindLatest` is used for Kinesis sources. |
| `currentoffsets` | N/A | Consumer's current read offset, per partition | Application (for Topic), Parallelism (for PartitionId) | |
| `committedoffsets` | N/A | Last successfully committed offsets to Kafka, per partition | Application (for Topic), Parallelism (for PartitionId) | |
| `commitsFailed` | N/A | Total number of offset commit failures to Kafka | Application, Operator, Task, Parallelism | Commit failure does not affect integrity of Flink's checkpointed partition offsets. |
| `commitsSucceeded` | N/A | Total number of successful offset commits to Kafka | Application, Operator, Task, Parallelism | |
| `bytes_consumed_rate` | Bytes | Average number of bytes consumed per second for a topic | Application, Operator, Task, Parallelism | |

### How cpuUtilization and heapMemoryUtilization Are Reported

A common source of confusion: these metrics are **not** reported as a single summed value across all TaskManagers. Instead, Managed Service for Apache Flink publishes **one sample per TaskManager** per reporting interval.

With 5 TaskManagers, CloudWatch receives 5 data points per interval. CloudWatch statistics then work naturally:

- `Average` = mean utilization across all TaskManagers
- `Maximum` = the hottest (most utilized) TaskManager
- `Minimum` = the least utilized TaskManager

**You do not need to divide by KPU count.** Use `Maximum` to find the bottleneck TaskManager, or `Average` for overall health. The AWS docs recommend using `Maximum` for alarm thresholds.

**Note**: `containerCPUUtilization` and `containerMemoryUtilization` publish **2× the number of samples** per TaskManager per minute (2 × number of TaskManagers).

### Metric Dimensions

Managed Service for Apache Flink metrics are available at four dimension levels:

| Dimension | Granularity | When to Use |
|-----------|-------------|-------------|
| **Application** | Entire Managed Service for Apache Flink application | Default for dashboards and alarms. Provides a single view of overall application health. Use for `cpuUtilization`, `heapMemoryUtilization`, `downtime`, `uptime`, checkpoint metrics, and container metrics. |
| **Task** | Per-task (group of chained operators) | Use when diagnosing which part of the pipeline is the bottleneck. `backPressuredTimeMsPerSecond` and `busyTimeMsPerSecond` at the task level reveal which operator chain is overloaded. |
| **Operator** | Per-operator (individual operator within a task) | Use for fine-grained debugging of specific operators. `numRecordsInPerSecond` and `numRecordsOutPerSecond` at the operator level help identify data skew or filtering ratios. |
| **Parallelism** | Per-subtask (individual parallel instance) | Most granular level. Use for diagnosing data skew across subtasks. Kinesis `millisBehindLatest` uses this for per-ShardId metrics. Kafka offsets use this for per-PartitionId metrics. |

**Dimension selection guidance:**

- Start with Application-level metrics for dashboards and alarms — they give the overall health picture with minimal cardinality.
- Drop to Task-level when Application-level metrics show a problem (e.g., high backpressure) and you need to identify which task chain is responsible.
- Use Operator-level for targeted debugging of specific operators.
- Use Parallelism-level only for diagnosing data skew or per-shard/partition analysis, not for persistent dashboards.

### Warning: Task-Level Metrics and High Cardinality

Task-level, operator-level, and parallelism-level metrics produce one CloudWatch metric per subtask per metric name. The total metric count is:

```
metric_count = num_metrics × total_parallelism × num_operators
```

With high parallelism and ParallelismPerKPU > 1, this can produce thousands of individual CloudWatch metrics, leading to:

- **High CloudWatch costs**: CloudWatch charges per metric per month. An application with Parallelism = 64 (32 KPUs × ParallelismPerKPU = 2) × 50 operator-level metrics = 3,200 custom metrics.
- **Dashboard performance degradation**: CloudWatch dashboards with thousands of metrics load slowly and become difficult to navigate.
- **Alarm limits**: CloudWatch has per-account alarm limits. Task-level alarms at high parallelism can consume a significant portion of the quota.

**Recommendation**: Use Application-level dimensions for all persistent alarms and dashboards. Reserve Task-level, Operator-level, and Parallelism-level dimensions for temporary diagnostic queries using CloudWatch Metrics Insights or the Flink Web UI, which provides subtask-level metrics without CloudWatch cardinality costs.

## Recommended Alarms and Thresholds

### Critical Metric Alarms

Set up CloudWatch alarms for these metrics on every Managed Service for Apache Flink production application. All alarms should use the Application dimension unless otherwise noted. These align with the [AWS recommended alarms](https://docs.aws.amazon.com/managed-flink/latest/java/monitoring-metrics-alarms.html).

| Metric | Statistic | Period | Threshold | Alarm Condition | Severity |
|--------|-----------|--------|-----------|-----------------|----------|
| `downtime` (Flink 1.x) or `restartingTime` / `cancellingTime` / `failingTime` (Flink 2.2) | Average | 1 minute | > 0 | Any non-zero value means the job is not running. Use "1 out of 1" evaluation — any downtime is immediately actionable. | Critical |
| `RATE(numberOfFailedCheckpoints)` | Average | 5 minutes | > 0 | Monitor the rate (gradient), not absolute values. A non-zero rate means checkpoints are actively failing. | High |
| `Operator.numRecordsOutPerSecond` | Average | 5 minutes | < minimum expected throughput | Falling below this threshold indicates the application isn't making expected progress on input data. | High |
| `lastCheckpointDuration` | Maximum | 5 minutes | > 50% of checkpoint interval | Checkpoint taking too long; risk of queuing and timeout. Also monitor `RATE(lastCheckpointDuration)` for trends. | High |
| `lastCheckpointSize` | Maximum | 5 minutes | > maximum expected size | Continuously increasing size indicates unbounded state accumulation. Also monitor `RATE(lastCheckpointSize)`. | High |
| Memory utilization (`heapMemoryUtilization` and `containerMemoryUtilization`) | Maximum | 5 minutes | heap > 90% / container > 85% |  **`heapMemoryUtilization`** is what AWS officially recommends in [Use CloudWatch Alarms with Amazon Managed Service for Apache Flink](https://docs.aws.amazon.com/managed-flink/latest/java/monitoring-metrics-alarms.html); threshold 90% Maximum, "3 out of 3 consecutive periods". Sees only the TaskManager JVM heap. **`containerMemoryUtilization`** catches container-level OOMs that heap misses (off-heap RocksDB state, native libraries, JVM overhead) — per the AWS [Metrics and dimensions](https://docs.aws.amazon.com/managed-flink/latest/java/metrics-dimensions.html) page, this is "a better tracker of total memory exhaustion." Use container as your primary memory alarm if your application is stateful with RocksDB. Either alone is acceptable; both is recommended for stateful apps. | High |
| `cpuUtilization` | Maximum | 5 minutes | > 80% | AWS recommends 80% threshold using `Maximum` statistic. Use "3 out of 3 consecutive periods" evaluation. | High |
| `records_lag_max` or `millisBehindLatest` | Maximum | 5 minutes | > maximum expected latency | Use `records_lag_max` for Kafka sources, `millisBehindLatest` for Kinesis sources. Rising above threshold means the application is falling behind. | Medium |
| `backPressuredTimeMsPerSecond` | Maximum | 5 minutes | > 500 ms/s sustained for 3 consecutive periods | Severe backpressure; downstream bottleneck. | High |
| `uptime` (Flink 1.x) or `runningTime` (Flink 2.2) | Minimum | 5 minutes | Resets (drops to 0) more than 2× in 1 hour | Frequent restarts indicate instability. | High |
| `threadsCount` | Maximum | 5 minutes | > maximum expected thread count | Watch for thread leaks in task managers. | Medium |
| `(oldGenerationGCTime * 100) / 60000` | Maximum | 1 minute | > threshold (set so typical GC is 60% of threshold) | AWS recommends this percentage-of-time formula. Continuously increasing indicates a memory leak. | Medium |
| `RATE(oldGenerationGCCount)` | Maximum | 5 minutes | > maximum expected rate | Continuously increasing indicates a memory leak. | Medium |
| `currentOutputWatermark - currentInputWatermark` | Minimum | 5 minutes | > threshold | Continuously increasing indicates the application is processing increasingly older events or an upstream subtask has stalled watermark emission. | Medium |

**Alarm configuration notes:**

- Use "3 out of 3 consecutive periods" evaluation for CPU, heap, and backpressure alarms to avoid false alarms from transient spikes during checkpoints or GC.
- For `downtime`, use "1 out of 1" — any downtime is immediately actionable.
- For `lastCheckpointDuration`, calculate the threshold from your configured checkpoint interval. If the interval is 60 seconds, alarm at > 30,000 ms.
- For `millisBehindLatest` / `records_lag_max`, combine the threshold with a trend check: a one-time spike that recovers is less concerning than a steadily increasing value.

### Using Metric Trends to Drive Scaling Decisions

Point-in-time metric values can be misleading. Use trends over 30–60 minute windows to make scaling decisions:

**Scale up (add KPUs) when:**

- `cpuUtilization` `Maximum` is sustained above 70% for 30+ minutes during normal (non-peak) traffic. This leaves insufficient headroom for traffic spikes and checkpoint overhead.
- `backPressuredTimeMsPerSecond` is sustained above 100 ms/s for 15+ minutes. This means at least one operator chain cannot keep up with its input rate.
- `millisBehindLatest` or `records_lag_max` is monotonically increasing over 30+ minutes. The application is falling further behind and will not recover without more resources.
- `lastCheckpointDuration` is trending upward and approaching the checkpoint interval. State is growing faster than the application can snapshot it.

**Scale down (reduce KPUs) when:**

- `cpuUtilization` `Maximum` is sustained below 30% for 60+ minutes during peak traffic. The application is over-provisioned.
- `backPressuredTimeMsPerSecond` is consistently 0 for 60+ minutes. No operators are bottlenecked.
- `heapMemoryUtilization` `Maximum` is sustained below 40% for 60+ minutes. Memory is significantly over-provisioned.

**Do not scale based on:**

- Short spikes (< 10 minutes) in CPU or backpressure — these are often caused by checkpoint processing or transient traffic bursts and resolve on their own.
- A single high `lastCheckpointDuration` value — one slow checkpoint can be caused by a GC pause or S3 latency spike. Look for a trend of increasing duration across multiple checkpoints.
- `numRecordsInPerSecond` alone — throughput fluctuations are normal. Combine with backpressure and lag metrics to determine if the application is actually struggling.

## Custom Metrics Emission

### Registering Custom Metrics via Flink MetricGroup API

Flink provides four metric types through the `MetricGroup` API, available in any `RichFunction` or `ProcessFunction` via `getRuntimeContext().getMetricGroup()`:

| Metric Type | Purpose | Registration Method | Example Use Case |
|-------------|---------|-------------------|------------------|
| **Counter** | Monotonically increasing count | `metricGroup.counter("name")` | Records processed, errors encountered, records filtered |
| **Gauge** | Point-in-time value that can go up or down | `metricGroup.gauge("name", gaugeFunction)` | Queue depth, cache size, current processing delay |
| **Meter** | Rate of events (events per second) | `metricGroup.meter("name", new MeterView(60))` | Throughput rate, error rate over a sliding window |
| **Histogram** | Distribution of values (min, max, mean, percentiles) | `metricGroup.histogram("name", new DescriptiveStatisticsHistogram(100))` | Record processing latency, payload sizes |

### Critical: The `kinesisanalytics` Metric Group Requirement

**Managed Service for Apache Flink publishes only metrics registered under the `kinesisanalytics` metric group to CloudWatch.** If you register custom metrics directly on `getRuntimeContext().getMetricGroup()` without adding the `kinesisanalytics` group, your metrics will be visible in the Flink Web UI but will **not** appear in CloudWatch.

You must use `.addGroup("kinesisanalytics")` when registering custom metrics:

```java
// CORRECT — metrics will appear in CloudWatch
getRuntimeContext().getMetricGroup()
    .addGroup("kinesisanalytics")
    .counter("myCounter");

// WRONG — metrics will NOT appear in CloudWatch
getRuntimeContext().getMetricGroup()
    .counter("myCounter");
```

The `kinesisanalytics` group name is a legacy from when the service was called Kinesis Data Analytics. Additional metric groups can be included and will be published to CloudWatch as dimensions.

### How Custom Metrics Publish to CloudWatch from Managed Service for Apache Flink

Managed Service for Apache Flink automatically publishes all Flink metrics registered under the `kinesisanalytics` group to CloudWatch under the `AWS/KinesisAnalytics` namespace. Custom metrics appear in CloudWatch with the same dimensions as built-in metrics (Application, Task, Operator, Parallelism).

**Naming conventions:**

- Use descriptive concatenated names: `ReceivedRecordsTotal`, `FilteredRecordsAverage` (as shown in the AWS examples)
- Prefix with a domain to avoid collisions with Flink internal metrics
- Keep names short — they contribute to CloudWatch metric cardinality and appear in dashboards

### Code Example

The following example demonstrates the pattern from the [official AWS CustomMetrics sample](https://github.com/aws-samples/amazon-managed-service-for-apache-flink-examples/tree/main/java/CustomMetrics). It uses a `RichMapFunction` as a pass-through that emits a counter and a gauge:

```java
public class MetricEmittingMapperFunction extends RichMapFunction<SpeedRecord, SpeedRecord> {
    private static final double AVERAGE_DECAY = 0.1;

    private transient Counter counter;
    private transient double runningAverage;
    private final String customMetricName;

    public MetricEmittingMapperFunction(final String customMetricName) {
        this.customMetricName = customMetricName;
    }

    @Override
    public void open(OpenContext openContext) throws Exception {
        // CRITICAL: Must use .addGroup("kinesisanalytics") for CloudWatch publishing
        this.counter = getRuntimeContext().getMetricGroup()
                .addGroup("kinesisanalytics")
                .counter(customMetricName + "Total");

        getRuntimeContext().getMetricGroup()
                .addGroup("kinesisanalytics")
                .gauge(customMetricName + "Average", () -> runningAverage);
    }

    @Override
    public SpeedRecord map(SpeedRecord value) {
        counter.inc();
        runningAverage = runningAverage * (1 - AVERAGE_DECAY) +
                value.speed * AVERAGE_DECAY;
        return value;
    }
}
```

This mapper is then used in the pipeline to emit metrics at different stages:

```java
// Emit metrics before filtering
DataStream<SpeedRecord> beforeFilter = input
        .map(new MetricEmittingMapperFunction("ReceivedRecords"));

// Filter
DataStream<SpeedRecord> filtered = beforeFilter
        .filter(SpeedLimitFilter::isAboveSpeedLimit);

// Emit metrics after filtering
DataStream<SpeedRecord> afterFilter = filtered
        .map(new MetricEmittingMapperFunction("FilteredRecords"));
```

### Cardinality Limits and Management Strategies

CloudWatch has practical limits on custom metric cardinality that affect cost and usability:

- **CloudWatch pricing**: Each unique metric (combination of namespace, metric name, and dimension values) is billed as a custom metric. At $0.30 per metric per month, an application with 100 custom metrics × 32 subtasks = 3,200 billable metrics = ~$960/month.
- **Dashboard limits**: CloudWatch dashboards become slow and unwieldy with more than a few hundred metrics. Operator-level custom metrics at high parallelism quickly exceed this.
- **API throttling**: CloudWatch `PutMetricData` has API rate limits. Excessive custom metrics can cause metric publishing delays or dropped data points.

**Strategies for managing cardinality:**

1. **Register metrics at the operator level, not per-key.** Do not create a separate counter for each key value (e.g., `orders.processed.customerA`, `orders.processed.customerB`). Instead, use a single counter per operator and rely on subtask-level dimensions for distribution analysis.

2. **Use Application-level aggregation for alarms.** CloudWatch automatically aggregates subtask-level metrics to the Application level using the `Average`, `Sum`, `Min`, and `Max` statistics. Set alarms on Application-level aggregates rather than individual subtask metrics.

3. **Limit custom metrics to 10–20 per operator.** Beyond this, the cardinality cost grows quickly with parallelism. Focus on metrics that directly inform operational decisions (error rates, processing latency, business KPIs).

4. **Prefer counters and gauges over histograms.** Histograms publish multiple CloudWatch metrics per registration (min, max, mean, p50, p75, p95, p99, count) — a single histogram registration produces 8+ CloudWatch metrics per subtask.

### Metric Reporting Interval and Cost Implications

Managed Service for Apache Flink reports metrics to CloudWatch at a fixed interval, typically every 60 seconds (with 4 snapshots per minute for throughput metrics). This has several implications:

- **Granularity**: Custom metrics have 1-minute resolution in CloudWatch. Sub-minute fluctuations are averaged within each reporting interval. For latency-sensitive monitoring, use the Flink Web UI (which updates in near-real-time) alongside CloudWatch.
- **Cost**: CloudWatch charges are per-metric per-month, not per-data-point. The reporting interval does not directly affect cost — but more frequent reporting (if configurable in future Managed Service for Apache Flink versions) would not increase cost for the same metric set.
- **Meter accuracy**: Flink's `MeterView` calculates rates over a configurable window (e.g., 60 seconds). Align the meter window with the reporting interval for consistent rate values in CloudWatch. A 60-second `MeterView` window with 60-second reporting produces stable rate metrics.
- **Gauge staleness**: Gauges report their current value at each reporting interval. If the gauge value changes rapidly between intervals, CloudWatch only captures the value at the reporting moment. For rapidly changing values, consider using a counter (cumulative) and computing rates in CloudWatch metric math.

## Monitoring Setup Operations

Operational specifics for wiring up monitoring on a new or existing MSF application.

### Log Group / Stream Creation Order

The log group and stream **must exist before** `add-application-cloud-watch-logging-option` is called — MSF does not create them. Application logs are silently dropped if the destination doesn't exist.

```
1. aws logs create-log-group    --log-group-name /aws/kinesis-analytics/<app>
2. aws logs create-log-stream   --log-group-name /aws/kinesis-analytics/<app> \
                                --log-stream-name kinesis-analytics-log-stream
3. aws logs put-retention-policy --log-group-name /aws/kinesis-analytics/<app> \
                                 --retention-in-days 30
4. aws kinesisanalyticsv2 add-application-cloud-watch-logging-option ...
```

Default CloudWatch log retention is unlimited — set retention explicitly to control cost. 30 days is a reasonable default; 7 days for dev.

### MetricsLevel — Cost vs Granularity

| Level | Per-app metrics emitted | When to use |
|-------|------------------------|-------------|
| APPLICATION | ~25 metrics × 1 dimension | Production default |
| OPERATOR | ~25 × N operators | Diagnosing a specific bottleneck operator |
| TASK | ~25 × M tasks | Rare — usually OPERATOR is sufficient |
| PARALLELISM | ~25 × Parallelism × N operators | **Avoid above Parallelism=64** (CloudWatch metric explosion) |

OPERATOR/TASK/PARALLELISM are useful for short-window diagnosis; switch back to APPLICATION after. CloudWatch custom metrics are billed at ~$0.30/metric-month.

### `treat-missing-data` Semantics

The `--treat-missing-data` flag determines alarm state when a metric stops reporting. The right value differs per alarm:

| Metric | `treat-missing-data` | Why |
|--------|---------------------|-----|
| `downtime` | `breaching` | Missing data = app not reporting = a problem |
| `fullRestarts` / `numRestarts` (cumulative) | `notBreaching` | Counter only emits when non-zero in some Flink versions |
| `numberOfFailedCheckpoints` | `notBreaching` | Cumulative counter; resets on restart |
| `cpuUtilization`, `containerCPUUtilization`, `containerMemoryUtilization`, `heapMemoryUtilization` | `missing` (default) | Brief gaps during restart are normal |
| `backPressuredTimeMsPerSecond` | `missing` | Operator-level metric, gaps are normal |

**Cumulative counters need special treatment.** `numberOfFailedCheckpoints`, `fullRestarts`, and `numRestarts` only ever increase during a job's lifetime; they reset only when the application restarts. Three rules follow from this and must be configured together — getting any one wrong breaks the alarm.

1. **Alarm on `RATE()`, not the raw value.** `RATE(numberOfFailedCheckpoints) > 0` alarms when checkpoints are *actively* failing in the current window. An alarm on the raw cumulative value would trip on the first failure ever and stay in ALARM until the next application restart, even after the underlying issue was fixed, because the count never decreases.

2. **Set `treat-missing-data: notBreaching`.** Some Flink versions only emit these counters when the value is non-zero, so a healthy app produces emission gaps as a normal steady state. `notBreaching` makes those gaps count as "not in alarm" instead of flipping the alarm to INSUFFICIENT_DATA. Combined with rule 1, the lifecycle is: healthy app → no data points → OK; failures land → non-zero `RATE()` → ALARM; failures stop → gaps return → OK.

3. **Route the alarm as an investigation trigger, not a self-clearing health signal.** Rule 1 means the alarm *will* return to OK on its own once new failures stop landing in the window. That is a statement about *recent activity*, not about *resolution*: "no new failures in the last N minutes" is not the same as "an operator diagnosed the root cause." Send these alarms to a ticketing or acknowledgment workflow where a human closes them after investigation, not to a paging path that treats the OK transition as "problem solved." A burst of checkpoint failures that stops on its own is still worth a postmortem.

### Alarm Priority Order for New Applications

When setting up monitoring on a new app, configure in this order — earlier alarms catch issues that downstream alarms can't:

1. `RATE(numberOfFailedCheckpoints) > 0` — checkpoint failures = data loss risk
2. `downtime > 0` (Flink 1.x) or `restartingTime > 0` (Flink 2.2) — app not processing
3. `RATE(fullRestarts) > 0` (Flink 1.x) or `RATE(numRestarts) > 0` (Flink 2.2) — instability
4. `cpuUtilization > 80%` Maximum, 3/3 — capacity warning
5. `heapMemoryUtilization > 90%` Maximum, 3/3 — OOM risk (AWS's officially recommended alarm). Substitute or supplement with `containerMemoryUtilization > 85%` for stateful apps where off-heap RocksDB / native memory matters; AWS's metric docs call container "a better tracker of total memory exhaustion."
6. `backPressuredTimeMsPerSecond > 500` Average, 3/3 — bottleneck
7. `millisBehindLatest` (Kinesis) or `records_lag_max` (Kafka) — falling behind input

For exact thresholds and statistic recommendations, see [Recommended Alarms and Thresholds](#recommended-alarms-and-thresholds) above.

### Common Setup Mistakes

| Mistake | Consequence |
|---------|-------------|
| Adding logging option before creating log group | Logs silently dropped; no error |
| `treat-missing-data: missing` on `downtime` | Missed outages — a stopped app emits no `downtime` data |
| Alarming on cumulative counter without `RATE()` | One-time alert that never auto-resolves |
| Leaving MetricsLevel=PARALLELISM in production | CloudWatch metric cost explosion at scale |
| No log retention policy | Unbounded log storage cost |
| APPLICATION level when diagnosing a specific operator | Cannot isolate the bottleneck — temporarily switch to OPERATOR |
