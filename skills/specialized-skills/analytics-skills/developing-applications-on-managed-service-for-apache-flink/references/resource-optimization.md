# Resource Optimization Guide

## Overview

This guide covers KPU sizing, operator parallelism tuning, Amazon Managed Service for Apache Flink configuration overrides, and checkpoint resource impact. Use it when right-sizing a new Managed Service for Apache Flink application or optimizing an existing one based on CloudWatch metrics.

## KPU Sizing Methodology

### CRITICAL: Understanding the KPU Resource Model

Each Kinesis Processing Unit (KPU) provides exactly:

- 1 vCPU
- 4 GB memory (3 GiB JVM heap + 1 GiB reserved for native code allocations including RocksDB, network buffers, and framework overhead)
- 50 GB running application storage

Managed Service for Apache Flink allocates KPUs based on two configuration parameters you set at the service level (console or API):

- **Parallelism**: The total number of parallel task slots for your application (default: 1, default max: 256)
- **ParallelismPerKPU**: The number of task slots per KPU (default: 1, max: 8)

MSF derives the KPU count from these settings:

**Allocated KPUs = Parallelism / ParallelismPerKPU**.

| Parallelism | ParallelismPerKPU | Allocated KPUs | Resources |
|-------------|-------------------|----------------|-----------|
| 4           | 1                 | 4              | 4 vCPU, 16 GB |
| 8           | 1                 | 8              | 8 vCPU, 32 GB |
| 16          | 2                 | 8              | 8 vCPU, 32 GB |
| 16          | 1                 | 16             | 16 vCPU, 64 GB |
| 32          | 2                 | 16             | 16 vCPU, 64 GB |
| 32          | 1                 | 32             | 32 vCPU, 128 GB |

Use ParallelismPerKPU = 1 for most workloads. Increase only when the application is CPU-light and memory-light per task slot (e.g., simple filtering or routing jobs), or for applications with blocking operations (e.g., I/O) where higher values lead to fuller utilization of KPU resources. Higher values pack more task slots per KPU, reducing memory/CPU/storage available per slot.

### Estimating Needed KPU Count

Start with the highest of these three estimates, then add headroom:

**1. CRITICAL: Throughput-based estimate:**

```
base_kpus = (input_record_rate × avg_record_size_bytes × processing_amplification) / throughput_per_kpu
```

- `processing_amplification`: ratio of total bytes processed (including intermediate shuffles) to input bytes. Typically 2–4× for jobs with `keyBy` and windowing.
- `throughput_per_kpu`: start with 5–10 MB/s per KPU for typical ETL workloads. CPU-intensive transformations (regex, JSON parsing, ML inference) reduce this to 1–3 MB/s.

**2. CRITICAL: State-size-based estimate:**

```
base_kpus = total_state_size_gb / usable_memory_per_kpu_gb
```

- `usable_memory_per_kpu_gb`: approximately 2–2.5 GB per KPU after JVM overhead and network buffers (out of 3 GiB heap). The 1 GiB native memory is used by RocksDB and framework overhead. With ParallelismPerKPU = 2, usable memory per slot drops to ~1–1.2 GB.

**3. CRITICAL: Source-parallelism-based estimate:**

```
base_kpus = max(kinesis_shard_count, kafka_partition_count)
```

Source parallelism should match the partition/shard count. If the source has 16 shards, you generally need at least 16 task slots.  

**Final KPU count with headroom:**

```
recommended_kpus = max(throughput_estimate, state_estimate, source_estimate) × 1.3
```

The 1.3× multiplier provides ~30% headroom for checkpoint overhead, traffic spikes, and GC pauses. Round up to the nearest even number for balanced TaskManager allocation.

### Auto-Scaling Behavior

Managed Service for Apache Flink's built-in auto-scaling uses fixed rules based on `containerCPUUtilization`:

- **Scale up**: When `containerCPUUtilization` exceeds 75% for 15 consecutive 1-minute datapoints, Managed Service for Apache Flink doubles `CurrentParallelism` (which increases allocated KPUs).
- **Scale down**: When `containerCPUUtilization` stays below 10% for 360 consecutive 1-minute datapoints (6 hours), Managed Service for Apache Flink halves `CurrentParallelism`. Will never reduce below the configured `Parallelism` setting.
- **During scaling**: Application enters `AUTOSCALING` status with downtime. Only `StopApplication` with `Force=true` is valid.
- Auto-scaling reacts only to CPU, not `heapMemoryUtilization` or backpressure. Scale manually for other metrics.
- Default KPU limit: 64 per application. Request increase via Service Quotas.

**For finer-grained control**, disable built-in auto-scaling and implement custom scaling using CloudWatch alarms and the `UpdateApplication` API.

### Using CloudWatch Metrics to Determine Scaling Direction

After deployment, use these CloudWatch metrics to validate sizing and adjust:

| Metric | Scale Up Signal | Scale Down Signal |
|--------|----------------|-------------------|
| `containerCPUUtilization` | Sustained > 75% over 15 min (triggers auto-scale-up) | Sustained < 10% over 6 hours (triggers auto-scale-down) |
| `heapMemoryUtilization` | Sustained > 80% | Sustained < 40% |
| `backPressuredTimeMsPerSecond` | > 100 ms/s sustained | Consistently 0 |
| `lastCheckpointDuration` | Increasing trend, approaching interval | Stable and well below interval |
| `millisBehindLatest` (Kinesis) | Increasing over time | Stable near 0 |

**Scaling decision process:**

**`heapMemoryUtilization` graduated thresholds**:

- **Healthy:** ≤ 75% — no action needed
- **Scale-up / investigation:** > 80% sustained — investigate state size, TTL, and consider adding KPUs (see [monitoring-and-metrics.md](monitoring-and-metrics.md))
- **Critical alarm:** > 90% — immediate action required; risk of OOM (see [checkpoint-tuning.md](checkpoint-tuning.md) for OOM diagnostic steps)

1. High `containerCPUUtilization` + low `heapMemoryUtilization` → add KPUs (CPU-bound)
2. High `heapMemoryUtilization` + low CPU → increase KPUs or request memory override (memory-bound)
3. High `backPressuredTimeMsPerSecond` → identify bottleneck operator, then scale or optimize
4. Growing `millisBehindLatest` → add KPUs or optimize processing logic

## Operator Parallelism Tuning

### When to Override Default Parallelism

Managed Service for Apache Flink sets application-level parallelism through the service console (`Parallelism` and `ParallelismPerKPU` parameters). In most cases, all operators inherit the configured `Parallelism` as their default. Override per-operator parallelism with `setParallelism()` only when:

- A source operator needs parallelism matched to its partition/shard count
- A CPU-intensive operator needs higher parallelism than the rest of the pipeline
- A lightweight operator (simple filter, static enrichment) can run at lower parallelism to free task slots

**Do not** set application-level parallelism in code for Managed Service for Apache Flink deployments. Managed Service for Apache Flink service-level settings take precedence.

### CRITICAL: Source Parallelism Recommendations

Set source parallelism equal to the number of Kinesis shards or Kafka partitions:

```java
// Kinesis: match shard count
DataStream<Event> events = env
    .fromSource(kinesisSource, watermarkStrategy, "kinesis-source")
    .setParallelism(16)  // Match shard count
    .uid("kinesis-source-uid");
```

If parallelism < partition/shard count, some subtasks handle multiple partitions (uneven load). If parallelism > count, excess subtasks sit idle and waste task slots.

### Per-Operator Parallelism and KPU Interaction

When you set per-operator parallelism, Managed Service for Apache Flink still allocates task slots based on the maximum parallelism across all operators. Operators with lower parallelism use fewer slots; operators with higher parallelism require enough total slots to accommodate them.

**Example**: Parallelism = 16, ParallelismPerKPU = 1 → 16 KPUs, 16 task slots.

```java
// Source: 8 shards → parallelism 8
DataStream<Event> events = env
    .fromSource(kinesisSource, watermarkStrategy, "kinesis-source")
    .setParallelism(8)
    .uid("kinesis-source-uid");

// CPU-heavy processing: inherits default parallelism of 16
DataStream<Result> results = events
    .keyBy(Event::getKey)
    .process(new HeavyProcessor())
    .uid("heavy-processor-uid");

results.sinkTo(sink).uid("sink-uid");
```

## Managed Service for Apache Flink Configuration Overrides

### Parameters Overridable via AWS Support

Managed Service for Apache Flink manages most infrastructure configuration automatically. However, certain parameters can be overridden by opening an AWS support case. These include:

| Parameter | Default | Override Range | Use Case |
|-----------|---------|---------------|----------|
| JVM heap size | 3 GiB (~75% of KPU memory) | Custom | Applications with large in-memory caches or high object churn |
| TaskManager native memory | 1 GiB (~25% of KPU memory) | Custom | Adjusting RocksDB vs heap balance |
| RocksDB block cache size | Auto-configured | Custom size | Large state with frequent random reads |
| RocksDB write buffer count | Default | 2–6 | High write-throughput state workloads |
| Network buffer memory | Auto-configured | Custom size | Jobs with high fan-out or many network channels |
| State backend type (RocksDB vs. HashMap) | RocksDB | | Jobs with lightweight state that can stay in-memory and benefit from faster in-memory performance |

### Process for Requesting Overrides

1. Gather diagnostic evidence: CloudWatch metrics showing the resource constraint (heap utilization, GC time, checkpoint duration trends)
2. Open an AWS support case under "Managed Service for Apache Flink"
3. Include: application ARN, current KPU count, the specific parameter to override, the requested value, and the diagnostic evidence
4. AWS support applies the override at the service level — no application code changes needed
5. After the override is applied, Managed Service for Apache Flink restarts the application to pick up the new configuration

For checkpoint impact on resources (checkpoint size and memory, frequency vs CPU/network, duration exceeding interval, OOM/GC diagnostic steps), see [checkpoint-tuning.md](checkpoint-tuning.md).
