# Lambda Concurrency Controls

Four concurrency controls operate at different levels with non-obvious interactions. The exact numbers and mutual-exclusivity rules below are the part that's easy to get wrong.

## The 4 concurrency types

1. **Reserved Concurrency** (scope: function) — sets the **max** concurrent instances AND reserves that capacity from the account pool. Setting to **0** fully throttles the function (emergency shutoff). Use to protect critical functions, cap to protect downstream, or kill-switch.

2. **Provisioned Concurrency** (scope: published version or alias — **NOT `$LATEST`**) — pre-initializes environments so they're ready before requests arrive. Spills to on-demand (with cold starts) beyond the provisioned count. Combine with Application Auto Scaling (~70% target). Paid even when idle.

3. **Maximum Concurrency** (scope: per SQS ESM, range **2–1,000**) — caps how many concurrent instances one SQS ESM can invoke. Does **not** reserve anything; other triggers can still consume function concurrency.

4. **Provisioned Mode — ESM** (SQS and Kafka/MSK) — allocates dedicated event pollers for an SQS/Kafka ESM with configurable min/max. Per-poller capacity is an **OR** envelope and differs by source: **SQS = 1 MB/s or 10 concurrent invokes**; **Kafka/MSK = 5 MB/s or 5 concurrent invokes**. Use for high-throughput or spiky traffic where standard ramp-up (5 → +300/min) is too slow.

## Key numbers and interactions

- **Account RPS quota = 10 × account concurrency** (e.g. 1,000 concurrency → 10,000 RPS, across all functions). This is an account quota, not a per-instance cap. Per-instance throughput = 1 / function duration.
- **Max reservable = account limit − 100.** Lambda always keeps 100 unreserved.
- **Scaling rate: 1,000 new environments / 10s, per function**
- Provisioned ≤ Reserved when both are set (reserved is the ceiling).
- Provisioned counts against the account limit even when idle — monitor `ClaimedAccountConcurrency`.

| Combination | OK? | Notes |
|-------------|:---:|-------|
| Reserved + Provisioned | Yes | Provisioned ≤ Reserved |
| Reserved + Maximum Concurrency (ESM) | Yes | Reserved ≥ Σ(Maximum Concurrency across ESMs) |
| Provisioned + Maximum Concurrency / Provisioned Mode (ESM) | Yes | Different layers |
| **Maximum Concurrency + Provisioned Mode (same ESM)** | **No** | **Mutually exclusive** |
| **Provisioned Concurrency + SnapStart** | **No** | **Mutually exclusive** |

**At the limit:** Sync → 429. Async → retries up to 6h then DLQ. Streams → polling throttled, messages stay in source.

**RPS gotcha:** a 50ms function at 20,000 RPS needs only 1,000 concurrency, but the RPS limit (10×1,000 = 10,000) throttles it. Request account concurrency = 2,000.

```bash
aws service-quotas request-service-quota-increase \
  --service-code lambda --quota-code L-B99A9384 --desired-value 5000
```

## Decision scenarios

| Scenario | Reserved | Provisioned | Maximum Concurrency (ESM) | Prov Mode (ESM) |
|----------|:--------:|:-----------:|:--------------:|:---------------:|
| Protect critical API / cap downstream | Yes | — | — | — |
| Eliminate cold starts (user-facing API) | Optional | Yes | — | — |
| Multiple SQS queues, prevent hogging | Yes | — | Yes | — |
| High-throughput SQS, low-latency | Optional | Optional | — | Yes |
| Kafka/SQS ESM with spiky traffic | — | — | — | Yes |
| Predictable daily traffic | — | Yes + AutoScale | — | — |
| Emergency shutoff | Yes (=0) | — | — | — |

## Common mistakes

1. **Reserved = 0 left over from an incident** — blocks ALL invocations (429). If a function throttles at low traffic, check this first.
2. **Reserved too low** — reserve 50, need 80 → throttled at 51 even with spare account capacity.
3. **Starving other functions** — reserved is subtracted even when unused; be conservative.
4. **Provisioned without auto scaling** — paying for idle off-peak, spilling on-peak.
5. **Provisioned on `$LATEST`** — doesn't work; publish a version, create an alias.
6. **Maximum Concurrency > reserved** — ESM tries 100, function caps at 50. Ensure reserved ≥ Σ(Maximum Concurrency).
7. **Confusing ESM Maximum Concurrency with reserved** — Maximum Concurrency reserves nothing; API Gateway can still consume all concurrency.
8. **Forgetting the 100-unit buffer** — max reservable = account limit − 100.

## SnapStart vs Provisioned Concurrency

> **Mutually exclusive on the same function.**

```
Runtime Java 11+ / Python 3.12+ / .NET 8+
├─ No  → Provisioned Concurrency
└─ Yes
   ├─ Need guaranteed <50ms on EVERY request? → Provisioned Concurrency
   ├─ Need EFS or >512MB ephemeral storage?   → Provisioned Concurrency
   └─ Otherwise → SnapStart first; if P99 still too high, switch (they cannot coexist)
```

## SAM/CDK property reference

| Type | SAM | CDK |
|---|---|---|
| Reserved | `ReservedConcurrentExecutions` | `reservedConcurrentExecutions` |
| Provisioned | `AutoPublishAlias` + `ProvisionedConcurrencyConfig.ProvisionedConcurrentExecutions` | `new lambda.Alias({ provisionedConcurrentExecutions })` (alias, not `$LATEST`) |
| Maximum Concurrency (ESM) | `ScalingConfig.MaximumConcurrency` | `maxConcurrency` on `EventSourceMapping` |
| Provisioned Mode (ESM) | `ProvisionedPollerConfig.MinimumPollers` / `MaximumPollers` | `provisionedPollerConfig: { minimumPollers, maximumPollers }` |
| SnapStart | `SnapStart.ApplyOn: PublishedVersions` + `AutoPublishAlias` | `snapStart: lambda.SnapStartConf.ON_PUBLISHED_VERSIONS` |

Auto scaling: `alias.addAutoScaling({ minCapacity, maxCapacity })` then `scaling.scaleOnUtilization({ utilizationTarget: 0.7 })`.
