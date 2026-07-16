# AWS Lambda Reference

Quotas, constraints, and gotchas that are easy to get wrong. Assumes you already know Lambda basics (packaging, layer paths, VPC-has-no-public-IP, Graviton ≈ 34% better price-performance, Powertools APIs) — this file focuses on the values and edge cases that trip up implementations.

## Contents

- [Cold Start Optimization](#cold-start-optimization)
- [Memory and Timeout Tuning](#memory-and-timeout-tuning)
- [VPC Connectivity](#vpc-connectivity)
- [Runtime Lifecycle](#runtime-lifecycle)
- [Function URLs](#function-urls)
- [Powertools and Packaging](#powertools-and-packaging)

---

## Cold Start Optimization

### SnapStart

Snapshots the initialized execution environment (Firecracker microVM memory + disk) and restores from cache instead of cold-booting.

**Supported runtimes:** Java 11+, Python 3.12+, .NET 8+

**Constraints:**

- **Mutually exclusive with Provisioned Concurrency** (cannot set both on one function)
- Mutually exclusive with Amazon EFS
- Ephemeral storage must be ≤ 512 MB
- Only works on published versions (not `$LATEST`)
- Java: no additional SnapStart charge. Python/.NET: caching charge (by memory, min 3 hours) + per-restore charge

**Restoration gotchas** (snapshot is reused across restores):

- Generate unique IDs/secrets in the handler, not during init
- Re-establish network connections in the handler (connections are stale after restore)
- Refresh cached timestamps/credentials in the handler

```python
# CDK (Python)
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
- **Account-level RPS quota: 10 × total concurrency** (applies across all invocations, not per instance)
- Supports auto-scaling via Application Auto Scaling (target ~70% utilization)
- Lambda can scale beyond provisioned count using on-demand instances
- **Paid even when idle** — disable in dev/staging

### Strategy Selection

| Scenario | Strategy |
|---|---|
| Java/Python/.NET with heavy init | SnapStart |
| Strict <50ms cold start, or need EFS / >512MB ephemeral | Provisioned Concurrency |
| Tolerant of occasional cold starts | On-demand + minimize package |
| Predictable traffic | Provisioned Concurrency + auto-scaling |
| General optimization | arm64 (Graviton) |

---

## Memory and Timeout Tuning

### Memory → CPU

| Parameter | Value |
|---|---|
| Range | 128 MB – 10,240 MB (1 MB increments), default 128 MB |
| **1 vCPU at** | **1,769 MB** |
| ~5.8 vCPUs at | 10,240 MB |

CPU scales linearly with memory — doubling memory doubles CPU. **Over-provisioning memory often lowers cost** (faster execution = less billed duration). Start at 256–512 MB; tune with [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) against `Max Memory Used` in REPORT lines.

### Ephemeral storage (/tmp)

- 512 MB (default/min) – 10,240 MB; extra cost above 512 MB
- Persists across warm invocations (transient cache); NOT cleared after invoke failures
- SnapStart requires ≤ 512 MB

### Timeout

- Range 1s – 900s (15 min); **default is 3s** — always set it explicitly

**Critical integration limits:**

- **API Gateway REST API: 29s default** — adjustable higher for Regional/private APIs; **edge-optimized remains 29s max**
- **API Gateway HTTP API: 30s hard limit** (cannot be raised)
- SQS visibility timeout should be **≥ 6× function timeout**

### Other limits worth knowing

| Resource | Limit |
|---|---|
| Sync invocation payload (request/response) | 6 MB each |
| Async invocation payload | 1 MB |
| Streamed response | 200 MB (2 MBps after first 6 MB) |
| Environment variables (total) | 4 KB |
| Concurrent executions (default) | 1,000 per region (soft) |
| Scaling rate | 1,000 new environments / 10s, per function |

---

## VPC Connectivity

Lambda uses **Hyperplane ENIs** — shared across functions that use the same subnet + security group combination (NOT per-function). Each ENI supports ~65,000 connections.

- First-time ENI creation can take **several minutes** (function stays `Pending`)
- ENIs reclaimed after **14 days of inactivity** (function goes `Inactive`); removing VPC config takes up to **20 minutes**

Reuse subnet + SG combos to share ENIs. Prefer **VPC endpoints** (gateway: S3, DynamoDB; interface: STS, Secrets Manager, SQS, …) over NAT Gateway for AWS-service access — lower latency, traffic stays on the AWS backbone. Don't attach to a VPC unless you need private resources (RDS, ElastiCache). VPC-attached functions need `AWSLambdaVPCAccessExecutionRole`.

---

## Runtime Lifecycle

```
INIT ──▶ INVOKE (repeat) ──▶ SHUTDOWN          [+ RESTORE phase for SnapStart]
```

**Init phase** (extension init → runtime init → function init):

- **On-demand init timeout: 10s.** If exceeded, Lambda retries at first invocation using the function's configured timeout.
- **Provisioned/SnapStart init timeout: up to 15 minutes.**

**Shutdown phase:** 0 ms (no extensions), 500 ms (internal only), 2,000 ms (external extensions); SIGKILL if not done in time.

**Restore phase (SnapStart):** 10s timeout for restore + after-restore hooks.

### Warm-start reuse

Objects initialized outside the handler persist across invocations (SDK clients, DB connections, `/tmp`). Gotchas:

- **Execution environments are recycled periodically** for maintenance even under continuous load — never assume an environment (or its warmed state) lives indefinitely.
- **Global variables persist** — stale DB connections, expired credentials, and leaked state across invocations cause subtle production bugs. Refresh connections/credentials in the handler.

---

## Function URLs

A Function URL is a dedicated HTTPS endpoint on a single function — no API Gateway. Use for internal service-to-service (IAM auth), Lambdalith + CloudFront, response streaming, or webhook receivers. There's **no built-in rate limiting, WAF, or request validation** (front with CloudFront/API Gateway if you need those). Choose **API Gateway** instead for public APIs needing rate limiting, JWT/Cognito auth, multi-function routing, request validation, or WAF without CloudFront.

Invoking a Function URL **always requires `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction`** — granting only `InvokeFunctionUrl` returns **HTTP 403** even with `AuthType=NONE`. The two `AuthType` options differ in *how* those permissions are supplied:

### `AuthType=AWS_IAM` (non-public — prefer for production)

Only callers with valid AWS credentials that sign requests with **SigV4** can invoke; unauthenticated requests get **403**.

- **Same-account caller:** grant the two actions in the caller's **identity-based policy** *or* the function's resource-based policy — a resource-based policy is **optional** if the caller's identity policy already allows them (this is why an admin/broad identity policy invokes with no resource policy on the function).
- **Cross-account caller:** requires **both** an identity-based policy on the caller **and** a resource-based policy on the function.
- For CloudFront in front, use **Origin Access Control** to sign requests rather than `NONE`.

### `AuthType=NONE` (public)

Lambda does no auth — the resource-based policy alone gates access, so it must grant **public** access. Only use when the endpoint must be reachable by unauthenticated clients (e.g. a browser hitting the URL directly) with no CloudFront/edge auth in front; it exposes the function to anyone with the URL, so pair it with in-code auth, throttling, and monitoring. The console and SAM add both required statements automatically; with the CLI/API add each yourself (two separate `add-permission` calls):

```bash
# Statement 1: allow invoking via the Function URL (public)
aws lambda add-permission --function-name my-function \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl --principal '*' \
  --function-url-auth-type NONE

# Statement 2: REQUIRED — allow the underlying invoke, scoped to URL calls
aws lambda add-permission --function-name my-function \
  --statement-id FunctionURLInvokeAllowPublicAccess \
  --action lambda:InvokeFunction --principal '*' \
  --invoked-via-function-url
```

The `lambda:InvokedViaFunctionUrl` condition on statement 2 (set by `--invoked-via-function-url`) restricts that grant to Function URL calls, so it does not open direct `Invoke` access. See [Lambda function URL auth](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html).

## Powertools and Packaging

Use **Powertools for AWS Lambda** (Python, TypeScript, Java, .NET) for structured logging, X-Ray tracing, EMF metrics, idempotency, batch processing, event handling, and parameter caching. The APIs are well-documented at [docs.powertools.aws.dev](https://docs.powertools.aws.dev/lambda/); for a ready-to-use Python handler with Logger + Tracer + Metrics + Idempotency wired, start from [assets/powertools-handler.py](../assets/powertools-handler.py).

Powertools adds cold-start overhead — use selective imports when cold start is critical.

**Useful Powertools env vars:** `POWERTOOLS_SERVICE_NAME`, `POWERTOOLS_METRICS_NAMESPACE`, `POWERTOOLS_LOG_LEVEL`, `POWERTOOLS_TRACE_DISABLED` (tests), `POWERTOOLS_DEV` (pretty-print).

**Packaging quick facts:** 50 MB zipped / 250 MB unzipped (incl. layers) → switch to container image (10 GB) past that. Max 5 layers/function; layers don't work with container images. Use `uv pip install` (10–100× faster than pip) and `--platform manylinux2014_{x86_64,aarch64} --only-binary=:all:` for cross-platform builds, or let `sam build` handle it. See [troubleshooting.md](troubleshooting.md) for size/import errors.
