# Orchestration Reference

Step Functions and EventBridge decision matrices, error semantics, and limits. Assumes you can write Amazon States Language (Saga/Parallel/Map/Choice JSON) and EventBridge patterns — this file focuses on the choices and gotchas.

## Contents

- [Standard vs Express](#standard-vs-express)
- [State machine limits and patterns](#state-machine-limits-and-patterns)
- [Error handling](#error-handling)
- [EventBridge rules, pipes, and patterns](#eventbridge-rules-pipes-and-patterns)
- [Step Functions vs Lambda durable functions](#step-functions-vs-lambda-durable-functions)

---

## Standard vs Express

| Dimension | Standard | Express |
|---|---|---|
| Max duration | 1 year | 5 minutes |
| Execution semantics | Exactly-once | At-least-once (async) / At-most-once (sync) |
| Execution history | Stored 90 days (API/console) | CloudWatch Logs only (must enable) |
| `.sync` integration | Supported | **Not supported** |
| `.waitForTaskToken` | Supported | **Not supported** |
| Distributed Map | Supported | **Not supported** |
| Activities | Supported | **Not supported** |
| Idempotency | Automatic (execution name unique 90 days) | Not managed |

Express sub-types: **Async** (fire-and-forget, results via CloudWatch Logs); **Sync** (blocks until completion, invokable from API Gateway/Lambda/`StartSyncExecution`, 5-min max).

| Use case | Type |
|---|---|
| Long-running, `.sync`/callback, non-idempotent (payments) | Standard |
| Distributed Map (large-scale parallel) | Standard |
| High-volume event processing (IoT, streaming) | Express |
| API-backed synchronous microservice orchestration | Synchronous Express |

---

## State machine limits and patterns

- **Payload limit: 256 KiB between states** — store large data in S3, pass S3 keys.
- **Inline Map:** max **40 concurrent** iterations, same execution.
- **Distributed Map:** up to **10,000 parallel child executions**, reads from S3 (JSON/CSV/inventory), supports `ItemBatcher`/`ItemReader`/`ResultWriter`. **Standard workflows only.**
- **25,000 execution-history entries** (Standard) — split long workflows into child executions.
- **Parallel state output is an array** (one element per branch); all branches must succeed or the state fails.
- **Choice state:** always include a `Default` branch.

Common patterns (write the ASL directly): **Saga** (each step has a compensating undo via `Catch`, chained in reverse); **Parallel** (concurrent branches); **Map** (iterate an array); **Agentic AI loop** (`bedrock:invokeModel` → Choice on `stop_reason = 'tool_use'` → execute tool → loop). Prefer **direct SDK integrations** (200+ services) over Lambda intermediaries to cut latency, and prefer **JSONata** for inline transforms over a Lambda task.

---

## Error handling

### Built-in error names

| Error Name | Retriable? | Notes |
|---|:---:|---|
| `States.ALL` | Yes | Wildcard — but does **NOT** match the two terminal errors below |
| `States.TaskFailed` | Yes | Wildcard for task errors (except `States.Timeout`) |
| `States.Timeout` / `States.HeartbeatTimeout` | Yes | Exceeded `TimeoutSeconds` / missed `HeartbeatSeconds` |
| `States.Permissions` | Yes | Insufficient IAM privileges |
| `States.DataLimitExceeded` | **No** | Payload > 256 KiB — **terminal** |
| `States.Runtime` | **No** | Invalid JSONPath, null payload — **terminal** |
| `States.ItemReaderFailed` / `States.ResultWriterFailed` | Yes | Map source/destination errors |

> **`States.ALL` does NOT catch `States.DataLimitExceeded` or `States.Runtime`.** These are terminal and must be designed around, not retried.

### Retry config

```json
"Retry": [
  { "ErrorEquals": ["States.Timeout"], "IntervalSeconds": 3, "MaxAttempts": 2,
    "BackoffRate": 2.0, "MaxDelaySeconds": 30, "JitterStrategy": "FULL" },
  { "ErrorEquals": ["Lambda.ServiceException", "Lambda.SdkClientException"],
    "IntervalSeconds": 1, "MaxAttempts": 3, "BackoffRate": 2.0 },
  { "ErrorEquals": ["States.ALL"], "IntervalSeconds": 1, "MaxAttempts": 3, "BackoffRate": 2.0 }
]
```

Defaults: `IntervalSeconds` 1, `MaxAttempts` 3 (0 = never), `BackoffRate` 2.0, `JitterStrategy` `"NONE"`.

Rules and best practices:

- `States.ALL` must be **last** in the Retry array; retries are attempted **before** catchers.
- Retries count as state transitions (billed in Standard).
- Always set `TimeoutSeconds` on every Task; always retry `Lambda.ServiceException` / `Lambda.SdkClientException`.
- Use `JitterStrategy: "FULL"` to prevent thundering herd; `HeartbeatSeconds` for long tasks.
- `Catch` with `ResultPath: "$.error-info"` preserves the original input alongside the error (without it, error output replaces the input).
- Listen for top-level execution failures via EventBridge (`source: aws.states`, `detail-type: Step Functions Execution Status Change`, `status: [FAILED, TIMED_OUT, ABORTED]`).

---

## EventBridge rules, pipes, and patterns

### Event patterns

All specified fields must match (AND); values within an array are OR'd. Operators: exact `["value"]`, `{"prefix"}`, `{"suffix"}`, `{"anything-but"}`, `{"numeric": [">", 0, "<=", 100]}`, `{"exists": true}`, `{"wildcard": "prod-*-east"}`.

### Best practices

1. **Dedicated event bus per application domain** — default bus for AWS service events only.
2. **Be precise with patterns** — broad patterns risk infinite loops.
3. **One target per rule** — simplifies debugging and IAM.
4. **DLQs on all targets.**
5. Use the EventBridge Sandbox to test patterns before deploying.

### Pipes vs Rules

| Dimension | Pipes | Rules |
|---|---|---|
| Topology | Point-to-point (1→1) | Fan-out (1→N) |
| Flow | Source → Filter → Enrichment → Transform → Target | Event routing on a bus |
| Sources | SQS, Kinesis, DynamoDB Streams, MSK, MQ | Any event on a bus |
| Enrichment | Built-in (Lambda, API GW, API Destinations, Sync Express SFN) | Not built-in |
| Use case | **Replace Lambda glue** for source→target | Event routing and distribution |

Pipes filtering happens **at the source** — you pay only for matched events — with built-in retry + DLQ.

---

## Step Functions vs Lambda durable functions

Lambda durable functions let you write reliable multi-step workflows as **plain code** (TS/Python/Java) with automatic checkpointing — the SDK persists each step and replays from the checkpoint on interruption, enabling executions up to 1 year with zero compute during waits. **For full guidance use the aws-lambda-durable-functions skill** (see SKILL.md routing).

| Question | Lambda durable functions | Step Functions |
|---|---|---|
| Programming model | Standard code (TS/Python/Java) | Amazon States Language / visual designer |
| AWS service integrations | Primarily Lambda | 200+ native integrations |
| Who reads the workflow | Developers | Non-technical stakeholders too |
| Best for | Distributed transactions, stateful logic, AI agent loops | Business process automation, multi-service orchestration |
