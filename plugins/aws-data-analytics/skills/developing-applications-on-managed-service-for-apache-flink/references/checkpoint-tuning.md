# Checkpoint Impact on Resources

## Overview

This guide covers how checkpointing affects Managed Service for Apache Flink application resources, including checkpoint size and memory consumption, frequency vs CPU/network trade-offs, checkpoint duration exceeding interval, and OOM/GC diagnostic steps.

For KPU sizing, operator parallelism tuning, and MSF configuration overrides, see [resource-optimization.md](resource-optimization.md).

## Checkpoint Size and KPU Memory Consumption

During a checkpoint, Flink snapshots operator state and uploads it to S3 (Managed Service for Apache Flink-managed bucket). This process consumes memory and CPU on each TaskManager:

- **RocksDB state backend** (default on Managed Service for Apache Flink): For incremental checkpoints, Flink uploads only new SST files created since the last checkpoint to S3. The async phase (uploading to S3) does not block record processing but does consume network bandwidth and some memory for upload buffers. The sync phase (snapshotting RocksDB) briefly blocks the subtask.
- Larger state per TaskManager means more data to read and upload, increasing memory and network pressure during the checkpoint window. Skewed state distribution can cause individual TaskManagers to become bottlenecks even when aggregate resources are sufficient.
- There is no official AWS or Flink guidance specifying a fixed percentage of KPU memory to reserve for checkpoint overhead. The actual impact depends on state size, checkpoint type (incremental vs full), and upload concurrency. Monitor `lastCheckpointDuration` and `heapMemoryUtilization` during checkpoint windows to assess whether checkpoint overhead is causing memory pressure.

## Checkpoint Frequency vs CPU and Network Bandwidth

Checkpoint frequency is configured via the Managed Service for Apache Flink `CheckpointInterval` setting (default: 60000ms / 60 seconds). The `MinPauseBetweenCheckpoints` (default: 5000ms) prevents continuous checkpointing when a checkpoint takes longer than the interval. You must set `ConfigurationType` to `CUSTOM` to modify these values. More frequent checkpoints:

- **Increase CPU usage**: each checkpoint triggers RocksDB file reads and S3 uploads across all TaskManagers. With incremental checkpoints (Managed Service for Apache Flink default), the CPU impact is proportional to state changes, not total state size.
- **Increase network bandwidth**: checkpoint data flows from TaskManagers to S3. With large state and frequent checkpoints, this can compete with data processing traffic.
- **Reduce recovery time**: more frequent checkpoints mean less data to replay from sources after a failure.

**Trade-off guidance per Flink docs:** When checkpoints frequently take longer than the base interval, the system ends up constantly taking checkpoints, tying up resources and reducing operator progress. Use `MinPauseBetweenCheckpoints` to prevent this. The Flink documentation does not prescribe specific interval ranges for state sizes — tune based on observed `lastCheckpointDuration` relative to your interval, and ensure checkpoints complete well within the interval with room to spare.

## Checkpoint Duration Exceeding Interval

**Symptoms:**

- `lastCheckpointDuration` in CloudWatch approaches or exceeds the configured checkpoint interval
- `numberOfInProgressCheckpoints` stays > 0 for extended periods
- Increasing `backPressuredTimeMsPerSecond` during checkpoint windows
- `millisBehindLatest` (Kinesis) or consumer lag (Kafka) grows during checkpoints

**Consequences:**

- By default, the next checkpoint is triggered immediately once the ongoing one completes. With `MinPauseBetweenCheckpoints` (default 5s on Managed Service for Apache Flink), there's a minimum gap, but the system can still end up constantly checkpointing.
- For aligned checkpoints (the default mode), checkpoint barriers can cause channels to block while waiting for alignment, contributing to backpressure. Unaligned checkpoints (available from Flink 1.15+, requestable via AWS support for Managed Service for Apache Flink) avoid this alignment delay but have other trade-offs.
- In extreme cases, checkpoint timeouts trigger checkpoint failures, and repeated failures can cause application restarts.

**Remediation:**

1. **Verify incremental checkpoints are active** (they are enabled by default on Managed Service for Apache Flink). If for some reason they were overridden, re-enable them — incremental checkpoints only upload state changes since the last checkpoint, dramatically reducing upload size for large state.
2. **Increase checkpoint interval** via the `UpdateApplication` API with `ConfigurationType: CUSTOM` to give more time for completion. Also consider increasing `MinPauseBetweenCheckpoints`.
3. **Add KPUs** to spread state across more TaskManagers, reducing per-TaskManager checkpoint size.
4. **Reduce state size**: add or tighten TTL on keyed state, reduce key cardinality, or use more compact serialization (POJO over Kryo).
5. **Request RocksDB tuning overrides** via AWS support if compaction or read amplification is the bottleneck.
6. **Consider buffer debloating** — request enablement via AWS support case. This can help applications with backpressure-related checkpoint issues.

## OOM and GC Diagnostic Steps

If the application throws `OutOfMemoryError` or shows sustained high GC activity:

1. **Check `heapMemoryUtilization` in CloudWatch.** If sustained > 80%, the application needs investigation and likely a scale-up (see [monitoring-and-metrics.md](monitoring-and-metrics.md) for graduated thresholds: healthy ≤ 75%, scale-up signal > 80% sustained, critical alarm > 90%).
2. **Check `lastCheckpointSize` and `lastCheckpointDuration`.** Large checkpoints consume significant heap during snapshot creation.
3. **Review state TTL configuration.** Missing or overly long TTL causes state to accumulate indefinitely.
4. **Check for Kryo serialization fallbacks.** Kryo uses more memory than POJO serialization. Look for log messages: `"Class ... cannot be used as a POJO type"`.
5. **Review operator state usage.** Use Flink Web UI to check state size per operator. Identify operators with disproportionately large state.

**If the root cause is legitimate memory pressure after optimization:**

- Request a JVM heap size increase via AWS support
- Consider increasing KPU count to spread state across more TaskManagers
- Request RocksDB block cache increase if state reads are the bottleneck (high cache miss rate)
