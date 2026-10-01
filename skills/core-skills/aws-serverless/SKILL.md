---
name: aws-serverless
description: Routes serverless requests to a compute form factor and the skill that owns it. Applies first to Lambda, API Gateway, EventBridge, Step Functions and event-driven work while the compute, orchestration or integration choice is open — API backends, webhooks, jobs, cron, queue/stream consumers, durable workflows, event routing, Step Functions vs Durable Functions, and Pipes vs native event source mappings for queues and streams. Decides Event Functions on-demand vs Managed Instances, Web Functions, MicroVMs, EventBridge rules/Scheduler/Pipes/bus, HTTP vs REST API. Owns shared Lambda references (cold starts, SnapStart, concurrency, event sources, function URLs, throttling, troubleshooting). Defers to the specialized skill once a request commits to one form factor or service, or describes its defining feature, even unnamed (durable checkpointing and automatic step retries, Firecracker sandbox, managed instances, Node.js server). Not for EC2, ECS/EKS/Fargate or Amplify hosting.
metadata:
  version: "5"
---

# AWS Serverless

## Overview

This skill is the **router** for serverless work on AWS. It makes one opinionated recommendation for each application component and each raised decision dimension (form factor + capacity provider + orchestration + feature choices), then hands off to every specialized skill needed for that composition. Do not force a multi-component application onto one form factor. This skill keeps only the shared Lambda reference material that has no dedicated skill.

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) — recommended for sandboxed command execution and audit logging. All guidance also works with standard AWS CLI access.

**How to use this skill:** Step 0 fixes the entry point (new, optimizing, migrating); Step 1 routes components that already name the technology; Step 2 walks the compute decision flow (Tier 1 → 3) for each component until its form factor and capacity provider are locked, with the Tier 4 edge cases detailed in [compute-decision-edge-cases.md](references/compute-decision-edge-cases.md); Steps 3–5 resolve orchestration, eventing and the HTTP front door only when the request raises them, with the full comparisons in [orchestration.md](references/orchestration.md) and [api-gateway.md](references/api-gateway.md). Then hand off to every applicable specialized skill and fall back to the [shared references](#shared-references-in-this-skill) for anything without a dedicated skill.

If a routed skill is not available in your environment, **the decision made here still stands**: answer from the decision flow below and the shared references, name the recommended form factor and the skill that owns it, and do not switch to a different form factor because its documentation is easier to find. In particular, Lambda Web Adapter is **not** a substitute for Web Functions on a Node.js HTTP app — it is the Event Functions path for non-Node.js runtimes, container images, or an existing API Gateway integration.

## Rules (apply to every recommendation)

1. **Be opinionated per component and resolved dimension.** State *"Use X because …"*. Do not force one service across components with different requirements, and do not present neutral comparison tables as the answer. For a *Decided* dimension, add one clause naming why the closest alternative does not fit (for example, Event and Web Functions have no OS-level access for eBPF; Durable Functions has no native `.sync` integration to start and wait on Glue or ECS jobs), and keep the recommendation and its reasons in the final response even after consulting other skills or documentation.
2. **Resolve every raised component and decision dimension independently.** Form factor, capacity provider, orchestration and feature constraints are separate decisions; resolving one does not close another. Different components may use different form factors, and one component may pair a compute form factor with an orchestration layer.
3. **Infer facts, not boundaries: classify each raised dimension before answering.**
   - *Decided* — the request states the fact that separates the candidates (runtime, trigger, a stated duration or size, "all steps are Lambda functions", "runs continuously") → commit and ask nothing about that dimension.
   - *Leaning* — the request gives only a qualitative hint ("bursty", "uneven", "quiet overnight", "large dependencies", "untrusted", "thousands of short tasks", "takes a while") while a candidate still depends on an observable fact it leaves unstated → lead with the provisional choice and why, then put the missing fact to the user as a direct question (ending in "?") and say which answer flips the route. Stating what *would* change the answer is not a substitute for asking. A hint supports the lean; it never substitutes for the deciding fact.
   - *Open* — no usable hint → use that tier's narrowing question.
   - *Unraised* — the request neither asks about a dimension nor gives a signal for it → apply its default without a question (for example, an event-triggered function with no traffic, duration, instance-type or pricing signal is **Event Functions · On-Demand**).

   Do not reopen an unraised or decided dimension, ask no more than 3–4 questions overall, and never reply with questions alone. When a numeric threshold decides the route, name it in the question so the customer can answer from their metrics (for example, a peak-to-mean ratio below 2 within 5–10 minutes for Managed Instances, Tier 3).
4. **Revise.** New information → re-run the affected tier and update the recommendation.
5. **Do not guess facts.** Ground limits, runtimes, pricing and timeouts in the shared references below and confirm against current AWS documentation when precision matters.
6. **Route, do not duplicate.** Once a specialized skill is chosen, follow it rather than re-deriving its content here.

## Step 0 — Entry point: what is the user doing?

If unclear, ask once: *"Are you starting something new, tuning a workload you already have, or moving an existing workload onto serverless?"*

| Context | Signals | Path |
|---|---|---|
| **New application** | "building", "starting", "new project", "greenfield", no existing compute named | Step 1, then the Step 2 decision flow |
| **Optimizing existing** | "bill is too high", "cold starts", "too slow", "lag", names a current Lambda setup | Step 2 Tier 3–4 (capacity, cold start, throughput), then [lambda.md](references/lambda.md), [concurrency.md](references/concurrency.md), [troubleshooting.md](references/troubleshooting.md) |
| **Re-platform / migrate** | "moving off EC2/ECS", "containerize", "get off servers", "modernizing" | Step 2 with runtime, duration and packaging as the first constraints, then optimize |

## Step 1 — Direct routes (the request already names the technology)

| Route to | When the request names or clearly implies | Do **not** route when |
|---|---|---|
| **Event Functions** — this skill: [lambda.md](references/lambda.md), [event-sources.md](references/event-sources.md) | A Lambda function invoked by an event source or trigger (SQS, Kinesis, Kafka, S3, DynamoDB Streams, EventBridge, SNS, API Gateway, ALB, IoT, Function URL), an HTTP handler in a non-Node.js runtime, a container image, Lambda layers | A Node.js HTTP server listening on a port (Web Functions), a customer-managed environment (MicroVMs), or a compute choice that is still open — Step 2. Tier 3 still decides the capacity provider |
| **aws-lambda-web-functions** | Lambda Web Functions, `aws lambda-web`, deploying a Node.js HTTP server (Express, Hono, Fastify) on Lambda, CloudFront-fronted Node.js apps, multi-region HTTP endpoints, active-CPU billing, native HTTP response streaming | Non-Node.js runtimes, container images, event-driven triggers (SQS, Kinesis, S3, DynamoDB Streams) — these are Event Functions |
| **aws-lambda-microvms** | Lambda MicroVMs, Firecracker microVM images, `launch/suspend/resume/terminate`, snapshot-resumable environments, VM-level isolation, untrusted/AI-generated code execution, retained files/processes across interactions, OS access (FUSE, eBPF), gRPC or WebSocket servers on custom ports, sessions up to 8 hours | "isolation" alone for ordinary request/response or event handlers. Event Functions have per-function isolation by default; use tenant isolation mode when environments must be dedicated to one invoker |
| **aws-lambda-managed-instances** | Lambda Managed Instances (LMI), capacity providers, `CapacityProviderConfig`, `PerExecutionEnvironmentMaxConcurrency`, EC2-backed Lambda, Savings Plans / Reserved Instances for Lambda, specific instance types for functions, async or ESM executions up to 90 minutes | Bursty traffic that scales to zero with no instance-type or commitment requirement |
| **aws-lambda-durable-functions** | Durable execution, checkpoint-and-replay, `context.step` / `context.wait` / `context.invoke`, `withDurableExecution`, `durable-execution-sdk`, saga written as code on Lambda, `LocalDurableTestRunner` | A visual/ASL workflow, Distributed Map, or broad orchestration of AWS services and non-Lambda compute — see Step 3 |
| **aws-step-functions** | State machines, Amazon States Language (ASL), JSONata, Distributed Map, `.sync` / `waitForTaskToken`, orchestrating ECS/Fargate, Glue, SageMaker, Batch | Code-first orchestration owned in Lambda application code — see Step 3 |
| **amazon-eventbridge-event-bus** | The new EventBridge custom event bus (`eventsv2`), any new workload publishing its own application events (including single-account), pub/sub, independent subscribers, choreography, a central bus shared across teams/accounts, ordered delivery per event group, replay, retention, deduplication, schema registry with open formats (CloudEvents, Avro, Protobuf), or migration from a classic custom bus to those capabilities | Operating an existing classic custom bus with rules and targets, EventBridge Scheduler, Pipes, Global Endpoints, the Schema Registry on its own, API Destinations or Connections — these stay with this skill (Step 4 and [orchestration.md](references/orchestration.md)) |

## Step 2 — Compute decision flow

Run the tiers independently for each application component. Drop to the next tier only when the previous one did not produce a confident match for that component. Lock its form factor first (Tier 1–2); Tier 3 decides the Event Functions capacity provider and Step 3 decides orchestration. If the prompt is too vague to identify any component, ask: *"What are you trying to build?"*

### Tier 1 — Match the workload to a form factor

Lambda has three form factors: **Event Functions**, **Web Functions** and **MicroVMs**. Scan these signals against the request; the capacity provider (On-Demand vs Managed Instances) is a separate decision in Tier 3.

| Form factor | Locks when the request has | Typical use cases |
|---|---|---|
| **Event Functions** | An event source or trigger (SQS, Kinesis, Kafka, S3, DynamoDB Streams, EventBridge, SNS, API Gateway, ALB, IoT, Function URL), a non-Node.js runtime for an HTTP handler, a container image, Lambda layers, event fan-out, retries/DLQ/idempotency semantics | Event-driven processing, queue/stream consumers, glue between services, API Gateway backends |
| **Web Functions** | A Node.js HTTP server that listens on a port (Express, Hono, Fastify), I/O-heavy request/response where most time is waiting on network, native response streaming or SSE, long-held/long-polling connections, multi-concurrent requests in one sandbox, CloudFront in front, multi-Region endpoints, "pay only for active CPU" | Web apps and REST backends in Node.js, streaming AI responses, Node.js backends that fan out parallel calls to downstream services and assemble the response |
| **MicroVMs** | Customer-managed sandbox lifecycle (launch/suspend/resume/terminate), state that must persist across a session (memory, disk, processes), untrusted or LLM-generated code, OS access (FUSE, eBPF), custom ports, per-session or per-tenant VM isolation, sessions up to 8 hours | AI-agent code sandboxes, browser IDEs and notebooks, CI/build runners, security scanners, ephemeral dev environments |

More than one row may match when the request describes several components. Route each component separately—for example, a Web Function control-plane API plus MicroVM session workers—rather than treating the rows as mutually exclusive for the whole application.

Constraints that decide ties: Web Functions and MicroVMs run on On-Demand only; Managed Instances is an Event Functions capacity provider (Tier 3), not a form factor; Durable Functions runs on Event Functions (On-Demand or Managed Instances) only. Web Functions is Node.js only (zip, no container images, no event source mappings, no Provisioned Concurrency or SnapStart). Duration ceilings: 15 min per invocation on On-Demand, on Web Functions and for synchronous invocations on Managed Instances; 90 min on Managed Instances for async or ESM invocations; 8 h per MicroVM session; longer than that is outside Lambda.

**Narrowing questions** (only when Tier 1 cannot classify a component from the request; skip facts already supplied):

1. **Functions vs MicroVMs** — ask: *"Does this component just handle individual requests/events, or does each session need an environment that keeps files, memory or processes between interactions?"* → retained environment/customer-controlled lifecycle = **MicroVMs** (confirm each session ≤ 8 h). Individual executions = Functions → Q2.
2. **Event vs Web** — ask: *"Is this component invoked through a queue, stream, event source or Lambda HTTP integration, or is it a Node.js HTTP server that listens on a port?"* → event/handler integration = **Event Functions** → Tier 3. Node.js HTTP server = **Web Functions** candidate → Tier 2.

Durability is not a form-factor question: whether the work runs as multiple coordinated steps that must survive a crash, or waits on timers, callbacks or approvals and then resumes, is decided in Step 3 once the form factor and capacity provider are known (Durable Functions runs on Event Functions with either supported capacity provider: **On-Demand or Managed Instances**).

### Tier 2 — Web Functions vs Event Functions

Run this tier for a component whenever Web Functions is a candidate, or when Tier 1 could not separate Web from Event Functions. Infer runtime, packaging and existing integrations from the request or project first; ask only the first missing fact that changes the route.

| # | Question | Answer → decision |
|---|---|---|
| Q1 | What runtime is the app? | **Non-Node.js** → **Event Functions** (e.g. Flask/Django/Spring/.NET behind API Gateway, ALB or a Function URL, optionally via Lambda Web Adapter). **Node.js** → Q2 |
| Q2 | Do you require a container image deployment? | **Yes** → **Event Functions**. **No** → **Web Functions** |
| Q3 | (Only if an integration is already in place) What does the app integrate with today? | **CloudFront** → **Web Functions**. **API Gateway** → **Event Functions** (existing integrations are real migration cost; move them deliberately) |

Result: **Web Functions** → route to **aws-lambda-web-functions** (On-Demand only; Provisioned Concurrency, SnapStart and Managed Instances do not apply). Essentials if that skill is not loaded: the Node.js server keeps listening on its port with no handler rewrite; zip deployment via `aws lambda-web create-web-function` (an unrecognized `lambda-web` command means the AWS CLI is outdated); many concurrent requests share one execution environment and billing is active CPU + memory, so time blocked on I/O is not billed as CPU; native response streaming (SSE, LLM tokens); a global HTTPS endpoint with optional multi-Region serving, CloudFront in front. **Event Functions** → Tier 3.

### Tier 3 — Capacity provider (Event Functions only)

Event Functions run on one of two capacity providers. **On-Demand** scales to zero and suits spiky or unpredictable traffic with meaningful idle periods. **Lambda Managed Instances** runs the function on EC2 instances in your account and fits continuously utilized traffic (peak-to-mean ratio below 2 within 5–10 minutes); a required EC2 instance type; Savings Plans / Reserved Instance pricing; or executions up to 90 minutes (async or ESM invocations only). Typical Managed Instances workloads: continuously busy stream consumers, always-busy APIs behind API Gateway, and long async batch jobs.

Infer traffic shape from the request or metrics. If it is missing and changes the decision, ask once in observable terms: *"Does peak traffic stay below twice the average within any 5–10 minute window (peak-to-mean ratio below 2), or does it spike higher or drain and sit idle for meaningful periods? Do you require committed-use pricing or a specific instance type?"*

- No traffic, duration, instance-type or pricing signal → **Event Functions · On-Demand** as the recommendation, with no capacity question (Rule 3, Unraised).
- Bursty or idle periods, with no instance/commitment requirement → **Event Functions · On-Demand**.
- Continuously utilized, or an instance/commitment requirement → **Event Functions · Managed Instances** → route to **aws-lambda-managed-instances**.

Managed Instances is chosen when the function is created: create a new function attached to a capacity provider and shift traffic to it; do not describe this as toggling a setting on an existing On-Demand function.

Also choose Managed Instances when a single execution needs more than 15 minutes, up to 90 minutes (async or ESM invocation only; synchronous invocations keep the 15-minute ceiling on both providers). Do not reopen an explicit continuous/always-busy signal merely to ask about instance type or pricing. If the request says only "steady" without observable traffic shape, ask whether it truly runs continuously or has long idle periods. Words such as "bursty", "light", "uneven" or "quiet for long stretches" lean **On-Demand** but are Leaning hints (Rule 3) when Managed Instances is being weighed: recommend On-Demand provisionally and ask how many invocations run at the same time at peak (Managed Instances packs several simultaneous invocations into one execution environment, so it pays off only when they run concurrently) and whether traffic really drops to zero. Many short parallel tasks are not by themselves a Managed Instances signal; ask whether the work is a one-off or periodic batch that drains to zero (On-Demand) or a continuous stream (Managed Instances).

### Tier 4 — Edge cases (after form factor and capacity are locked)

Headline decisions; the questions to ask, thresholds and caveats are in [compute-decision-edge-cases.md](references/compute-decision-edge-cases.md) — read it whenever a request raises one of these.

- **Duration** — Treat total durable-workflow duration and the duration of one active invocation as separate limits. An unspecified upper bound is not a value: *"long-running"*, *"well past 15 minutes"* or similar wording does not imply > 90 minutes. For an asynchronous or event-source-mapping invocation known to exceed 15 minutes but with no stated maximum, provisionally recommend **Managed Instances** and ask: *"What is the maximum duration of the longest single invocation?"* ≤ 90 min → **Managed Instances**; > 90 min → **aws-containers** / **aws-compute**. For a customer-managed sandbox or stateful session, use **MicroVMs** for up to 8 h; a MicroVM session > 8 h → **aws-compute**. A synchronous Event Function > 15 min → **aws-containers** / **aws-compute**. Multiple coordinated Lambda tasks → **Durable Functions** (Step 3).
- **Stream or queue lag** (backlog, `ApproximateAgeOfOldestRecord` climbing) → **provisioned mode for the event source mapping** (min/max pollers); Provisioned Concurrency does nothing for a backlog — [concurrency.md](references/concurrency.md).
- **First-request latency on On-Demand** → the free levers first (a smaller deployment package, fewer or lighter layers, lazy initialization, right-sized memory — [lambda.md](references/lambda.md)), then choose among three levers: **Provisioned Concurrency** when environment start-up is the delay and double-digit-millisecond overhead is required; **SnapStart** when heavy initialization code on Java, Python or .NET makes sub-second acceptable (zip or any container image); **Managed Instances** when traffic never reaches zero and holds a steady floor. An explicit "always busy" or continuous-traffic signal is already Decided → **Managed Instances**, with no lever question. Traffic that comes in waves or goes "quiet" does not say whether it reaches zero: give a provisional lever and ask whether traffic drops to zero, the runtime, and whether the delay is environment start-up or initialization code.
- **Packaging is a separate decision from capacity** — zip vs container image is decided by artifact size (past the zip limits → container image, [lambda.md](references/lambda.md)), while traffic shape decides the capacity provider. When native binaries or large dependencies are mentioned without a size, recommend On-Demand with a container image if it exceeds the zip limits and ask the packaged size.
- **Steady or "always busy" traffic cited to remove cold starts** → **Managed Instances** (warm, multi-concurrent instances remove cold starts).
- **Untrusted or user-submitted code** → provisionally **MicroVMs** (VM-level session isolation, OS access, state that persists under a customer-managed lifecycle). If the request does not say whether the code may be adversarial, needs elevated OS access or custom ports, or keeps state across runs, ask, and state both paths: short, stateless runs of untested but non-adversarial code from authenticated users can stay on **Event Functions · On-Demand**, where each execution environment runs one invocation at a time and is never shared across functions.
- **Tenant isolation** → event handlers that need execution environments dedicated to one invoker use **tenant isolation mode** on Event Functions · On-Demand; this does not create a fresh VM per invocation. A persistent per-tenant environment, untrusted code, retained files/processes or OS access → **MicroVMs**. A bare "strict tenant isolation" requirement is Leaning (Rule 3): recommend tenant isolation mode provisionally and ask whether tenants run their own code or need a persistent environment or OS access.
- **Conflicting signals** — for example a Node.js web app with steady high-volume traffic (Web Functions by programming model, Managed Instances by traffic) → present both options with the one-line tradeoff and let the user decide; otherwise commit to one recommendation.

### Hand-off after the decision

Apply every relevant row. A specialized skill owns each implementation dimension; a component can require both a compute skill and an orchestration skill. For Event Functions · On-Demand, open only the reference whose trigger applies.

| Decision or feature | Continue with |
|---|---|
| Event Functions · Managed Instances | **aws-lambda-managed-instances** |
| Web Functions | **aws-lambda-web-functions** |
| MicroVMs | **aws-lambda-microvms** |
| Durable Functions | **aws-lambda-durable-functions** |
| Event Functions · On-Demand — function configuration: memory, timeout, VPC, layers, Function URLs, cold starts, SnapStart, packaging (zip vs container image) | [lambda.md](references/lambda.md) |
| Event Functions · On-Demand — the trigger: SQS, DynamoDB Streams, SNS, Kinesis, filtering, batch failures | [event-sources.md](references/event-sources.md) |
| Event Functions · On-Demand — reserved or Provisioned Concurrency, throttling, ESM provisioned mode for stream or queue lag | [concurrency.md](references/concurrency.md) |
| Event Functions · On-Demand — SAM/CDK/CloudFormation resources and deployment | [deployment.md](references/deployment.md) |
| Event Functions · On-Demand — wiring API Gateway, DynamoDB or VPC internet access | The SOPs below |

## Step 3 — Orchestration: Durable Functions vs Step Functions

Route here when the user wants to coordinate multiple steps, services, or functions. Triggers include "orchestration", "workflow", "state machine", "multi-step coordination", "coordinate Lambda functions", "durable execution", "pipeline with retries", a saga/compensation pattern, human approval, fan-out, or long-running async coordination.

When starting a new orchestration, surface AWS Lambda Durable Functions and AWS Step Functions before implementing unless the request already supplies a complete deciding fact. Retries, branching, waits, approvals, and a generic "on AWS" statement are shared orchestration signals, not state-machine signals: when these are all the request supplies, present both choices and their tradeoff up front, ask the implementation-model question, and do not choose either service yet. Resolve orchestration independently of compute and capacity. You can use Durable Functions as an orchestrator for MicroVMs.

- **Code-first signals → recommend Durable Functions as the single answer** (mention Step Functions in one line at most; do not present them as co-equal options or ask the implementation-model question): the workflow should live in application code or "normal code"; the user names a supported Durable Functions runtime (Python 3.13+, Node.js 22+, Java 17+ or .NET 8+; Rust and Go in preview); the workflow is placed on Lambda ("on Lambda", "all steps are Lambda functions") and needs durable behavior such as a human approval or callback, a long wait (days up to a year), checkpointed progress that survives failures, resume, retries or compensation; or the workflow replaces hand-built checkpoint/retry state. Calls from durable steps to external APIs or databases remain code-first operations; they do not make the workflow heterogeneous. State the deciding reasons explicitly: orchestration stays in application code in a supported runtime, and an asynchronously invoked durable execution can wait for up to 1 year at no compute cost while suspended.
- **State-machine signals → recommend Step Functions** (mention Durable Functions in one line at most): the user explicitly wants ASL/state-machine authoring, a visual/auditable workflow, a shared cross-team contract, JSONata for payload and data transformation, Distributed Map (up to 10,000 parallel child executions, iterating over hundreds of millions of items), TestState for unit testing individual states, or an unsupported runtime.
- **Implementation model unstated** — only when the request names neither a supported language nor Lambda as the place the steps run, and has no state-machine signal (a generic saga, approval, fan-out, retry, branching, or crash-recovery request "on AWS") → provisionally recommend **Lambda Durable Functions** for code-first orchestration, name **AWS Step Functions** as the visual/ASL and broad service-integration alternative with the one-line tradeoff, and ask: *"Will every step run as your own code on Lambda, or should a visual state machine coordinate other AWS services?"* When the durable design itself is also unclear, ask how long the longest wait can last or whether any step must run exactly once. Durable signals alone (waits, approvals, crash recovery) establish that orchestration is needed, not where it lives. Do not infer Step Functions merely because code calls an external API or database.

**Tradeoff (use when either fits):** Durable Functions keeps orchestration in Lambda application code — Python 3.13+, Node.js 22+, Java 17+ or .NET 8+, with Rust and Go in preview — with checkpoint/replay (`context.step` / `context.wait` / `context.invoke`), retries, conditions, callbacks, and execution history. Durable executions can run up to 1 year on async invocations at zero cost while waiting; each step remains bounded by its Event Functions capacity-provider timeout. Step Functions externalizes orchestration into a managed visual state machine with 200+ native service integrations and Distributed Map (Standard executions up to 1 year, Express up to 5 minutes). Full comparison: [orchestration.md](references/orchestration.md); implementation belongs to the routed skill.

## Step 4 — Eventing: which EventBridge capability

Choose the capability from the use case the request describes (trigger, event origin, topology, existing investment); do not ask EventBridge clarifying questions. Full details are in [orchestration.md](references/orchestration.md).

- **Time-based triggers** (cron, rate, one-time; retries, maximum event age and a DLQ) → **EventBridge Scheduler**, not rules with a schedule expression or an always-on worker.
- **One poll-based source to one Lambda function** (SQS, Kinesis, DynamoDB Streams, Kafka/MSK, Amazon MQ), with native batching/filtering/retry controls sufficient → the **Event Function's native event source mapping**, not a Pipe.
- **One poll-based source to one target with filtering, enrichment, or transformation**, or a non-Lambda target → **EventBridge Pipes**. A Pipe has exactly one target.
- **Several consumers need events from a poll-based source** → one Pipe may filter/enrich and target the **new custom event bus**; each consumer owns a subscriber. Do not create one Pipe per consumer merely to simulate fan-out.
- **AWS service state-change events on the default bus**, or an established classic single-account integration → **EventBridge rules** with content-based patterns.
- **A new workload publishing its own application events**—including a single-account workload—or one needing independent subscribers, retention/replay, ordering, deduplication, schema registry, or cross-team/account sharing → **new EventBridge custom event bus** (`eventsv2`) → **amazon-eventbridge-event-bus**.
- **An existing classic custom bus moving to new-bus capabilities** → **amazon-eventbridge-event-bus** migration guidance. Bridge classic and new buses so producers and consumers move independently; keep classic for unsupported requirements such as Global Endpoints.

If steps must run in a defined order with checkpointed progress, retries, waits, or compensation, that is orchestration rather than eventing: decide Durable Functions vs Step Functions in Step 3.

## Step 5 — HTTP front door

Node.js HTTP server → **Web Functions** (Tier 2). When the request asks for an HTTP endpoint without saying the runtime or server model and whether API management is needed, it is Leaning (Rule 3): name the three options (Web Functions for a Node.js server, API Gateway in front of an Event Function, a Function URL for one function without API management), give the provisional default, and ask the runtime/server model and whether per-client rate limits, API keys, WAF or request validation are required. Otherwise put **API Gateway HTTP API** in front of Event Functions by default — up to ~70% lower per-request price than REST API and lower latency — and move to **REST API** only for its exclusive features (WAF, usage plans and API keys, request validation and transformation, caching, canary deployments, private or edge-optimized endpoints); say this cost/feature tradeoff explicitly when recommending an API front door. Persistent bidirectional connections → **API Gateway WebSocket API**; a single Event Function that needs an HTTPS endpoint without API management → **Lambda Function URL**. Front-door table, quotas and authorizers: [api-gateway.md](references/api-gateway.md); wiring procedures: the API Gateway SOPs below.

## Step-by-step task procedures (tested CLI SOPs)

| Use this skill | For the task |
|---|---|
| **connecting-lambda-to-api-gateway** | Wire an existing Lambda to a new REST/HTTP API: proxy integration, permissions, CORS, throttling, access logging, deployment |
| **connecting-lambda-to-dynamodb** | Connect Lambda to DynamoDB: IAM execution role, read/write permissions, stream event source mapping |
| **creating-api-gateway-stage** | Create an API Gateway stage with CloudWatch logging, X-Ray tracing, throttling, WAF association, and authorization |
| **deploying-custom-domain-rest-api** | Deploy a Regional REST API with custom domain: ACM cert, Lambda backend, request authorizer, base path mapping, Route 53 DNS |
| **debugging-lambda-timeouts** | Systematically diagnose a timing-out Lambda: config, CloudWatch logs/metrics, VPC, cold starts, memory, downstream calls |
| **enabling-lambda-vpc-internet-access** | Give a VPC-attached Lambda internet access: NAT Gateway, subnet routing, security groups |
| **processing-s3-uploads-with-step-functions** | Deploy an event-driven workflow: S3 upload → EventBridge → Step Functions → Lambda (small files) or Fargate (large files), with VPC/ECR/ECS/IAM |

## Shared references in this skill

| User need | Read |
|-----------|------|
| Tier 4 edge cases: duration ceilings, cold start vs stream lag, SnapStart and Provisioned Concurrency, steady-state Managed Instances, tenant isolation | [compute-decision-edge-cases.md](references/compute-decision-edge-cases.md) |
| Patterns for a new serverless application once compute is chosen | [architecture.md](references/architecture.md) |
| Lambda config, cold starts, SnapStart, memory, VPC, layers, Function URLs | [lambda.md](references/lambda.md) |
| Concurrency (reserved, provisioned, ESM controls including provisioned mode) | [concurrency.md](references/concurrency.md) |
| Event sources (SQS, DynamoDB Streams, SNS, Kinesis), filtering, batch failures | [event-sources.md](references/event-sources.md) |
| Step Functions vs Durable Functions comparison, Standard vs Express, EventBridge capability table, rules/pipes/scheduler details | [orchestration.md](references/orchestration.md) |
| HTTP front-door table, API Gateway quotas, authorizers, WebSocket | [api-gateway.md](references/api-gateway.md) |
| SAM/CDK resource types and fast iteration | [deployment.md](references/deployment.md) |
| Production readiness, observability, anti-patterns | [production.md](references/production.md) |
| Debugging an error (exact string → cause → fix) | [troubleshooting.md](references/troubleshooting.md) |
| Powertools handler template | [powertools-handler.py](assets/powertools-handler.py) |

## Security considerations

- Every recommendation inherits the Lambda baseline: least-privilege execution roles per function, no `*` resource policies on Function URLs or API Gateway (`AuthType: NONE` and open access are never defaults), encryption at rest for queues, streams and state, and CloudTrail plus CloudWatch alarms on errors and throttles.
- Orchestration services persist workflow state and payloads — Step Functions records full input/output in execution history (console and, if enabled, CloudWatch Logs). Enable execution logging, alarm on failures, use least-privilege per-workflow roles, never pass secrets, tokens or PII through workflow state (reference them by Secrets Manager/ARN pointer), and apply a customer-managed KMS key when state is sensitive.
- For ordinary multi-tenant handlers, tenant isolation mode dedicates Event Functions execution environments to one invoker; it is not a fresh VM per invocation. Use MicroVMs for untrusted code, retained per-session state, customer-controlled lifecycle, or OS access. Do not rely on application-level sandboxing inside a shared execution environment.
- Public HTTP endpoints (Web Functions, API Gateway, Function URLs) should sit behind AWS WAF with throttling, input validation and TLS via ACM certificates.

**Note:** Reference files contain specific runtime versions, quotas, pricing premiums and feature matrices that change. When precision matters (production, runtime choice, quotas), confirm against current AWS documentation. The references focus on values and gotchas that are easy to get wrong — not on basics.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's **own bundled files** — the `references/` documents and `assets/powertools-handler.py` — from different places. Determine how the skill was loaded before you read one:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not installed on the local filesystem**; its reference and asset files do not exist on disk. You MUST fetch each one through the same `retrieve_skill` tool by passing the `file` parameter (for example, `file="references/lambda.md"` or `file="assets/powertools-handler.py"`). Do NOT `file_read` these paths from the local or working directory, and do NOT search the filesystem for them — they are not there, and any local file that happens to match the name is unrelated to this skill.
- **Installed locally** (the skill lives in a local skills directory such as `.claude/skills/aws-serverless/`, `~/.claude/skills/aws-serverless/`, or `.kiro/skills/aws-serverless/`). Read references and assets from the local skill directory using the relative paths shown throughout this document.

This distinction applies **only** to the skill's own packaged files. The user's application code — handlers, SAM/CDK templates, `package.json`, deployment artifacts — is always read from and written to the user's working directory regardless of how the skill was loaded. Never fetch or write customer data through `retrieve_skill`.
