# AWS Lambda Reference

Specific values, limits, constraints, and code that complement general Lambda knowledge.

## Contents

- [Cold Start Optimization](#cold-start-optimization)
- [Packaging](#packaging)
- [Memory and Timeout Tuning](#memory-and-timeout-tuning)
- [VPC Connectivity](#vpc-connectivity)
- [Execution Roles](#execution-roles)
- [Runtime Lifecycle](#runtime-lifecycle)
- [Powertools for AWS Lambda](#powertools-for-aws-lambda)

---

## Cold Start Optimization

### SnapStart

Snapshots the initialized execution environment (Firecracker microVM memory + disk) and restores from cache instead of cold-booting.

**Supported runtimes:** Java 11+, Python 3.12+, .NET 8+
**NOT supported:** Node.js, Ruby, container images, OS-only runtimes

**Constraints:**

- Mutually exclusive with Provisioned Concurrency
- Mutually exclusive with Amazon EFS
- Ephemeral storage must be ≤ 512 MB
- Only works on published versions (not `$LATEST`)
- Java: no additional SnapStart overhead
- Python/.NET: caching charge (based on memory, minimum 3 hours) + per-restore charge

**Restoration considerations:**

- Generate unique IDs/secrets in the handler, not during init (snapshot reuse)
- Re-establish network connections in the handler (connections are stale after restore)
- Refresh cached timestamps/credentials in the handler

**CDK example (Python):**

```python
from aws_cdk import aws_lambda as lambda_

fn = lambda_.Function(self, "MyFunction",
    runtime=lambda_.Runtime.PYTHON_3_13,
    handler="index.handler",
    code=lambda_.Code.from_asset("lambda"),
    snap_start=lambda_.SnapStartConf.ON_PUBLISHED_VERSIONS,
)
version = fn.current_version
```

### Provisioned Concurrency

Pre-initializes execution environments that stay warm permanently.

- A single instance handles one concurrent request at a time; throughput per instance = 1 / function duration
- Account-level RPS quota: 10 × total concurrency (applies across all invocations, not per instance)
- Supports auto-scaling via Application Auto Scaling
- Lambda can scale beyond provisioned count using on-demand instances
- **Paid even when idle** — disable in dev/staging

```typescript
const fn = new lambda.Function(this, 'MyFunction', {
  runtime: lambda.Runtime.NODEJS_22_X,
  handler: 'index.handler',
  code: lambda.Code.fromAsset('lambda'),
});

const version = fn.currentVersion;
const alias = new lambda.Alias(this, 'ProdAlias', {
  aliasName: 'prod',
  version,
  provisionedConcurrentExecutions: 10,
});
```

### Graviton (arm64)

- **Up to 34% better price-performance** compared to x86 (per AWS)
- Supported for all Lambda managed runtimes
- Set `architecture: lambda_.Architecture.ARM_64` in CDK

### Strategy Selection

| Scenario | Strategy |
|---|---|
| Java/Python/.NET with heavy init | SnapStart |
| Strict <50ms cold start | Provisioned Concurrency |
| Tolerant of occasional cold starts | On-demand + minimize package |
| Predictable traffic | Provisioned Concurrency + auto-scaling |
| General optimization | arm64 (Graviton) |

---

## Packaging

### Decision Tree

```
Need > 250 MB uncompressed?
  └─ YES → Container image (up to 10 GB)
  └─ NO
      ├─ Sharing deps across multiple functions?
      │   └─ YES → Lambda layers
      └─ NO
          ├─ Simple function, few deps → .zip
          └─ Native binaries, complex build → Container image
```

### Size Limits

| Package Type | Limit |
|---|---|
| .zip compressed | 50 MB |
| .zip uncompressed (including layers) | 250 MB |
| Container image | 10 GB |
| Layers per function | 5 |

### Layer Paths by Runtime

| Runtime | Layer Path |
|---|---|
| Python | `python/` or `python/lib/python3.x/site-packages/` |
| Node.js | `nodejs/node_modules/` |
| Java | `java/lib/` |
| Ruby | `ruby/gems/3.4.0/` or `ruby/lib/` |
| All runtimes | `bin/` (PATH), `lib/` (LD_LIBRARY_PATH) |

**Layer constraints:**

- Layers count toward the 250 MB unzipped limit
- Layers only work with .zip deployments, NOT container images
- Not recommended for Go/Rust — bundle deps in the deployment package
- Multiple layers with conflicting dependency versions cause subtle bugs; merge order matters

### Container Image Dockerfile

```dockerfile
FROM public.ecr.aws/lambda/python:3.13

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ${LAMBDA_TASK_ROOT}

CMD ["app.handler"]
```

- Use official AWS base images from `public.ecr.aws/lambda/`
- Container images do NOT support Lambda layers
- SnapStart is NOT supported with container images

### Python Build Tips

Use `uv` for dependency installation — **10-100x faster than pip**:

```bash
uv pip install -r requirements.txt --target ./package
```

Cross-platform build flags (when building on non-Linux):

```bash
pip install -r requirements.txt \
  --target ./package \
  --platform manylinux2014_x86_64 \
  --only-binary=:all:
```

Use `manylinux2014_aarch64` for arm64. Exclude `__pycache__`, `.pyc`, tests, docs.

---

## Memory and Timeout Tuning

### Memory

| Parameter | Value |
|---|---|
| Minimum | 128 MB |
| Maximum | 10,240 MB (10 GB) |
| Increment | 1 MB |
| Default | 128 MB |
| 1 vCPU at | 1,769 MB |
| ~5.8 vCPUs at | 10,240 MB |

CPU scales linearly with memory. Doubling memory doubles CPU. **Over-provisioning memory can improve performance** — faster execution = less total duration.

**Tuning process:**

1. Start at 256–512 MB (128 MB only for trivial event routers)
2. Monitor `Max Memory Used` in CloudWatch REPORT lines
3. Use **AWS Lambda Power Tuning** (open-source Step Functions tool):

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:powerTuningStateMachine \
  --input '{
    "lambdaARN": "arn:aws:lambda:REGION:ACCOUNT:function:my-function",
    "powerValues": [128, 256, 512, 1024, 1769, 3008],
    "num": 50,
    "payload": "{\"test\": true}"
  }'
```

### Ephemeral Storage (/tmp)

| Parameter | Value |
|---|---|
| Minimum / Default | 512 MB |
| Maximum | 10,240 MB (10 GB) |
| Extra cost | Above 512 MB |

- Content **persists across warm invocations** (use as transient cache)
- Content is NOT cleared after invoke failures
- SnapStart requires ≤ 512 MB ephemeral storage

### Timeout

| Parameter | Value |
|---|---|
| Minimum | 1 second |
| Maximum | 900 seconds (15 minutes) |
| Default | 3 seconds |

**Critical integration limits:**

- API Gateway REST API: **29s default** (adjustable for Regional/private APIs since June 2024; edge-optimized remains 29s max)
- API Gateway HTTP API: **30-second hard limit**
- SQS visibility timeout must be **≥ 6× function timeout** (AWS recommendation)

### Other Limits

| Resource | Limit |
|---|---|
| Environment variables (total) | 4 KB |
| Sync invocation payload (request/response) | 6 MB each |
| Async invocation payload | 1 MB |
| Streamed response | 200 MB (first 6 MB uncapped, then 2 MBps) |
| File descriptors | 1,024 |
| Processes/threads | 1,024 |
| Concurrent executions (default) | 1,000 per region (soft limit) |
| Scaling rate | 1,000 new environments every 10s per function |
| Function code storage (.zip) | 75 GB per region (soft limit) |

---

## VPC Connectivity

### Hyperplane ENI

Lambda uses **Hyperplane Elastic Network Interfaces** (shared, not per-function):

- Shared across functions using the same subnet + security group combination
- Each ENI supports **65,000 connections/ports**
- First-time ENI creation: **several minutes** (function stays in `Pending`)
- ENIs reclaimed after **14 days of inactivity** (function goes `Inactive`)
- Removing VPC config takes up to **20 minutes** for ENI cleanup
- Default quota: **500 Hyperplane ENIs per VPC** (Lambda-specific soft limit, can be increased). The broader VPC ENI service quota is **5,000 per region** by default.

### Internet Access Patterns

**Lambda in a VPC NEVER gets a public IP**, even in a public subnet.

**Pattern 1: Private Subnet + NAT Gateway** (most common)

```
Lambda → Private Subnet → Route Table → NAT Gateway → IGW → Internet
```

- Deploy in each AZ for HA

**Pattern 2: VPC Endpoints** (for AWS services)

```
Lambda → Private Subnet → VPC Endpoint → AWS Service
```

- **Gateway endpoints:** S3, DynamoDB
- **Interface endpoints:** STS, Secrets Manager, SQS, etc.
- Traffic stays on AWS network — lower latency

#### Pattern 3: IPv6 Egress-Only Internet Gateway

```
Lambda → Dual-Stack Subnet → Egress-Only IGW → Internet (IPv6)
```

- Eliminates NAT Gateway for IPv6 traffic
- Requires dual-stack subnets and IPv6-capable endpoints
- Set `Ipv6AllowedForDualStack=true` in function config

### Required IAM Permissions

VPC-attached functions need `AWSLambdaVPCAccessExecutionRole` managed policy or equivalent EC2 network interface permissions.

### Best Practices

- Reuse subnet + security group combos across functions to share ENIs
- Use multiple subnets across AZs for HA
- Prefer VPC endpoints over NAT Gateway for AWS service access
- Don't attach to VPC unless accessing private resources (RDS, ElastiCache, etc.)

---

## Execution Roles

One execution role per function. Key Lambda-specific managed policies:

| Policy | Grants |
|---|---|
| `AWSLambdaBasicExecutionRole` | CloudWatch Logs only |
| `AWSLambdaVPCAccessExecutionRole` | VPC ENI management |
| `AWSLambdaDynamoDBExecutionRole` | DynamoDB Streams |
| `AWSLambdaSQSQueueExecutionRole` | SQS polling |
| `AWSLambdaKinesisExecutionRole` | Kinesis Streams |

---

## Runtime Lifecycle

### Phases

```
┌─────────┐    ┌─────────┐    ┌──────────┐
│  INIT   │───▶│ INVOKE  │───▶│ SHUTDOWN │
│         │    │(repeat) │    │          │
└─────────┘    └─────────┘    └──────────┘
```

**Init Phase** (3 sub-phases: extension init → runtime init → function init):

- On-demand timeout: **10 seconds**
- Provisioned/SnapStart timeout: **up to 15 minutes**
- If init exceeds 10s on-demand, Lambda retries at first invocation using the function's configured timeout

**Invoke Phase:**

- Limited by function timeout (max 900s)
- Each environment handles **one concurrent invocation** at a time

**Shutdown Phase:**

- 0 ms (no extensions), 500 ms (internal only), 2,000 ms (external extensions)
- SIGKILL if extensions don't respond in time

**Restore Phase** (SnapStart only):

- Resumes from cached snapshot
- 10-second timeout for restore + after-restore hooks

### Execution Environment Reuse (Warm Starts)

Objects initialized outside the handler persist across invocations:

- SDK clients, DB connections, cached data all survive
- `/tmp` content persists (512 MB–10 GB)
- Background processes resume on next invocation
- **Workers have a maximum lease lifetime of ~14 hours** (observed behavior, not a documented SLA — do not depend on this value)
- Environments terminated periodically for maintenance even under continuous load

**Common pitfall:** Global variables persist — stale DB connections, expired credentials, and leaked state across invocations cause subtle production bugs.

### Extensions

- **Internal:** Run in the runtime process (APM agents)
- **External:** Separate processes alongside the runtime
- Use Extensions API and Telemetry API for lifecycle events, logs, metrics, traces

---

## Powertools for AWS Lambda

Official AWS toolkit for Lambda best practices. Available for Python, TypeScript, Java, .NET.

**Performance note:** Powertools adds cold start overhead. Use selective imports when cold start matters:

```python
# Instead of: from aws_lambda_powertools import Logger, Tracer, Metrics
# Import only what you need if cold start is critical
from aws_lambda_powertools import Logger
```

### Core Utilities

| Utility | Purpose |
|---|---|
| Logger | Structured JSON logging with correlation IDs |
| Tracer | X-Ray tracing with decorators/middleware |
| Metrics | CloudWatch metrics via Embedded Metric Format (EMF) |
| Idempotency | Make handlers idempotent using DynamoDB |
| Batch Processing | Partial failure handling for SQS, Kinesis, DynamoDB Streams |
| Event Handler | Routing for API Gateway, ALB, Function URLs, AppSync |
| Parameters | Retrieve/cache SSM, Secrets Manager, AppConfig, DynamoDB values |

### Environment Variables

| Variable | Purpose |
|---|---|
| `POWERTOOLS_SERVICE_NAME` | Service name for logs, metrics, traces |
| `POWERTOOLS_METRICS_NAMESPACE` | CloudWatch metrics namespace |
| `POWERTOOLS_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `POWERTOOLS_TRACE_DISABLED` | Disable tracing (useful for tests) |
| `POWERTOOLS_DEV` | Dev mode (pretty-print JSON, verbose errors) |

### Python: Logger + Tracer + Metrics

```python
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
tracer = Tracer()
metrics = Metrics()

@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    logger.info("Processing order", order_id=event.get("order_id"))
    metrics.add_metric(name="OrdersProcessed", unit=MetricUnit.Count, value=1)
    result = process_order(event)
    return {"statusCode": 200, "body": result}

@tracer.capture_method
def process_order(event: dict) -> str:
    return "processed"
```

### TypeScript: Logger + Tracer + Metrics

```typescript
import { Logger } from '@aws-lambda-powertools/logger';
import { Tracer } from '@aws-lambda-powertools/tracer';
import { Metrics, MetricUnit } from '@aws-lambda-powertools/metrics';
import middy from '@middy/core';
import { injectLambdaContext } from '@aws-lambda-powertools/logger/middleware';
import { captureLambdaHandler } from '@aws-lambda-powertools/tracer/middleware';
import { logMetrics } from '@aws-lambda-powertools/metrics/middleware';

const logger = new Logger({ serviceName: 'orderService' });
const tracer = new Tracer({ serviceName: 'orderService' });
const metrics = new Metrics({ namespace: 'OrderApp', serviceName: 'orderService' });

const lambdaHandler = async (event: any) => {
  logger.info('Processing order', { orderId: event.orderId });
  metrics.addMetric('OrdersProcessed', MetricUnit.Count, 1);
  const result = await processOrder(event);
  return { statusCode: 200, body: JSON.stringify(result) };
};

export const handler = middy(lambdaHandler)
  .use(injectLambdaContext(logger, { logEvent: false }))
  .use(captureLambdaHandler(tracer))
  .use(logMetrics(metrics, { captureColdStartMetric: true }));
```

### Python: Idempotency

```python
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    idempotent,
)

persistence_layer = DynamoDBPersistenceLayer(table_name="IdempotencyTable")

@idempotent(persistence_store=persistence_layer)
def handler(event: dict, context) -> dict:
    payment = process_payment(event)
    return {"payment_id": payment.id, "status": "success"}
```

### TypeScript: Idempotency

```typescript
import { makeIdempotent } from '@aws-lambda-powertools/idempotency';
import { DynamoDBPersistenceLayer } from '@aws-lambda-powertools/idempotency/dynamodb';

const persistenceStore = new DynamoDBPersistenceLayer({
  tableName: 'IdempotencyTable',
});

const processPayment = async (event: { paymentId: string; amount: number }) => {
  return { paymentId: event.paymentId, status: 'success' };
};

export const handler = makeIdempotent(processPayment, {
  persistenceStore,
});
```

### Python: Batch Processing (SQS Partial Failures)

```python
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord

processor = BatchProcessor(event_type=EventType.SQS)

def record_handler(record: SQSRecord):
    payload = record.json_body
    process_item(payload)

def handler(event, context):
    return process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )
```

### TypeScript: Batch Processing (SQS Partial Failures)

```typescript
import {
  BatchProcessor,
  EventType,
  processPartialResponse,
} from '@aws-lambda-powertools/batch';
import type { SQSRecord, SQSHandler } from 'aws-lambda';

const processor = new BatchProcessor(EventType.SQS);

const recordHandler = async (record: SQSRecord): Promise<void> => {
  const payload = JSON.parse(record.body);
  await processItem(payload);
};

export const handler: SQSHandler = async (event, context) => {
  return processPartialResponse(event, recordHandler, processor, {
    context,
  });
};
```

### Asset Reference

For a ready-to-use Python handler with Powertools wired, read [assets/powertools-handler.py](../assets/powertools-handler.py).
