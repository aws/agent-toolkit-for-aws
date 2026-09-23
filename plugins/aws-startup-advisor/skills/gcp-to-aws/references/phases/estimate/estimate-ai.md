# Estimate Phase: AI Workload Cost Analysis

> Loaded by estimate.md when aws-design-ai.json exists.

**Execute ALL steps in order. Do not skip or optimize.**

## Pricing Mode

The parent `estimate.md` selects the pricing mode before loading this file.

**Price lookup order:**

1. **`shared/pricing-cache.md` (primary)** — Look up Bedrock model pricing and source provider pricing by table. Set `pricing_source: "cached"`.
2. **Unavailable** — If a model is NOT in the cache, set `pricing_source: "unavailable"` and warn the user. An `_unverified_` cache cell is blocking — do not use it as if it were a confirmed price.

For typical migrations (Claude, Llama, Nova, Mistral, DeepSeek, Gemma, OpenAI gpt-oss, Gemini source pricing), ALL prices are in `pricing-cache.md`. Zero MCP calls needed.

**Model lifecycle:** When building the model comparison table, check `references/vendored/ai/ai-model-lifecycle.md` and apply the 90-day exclusion rule:

- **Excluded** (≤90 days to EOL): omit entirely from `model_comparison`, `recommended_model`, and `backup_model`.
- **Legacy** (>90 days to EOL): include in `model_comparison` with `(Legacy — EOL YYYY-MM-DD)` annotation. Do not select as `recommended_model` unless no Active alternative exists.
- **Active**: no restrictions.
- **Restricted** (`restricted (…)` in the `pricing-cache.md` Status column — Covered Models such as Claude Fable 5 / 5.1, gated previews such as Claude Mythos): never `recommended_model` or `backup_model`. Include in `model_comparison` only when the user explicitly asked for a frontier model, annotated with the data-retention opt-in it requires.

## Prerequisites

Read from `$MIGRATION_DIR/`:

- **`ai-workload-profile.json`** — `current_costs.monthly_ai_spend`, `current_costs.services_detected`, `models[]`, `metadata.profile_source`, `summary.inferred_from_iac`
- **`openai-usage-profile.json`** (if present) — `summary.monthly_cost_usd`, `usage_by_model[]` (real per-model input/output token counts from the OpenAI Admin API). Check `metadata.capture_warnings` first: a failed usage endpoint means that category's volume is UNKNOWN, not zero — say so in the output and do not price the affected capability from this profile.
- **`preferences.json`** — `ai_constraints.ai_token_volume.value`, `ai_constraints.ai_capabilities_required.value`
- **`aws-design-ai.json`** — `metadata.ai_source`, `ai_architecture.honest_assessment`, `ai_architecture.tiered_strategy`, `ai_architecture.bedrock_models[]` (with `source_provider_price`, `bedrock_price`, `honest_assessment`), `ai_architecture.capability_mapping`

**Traditional-AI workloads (not yet costed by this phase):** `design_blocks[]` entries with `target_aws_service` set (capability `document_extraction`, `image_analysis`, or `speech_transcription` — Textract, Rekognition, Transcribe) are per-page/per-image/per-minute priced, not token priced, and this phase's cost model does not cover them yet. Skip these blocks in Parts 1–2 below; list them in the output under a `services_not_estimated[]` array (`{workload_id, target_aws_service, reason: "not_token_priced"}`) so the user knows they're excluded rather than assumed free.

---

## Part 1: Establish Current AI Costs

Determine current AI spending from the best available source:

1. **`current_costs.monthly_ai_spend` (preferred whenever present)** — from `ai-workload-profile.json`. This figure is already provider-aware: Discover merges billing-CSV (GCP/Vertex) and OpenAI usage API spend there, summing across providers with `source: "mixed"` and a per-provider `breakdown[]`. Do NOT bypass it by reading `openai-usage-profile.json → summary.monthly_cost_usd` directly — that drops the non-OpenAI half of a mixed workload. When `breakdown[]` exists, carry the per-provider split into the comparison output. **Partial-window check:** if `source` is `openai_usage_api` or `mixed` AND `openai-usage-profile.json → metadata.partial_window` is `true`, the OpenAI portion is not a monthly baseline — apply source 2's exception to that portion (reference figure only, labeled with `active_days`; for `mixed`, keep the GCP portion from `breakdown[]` and cover the OpenAI portion via sources 3–4).
2. **OpenAI usage profile dollars (fallback)** — Use `summary.monthly_cost_usd` from `openai-usage-profile.json` ONLY when no `current_costs` exists (standalone usage capture with no AI workload profile). **Exception:** if `metadata.partial_window` is `true`, the window is too short to be a monthly baseline — do NOT rank it above sources 3–4; fall back and present the partial actuals as a reference figure only, labeled with `active_days`.
3. **Estimated from token volume** — Use `ai_constraints.ai_token_volume.value` from `preferences.json` with Gemini pricing from `pricing-cache.md` (under "Source Provider Pricing"). Apply 60/40 input/output ratio if actual ratio unknown.
4. **None available** — Note in output and present model comparison at multiple volume tiers so user can find their range.

Regardless of which dollar source wins, `openai-usage-profile.json → usage_by_model[]` remains the Part 2 token-volume source (subject to the same `partial_window` exception there).

**IaC-only profile:** If `metadata.profile_source` is `iac_vertex` or `summary.inferred_from_iac` is true and billing/token data is missing, state explicitly that **current GCP AI spend is unverified** and widen uncertainty bands (use the same multi-tier comparison approach as in case 3).

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

If design or discover phase has more specific token estimates, use those instead. In particular, when `openai-usage-profile.json` exists with `metadata.partial_window` `false`, use its `usage_by_model[]` actual monthly input/output token totals (and actual ratio) instead of the tier table — a real observed month beats a tier midpoint. **Exception:** if `metadata.partial_window` is `true`, a few days of tokens is NOT a monthly volume — projecting it as one understates the Bedrock estimate. Use the tier table (from `ai_token_volume`) and present the partial actuals as a reference figure only, labeled with `active_days`.

**Cost formula:** `Monthly = (input_tokens / 1M × input_rate) + (output_tokens / 1M × output_rate)`

**Long-context surcharge:** If `ai_critical_feature = "ultra_long_context"` in `preferences.json`, Claude models charge 2x the standard input rate for tokens beyond 200K context. Apply the surcharge to the portion of input tokens that exceeds 200K per request. If per-request token counts are unknown, assume 50% of input tokens fall in the long-context tier as a conservative estimate.

**Comparison table columns:** Model, Bedrock Monthly, vs Source Provider ($ and %), vs Current GCP, Quality, Capabilities Match (checked against `ai_capabilities_required`).

Include source provider pricing from `aws-design-ai.json` → `bedrock_models[].source_provider_price`.

If Bedrock is more expensive for the recommended model, flag prominently.

If embeddings are needed, add a separate line (additive to primary model cost).

---

## Part 3: Recommended Model Cost Breakdown

Using the model selected in the design phase, show:

- Input tokens × rate, output tokens × rate, embeddings × rate (if applicable)
- Total monthly cost
- Comparison to current GCP spend (monthly and annual difference)
- Backup model cost for comparison

---

## Part 4: Human One-Time Migration Costs (Out of Scope)

**Do not** present human labor, contractors, professional services, or engineering effort as one-time migration **costs** or budget line items (no dollar figures, no "budget for people work" lists, no "one-time migration cost" categories for implementation).

Populate `migration_cost_considerations.categories` as an **empty array** `[]`. Use `migration_cost_considerations.note` to state that human and professional-services one-time migration costs are intentionally excluded from this advisor.

**Technical integration complexity** (for internal JSON and risk context only — not framed as money):

From `ai-workload-profile.json`, record non-monetary factors in `migration_cost_considerations.complexity_factors[]` as short strings, for example:

- `integration.pattern = "framework"` → lower integration touch surface
- `integration.pattern = "direct_sdk"` → moderate SDK and API pattern changes
- `integration.pattern = "rest_api"` → higher endpoint, auth, and parsing changes
- `summary.total_models_detected` > 3 → multi-model coordination
- `quota_risk = "high"` (from `aws-design-ai.json`) → Bedrock quota increase required before migration; allow 1–5 business days (see `vendored/ai/bedrock-quotas.md`)

Do **not** repeat these as "costs" in the user-facing summary.

---

## Part 5: ROI Analysis

Present the monthly and annual cost difference between current GCP AI spend and projected Bedrock cost:

- **If the model is unchanged** (`model_change: false`): projected cost is **about 10% higher**, not the same — Bedrock in-region is priced at OpenAI's data-residency tier, which is 1.10x OpenAI standard. Quote the increase plainly and make the case on non-cost grounds. If any workload exceeds 272K context, price it at the long-context tier (2.0x input / 1.5x output) and show that separately; it can dominate the comparison.
- **If Bedrock is cheaper**: present monthly and annual savings clearly
- **If Bedrock is more expensive**: state clearly, justify with non-cost benefits or note "not justified if cost is the only priority"

Reference `aws-design-ai.json` → `honest_assessment`. If `"recommend_stay"`, present prominently along with `honest_assessment_reason`.

**Non-cost benefits to present:** usage counting toward existing AWS commitments, IAM/VPC/PrivateLink/KMS/CloudTrail governance, in-region processing for data residency, prompt caching (Claude, and GPT-5.6 at 90% off cached input with cached tokens exempt from the input-TPM quota), model flexibility (100+ models), AWS ecosystem (Guardrails, Knowledge Bases, AgentCore), and — for a same-model move — the elimination of behavior-delta and prompt-regression risk.

**Pricing source caveat (all providers):** a `pricing-cache.md` cell marked `_unverified_` is **blocking for any quoted figure, whatever the provider** — resolve it from the Bedrock pricing page or the model card before the row enters `model_comparison` or the ROI table; never substitute a guess or a same-tier sibling's rate. An `_unverified_` cache cell is not evidence the model is unavailable or free — it means the rate was not confirmed when the cache was last updated. See `shared/openai-on-bedrock.md`.

**Unverified gate (all providers, not just OpenAI):** any cell marked `_unverified_` in `shared/pricing-cache.md` — including Anthropic batch cells for models not yet on the [batch-supported models table](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-supported.html) (Sonnet 5, Opus 4.8 as of 2026-09-02) — is blocking for any quoted figure that depends on it. Do not apply a batch discount to an `_unverified_` batch cell; price on-demand and note batch as a possible future saving, or resolve the rate from the Bedrock pricing page first.

**Note:** Human/professional-services one-time migration costs are intentionally out of scope for this advisor and excluded from ROI calculations.

---

## Part 6: Cost Optimization Opportunities

Present applicable optimizations with estimated savings. **Every entry requires a `type`** (stricter than the infra side, where `type` is optional — see `references/shared/ri-sp-eligibility.md` § Consumers) so a Provisioned Throughput row can never silently inherit RI/SP-style commitment language by copy-paste. `commitment` and `target_services` are also required on every entry, for parity with the infra-side render columns consumed by `generate-artifacts-report.md` Appendix B (see that file's key-map table for how the differently-named savings fields on each side map to the same rendered column).

**Do not attach the infra-side Activate-credits caveat to any row in this table.** That caveat (`references/shared/ri-sp-eligibility.md` § Required caveats item 2) exists because RIs/Savings Plans have an upfront cost credits can't cover. None of these seven AI-side levers have an upfront cost — six carry `commitment: "none"` (not "free": Batch API is 50% _of_ on-demand cost, not zero, and prompt-cache-write tokens can be billed at a _higher_ rate than uncached input for some models — "no RI/SP upfront cost" is the accurate framing, not "free"), and Provisioned Throughput is billed hourly with no upfront fee. Applying that sentence here would be incorrect, not just redundant.

**Sequencing note — not all seven are available on day one.** Prompt caching (if prompts qualify), Batch API (if latency is flexible), model downsizing, input token reduction, and multi-model tiered routing (a design-time choice) are usable immediately after migration. Provisioned Throughput requires a sustained-traffic baseline (>100M tokens/month, predictable) and Intelligent Prompt Routing benefits from 2+ weeks of production traffic to validate routing quality before either is worth adopting. Do not present all seven as equally available at migration time — a pre-revenue team reading "up to 90%" and "Provisioned Throughput" side by side, with no sequencing signal, could read both as things to buy in week one.

| Optimization               | `type`                       | Savings                                                                                      | `commitment`                                                                           | Applies When                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model downsizing / tiering | `model_tiering`              | 60-87%                                                                                       | `"none"`                                                                               | High volume, premium model selected. Available: Day 1.                                                                                                                                                                                                                                                                                                                                                              |
| Prompt caching             | `prompt_caching`             | up to 90% on cached input tokens (workload- and cache-hit-rate dependent — see caveat below) | `"none"`                                                                               | Repeated system prompts, long cacheable context. Available: Day 1.                                                                                                                                                                                                                                                                                                                                                  |
| Batch API                  | `batch_api`                  | 50% of on-demand                                                                             | `"none"`                                                                               | Non-real-time workloads (`ai_latency = "flexible"`) — **confirmed-batch models only**; models whose batch cells are `_unverified_` in `shared/pricing-cache.md` must not be quoted with a batch discount. Available: Day 1.                                                                                                                                                                                         |
| Input token reduction      | `input_token_reduction`      | 10-30%                                                                                       | `"none"`                                                                               | Prompt optimization, shorter context. Available: Day 1.                                                                                                                                                                                                                                                                                                                                                             |
| Multi-model tiered routing | `multi_model_routing`        | 60-87%                                                                                       | `"none"`                                                                               | High/very-high volume, `tiered_strategy` in design. Available: Day 1 (design-time choice).                                                                                                                                                                                                                                                                                                                          |
| Intelligent Prompt Routing | `intelligent_prompt_routing` | up to 30% (AWS-published ceiling)                                                            | `"none"`                                                                               | Same model family (Anthropic or Meta Llama by default; additional models via configurable routers) available in 2+ tiers, latency-tolerant routing. **Does not apply to a Gemini-only or OpenAI-only Bedrock stack** — check the design's model family has a router available. Available: after 2+ weeks production traffic (this plugin's caution, not an AWS-imposed minimum -- AWS documents no waiting period). |
| Provisioned throughput     | `provisioned_throughput`     | Varies                                                                                       | no-commit, 1-month, or 6-month (never "1-year or 3-year" — see `ri-sp-eligibility.md`) | Token volume > 100M/month, predictable traffic. Available: after sustained-traffic baseline.                                                                                                                                                                                                                                                                                                                        |

**`target_services` is `["Bedrock"]` for all seven entries** — every AI-side optimization applies to Bedrock inference specifically, unlike the infra side where target services genuinely differ per optimization.

**`potential_savings_monthly` will frequently be `null` pre-migration — populate `potential_savings_percent` too, on every entry, so the merged report table is never blank.** Unlike the infra side, where `savings_monthly` falling back to `savings_percent` is Appendix B's job, the AI-side schema previously had no percent field at all — add one (see Output schema below), sourced from this table's Savings column. Do not ship `potential_savings_monthly: null` with no percent fallback; that produces exactly the blank Monthly Savings cell this schema change exists to prevent.

**Prompt caching vs. Intelligent Prompt Routing vs. Multi-model tiered routing — these are three distinct mechanisms, do not merge or confuse them:**

- **Prompt caching** reduces cost on _repeated_ input tokens within the _same_ model, via Bedrock's cache-read pricing. AWS's own published figure is "up to 90% on cached input tokens" (verified via `docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html` and the GA announcement) — this is a ceiling figure driven by cache hit rate and how much of the prompt is cacheable, not a typical realistic number. Applies beyond Claude — Nova Micro/Lite/Pro and other models also support it (do not title this row "(Claude)"; GPT-5.6 caching is referenced separately in Part 5 of this file). Do not use the previous `~30%` estimate found elsewhere in this codebase; that figure was never sourced from AWS and has been corrected.
- **Intelligent Prompt Routing** is Bedrock's own automatic per-request router between two models in the _same family_ — default routers cover Anthropic and Meta Llama families only; additional models require a configurable router. **This will not help a design whose only Bedrock models are Gemini-on-Bedrock or OpenAI-on-Bedrock** — confirm the design's model family has a router available before surfacing this row. AWS's own published figure is "up to 30%" (verified via `aws.amazon.com/bedrock/intelligent-prompt-routing/`) — this figure is AWS-sourced, but the "2+ weeks production traffic" wait before adopting it is **this plugin's own caution, not an AWS requirement** (AWS's documentation states no minimum traffic period); label it as a plugin estimate the same way the 60-87% multi-model routing figure below is labeled, not as an AWS constraint. This is a **separate row from Multi-model tiered routing** below — do not collapse the two into one entry.
- **Multi-model tiered routing** is this plugin's own design-time optimization: manually splitting traffic across model tiers by workload type (e.g. simple queries to a cheap model, complex queries to a premium model), driven by `tiered_strategy` in the design artifact. This is not an AWS product feature with a published percentage — the 60-87% figure is this plugin's own estimate for that specific design pattern, distinct from Bedrock's automatic Intelligent Prompt Routing.

For each applicable optimization, calculate before/after monthly cost and show an `optimized_projection` (best-case monthly with all optimizations).

**Post-migration optimization (do not surface during migration):** Model distillation — training a smaller, faster student model from a larger teacher model — can reduce inference costs up to ~75% for high-volume, stable workloads. Requires production traffic, labeled examples, and a teacher/student eval loop. Mention in the estimate summary as: "Once you have 2–4 weeks of Bedrock production traffic, consider model distillation to further reduce costs. See docs.aws.amazon.com/bedrock/latest/userguide/model-distillation.html." Do not recommend distillation before the startup has migrated and validated their workload. Model distillation is a genuinely different mechanism from model downsizing/tiering above — downsizing picks a cheaper _existing_ model up front, distillation trains a _new, custom_ smaller model post-migration from observed production traffic. Both are legitimate, non-overlapping levers.

**Emit template — one example per `type`:**

```json
{
  "opportunity": "Prompt caching",
  "type": "prompt_caching",
  "target_services": ["Bedrock"],
  "potential_savings_monthly": null,
  "potential_savings_percent": "up to 90% on cached input tokens",
  "commitment": "none",
  "implementation_effort": "low",
  "available": "day_1",
  "description": "Repeated system prompts or long shared context qualify for cache-read pricing. AWS's published figure is up to 90% cost reduction on cached input tokens — actual savings depend on cache hit rate and how much of the prompt is cacheable. Applies to Claude, Nova Micro/Lite/Pro, and other supported models, not Claude only."
}
```

```json
{
  "opportunity": "Intelligent Prompt Routing",
  "type": "intelligent_prompt_routing",
  "target_services": ["Bedrock"],
  "potential_savings_monthly": null,
  "potential_savings_percent": "up to 30%",
  "commitment": "none",
  "implementation_effort": "low",
  "available": "after_2_weeks_production_traffic",
  "description": "Bedrock's automatic per-request router between two models in the same family (default: Anthropic or Meta Llama; additional models via configurable routers). AWS's published figure is up to 30% cost reduction without compromising accuracy. Does not apply to a design whose only Bedrock models are Gemini-on-Bedrock or OpenAI-on-Bedrock -- confirm a router is available for the design's model family before emitting this entry."
}
```

```json
{
  "opportunity": "Provisioned Throughput",
  "type": "provisioned_throughput",
  "target_services": ["Bedrock"],
  "potential_savings_monthly": null,
  "potential_savings_percent": "varies",
  "commitment": "no-commit, 1-month, or 6-month",
  "implementation_effort": "medium",
  "available": "after_sustained_traffic_baseline",
  "description": "For sustained, predictable high-volume traffic (>100M tokens/month). Distinct from Reserved Instances/Savings Plans — no 1-year or 3-year term exists for this product. Billed hourly, no upfront fee."
}
```

The remaining four types (`model_tiering`, `batch_api`, `input_token_reduction`, `multi_model_routing`) follow the same shape with `"commitment": "none"` and `"available": "day_1"` — always populate `potential_savings_percent` from Part 6's table above, even when `potential_savings_monthly` is `null`.

---

## Part 7: Migration Recommendation (REQUIRED)

Produce a clear migrate/stay/optimize verdict for the AI workload migration. This is the AI-only equivalent of `estimate-infra.md` Part 7.

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

- MUST emit `recommendation` — never omit. If data is insufficient, set `confidence: "low"` and state why in `rationale`.
- If `honest_assessment` from `aws-design-ai.json` says `recommend_stay`, `recommendation.path` MUST be `stay` regardless of cost numbers.
- **A same-model move is a modest cost increase, not parity.** When `bedrock_models[].model_change` is `false`, Bedrock in-region costs ~10% more than OpenAI standard for the same model. Report that figure rather than "no savings identified", and argue the case on commitments, governance, residency, prompt caching, and eliminated behavior-delta risk. A ~10% increase alone should not route to `stay` unless `ai_priority = cost` and no non-cost driver applies; a long-context workload at the 1M tier is a different matter and may legitimately favour staying.
- For multi-workload runs: if some workloads favor migration and others don't, use `migrate_phased` and list which workloads to migrate vs. keep in `rationale`.

---

## Output

Write `estimation-ai.json` to `$MIGRATION_DIR/`.

**Schema — top-level fields:**

| Field                           | Type   | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `phase`                         | string | `"estimate"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `timestamp`                     | string | ISO 8601                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `pricing_source`                | string | `"cached"` or `"unavailable"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `accuracy_confidence`           | string | `"±5-10%"` or `"±15-25%"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `current_costs`                 | object | `source`, `gcp_monthly_ai_spend`, `services[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `token_volume`                  | object | `source`, `monthly_input_tokens`, `monthly_output_tokens`, ratio                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `model_comparison`              | array  | All viable models: `model`, `monthly_cost`, `vs_current`, `quality`, `capabilities_match`, `missing_capabilities[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `recommended_model`             | object | `model`, `monthly_cost`, `breakdown` (input/output/embeddings), `rationale`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `backup_model`                  | object | `model`, `monthly_cost`, `rationale`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `embeddings`                    | object | `model`, `monthly_cost`, `monthly_tokens`, `note` (if applicable)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `cost_comparison`               | object | `current_gcp_monthly`, `projected_bedrock_monthly`, `monthly_difference`, `annual_difference`, `percent_change`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `migration_cost_considerations` | object | `categories[]` (always `[]`), `complexity_factors[]` (technical integration only), `note` (must state human/pro costs excluded)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `roi_analysis`                  | object | `monthly_cost_delta`, `annual_cost_delta`, `justification`, `non_cost_benefits[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `optimization_opportunities`    | array  | `opportunity`, `type` (**required** — one of `model_tiering`, `prompt_caching`, `batch_api`, `intelligent_prompt_routing`, `provisioned_throughput`, `input_token_reduction`, `multi_model_routing`), `target_services` (always `["Bedrock"]`), `commitment` (`"none"` for all except `provisioned_throughput`, which uses the exact vocabulary from `references/shared/ri-sp-eligibility.md` — never "1-year" or "3-year"), `potential_savings_monthly`, `potential_savings_percent` (**required** — populate from Part 6's table even when `potential_savings_monthly` is null, so the merged report table is never blank), `available` (`"day_1"`, `"after_2_weeks_production_traffic"`, or `"after_sustained_traffic_baseline"` — see Part 6), `implementation_effort`, `description` |
| `optimized_projection`          | object | `monthly_with_optimizations`, `vs_current`, `note`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `recommendation`                | object | `path`, `path_label`, `migrate_if`, `stay_if`, `confidence`, `rationale` (see Part 7)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

All cost values are numbers, not strings. Output must be valid JSON.

## Validation Checklist

- [ ] `recommendation` field is present with non-empty `path`, `path_label`, `migrate_if`, `stay_if`, and `rationale`
- [ ] `recommendation.path` is one of: `migrate_optimized`, `migrate_phased`, `stay`
- [ ] If Design `honest_assessment` = `recommend_stay`, then `recommendation.path` = `stay`
- [ ] `model_comparison` includes ALL viable Bedrock models, not just recommended
- [ ] Legacy models in `model_comparison` are annotated with EOL dates (per `vendored/ai/ai-model-lifecycle.md`)
- [ ] `recommended_model` is an Active model (not Legacy) unless no Active alternative exists
- [ ] Neither `recommended_model` nor `backup_model` carries a `restricted (…)` Status in `shared/pricing-cache.md`
- [ ] Every model has `capabilities_match` checked against `ai_capabilities_required`
- [ ] `recommended_model.rationale` references user's priority, preference, and volume
- [ ] `roi_analysis` is honest — if migration increases cost, says so
- [ ] `optimization_opportunities` only includes strategies relevant to user's workload
- [ ] Every `optimization_opportunities[]` entry has `type`, `commitment`, `target_services`, `potential_savings_percent`, and `available` — none are omitted, and `potential_savings_percent` is populated even when `potential_savings_monthly` is `null`
- [ ] The `provisioned_throughput` entry's `commitment` is `"no-commit, 1-month, or 6-month"` (or equivalent exact wording from `references/shared/ri-sp-eligibility.md`) — never `"1-year"` or `"3-year"`
- [ ] No `optimization_opportunities[]` entry carries the infra-side Activate-credits caveat sentence — none of these seven levers have an upfront cost for that caveat to apply to
- [ ] The `intelligent_prompt_routing` entry is omitted (or the design is confirmed to have a router available) when the design's Bedrock models are Gemini-on-Bedrock or OpenAI-on-Bedrock only
- [ ] No compute, database, storage, or networking costs (those belong in `estimate-infra.md`)
- [ ] `migration_cost_considerations.categories` is `[]` — no human one-time migration costs presented

## Completion Handoff Gate (Fail Closed)

Before returning control to `estimate.md`, require:

- `estimation-ai.json` exists and passes the Validation Checklist above.

If this gate fails: STOP and output: "estimate-ai did not produce a valid `estimation-ai.json`; do not complete Phase 4."

## Present Summary

After writing `estimation-ai.json`, present under 25 lines:

1. **Pricing source and accuracy**: State whether prices came from cache or live API, and the accuracy range (±15-25% for AI models from cache, ±5-10% from live API). Example: "AI model estimates based on cached pricing (2026-03-07), accuracy ±15-25%."
2. Current GCP AI spend vs estimated monthly Bedrock cost (recommended model)
3. Model comparison table: model name, estimated monthly cost, vs source provider %, capabilities match
4. Recommended model with estimated monthly cost breakdown
5. If migration increases cost: flag honestly with non-cost justification
6. Top 2-3 optimization opportunities with potential estimated monthly savings (use `potential_savings_percent` when `potential_savings_monthly` is null — never present a blank savings figure). If Provisioned Throughput is among the top entries shown, state its commitment terms explicitly: "no-commit, 1-month, or 6-month" — never imply a 1-year or 3-year term. If Intelligent Prompt Routing or Provisioned Throughput is shown, note they require a production-traffic baseline first (2+ weeks, or a sustained >100M tokens/month baseline respectively) — do not present them as available immediately alongside day-1 levers like prompt caching or Batch API. Do not attach the "Activate credits don't cover upfront RI/SP costs" caveat here — none of these AI-side optimizations have an upfront cost.
7. Optimized projection

**Cost labeling rule:** All dollar figures presented to the user MUST be labeled as "estimated monthly costs" or prefixed with "Est." — never present raw dollar amounts as if they are exact.

## Generate Phase Integration

The Generate phase uses `estimation-ai.json`:

1. **`recommended_model`** — Which Bedrock model to provision and test
2. **`migration_cost_considerations`** — `complexity_factors[]` only for integration risk context; **never** present human one-time migration **costs** to the user (`categories` stays `[]`)
3. **`optimization_opportunities`** — Which optimizations to implement and when
4. **`cost_comparison`** — Cost monitoring targets and alerts in production
5. **`model_comparison`** — Fallback options if recommended model doesn't meet quality bar

## Scope Boundary

**This phase covers financial analysis ONLY for AI workloads.**

FORBIDDEN — Do NOT include compute, database, storage, networking cost calculations, infrastructure provisioning, code migration examples, or detailed migration timelines.
