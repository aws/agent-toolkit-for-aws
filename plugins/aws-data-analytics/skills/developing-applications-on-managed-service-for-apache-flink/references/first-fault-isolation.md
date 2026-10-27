# First-Fault Isolation for Restart Loops

## Overview

Diagnose Flink jobs that are restarting, crashing, or stuck in a failure loop. The current exception in recent logs is almost always a **loop-sustaining side effect**, not the root cause. Find the FIRST task failure (attempt #0) and read its `throwableInformation`.

Use this guide when `fullRestarts > 0`, `downtime > 0`, the Flink job keeps cycling RUNNING → STARTING → RUNNING, or recent logs show repeating exceptions without obvious cause.

## #1 Rule

When a Flink job is in a restart loop, recent logs show loop iterations, NOT the root cause. Everything else — `addSplitsBack`, `UnsupportedOperationException: Partial recovery is not supported`, SSLException during restarts, connection errors after a stop — is a **loop-sustaining side effect**. The original trigger is in attempt #0's `throwableInformation` field.

## Methodology

### Step 1: Find crash onset (binary search)

Restart loops can run for days or weeks. The "last 1h" log window will only show loop iterations. Find the hour where `fullRestarts` first transitioned from 0 → >0 by binary searching backward across 14 days using CloudWatch:

```bash
for DAYS_AGO in 14 7 3 1; do
  aws cloudwatch get-metric-statistics --namespace AWS/KinesisAnalytics \
    --metric-name fullRestarts --dimensions Name=Application,Value="$APP" \
    --start-time $(date -u -d "${DAYS_AGO} days ago" +%Y-%m-%dT%H:%M:%SZ) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 3600 --statistics Maximum
done
```

Halve the window until you isolate the **hour** where `fullRestarts` went from 0 to >0. If `fullRestarts > 0` for the entire 14-day window, the job has never been stable on the current configuration.

In Flink 2.2+, use `numRestarts` (cumulative counter) — `fullRestarts` is removed.

### Step 2: Find the last successful checkpoint or transition to RUNNING before crash onset

If the app has checkpointing enabled, you can look for the last time the application successfully took a checkpoint:

```bash
aws logs filter-log-events --log-group-name "/aws/kinesis-analytics/$APP" \
  --filter-pattern '"Completed checkpoint"' \
  --start-time $((CRASH_ONSET_MS - 3600000)) --end-time $CRASH_ONSET_MS \
  --limit 50 --output json | jq '.events[-1]'
```

This gives the timestamp where the job was last healthy.

For apps without checkpointing, or using unaligned checkpointing, it is more reliable to identify the first time the app transitioned from a RUNNING state (see step 3).

### Step 3: Find attempt #0 — the FIRST task failure

In the 30 seconds after the last successful checkpoint, fetch ALL log events (do not filter) and look for:

- `"switched from RUNNING to"` — the task status change event
- `"#0 ("` in the task name — `#0` confirms attempt zero (first failure, not a loop iteration)
- `"Recovering subtask"` followed by `"Triggering job failover"` — the restart loop beginning

```bash
aws logs filter-log-events --log-group-name "/aws/kinesis-analytics/$APP" \
  --start-time $LAST_CHECKPOINT_MS --end-time $((LAST_CHECKPOINT_MS + 30000)) \
  --limit 50 --output json
```

### Step 4: Extract `throwableInformation` from attempt #0

MSF emits structured JSON logs. The actual exception and stack trace are in the `throwableInformation` field, NOT the `message` field. CloudWatch `filter-log-events` searches the raw log string, so a pattern like `"JsonParseException"` may not match if the exception is nested inside `throwableInformation`.

The reliable approach is to filter on `"switched from RUNNING"` then extract the field with jq:

```bash
aws logs filter-log-events --log-group-name "/aws/kinesis-analytics/$APP" \
  --filter-pattern '"switched from RUNNING"' \
  --start-time $FIRST_FAILURE_MS --end-time $((FIRST_FAILURE_MS + 2000)) \
  --output json | jq '.events[].message | fromjson | .throwableInformation'
```

Follow the `Caused by` chain downward, but **the deepest exception is not automatically the root cause** — it's just where the stack trace ends. Often it is the root cause (a `JsonParseException` at a specific offset, an `AmazonS3Exception: 403`, a user-code `NullPointerException` at a named line). Sometimes it isn't. Treat the deepest exception as the root cause only when it has **specific, actionable context** — a class.method() in user code, a connector message naming a resource and HTTP status, a parser pointing at a byte offset.

#### When the deepest exception is itself a symptom

Some exceptions terminate the stack trace but tell you almost nothing about *why*. They mean "the TaskManager / job stopped responding," not "here is what went wrong." When you see one of these as the deepest `Caused by`, **stop reading stack traces and pivot to metrics and live diagnostics** — the cause is no longer in the logs, it's in what was happening to the JVM or the cluster at that moment.

| Exception in `throwableInformation` | What it actually means | Where to pivot |
|---|---|---|
| `TimeoutException: Heartbeat of TaskManager with id ... timed out` | TM stopped sending heartbeats — GC pause, OOMKill, network partition, or CPU starvation | CloudWatch `heapMemoryUtilization`, `oldGenerationGCTime`, `cpuUtilization`, `containerCPUUtilization` for ±5 min around `FIRST_FAILURE_MS`; thread dump if app is still RUNNING |
| `Connection unexpectedly closed by remote task manager` / `LostTaskException` | Peer TM disappeared mid-shuffle | Same metrics on the *peer* TM; check whether a TM was killed by the resource manager (look for `TaskManager exited` / container exit codes in logs) |
| `JobMasterException: ... has not been heard from` | JobManager lost contact with TMs | JM-side GC and CPU; ZooKeeper / leader-election logs |
| `OutOfMemoryError: Java heap space` *with no application frames in the trace* | Heap exhausted during framework op (checkpoint serialization, network buffers) | `heapMemoryUtilization`, checkpoint size growth, state-backend choice; not user-code unless app frames are in the trace |
| `IOException: Insufficient number of network buffers` | Buffer pool exhausted | parallelism × shuffle-edge fan-out and `taskmanager.network.memory.*` config |
| Generic `IOException` / `ExecutionException` wrapping nothing specific | Wrapper with no diagnostic content | Keep walking `Caused by`; if the wrapper *is* the deepest entry, the cause is upstream of the JVM and you need metrics, not logs |

The pivot itself: re-anchor on `FIRST_FAILURE_MS` and pull a tight window of metrics and JM/TM logs around it.

```bash
# Heap, GC, CPU at the moment of failure (±5 min)
START=$(( (FIRST_FAILURE_MS - 300000) / 1000 ))
END=$(( (FIRST_FAILURE_MS + 300000) / 1000 ))
for METRIC in heapMemoryUtilization oldGenerationGCTime cpuUtilization containerCPUUtilization; do
  aws cloudwatch get-metric-statistics --namespace AWS/KinesisAnalytics \
    --metric-name "$METRIC" --dimensions Name=Application,Value="$APP" \
    --start-time @$START --end-time @$END --period 60 \
    --statistics Maximum Average
done

# Was a TaskManager killed (OOMKill, container exit) just before the heartbeat timeout?
aws logs filter-log-events --log-group-name "/aws/kinesis-analytics/$APP" \
  --filter-pattern '?"TaskManager exited" ?"OutOfMemory" ?"killed by" ?"exit code"' \
  --start-time $((FIRST_FAILURE_MS - 120000)) --end-time $FIRST_FAILURE_MS
```

Concrete pattern to look for: `oldGenerationGCTime` rising sharply or `heapMemoryUtilization` near 100% in the minutes before a heartbeat timeout = GC pressure / impending OOM, not a network issue. `containerCPUUtilization` pinned at the limit before a heartbeat timeout = CPU starvation, also not a network issue. If neither is true, suspect a real network event (VPC issue, ENI exhaustion) and check the EC2/VPC side.

Only after you have a coherent story across logs *and* metrics is it safe to call the root cause. If you can't get there from the data, say so explicitly in the report rather than promoting a symptom.

## Loop-Sustainer vs Original Trigger

| Exception | Role |
|-----------|------|
| Found in attempt #0's `throwableInformation` with specific context | **ORIGINAL TRIGGER** (root cause) |
| Heartbeat / `TaskManagerLost` / framework `OutOfMemoryError` as deepest `Caused by` | Symptom of GC / OOMKill / CPU / network — **pivot to metrics**, not the deepest cause |
| `UnsupportedOperationException: Partial recovery is not supported` | Loop sustainer (Kinesis Source FLIP-27 limitation) |
| `addSplitsBack` in stack trace | Loop sustainer (connector cannot partial-recover) |
| `SSLException`, `ConnectException` during restart | Loop side effect (rapid restarts cause connection churn) |
| `Recovering subtask ... Triggering job failover` | Loop iteration mechanics |
| `Restarting job` / `Task failed` | Symptoms — never report as root cause |
| `Caused by: <wrapper>` with no specific context | Follow chain deeper |

## Kinesis Source FLIP-27 Recovery Blocker

The `KinesisStreamsSource` (FLIP-27) does not support partial recovery. Any task failure with this source becomes an infinite restart loop because every restart attempt fails with `UnsupportedOperationException` from `addSplitsBack()`. The original cause in attempt #0 may have been transient (a single bad record, a momentary network blip), but the loop is permanent until you escape it.

**Escape procedure** (causes reprocessing or data loss — confirm with user):

1. Fix the root cause from attempt #0
2. Stop the application with `--force`
3. Poll until READY
4. Start with `ApplicationRestoreType=SKIP_RESTORE_FROM_SNAPSHOT`

## Diagnostic Anchors (Stack Trace Reading)

| Stack Frame | What It Means |
|-------------|---------------|
| `at com.<your-package>.MyUDF.process()` | User code bug |
| `at ...JsonDeserializationSchema.deserialize()` | Malformed input data |
| `at ...KafkaConsumer.poll()` / `at ...KinesisProxy...` | Connector/infrastructure issue (read message carefully) |
| `at org.apache.flink.runtime...` only | Framework-level — usually triggered by deeper user/connector cause; keep digging |
| Bare `IOException` wrapping deeper exception | Follow `Caused by` |

## Flink Dashboard for Live Diagnosis

When the Flink job is running (not stuck restarting), use the Flink Dashboard REST API for thread dumps, per-vertex backpressure, and execution plan analysis. Get a pre-signed URL:

```bash
aws kinesisanalyticsv2 create-application-presigned-url \
  --application-name "$APP" --url-type FLINK_DASHBOARD_URL \
  --query 'AuthorizedUrl' --output text
```

Authenticate by curling the URL with `-c cookie.jar -L`, then use `${BASE}flinkdashboard/` as the API base. Useful endpoints:

| Endpoint | Purpose |
|----------|---------|
| `overview` | Cluster status, slots, jobs |
| `jobs/$JOB_ID` | Per-vertex parallelism, status, read/write counts |
| `jobs/$JOB_ID/checkpoints` | Checkpoint history with sizes and durations |
| `jobs/$JOB_ID/vertices/$VERTEX_ID/backpressure` | Per-vertex backpressure level |
| `jobs/$JOB_ID/vertices/$VERTEX_ID/subtasks` | Per-subtask metrics — **detect data skew** |
| `jobs/$JOB_ID/plan` | Execution DAG with ship strategies |
| `taskmanagers/$TM_ID/thread-dump` | JVM thread dump for hot-thread / lock-contention analysis |

`create-application-presigned-url` fails on non-RUNNING applications.

### Thread Dump Patterns

| Stack Pattern | Diagnosis |
|--------------|-----------|
| `BLOCKED` on `synchronized` | Lock contention — reduce shared state, use async I/O |
| `TIMED_WAITING` in `Thread.sleep` | Explicit sleep in user code |
| `WAITING` in `Object.wait` on mailbox | Operator idle (normal for low-throughput) |
| `RUNNABLE` in `RocksDB.*` methods | State backend I/O — increase managed memory or enable incremental checkpoints |
| `RUNNABLE` in `SocketInputStream.read` | Network I/O — check source/sink latency |
| `RUNNABLE` in user package | CPU-bound user code |
| Multiple threads in same method | Hot method — profile and optimize |

### Job Graph Anti-Patterns (from `plan` and `subtasks` endpoints)

| Anti-Pattern | Detection | Fix |
|-------------|-----------|-----|
| Excessive shuffles | Multiple `HASH`/`REBALANCE` `ship_strategy` between vertices | Chain operators, use `forward` partitioning |
| Data skew | Subtask `read-records` variance > 5× across the same vertex | `rebalance()` instead of `keyBy()` on hot keys; pre-split |
| Late filtering | `read:write` ratio > 100:1 | Push filters upstream (predicate pushdown) |
| Parallelism mismatch | Downstream parallelism < upstream | Match parallelism across connected operators |
| Unchained operators | `FORWARD` strategy across separate vertices | Same parallelism + remove `disableChaining()` |

## Mandatory Report Format

When delivering diagnosis to the user, structure it as:

```
## Root Cause
First fault at <timestamp>: <specific exception> at <class.method>
Last healthy: <timestamp of last successful checkpoint>
Trigger: <one sentence — bad record, OOM, schema change, etc.>

## Symptoms (cascading from root cause)
- <symptom 1> — <relationship to root cause>
- <symptom 2> — <relationship to root cause>

## Fix
<specific action; not "investigate further">
```

State transitions (`RUNNING → FAILED`, `Task failed`, `Restarting job`) are **always symptoms**. Never report a state transition as a root cause.

## Common Mistakes

| Mistake | Why It Fails |
|---------|--------------|
| Searching last 1–24h on a multi-day restart loop | You find loop iterations, not the original failure |
| Reporting `addSplitsBack` / `UnsupportedOperationException` as root cause | These are loop-sustaining side effects of FLIP-27 Kinesis source |
| Reading only the `message` field of MSF JSON logs | Stack trace lives in `throwableInformation` |
| Reporting the deepest `Caused by` as root cause when it's a heartbeat timeout, `TaskManagerLost`, or framework `OutOfMemoryError` | Those are TM-died symptoms — pivot to heap/GC/CPU metrics around `FIRST_FAILURE_MS` |
| Filtering CloudWatch logs by exception class name | Filter searches raw string; nested fields may not match — filter on the `RUNNING to FAILED` event instead |
| Concluding from truncated `filter-log-events` output | If `NextToken` is present or `--limit` was hit, requery with wider window |
| Calling `create-application-presigned-url` on a non-RUNNING app | Fails — only works while RUNNING |

## References

- [MSF Troubleshooting Guide](https://docs.aws.amazon.com/managed-flink/latest/java/troubleshooting.html)
- [Flink REST API](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/rest_api/)
- [FLIP-27: Refactor Source Interface](https://cwiki.apache.org/confluence/display/FLINK/FLIP-27%3A+Refactor+Source+Interface)
