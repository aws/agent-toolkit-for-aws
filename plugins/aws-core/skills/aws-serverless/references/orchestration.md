# Orchestration Reference

Step Functions and EventBridge decision matrices, error semantics, and limits. Assumes you can write Amazon States Language (Saga/Parallel/Map/Choice JSON) and EventBridge patterns — this file focuses on the choices and gotchas.

## Contents

- [Standard vs Express](#standard-vs-express)
- [State machine limits and patterns](#state-machine-limits-and-patterns)
- [Error handling](#error-handling)
- [Which EventBridge capability](#which-eventbridge-capability)
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

## Which EventBridge capability

Decided in `SKILL.md` Step 4; this is the full table.

| Need | Use | Continue with |
|---|---|---|
| Time-based triggers (cron, rate, one-time), replacing VM cron or always-on workers for infrequent jobs, millions of tenant schedules, retries + maximum event age + DLQ, auditable scheduled runs | **EventBridge Scheduler** | Scheduler invokes AWS APIs directly (Lambda, Step Functions, SQS, ECS RunTask, …); surface failures with the DLQ plus CloudWatch alarms on `TargetErrorCount` and on DLQ depth |
| AWS service state-change events on the default bus, or an existing classic single-account integration that routes events to up to 5 targets per rule by pattern matching | **EventBridge rules** on the default bus | [Event patterns](#eventbridge-rules-pipes-and-patterns) below |
| Any new workload that publishes its own application events, including a single-account workload; many independent consumers; cross-team or cross-account sharing; central governance; ordered delivery per event group; schema integration; per-subscriber transformation; deduplication; retention and replay | **New EventBridge custom event bus** (`eventsv2`) | **amazon-eventbridge-event-bus** skill. Classic EventBridge operations still use the `events` API; migration from classic to the new bus is covered by that skill's migration reference |
| One poll-based source (SQS, Kinesis, DynamoDB Streams, Kafka/MSK, Amazon MQ) feeding one target with optional filtering, enrichment, or transformation | **EventBridge Pipes** | [Source-to-target choices](#source-to-target-choices) below. If the only target is one Lambda function and no Pipe-only enrichment is needed, use the Event Function's native event source mapping directly |

"Decouple these steps" for a single application with fan-out → new custom event bus for newly published application events, or existing classic rules when preserving an established integration. When steps must run in order with checkpointed progress, retries, or compensation, that is orchestration rather than eventing: decide Durable Functions vs Step Functions below.

For an existing classic custom bus that needs retention, replay, ordering, or subscribers, plan an incremental migration through **amazon-eventbridge-event-bus**. Bridge classic and new buses so publishers and consumers can move independently; do not require a big-bang rewrite. Stay on classic for a feature the new bus does not support, such as Global Endpoints.

---

## EventBridge rules, pipes, and patterns

### Event patterns

All specified fields must match (AND); values within an array are OR'd. Operators: exact `["value"]`, `{"prefix"}`, `{"suffix"}`, `{"anything-but"}`, `{"numeric": [">", 0, "<=", 100]}`, `{"exists": true}`, `{"wildcard": "prod-*-east"}`.

### Best practices

1. Use the default bus for AWS service state-change events. For a new workload publishing its own events, evaluate the new custom event bus first.
2. **Be precise with patterns** — broad patterns risk infinite loops.
3. With classic rules, prefer one target per rule to simplify debugging and IAM.
4. Configure DLQs on deliveries that support them.
5. Use the EventBridge Sandbox to test classic event patterns before deploying.
6. The new custom bus uses subscribers rather than rules and targets; continue with **amazon-eventbridge-event-bus** for its payload shapes, filtering, transformations, retention, replay, ordering, migration, and delivery contract.

### Source-to-target choices

| Mechanism | Topology | Choose it when |
|---|---|---|
| Native Lambda event source mapping | Poll-based source → one Lambda function | The source is SQS, Kinesis, DynamoDB Streams, Kafka/MSK, or Amazon MQ; Lambda is the only target; native batching/filtering/retry controls are sufficient |
| EventBridge Pipes | Poll-based source → one target | Filtering, enrichment, or input transformation is needed in transit; the target is not Lambda; or a managed connector should replace glue code |
| Pipe → new custom event bus | Poll-based source → many independent consumers | One Pipe performs source-side filtering/enrichment and publishes to the bus; each consumer owns a subscriber. Do not create one Pipe per consumer merely to simulate fan-out |
| New custom event bus (`eventsv2`) | Application publishers → independent subscribers | The application publishes its own events and needs fan-out, retention/replay, ordering, deduplication, schemas, or independent consumer operations—even within one account |
| Classic rules | Event on a classic/default bus → up to 5 targets per rule | Routing AWS service state-change events or preserving an existing classic EventBridge integration |

Pipes filtering happens **at the source**—you pay only for matched events—with built-in retry and DLQ. A Pipe has one target; fan-out occurs after the Pipe through a bus and its subscribers.

---

## Step Functions vs Lambda durable functions

The choice is made in `SKILL.md` (Step 3 — orchestration). Treat compute and orchestration as separate dimensions:

- **Durable Functions** fits code-first orchestration written with the application, including all-Lambda workflows and replacement of hand-built checkpoint state.
- **Step Functions** fits an explicitly visual or ASL-authored workflow, a shared cross-team state-machine contract, Distributed Map, or broad coordination of AWS services and non-Lambda compute through native integrations.
- When the implementation model is not stated and either fits, name both with the one-line tradeoff rather than inferring that an external API/database call makes a workflow heterogeneous.

| Use this skill | When the workload involves |
|---|---|
| **aws-step-functions** | Orchestration whose primary work is coordinating AWS services directly; coordinating ECS/Fargate, Glue, SageMaker, or Batch through native managed integrations; a visual, auditable workflow definition required for compliance or operations; a shared contract between teams that do not share a codebase; a runtime Durable Functions does not support; Distributed Map fan-out to thousands of parallel executions; authoring or editing Amazon States Language (ASL), JSONata, Retry/Catch, `.sync`/`waitForTaskToken`, TestState, or JSONPath-to-JSONata migration |
| **aws-lambda-durable-functions** | Code-first orchestration when building on Lambda (`context.step`/`context.wait`/`context.invoke`, `withDurableExecution`); workflows written as plain sequential code in a supported runtime; waits on timers, callbacks, or conditions; checkpointed retries and execution history; replacing hand-rolled checkpointing in DynamoDB/Redis; saga and compensation logic; many fine-grained steps where Step Functions Standard transition cost may be significant |

Limits that decide ties: a Durable Functions step is bounded by the Lambda timeout of the capacity provider it runs on (15 min on On-Demand and for synchronous invocations on Managed Instances; 90 min on Managed Instances for async or ESM invocations), and a durable execution can run up to 1 year on async invocations. Step Functions Standard executions run up to 1 year and Express up to 5 minutes (see [Standard vs Express](#standard-vs-express)).

A Durable Function is an orchestration layer implemented by an Event Function. Few steps and a short wait may only need an idempotent handler plus a DLQ rather than either orchestrator.

**For implementation guidance use the aws-lambda-durable-functions or aws-step-functions skill** — this file covers only the choice, Step Functions execution semantics, and EventBridge details above.
