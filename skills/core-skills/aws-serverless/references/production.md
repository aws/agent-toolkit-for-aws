# Production-Ready Serverless on AWS

Pre-deployment checklist, architecture trade-offs, and operational patterns. Concise on purpose — the value here is the structured checklist and opinionated defaults, not API syntax.

## Contents

- [Production readiness checklist](#production-readiness-checklist)
- [Architecture decisions](#architecture-decisions)
- [Observability](#observability)
- [Idempotency](#idempotency)
- [Response streaming](#response-streaming)
- [Anti-patterns](#anti-patterns)

---

## Production readiness checklist

### Compute

- [ ] Memory right-sized (Power Tuning / load test)
- [ ] Timeout set explicitly (P99 + buffer — never the 3s default)
- [ ] Reserved concurrency set to protect downstream
- [ ] DLQ / on-failure destination on every async invocation and ESM
- [ ] Config via env vars; SDK clients initialized outside the handler
- [ ] Deployment package minimized (exclude tests, docs, unused deps)

### Observability

- [ ] Structured JSON logging (Powertools Logger) + correlation IDs propagated
- [ ] X-Ray active tracing
- [ ] Custom metrics via EMF
- [ ] Alarms on Errors, Throttles, Duration P99, IteratorAge, ConcurrentExecutions, DLQ depth (see below)
- [ ] Log retention set — **not** unlimited
- [ ] Log group encryption with customer managed KMS key when compliance requires it
- [ ] Lambda Insights enabled

### Security

- [ ] One IAM role per function, scoped to exact resource ARNs
- [ ] No secrets in env vars — Secrets Manager / SSM (SecureString) with Powertools caching
- [ ] Input validation at the handler boundary (Zod / Pydantic / Powertools Validation)
- [ ] VPC only when required (RDS, ElastiCache); VPC endpoints for AWS services
- [ ] GuardDuty Lambda Protection, Security Hub Lambda controls, Inspector Lambda scanning, CI dependency scanning
- [ ] Function URLs use `AWS_IAM` auth (not `NONE`) in production
- [ ] SQS queues use SSE-KMS for encryption at rest when compliance requires customer managed keys (SSE-SQS is enabled by default)
- [ ] DynamoDB tables use customer managed KMS keys when compliance requires key control (AWS owned encryption is enabled by default)
- [ ] Enforce HTTPS-only access with `aws:SecureTransport` condition in resource policies (S3 buckets, SQS queues)

### Reliability

- [ ] Every handler idempotent
- [ ] Partial batch failure reporting (SQS, Kinesis, DynamoDB Streams)
- [ ] `BisectBatchOnFunctionError` for stream sources
- [ ] Retry config tuned (`MaximumRetryAttempts`, `MaximumEventAgeInSeconds`)
- [ ] Reserved concurrency = 0 documented as the emergency kill switch
- [ ] No unhandled exceptions — catch, log, return meaningful errors

### Deployment

- [ ] Aliases + weighted shifting (or CodeDeploy canary/linear) with rollback alarms
- [ ] All infra in code (CDK/SAM/CloudFormation)
- [ ] Separate accounts for dev/staging/prod
- [ ] Post-deploy smoke tests + pre-traffic hooks before full shift

---

## Architecture decisions

### Lambdalith vs micro-Lambda

Prefer **micro-Lambda** (function per route) for greenfield: per-function least-privilege IAM, independent scaling + reserved concurrency, granular observability, smaller/faster cold starts. Use a **Lambdalith** when migrating an existing Express/FastAPI app or when a small team values deployment simplicity over granularity.

### Reserved vs Provisioned Concurrency

Reserved = guarantee capacity + protect downstream (cold starts still possible, throttles at the limit). Provisioned = eliminate cold starts (spills to on-demand beyond the count). Need both → provisioned ≤ reserved. Try **SnapStart** before Provisioned for Java/Python 3.12+/.NET 8+ (no cost for Java). See [concurrency.md](concurrency.md).

---

## Observability

Use Powertools **Logger** (structured JSON, auto correlation IDs), **Tracer** (wraps X-Ray, auto-captures SDK/HTTP calls; annotate traces with business keys), **Metrics** (EMF — zero latency, writes to stdout vs ~5–20ms for synchronous `PutMetricData`; avoid `PutMetricData` in hot paths).

### Minimum alarm set (every production function)

| Alarm | Metric | Threshold | Why |
|---|---|---|---|
| Error rate | `Errors / Invocations` | > 1% | Bugs / upstream failures |
| Throttles | `Throttles` | > 0 | Concurrency limit hit |
| Duration P99 | `Duration` P99 | > 80% of timeout | Catch slow functions before timeout |
| Iterator age | `IteratorAge` | > 60s | Stream processing falling behind |
| Concurrent executions | `ConcurrentExecutions` | > 80% of reserved | Approaching throttle threshold |
| DLQ depth | SQS `ApproximateNumberOfMessagesVisible` | > 0 | Failed messages accumulating |

Set **log retention** when creating log groups — the default is "never expire."

### Testing

Serverless apps are mostly about **service integrations**, not complex business logic — so the **integration layer (tested in the cloud) is the most valuable**, with few unit tests (pure logic) and few E2E. Structure handlers as thin adapters calling pure functions. Don't rely on LocalStack/DynamoDB Local as primary testing (they diverge on IAM, quotas, error codes); don't mock AWS SDK calls for integration tests. Iterate fast with `sam sync` / `cdk watch`; give each developer an isolated stack.

---

## Idempotency

Lambda guarantees **at-least-once** — duplicates come from async retries, SQS visibility expiry, stream replays, client retries, Step Functions task retries. Use the **Powertools Idempotency** utility (Python/TS/Java/.NET), backed by a DynamoDB table with TTL.

Table: `id` (hash of idempotency key) + `status` (INPROGRESS/COMPLETED/EXPIRED), `data` (cached response), `expiration` (TTL).

Idempotency key by source:

| Source | Key |
|---|---|
| SQS | `messageId` |
| EventBridge | `detail.id` or composite |
| DynamoDB Streams | `eventID` |
| API Gateway / Function URL | `Idempotency-Key` header or body hash |
| Step Functions | Execution ID + task token |

TTL ≈ how long duplicates can arrive (API retries ~1h; SQS ≈ `maxReceiveCount` × visibility; stream replays ~24h).

---

## Response streaming

Use for payloads > 6 MB (buffered limit), TTFB-sensitive responses, SSE, LLM token streaming, or large file generation.

- **Function URLs** are simplest; REST API also supports streaming (proxy, STREAM mode); **HTTP API does not**.
- **200 MB** response limit; **2 MBps** cap after the first 6 MB.
- Billed for full duration even if the client disconnects.
- Node.js has native support (`awslambda.streamifyResponse` + `awslambda.HttpResponseStream.from`); other runtimes need a custom runtime or Lambda Web Adapter.
- **Not supported for VPC-attached functions via Function URL** — use the `InvokeWithResponseStream` API instead.

Don't stream small JSON (< 6 MB) — buffered is simpler.

---

## Anti-patterns

- **Lambda calling Lambda synchronously** — doubles latency, tight coupling, fragile error handling. Decouple via SQS, or use Step Functions when you need the result.
- **Unintentional monolithic handler** — routing stuffed into one function without weighing trade-offs prevents independent scaling and broadens IAM blast radius. Choose Lambdalith vs micro-Lambda deliberately (see above).
- **Secrets in env vars** — visible in console/API, 4 KB total cap. Use Secrets Manager with Powertools caching.
- **Skipping idempotency** — at-least-once delivery causes duplicate records.
- **VPC when not needed** — adds cold-start latency. Only for private resources; use VPC endpoints for AWS services.
- **Default 3s timeout** — legitimate requests fail silently. Set SDK/HTTP client timeouts shorter than the Lambda timeout for meaningful errors.
- **Missing DLQ** — failed async invocations / ESM messages are discarded silently.
- **Log retention = forever** — storage accumulates continuously.

---

## Sources

- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [Lambda Concurrency and Scaling](https://docs.aws.amazon.com/lambda/latest/dg/lambda-concurrency.html)
- [Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [Testing serverless functions](https://docs.aws.amazon.com/lambda/latest/dg/testing-guide.html)
- [Serverless Applications Lens — Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html)
- [Powertools for AWS Lambda](https://docs.powertools.aws.dev/lambda/)
