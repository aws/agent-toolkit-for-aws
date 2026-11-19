---
name: aws-lambda-managed-instances
description: "Evaluates, configures, and migrates workloads to AWS Lambda Managed Instances (LMI). Runs Lambda Event Functions on EC2 instances in the user's account while AWS manages provisioning, patching, and scaling. Triggers when queries mention Lambda Managed Instances, LMI, capacity providers, multi-concurrent execution environments, EC2-backed Lambda, persistent Lambda instances, PerExecutionEnvironmentMaxConcurrency, CapacityProviderConfig, cold start elimination via dedicated instances, SOCI (Seekable OCI) image lazy loading, GPU functions (AcceleratorConfig, vLLM/SGLang), migrating Lambda Event Functions to managed instances, or LMI cost comparison with Savings Plans or Reserved Instances. Also covers long-running and asynchronous workloads, the 90-minute (5400s) timeout for asynchronous and event-source-mapping (SQS, Kinesis, DynamoDB Streams / ESM) invocations and the 30-minute (1800s) synchronous limit, including how to raise the function timeout up to 90 minutes / 5400s."
version: 6
---

# AWS Lambda Managed Instances (LMI)

Runs Lambda Event Functions on EC2 instances in the user's account while AWS manages provisioning, patching, scaling, routing, and load balancing. Combines Lambda's developer experience with EC2's pricing and hardware options.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) for sandboxed CLI execution and audit logging. All guidance also works with standard AWS CLI or SAM CLI.

**Note:** Confirm regional availability, quotas, and instance type offerings against current AWS documentation before production deployment.

## Quick Decision: Is LMI Right for This Workload?

| Signal | LMI is a strong fit | Lambda Event Functions are better |
|--------|---------------------|---------------------------|
| Traffic | Steady, predictable, 50M+ req/mo | Bursty, unpredictable, long periods of no traffic |
| Duration | Long-running asynchronous/ESM jobs that exceed 30 min (up to 90 min on LMI): ETL/data processing, media transcoding, ML inference, financial calc, web scraping | Short invocations; synchronous work needing >30 min (not supported on any Lambda) |
| Cost | Duration-heavy spend at scale | Low or sporadic invocations |
| Cold starts | Unacceptable (LMI eliminates for provisioned capacity) | Tolerable |
| Compute | Latest CPUs, specific families, high network bandwidth, NVIDIA GPUs (inference, transcoding, rendering) | Lambda Event Functions memory/CPU sufficient |
| Isolation | Dedicated EC2 instances in your account, full VPC control | Shared Firecracker micro-VMs acceptable |
| Scale-to-zero | Does not scale to zero but can create custom schedules with AWS provided solutions | Required (pay nothing when idle) |
| Code readiness | Thread-safe (Node.js/Java/.NET) or any Python code | Non-thread-safe code, expensive to change |

## Routing

Read ONLY the single reference file that matches the user's task. Do not preload multiple references.

| User need | Action |
|-----------|--------|
| Cost comparison, pricing analysis, Savings Plans, Reserved Instances | Read [cost-comparison.md](references/cost-comparison.md) |
| Instance types, memory sizing, vCPU ratios, scaling tuning, capacity provider config, SOCI lazy loading for large container images | Read [configuration-guide.md](references/configuration-guide.md) |
| Thread safety, concurrency model, code review checklist, multi-concurrency readiness | Read [thread-safety.md](references/thread-safety.md) |
| Before/after code examples, runtime-specific migration, connection pooling | Read [migration-patterns.md](references/migration-patterns.md) |
| IAM roles, VPC setup, CLI commands, SAM template, CDK example | Read [infrastructure-setup.md](references/infrastructure-setup.md) |
| Errors, throttling, debugging, stuck deployments | Read [troubleshooting.md](references/troubleshooting.md) |
| GPU-accelerated functions: accelerator memory, GPU instances, GPU base images (vLLM, SGLang, PyTorch), GPU concurrency, GPU errors | Read [gpu-acceleration.md](references/gpu-acceleration.md) |

**Troubleshooting quick facts** (always mention when diagnosing issues):

- Function version stuck in Pending → instance launches are failing; **check the version's `StateReasonCode`**. Top causes: `INSUFFICIENT_CAPACITY` (EC2 capacity), `INSUFFICIENT_OPERATOR_ROLE_PERMISSIONS`, `CAPACITY_PROVIDER_SCALING_LIMIT_EXCEEDED` (raise `MaxVCpuCount`). A capacity provider has no long CREATING state: it is Active once `CreateCapacityProvider` succeeds, and bad subnets, security groups, operator role or quotas are rejected in that call with `InvalidParameterValueException`.
- Instances **do not need NAT or VPC endpoints to come up** (image pulls, registration, health checks and vended metrics use a Lambda-owned ENI). NAT or VPC endpoints are needed only for CloudWatch Logs / X-Ray delivery and the function code's own outbound calls.
- Function not scaling → check that a **version is published** (PublishToLatestPublished: true)
- Memory errors → LMI minimum is **2048 MB**

## Workflow

### Step 1: Assess the Workload

Gather these signals before recommending:

1. **Traffic pattern**: Steady vs bursty? Requests per second?
2. **Current costs**: Monthly Lambda spend? Existing Savings Plans?
3. **Runtime**: Node.js, Java, .NET, or Python?
4. **Memory/CPU**: How much memory? CPU-bound or I/O-bound?
5. **Execution duration**: Average and P99?
6. **Concurrency readiness**: Thread safety? Shared `/tmp` paths? Per-invocation DB connections?
7. **VPC**: Already in a VPC? Private resource access needed?
8. **GPU**: Does the workload need a GPU (CUDA, PyTorch, vLLM, NVENC, OpenGL)? If yes, read [gpu-acceleration.md](references/gpu-acceleration.md).

**Long-running asynchronous/ESM jobs that exceed 30 min are a positive fit** — LMI supports a function timeout up to 90 min (5400s) for asynchronous and event-source-mapping invocations (ETL/data processing, media transcoding, ML inference, financial calc, web scraping). Duration is the key differentiator here, not just cost.

When recommending LMI, ALWAYS mention: minimum 3 execution environments for AZ resiliency (cannot go below 3 in production). GPU-accelerated functions default to a minimum of 1 instead (see [gpu-acceleration.md](references/gpu-acceleration.md)).

### Step 2: Build the Cost Comparison

REQUIRED: Present a cost comparison before recommending LMI.

Rule of thumb: LMI becomes cost-competitive at 50-100M+ req/month with steady traffic. Use the [LMI Pricing Calculator](https://aws-samples.github.io/sample-aws-lambda-managed-instances/) for accurate comparisons.

### Step 3: Configure the Deployment

- **Instance families** (400+ types, .large and up): C-series (compute), M-series (general), R-series (memory). ARM (Graviton) for best price-performance.
- **When using Graviton instances, MUST set `Architectures: [arm64]`** in the function configuration to match.
- **Memory-to-vCPU ratios** (`ExecutionEnvironmentMemoryGiBPerVCpu`): 2:1 (compute, default), 4:1 (general), 8:1 (memory). Min 2 GB, max 32 GB.
- **Multi-concurrency per-vCPU maximums**: Node.js 64, Java 32, .NET 32, Python 16. These are system caps — the actual setting is PerExecutionEnvironmentMaxConcurrency (per execution environment, not per vCPU).
- **For I/O-bound workloads**: use the runtime default or higher PerExecutionEnvironmentMaxConcurrency (e.g., 10 for Node.js) since each request uses minimal CPU while waiting on network.
- **For CPU-bound workloads**: set PerExecutionEnvironmentMaxConcurrency to 1-2 per vCPU since each request saturates CPU.
- **Scaling**: MinExecutionEnvironments (default 3), MaxVCpuCount (optional, default 400 — set explicitly as best practice), TargetResourceUtilization.
- **Function timeout up to 5400s (90 min)** — set via the existing `Timeout` field (CLI `update-function-configuration --timeout 5400`, SAM/CFN `Timeout: 5400`, or console). Uses the existing `Timeout` field — no separate API, property, tag, or code change is required. Applies to **asynchronous and ESM invocations only**; synchronous invocations can run for up to 30 min (1800s), so set `Timeout` up to 1800 for a synchronous job that fits; if `Timeout` is higher, Lambda stops a synchronous invocation after 30 min (`GetFunctionConfiguration` still reports the configured value). On-Demand functions allow up to 30 min for every invocation type. The Init phase is still capped at 15 min. Durable Functions: each step can run up to 90 min; a multi-step workflow up to 1 year. To invoke a durable function synchronously, through an ESM, or through a function URL, set its durable execution timeout (`DurableConfig` `ExecutionTimeout`, separate from the function `Timeout`) to 1800s (30 min) or less.

### Step 4: Migrate the Code

Review code for concurrency safety. LMI runs multiple invocations concurrently per execution environment:

- **Python**: Process-based isolation — globals are NOT shared. No thread-safety changes needed. Focus on `/tmp` conflicts and memory sizing.
- **Node.js**: Worker threads — globals shared within a worker. Requires async safety.
- **Java/.NET**: OS threads/Tasks — handler shared across threads. Requires full thread safety.

### Step 5: Set Up Infrastructure

1. Create two IAM roles: execution role (for the function) and operator role (for capacity provider EC2 management)
2. Configure VPC with subnets across 3+ AZs
3. Create capacity provider with VPC config and scaling limits
4. Create a new function with the capacity provider attached
5. Publish a version (triggers instance provisioning)

### Step 6: Validate and Cut Over

1. Deploy to a non-production environment first
2. Monitor CloudWatch: CPU utilization, memory, concurrency, throttle rate
3. Gradual traffic shift at the invoking service or routing layer (10% → 50% → 100%)
4. Compare costs after 1-2 weeks of production data
5. Decommission the Lambda Event Function once stable

## Best Practices

### Pricing (always mention when discussing costs)

- **Three components**: EC2 instance hours + 15% management fee + $0.20/1M requests
- **Savings Plans**: Compute Savings Plans apply to the EC2 portion (up to 60-72% discount)
- **The 15% fee** is charged on top of EC2 cost for AWS managing provisioning, patching, scaling, lifecycle
- **GPU-accelerated functions**: check [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/) for the GPU management fee and instance prices

### Scaling (always mention when discussing scaling or traffic)

- LMI absorbs a 50% traffic spike immediately and **doubles capacity within 5 minutes** — if traffic more than doubles faster, requests throttle
- Lambda Event Functions burst to 3000 instantly — LMI cannot match this
- **Pre-warm** with MinExecutionEnvironments before known spikes
- **MaxVCpuCount** (default 400) — set explicitly as a cost ceiling
- **Shape**: Reduce MinExecutionEnvironments to lower capacity during off-hours (minimum 3 for AZ resiliency on CPU functions; GPU functions default to 1)

### Large container images (SOCI lazy loading)

- For container image functions, the image pull is the largest part of the time between publishing a version or scaling out and the first invocation. **Seekable OCI (SOCI)** lets Lambda start the execution environment before the whole image is downloaded and fetch files on demand as the function reads them. The benefit is largest for multi-GB images, such as images that package ML frameworks.
- **Enable it** by pushing a SOCI index to Amazon ECR next to the image, pointing the function's image URI at the SOCI-indexed tag, and publishing a version. No other function configuration changes. Steps in [configuration-guide.md](references/configuration-guide.md).
- **Import libraries and read files in init code, not in the handler.** A file first read in the handler is fetched during that invocation and adds to its duration; Lambda does not download the rest of the image in the background.
- Recommend testing with and without SOCI to compare startup time and invocation duration for the workload.

### Instance Sizing

- **1 vCPU + 1 GB reserved per instance** for OS overhead (not available to your function)
- Usable capacity = total - overhead

### Configuration

- The default ratio is 2:1 (compute-heavy work); set 4:1 for balanced web APIs and microservices (M-series), and 4:1 or 8:1 for memory-heavy or Python workloads. Start with the runtime default concurrency
- Use ARM (Graviton) unless x86 dependencies exist
- Let Lambda choose instance types unless specific hardware needed
- Set MaxVCpuCount to control cost ceiling
- Never set MinExecutionEnvironments below 3 for CPU functions (breaks AZ resiliency); GPU-accelerated functions default to 1 (see [gpu-acceleration.md](references/gpu-acceleration.md))

### Migration

- Start with I/O-heavy functions (benefit most from multi-concurrency)
- Review code for concurrency safety before attaching to capacity provider
- Shift traffic gradually at the invoking service or routing layer
- Include request IDs in all log statements
- Initialize DB pools and SDK clients outside the handler

### Operations

- Set CloudWatch alarms on throttle rate > 1% and CPU > 80%
- Plan for 14-day instance rotation (automatic)
- Never manually terminate LMI EC2 instances (delete the capacity provider instead)
- Always publish a version — unpublished functions cannot run on LMI

### Long-duration invocations (asynchronous/ESM up to 90 min)

- **SQS**: the queue visibility timeout MUST be ≥ the function timeout (≥ 5400s for a 90-min function). The ESM validates this on create and update — but once the ESM exists, the SQS visibility timeout and the function timeout can each be changed independently (outside the ESM API), which bypasses the check and can reintroduce a mismatch, causing messages to reappear and duplicate invokes.
- **Kinesis / DynamoDB Streams**: enable **partial batch failure reporting** (`ReportBatchItemFailures`) and tune the max batching window and parallelization factor — otherwise one failed record retries the whole batch, re-running up to ~80 min of already-completed work.
- **Asynchronous invocations**: failed or timed-out invocations follow the retry policy (up to 2 retries by default), then route to the DLQ / on-failure destination.
- **Not all ESM sources qualify**: Amazon MQ and Amazon DocumentDB ESM support function timeouts of up to 14 min; other ESM sources (SQS, Kinesis, DynamoDB Streams, Amazon MSK, and self-managed Kafka) and asynchronous invocations get 90 min. Confirm the limit for the source in use in the [event source mapping docs](https://docs.aws.amazon.com/lambda/latest/dg/invocation-eventsourcemapping.html).
- **Observability is unchanged**: CloudWatch, CloudTrail (one Invoke event on completion/timeout), and X-Ray (single trace) behave identically. Use X-Ray sub-segments to find slow phases near the 90-min limit.

### Long-running networking (functions now run for tens of minutes)

- **NAT Gateway idle timeout** — send periodic keep-alive packets on long-lived TCP connections through a NAT Gateway.
- **Idle connection timeouts** (RDS, ElastiCache, external APIs) — add connection health checks / reconnection logic for connections that may go idle mid-computation.
- **Synchronous callers** — set the client read timeout higher than the function timeout and turn on TCP keep-alive (AWS CLI: `--cli-read-timeout 0`). Some services stop waiting sooner: API Gateway REST APIs after 29s by default, HTTP APIs after 30s at most.
- **DNS TTL** — re-resolve external hostnames periodically; the AWS SDK does this, but custom HTTP clients may cache beyond TTL.
- **Credentials** — rely on the execution role's ephemeral credentials (automatically refreshed by the runtime). For non-IAM secrets (DB passwords, API keys), retrieve them from AWS Secrets Manager or SSM Parameter Store with SDK caching and periodic refresh; never embed long-lived credentials in code or environment variables.

## Limits Quick Reference

| Resource | Limit |
|----------|-------|
| Memory | 2 GB min, 32 GB max |
| Asynchronous/ESM invoke timeout | 90 min (5400s), via the existing Timeout field |
| Synchronous invoke timeout | Up to 30 min (1800s); Lambda stops synchronous invocations at 30 min even if Timeout is higher |
| Init phase | 15 min |
| ESM sources capped at 14 min | Amazon MQ, Amazon DocumentDB (other ESM sources get 90 min); see the [event source mapping docs](https://docs.aws.amazon.com/lambda/latest/dg/invocation-eventsourcemapping.html) |
| Execution environments | 3 minimum (MinExecutionEnvironments, AZ resiliency); GPU-accelerated functions default to 1 |
| Instance lifespan | 14 days (auto-replaced) |
| Concurrency/vCPU | 64 (Node.js), 32 (Java/.NET), 16 (Python) |
| Runtimes | Node.js 22+, Java 21+, .NET 8+, Python 3.13+, Rust (provided.al2023) |
| Instance families | C, M, R (.large and up); NVIDIA GPU families for GPU-accelerated functions (see [gpu-acceleration.md](references/gpu-acceleration.md)) |
| Scaling | Burst headroom equals unused capacity from TargetResourceUtilization; new instances launch within minutes |
| SOCI lazy loading | Container image functions on LMI only (not Lambda Event Functions on-demand); SOCI Index Manifest v2 only; image index with exactly one OCI image manifest plus the SOCI index (no multi-architecture indexes) |

## Security Considerations

- **Operator role scoping**: Add `aws:SourceAccount` and `aws:SourceArn` conditions to trust policies to prevent confused deputy attacks.
- **VPC egress**: Scope security group egress to VPC endpoint security groups or AWS prefix lists rather than 0.0.0.0/0.
- **Credentials**: Use AWS Secrets Manager or Parameter Store for database credentials — never environment variables for secrets.
- **Encryption**: Enable SQS SSE, CloudWatch Logs encryption (KMS), and S3 default encryption for any data at rest.
- **Logging**: Set CloudWatch Log group retention policies. Avoid logging PII or credentials. Enable CloudTrail data events for Lambda.
- **Instance rotation**: The 14-day automatic rotation ensures security patches are applied without manual intervention.
- **References**: [Lambda Security Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html), [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

## Files

| File | Content |
|------|---------|
| [cost-comparison.md](references/cost-comparison.md) | Pricing analysis, break-even calculations, Savings Plans/RI impact |
| [configuration-guide.md](references/configuration-guide.md) | Instance selection, memory ratios, scaling tuning, capacity provider config, SOCI lazy loading |
| [thread-safety.md](references/thread-safety.md) | Concurrency model per runtime, code review checklist, Powertools compatibility |
| [migration-patterns.md](references/migration-patterns.md) | Before/after code by runtime, connection pooling, gradual cutover |
| [infrastructure-setup.md](references/infrastructure-setup.md) | IAM roles, VPC setup, SAM templates, CLI commands |
| [troubleshooting.md](references/troubleshooting.md) | Common errors, throttling, debugging, stuck deployments |
| [gpu-acceleration.md](references/gpu-acceleration.md) | GPU setup rules, accelerator memory, GPU concurrency, startup, deployments, GPU errors |
