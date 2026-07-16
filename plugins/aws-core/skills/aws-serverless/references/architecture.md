# Serverless Architecture Patterns

Pattern selection and the opinionated service defaults / constraints for each. The patterns themselves are standard — the value here is the default-vs-alternative choices and the non-obvious constraints.

## Pattern selection

| What you're building | Pattern |
|---|---|
| Synchronous request/response API | REST/HTTP API → Lambda → DynamoDB |
| Processing events from a queue/stream/database | Event processing (SQS/Streams → Lambda) |
| Multi-step workflow with branching/error handling | Orchestration (Step Functions) |
| Real-time bidirectional / LLM streaming | WebSocket API or Function URL streaming |
| One event → multiple independent consumers | Async fan-out (EventBridge / SNS) |
| Recurring task on a schedule | EventBridge Scheduler → Lambda / Step Functions |

Most real apps combine several. Start with one (a CRUD API on DynamoDB covers most initial needs); add event processing for async work, orchestration for multi-step workflows, fan-out for cross-service comms.

---

## REST/HTTP API pattern

CRUD APIs, mobile/web backends, microservices.

| Decision | Default | Alternative |
|---|---|---|
| API type | HTTP API (simpler) | REST API for WAF, caching, request validation, API keys |
| Auth | JWT authorizer (HTTP API native) | Cognito (REST native), Lambda authorizer (custom logic) |
| Database | DynamoDB (on-demand) | RDS Proxy + RDS for relational data |
| File storage | S3 presigned URLs | Direct upload via API Gateway (10 MB limit) |
| Function pattern | One function per route | Lambdalith for Express/FastAPI migrations |

Constraints: HTTP API 30s hard timeout, no WAF/caching; REST API 29s default (adjustable for Regional/private). Both 10 MB payload.

---

## Event processing pattern

Async workloads, decoupled producers/consumers, batch/file processing.

| Decision | Default | Alternative |
|---|---|---|
| Buffer | SQS standard | SQS FIFO if ordering matters (10-msg batch) |
| Trigger | SQS ESM | S3 event notification → Lambda (file uploads) |
| Change data capture | DynamoDB Streams → Lambda | EventBridge Pipes → Lambda (no ESM) |
| Stream ingestion | SQS (simpler) | Kinesis (ordered replay, multiple consumers, high-throughput) |
| Error handling | SQS redrive policy (DLQ) | On-failure destination for streams |
| Concurrency control | `MaximumConcurrency` on ESM | Reserved concurrency on function |

Constraints: SQS visibility ≥ 6× function timeout; `MaximumConcurrency` and Provisioned Mode mutually exclusive on one ESM; SQS filter drops unmatched messages permanently. **S3 triggers:** never write output to the triggering bucket/prefix (recursion); no native DLQ (use Lambda async DLQ); consider EventBridge for S3 (richer filtering). **DynamoDB Streams:** max 2 consumers/shard, 24h retention, ordering per partition key only.

---

## Orchestration pattern

Multi-step workflows, saga transactions, approval chains, data pipelines, AI agent loops.

| Decision | Default | Alternative |
|---|---|---|
| Workflow type | Standard (exactly-once, ≤ 1 year) | Express (< 5 min, high-volume) |
| Simple transforms | JSONata (inline, no Lambda) | Lambda task (complex logic) |
| Service calls | Direct SDK integration (200+ services) | Lambda intermediary (only if business logic needed) |
| Human approval | `.waitForTaskToken` | Lambda durable functions `waitForCallback` |
| AI agent loops | Step Functions + Bedrock | Lambda durable functions (code-first, checkpointed) |

Constraints: 256 KiB between states (use S3 for large data); Express lacks `.sync`/`.waitForTaskToken`/Distributed Map/Activities; 25,000 history entries (Standard). See [orchestration.md](orchestration.md).

---

## Real-time streaming pattern

Chat, live dashboards, notifications, LLM token streaming, multiplayer.

| Decision | Default | Alternative |
|---|---|---|
| Bidirectional | API Gateway WebSocket | AppSync subscriptions (GraphQL) |
| LLM streaming | Lambda Function URL + ConverseStream | REST API proxy with STREAM mode |
| Connection state | DynamoDB (connectionId → metadata, TTL to clean up after 2h max) | ElastiCache (higher throughput) |
| Auth | `$connect` route authorizer | Cognito + custom auth in Lambda |

Constraints: WebSocket 10-min idle / 2-hour max / 128 KB message; Function URL streaming 200 MB, 2 MBps after first 6 MB, Node.js native. **For streaming behind CloudFront, Function URLs should use `AWS_IAM` auth** — use Origin Access Control to sign requests rather than setting auth to `NONE`; if `NONE` is unavoidable, enforce auth at the edge (CloudFront + Lambda@Edge). (For a deliberately public, browser-reachable URL with no edge in front, `NONE` is the intended auth type — see [Function URLs in lambda.md](lambda.md#function-urls) for the required permissions.)

---

## Async fan-out pattern

One event → multiple independent actions; event-driven microservices.

| Decision | Default | Alternative |
|---|---|---|
| Event router | EventBridge (content-based routing) | SNS (simpler fan-out, attribute/body filtering) |
| Point-to-point | EventBridge Pipes (no Lambda glue) | SQS → Lambda ESM |
| Schema management | EventBridge Schema Registry + Discovery | Manual docs |
| Cross-account | EventBridge cross-account rules | SNS cross-account subscriptions |
| Scheduling | EventBridge Scheduler (cron/rate) | EventBridge rules with schedule expression |

Constraints: dedicated event bus per domain (not the default bus); be precise with patterns (broad patterns risk loops); DLQs on all targets.

---

## Scheduled jobs pattern

Cron jobs, periodic sync, report generation, cleanup.

| Decision | Default | Alternative |
|---|---|---|
| Scheduler | EventBridge Scheduler (flexible, one-time + recurring) | EventBridge rules schedule expression (simpler) |
| Short task (< 15 min) | Lambda directly | — |
| Long task (> 15 min) | Step Functions (≤ 1 year) | Lambda durable functions |
| High frequency (< 1 min) | Not supported natively | SQS delay queue + Lambda |

Constraints: minimum interval 1 minute; always make scheduled Lambdas idempotent (at-least-once); prefer EventBridge Scheduler over rules for new projects (flexible time windows).

---

## Common combinations

| Application | Patterns |
|---|---|
| SaaS API backend | REST API + Event processing + Scheduled jobs |
| E-commerce | REST API + Orchestration (order saga) + Fan-out (notifications) |
| Data pipeline | Scheduled jobs + Event processing + Orchestration |
| AI chatbot | Real-time streaming + Orchestration (agent loop) |
| IoT processing | Event processing + Fan-out + Scheduled jobs (aggregation) |
