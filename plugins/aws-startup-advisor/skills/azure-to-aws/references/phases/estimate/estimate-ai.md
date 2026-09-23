---
_fragment: ai
_of_phase: estimate
_contributes:
  - estimation-ai.json
---

# Estimate — AI Workload Cost Engine

> Loaded when ai-workload-profile.json exists. Contributes estimation-ai.json (the assembler is its creator; see estimate.md). Execute ALL steps in order.
>
> **Fragment unit.** This fragment _contributes_ to `estimation-ai.json`; the artifact
> itself is declared on the assembler's `_produces` and written there — the same
> design-ai / aws-design-ai split, one layer over. `estimate-infra.md` prices the estate's
> compute/database/storage/network; this file prices AI token spend and nothing else.

**Execute ALL parts in order. Do not skip or optimize.**

---

## Pricing Mode

The parent `estimate.md` selects the pricing mode before loading this file.

**Price lookup order:**

1. **`shared/pricing-cache.md` (primary)** — Look up Bedrock model pricing and source
   provider pricing by table. Set `pricing_source: "cached"`.
2. **Unavailable** — If a model is NOT in the cache, consult `shared/pricing-fallback.md`,
   set `pricing_source: "unavailable"`, emit `null` for the affected per-token fields, and warn
   the user. Never fabricate a token price. An `_unverified_` cache cell is blocking — do not
   use it as if it were a confirmed price. There is no live pricing lookup to top the cache up.

For typical migrations (Claude, Llama, Nova, Mistral, DeepSeek, Gemma, OpenAI gpt-oss, and the
proprietary GPT-5.x source rows), ALL prices are in `pricing-cache.md`.

**Staleness:** if `pricing-cache.md` is more than 30 days past its **Last updated** date, treat
AI prices as potentially stale, set `pricing_source: "cached_stale"`, and note it — per that
file's staleness warning.

**Bedrock pricing is per-1M-tokens.** Every generative Bedrock figure in `pricing-cache.md` is
stated per 1M input tokens and per 1M output tokens. Divide token counts by 1,000,000 before
multiplying by the rate. **Embedding models are input-only** — the § Embeddings — Bedrock table
gives a single per-1M-input rate and no output column; price an embedding workload as
input_tokens × rate (no output term), and compare against the § Embeddings — OpenAI / Azure OpenAI
source rate for the "$X today" baseline. A source `text-embedding-3-*` → Titan v2 move is a
re-embedding task (dimension change), not a free swap — carry the note into the estimate. There is no per-hour or baked-in-Multi-AZ dimension here — that RDS-style rule belongs
to `estimate-infra.md` and does NOT apply to token pricing.

**Model lifecycle:** When building the model comparison table, check
`references/vendored/ai/ai-model-lifecycle.md` and apply the 90-day exclusion rule:

- **Excluded** (≤90 days to EOL): omit entirely from `model_comparison`, `recommended_model`,
  and `backup_model`.
- **Legacy** (>90 days to EOL): include in `model_comparison` with `(Legacy — EOL YYYY-MM-DD)`
  annotation. Do not select as `recommended_model` unless no Active alternative exists.
- **Active**: no restrictions.

## Prerequisites

Read from `$MIGRATION_DIR/`:

- **`ai-workload-profile.json`** — `current_costs.monthly_ai_spend`,
  `current_costs.services_detected`, `models[]`, `metadata.profile_source`,
  `summary.inferred_from_iac`, `integration.pattern`.
- **`openai-usage-profile.json`** (if present) — `summary.monthly_cost_usd`,
  `usage_by_model[]` (real per-model input/output token counts from the OpenAI / Azure OpenAI
  usage API). Check `metadata.capture_warnings` first: a failed usage endpoint means that
  category's volume is UNKNOWN, not zero — say so in the output and do not price the affected
  capability from this profile.
- **`preferences.json`** — `ai_constraints.ai_token_volume.value`,
  `ai_constraints.ai_capabilities_required.value`.
- **`aws-design-ai.json`** — `metadata.ai_source`, `ai_architecture.honest_assessment`,
  `ai_architecture.tiered_strategy`, `ai_architecture.bedrock_models[]` (with
  `source_provider_price`, `bedrock_price`, `honest_assessment`, `model_change`),
  `ai_architecture.capability_mapping`, and `design_blocks[]`.

**Traditional-AI workloads (excluded from token cost):** `design_blocks[]` entries with
`target_aws_service` set (capability `document_extraction`, `image_analysis`, or
`speech_transcription` → Textract, Rekognition, Transcribe) are per-page / per-image / per-minute
priced, not token priced, and this phase's cost model does not cover them yet. Skip these blocks
in Parts 1–3; list them in the output under `services_not_estimated[]`
(`{workload_id, target_aws_service, reason: "not_token_priced"}`) so the user knows they are
excluded rather than assumed free.

---

## Part 1: Establish Current AI Costs

Determine current AI spending from the best available source. **Four-level precedence, first
match wins:**

1. **`current_costs.monthly_ai_spend` (preferred whenever present)** — from
   `ai-workload-profile.json`. This figure is already provider-aware: Discover merges billing
   (an **Azure Cost Management export**) and OpenAI / Azure OpenAI usage-API spend there, summing
   across providers with `source: "mixed"` and a per-provider `breakdown[]`. Do NOT bypass it by
   reading `openai-usage-profile.json → summary.monthly_cost_usd` directly — that drops the
   non-OpenAI half of a mixed workload. When `breakdown[]` exists, carry the per-provider split
   into the comparison output. **Partial-window check:** if `source` is `openai_usage_api` or
   `mixed` AND `openai-usage-profile.json → metadata.partial_window` is `true`, the OpenAI
   portion is not a monthly baseline — apply level 2's exception to that portion (reference figure
   only, labeled with `active_days`; for `mixed`, keep the Azure portion from `breakdown[]` and
   cover the OpenAI portion via levels 3–4).
2. **OpenAI usage profile dollars (fallback)** — use `summary.monthly_cost_usd` from
   `openai-usage-profile.json` ONLY when no `current_costs` exists (standalone usage capture with
   no AI workload profile). **Exception:** if `metadata.partial_window` is `true`, the window is
   too short to be a monthly baseline — do NOT rank it above levels 3–4; fall back and present the
   partial actuals as a reference figure only, labeled with `active_days`.
3. **Estimated from token volume** — use `ai_constraints.ai_token_volume.value` from
   `preferences.json` with **OpenAI / Azure OpenAI source list prices** from `pricing-cache.md`
   (under "Source Provider Pricing → OpenAI / Azure OpenAI"). Azure OpenAI serves the same GPT
   models and reads those same OpenAI rows — there is no separate Azure-OpenAI table. Apply the
   60/40 input/output ratio if the actual ratio is unknown.
4. **None available / multi-tier** — note in output and present the model comparison at multiple
   volume tiers so the user can find their range.

Regardless of which dollar source wins, `openai-usage-profile.json → usage_by_model[]` remains
the Part 2 token-volume source (subject to the same `partial_window` exception there).

**IaC-only profile:** If `metadata.profile_source` is `iac_cognitive` or
`summary.inferred_from_iac` is true and billing/token data is missing, state explicitly that
**current Azure AI spend is unverified** and widen uncertainty bands (use the same multi-tier
comparison approach as in level 3).

---

## Part 2: Build Model Comparison Table

Calculate the monthly Bedrock cost for **every viable model** at the user's token volume.

**Token volume mapping** (from `ai_token_volume` in `preferences.json`):

| `ai_token_volume` | Input tokens/month | Output tokens/month | Ratio |
| ----------------- | ------------------ | ------------------- | ----- |
| `"low"`           | 6M                 | 4M                  | 60/40 |
| `"medium"`        | 60M                | 40M                 | 60/40 |
| `"high"`          | 600M               | 400M                | 60/40 |
| `"very_high"`     | 6B                 | 4B                  | 60/40 |

If the design or discover phase has more specific token estimates, use those instead. In
particular, when `openai-usage-profile.json` exists with `metadata.partial_window` `false`, use
its `usage_by_model[]` actual monthly input/output token totals (and actual ratio) instead of the
tier table — a real observed month beats a tier midpoint. **Exception:** if
`metadata.partial_window` is `true`, a few days of tokens is NOT a monthly volume — projecting it
as one understates the Bedrock estimate. Use the tier table (from `ai_token_volume`) and present
the partial actuals as a reference figure only, labeled with `active_days`.

**Cost formula:** `Monthly = (input_tokens / 1M × input_rate) + (output_tokens / 1M × output_rate)`

**Long-context surcharge:** If `ai_critical_feature = "ultra_long_context"` in `preferences.json`,
Claude models charge 2x the standard input rate for tokens beyond 200K context. Apply the
surcharge to the portion of input tokens that exceeds 200K per request. If per-request token
counts are unknown, assume 50% of input tokens fall in the long-context tier as a conservative
estimate.

**Comparison table columns:** Model, Bedrock Monthly, vs Source Provider ($ and %), vs Current
Azure, Quality, Capabilities Match (checked against `ai_capabilities_required`).

Include source provider pricing from `aws-design-ai.json` → `bedrock_models[].source_provider_price`.

If Bedrock is more expensive for the recommended model, flag prominently.

If embeddings are needed, add a separate line (additive to the primary model cost).

---

## Part 3: Recommended Model Cost Breakdown

Using the model selected in the design phase, show:

- Input tokens × rate, output tokens × rate, embeddings × rate (if applicable)
- Total monthly cost
- Comparison to current Azure spend (monthly and annual difference)
- Backup model cost for comparison

---

## Part 4: Human One-Time Migration Costs (Out of Scope)

**Do not** present human labor, contractors, professional services, or engineering effort as
one-time migration **costs** or budget line items (no dollar figures, no "budget for people work"
lists, no "one-time migration cost" categories for implementation).

Populate `migration_cost_considerations.categories` as an **empty array** `[]`. Use
`migration_cost_considerations.note` to state that human and professional-services one-time
migration costs are intentionally excluded from this advisor.

**Technical integration complexity** (for internal JSON and risk context only — not framed as
money): from `ai-workload-profile.json`, record non-monetary factors in
`migration_cost_considerations.complexity_factors[]` as short strings, for example:

- `integration.pattern = "framework"` → lower integration touch surface
- `integration.pattern = "direct_sdk"` → moderate SDK and API pattern changes
- `integration.pattern = "rest_api"` → higher endpoint, auth, and parsing changes
- `summary.total_models_detected` > 3 → multi-model coordination
- `quota_risk = "high"` (from `aws-design-ai.json`) → Bedrock quota increase required before
  migration; allow 1–5 business days (see `vendored/ai/bedrock-quotas.md`)

Do **not** repeat these as "costs" in the user-facing summary.

---

## Part 5: ROI Analysis

Present the monthly and annual cost difference between current Azure AI spend and projected
Bedrock cost:

- **If the model is unchanged** (`model_change: false`): projected cost is **about 10% higher**,
  not the same — Bedrock in-region is priced at OpenAI's data-residency tier, which is 1.10x
  OpenAI / Azure OpenAI standard. Quote the increase plainly and make the case on non-cost
  grounds. If any workload exceeds 272K context, price it at the long-context tier and show that
  separately; it can dominate the comparison.
- **If Bedrock is cheaper:** present monthly and annual savings clearly.
- **If Bedrock is more expensive:** state clearly, justify with non-cost benefits, or note "not
  justified if cost is the only priority".

Reference `aws-design-ai.json` → `honest_assessment`. If `"recommend_stay"`, present prominently
along with `honest_assessment_reason`.

**Non-cost benefits to present:** usage counting toward existing AWS commitments,
IAM/VPC/PrivateLink/KMS/CloudTrail governance, in-region processing for data residency, prompt
caching (Claude, and GPT-5.6 at 90% off cached input with cached tokens exempt from the input-TPM
quota), model flexibility (100+ models), AWS ecosystem (Guardrails, Knowledge Bases, AgentCore),
and — for a same-model move — the elimination of behavior-delta and prompt-regression risk.

**Pricing source caveat for OpenAI models:** the AWS Price List API does not carry the
proprietary GPT-5.x models. A missing or empty price-list result is **not** evidence the model is
unavailable or free. Use `shared/pricing-cache.md`, and treat rows
marked `unverified` there as blocking for any quoted figure — resolve them from the Bedrock
pricing page first. See `shared/openai-on-bedrock.md`.

**Note:** Human / professional-services one-time migration costs are intentionally out of scope
for this advisor and excluded from ROI calculations.

---

## Part 6: Cost Optimization Opportunities

Present applicable optimizations with estimated savings:

| Optimization               | Savings | Applies When                                        |
| -------------------------- | ------- | --------------------------------------------------- |
| Model downsizing / tiering | 60-87%  | High volume, premium model selected                 |
| Prompt caching (Claude)    | ~30%    | Repeated system prompts                             |
| Batch API                  | 50%     | Non-real-time workloads (`ai_latency = "flexible"`) |
| Provisioned throughput     | Varies  | Token volume > 100M/month, predictable traffic      |
| Input token reduction      | 10-30%  | Prompt optimization, shorter context                |
| Multi-model tiered routing | 60-87%  | High/very-high volume, `tiered_strategy` in design  |

For each applicable optimization, calculate before/after monthly cost and show an
`optimized_projection` (best-case monthly with all optimizations).

**Post-migration optimization (do not surface during migration):** Model distillation — training
a smaller, faster student model from a larger teacher model — can reduce inference costs up to
~75% for high-volume, stable workloads. Requires production traffic, labeled examples, and a
teacher/student eval loop. Mention in the estimate summary as: "Once you have 2–4 weeks of
Bedrock production traffic, consider model distillation to further reduce costs. See
docs.aws.amazon.com/bedrock/latest/userguide/model-distillation.html." Do not recommend
distillation before the startup has migrated and validated their workload.

---

## Part 7: Migration Recommendation (REQUIRED)

Produce a clear migrate/stay/optimize verdict for the AI workload migration. This is the AI-only
equivalent of `estimate-infra.md` Part 8.

**Decision logic:**

| Condition                                                                                                                         | Verdict             | `recommendation.path` |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------- | --------------------- |
| **Same model on Bedrock** (`model_change: false`) — ~10% higher, short-context; non-cost benefits carry it                        | Migrate with caveat | `migrate_optimized`   |
| Bedrock cheaper AND capabilities match                                                                                            | Migrate             | `migrate_optimized`   |
| Bedrock more expensive BUT non-cost benefits justify (vendor diversification, Guardrails, multi-model) AND user priority ≠ `cost` | Migrate with caveat | `migrate_optimized`   |
| Bedrock more expensive AND user priority = `cost` AND no compelling non-cost reason                                               | Stay                | `stay`                |
| Design `honest_assessment` = `recommend_stay`                                                                                     | Stay                | `stay`                |
| Mixed (some workloads cheaper, some not)                                                                                          | Migrate selectively | `migrate_phased`      |

**Output fields** (add to `estimation-ai.json` top-level):

```json
"recommendation": {
  "path": "migrate_optimized | migrate_phased | stay",
  "path_label": "Migrate to Bedrock | Migrate selectively | Stay on current provider",
  "migrate_if": "Brief condition under which migration makes sense (1 sentence)",
  "stay_if": "Brief condition under which staying makes sense (1 sentence)",
  "confidence": "high | medium | low",
  "rationale": "2-3 sentence justification citing cost delta and non-cost factors"
}
```

**Rules:**

- MUST emit `recommendation` — never omit. If data is insufficient, set `confidence: "low"` and
  state why in `rationale`.
- If `honest_assessment` from `aws-design-ai.json` says `recommend_stay`, `recommendation.path`
  MUST be `stay` regardless of cost numbers.
- **A same-model move is a modest cost increase, not parity.** When
  `bedrock_models[].model_change` is `false`, Bedrock in-region costs ~10% more than OpenAI /
  Azure OpenAI standard for the same model. Report that figure rather than "no savings
  identified", and argue the case on commitments, governance, residency, prompt caching, and
  eliminated behavior-delta risk. A ~10% increase alone should not route to `stay` unless
  `ai_priority = cost` and no non-cost driver applies; a long-context workload at the 1M tier is a
  different matter and may legitimately favour staying.
- For multi-workload runs: if some workloads favor migration and others don't, use
  `migrate_phased` and list which workloads to migrate vs. keep in `rationale`.

---

## Output

The assembler writes `estimation-ai.json` to `$MIGRATION_DIR/`; this fragment contributes its
fields.

**Schema — top-level fields:**

| Field                           | Type   | Description                                                                                                                     |
| ------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `phase`                         | string | `"estimate"`                                                                                                                    |
| `timestamp`                     | string | ISO 8601                                                                                                                        |
| `pricing_source`                | string | `"cached"`, `"live"`, `"cached_fallback"`, `"cached_stale"`, or `"unavailable"`                                                 |
| `accuracy_confidence`           | string | `"±5-10%"` or `"±15-25%"`                                                                                                       |
| `current_costs`                 | object | `source`, `azure_monthly_ai_spend`, `services[]`                                                                                |
| `token_volume`                  | object | `source`, `monthly_input_tokens`, `monthly_output_tokens`, `ratio`                                                              |
| `model_comparison`              | array  | All viable models: `model`, `monthly_cost`, `vs_current`, `quality`, `capabilities_match`, `missing_capabilities[]`             |
| `recommended_model`             | object | `model`, `monthly_cost`, `breakdown` (input/output/embeddings), `rationale`                                                     |
| `backup_model`                  | object | `model`, `monthly_cost`, `rationale`                                                                                            |
| `embeddings`                    | object | `model`, `monthly_cost`, `monthly_tokens`, `note` (if applicable)                                                               |
| `cost_comparison`               | object | `current_azure_monthly`, `projected_bedrock_monthly`, `monthly_difference`, `annual_difference`, `percent_change`               |
| `migration_cost_considerations` | object | `categories[]` (always `[]`), `complexity_factors[]` (technical integration only), `note` (must state human/pro costs excluded) |
| `roi_analysis`                  | object | `monthly_cost_delta`, `annual_cost_delta`, `justification`, `non_cost_benefits[]`                                               |
| `optimization_opportunities`    | array  | `opportunity`, `potential_savings_monthly`, `implementation_effort`, `description`                                              |
| `optimized_projection`          | object | `monthly_with_optimizations`, `vs_current`, `note`                                                                              |
| `recommendation`                | object | `path`, `path_label`, `migrate_if`, `stay_if`, `confidence`, `rationale` (see Part 7)                                           |
| `services_not_estimated`        | array  | Traditional-AI workloads excluded from token cost: `{workload_id, target_aws_service, reason: "not_token_priced"}`              |

`current_costs.azure_monthly_ai_spend` (NOT `gcp_monthly_ai_spend`) and
`cost_comparison.current_azure_monthly` (NOT `current_gcp_monthly`) are the Azure field names.
**All cost values are numbers, not strings.** Output must be valid JSON.

## Validation Checklist

- [ ] `recommendation` field is present with non-empty `path`, `path_label`, `migrate_if`,
      `stay_if`, and `rationale`
- [ ] `recommendation.path` is one of: `migrate_optimized`, `migrate_phased`, `stay`
- [ ] If Design `honest_assessment` = `recommend_stay`, then `recommendation.path` = `stay`
- [ ] `model_comparison` includes ALL viable Bedrock models, not just recommended
- [ ] Legacy models in `model_comparison` are annotated with EOL dates (per
      `vendored/ai/ai-model-lifecycle.md`)
- [ ] `recommended_model` is an Active model (not Legacy) unless no Active alternative exists
- [ ] Every model has `capabilities_match` checked against `ai_capabilities_required`
- [ ] `recommended_model.rationale` references the user's priority, preference, and volume
- [ ] `roi_analysis` is honest — if migration increases cost, says so
- [ ] `optimization_opportunities` only includes strategies relevant to the user's workload
- [ ] No compute, database, storage, or networking costs (those belong in `estimate-infra.md`)
- [ ] `migration_cost_considerations.categories` is `[]` — no human one-time migration costs
- [ ] `services_not_estimated[]` lists every traditional-AI workload (Textract/Rekognition/
      Transcribe) with `reason: "not_token_priced"`
- [ ] All cost values are numbers, not strings

## Completion Handoff Gate (Fail Closed)

Before returning control to `estimate.md`, require:

- `estimation-ai.json` exists and passes the Validation Checklist above.

If this gate fails: STOP and output: "estimate-ai did not produce a valid `estimation-ai.json`;
do not complete Phase 4."

> **Note:** `_assert` has no teeth here — a passing `_assert` only confirms the file parses, not
> that it is correct. The Completion Handoff Gate above is judged by the oracle, not by
> `_assert`; treat the checklist, not schema-parseability, as the bar.

## Present Summary

After the assembler writes `estimation-ai.json`, present under 25 lines:

1. **Pricing source and accuracy:** State whether prices came from cache or live API, and the
   accuracy range (±15-25% for AI models from cache, ±5-10% from live API). Example: "AI model
   estimates based on cached pricing (2026-08-24), accuracy ±15-25%."
2. Current Azure AI spend vs estimated monthly Bedrock cost (recommended model)
3. Model comparison table: model name, estimated monthly cost, vs source provider %, capabilities
   match
4. Recommended model with estimated monthly cost breakdown
5. If migration increases cost: flag honestly with non-cost justification
6. Top 2-3 optimization opportunities with potential estimated monthly savings
7. Optimized projection

**Cost labeling rule:** All dollar figures presented to the user MUST be labeled as "estimated
monthly costs" or prefixed with "Est." — never present raw dollar amounts as if they are exact.

## Generate Phase Integration

The Generate phase uses `estimation-ai.json`:

1. **`recommended_model`** — Which Bedrock model to provision and test
2. **`migration_cost_considerations`** — `complexity_factors[]` only for integration risk
   context; **never** present human one-time migration **costs** to the user (`categories` stays
   `[]`)
3. **`optimization_opportunities`** — Which optimizations to implement and when
4. **`cost_comparison`** — Cost monitoring targets and alerts in production
5. **`model_comparison`** — Fallback options if the recommended model doesn't meet the quality bar

## Scope Boundary

**This phase covers financial analysis ONLY for AI workloads.**

FORBIDDEN — Do NOT include compute, database, storage, networking cost calculations,
infrastructure provisioning, code migration examples, or detailed migration timelines.

## Status — build step 3 (AI route)

Written alongside the other estimate AI consumers. Reads the `aws-design-ai.json` contract
(`shared/schema-design-aws-ai.md`, build step 2) and contributes `estimation-ai.json`, which the
Generate phase's AI route (`generation-ai.json`) consumes in the next step.
