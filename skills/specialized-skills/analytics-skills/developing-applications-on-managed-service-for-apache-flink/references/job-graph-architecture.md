# Job Graph Architecture Guide

## Overview

This guide covers Flink job graph design for Managed Service for Apache Flink applications: operator chaining, operator-to-task-slot mapping, and task slot overload diagnosis. Use it when designing a new job graph, diagnosing performance problems in an existing one, or deciding whether to split a large application. For anti-patterns (data skew, monolith jobs, high fan-out), see [job-graph-anti-patterns.md](job-graph-anti-patterns.md).

## Operator Chaining and Job Graph Basics

### How Operator Chaining Works

Flink automatically chains operators that meet all of these conditions into a single task:

- Same parallelism
- Connected by a forward (non-shuffle) data exchange
- Same slot sharing group
- Neither operator has chaining explicitly disabled

Chained operators run in the same thread, eliminating serialization/deserialization overhead and thread context switching between them. In the Flink Web UI, chained operators appear as a single box in the job graph with names joined by arrows (e.g., `Source → Map → Filter`).

**Verifying chaining in the Flink Web UI:**

1. Open the Flink Web UI from the Managed Service for Apache Flink console
2. Navigate to the running job's "Overview" tab
3. Each box in the job graph represents one task (a chain of operators)
4. Click a task box to see which operators are chained inside it
5. If operators you expected to be chained appear as separate boxes, check that parallelism matches and the data exchange is forward

**Diagnosing unexpected chain breaks** — work this list in order before assuming a bug or re-running the job:

1. **Parallelism mismatch.** Confirm every operator in the supposed chain runs at the same parallelism. Source connectors are a frequent culprit — a Kinesis source defaults to one subtask per shard, so a 4-shard stream can't chain with downstream operators set to 8. Per-operator `setParallelism()` overrides the env default.
2. **Implicit shuffle.** Any `keyBy()`, `rebalance()`, `shuffle()`, `broadcast()`, or `rescale()` between two operators inserts a network exchange and breaks the chain at that point. The exchange-label arrow (`HASH`, `REBALANCE`, `FORWARD`) between job-graph boxes tells you which case applies.
3. **`startNewChain()` or `disableChaining()` left in code.** These are commonly added for diagnostic isolation (see below) and forgotten.
4. **Different slot sharing groups.** A `slotSharingGroup("...")` on one operator that differs from its neighbor will prevent chaining even if everything else aligns.

Breaking a chain is not always wrong — see "Using `disableChaining()` and `startNewChain()` Strategically" below for legitimate reasons (operator-metric isolation, external-call latency separation, explicit parallelism boundaries). The Flink Web UI is the source of truth here, not "the display might be misleading."

### Operator-to-Task-Slot Mapping

Each task slot runs one parallel pipeline of chained operators. The number of operators per task slot depends on how many operators chain together and how many slot sharing groups exist.

**Rule of thumb: 20–40 operators per task slot.** This range balances resource utilization against overhead:

| Operators per Task Slot | Behavior |
|------------------------|----------|
| < 20 | Underutilized slots; consider consolidating operators or reducing KPUs |
| 20–40 | Healthy range for most workloads |
| 40–100 | Monitor GC pressure and checkpoint duration closely |
| 100–200 | Likely experiencing performance degradation; consider restructuring |
| > 200 | Split the job or restructure the graph (see Operator-to-Task-Slot Overload) |

### Using `disableChaining()` and `startNewChain()` Strategically

Break chains only when you have a specific reason:

```java
// Break the chain before a CPU-intensive operator to isolate its metrics
DataStream<Result> results = events
    .keyBy(Event::getKey)
    .process(new ExpensiveProcessor())
    .startNewChain()  // This operator starts a new chain
    .uid("expensive-processor-uid");

// Completely disable chaining for a specific operator (rarely needed)
DataStream<Enriched> enriched = events
    .map(new ExternalServiceLookup())
    .disableChaining()  // Runs in its own task, not chained with anything
    .uid("external-lookup-uid");
```

**When to break chains:**

- To isolate a CPU-intensive operator so its metrics (busyTime, backpressure) are visible independently in the Flink Web UI
- To separate an operator that makes external calls (HTTP, database) from the rest of the pipeline so its latency does not mask upstream/downstream metrics
- To control parallelism boundaries — operators with different parallelism cannot chain anyway, but `startNewChain()` makes the intent explicit

**When NOT to break chains:**

- For debugging only — use the Web UI's subtask metrics instead
- To "improve parallelism" — breaking chains does not change parallelism; it only adds serialization overhead
- Preemptively on every operator — this defeats the purpose of chaining and increases resource consumption

### Viewing the Physical Execution Plan

The Flink Web UI shows two views of the job:

1. **Job Graph** (Overview tab): Shows the logical plan with chained operators grouped into task boxes. Use this to verify chaining decisions.
2. **Task Managers** tab: Shows which task slots are allocated on each TaskManager and what tasks run in each slot. Use this to verify operator-to-task-slot distribution.

To check operator-to-task-slot assignments:

1. Open the Flink Web UI → select the running job
2. Click on a task box in the job graph to expand its details
3. The "Subtasks" tab shows each parallel instance (subtask) and which TaskManager hosts it
4. Cross-reference with the TaskManagers tab to see total slot utilization per TaskManager

For data skew detection and mitigation, the monolith job anti-pattern, and the high fan-out anti-pattern, see [job-graph-anti-patterns.md](job-graph-anti-patterns.md).

## Operator-to-Task-Slot Overload

### Recommended Ratios and Performance Implications

Each task slot runs a parallel pipeline of chained operators within a single thread. The more operators packed into a slot, the more work that thread must perform — including state access, serialization, timer management, and checkpoint barrier handling.

**Recommended ratio: 20–40 operators per task slot.**

| Ratio Range | Impact |
|-------------|--------|
| 20–40 | Optimal. Checkpoint barriers propagate quickly, GC pressure is manageable, per-operator metrics remain meaningful. |
| 40–100 | Elevated GC pressure from increased object allocation. Checkpoint duration starts to grow as more state must be snapshotted per slot. Latency percentiles widen. |
| 100–200 | Noticeable degradation. GC pauses become frequent, checkpoint durations may approach the checkpoint interval, and tail latency increases significantly. |
| > 200 | Critical. Split the job or restructure the graph. At this density, GC overhead dominates CPU time, checkpoints risk timing out, and individual operator metrics become unreliable. |

### Symptoms of Task Slot Overload

- **High GC pressure**: `heapMemoryUtilization` sustained above 80% (scale-up signal; see [monitoring-and-metrics.md](monitoring-and-metrics.md)), frequent full GC pauses
- **Slow checkpoints**: `lastCheckpointDuration` increasing or approaching the checkpoint interval
- **Increased latency**: `busyTimeMsPerSecond` approaching 1000 (fully saturated)
- **Unresponsive heartbeats**: In extreme cases, TaskManagers miss heartbeat deadlines causing restarts

### Threshold: >200 Operators → Split or Restructure

1. **Split the job** into independent Flink applications for processing paths that don't share state
2. **Restructure the graph**: combine sequential map/filter operations into a single `ProcessFunction`; remove redundant operators
3. **Adjust slot sharing groups** to distribute operators across more slots:

```java
DataStream<Result> results = events
    .keyBy(Event::getKey)
    .process(new HeavyProcessor())
    .slotSharingGroup("heavy-processing")
    .uid("heavy-processor-uid");
```

### Operator Group Scheduling

Flink's slot sharing allows operators from different pipeline parts to share the same task slot. When all operators are in the default group and the job has many operators, every slot runs one subtask of every operator — leading to overload.

**Strategies**: Group operators by resource profile (CPU-intensive vs I/O-bound in separate groups). Use the Flink Web UI's TaskManagers tab to verify balanced slot utilization.

## References

- See [Resource Optimization](resource-optimization.md) for KPU sizing, operator parallelism tuning, and checkpoint resource impact
- See [Best Practices](best-practices.md) for state management and serialization guidance
- See [Monitoring and Metrics](monitoring-and-metrics.md) for CloudWatch metric details and alarm configuration
- See [Managed Service for Apache Flink Overview](msf-overview.md) for KPU resource model and service constraints
