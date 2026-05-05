# Lambda Concurrency Controls

Four concurrency controls operate at different levels, solve different problems, and have complex interactions.

## Contents

- [The 4 concurrency types](#the-4-concurrency-types)
- [Interaction matrix](#interaction-matrix)
- [Decision scenarios](#decision-scenarios)
- [Account limits and scaling](#account-limits-and-scaling)
- [Common mistakes](#common-mistakes)
- [SnapStart interaction](#snapstart-interaction)
- [SAM/CDK examples](#samcdk-property-reference)

---

## The 4 concurrency types

### 1. Reserved Concurrency
Sets the **maximum** concurrent instances for a function and **reserves** that capacity from the account pool so no other function can consume it.

- **Scope:** Function.
- Reserve 400 → function always gets up to 400, never more. Others share the rest.
- Setting to **0** completely throttles the function (emergency shutoff).
- Use for: protecting critical functions, capping to protect downstream, emergency shutoff.

### 2. Provisioned Concurrency
Pre-initializes execution environments so they are **ready before requests arrive**.

- **Scope:** Published version or alias (**NOT** `$LATEST`).
- **Allocation rate:** Up to 6,000 environments per minute when provisioning.
- Configure 100 on alias `PROD` → first 100 concurrent requests get sub-10ms startup.
  Request 101+ spills to on-demand with cold starts.
- **Account-level RPS quota**: RPS = 10 × account concurrency. For example, 1,000 account concurrency → 10,000 RPS cap across all functions. This is an account-level quota, not a per-instance throughput cap. Per-instance throughput = 1 / function duration.
- Combine with **Application Auto Scaling** (target ~70% utilization).
- Use for: user-facing APIs, functions with heavy init (ML models, DB pools).

### 3. Maximum Concurrency
Limits how many concurrent instances a **specific SQS event source mapping (ESM)** can invoke.

- **Scope:** Per ESM. **Range:** 2–1,000. **Sources:** SQS only.
- Does **not** reserve anything — other triggers can still consume function concurrency.
- Use for: multiple SQS queues on one function, rate-limiting a specific queue.

### 4. Provisioned Mode — ESM (Kafka 2024, SQS 2025)
Allocates **dedicated event pollers** for an SQS or Kafka ESM with configurable min/max.

- **Scope:** Per ESM.
- Standard mode: ~5 pollers, +300/min, max 1,250 invokes. Provisioned mode: you control
  min/max pollers. Each handles up to 1 MB/s, 10 concurrent invokes.
- Use for: high-throughput SQS/Kafka, spiky traffic where standard ramp-up is too slow.

---

## Interaction matrix

| Combination | OK? | Notes |
|-------------|:---:|-------|
| Reserved + Provisioned | Yes | Provisioned ≤ Reserved |
| Reserved + Max Concurrency (ESM) | Yes | Reserved ≥ Σ(max concurrency across ESMs) |
| Reserved + Provisioned Mode (ESM) | Yes | Independent layers |
| Provisioned + Max Concurrency (ESM) | Yes | Different layers |
| Provisioned + Provisioned Mode (ESM) | Yes | Warms envs vs warms pollers |
| **Max Concurrency + Provisioned Mode (same ESM)** | No | **Mutually exclusive** |
| **Provisioned Concurrency + SnapStart** | No | **Mutually exclusive** |

**Key rules:** Account limit is the hard ceiling. Reserved carves from the pool — Lambda
always keeps **100 unreserved**. Provisioned ≤ Reserved when both set. Max Concurrency is
advisory to the ESM, not the function.

```
┌──────────────────────────────────────────────────────┐
│  ACCOUNT: 1,000 concurrency                          │
│  ┌─────────────────┐  ┌───────────────────────────┐  │
│  │ RESERVED (400)   │  │ UNRESERVED POOL (600)     │  │
│  │ ┌─────────────┐  │  │ Shared by all others      │  │
│  │ │PROVISIONED  │  │  │ Must keep ≥100 always     │  │
│  │ │(200 warm)   │  │  └───────────────────────────┘  │
│  │ └─────────────┘  │                                 │
│  │ + 200 on-demand  │  ESM LAYER (per mapping):       │
│  └─────────────────┘  Max Concurrency — OR —          │
│                        Provisioned Mode (not both)     │
└──────────────────────────────────────────────────────┘
```

---

## Decision scenarios

| Scenario | Reserved | Provisioned | Max Conc (ESM) | Prov Mode (ESM) |
|----------|:--------:|:-----------:|:--------------:|:---------------:|
| Protect critical API from starvation | Yes | — | — | — |
| Cap function to protect downstream DB | Yes | — | — | — |
| Eliminate cold starts for user-facing API | Optional | Yes | — | — |
| Multiple SQS queues, prevent hogging | Yes | — | Yes | — |
| High-throughput SQS, low-latency | Optional | Optional | — | Yes |
| Kafka ESM with spiky traffic | — | — | — | Yes |
| Predictable daily traffic | — | Yes+AutoScale | — | — |
| Emergency shutoff | Yes (=0) | — | — | — |
| Java/.NET heavy init | — | Yes or SnapStart | — | — |

**A — Checkout API:** Reserved=200 + Provisioned=150 + Auto Scaling for peak.
**B — 3 SQS queues → 1 function:** Reserved=300, Max Concurrency=100 per ESM.
**C — Kafka stream (spiky):** Provisioned Mode min=5, max=50 pollers.
**D — Batch job:** Reserved=50, no provisioned.

---

## Account limits and scaling

| Quota | Default | Adjustable? |
|-------|---------|:-----------:|
| Account concurrency | 1,000 / Region | Yes |
| Reservable concurrency | Account − 100 | Scales |
| RPS limit | 10 × concurrency | Scales |
| Scaling rate | 1,000 envs / 10s / function | No |

Scaling is per-function, continuously refilled, unused capacity does not accumulate.
~50 seconds to reach 5,000 concurrency from zero.

**At the limit:** Sync → 429. Async → retries up to 6h then DLQ. Streams → polling
throttled, messages stay in source.

**RPS constraint:** A 50ms function at 20,000 RPS needs only 1,000 concurrency but the RPS
limit (10×1,000=10,000) throttles it. Request account concurrency = 2,000.

```bash
aws service-quotas request-service-quota-increase \
  --service-code lambda --quota-code L-B99A9384 --desired-value 5000
```

---

## Common mistakes

1. **Reserved set to 0** — Blocks ALL invocations (429 TooManyRequestsException). Sometimes
   set during an incident and not restored. If a function is throttled at low traffic, check
   this first.

2. **Reserved too low** — Reserve 50, need 80 → throttled at 51 even with spare account
   capacity. Fix: monitor `ConcurrentExecutions`, set above peak + buffer.

3. **Starving other functions** — Reserve 800/1,000 → others share 200. Reserved is
   subtracted even when unused. Fix: be conservative.

4. **Provisioned without auto scaling** — Paying for idle envs off-peak, spilling on-peak.
   Fix: Auto Scaling targeting ~70% `ProvisionedConcurrencyUtilization`.

5. **Provisioned on `$LATEST`** — Doesn't work. Fix: publish a version, create an alias.

6. **Max concurrency > reserved** — ESM tries 100, function caps at 50. Fix: ensure
   `reserved ≥ Σ(max concurrency across ESMs)`.

7. **Confusing ESM max with reserved** — Max concurrency doesn't reserve anything. API
   Gateway can still consume all concurrency. Fix: use reserved on the function.

8. **Both ESM controls on same ESM** — Mutually exclusive; API rejects it. Fix: choose one.

9. **Forgetting 100-unit buffer** — Max reservable = account limit − 100.

10. **Not tracking ClaimedAccountConcurrency** — Provisioned counts against account limit
   even when idle. Monitor the metric.

---

## SnapStart interaction

| Aspect | SnapStart | Provisioned Concurrency |
|--------|-----------|------------------------|
| Cold start | Seconds → sub-second | Seconds → ~0 |
| Runtimes | Java 11+, Python 3.12+, .NET 8+ | All |
| Scales with traffic | Yes (snapshot restore) | Only up to provisioned count |

> **SnapStart and Provisioned Concurrency are mutually exclusive on the same function.**

```
Is runtime Java 11+, Python 3.12+, or .NET 8+?
├─ No  → Provisioned Concurrency
└─ Yes
   ├─ Need guaranteed <50ms on EVERY request? → Provisioned Concurrency
   ├─ Need EFS or >512MB ephemeral storage?   → Provisioned Concurrency
   └─ Otherwise → SnapStart first; if P99 still too high, switch to Provisioned Concurrency (they cannot coexist)
```

Limitations: no EFS, no >512MB ephemeral, no container images, must handle uniqueness,
re-validate network connections on restore.

---

## SAM/CDK property reference

| Concurrency type | SAM property | CDK property |
|---|---|---|
| Reserved | `ReservedConcurrentExecutions: 100` | `reservedConcurrentExecutions: 100` |
| Provisioned | `AutoPublishAlias: live` + `ProvisionedConcurrencyConfig.ProvisionedConcurrentExecutions: 50` | `new lambda.Alias({ provisionedConcurrentExecutions: 50 })` — must use alias, not `$LATEST` |
| Maximum Concurrency (ESM) | `ScalingConfig.MaximumConcurrency: 50` | `maxConcurrency: 50` on `EventSourceMapping` |
| Provisioned Mode (ESM) | `ProvisionedPollerConfig.MinimumPollers` / `MaximumPollers` | `provisionedPollerConfig: { minimumPollers, maximumPollers }` on `EventSourceMapping` |
| SnapStart | `SnapStart.ApplyOn: PublishedVersions` + `AutoPublishAlias` | `snapStart: lambda.SnapStartConf.ON_PUBLISHED_VERSIONS` |

Auto scaling for Provisioned Concurrency: `alias.addAutoScaling({ minCapacity, maxCapacity })` then `scaling.scaleOnUtilization({ utilizationTarget: 0.7 })`.
