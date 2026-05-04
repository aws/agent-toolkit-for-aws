# Production-Ready Serverless on AWS

Quick-reference for shipping Lambda workloads to production. Covers the pre-deployment checklist, architecture trade-offs, and operational patterns for production traffic.

## Contents

- [Production readiness checklist](#production-readiness-checklist)
- [Architecture decisions](#architecture-decisions)
- [Observability](#observability)
- [Security hardening](#security-hardening)
- [Testing strategies](#testing-strategies)
- [Idempotency patterns](#idempotency-patterns)
- [Response streaming](#response-streaming)
- [Anti-patterns](#anti-patterns)

---

## Production readiness checklist

Walk through every item before the first production deployment.

### Compute

- [ ] Memory right-sized (use AWS Lambda Power Tuning or load testing)
- [ ] Timeout set explicitly (P99 + buffer, never the 3 s default)
- [ ] Reserved concurrency configured to protect downstream systems
- [ ] Dead-letter queue (DLQ) or on-failure destination for every async invocation
- [ ] Environment variables for all config (bucket names, table names, endpoints)
- [ ] Code signing enabled (if compliance requires it)
- [ ] SDK clients initialized outside handler (reuse across warm invocations)
- [ ] Deployment package size minimized (exclude tests, docs, unused dependencies)

### Observability

- [ ] Structured JSON logging via Powertools Logger
- [ ] X-Ray active tracing enabled
- [ ] Custom metrics emitted via Embedded Metric Format (EMF)
- [ ] CloudWatch Alarms on Errors, Throttles, Duration P99, IteratorAge, ConcurrentExecutions, DLQ depth
- [ ] Log retention policy set — do not leave at unlimited
- [ ] Correlation IDs propagated to downstream services
- [ ] Lambda Insights enabled for system-level metrics (CPU, memory, network)

### Security

- [ ] One IAM execution role per function, scoped to exact resource ARNs
- [ ] No secrets in environment variables — use Secrets Manager / SSM with caching
- [ ] Input validation on every event payload (JSON Schema, Zod, Pydantic)
- [ ] VPC placement only when required (RDS, ElastiCache); VPC endpoints for AWS services
- [ ] GuardDuty Lambda Protection enabled
- [ ] Security Hub Lambda controls enabled
- [ ] Dependency scanning in CI (`npm audit`, `pip-audit`, Snyk)
- [ ] Amazon Inspector Lambda scanning enabled
- [ ] Function URLs use `AWS_IAM` auth (not `NONE`) in production

### Reliability

- [ ] Every handler is idempotent
- [ ] Partial batch failure reporting enabled (SQS, Kinesis, DynamoDB Streams)
- [ ] `BisectBatchOnFunctionError` enabled for stream sources (isolates poison records)
- [ ] Retry config tuned — `MaximumRetryAttempts`, `MaximumEventAgeInSeconds`
- [ ] Circuit breakers on downstream HTTP calls
- [ ] Reserved concurrency = 0 documented as emergency kill switch
- [ ] Graceful error handling — catch, log, and return meaningful errors (no unhandled exceptions)

### Deployment

- [ ] Aliases + weighted traffic shifting (or CodeDeploy canary/linear)
- [ ] Rollback alarms wired into the deployment pipeline
- [ ] All infrastructure defined in code (CDK, SAM, or CloudFormation)
- [ ] Separate AWS accounts for dev, staging, production
- [ ] Automated smoke tests run post-deployment before full traffic shift
- [ ] Pre-traffic hooks (BeforeAllowTraffic) validate function health before shifting

---

## Architecture decisions

### Monolith Lambda vs micro-Lambda

| Aspect | Lambdalith (single function) | Micro-Lambda (function per route) |
|---|---|---|
| Cold starts | One function to warm; larger package | Many functions; smaller, faster init |
| IAM granularity | Single broad role | Per-function least-privilege |
| Deployment | Everything together; simpler CI/CD | Independent; more pipeline complexity |
| Observability | One log group; harder per-route metrics | Per-function metrics, alarms, logs |
| Scaling | Single concurrency pool | Independent scaling + reserved concurrency per function |
| DX | Familiar Express/FastAPI style | More AWS-native; requires IaC discipline |

**Guidance**: Prefer micro-Lambda for greenfield (least privilege, independent scaling, granular observability). Use Lambdalith when migrating existing Express/FastAPI apps or when team size makes deployment simplicity more valuable than granularity.

### Function URLs vs API Gateway

| Feature | Function URLs | API Gateway (HTTP API) | API Gateway (REST API) |
|---|---|---|---|
| Auth | IAM only (or in-code) | IAM, JWT, Lambda authorizers | IAM, Cognito, Lambda authorizers, API keys |
| Rate limiting | None built-in | Built-in throttling | Throttling + usage plans |
| Response streaming | Yes (native) | No | Yes (proxy integration) |
| Custom domains | Via CloudFront | Built-in | Built-in |
| WAF | No (use CloudFront) | No (use CloudFront) | Yes |
| Request validation | None | None | JSON Schema |
| Caching | Via CloudFront | None | Built-in |
| WebSocket | No | No | No (separate WebSocket API required) |

**Use Function URLs** for: internal service-to-service (IAM auth), Lambdalith + CloudFront, streaming, webhook receivers.

**Use API Gateway** for: public APIs needing rate limiting, JWT/Cognito auth, multi-function path routing, WAF without CloudFront.

### Reserved vs Provisioned Concurrency

| Aspect | Reserved Concurrency | Provisioned Concurrency |
|---|---|---|
| Purpose | Guarantee capacity + protect downstream | Eliminate cold starts |
| Cold starts | Still possible | Eliminated (pre-warmed) |
| Throttling | Throttles at the limit | Spills to on-demand beyond provisioned |
| Use case | Protect a database; guarantee capacity | Latency-sensitive APIs; payment processing |

Decision flow:

1. **Need to limit scaling** → Reserved concurrency
2. **Need to eliminate cold starts** → Provisioned concurrency (try SnapStart first — no additional cost for Java; caching + restore charges for Python/.NET)
3. **Need both** → Set provisioned ≤ reserved; reserved acts as the ceiling

---

## Observability

### Powertools setup (Python / TypeScript / Java / .NET)

**Logger** — structured JSON, correlation IDs injected automatically, log level via env var.

**Tracer** — wraps X-Ray SDK; auto-captures AWS SDK calls, HTTP requests, handler. Add custom subsegments for critical paths. Annotate traces with business keys (customer ID, order ID) for filtering.

**Metrics** — emits via Embedded Metric Format. Zero latency impact.

### EMF vs PutMetricData

| | EMF (Powertools Metrics) | `PutMetricData` API |
|---|---|---|
| Latency impact | Zero — writes to stdout | Synchronous API call (~5–20 ms) |
| Complexity | One-liner with Powertools | Manual batching, error handling |
| Recommendation | **Use this** | Avoid in hot paths |

### Minimum alarm set

Set these six alarms on every production function:

| Alarm | Metric | Threshold | Period | Why |
|---|---|---|---|---|
| Error rate | `Errors / Invocations` | > 1 % | 5 min | Catch bugs and upstream failures |
| Throttles | `Throttles` | > 0 | 5 min | Concurrency limit hit |
| Duration P99 | `Duration` P99 | > 80 % of timeout | 5 min | Catch slow functions before timeout |
| Iterator age | `IteratorAge` | > 60 s | 5 min | Stream processing falling behind |
| Concurrent executions | `ConcurrentExecutions` | > 80 % of reserved | 5 min | Approaching throttle threshold |
| DLQ depth | SQS `ApproximateNumberOfMessagesVisible` | > 0 | 5 min | Failed messages accumulating |

### Log retention

Set retention when creating log groups. Defaults to "never expire" — storage accumulates continuously. Choose a retention period based on your compliance and debugging needs.

---

## Security hardening

### One role per function

Never share IAM roles across functions. Scope every policy to specific resource ARNs:

```yaml
# Good
Effect: Allow
Action: dynamodb:PutItem
Resource: arn:aws:dynamodb:us-east-1:123456789012:table/OrdersTable

# Bad
Effect: Allow
Action: dynamodb:*
Resource: "*"
```

Use IAM Access Analyzer to identify unused permissions and generate least-privilege policies.

### Secrets management

- Store in **Secrets Manager** or **SSM Parameter Store** (SecureString)
- Cache in the execution environment with **Powertools Parameters** (avoids API call per invocation)
- Rotate automatically via Secrets Manager rotation Lambdas
- Environment variables are visible in the Lambda console and API — never put secrets there

### Input validation

Validate at the handler boundary before business logic runs:

| Language | Library |
|---|---|
| TypeScript | Zod, io-ts, JSON Schema |
| Python | Pydantic, Powertools Validation (JSON Schema) |
| Java | Bean Validation (JSR 380), JSON Schema |

Powertools Validation supports envelope extraction for API Gateway, SQS, EventBridge, etc.

### VPC: endpoints over NAT Gateway

If your function must be in a VPC, use **VPC endpoints** for AWS service access instead of NAT Gateway:

| | VPC Endpoint | NAT Gateway |
|---|---|---|
| Latency | Lower (stays on AWS backbone) | Higher (extra hop) |

Create endpoints for: DynamoDB (gateway), S3 (gateway), SQS, Secrets Manager, SSM, KMS.

---

## Testing strategies

### The serverless testing pyramid (inverted)

```
        ┌─────────────┐
        │   E2E Tests  │  Few — full workflow verification
        ├─────────────┤
        │ Integration  │  Many — THIS IS THE MOST VALUABLE LAYER
        │  (in cloud)  │  Test real service interactions
        ├─────────────┤
        │  Unit Tests  │  Fast — pure business logic only
        └─────────────┘
```

Serverless apps are primarily about service integrations, not complex business logic. Integration tests in the cloud detect the most impactful defects.

### Structure code for testability

```
handler (thin adapter)
  → extract + validate event
  → call business logic (pure functions — unit test these)
  → call AWS services (integration test these in the cloud)
```

### What to test where

| Layer | What | How |
|---|---|---|
| Unit | Business logic (calculations, transforms, validation) | Local, fast, mocked dependencies |
| Integration | Service contracts (DynamoDB reads/writes, SQS send/receive, IAM permissions) | Deploy to AWS, test against real services |
| E2E | Full workflows (API → Lambda → DynamoDB → Stream → Lambda → SQS) | Dedicated staging environment; poll for async side effects |

### Fast iteration

- **`sam sync`** — hot-deploys code changes to AWS in seconds
- **`cdk watch`** — watches for file changes and auto-deploys
- Each developer gets an isolated test stack (separate account or prefixed stack name)

### What NOT to do

- Don't rely on LocalStack / DynamoDB Local as primary testing — they diverge from real AWS (IAM, quotas, error codes)
- Don't mock AWS SDK calls for integration tests — you'll miss permission and config issues
- Don't skip cloud testing because "it's slow" — use `sam sync` / `cdk watch`

---

## Idempotency patterns

Lambda guarantees **at-least-once** execution. Duplicates happen from: async retries, SQS visibility timeout expiry, stream shard replays, client retries on timeout, Step Functions task retries.

### Powertools Idempotency utility

Uses DynamoDB to track processed events. Available for Python, TypeScript, Java, .NET.

**Python:**

```python
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer, idempotent
)

persistence = DynamoDBPersistenceLayer(table_name="IdempotencyTable")

@idempotent(persistence_store=persistence)
def handler(event, context):
    payment = process_payment(event)
    return {"statusCode": 200, "body": payment}
```

**TypeScript:**

```typescript
import { makeIdempotent } from "@aws-lambda-powertools/idempotency";
import { DynamoDBPersistenceLayer } from "@aws-lambda-powertools/idempotency/dynamodb";

const persistence = new DynamoDBPersistenceLayer({ tableName: "IdempotencyTable" });

export const handler = makeIdempotent(async (event) => {
  const payment = await processPayment(event);
  return { statusCode: 200, body: JSON.stringify(payment) };
}, { persistenceStore: persistence });
```

### DynamoDB table design

```
Table: IdempotencyTable
  PK: id (String)          — hash of the idempotency key
  Attributes:
    status:     INPROGRESS | COMPLETED | EXPIRED
    data:       cached response payload
    expiration: TTL epoch timestamp
  TTL attribute: expiration
```

### Choosing the idempotency key

| Event source | Key |
|---|---|
| SQS | `messageId` |
| EventBridge | `detail.id` or composite of event fields |
| DynamoDB Streams | `eventID` |
| API Gateway / Function URL | `Idempotency-Key` header or request body hash |
| Step Functions | Execution ID + task token |

### TTL for cleanup

Set TTL based on how long duplicates can arrive. Typical values:

- API retries: 1 hour
- SQS retries: match the queue's `maxReceiveCount` × visibility timeout
- Stream replays: 24 hours (Kinesis retention default)

DynamoDB automatically deletes expired items (typically within a few days of TTL expiry).

---

## Response streaming

### When to use

| Use case | Why streaming helps |
|---|---|
| Large payloads (> 6 MB) | Buffered limit is 6 MB; streaming supports up to 200 MB |
| TTFB-sensitive responses | Client sees partial data immediately (HTML shell, then content) |
| Server-sent events (SSE) | Real-time updates to browser clients |
| LLM / AI token streaming | Stream tokens as generated (conversational AI-style) |
| Large file generation | CSV/PDF rows streamed as produced |

### Constraints

- **Function URLs** are simplest for streaming. REST API also supports streaming via proxy integration with STREAM transfer mode. HTTP API does **not** support streaming.
- **200 MB** response limit
- **2 MBps** bandwidth cap after the first 6 MB
- Billed for full function duration even if client disconnects
- Node.js has native support; other runtimes use custom runtime or Lambda Web Adapter
- **Function URL streaming is NOT supported for VPC-attached functions.** Use the `InvokeWithResponseStream` API as an alternative.

### Node.js example

```javascript
export const handler = awslambda.streamifyResponse(
  async (event, responseStream, context) => {
    const metadata = {
      statusCode: 200,
      headers: { "Content-Type": "text/html" },
    };
    responseStream = awslambda.HttpResponseStream.from(responseStream, metadata);

    responseStream.write("<html><body>");
    for (const chunk of generateContent()) {
      responseStream.write(chunk);
    }
    responseStream.write("</body></html>");
    responseStream.end();
  }
);
```

### When NOT to use

- Small JSON responses (< 6 MB) — buffered is simpler
- When you need API Gateway features (rate limiting, caching, WAF) without CloudFront
- VPC-based functions needing Function URL streaming (use `InvokeWithResponseStream` API instead)

---

## Sources

- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [Lambda Concurrency and Scaling](https://docs.aws.amazon.com/lambda/latest/dg/lambda-concurrency.html)
- [Response Streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html)
- [How to Test Serverless Functions](https://docs.aws.amazon.com/lambda/latest/dg/testing-guide.html)
- [Serverless Applications Lens — Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html)
- [Powertools for AWS Lambda](https://docs.powertools.aws.dev/lambda/)

---

## Anti-patterns

Common mistakes that cause production issues in serverless applications. Each pairs the problem with the correct alternative.

### Avoid: Lambda calling Lambda synchronously

Synchronous Lambda-to-Lambda invocation doubles latency, creates tight coupling, and makes error handling fragile.

```python
# BAD: Direct synchronous invocation
lambda_client.invoke(FunctionName='downstream', InvocationType='RequestResponse', Payload=json.dumps(event))
```

### Instead: Use Step Functions or SQS

```python
# GOOD: Decouple via SQS
sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(event))
```

Or use Step Functions for orchestration when you need the result.

---

### Avoid: Monolithic handler without intentional design

Routing logic stuffed into a single handler without considering trade-offs prevents independent scaling, broadens IAM blast radius, and increases cold start times.

```python
# BAD: One function handling all routes without considering trade-offs
def handler(event, context):
    path = event['path']
    if path == '/users': return handle_users(event)
    elif path == '/orders': return handle_orders(event)
    elif path == '/products': return handle_products(event)
```

### Instead: Choose deliberately

For greenfield projects, prefer one function per route (least privilege, independent scaling, granular observability). For migrations from Express/FastAPI or small teams prioritizing deployment simplicity, a Lambdalith is a valid choice — see [Architecture decisions](#architecture-decisions) for trade-offs.

---

### Avoid: Secrets in environment variables

Visible in console and API, 4 KB total limit for all environment variables combined.

```python
# BAD: Secret in env var
db_password = os.environ['DB_PASSWORD']
```

### Instead: Use Secrets Manager with Powertools caching

```python
# GOOD: Cached secret retrieval
from aws_lambda_powertools.utilities import parameters
db_password = parameters.get_secret("my-db-secret", max_age=300)
```

---

### Avoid: Skipping idempotency

Lambda delivers at-least-once; duplicates cause duplicate records.

### Instead: Use Powertools Idempotency

```python
from aws_lambda_powertools.utilities.idempotency import idempotent, DynamoDBPersistenceLayer

persistence = DynamoDBPersistenceLayer(table_name="IdempotencyTable")

@idempotent(persistence_store=persistence)
def handler(event, context):
    return process_payment(event)
```

---

### Avoid: VPC when not needed

Adds cold start latency. Only attach Lambda to a VPC for private resources (RDS, ElastiCache, Elasticsearch). Use VPC endpoints for AWS service access instead.

---

### Avoid: Default 3s timeout

Legitimate requests fail silently. Set timeout based on load-test P99 + buffer. Set SDK/HTTP client timeouts shorter than Lambda timeout to get meaningful errors instead of generic timeouts.

---

### Avoid: Missing DLQ

Failed async invocations and event source messages are discarded without notification. Configure dead-letter queues on all async invocations and event source mappings.

---

### Avoid: CloudWatch Logs retention = forever

Storage accumulates continuously. Set a retention period — do not leave at unlimited.
