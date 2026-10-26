# Scaling Decision Framework

## Overview

Decision matrix for choosing the right scaling action based on observed bottleneck. For initial KPU sizing methodology and CloudWatch trend signals, see [resource-optimization.md](resource-optimization.md). This guide is for in-flight scaling decisions on running applications.

## Decision Matrix

```
What is the bottleneck?
│
├─► CPU > 70% sustained or backpressure > 500ms/s
│   → INCREASE Parallelism (adds KPUs, restart required)
│
├─► OOM errors or heapMemoryUtilization > 85%
│   → DECREASE ParallelismPerKPU (more memory per subtask)
│   → Same total parallelism, more KPUs, lower throughput-per-dollar
│
├─► Variable/spiky load + can tolerate restart-on-scale
│   → ENABLE AutoScalingEnabled=true
│   → MSF reacts on CPU only; 5-15 min reaction; restart per event
│
└─► CPU < 30% sustained, idle > 500ms/s, no backpressure
    → DECREASE Parallelism (over-provisioned)
    → Validate with 60+ minute trend before reducing
```

## Scaling Impact Table

| Change | KPU Effect | Memory Per Subtask | Cost Impact |
|--------|-----------|---------------------|-------------|
| Parallelism 4 → 8, PPK=1 | 4 → 8 KPU | 4 GB (unchanged) | 2× |
| Parallelism 4 → 8, PPK=2 | 2 → 4 KPU | 2 GB (unchanged) | 2× |
| PPK 2 → 1, Parallelism=8 | 4 → 8 KPU | 2 → 4 GB | 2× |
| PPK 1 → 2, Parallelism=8 | 8 → 4 KPU | 4 → 2 GB | 0.5× |
| Parallelism 8 → 4, PPK=1 | 8 → 4 KPU | 4 GB (unchanged) | 0.5× |

KPU formula: `KPU = Parallelism / ParallelismPerKPU`. Add 1 orchestration KPU for total billed.

## Pre-Scaling Validation

Always validate the bottleneck against trends, not point-in-time values, before scaling. Pull the last 6 hours of:

- `containerCPUUtilization` — Maximum (hottest container)
- `backPressuredTimeMsPerSecond` — Average and Maximum
- `idleTimeMsPerSecond` — Average and Minimum
- `heapMemoryUtilization` — Maximum
- `lastCheckpointDuration` — trend (rising = pressure)

If signals conflict (high CPU but also high idle, or backpressure with low CPU), the bottleneck is downstream — investigate the operator graph via Flink Dashboard before scaling. Adding KPUs to a sink-bound or skew-bound job wastes money. See [first-fault-isolation.md](first-fault-isolation.md) for live diagnosis via the Dashboard.

## AutoScalingEnabled Behavior

MSF built-in autoscaling is CPU-only with fixed thresholds:

- **Scale up:** `containerCPUUtilization > 75%` for 15 consecutive 1-min datapoints → doubles `CurrentParallelism`
- **Scale down:** `containerCPUUtilization < 10%` for 360 consecutive 1-min datapoints (6h) → halves `CurrentParallelism`, never below configured `Parallelism`
- **Each event triggers a full restart** (10–30s downtime). Backpressure, lag, and memory pressure do **not** trigger autoscaling.
- During scaling: status is `AUTOSCALING`. Only `stop-application --force` is valid.

For backpressure-driven, lag-driven, or memory-driven autoscaling: disable `AutoScalingEnabled` and implement custom scaling via CloudWatch alarms → Lambda → `update-application`.

## Stateful vs Stateless ParallelismPerKPU

| Workload | ParallelismPerKPU | Why |
|----------|-------------------|-----|
| Stateful (keyed windows, joins, large RocksDB state) | 1 | Each subtask needs full 4 GB; sharing causes RocksDB contention and OOM |
| Stateless transforms (map, filter, simple routing) | 2 | Half memory per subtask is fine; doubles compute density per KPU |
| I/O-blocking (async lookups, slow sinks) | 2–4 | Subtasks spend most time blocked; pack more per KPU to fill CPU |
| Source operators matched to shards/partitions | Match to source count | Use `setParallelism()` on the source only |

## Scaling Guardrails

- ❌ Cannot scale during a transitional state (STARTING, UPDATING, STOPPING, AUTOSCALING)
- ❌ Cannot scale during another in-flight update — sequence operations
- ⚠️ Every scaling change triggers a restart with 10–30s downtime (varies with state size and snapshot recency)
- ⚠️ Take a snapshot before scaling for rollback safety
- ⚠️ Scaling beyond 64 KPU requires a Service Quotas increase (default limit)
- ⚠️ Setting Parallelism > source partition/shard count creates idle subtasks — wasted KPUs

## Anti-Patterns

| Anti-Pattern | Why It Fails |
|-------------|--------------|
| Scaling up to fix checkpoint failures | Checkpoint failures are usually serialization, S3 perms, or alignment timeout — not capacity |
| Scaling up to fix data skew | Hot keys still go to the same subtask. Fix with `rebalance()` or pre-splitting keys |
| Scaling up to fix slow sink | Sink is the bottleneck regardless of KPU count. Optimize sink (batching, async I/O) or switch sink |
| Scaling during active restart loop | Restart loops persist until root cause is fixed; new KPUs join the loop |
| Reducing PPK and Parallelism in separate updates | Each triggers a restart; two sequential updates = double downtime. Combine in a single `update-application` call |
| Scaling on a single high CPU spike | Spikes from checkpointing or GC are normal; require sustained 30+ minute trend |

## References

- [MSF Auto-Scaling Behavior](https://docs.aws.amazon.com/managed-flink/latest/java/how-scaling.html#how-scaling-auto)
- [resource-optimization.md](resource-optimization.md) — KPU sizing methodology and trend-based signals
- [first-fault-isolation.md](first-fault-isolation.md) — diagnose before scaling
