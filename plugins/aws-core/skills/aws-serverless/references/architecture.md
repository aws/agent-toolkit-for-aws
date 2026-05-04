# Serverless Architecture Patterns

Reference architectures, pattern selection flowcharts, and service selection tables for common serverless workloads.

## Contents

- [Pattern selection flowchart](#pattern-selection-flowchart)
- [REST/HTTP API pattern](#resthttp-api-pattern)
- [Event processing pattern](#event-processing-pattern)
- [Orchestration pattern](#orchestration-pattern)
- [Real-time streaming pattern](#real-time-streaming-pattern)
- [Async fan-out pattern](#async-fan-out-pattern)
- [Scheduled jobs pattern](#scheduled-jobs-pattern)
- [Choosing between patterns](#choosing-between-patterns)

---

## Pattern selection flowchart

```
What are you building?
│
├── Synchronous request/response API?
│   └── REST/HTTP API pattern
│
├── Processing events from a queue/stream/database?
│   └── Event processing pattern
│
├── Multi-step workflow with branching/error handling?
│   └── Orchestration pattern
│
├── Real-time bidirectional communication or LLM streaming?
│   └── Real-time streaming pattern
│
├── One event triggers multiple independent consumers?
│   └── Async fan-out pattern
│
└── Recurring task on a schedule?
    └── Scheduled jobs pattern
```

---

## REST/HTTP API pattern

```
Client → API Gateway (HTTP API) → Lambda → DynamoDB
                                         → S3 (binary storage)
```

**When:** CRUD APIs, mobile/web backends, microservices.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| API type | HTTP API (simpler) | REST API if you need WAF, caching, request validation, API keys |
| Auth | JWT authorizer (HTTP API native) | Cognito (REST: native Cognito authorizer; HTTP: JWT authorizer), Lambda authorizer (custom logic) |
| Database | DynamoDB (on-demand) | RDS Proxy + RDS if relational data needed |
| File storage | S3 with presigned URLs | Direct upload via API Gateway (10 MB limit) |
| Function pattern | One function per route | Lambdalith if team prefers Express/FastAPI style |

**Key constraints:**

- HTTP API: 30s hard timeout, no WAF, no caching, 10 MB payload
- REST API: 29s default timeout (adjustable for Regional/private APIs), 10 MB payload

---

## Event processing pattern

```
Event source → SQS → Lambda → DynamoDB / S3
                ↓
              DLQ (failed messages)
```

**When:** Async workloads, decoupled producers/consumers, batch processing, file processing.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| Buffer | SQS standard queue | SQS FIFO if ordering matters (10 msg batch limit) |
| Trigger | SQS event source mapping | S3 event notification → Lambda (file uploads) |
| Change data capture | DynamoDB Streams → Lambda | EventBridge Pipes → Lambda (no ESM needed) |
| Stream ingestion | SQS (simpler) | Kinesis (ordered replay, multiple consumers, high-throughput) |
| Error handling | SQS redrive policy (DLQ) | On-failure destination (SQS/SNS/S3) for streams |
| Concurrency control | MaximumConcurrency on ESM | Reserved concurrency on function |
| Batch processing | ReportBatchItemFailures | Powertools Batch Processor utility |

**Key constraints:**

- SQS visibility timeout ≥ 6× function timeout
- MaximumConcurrency and Provisioned Mode are mutually exclusive on same ESM
- Enable partial batch failure reporting to avoid reprocessing successful messages
- SQS event filtering automatically deletes unmatched messages (permanently — not sent to DLQ)

**S3 trigger constraints:**

- Recursive invocation risk: never write output to the same bucket/prefix that triggers the function
- No native DLQ on S3 notifications — use Lambda async invocation DLQ instead
- Use prefix/suffix filtering to limit which objects trigger the function
- Consider EventBridge for S3 instead of S3 notifications (richer filtering, multiple targets)

**DynamoDB Streams constraints:**

- Max 2 Lambda consumers per stream shard (use EventBridge Pipes for more)
- 24-hour stream retention — records expire and cannot be replayed after that
- Ordering guaranteed per partition key, not globally

---

## Orchestration pattern

```
Trigger → Step Functions → Lambda (validate)
                         → Choice (route by status)
                         → Parallel (fan-out)
                         → Lambda (aggregate) → DynamoDB
```

**When:** Multi-step workflows, saga transactions, approval chains, data pipelines, AI agent loops.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| Workflow type | Standard (exactly-once, up to 1 year) | Express (<5 min, high-volume; async=at-least-once, sync=at-most-once) |
| Simple data transforms | JSONata (inline, no Lambda needed) | Lambda task (complex logic) |
| Service calls | Direct SDK integration (200+ services) | Lambda intermediary (only if business logic needed) |
| Human approval | .waitForTaskToken | Durable Functions waitForCallback |
| AI agent loops | Step Functions + Bedrock | Durable Functions (code-first, checkpointed) |
| Error handling | Retry + Catch in ASL | Durable Functions try/catch in code |

**Key constraints:**

- 256 KB payload limit between states — use S3 for large data
- Express: no .sync, no .waitForTaskToken, no Distributed Map, no Activities
- 25,000 execution history entries (Standard) — split long workflows into child executions
- Prefer direct SDK integrations over Lambda intermediary functions to reduce latency

---

## Real-time streaming pattern

```
Client ←→ API Gateway WebSocket ←→ Lambda → DynamoDB (connections)
                                          → Bedrock (LLM responses)
```

Or for LLM token streaming:

```
Client → Lambda Function URL (streaming) → Bedrock ConverseStream
```

**When:** Chat apps, live dashboards, notifications, LLM token streaming, multiplayer games.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| Bidirectional | API Gateway WebSocket | AppSync subscriptions (GraphQL) |
| LLM streaming | Lambda Function URL + ConverseStream | REST API proxy with STREAM mode |
| Connection state | DynamoDB (connectionId → metadata) | ElastiCache (higher throughput) |
| Auth | $connect route authorizer | Cognito + custom auth in Lambda |

**Key constraints:**

- WebSocket: 10 min idle timeout, 2 hour max connection, 128 KB message (hard limit)
- Function URL streaming: 200 MB limit, 2 MBps after first 6 MB, Node.js native support
- Function URLs support `AWS_IAM` or `NONE` (public) — no native JWT/Cognito. Add CloudFront + Lambda@Edge for JWT/Cognito auth.

---

## Async fan-out pattern

```
Producer → EventBridge → Rule A → Lambda (process)
                       → Rule B → Step Functions (workflow)
                       → Rule C → SQS → Lambda (batch)
```

**When:** One event triggers multiple independent actions, event-driven microservices, cross-service communication.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| Event router | EventBridge (content-based routing) | SNS (simpler fan-out, attribute/body filtering) |
| Point-to-point | EventBridge Pipes (source→target, no Lambda intermediary) | SQS → Lambda ESM |
| Schema management | EventBridge Schema Registry + Discovery | Manual schema documentation |
| Cross-account | EventBridge cross-account rules | SNS cross-account subscriptions |
| Scheduling | EventBridge Scheduler (cron/rate) | EventBridge rules (simpler but less flexible) |

**Key constraints:**

- Use dedicated event bus per application domain (not the default bus)
- EventBridge Pipes eliminates Lambda intermediary functions for source→target integrations
- Be precise with event patterns — overly broad patterns risk loops
- Configure DLQs on all targets

---

## Scheduled jobs pattern

```
EventBridge Scheduler → Lambda (task)
                      → Step Functions (complex workflow)
```

**When:** Cron jobs, periodic data sync, report generation, cleanup tasks.

**Service selection:**

| Decision | Default | Alternative |
|---|---|---|
| Scheduler | EventBridge Scheduler (flexible, one-time + recurring) | EventBridge rules with schedule expression (simpler) |
| Short task (<15 min) | Lambda directly | — |
| Long task (>15 min) | Step Functions (up to 1 year) | Durable Functions |
| High frequency (<1 min) | Not supported natively | SQS delay queue + Lambda |

**Key constraints:**

- Minimum schedule interval: 1 minute
- Lambda max timeout: 15 minutes — use Step Functions for longer
- Always make scheduled Lambda idempotent (scheduler guarantees at-least-once)
- Use EventBridge Scheduler over EventBridge rules for new projects (more features, flexible time windows)

---

## Choosing between patterns

Most real applications combine multiple patterns:

```
                    ┌─ HTTP API ─── Lambda ─── DynamoDB
Client ─── CloudFront ─┤
                    └─ WebSocket ── Lambda ─── DynamoDB
                                      │
                                      ▼
                              EventBridge
                              ┌────┼────┐
                              ▼    ▼    ▼
                            SQS  SFN  Lambda
                              │    │
                              ▼    ▼
                           Lambda  Bedrock
```

**Common combinations:**

| Application | Patterns used |
|---|---|
| SaaS API backend | REST API + Event processing + Scheduled jobs |
| E-commerce | REST API + Orchestration (order saga) + Fan-out (notifications) |
| Data pipeline | Scheduled jobs + Event processing + Orchestration |
| AI chatbot | Real-time streaming + Orchestration (agent loop) |
| IoT processing | Event processing + Fan-out + Scheduled jobs (aggregation) |

**Begin with a single pattern and add more as requirements grow.** A CRUD API with DynamoDB covers most initial implementations. Add event processing when you need async work. Add orchestration when you need multi-step workflows. Add fan-out when you need cross-service communication.
