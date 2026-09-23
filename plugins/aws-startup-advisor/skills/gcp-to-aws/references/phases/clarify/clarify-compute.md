# Category B — Configuration Gaps + Category C — Compute Model

This file covers two related categories:

- **Category B** — Configuration gaps for billing-source inventories (factual questions to fill inferred data)
- **Category C** — Compute model questions (platform and traffic pattern decisions)

---

## Category B — Configuration Gaps (Billing-Only Mode)

_Fire when:_ `billing-profile.json` exists AND `gcp-resource-inventory.json` does NOT exist (billing-only mode).
_Skip when:_ `gcp-resource-inventory.json` exists (Terraform/IaC provides configuration directly).

These fill factual gaps that billing data alone cannot answer. Answers update the inventory understanding — they do not produce design constraints directly.

Each question fires only when the matching `gcp_service_type` appears in `billing-profile.json → services[]`:

- **Cloud SQL HA**: Single-zone or high-availability? _(fire if `google_sql_database_instance` in billing services)_
  > Default: assume Zonal is intentional.
- **Cloud Run service count**: How many distinct services? _(fire if `google_cloud_run_service` in billing services)_
  > Default: assume 1 service.
- **Memorystore memory size**: How much memory (GB)? _(fire if `google_redis_instance` in billing services)_
  > Default: estimate from usage amount.
- **Cloud Functions generation**: Gen 1 or Gen 2? _(fire if `google_cloudfunctions_function` in billing services)_
  > Default: assume Gen 1.

Record Category B answers in `metadata.inventory_clarifications`.

---

## Category C — Compute Model (If Compute Resources Present)

_Fire when:_ Compute resources present (Cloud Run, Cloud Functions, GKE, GCE, App Engine).

---

## Q7b — What compute operational model do you prefer for your App Engine workloads?

_Fire when:_ App Engine present in inventory (`google_app_engine_application`) AND Q5 != 1 (multi-cloud). Skip when: no App Engine in inventory, or Q5 = 1 (multi-cloud already resolved compute to EKS — App Engine routes to EKS, overriding the EB default; same portability override as Q8).

**Rationale:** GCP App Engine is a PaaS that can map to different AWS compute targets depending on whether the user wants to preserve the managed platform model (Elastic Beanstalk), switch to direct container control (Fargate/ECS), or go serverless (Lambda). This drives the fundamental routing decision for App Engine resources.

Note: This question does NOT affect Cloud Run resources. Cloud Run maps to Fargate via its own deterministic fast-path regardless of this answer.

> Your App Engine setup uses a managed platform (you provide code, Google manages everything else). On AWS, you have a few options for these workloads:
>
> 1. Managed platform — I provide code, AWS manages everything else (like App Engine today)
> 2. Container orchestration — I want direct control over containers and scaling
> 3. Serverless — Event-driven functions, scale-to-zero, stateless
> 4. I don't know — recommend the best fit

| Answer            | Recommendation Impact                                                              |
| ----------------- | ---------------------------------------------------------------------------------- |
| Managed platform  | Elastic Beanstalk — preserves PaaS model, AWS manages deployments/scaling/patching |
| Container control | ECS Fargate — direct container management with full VPC/ALB/IAM integration        |
| Serverless        | Lambda — event-driven, stateless functions with scale-to-zero                      |
| I don't know      | Default: Elastic Beanstalk (PaaS-to-PaaS, closest match to App Engine)             |

Interpret:

```
1 -> compute_model: "managed_platform" — Elastic Beanstalk recommended
2 -> compute_model: "container_orchestration" — ECS Fargate recommended
3 -> compute_model: "serverless" — Lambda recommended
4 -> same as default (1)
```

**Default:** **1** (`compute_model: "managed_platform"`). App Engine is PaaS; Elastic Beanstalk is the closest AWS equivalent. Users who skip or say "I don't know" get the PaaS-to-PaaS path.

_Note: If Q5=Yes (multi-cloud), this question is skipped — `compute: "eks"` is already decided and App Engine routes to EKS, overriding the EB default (mirrors Q8)._

---

## Q8 — How does your team feel about managing Kubernetes?

_Fire when:_ GKE cluster present AND Q5 != 1 (multi-cloud). Skip when: Q5 = 1 (already resolved to EKS) or no GKE in inventory.

**Rationale:** When multi-cloud is not required (Q5=No) and GKE is detected, team sentiment is the deciding factor between EKS and ECS Fargate. This is subjective and cannot be inferred from IaC.

**Context for user:** When asking, frame it practically so the user gives an honest answer rather than aspirational:

- **Love it / K8s expert** — your team writes Helm charts, debugs CrashLoopBackOff in their sleep, and actively chose K8s
- **Neutral / Competent** — K8s works, your team can operate it, but it's not a passion project
- **Frustrated / Steep curve** — K8s feels like overhead; your team spends more time fighting YAML than shipping features

> Your team's Kubernetes experience determines whether we recommend EKS (Kubernetes on AWS) or ECS Fargate (simpler managed containers).
>
> 1. Love it / Team is K8s expert
> 2. Neutral / Competent with K8s
> 3. Frustrated / Learning curve steep
> 4. N/A — We don't use Kubernetes
> 5. I don't know

| Answer                   | Recommendation Impact                                                                                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Love it / K8s expert     | EKS recommended — preserves existing Kubernetes investment and expertise                                     |
| Neutral / Competent      | EKS recommended with managed node groups to reduce operational burden                                        |
| Frustrated / Steep curve | **Strong ECS Fargate recommendation** — eliminates Kubernetes management entirely; simpler operational model |

_Note: If Q5=Yes (multi-cloud), this question is skipped and EKS is already decided._

Interpret:

```
1 -> kubernetes: "eks-managed" — EKS recommended, preserves K8s investment
2 -> kubernetes: "eks-or-ecs" — EKS with managed node groups to reduce operational burden
3 -> kubernetes: "ecs-fargate" — Strong ECS Fargate recommendation, eliminates K8s management
4 -> (no constraint written — no K8s workloads)
5 -> same as default — see IaC-signal default rule below
```

**Default (IaC-signal driven):**

- If `gcp-resource-inventory.json` contains `google_container_cluster` resources → Default **3** (`kubernetes: "ecs-fargate"`). Teams that answer "I don't know" are better served by Fargate's lower operational overhead; EKS remains available via explicit answers 1 and 2.
- If no `google_container_cluster` in inventory (Cloud Run, Cloud Functions, or billing-only) → Default **3** (`kubernetes: "ecs-fargate"`). No Kubernetes signal; Fargate is the lower-ops starting point.
- If inventory is absent (billing-only mode) → Default **3** (`kubernetes: "ecs-fargate"`).

**Rationale:** Teams that answer 5 ("I don't know") have not expressed a Kubernetes preference. Defaulting to Fargate gives them a simpler, lower-ops starting point regardless of what discovery found. Teams who actively want EKS will answer 1 or 2 explicitly. EKS remains fully available via explicit answers 1 and 2.

---

## Q9 — Do any of your services need WebSocket support or long-lived connections?

_Fire when:_ Compute resources present AND WebSocket usage cannot be determined from inventory.

**Auto-extract signal:** Only when application code was analyzed (see Clarify Step 2 item 14). If code was scanned and no WebSocket patterns found, extract `websocket: false` and skip. **If no code was analyzed** (Terraform-only), always ask Q9 — do not infer absence of WebSockets.

**Rationale:** WebSocket support affects load balancer configuration.

> WebSocket support affects load balancer configuration. This confirms whether ALB WebSocket configuration is needed in the migration templates.
>
> 1. Yes — Real-time features, WebSockets, persistent connections
> 2. No — Standard HTTP/HTTPS only
> 3. I don't know

| Answer                  | Recommendation Impact                                                         |
| ----------------------- | ----------------------------------------------------------------------------- |
| Yes — WebSockets needed | ECS Fargate or EKS required; ALB with WebSocket support included in templates |
| No — HTTP only          | ECS Fargate recommended for simple stateless services                         |

Interpret:

```
1 -> websocket: "required" — ALB with WebSocket support, ECS Fargate or EKS required
2 -> (no constraint written)
3 -> same as default (2) — assume no WebSocket; can be reconfigured later
```

Default: 2 — no constraint.

---

## Q10 — What's your typical traffic pattern for your Cloud Run services?

_Fire when:_ Cloud Run present in inventory. Skip when: no Cloud Run.

**Auto-extract signal:** When Cloud Run `min_instance_count` / `min_instances` > 0 in Terraform config, extract `cloud_run_traffic_pattern: "constant-24-7"` with `chosen_by: "extracted"` and **skip Q10**.

**Rationale:** Cloud Run's scale-to-zero is its primary cost advantage.

> Cloud Run's scale-to-zero is its primary cost advantage. Understanding your traffic pattern helps me determine whether migrating Cloud Run to AWS makes financial sense.
>
> 1. Business hours only (9am–5pm weekdays, ~40 hrs/week)
> 2. Active most of the day (16–20 hours, ~120 hrs/week)
> 3. Constant 24/7 traffic (~168 hrs/week)
> 4. N/A — We don't use Cloud Run
> 5. I don't know

| Answer              | Recommendation Impact                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------- |
| Business hours only | AWS likely 40–50% MORE expensive — recommend staying on Cloud Run or flagging cost increase prominently |
| Active most of day  | Moderate cost difference — present both options with cost comparison                                    |
| Constant 24/7       | AWS costs similar or cheaper — ECS Fargate recommended as straightforward migration                     |

Interpret:

```
1 -> cloud_run_traffic_pattern: "business-hours" — AWS likely 40-50% MORE expensive; flag cost increase
2 -> cloud_run_traffic_pattern: "most-of-day" — Moderate cost difference; present both options
3 -> cloud_run_traffic_pattern: "constant-24-7" — AWS costs similar or cheaper; ECS Fargate recommended
4 -> (no constraint written — Cloud Run not used)
5 -> same as default (3) — assume constant traffic for conservative estimate
```

Default: 3 — `cloud_run_traffic_pattern: "constant-24-7"`.

---

## Q11 — Approximately how much are you spending on Cloud Run per month?

_Fire when:_ Cloud Run present in inventory. Skip when: no Cloud Run.

**Rationale:** Absolute spend determines whether the migration math makes financial sense regardless of traffic pattern. Low-spend Cloud Run workloads are rarely worth the migration complexity.

> Absolute Cloud Run spend determines whether the migration math makes financial sense regardless of traffic pattern.
>
> 1. < $100/month
> 2. $100–$500/month
> 3. $500–$1,500/month
> 4. $1,500/month
> 5. N/A — We don't use Cloud Run
> 6. I don't know

| Answer            | Recommendation Impact                                                            |
| ----------------- | -------------------------------------------------------------------------------- |
| < $100/month      | Recommend staying on Cloud Run — migration cost and complexity exceeds savings   |
| $100–$500/month   | Present cost comparison; migration may make sense if consolidating to AWS        |
| $500–$1,500/month | Fixed-cost AWS options (ECS Fargate reserved capacity) become attractive         |
| > $1,500/month    | Strong case for migration to ECS Fargate with Savings Plans or reserved capacity |

Interpret:

```
1 -> cloud_run_monthly_spend: "<$100" — Recommend staying on Cloud Run; migration cost exceeds savings
2 -> cloud_run_monthly_spend: "$100-$500" — Present cost comparison; migration may make sense if consolidating
3 -> cloud_run_monthly_spend: "$500-$1500" — Fixed-cost AWS options attractive (ECS Fargate reserved)
4 -> cloud_run_monthly_spend: ">$1500" — Strong case for ECS Fargate with Savings Plans
5 -> (no constraint written)
6 -> same as default (2)
```

Default: 2 — `cloud_run_monthly_spend: "$100-$500"`.

---

## Q11b — Target Graviton (ARM64) for eligible compute?

_Applies when:_ Compute resources are present in the inventory. (If no compute resources, skip — do not write `cpu_architecture`.)

**Risk signals (precise definition):** a `graviton_profile` entry carries a risk signal when its `tier` is `incompatible`, or its `tier` is `conditional`/`unknown` due to any of: native C extensions (`node-gyp`, niche Python C packages), native gem extensions, JNI (`System.loadLibrary`/`JNI_OnLoad`), recompile-required languages (Rust/C/C++) or x86 SIMD/intrinsics, a `platform: linux/amd64` pin, proprietary/vendor AMIs, or an architecture that could not be determined (`unknown`). These mirror the detection tables in `references/shared/schema-graviton.md`.

**Decision table (evaluate top-down; first match wins):**

| Discovery state                                                                                                                                                                                           | Action                                                                                                                                                                                                        |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `graviton_profile` emitted at all (e.g., billing-only, or Discover produced none) but compute is present                                                                                               | **Ask** Q11b — architecture is unconfirmed                                                                                                                                                                    |
| ALL compute entries `tier: ready`                                                                                                                                                                         | **Skip.** Write `cpu_architecture = {"value": "graviton", "chosen_by": "default"}` (matches existing `db.t4g` default)                                                                                        |
| Mix of `ready` + `incompatible` only (no `conditional`/`unknown`)                                                                                                                                         | **Skip the question** but write `cpu_architecture = {"value": "mixed", "chosen_by": "default"}` (Graviton where ready, x86 for incompatible) and state this in the AI/Clarify summary so the user is informed |
| All profiles for not-all-`ready` compute are `source: "iac"` with no `app_code` profile for the same service (architecture unconfirmed by code — e.g. a `conditional` from a `machine_type` signal alone) | **Ask** Q11b                                                                                                                                                                                                  |
| Any entry `conditional` or `unknown` with a risk signal                                                                                                                                                   | **Ask** Q11b                                                                                                                                                                                                  |
| Any entry `incompatible` only, no `ready` compute at all                                                                                                                                                  | **Skip.** Write `cpu_architecture = {"value": "x86", "chosen_by": "default"}`                                                                                                                                 |

**Rationale:** Graviton (ARM64) is ~15–20% cheaper per hour at the same vCPU/memory, so we default to it whenever every service is confirmed compatible. We only spend a question when a service has a real compatibility caveat or the architecture is unconfirmed — never defaulting Graviton onto an `unknown` workload without asking.

> Some of your services have ARM64 compatibility considerations. Graviton (ARM64) instances are ~15–20% cheaper per hour. Your [language] workloads appear compatible; [service X] has [caveat]. How would you like to proceed?
>
> 1. Yes — target Graviton for all eligible services (recommended)
> 2. No — stay on x86 for everything
> 3. Let me decide per-service (Graviton where ready, x86 for flagged services)

| Answer             | Recommendation Impact                                                                  |
| ------------------ | -------------------------------------------------------------------------------------- |
| Yes — all eligible | Graviton for ready + conditional services; x86 only for incompatible ones              |
| No — stay x86      | x86 everywhere; forgoes the ~15–20% hourly discount                                    |
| Per-service        | Graviton for `ready`; flagged `conditional`/`unknown` services stay x86 pending review |

Interpret:

```
1 -> cpu_architecture: {"value": "graviton", "chosen_by": "user"}
2 -> cpu_architecture: {"value": "x86", "chosen_by": "user"}
3 -> cpu_architecture: {"value": "mixed", "chosen_by": "user"}
```

Default (if skipped/unsure): `{"value": "graviton", "chosen_by": "default"}` when all-ready; otherwise `{"value": "mixed", "chosen_by": "default"}`. See `references/shared/graviton.md` and `references/shared/schema-graviton.md`.
