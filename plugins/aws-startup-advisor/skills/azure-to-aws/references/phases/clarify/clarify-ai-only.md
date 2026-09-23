# AI-Only Migration — Clarify Requirements

**Standalone flow** — used when ONLY `ai-workload-profile.json` exists (no
`azure-resource-inventory.json`, no billing artifacts), i.e. an app-code-only run.
Infrastructure stays on Azure; only AI/LLM calls move to AWS Bedrock. Routed here by
`clarify.md` Step 0 (Migration Type Detection) — it is NOT a `_fragments` entry; `clarify.md`
reads this file directly and follows it to completion, skipping the normal infra flow.

Produces the same `preferences.json` but with `design_constraints` limited to region and
compliance, `startup_constraints` populated, and `ai_constraints` fully populated. Two
progressive batches with an intermediate save. The Azure port of gcp's `clarify-ai-only.md`:
the cross-cloud framing and question mechanics port unchanged; the model catalog and provider
wording are Azure-swapped (Azure OpenAI, no Gemini).

## Step 0: Prior-run check

- **`preferences.json` present** → offer reuse vs start-fresh; on reuse skip to Step 3.
- **`preferences-draft.json` present** (Batch 1 done) → offer resume vs start-fresh; on resume
  load the draft, skip Batch 1, present Batch 2.
- **No prior state** → Step 1.

## Step 1: Present the AI-only detection summary

> **AI-only migration detected.** Your project has AI workloads but no infrastructure artifacts
> (no Terraform/Bicep/ARM). I'll migrate your AI/LLM calls to AWS Bedrock while your
> infrastructure stays on Azure.
>
> **AI source:** [`summary.ai_source`] · **Models:** [`models[].model_id`] ·
> **Capabilities:** [`integration.capabilities_summary` where true] ·
> **Integration:** [`integration.pattern`] via [`integration.primary_sdk`] ·
> **Gateway/router:** [`integration.gateway_type`, or "None (direct SDK)"]

## Step 1.5: Fast-path check

If the AI usage looks simple (single model, non-agentic, no multi-provider/multi-model routing):
present ONLY Q1.5, Q2, Q3, Q4, Q11 (Q1 framework, Q5 model, Q6 capabilities are extracted;
Q7–Q10 default). **Q1.5 (compliance) and Q11 (Activate) are never dropped** — always PRESENTED,
never silently omitted. "Use defaults for the rest" applies documented defaults (compliance →
`["unknown"]` + a `metadata.report_caveats[]` entry, never a silent "none"; Activate → `unknown`).
Then skip to Step 3. Otherwise continue to Step 1.75 → Step 2.

## Step 1.75: Mini assumption sheet

Before asking anything, present a compact confirm-or-edit sheet: what discovery already answered
(framework, primary model, input types — from the profile) and what will be assumed (usage
volume Low, response speed Important, task complexity Moderate) with each assumption's
consequence. Rows resolved here are not re-asked; record `chosen_by: "extracted"` (detected) or
`"default"` (assumed, sheet-confirmed); corrected rows become `chosen_by: "user"`.

## Step 2: Questions in two batches

The user can answer, skip individual questions (defaults applied), or say "use defaults for the
rest" to apply defaults for all remaining and proceed.

### Batch 1 — AI strategy & setup (Q1–Q5 + Q1.5)

**Q1 — AI framework / orchestration** (select all). Auto-detect from `integration.pattern` /
`gateway_type` / `frameworks`; skip when definitive (a `direct_sdk` + empty frameworks + null
gateway → `["direct"]`). → `ai_framework`. Default `["direct"]`.

**Q1.5 — Compliance / regulatory requirements** (select all; **never dropped**). Compliance gates
Bedrock regions/models/logging **even though infrastructure stays on Azure** — prompts and
completions are processed on AWS the moment model calls move. Options None / SOC2-ISO27001 /
PCI DSS / HIPAA / FedRAMP / GDPR / CCPA / "don't know". Impacts: HIPAA → BAA-eligible models,
KMS-encrypted logs, us-east-1/us-west-2; FedRAMP → GovCloud (smaller catalog); GDPR → EU regions
with geographic `eu.` inference profiles (`global.` forbidden), document the Azure-EU → AWS-EU
transfer; PCI/SOC2/CCPA → CloudTrail + scoped IAM + retention. → `design_constraints.compliance`.
Explicit "None" → `["none"]` `chosen_by: user`. Skip/default → `["unknown"]` `chosen_by: default`

- append "Compliance requirements were not confirmed by the user" to `metadata.report_caveats[]`.

**Q2 — What matters most?** Quality (Sonnet/Opus) / Speed (Haiku, Nova) / Cost (Haiku, Nova
Micro) / Special (→Q10) / Balanced (Sonnet). → `ai_priority`. Default `"balanced"`.

**Q3 — Monthly AI spend on Azure OpenAI / OpenAI?** `<$500` / `$500-$2K` / `$2K-$10K` / `>$10K` /
don't know. → `ai_monthly_spend`. Default `"$500-$2K"`.

**Q4 — Cross-cloud API call concerns** (unique to AI-only — infra stays on Azure while AI calls
route to AWS): Latency critical (VPC endpoint, closest region) / Acceptable (standard endpoint,
region by cost) / Egress-concerned (PrivateLink, egress analysis) / Test-first (phased parallel
running). → `ai_constraints.cross_cloud`. Default `"latency-acceptable"`.

**Q5 — Current model in use?** Establishes the baseline Bedrock recommendation. Skip when
`models[].model_id` is populated with confidence ≥ 0.8 (`chosen_by: extracted`). **Azure catalog**
(Azure OpenAI deployments — no Gemini):

| Source (Azure OpenAI / OpenAI deployment) | Baseline recommendation                | Pricing context                            |
| ----------------------------------------- | -------------------------------------- | ------------------------------------------ |
| GPT-5.6 (Sol/Terra/Luna)                  | **Same model on Bedrock**              | ~10% over OpenAI std (data-residency tier) |
| GPT-5.5                                   | **Same model on Bedrock**              | ~10% over std                              |
| GPT-5.4                                   | **Same model on Bedrock**              | ~10% over std                              |
| GPT-4o                                    | GPT-5.6 Terra; or Claude Sonnet 5      | not on Bedrock — offer both                |
| GPT-4 / 4 Turbo                           | GPT-5.6 Terra; or Sonnet 5             | not on Bedrock — offer both                |
| GPT-4.1 / mini / nano                     | GPT-5.6 Terra/Luna; or Nova Lite/Micro | not on Bedrock — offer both                |
| GPT-3.5 Turbo                             | GPT-5.6 Luna; or Haiku 4.5             | Luna cheaper                               |
| o-series (o3/o4-mini)                     | GPT-5.6 Sol/Terra; or Sonnet 5         | not on Bedrock — offer both                |
| Claude (Anthropic SDK)                    | Same model on Bedrock                  | client swap only — no model change         |
| Other / multiple / don't know             | ask / infer                            | —                                          |

**Same-model rows first.** GPT-5.6/5.5/5.4 run on Bedrock via `bedrock-mantle` (Responses,
in-region only) — the case is AWS commitments/governance/residency, not savings, and not parity
(~10% above OpenAI standard). For sources with no Bedrock equivalent, present a same-vendor
upgrade AND a cross-family option. → `ai_model_baseline`.

**After Batch 1:** interpret answers, write `preferences-draft.json` (`metadata.draft: true`,
`migration_type: "ai-only"`, `batches_completed: ["ai-strategy"]`), then present Batch 2. On "use
defaults for the rest" during Batch 1, skip the draft save (assembly happens same turn).

### Batch 2 — Technical requirements (Q6–Q11)

**Q6 — Input types** (text / vision / audio-video). Skip when `capabilities_summary` is
definitive. → `ai_vision`. **Q7 — Monthly usage volume.** Auto-resolve from
`openai-usage-profile.json` when present (tiers `<1M`→low, `1–10M`→medium, `10–100M`→high,
`>100M`→very_high). → `ai_token_volume`. Default `"medium"`. **Q8 — Response speed** (critical /
important / flexible). → `ai_latency`. Default `"important"`. **Q9 — Task complexity** (simple /
moderate / complex). → `ai_complexity`. Default `"moderate"`. **Q10 — Specialized features**
(function calling / ultra-long-context / extended-thinking / prompt-caching / RAG / agentic /
real-time / image-gen / speech). → `ai_critical_feature`. Default none.

**Q11 — AWS Activate credits** (**never dropped**; ≡ full-flow Q27). Never infer funding stage
from Q3 spend. Options: have credits / self-funded (→ Activate Founders up to $5K) /
VC-backed (→ Activate Portfolio up to $200K, needs Org ID) / don't know. Escalations: `>$10K`→
AWS Credits for AI Startups; $2K-$10K plus AND agentic → Generative AI Accelerator (up to $1M).
→`startup_program_status`. Default`"unknown"` (neutral copy, both tiers).

## Step 3: Assemble and write preferences.json

Merge both batches (use `preferences-draft.json` as base if present; strip draft metadata).
Write `$MIGRATION_DIR/preferences.json`:

- `metadata.migration_type: "ai-only"` (downstream skips infra phases),
  `metadata.discovery_artifacts: ["ai-workload-profile.json"]`, `metadata.clarify_mode`
  (`"fast_path"` if Step 1.5 fired, else `"full"`), and the disjoint
  `questions_asked`/`questions_defaulted`/`questions_extracted` lists.
- `design_constraints`: `target_region` (derived — precedence: Q1.5 compliance > an Azure region
  captured in discovery > Q4 cross-cloud preference > fallback `us-east-1`; `chosen_by: "derived"`
  naming the rule) and `compliance` (from Q1.5). NO infra constraints.
- `startup_constraints.startup_program_status` (Q11).
- `ai_constraints`: `ai_framework`, `ai_priority`, `ai_monthly_spend`, `cross_cloud` (Q4 —
  unique to AI-only), `ai_model_baseline`, `ai_vision`, `ai_token_volume`, `ai_latency`,
  `ai_complexity`, `ai_critical_feature`, `ai_capabilities_required` (derived from
  `capabilities_summary`).
- Persist the confirmed `workloads[]` (top-level) exactly as `clarify-ai.md` specifies — each
  entry carries `workload_id`, `model_id`, `sdk_method`, `capability`, `capability_confidence`,
  `structured_output`, `call_sites`, `target_bedrock_model`, `priority`, `latency_tier`. This is
  the downstream source of truth (design-ai reads it, not the profile).

Each constraint carries the full clarify field shape (`value`, `chosen_by` ∈
`user|extracted|default|derived`, `prompt`, `design_consequence`, `source`/`question_id`). No
nulls. Delete `preferences-draft.json` after writing.

## Step 4: Output gate

- `preferences.json` exists and `metadata.migration_type == "ai-only"`.
- If either fails: STOP and output "AI-only clarify output validation failed. Fix preferences.json
  before completing Phase 2."

On pass, `clarify.md` handles the phase-status update and advances to `design`. `design-ai.md`
runs (it fires on `ai-workload-profile.json`), the infra design fragment no-ops (no inventory),
and the chain threads through estimate-ai → generate-artifacts-ai — the same artifact-presence
routing the mixed path uses.

> **`_assert` has no teeth.** This flow's gate is prose the model both produces and evaluates.
> Judge correctness by an AI-only fixture oracle and a fresh-context run, not by "it completed."

## Status — build step (app-code-only / AI-only route, plan §19.12)

Wired: `clarify.md` Step 0 routes here when the inventory is absent and `ai-workload-profile.json`
is present. This is the standalone AI-only Clarify flow that §19.9c deferred and §19.12 reversed
on owner instruction (gcp supports app-code-only; azure now does too).
