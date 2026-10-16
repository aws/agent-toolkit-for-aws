# Schema — generation-ai.json (canonical, target-only)

> **Why this file exists.** `estimation-ai.json` just gained a single, provider-neutral written
> contract (`schema-estimate-ai.md`, #389 follow-on). `generation-ai.json` is the same risk one
> phase further: GCP's `skills/gcp-to-aws/references/phases/generate/generate-ai.md` and the
> `generation-ai.json` section of Azure's
> `skills/azure-to-aws/references/phases/generate/generate-artifacts-ai.md` each carry their own
> "Schema — top-level fields" table for the same artifact. This file is the single,
> provider-neutral written contract for `generation-ai.json`, matching
> `schema-estimate-ai.md`'s own canonicalization pattern so GCP and Azure share one definition
> instead of drifting independently. Each consuming skill carries a byte-identical vendored copy
> at `references/vendored/ai/schema-generate-ai.md`.
>
> **This is a target-only contract, like `schema-estimate-ai.md` and the rest of this
> contract family (#410, #415, #416).** Structural validity against this document or its
> companion JSON Schema (`scripts/contracts/generation-ai.schema.json`) does NOT imply an
> implemented adapter, rollout mechanism, or runtime-supported identity, and does NOT imply that
> either skill's current `generate-ai.md` / `generate-artifacts-ai.md` actually emits this shape
> yet. No producer has been repointed to this canonical contract in this change — that is
> deferred runtime-adoption work.

## Shape

```jsonc
{
  "phase": "generate",
  "generation_source": "ai",
  "timestamp": "<ISO 8601>",
  "migration_plan": {
    "duration_drivers": [],
    "approach": "<string>",
    "phases": [],
    "models_to_migrate": [] // normalizedModel[] — covers every model from aws-design-ai.json
  },
  "step_by_step_guide": {
    "languages": [],
    "primary_pattern": "<string>",
    "files_to_modify": [],
    "dependency_changes": "<string>"
  },
  "rollback_plan": {
    "mechanism": "feature_flag", // MUST be this exact value
    "flag_name": "<string>",
    "default_value": "<string>", // free-form pre-cutover provider identifier, e.g. "vertex_ai" | "azure_openai" — not an enum
    "rollback_time": "<string>",
    "triggers": []
  },
  "monitoring": {
    "dashboards": [],
    "alerting_rules": [] // each: { severity, condition, action }
  },
  "production_readiness_checklist": [], // >= 5 string items
  "success_criteria": {
    "quality": {},
    "latency": {},
    "cost": {}
  },
  "recommendation": {
    "approach": "<string>",
    "confidence": "high | medium | low",
    "key_risks": []
  },
  "artifacts_by_source": [] // many-valued — see § artifacts_by_source[]
}
```

## artifacts_by_source[]

Carries the traceability chain one phase forward from `estimation-ai.json`'s `cost_by_source[]`:
each entry's `(provider, source_service)` pair MUST exist in the `estimation-ai.json`
`cost_by_source[]` the migration plan was built from, and every `models[].model` MUST be one of
that source's `models[]`. This is additive — it does not replace `migration_plan.models_to_migrate[]`,
which remains the flat list of every model being migrated regardless of source attribution.

```jsonc
{
  "provider": "anthropic", // extensibleIdentity — never "both" | "openrouter" | "unknown"
  "source_service": "anthropic_api",
  "models": [
    {
      "model": "claude-3-5-sonnet-20240620", // normalizedModel — must trace to the matching estimation-ai.json cost_by_source[] entry
      "generated_files": ["src/ai/anthropic_client.py"] // files this migration plan touches for this specific model
    }
  ]
}
```

Semantic uniqueness is the `(provider, source_service)` pair, same as `estimation-ai.json`'s
`cost_by_source[]`. `provider` is never `"openrouter"` — an OpenRouter-fronted artifact still
attributes to the fronted provider's `(provider, source_service)` pair.

## Design-decision: no `model_observations[]` here

Same rationale as `schema-estimate-ai.md`: by Generate, the model identity has been resolved
twice over (Design, then Estimate). `artifacts_by_source[]` entries key off
`(provider, source_service, model)` triples copied FROM `estimation-ai.json`'s `cost_by_source[]`,
not re-observed. Carrying `model_observations[]` forward here would re-introduce an uncertainty
concept that was resolved two phases earlier. This is intentionally dropped, not forgotten.

## rollback_plan

`mechanism` MUST be the literal string `"feature_flag"` — this contract does not model any other
rollback mechanism. `default_value` is a free-form string naming the pre-cutover provider
identifier (e.g. GCP's `"vertex_ai"`, Azure's `"azure_openai"`); both skills already treat it as
a free-form string, not an enum, and this contract does not special-case the value.

## Validation Checklist

- [ ] `migration_plan.models_to_migrate` covers all models from the matching `aws-design-ai.json`.
- [ ] `artifacts_by_source[]` is non-empty whenever the matching `estimation-ai.json`'s
      `cost_by_source[]` is non-empty, and each entry's `(provider, source_service)` pair is
      unique.
- [ ] Every `artifacts_by_source[]` entry's `(provider, source_service)` pair exists in the
      matching `estimation-ai.json`'s `cost_by_source[]`.
- [ ] Every `artifacts_by_source[].models[].model` is one of that source's `cost_by_source[]`
      `models[].model` entries in the matching `estimation-ai.json`.
- [ ] No entry in `artifacts_by_source[]` has `provider: "openrouter"`.
- [ ] `rollback_plan.mechanism` is `"feature_flag"`.
- [ ] `production_readiness_checklist` has at least 5 items.
- [ ] `success_criteria` covers `quality`, `latency`, and `cost`.

## Status — target-only, no producer yet

This canonical contract has no producer in this change. GCP's
`skills/gcp-to-aws/references/phases/generate/generate-ai.md` and the `generation-ai.json`
section of Azure's `skills/azure-to-aws/references/phases/generate/generate-artifacts-ai.md`
still write against their own "Schema — top-level fields" tables, and neither emits
`artifacts_by_source[]`. This document (and its companion JSON Schema,
`scripts/contracts/generation-ai.schema.json`) is the TARGET contract. Repointing either skill's
generate phase to emit this shape is deferred runtime-adoption work, named explicitly so a
future PR does not silently assume today's runtime output already satisfies this contract.
