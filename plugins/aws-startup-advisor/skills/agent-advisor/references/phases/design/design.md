---
_phase: design
_title: "Design"
_requires_phase: confirm
_input:
  - scoring-result.json
  - confirm.json
  - model-recommendation.json
_knowledge:
  - { file: references/decision-refs/workload-classes.md, _when: "any unit has workload_class != agent_session" }
  - { file: references/decision-refs/temporal.md, _when: "any unit has workload_class == temporal_worker_poll or the temporal context is detected" }
_assemble:
  _file: phases/design/design-assemble.md
_produces:
  - design.json
_advances_to: estimate
_preconditions:
  - _check_phase_completed: confirm
    _on_failure: _halt_and_inform
  - _check_file_exists: [scoring-result.json, confirm.json, model-recommendation.json]
    _on_failure: _unrecoverable
  - _validate_json: [scoring-result.json, confirm.json, model-recommendation.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: design.json
    _on_failure: _halt_and_inform
  - _validate_json: design.json
    _on_failure: _halt_and_inform
  - _assert: "Every unit selecting registry records its intended Registry Region and current-run verified Registry availability; cached or unavailable Regions cannot satisfy this check. A user-confirmed omission is reflected in both confirm.json and design.json service lists, including the primary-unit mirrors."
    _on_failure: _halt_and_inform
  - _assert: "design.json has one units[] entry per inventory unit, a platform block consistent with confirm.platform_decision, and top-level legacy fields mirroring the primary unit; design.json has top-level verdict, chosen_runtime, deployment_model, agentcore_compute_type, agentcore_services, model_recommendation, and carries scores + eliminated (and blocking_constraints when present) copied verbatim from scoring-result.json; every agentcore-verdict unit carries agentcore_compute_type (microvms or instances) verbatim from its scoring result and every non-agentcore unit carries null — the compute type is never re-derived in Design; every model-bearing unit's model_recommendation is derived from the matching model-recommendation.json workload entry and accepted confirm.model_decision, including model_identity, model, api_path, invocation_model_id, source, source_analysis, feature_assessment, compatibility, architecture_impacts, additional_targets (separate-modality target contracts, carried verbatim when present), blocks, tuning, migration_deltas, evaluation, rollout, provisional verification, and live_verification when model-verification.json exists; no model was independently selected from scoring-result.json; handoff_required is true iff ANY unit's effective_runtime needs a compute handoff — one of ecs, eks, fargate, or batch (not just the primary/winning runtime; AgentCore/Lambda/Lambda MicroVMs are self-contained); when temporal units exist, design.json has a temporal block recording the Way, per-queue Tier 1 rule ids, and Serverless Workers labeled Public Preview regardless of any docs label; Workflow orchestration code is never rewritten; every unit carries a key_change line derived from its runtime's service card; every non-agent unit's verdict equals the runtime its workload-classes rule maps to (W1→eks/ecs; W2→batch; W3/W4→lambda; W5/W6→fargate) — verdict and workload_class are never contradictory; every unit carries an effective_runtime equal to platform.runtime when platform.mode is consolidated, else its own resolved runtime (a co_recommend unit resolves to its confirm chosen_runtime) — effective_runtime is always a concrete runtime enum, never the literal co_recommend"
    _on_failure: _halt_and_inform
---

# Phase: Design

Assembles the recommendation from the scoring result + Confirm choices + service cards.

## Step 1 — Read inputs

Read `$RUN_DIR/scoring-result.json`, `$RUN_DIR/model-recommendation.json`, and
`$RUN_DIR/confirm.json`. The winning runtime is
`confirm.chosen_runtime` if present (co_recommend pick), else `scoring-result.verdict`. Prefer
`confirm.deployment_model` and `confirm.agentcore_services` over the scoring-result defaults (Confirm
is the user-confirmed set). (Clarify's scope gate guarantees at least one agent_session unit, so a
scored top-level verdict always exists — there is no zero-agent branch.)

If `$RUN_DIR/model-verification.json` exists, read it and attach each workload's matching
record as `live_verification`. Do not infer `passed` from `confirm.model_decision.accepted`;
acceptance and target-account invocability are separate.

## Step 2 — Load the winning runtime's service card

Load ALL THREE files (each is required; do not skip any — Step 4's lock-in check depends on
`managed-alternatives.md` even when no lock-in ends up applying):

1. `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/<verdict>.md` (use
   `lambda-microvms.md` for lambda_microvms; use `ecs.md` for `fargate` — ECS-on-Fargate
   shares the ecs card; `batch` has its own `batch.md`; for co_recommend, load both cards).
   **`serverless_workers` has NO card** — skip this load for it and derive from `temporal.md`
   plus `poc-shapes.md` per the key_change note below.
2. `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/model-selection.md`
3. `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/managed-alternatives.md`

## Step 3 — Refresh volatile facts

Load `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/freshness.md` and follow its procedure:
read the winning profile's `volatile_facts`, try the AWS MCP Server for each, fall back to cached
values on failure. Record which succeeded vs fell back (for the freshness footer).
When any unit selects `registry`, also load the AgentCore service card and the
`registry_regions` fact from `references/runtimes/agentcore.json`, even for non-AgentCore
runtime winners. Apply `freshness.md`'s Registry availability procedure in Step 4d.

## Step 4 — Provider lock-in check

Determine the managed alternative from the source/current model provider: Claude-committed →
`claude_managed`; OpenAI-committed → `bedrock_managed`; multi-provider or undecided → `none`.
If a managed alternative applies, surface it **as awareness only** (per `managed-alternatives.md`)
with its tradeoffs — do NOT present it as the recommendation. Otherwise note AgentCore supports
all models.

## Step 4b — I/O-wait TCO differentiator (surface proactively)

Most customers don't know AgentCore Runtime (and Harness) bill **$0 during I/O wait** (active
CPU only). Surface this as a TCO advantage — WITHOUT adding a question — when it actually
matters: if `traffic_pattern` is `bursty` or `idle`, OR `session_state` is `hitl`, AND AgentCore
is viable (winning runtime is `agentcore`, or it is in a `co_recommend` set, or it was not
eliminated). Set `io_wait_tco_note = true` in design.json and include a short note for the doc,
e.g.: "Your traffic is spiky / has human-in-the-loop waits — on AgentCore you pay nothing while
the agent waits on the model or a human (active-CPU billing only), which is a real TCO edge vs
always-on compute. Exact numbers come from the migration/pricing plugins." No dollar figures
here. If AgentCore is not viable, omit the note. **The note applies to the microVMs compute
type only** — when `agentcore_compute_type` is `instances`, billing is EC2 in the user's
account plus a management fee (an idle instance costs money unless the session is stopped),
so omit the $0-I/O-wait claim and let the scoring warning carry the pricing caveat instead.

## Step 4c — FedRAMP status (WIP, not a hard block)

If the user's `compliance` includes `fedramp`: AgentCore's FedRAMP authorization is **in progress
(WIP)** — do NOT hard-eliminate AgentCore for it. Verify the current status per `freshness.md`
(the `fedramp` volatile fact, via the AWS MCP Server). Then surface an honest note: "AgentCore's
FedRAMP authorization is in progress — verify the current status before committing. If you need
FedRAMP-authorized compute **today**, GovCloud on ECS/EKS is the safe fallback." Record
`fedramp_note = true` in design.json when this fires. (HIPAA/SOC/PCI/etc. are unaffected —
AgentCore is eligible for those.)

## Step 4d — Region gating (availability + CRIS/GDPR)

Read `region` from answers. Region does NOT change the verdict — it gates the following:

1. **Availability:** if the winning runtime is `agentcore` (or the chosen deployment model is
   Harness), verify it's available in the user's region via the AWS MCP Server (per
   `freshness.md`; the profile's `regions` volatile fact). If unavailable, surface a note with the
   nearest supported region and — if the gap is blocking — the container fallback. Do NOT silently
   recommend a runtime the user's region can't run. Record `region_availability_note` when it fires.
2. **Registry availability:** for each unit with `registry` in its confirmed `agentcore_services`,
   apply `freshness.md`'s AWS Agent Registry availability procedure independently of that unit's
   runtime, including ECS/EKS/Lambda. Check the intended Registry Region, not merely Runtime
   availability. Preserve the user's confirmed decision to omit Registry or use a supported
   Region in that unit's design rationale and mirror the primary unit at the top level. Record
   the intended Registry Region in each selected unit's rationale even when it matches the
   workload Region. If the user omits Registry, also update
   `confirm.json.units[unit_id].agentcore_services` (and the top-level primary mirror) so
   downstream POC generation cannot re-enable it from the earlier selection. An unavailable or
   unverified Registry must not appear as an available, ready-to-deploy service. Append its
   warning to existing `warnings` and `region_availability_note`; do not overwrite Runtime notes.
3. **CRIS / data residency:** if `region` is `multi`/`global` OR the user is in the EU OR
   `compliance` includes `gdpr`, surface the CRIS choice: **geo-CRIS keeps inference within the
   region (data-residency-safe)** vs **global-CRIS may route cross-region (a GDPR risk)**. Present
   it as a compliance decision, not a silent default. Record `cris_note = true`. Exact CRIS/region
   configuration is validated downstream in the migration flow — keep this directional.

## Step 4e — Temporal resolution (when temporal units exist)

When any unit has `workload_class == temporal_worker_poll`:

**Consume Confirm's decision — do NOT re-evaluate Tier 1.** Confirm already resolved every
temporal_worker_poll unit's runtime (including any user AskUserQuestion choice for Tier-1 rules 1
and 4) and persisted it in `confirm.json.resolved_runtimes[<unit_id>]`. Read that value as the
unit's verdict verbatim and cite the fired rule id it recorded in `rationale` (e.g.
"Tier1-R2: team operates K8s → EKS"). Re-running Tier 1 here — especially the OFFER rules — could
pick a different runtime than the one the user confirmed and make `platform_decision` disagree
with `effective_runtime`. Only if `resolved_runtimes` is somehow absent (older run) fall back to
loading `references/decision-refs/temporal.md` and applying the rules in order.

**Way resolution:** the Way comes FIRST from the user's answer
`answers.json.system.temporal_way` (cloud/self_hosted are binding); the Way table in
`references/decision-refs/temporal.md` applies ONLY when it is `undecided`/absent.
Commercials selection deferred to Generate.

Write the `temporal` block when temporal units exist:

```json
{
  "way": "cloud | self_hosted",
  "server_current": "...",
  "per_queue_rules": { "<queue>": "<rule id>" },
  "serverless_workers_status": "Public Preview"
}
```

`temporal.server_current` is read from `context-signals.json.temporal.server` (discover's
output; "unknown" on the declared no-code path). `serverless_workers_status` is set from
this run's freshness check (see freshness.md) — currently `"Public Preview"` — and MUST
NOT be auto-upgraded to GA from a docs label alone.

### Freshness (temporal units only)

Load `references/decision-refs/freshness.md` and run its Temporal section.

Use the public Temporal documentation pages and AWS Marketplace page named there.
Follow its web lookup and cached-fallback procedure without an authentication pause.
Preserve each result's source and date in `design.json.volatile_facts` for the freshness footer.

Non-negotiable regardless of channel: **Serverless Workers is Public Preview, not GA**
— the docs label has moved before without a GA announcement (it read "Available" in
2026-07); do not trust it at face value, re-verify this run and label the output
Public Preview until GA evidence appears. Workflow Streams and External Payload
Storage are Preview. The anti-fabrication rule applies:
only claim web-verified for calls actually made and results
observed this run.

## Step 5 — Assemble design.json

Assemble per unit:

- `agent_session` units: verdict/deployment_model/agentcore_compute_type/services from that
  unit's scoring result + that unit's confirm overrides (compute type is copied verbatim,
  never re-derived — scoring owns the >8h / GPU / instance-type routing); model/path from
  `model-recommendation.json.workloads[<unit_id>]` + the accepted
  `confirm.json.units[<unit_id>].model_decision` — read `confirm.json.units[<unit_id>]`
  (deployment_model, agentcore_services, chosen_runtime, tool_choices) for THIS unit, not a
  global top-level value. For a single-unit run, fall back to confirm.json's top-level fields.
  Each agent unit's confirmed runtime/services are independent — never copy the primary unit's.
  Write the compatibility `model_recommendation` object as
  `{"model": primary_model, "model_identity": ..., "reasoning": rationale joined for display,
  "api_path": api_path, "invocation_model_id": ..., "source": ..., "source_analysis": ...,
  "feature_assessment": ..., "alternatives": ..., "compatibility": ...,
  "architecture_impacts": ..., "additional_targets": ... (copy verbatim when the recommendation
  has them; a separate-modality target with status unresolved must NOT be turned into a runnable
  model id), "blocks": ..., "tuning": ..., "migration_deltas": ...,
  "evaluation": ..., "rollout": ..., "verification": ..., "live_verification": ... | null}`.
  This preserves current report consumers while carrying the complete advisor contract.
  `verification` is the catalog/probe requirement from the recommendation;
  `live_verification` is only populated from the separate probe artifact. Never read the
  scoring result's deprecated coarse model mirror for this field.
  **Every non-agent unit's runtime comes from `confirm.json.resolved_runtimes[<id>]` VERBATIM** —
  Confirm already resolved and (for Temporal rules 1/4) user-confirmed each one, so Design must NOT
  re-run temporal.md Tier 1 or workload-classes.md and risk a different pick than the one behind
  `platform_decision`. The rule references below only say WHICH rule produced that value (for the
  `rationale` cite) and are the fallback when `resolved_runtimes` is absent (older run).

- `temporal_worker_poll` units: verdict = `resolved_runtimes[<id>]` (Confirm's Tier-1 pick; cite
  the rule id it recorded in `rationale`, e.g. "Tier1-R5: default → ECS Fargate"). Fallback only:
  `references/decision-refs/temporal.md` Tier 1. `deployment_model` and `agentcore_services` are
  null; `model_recommendation` is null.
- other units: verdict = `resolved_runtimes[<id>]` (Confirm's workload-classes pick). It MUST be
  the exact runtime enum the fired rule maps to (W1 → `eks` or `ecs`; W2 → `batch`;
  W3 → `lambda`; W4 → `lambda`; W5 → `fargate`; W6 → `fargate`), NOT the prose label. Cite the
  rule id in `rationale` (e.g. "W2: batch → AWS Batch"). Fallback only:
  `references/decision-refs/workload-classes.md`.
  `deployment_model` and `agentcore_services` are null; `model_recommendation` only if
  the unit calls an LLM. The verdict and workload_class must be consistent: a `batch`
  workload_class NEVER has `ecs` verdict unless W1 (existing cluster reuse) fired.

**key_change derivation:** each unit gains a `"key_change"` field — one line extracted from
the winning runtime's "Serving & security notes" section. Derive it by reading the runtime
card's `## Serving & security notes` block and summarizing the entry contract + IAM posture.
Every runtime-card verdict has a card with this block: `agentcore.md`, `ecs.md`, `eks.md`,
`lambda.md`, `lambda-microvms.md`, `batch.md`, and `fargate` → `ecs.md` (ECS-on-Fargate shares
the ecs card). Never fabricate this line — read it from the resolved card.

**Model-less consumption rule (applies when reading ANY service card for a unit whose
`model_recommendation` is null — a non-agent SECONDARY unit in a mixed system):** the cards
describe the common model-bearing case, so their Bedrock-specific items (`bedrock:InvokeModel` in
the IAM posture, Bedrock Guardrails, "calls Bedrock directly", Bedrock egress) DO NOT apply — strip
them from that unit's `key_change` and IAM/networking summary, keeping only the service-specific
permissions (e.g. S3 for a batch job, ALB/networking for a service). Never emit `bedrock:InvokeModel`
or a Bedrock call for a model-less unit even though the card's prose lists it unconditionally. The
same rule governs Generate's use of the card. (A model-bearing unit reads the card as written.)

**`serverless_workers` has NO runtime card** (it is a temporal_worker_poll Tier-1 outcome, not a
scored runtime). Do NOT try to load `serverless_workers.md` in Step 2, and do NOT block on a
missing card. For a `serverless_workers` unit, derive `key_change` from
`references/decision-refs/temporal.md` (the Serverless Workers Tier-1 entry) + the Temporal
worker POC section of `poc-shapes.md` — one line on the worker's connection/env contract — and
label it Public Preview. (Same as the other temporal_worker_poll verdicts, whose cards are the
resolved compute card — ecs/eks — while serverless_workers is Temporal-managed with no AWS
compute card.)

- networking default in one sentence (e.g., "POST /invocations, execution role with InvokeModel,
  public endpoints over TLS"). This gives Generate a load-bearing sentence for the migration's
  operational shift.

**Consolidated does NOT rewrite per-unit `verdict`; it sets `effective_runtime` instead.**
Even when the user chose to consolidate onto a superset (e.g. ECS/EKS), each unit's `verdict`
stays the runtime its own rule produced (agent_session → its scored runtime; non-agent → its
workload-classes token — W2→`batch`, W3/W4→`lambda`, W5/W6→`fargate`). The consolidation lives
in the `platform` block (`mode: "consolidated"`, `runtime: "<superset>"`); it never overwrites
`units[].verdict`. The per-unit verdict records what each unit would run on its own (the report
shows the trade-off consolidation makes).

**Every unit ALSO gets an `effective_runtime` field — the ACTUAL deploy target — computed
here so every downstream phase reads ONE value instead of re-deriving it:**

- `platform.mode == "consolidated"` → `effective_runtime = platform.runtime` (the superset) for
  EVERY unit.
- `platform.mode == "split"` → `effective_runtime =` the unit's **resolved runtime**: when the
  unit's `verdict` is `co_recommend`, that is NOT a runtime — use the `chosen_runtime` the user
  picked in Confirm (`confirm.json.units[<id>].chosen_runtime`, or the top-level `chosen_runtime`
  for a single-unit run); otherwise the unit's `verdict`. `effective_runtime` is ALWAYS a
  concrete runtime enum (agentcore | lambda_microvms | ecs | eks | lambda | batch | fargate |
  serverless_workers) — never the literal `co_recommend`. (`serverless_workers` is a legal
  temporal_worker_poll Tier 1 outcome — Public Preview — and Estimate/POC dispatch on it; it
  MUST be in this enum or a user who accepts Public Preview Serverless Workers gets normalized
  to a wrong runtime.) Also set `units[].verdict` to that resolved runtime for a
  co_recommend unit (record the tie + the pick in `rationale`), so no downstream reader ever
  sees `verdict: "co_recommend"`.

Downstream phases (Estimate cost bands, Generate report + diagram, Migration Plan injection,
POC dispatch) MUST read `unit.effective_runtime` as the deploy/cost/render target, and use
`unit.verdict` only to show the "would-have-been" trade-off. A `content-review` unit with
`workload_class: light_io` under "consolidate onto ECS" therefore has `verdict: "lambda"`
(the `_assert` that verdict equals the workload-classes token still holds) AND
`effective_runtime: "ecs"` (where it actually deploys). In a split run the two are equal.

Each unit also carries its `coupling` object over from `context-signals.json.units[]` (verbatim
— `{ "mode": "queue|api|a2a|none" }`), **falling back to `answers.json.units[<id>].coupling`
when context-signals.json is absent** (a skipped-Discover run whose unit Clarify materialized —
that record carries `coupling`/`trigger`/`description`/`evidence`; use them). A materialized
single unit has `coupling.mode: "none"`. The diagram uses per-unit `coupling.mode` to wire ONLY
the units actually on the queue/gateway (an interconnect of `queue` means at least one queue
coupling exists, not that every unit is coupled), so an independent `none` unit is never linked.

Then the `platform` block: `mode` = `"consolidated" | "split"` from confirm.json's
`platform_decision`; `runtime` from the same; `interconnect` from the units' coupling
(`api`/`a2a` present → `gateway` and add `gateway` + `identity` to `shared_services`;
`queue` → `queue` (name the queue service from discovery evidence — the queue technology
the code uses — defaulting to Amazon SQS when none is detected, no Gateway); all `none`
→ `none`; single unit → `in_process`).
When couplings mix, precedence is gateway (any `api`/`a2a`) > `queue` > `none` — one
interconnect value describes the system.

**Legacy mirror (collapse + compatibility):** the primary unit (identified by
`answers.json.primary_unit`, chosen in Clarify) has its verdict, chosen_runtime,
deployment_model, agentcore_services, and model_recommendation ALSO written at design.json's top
level, exactly as today. The top-level `chosen_runtime` is the primary unit's RESOLVED runtime:
`confirm.json.resolved_runtimes[primary_unit]` (== the co_recommend pick when the primary's
verdict was co_recommend, else its plain verdict). It is always set — for a single-winner verdict
it equals the verdict, so it is never missing. (The primary is always an agent unit per Clarify's
scope gate.) Single-unit
runs therefore produce today's design.json plus a one-element `units` array.

Carry the scoring facts forward so Generate has a deterministic source for "Alternatives
considered" and the "Eliminated" line (Generate reads design.json, not scoring-result.json):

```json
{
  "units": [
    {
      "id": "...",
      "workload_class": "...",
      "verdict": "...",
      "effective_runtime": "... (= verdict when split; = platform.runtime when consolidated)",
      "coupling": { "mode": "queue | api | a2a | none (carried over from context-signals.json.units[])" },
      "deployment_model": "...",
      "agentcore_compute_type": "microvms | instances | null (verbatim from this unit's scoring result; instances = capacity-provider EC2 — >8h/GPU/heavy/instance-type workloads)",
      "agentcore_services": [...],
      "model_recommendation": {...},
      "rationale": "...",
      "key_change": "..."
    }
  ],
  "platform": {
    "mode": "consolidated | split",
    "runtime": "ecs | eks | lambda | lambda_microvms | agentcore | null (the consolidation superset = the runtime satisfying every unit's hard constraints with the highest summed score, null when split; in practice usually ECS/EKS, but any qualifying runtime is legal — Lambda/Lambda MicroVMs for an all-agent system that fits them, AgentCore only when every unit is agent_session)",
    "interconnect": "in_process | gateway | queue | none",
    "shared_services": [...]
  },
  "verdict": "...", "chosen_runtime": "...", "deployment_model": "...",
  "agentcore_compute_type": "microvms | instances | null",
  "agentcore_services": [...], "model_recommendation": {...}, "warnings": [...],
  "scores": {...}, "eliminated": {...}, "blocking_constraints": [...],
  "volatile_facts": {"microvms_session_cap": {"value": "8h", "source": "mcp|cached"},
                     "instances_session_cap": {"value": "14d", "source": "mcp|cached"}},
  "managed_alternative": "claude_managed | bedrock_managed | none",
  "io_wait_tco_note": true|false,
  "fedramp_note": true|false,
  "region_availability_note": "... | null",
  "cris_note": true|false,
  "handoff_required": true|false
}
```

Copy `scores`, `eliminated`, and (if present) `blocking_constraints` verbatim from
scoring-result.json. Set `handoff_required` = true when **ANY unit's `effective_runtime` needs a
downstream compute handoff — i.e. is one of `ecs`, `eks`, `fargate`, or `batch`** — not just the
primary unit's winning runtime. These runtimes hand the compute layer to the source-platform migration skill — `gcp-to-aws` or `heroku-to-aws` (their
service cards say so: ecs.md, eks.md, batch.md, and fargate = ECS). AgentCore, standard Lambda,
and Lambda MicroVMs are self-contained. So a system whose primary unit is AgentCore but which has
a secondary Fargate/Batch/ECS/EKS unit — OR which consolidated onto ECS/EKS — still needs the
handoff. Scan every `units[].effective_runtime`; if any is in {ecs, eks, fargate, batch},
`handoff_required` = true; a system with none of its units on those has `handoff_required` =
false. (For migrate, Generate ends with the migration-plan gate — the user chooses between an
in-skill migration plan and the classic downstream handoff; that's an entry-point behavior
in Step 6, independent of `handoff_required`.)

## Step 6 — Branch on entry point

- entry_point == migrate → set `phases.design` = completed and continue to **Estimate**, then
  Generate. The user gets the same recommendation doc + architecture diagram
  as Build paths; Generate then offers the migration-plan gate (Gate 1) at the end — in-skill plan or classic
  handoff. Estimate runs on migrate too — it produces the target-state run cost per unit; the
  migration TCO comparison stays with the Migration Plan engine.
- otherwise → set `phases.design` = completed and continue to Estimate.

## Maturity/readiness and provisional-verification extension

Load `references/decision-refs/maturity-readiness.md` with the design inputs. Copy `target_maturity`, `readiness`, `recommendation_status`, and `deferred_verification_requirements` from the run artifacts into `design.json`, preserving the release and evaluation gates applicable to the tier. A `provisional` recommendation is not a launch approval: state the unresolved constraint, verification key, owner, and blocking decision explicitly.

This supersedes the unconditional statement in Step 4b: include an AgentCore I/O-wait billing advantage only if the sibling `$RUN_DIR/current-run-verifications.json` artifact is schema-valid, its `run_id` matches `$RUN_DIR`, and its `agentcore.io_wait_billing` record has `status: "verified"` with a source-backed observed value from this run. Never read or write verification evidence through `answers.json`. Without validated current-run evidence, say only that the billing behavior requires current verification and do not make a comparative billing claim.
