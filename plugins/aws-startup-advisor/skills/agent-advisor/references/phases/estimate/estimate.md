---
_phase: estimate
_title: "Estimate — Coarse Cost Magnitude"
_requires_phase: design
_input:
  - design.json
_knowledge:
  - { file: references/decision-refs/cost-levers.md, _when: "always (drivers step)" }
_assemble:
  _file: phases/estimate/estimate-assemble.md
_produces:
  - estimate.json
_advances_to: generate
_interactive: false
_exec:
  _agent: rw
_preconditions:
  - _check_phase_completed: design
    _on_failure: _halt_and_inform
  - _check_file_exists: design.json
    _on_failure: _unrecoverable
  - _validate_json: design.json
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: estimate.json
    _on_failure: _halt_and_inform
  - _validate_json: estimate.json
    _on_failure: _halt_and_inform
  - _assert: "estimate.json states a monthly_magnitude_usd band (never a precise total), records pricing_source (cached|cached_stale|mcp), and lists every assumption behind the magnitude; estimate.json has a units{} entry per costed unit and a total band; top-level fields mirror the primary unit; each costed unit carries a breakdown {compute, model_tokens, other}; drivers[] cites only levers from cost-levers.md"
    _on_failure: _halt_and_inform
---

# Phase: Estimate — Coarse Cost Magnitude

All entry points except add_capabilities run Estimate. Scope: target-state run cost per unit,
presented as order-of-magnitude bands. This phase NEVER produces a TCO comparison or current-spend
delta — that belongs to the Migration Plan engine (for migrate entry points); do not duplicate or
contradict its numbers. The add_capabilities branch runs its own self-contained flow and never
reaches here. Magnitude only — NOT precise estimation (that's the migration skills' job). Mirrors
the migration skills' pricing pattern.

## Step 1 — Read the design and answers

Read `$RUN_DIR/design.json` and `$RUN_DIR/answers.json`. Extract `primary_unit` from answers.json
and the `units[]` array from design.json. Each unit has `id`, `workload_class`, `verdict`, and
(for agent units) `deployment_model`.

## Step 2 — Pricing source (cached, same as the migration skills)

1. Primary: a small cached rate table (inline below — AgentCore vCPU/GB-hour, Fargate, Lambda,
   plus the model default's token rates as order-of-magnitude). Carry a "last updated" date.
2. Record `pricing_source`: `cached` | `cached_stale` (if >90 days old).

Cached anchors (order-of-magnitude, us-east-1, verify; last updated 2025-07-14):

- AgentCore (microVMs compute type): ~$0.0895/vCPU-hour (active CPU only), ~$0.00945/GB-hour
- AgentCore (Instances compute type, `agentcore_compute_type: "instances"` in design.json):
  EC2 On-Demand rate for the chosen instance type (user's Savings Plans / ODCRs apply) PLUS
  an AgentCore management fee — NOT consumption-based and NOT $0 during I/O wait. No cached
  anchor here: use the instance type from the user's `instance_type_requirement` answer (else
  assume a mid-size general-purpose type and say so), and set `pricing_source: cached_stale`
  for that component with a note to verify the EC2 rate before committing.
- Lambda MicroVMs: ~$0.0997/vCPU-hour, ~$0.0132/GB-hour
- Fargate: ~$0.04048/vCPU-hour, ~$0.004445/GB-hour
- Bedrock model token rates: defer to the `gcp-to-aws` pricing cache (`skills/gcp-to-aws/references/shared/pricing-cache.md`) for exact figures

## Step 3 — Produce a magnitude per unit, not a quote

For EACH unit in design.json.units[], estimate a rough monthly band based on its workload_class
and its **`effective_runtime`** — NOT its `verdict`. Under a consolidated platform a unit actually
runs on `platform.runtime` (its `effective_runtime`), so it must be COSTED there: a unit whose
`verdict` is `batch` but whose `effective_runtime` is `ecs` bills as an always-on ECS Fargate task,
not as scale-to-zero AWS Batch. In a split run `effective_runtime == verdict`, so nothing changes.
Where a bullet below says "verdict", read `effective_runtime`. The pricing shape depends on the
unit's class:

**EKS pricing rule — applies to ANY unit whose `effective_runtime == "eks"`, regardless of
class (agent_session, service, batch, light_io):** price by the cluster's ACTUAL node capacity
type — do NOT assume Fargate. EKS-on-Fargate → the Fargate vCPU/GB anchor; EC2 managed nodes /
Karpenter / Spot / GPU → EC2 instance pricing for the stated instance type (Spot discount when
stated); reusing an existing cluster → near-zero marginal cost ONLY when the user stated there is
spare capacity to absorb the workload — otherwise Karpenter/ASG adds nodes and the full
incremental node cost applies, so price the added EC2/Fargate capacity the workload needs. State
the capacity-type assumption (and whether spare capacity was assumed). When the capacity type or
instance is unknown, set `pricing_source: cached_stale` and note the
assumption; do not assume Fargate. A W1
"existing cluster reuse" verdict or a consolidation onto EKS can land a service/batch unit here —
this rule governs it, NOT the class default below.

- **agent_session units** (effective_runtime = agentcore | lambda_microvms | ecs | eks | lambda):
  estimate as today — runtime + model + stated usage assumption (sessions/mo, duration, I/O wait
  %). Apply the cached anchors from Step 2 (AgentCore vCPU/GB, Lambda MicroVMs, Fargate) plus
  Bedrock model token rates. For a `lambda` runtime use Lambda request pricing (invocations ×
  duration × memory). For `eks`, apply the EKS pricing rule above. Any runtime missing a cached
  anchor: set `pricing_source: cached_stale` and state the assumption.
  For answers, read `answers.json.units[<unit_id>]` (which is already fully resolved — system +
  unit dims merged).

- **batch units** (verdict from workload-classes.md: AWS Batch → Fargate compute; scheduled Lambda):
  - When `effective_runtime == "eks"` (W1 existing-cluster reuse or a consolidation onto EKS):
    apply the EKS pricing rule above — NOT the AWS Batch / Fargate shape.
  - AWS Batch (long runs, GPU, large memory): Fargate vCPU-hour + GB-hour × run count/month. State
    assumptions: run frequency, duration, vCPU/GB per run.
  - Scheduled Lambda (short runs ≤ 15 min): Lambda request pricing (invocations × duration ×
    memory). State assumptions: schedule frequency, duration, memory.

- **light_io units** (verdict: Lambda or Fargate behind ALB):
  - Lambda (spiky/scale-to-zero): request pricing (invocations/month × avg duration × memory).
    State assumptions: request volume, duration, memory.
  - Fargate (sustained high traffic): vCPU-hour + GB-hour for always-on service. State assumptions:
    vCPU/GB allocation, % utilization.

- **service units** (verdict: Fargate ECS, or existing cluster reuse): Fargate vCPU-hour + GB-hour
  for long-running service. State assumptions: vCPU/GB allocation, % utilization. When
  `effective_runtime == "eks"` (W1 existing-cluster reuse or a consolidation onto EKS), apply the
  EKS pricing rule above instead of the flat Fargate anchor.

- **temporal_worker_poll units** (verdict from Tier 1: ecs / eks / serverless_workers): estimate the
  polling tier and the execution tier separately per the cost table shape below. The polling tier
  is the worker-fleet compute, priced by `effective_runtime`:
  - `effective_runtime == "ecs"` (Fargate) → tens of $/month (small).
  - `effective_runtime == "eks"` → NOT automatically small; apply the EKS pricing rule above
    (this class is subject to it like any other): EKS-on-Fargate → the Fargate anchor, but EC2
    managed nodes / Karpenter / Spot / GPU fleets → EC2 instance pricing, and a GPU worker fleet
    can run into hundreds–thousands of $/month, not "tens". State the node-capacity assumption.
  - `effective_runtime == "serverless_workers"` → Temporal Serverless Workers is **Public
    Preview, not GA** (labeled so regardless of any docs claim — the label has moved before
    without a GA announcement). Do NOT invent a cached anchor: give a **qualitative fallback** (state
    "Serverless Workers pricing is Public Preview / unverified — treated as a scale-to-zero
    execution-billed tier; confirm the published rate before committing") rather than a
    fabricated dollar band. Every other cost line for the unit still gets its band; only the SW
    polling line may be qualitative when the rate is unverified.

  **Charge ONLY the worker-fleet polling compute to the `temporal_worker_poll` unit's
  `monthly_magnitude_usd`.** The execution tier (LLM tokens, AgentCore sessions, batch compute) is
  the cost of the ACTIVITY-class units, which are ALREADY costed as their own `units{}` entries
  and already in `total_monthly_magnitude_usd` — do NOT also add execution cost into the worker
  unit or you DOUBLE-COUNT every Activity. The execution tier is USUALLY the dominant tier — same
  tokens as today (the migration moves them, it doesn't multiply them) — but do NOT assert
  dominance unconditionally: COMPARE the worker unit's polling band against the aggregate of the
  Activity units' bands (a comparison for the takeaway, NOT an addition). When Activity volume is
  low OR the polling fleet is on GPU/added EKS nodes (hundreds–thousands of $/mo), the polling
  tier can equal or exceed the aggregate Activity cost — say which dominates based on the numbers,
  or that they are comparable. For Temporal Cloud, derive actions line from user volume × $0.01/action
  when Way = cloud; self-hosted gets a qualitative-only ops line (no dollar figure). State
  assumptions per tier.

  The temporal cost table below:

  | Cost line                                                                          | Magnitude                                                                                                                                          | Note                                                                                                                  |
  | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
  | Polling tier (worker fleet: ECS / EKS / Serverless Workers)                        | tens of $/mo on ECS-Fargate; EKS priced by node capacity (EC2/Spot/GPU can be hundreds+); Serverless Workers Public Preview → qualitative fallback | small only on Fargate — size per the EKS pricing rule when effective_runtime==eks; SW rate unverified until confirmed |
  | Execution tier = the ACTIVITY units' own costs (already their own units{} entries) | usually dominant — but compare, do NOT re-add                                                                                                      | same tokens as today; counted ONCE via the Activity units — never folded into the worker unit; compare vs polling     |
  | Temporal Cloud actions (system-level orchestration)                                | derive from the user's volume × $0.01/action                                                                                                       | new line vs self-hosted; or unchanged if already on Cloud                                                             |
  | What it replaces                                                                   | qualitative only                                                                                                                                   | self-hosted cluster ops burden — no dollar figure                                                                     |

  One takeaway sentence: on ECS-Fargate the execution tier dominates and the polling tier is
  noise — but on EKS with EC2/GPU nodes (or under low Activity volume) the polling fleet can be
  material or even dominant, so compare the two computed bands rather than assuming an order.

  **Important:** Temporal Cloud actions are a SYSTEM-LEVEL cost (orchestration dispatches for
  ALL Activities), NOT attributable to any single unit — so do NOT fold them into any unit's
  `breakdown.other` or `monthly_magnitude_usd`. When Way = cloud, record them ONCE at the system
  level: add them into `total_monthly_magnitude_usd` and surface them as their own assumption in
  the top-level `assumptions` (e.g. "Temporal Cloud orchestration: N actions/mo ×
  $0.01"). This is the estimate.json source for the report's system-level "— orchestration"
  roll-up row (generate-report.md); it is deliberately a system line, not a per-unit breakdown
  entry, because the per-unit `breakdown` is fixed at `{compute, model_tokens, other}`. Way =
  self_hosted contributes no orchestration dollar line (qualitative ops burden only).

State every assumption per unit. Never present a precise total — always a band (e.g. "$10–30").

For each unit, also structure the components you just computed into a `breakdown` — don't flatten
them into the total: `compute` (runtime/request pricing: AgentCore or Lambda MicroVMs vCPU/GB,
Fargate, Lambda requests), `model_tokens` (Bedrock token costs — `null` for units that call no
models), and `other` (everything else: ALB, storage). Every component is a band, never precise —
EXCEPT when a component's rate is genuinely unverifiable (a Serverless Workers Public Preview
polling tier with no published cached rate): set that component to the string
`"unverified"` instead of a fabricated band, and reflect it in `monthly_magnitude_usd` — if the
unverified component is the only compute line, the unit's `monthly_magnitude_usd` is the band of
its remaining priced components plus a `"+ unverified SW polling"` suffix (e.g. `"40-120 +
unverified SW polling"`), never a made-up total. State the unverified rate in that unit's
`assumptions`. All other units/components stay strict dollar bands.

> Determinism note: this magnitude is computed in the LLM layer (convention-aligned with
> the migration skills, which also estimate in-skill). It is the one output that is NOT
> script-deterministic. Acceptable for v1 (magnitude-only, every assumption stated); flagged as
> a future candidate to move into a small deterministic script if precision is ever required.

## Step 4 — Identify cost drivers per unit

For each unit, determine what moves the cost and which optimization levers apply. Emit one
`drivers[]` entry per unit with the shape:

```json
{
  "unit": "<unit_id>",
  "driver": "<what moves the number>",
  "effect": "<band per increment>",
  "lever": "<from cost-levers.md, cited>"
}
```

Load `references/decision-refs/cost-levers.md` and cite only the levers documented in that table.
Do not invent discounts or optimizations outside of the table.

- **driver**: the primary cost input (e.g., "session count × avg duration", "batch runs/month", "model tokens", "request volume")
- **effect**: order-of-magnitude impact per increment (e.g., "+$10-30 per 1k sessions", "+$5-15 per 100 batch runs")
- **lever**: the applicable cost-optimization lever from cost-levers.md (e.g., "Model tier routing (Sonnet→Haiku for triage/simple items)", "Prompt caching", "Scale-to-zero runtimes"). Cite the lever name exactly as it appears in the table. If no lever applies, use `null`.

**IMPORTANT:** Each driver's lever must be the cost-levers.md lever that actually fits THAT
driver. Do not pick a legal-but-irrelevant lever. For example:

- A batch/OCR compute-bound driver (e.g., "pages × duration") should use "Batch inference" or
  right-sizing levers, NOT "Scale-to-zero runtimes" (AWS Batch is already scale-to-zero).
- An agent-session driver (e.g., "session count × duration") fits "Scale-to-zero runtimes" when
  traffic is spiky/idle-heavy.
- Model token drivers fit "Model tier routing", "Prompt caching", or "Batch inference" depending
  on the workload's latency tolerance.

Example for an agent_session unit:

```json
{
  "unit": "ai-customer-support",
  "driver": "session count × avg duration",
  "effect": "+$10-30 per 1k sessions",
  "lever": "Model tier routing (Sonnet→Haiku for triage/simple items)"
}
```

Example for a batch unit:

```json
{
  "unit": "weekly-report-generator",
  "driver": "batch runs/month",
  "effect": "+$5-15 per 100 runs",
  "lever": "Batch inference"
}
```

## Step 5 — Write estimate.json

Assemble per-unit estimates under `units{}`, compute the system total, populate the top-level
legacy mirror from the primary unit, and include the `drivers[]` array:

```json
{
  "units": {
    "<unit_id>": {
      "monthly_magnitude_usd": "50-150",
      "breakdown": {
        "compute": "10-30",
        "model_tokens": "40-120",
        "other": "0-5"
      },
      "assumptions": ["1000 sessions/mo, 5 min avg, 60% I/O wait"]
    },
    "<unit_id_2>": {
      "monthly_magnitude_usd": "10-30",
      "breakdown": {
        "compute": "10-25",
        "model_tokens": null,
        "other": "0-5"
      },
      "assumptions": ["500 batch runs/mo, 10 min avg, 2 vCPU/4GB"]
    }
  },
  "drivers": [
    {
      "unit": "<unit_id>",
      "driver": "session count × avg duration",
      "effect": "+$10-30 per 1k sessions",
      "lever": "Model tier routing (Sonnet→Haiku for triage/simple items)"
    },
    {
      "unit": "<unit_id_2>",
      "driver": "batch runs/month",
      "effect": "+$5-15 per 100 runs",
      "lever": "Batch inference"
    }
  ],
  "total_monthly_magnitude_usd": "60-180",
  "total_compute": "20-55",
  "total_model": "40-120",
  "total_other": "0-10",
  "monthly_magnitude_usd": "50-150",
  "pricing_source": "cached",
  "assumptions": ["1000 sessions/mo, 5 min avg, 60% I/O wait"],
  "note": "Order-of-magnitude only. For a precise estimate use the migration skills (gcp-to-aws or heroku-to-aws)."
}
```

**Legacy mirror (collapse + compatibility):** the primary unit's `monthly_magnitude_usd`,
`assumptions` are ALSO written at the top level (exactly as today). The top-level
`pricing_source` and `note` apply to the entire estimate. `total_monthly_magnitude_usd` is the
sum of the units' band edges PLUS any system-level line not attributable to a single unit
(e.g. Temporal Cloud orchestration actions when Way = cloud), rounded to a clean band (e.g.,
units of 50-150 and 10-30 → total 60-180; add the orchestration band on top when present). The
system-level line is recorded in the top-level `assumptions`, never inside a unit's `breakdown`.
Also emit `total_compute`, `total_model`, `total_other` — the per-column sums of the units'
`breakdown.compute` / `model_tokens` / `other` bands (Generate renders these as the cost table's
Total row). **Unverified handling (uniform across all three column totals AND
`total_monthly_magnitude_usd`):** when a component is the string `"unverified"` (a Serverless
Workers Public Preview rate the MCP could not confirm) or `null`, EXCLUDE it from the numeric sum
and append a `"+ unverified"` suffix to that total's band (e.g. `total_compute` = `"20-55 +
unverified"`, and `total_monthly_magnitude_usd` likewise carries `"+ unverified SW polling"`).
Never coerce an unverified component to $0 — an excluded-and-flagged band, never a silent drop.

Single-unit runs produce today's estimate.json plus a one-key `units` map (the collapse invariant:
single unit = today's behavior + additive `units{}` key).

## Step 6 — Write state

Set `phases.estimate` = completed.
