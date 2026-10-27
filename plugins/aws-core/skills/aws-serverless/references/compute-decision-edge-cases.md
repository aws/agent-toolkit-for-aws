# Compute Decision Edge Cases (Tier 4)

Tier 4 of the compute decision flow in `SKILL.md`: feature-level questions that are decided **after** the form factor and capacity provider are locked. Each section gives the question to ask, the decision, and the thresholds and caveats that the one-line summary in `SKILL.md` leaves out. Read this file when a request raises duration limits, cold starts or first-request latency, stream or queue lag, or tenant isolation.

## Contents

- [Duration ceilings](#duration-ceilings)
- [Long-lived sessions and long executions](#long-lived-sessions-and-long-executions)
- [Cold start vs stream lag](#cold-start-vs-stream-lag)
- [First-request latency](#first-request-latency)
- [Steady-state traffic: Managed Instances](#steady-state-traffic-managed-instances)
- [Tenant isolation](#tenant-isolation)

---

## Duration ceilings

| Form factor / feature | Ceiling | Notes |
|---|---|---|
| Event Functions · On-Demand | 15 min per invocation | Every invocation type |
| Web Functions | 15 min per request | Node.js only; On-Demand only |
| Event Functions · Managed Instances | 90 min per invocation | Asynchronous and event source mapping invocations only; synchronous invocations keep the 15-minute ceiling |
| MicroVMs | 8 h per session | Customer-managed lifecycle (launch/suspend/resume/terminate) within the session |
| Durable Functions | 1 year per execution (async invocation) | Each step is bounded by the Lambda timeout of the capacity provider it runs on; waits cost nothing |
| Step Functions | Standard 1 year, Express 5 min | See [orchestration.md](orchestration.md) |

Anything longer than these is outside Lambda: **aws-containers** (ECS/Fargate) or **aws-compute** (EC2).

---

## Long-lived sessions and long executions

Ask for the overall duration and, if the work splits into tasks, the per-task duration (the per-step ceiling is min(task, overall)).

- MicroVMs: session > 8 h → **aws-compute** (EC2); otherwise MicroVMs.
- Functions with multiple coordinated tasks → **Durable Functions** on Event Functions (`SKILL.md` Step 3); the remaining choice is On-Demand vs Managed Instances per step duration.
- Single **Event Function** invocation > 15 min → if asynchronous or invoked through an event source mapping and up to 90 min, use **Managed Instances**; if > 90 min, or synchronous and > 15 min, use **aws-containers** / **aws-compute**. This does not apply to MicroVM sessions, which use the 8 h session ceiling above.

---

## Cold start vs stream lag

Decide form factor, programming model, and capacity first. Infer the symptom from metrics or the request when possible. If it is still unclear, ask in customer-observable terms: *"Is only the first request after an idle period slow, or is a queue/stream backlog growing while traffic is being processed?"*

- **Stream/queue lag** (consumer backlog, `ApproximateAgeOfOldestRecord` or `IteratorAge` climbing, Kafka consumer lag) → **provisioned mode for the event source mapping** (minimum and maximum pollers / event poller units), on either Event Functions capacity provider. Provisioned mode controls input delivery: how quickly the event source mapping reads the source and hands records to Lambda. Provisioned Concurrency controls environment availability and does nothing for a backlog. Details: [concurrency.md](concurrency.md).
- **First-request latency** → next section.

---

## First-request latency

### Event Functions on On-Demand

1. Start with the levers that cost nothing: a smaller deployment package and fewer or lighter layers, lazy initialization outside the hot path, and right-sized memory — [lambda.md](lambda.md). (arm64/Graviton is a price-performance choice, not a cold-start fix.)
2. Use the stated latency objective when available. If the objective would change the choice and is missing, ask whether the application requires consistently double-digit-millisecond startup overhead or whether sub-second startup is sufficient.
   - Double-digit milliseconds → **Provisioned Concurrency**.
   - Sub-second → **SnapStart** if the runtime is Java, Python, or .NET, for zip or a container image: it snapshots the initialized execution environment after heavy initialization and resumes from that snapshot. Values generated during initialization must be regenerated when uniqueness matters, and network connections must be re-established after restore ([lambda.md](lambda.md)). Other runtimes → Provisioned Concurrency.
3. If traffic runs continuously (peak-to-mean ratio below 2 within 5–10 minutes), Managed Instances may remove repeated environment launches — next section.

### Web Functions

Web Functions use On-Demand capacity, but Provisioned Concurrency and SnapStart do not apply. Optimize application initialization and dependency loading, then continue with **aws-lambda-web-functions** for its latency and concurrency guidance. Do not send a Web Functions workload through the Event Functions Provisioned Concurrency/SnapStart decision path.

---

## Steady-state traffic: Managed Instances

Steady state or "always busy" traffic cited to eliminate environment-launch latency → **Managed Instances**: warm, multi-concurrent instances remove repeated cold starts. Infer this from continuous utilization when the request or metrics establish it. If traffic shape is missing, ask whether peak traffic stays below twice the average within any 5–10 minute window (peak-to-mean ratio below 2) or drains and sits idle for meaningful periods. The threshold follows from how Managed Instances scales: asynchronously on CPU utilization and multi-concurrency saturation, so traffic that more than doubles within 5 minutes can be throttled while capacity is added ([scaling](https://docs.aws.amazon.com/lambda/latest/dg/lambda-managed-instances-scaling.html)). Using Managed Instances requires creating a new function; Savings Plans and Reserved Instance pricing apply.

---

## Tenant isolation

- Event and request handlers have **per-function isolation by default**; this is not a promise of a fresh Firecracker VM or a new execution environment for every invocation.
- Handlers that need execution environments dedicated to one invoker or tenant → Event Functions on **On-Demand** with **tenant isolation mode**: set at creation, every invoke carries a tenant id, and environments assigned to one tenant are not reused for another. Tenant isolation mode is On-Demand only (not available on Managed Instances) and is not compatible with Function URLs, Provisioned Concurrency, or SnapStart.
- A persistent per-tenant environment, untrusted user- or LLM-generated code, retained memory/disk/processes, or OS access (FUSE, eBPF, custom ports) → **MicroVMs** (**aws-lambda-microvms**). Isolation is per MicroVM environment and persists with that environment's lifecycle.
- Do not rely on application-level sandboxing inside a shared execution environment.
