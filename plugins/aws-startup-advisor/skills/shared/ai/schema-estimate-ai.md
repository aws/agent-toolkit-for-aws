# Schema — estimation-ai.json (canonical, target-only)

> **Why this file exists.** `aws-design-ai.json` had a prose-only contract that drifted between
> GCP and Azure until #416 canonicalized it (`schema-design-aws-ai.md`). `estimation-ai.json` is
> the same risk one phase over: `estimate-ai.md` produces it (both GCP's
> `skills/gcp-to-aws/references/phases/estimate/estimate-ai.md` and Azure's
> `skills/azure-to-aws/references/phases/estimate/estimate-ai.md`), and `generate-ai.md` /
> `generate-artifacts-ai.md` consume it, with each skill's own "Schema — top-level fields"
> table carrying the same field set under GCP-/Azure-named keys (`gcp_monthly_ai_spend` vs
> `azure_monthly_ai_spend`, `current_gcp_monthly` vs `current_azure_monthly`). This file is the
> single, provider-neutral written contract, using neutral field names
> (`current_costs.monthly_ai_spend`, `cost_comparison.current_source_monthly`) so one JSON
> Schema (`scripts/contracts/estimation-ai.schema.json`) serves both skills without a GCP/Azure
> branch — the same provider-neutral framing `ai-workload-profile.schema.json` (#415) and
> `aws-design-ai.schema.json` (#416) already use. Each consuming skill carries a byte-identical
> vendored copy at `references/vendored/ai/schema-estimate-ai.md`.
>
> **This is a target-only contract, like `ai-migration-scenario.schema.json` (#410),
> `ai-workload-profile.schema.json` (#415), and `aws-design-ai.schema.json` (#416).** Structural
> validity against this document or its companion JSON Schema does NOT imply an implemented
> pricing lookup, model mapping, or runtime-supported identity, and does NOT imply that either
> skill's current `estimate-ai.md` actually emits this shape yet — NEITHER skill's `estimate-ai.md`
> currently emits the neutral field names (`current_costs.monthly_ai_spend`,
> `cost_comparison.current_source_monthly`, `cost_by_source[]`); current GCP/Azure output still
> uses the GCP-/Azure-named fields documented in each skill's own `estimate-ai.md`, unchanged by
> this document. No producer has been repointed to this canonical contract in this change — that
> is deferred runtime-adoption work.

## Shape

```jsonc
{
  "phase": "estimate",
  "timestamp": "<ISO 8601>",
  "pricing_source": "cached", // cached | unavailable
  "accuracy_confidence": "±15-25%",
  "current_costs": {
    "source": "mixed", // provenance label — see each skill's estimate-ai.md Part 1
    "monthly_ai_spend": 1200.0, // provider-neutral name for gcp_monthly_ai_spend / azure_monthly_ai_spend
    "services": []
  },
  "token_volume": {},
  "model_comparison": [],
  "recommended_model": {},
  "backup_model": {},
  "embeddings": {}, // present only when the workload uses embeddings
  "cost_comparison": {
    "current_source_monthly": 1200.0, // provider-neutral name for current_gcp_monthly / current_azure_monthly; number or null
    "projected_bedrock_monthly": 1320.0, // number or null
    "monthly_difference": 120.0, // number or null
    "annual_difference": 1440.0, // number or null
    "percent_change": 10.0 // number or null
  },
  "migration_cost_considerations": {
    "categories": [], // ALWAYS [] — human/pro-services costs are out of scope
    "complexity_factors": [],
    "note": "Human and professional-services one-time migration costs are intentionally excluded from this advisor."
  },
  "roi_analysis": {},
  "optimization_opportunities": [], // see § optimization_opportunities[]
  "optimized_projection": {},
  "recommendation": {}, // see § recommendation
  "cost_by_source": [], // many-valued — see § cost_by_source[]
  "services_not_estimated": [] // ALWAYS present, [] when every workload is token-priced
}
```

## cost_by_source[]

Carries the design-time identity chain forward into the estimate: each entry's
`(provider, source_service)` pair MUST exist in the `aws-design-ai.json` the estimate was built
from (either a direct `metadata.ai_sources[]` entry, or a `metadata.gateways[].upstreams[]`
entry), and every `models[].model` MUST be one of that source's `models[]` (direct) or
`model_families[].models` (gateway upstream). This is additive — it does not replace
`model_comparison[]`, which remains the per-model Bedrock-vs-source comparison for ALL viable
models regardless of source attribution.

```jsonc
{
  "provider": "anthropic", // extensibleIdentity — never "both" | "openrouter" | "unknown"
  "source_service": "anthropic_api",
  "models": [
    {
      "model": "claude-3-5-sonnet-20240620", // normalizedModel — must trace to the matching aws-design-ai.json source
      "monthly_cost": 1320.0, // projected Bedrock monthly cost for this model under this source; null when its target rate is unavailable
      "vs_source_percent": 10.0 // null when a source-side list rate is unavailable (e.g. an OpenRouter-only portion)
    }
  ]
}
```

Semantic uniqueness is the `(provider, source_service)` pair, same as `aws-design-ai.json`'s
`metadata.ai_sources[]` — a duplicate or overlapping pair is a contract violation, not a
presentation choice. `provider` is never `"openrouter"`; an OpenRouter-fronted cost still
attributes to the fronted provider's `(provider, source_service)` pair, mirroring how
`aws-design-ai.json`'s `metadata.gateways[].upstreams[]` represents gateway-fronted sources.

## Unknown costs and null propagation

Unavailable monetary values are JSON `null`, never numeric zero. If the source baseline is
unknown, `current_costs.monthly_ai_spend` and `cost_comparison.current_source_monthly` are `null`,
and all differences derived from that baseline (`monthly_difference`, `annual_difference`, and
`percent_change`) are also `null`. If a target rate is unavailable, set
`cost_comparison.projected_bedrock_monthly` and the affected
`cost_by_source[].models[].monthly_cost` values to `null`; every difference that depends on that
unknown target is `null` as well. Numeric `0` is reserved for a cost that is known to be zero.

## Design-decision: no `model_observations[]` here

`model_observations[]` (the raw/observed model string, provenance, and confidence pair) exists in
`ai-workload-profile.schema.json` and `aws-design-ai.schema.json` to carry an identity that is
still being established at Discover/Design time. By Estimate, the identity is already resolved —
`aws-design-ai.json`'s `metadata.ai_sources[]`/`models[]` is the resolved, trusted identity list,
and this contract's `cost_by_source[]` entries key off `(provider, source_service, model)` triples
copied FROM that resolved list, not re-observed. Carrying `model_observations[]` forward into
`estimation-ai.json` would re-introduce an uncertainty concept that Design has already resolved.
This is intentionally dropped, not forgotten.

## optimization_opportunities[]

Each entry's `type` is REQUIRED and is one of `model_tiering`, `prompt_caching`, `batch_api`,
`intelligent_prompt_routing`, `provisioned_throughput`, `input_token_reduction`,
`multi_model_routing` (see each skill's `estimate-ai.md` Part 6 for the full vocabulary and
sequencing notes). `target_services` is always `["Bedrock"]`. `potential_savings_percent` is
REQUIRED on every entry — populated even when `potential_savings_monthly` is `null`, so a merged
report table is never blank.

## recommendation

`path` is REQUIRED and is one of `migrate_optimized`, `migrate_phased`, `stay` (see each skill's
`estimate-ai.md` Part 7 for the full decision logic). When the Design artifact's
`ai_architecture.honest_assessment` is `recommend_stay`, `recommendation.path` MUST be `stay`
regardless of cost numbers.

## services_not_estimated[]

ALWAYS present (`[]` when every workload is token-priced). Per entry:
`{ workload_id, target_aws_service, reason: "not_token_priced" }` — `design_blocks[]` rows with
`target_aws_service` set (Textract, Rekognition, Transcribe) are per-page/per-image/per-minute
priced, not token priced, and are listed here instead of silently omitted.

## Validation Checklist

- [ ] `cost_by_source[]` is non-empty whenever `aws-design-ai.json`'s `metadata.ai_sources[]` is
      non-empty, and each entry's `(provider, source_service)` pair is unique.
- [ ] Every `cost_by_source[]` entry's `(provider, source_service)` pair exists in the matching
      `aws-design-ai.json`'s `metadata.ai_sources[]` or a `metadata.gateways[].upstreams[]` entry.
- [ ] Every `cost_by_source[].models[].model` is one of that source's `models[]` (direct) or
      `model_families[].models` (gateway upstream) in the matching `aws-design-ai.json`.
- [ ] No entry in `cost_by_source[]` has `provider: "openrouter"`.
- [ ] `recommendation` is present with non-empty `path`, `path_label`, `migrate_if`, `stay_if`,
      and `rationale`; `path` is one of `migrate_optimized`, `migrate_phased`, `stay`.
- [ ] If Design `honest_assessment` is `recommend_stay`, `recommendation.path` is `stay`.
- [ ] Every `optimization_opportunities[]` entry has `type`, `commitment`, `target_services`,
      `potential_savings_percent`, and `available`.
- [ ] `migration_cost_considerations.categories` is `[]`.
- [ ] Unknown source or target costs and their dependent deltas are `null`; known zero-dollar
      costs remain numeric `0`.
- [ ] `services_not_estimated[]` is present (`[]` when clean).

## Status — target-only, no producer yet

This canonical contract has no producer in this change. Both GCP's
`skills/gcp-to-aws/references/phases/estimate/estimate-ai.md` and Azure's
`skills/azure-to-aws/references/phases/estimate/estimate-ai.md` still write against their own
"Schema — top-level fields" table with GCP-/Azure-named fields (`current_costs.gcp_monthly_ai_spend`
/ `current_costs.azure_monthly_ai_spend`, `cost_comparison.current_gcp_monthly` /
`cost_comparison.current_azure_monthly`), and neither emits `cost_by_source[]`. This document
(and its companion JSON Schema, `scripts/contracts/estimation-ai.schema.json`) is the TARGET
contract. Repointing either skill's `estimate-ai.md` to emit this shape is deferred
runtime-adoption work, named explicitly so a future PR does not silently assume today's runtime
output already satisfies this contract. `generate-ai.md` and `generate-artifacts-ai.md` are
unchanged and still read today's artifact shape.
