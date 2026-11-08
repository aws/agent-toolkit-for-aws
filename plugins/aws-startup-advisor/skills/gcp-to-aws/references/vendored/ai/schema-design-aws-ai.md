# Schema — aws-design-ai.json (canonical, target-only)

> **Why this file exists.** `aws-design.json` had no schema once and a capability run
> reverse-engineered its shape from postconditions, inventing key names the golden did not
> share (§13.3a). The AI design artifact is the same risk one layer over: `design-ai.md`
> produces it, `estimate-ai.md` and `generate-artifacts-ai.md` consume it, and a prose-only
> contract drifts between producers by construction. This file is the single, provider-neutral
> written contract for `aws-design-ai.json`, canonicalized from Azure's prior
> `references/shared/schema-design-aws-ai.md` so GCP and Azure share one definition instead of
> drifting independently (GCP had none). Each consuming skill carries a byte-identical vendored
> copy at `references/vendored/ai/schema-design-aws-ai.md`.
>
> **This is a target-only contract, like `ai-migration-scenario.schema.json` (#410) and
> `ai-workload-profile.schema.json` (#415).** Structural validity against this document or its
> companion JSON Schema (`scripts/contracts/aws-design-ai.schema.json`) does NOT imply an
> implemented detector, adapter, route, model mapping, or runtime-supported identity, and does
> NOT imply that GCP's or Azure's current `design-ai.md` actually emits this shape yet. No
> producer has been repointed to this canonical contract in this change — that is deferred
> runtime-adoption work.
>
> **What changed from the prior Azure-only contract.** The prior contract's `metadata.ai_source`
> was a single scalar string (`azure_openai | openai | anthropic | both | other`) that MUST
> equal a single scalar `summary.ai_source` from the profile — the same lossy, single-identity
> `both`-sentinel pattern #410 and #415 retired in the observation layer. This canonical version
> replaces that scalar with many-valued `metadata.ai_sources[]` / `metadata.gateways[]`, mirroring
> `ai-workload-profile.schema.json`'s `ai_sources[]` / `gateways[]` shape EXACTLY (same field
> names, same types, same evidence-gating rules). A design can now carry simultaneous
> Anthropic-sourced and OpenAI-sourced workloads, or an OpenRouter gateway fronting several
> providers at once, without collapsing them into one scalar identity.

`aws-design-ai.json` is written by `phases/design/design-ai.md` **only when
`ai-workload-profile.json` exists**. It is a SEPARATE artifact from `aws-design.json`
(§19.10): the infra assembler still solely owns `aws-design.json`; the AI fragment owns this
file. When there is no AI workload, this file is not produced and nothing downstream looks
for it.

## Shape

```jsonc
{
  "phase": "design",
  "focus": "ai",
  "timestamp": "<ISO 8601>",
  "source_profile": "ai-workload-profile.json",
  "metadata": {
    "ai_sources": [], // many-valued — see § metadata.ai_sources[]; mirrors the profile's ai_sources[] exactly
    "gateways": [], // many-valued — see § metadata.gateways[]; mirrors the profile's gateways[] exactly
    "bedrock_models_selected": [], // aws_model_id strings chosen (Bedrock targets only)
    "regional_validation": "checked" // checked | fallback_static  (see § regional_validation)
  },
  "design_blocks": [], // one per workloads[] entry — see § design_blocks
  "ai_architecture": { // see § ai_architecture
    "honest_assessment": "strong_migrate",
    "honest_assessment_reason": null,
    "tiered_strategy": null,
    "bedrock_models": [],
    "capability_mapping": {},
    "code_migration": {},
    "infrastructure": [],
    "services_to_migrate": []
  },
  "regional_warnings": [], // ALWAYS present, [] when clean — see § regional_warnings
  "multi_model_warnings": [], // ALWAYS present, [] when single model — see § multi_model_warnings
  "agentic_design": null, // present ONLY when agentic_profile.is_agentic — see § agentic_design
  "halt": {} // present ONLY when the AI design is failing its gate
}
```

**Accounting invariant.** Every entry in the profile's `workloads[]` (or `models[]` when
`workloads[]` is empty) appears in exactly one `design_blocks[]` row, in input order.

## metadata.ai_sources[]

Byte-identical in shape to `ai-workload-profile.schema.json`'s `ai_sources[]` (`scripts/contracts/ai-workload-profile.schema.json`,
definition `aiSource`). Each entry:

```jsonc
{
  "provider": "anthropic", // extensibleIdentity — never "both" | "openrouter" | "unknown"
  "source_service": "anthropic_api", // extensibleIdentity — e.g. "openai_api" vs "azure_openai" distinguishes direct vs Azure-fronted OpenAI
  "model_families": ["claude"], // modelFamily[], non-empty
  "model_evidence": "observed", // observed | not_observed
  "models": ["claude-3-5-sonnet-20240620"], // normalizedModel[]; [] iff model_evidence == "not_observed"
  "model_observations": [] // raw-alias/evidence trail; [] iff model_evidence == "not_observed" — see the profile schema's modelObservation
}
```

The JSON Schema (`scripts/contracts/aws-design-ai.schema.json`) enforces `model_observations`
non-empty whenever `model_evidence == "observed"`, in addition to `models` non-empty — an
observed source can no longer carry an empty `model_observations[]`.

Semantic uniqueness is the `(provider, source_service)` pair; a design can carry multiple
simultaneous sources (one Anthropic-sourced workload and one OpenAI-sourced workload in the
same `aws-design-ai.json` is valid and expected — this is the shape change this canonicalization
makes). `provider` is never `"openrouter"` — OpenRouter and other LLM routers are represented
only in `metadata.gateways[]`, never as a direct source.

## metadata.gateways[]

Byte-identical in shape to `ai-workload-profile.schema.json`'s `gateways[]` (definition
`gateway`). An observed gateway's `upstreams[]` must correspond exactly to the `ai_sources[]`
entries it fronts (same provider/source_service/model_families/model_evidence/models
association #410's gateway-correspondence rule enforces); an unresolved gateway's `upstreams[]`
is explicitly empty.

```jsonc
{
  "product": "openrouter", // gatewayIdentity — never "both" | "unknown"
  "type": "llm_router",
  "upstream_evidence": "observed", // observed | unresolved
  "upstreams": [] // gatewayUpstream[]; [] iff upstream_evidence == "unresolved"
}
```

Both `metadata.ai_sources[]` and `metadata.gateways[]` project **verbatim** from the
`ai-workload-profile.json` the design was built from — the test suite
(`test_aws_design_ai_contracts.py`) proves this projection against #415's own semantic
oracle (`_assert_profile_semantics`), the same way #415 proved its own projection into #410.
A design that drops a model, renames a provider, or collapses two sources from the profile
into one is a contract violation, not a presentation choice.

## design_blocks[]

One row per confirmed workload. This is the per-workload target decision.

```jsonc
{
  "workload_id": "wl_3a1f2c", // from the profile's workloads[]; preserve verbatim
  "model_id": "gpt-4o", // the source model / SDK method the workload used
  "target_bedrock_model": "anthropic.claude-sonnet-4-5-v1:0", // XOR target_aws_service — see below
  "target_aws_service": null, // XOR target_bedrock_model — see below
  "capability": "text_generation", // the workload's capability (see § capability vocabulary)
  "capability_confidence": "high", // high | medium | low
  "rationale": "<one or two sentences a customer can read>",
  "confidence_warning": null // non-null string when capability_confidence == "low"
}
```

- **`target_bedrock_model` XOR `target_aws_service` — exactly one is non-null per row.**
  Bedrock-model capabilities (`text_generation`, `structured_output`, `image_generation`,
  `embedding`, `speech_to_text`, `text_to_speech`, `unknown`) set `target_bedrock_model` and
  leave `target_aws_service` null. The three traditional-AI capabilities
  (`document_extraction`, `image_analysis`, `speech_transcription`) set `target_aws_service`
  (one of `"textract"`, `"rekognition"`, `"transcribe"`, `"comprehend"`, `"translate"`,
  `"polly"`, `"sagemaker"`) and leave `target_bedrock_model` null. This is the same rule gcp
  enforces; it exists because those three are AWS AI services, not Bedrock model swaps.
- **`confidence_warning`** is a non-null string (naming the workload and that manual review is
  required) when `capability_confidence == "low"`; null for `high`/`medium`.
- **Input order preserved:** `design_blocks[]` order matches the profile's `workloads[]` order.
- **`model_id` provenance:** every `design_blocks[]` row's source model MUST trace to a
  `metadata.ai_sources[]` entry (directly, or through a `metadata.gateways[]` upstream) — a
  `design_blocks[]` row naming a model no retained source or gateway upstream carries is a
  contract violation.

## capability vocabulary

Bedrock-model capabilities: `text_generation`, `structured_output`, `image_generation`,
`embedding`, `speech_to_text`, `text_to_speech`, `unknown`.
Traditional-AI capabilities (AWS AI service, not Bedrock): `document_extraction`,
`image_analysis`, `speech_transcription`.

## ai_architecture

- **`honest_assessment`** — `strong_migrate | moderate_migrate | weak_migrate |
  recommend_stay | not_applicable`. Overall value = the weakest across all Bedrock models.
  `not_applicable` is a PER-WORKLOAD value for the three traditional-AI capabilities only —
  never the overall assessment (they are feature swaps, not a cost-driven model decision).
- **`honest_assessment_reason`** — REQUIRED (non-null) when `honest_assessment ==
  "recommend_stay"`; names the specific non-cost blocker (fixed region with no suitable model,
  a Realtime/streaming dependency, an Assistants-style feature with no Bedrock equivalent, or a
  confirmed unsupported API surface). Null otherwise. Cost parity alone is never sufficient to
  recommend staying when the source models are on Bedrock.
- **`tiered_strategy`** — object when `ai_token_volume == "high"` (a 3-tier routing plan);
  null for low/medium.
- **`bedrock_models[]`** — per Bedrock target: `source_model_id`, `aws_model_id`,
  `capabilities_matched[]`, `capability_gaps[]`, `honest_assessment`, `source_provider_price`,
  `bedrock_price`, `price_comparison`, `migration_complexity`, `model_change` (bool),
  `migration_path` (see below), `quota_risk` (`low|medium|high`), `required_client_api`
  (`responses | chat_completions | converse | invoke | messages` — the client API surface the
  generated code must use; for `runtime_openai_cris` it is the API the source app already
  calls, never an implicit Converse), `mantle_selector` (REQUIRED on every `mantle_*` row,
  absent otherwise — see below), `mantle_requirement` (object, REQUIRED on every `mantle_*` row,
  absent otherwise — the Clarify entry or catalog row the selector was derived from; see below)
  and `endpoint_assumption` (string, REQUIRED on every row whose `migration_path` does NOT start
  with `mantle_` — the verbatim bedrock-runtime disclosure; see below). Traditional-AI
  capabilities do NOT appear here — they are `design_blocks[]` rows with `target_aws_service`.
- **`capability_mapping`** — per capability that is `true` in the profile's
  `integration.capabilities_summary`: `{ parity: "full|partial|none", notes }`.
- **`code_migration`** — `primary_pattern` (matches profile `integration.pattern`),
  `framework`, `files_to_modify[]`, `dependency_changes`, and — when a retained source's
  `source_service` is `azure_openai` or a `provider`/`source_service` pair resolves to OpenAI —
  `openrouter_path` when a router was detected
  (`same_model_runtime|same_model_mantle|direct|litellm|keep_openrouter`; `same_model_runtime`
  is the default same-model route — `bedrock-runtime` CRIS — and `same_model_mantle` requires a
  `mantle_selector` on the row).
- **`infrastructure[]`** — source-cloud AI infra resource → AWS equivalent, with confidence.
- **`services_to_migrate[]`** — source-cloud AI service → AWS service, effort, notes.

## migration_path vocabulary

**`bedrock-runtime` is the default endpoint for every new path** (`vendored/ai/bedrock-endpoint-policy.md`):
a same-model OpenAI-protocol source records `runtime_openai_cris`, an Anthropic SDK source records
`runtime_messages`, and a `mantle_*` path is recorded only with a `bedrock_models[].mantle_selector`.

`runtime_openai_cris` (same-model move served via `bedrock-runtime` `/openai/v1` with a CRIS id,
`model_change: false`, `required_client_api` = the source app's `responses` or `chat_completions`;
`us.`/`in.`/`global.` for GPT-5.6 Terra and Luna; `us.`/`global.` only for GPT-5.6 Sol, GPT-6,
GPT-5.5 and GPT-5.4, per their model cards) · `runtime_messages` (Anthropic SDK kept on
`bedrock-runtime` `/anthropic` with a Claude profile id, `required_client_api: "messages"`,
`model_change` per the model mapping) · `mantle_openai_responses` (an OpenAI-protocol source — direct
or Azure-fronted — with the model on Bedrock and the region carrying it: keep the SDK,
`model_change: false`; requires `mantle_selector`) · `mantle_openai_chat` (same, preserving a Chat
Completions source on a model whose card lists Chat Completions on mantle — GPT-6, GPT-5.5,
GPT-5.4; requires `mantle_selector`) · `mantle_messages` (Anthropic SDK on the Mantle `/anthropic`
endpoint; requires `mantle_selector`, normally `workspaces`) · `converse` (Bedrock-native
Converse/`bedrock-runtime`; set `model_change: true` when the workload needs Knowledge Bases,
intelligent prompt routing, or another feature no same-model path serves) · `gpt-oss`
(OpenAI-lineage model on the Bedrock-native runtime) · `direct` (framework-agnostic Bedrock SDK
swap). A **bare** proprietary `openai.gpt-*` model ID is NEVER paired with a
`converse`/`bedrock-runtime` path — bare ids are mantle ids; every proprietary GPT target on
`bedrock-runtime` carries a CRIS-prefixed id (there is no runtime in-region form for GPT-6,
GPT-5.6, GPT-5.5 or GPT-5.4).

## mantle_selector (required on every `mantle_*` `bedrock_models[]` row)

One of `background_inference | server_side_tools | web_search | projects | workspaces |
mantle_only_model_or_api | in_region_processing` — the verified Mantle-only need that justified
leaving the `bedrock-runtime` default (definitions in `vendored/ai/bedrock-endpoint-policy.md`).
API continuity (the app already calls Responses, Chat Completions or Messages) is not a selector.
Absent on `runtime_*`, `converse`, `gpt-oss` and `direct` rows.

## mantle_requirement and endpoint_assumption (how mantle_selector is derived)

Design never infers a `mantle_selector` from the source API, the model, or a guess. It reads
`preferences.json → ai_constraints.mantle_requirements.value[]` (written by Clarify — full flow
Q22b, AI-only Q10.5; absent on older runs = no requirement recorded) and applies this rule per
workload:

- A workload (matched by its own `workload_id`, or by an entry whose `workload_id` is `*`) with an
  entry whose `selector` is one of `background_inference | server_side_tools | web_search |
  projects | workspaces | in_region_processing` and whose `source` is `detected` or `user` takes
  the Mantle path for its source API — `mantle_openai_responses` for a Responses source,
  `mantle_openai_chat` for a Chat Completions source, `mantle_messages` for an Anthropic SDK
  source — with `mantle_selector` = that selector. Several matching entries → the first in the
  policy-table order `background_inference, server_side_tools, web_search, projects, workspaces,
  in_region_processing` becomes `mantle_selector`; name the others in the row's `rationale`.
  `in_region_processing` applies only when `bedrock-runtime` serves the model in the entry's
  `region` through a CRIS profile alone (the CRIS-only gate in `ai-openai-to-bedrock.md`);
  otherwise the workload stays on `bedrock-runtime` in that Region.
- `mantle_only_model_or_api` is never a Clarify value: Design derives it from the catalog
  (`ai-openai-to-bedrock.md` / `openai-on-bedrock.md` access-path tables) when the selected model
  or API exists only on `bedrock-mantle`, and records `mantle_requirement.source: "catalog"`.
- Every other workload keeps the `bedrock-runtime` default and its row records
  `endpoint_assumption` verbatim (below). A `none` entry, a default entry, or no entry at all is a
  runtime lane by design, not an inference.

**`bedrock_models[].mantle_requirement`** — object, REQUIRED on every row whose `migration_path`
starts with `mantle_`, absent otherwise:

```jsonc
{
  "workload_id": "wl_3a1f2c", // the workloads[].workload_id the entry applied to, or "*"
  "selector": "web_search", // same value as the row's mantle_selector
  "source": "detected", // detected | user | catalog
  "evidence": "src/ai/openai_client.py:14 tools=[{\"type\": \"web_search\"}]", // present when source is detected (file:line construct) or catalog (the catalog file/row)
  "region": "us-east-1" // present iff selector is in_region_processing
}
```

`source: detected | user` entries are copied from the matching
`ai_constraints.mantle_requirements.value[]` entry (same `workload_id`, `selector`, `evidence`,
`region`); `source: "catalog"` is written only by Design for `mantle_only_model_or_api`.

**`bedrock_models[].endpoint_assumption`** — string, REQUIRED on every row whose
`migration_path` does NOT start with `mantle_` (`runtime_openai_cris`, `runtime_messages`,
`converse`, `gpt-oss`, `direct`), exactly:

> No Mantle-only requirement was recorded for <workload_id>; bedrock-runtime selected. If this
> workload needs background inference, server-side tools, Projects/Workspaces, or single-Region
> processing, re-run Clarify.

where `<workload_id>` is the `design_blocks[].workload_id` whose `model_id` equals the row's
`source_model_id` (several workloads → comma-joined ids), written as a plain id with no
backticks or quotes (`No Mantle-only requirement was recorded for wl_3a1f2c; …`). Generate echoes the sentence in the
generated script/adapter header and the llm-to-bedrock report quotes it, so the user sees that
the runtime choice rests on a recorded answer, not on a silent default.

## regional_validation

`checked` (`aws___get_regional_availability` on the AWS MCP Server confirmed model/region
availability) · `fallback_static` (the call failed; the static table in
`vendored/ai/ai-migration-guardrails.md` was used).

## regional_warnings[]

ALWAYS present (`[]` when clean). Per unavailable service:
`{ service, target_region, nearest_available, impact }`. A compliance constraint that forced a
region (e.g. `fedramp` → GovCloud, `gdpr` → EU `eu.` profiles) records the models it excluded
here. Never blocks the design — it flags the constraint and proceeds.

## multi_model_warnings[]

ALWAYS present (`[]` when a single model / no coordination issue). Per warning:
`{ type, message }`, `type ∈ embeddings_reindex | cascade_pair | multi_model_tiered |
image_separate | speech_separate`.

## agentic_design

Present ONLY when the profile's `agentic_profile.is_agentic == true`; null/absent otherwise.
`{ migration_approach: "retarget|harness|strands|undecided", ...path-specific config }`. When
`migration_approach == "harness"` carry `harness_config` (with `source_model_provider`, derived
per retained source rather than a single scalar — an OpenAI-protocol source with
`source_service: "azure_openai"` sets `source_model_provider: "open_ai"` — see §19.9(b)); when
`"strands"` carry the AgentCore Runtime config from `vendored/ai/design-ref-agentic-to-agentcore.md`.

## halt

Present ONLY when the AI design is failing its gate. `{ reason, blocking[] }` where each
`blocking[]` entry is `{ kind, identifier, why, action }`. The AI design halts when a routed
rubric file (`ai.md`, a provider-to-Bedrock mapping guide, or a `vendored/ai/*` ref) named by
`index.md` is not on disk — the same missing-rubric guard the infra design uses.

## Validation Checklist

- [ ] `metadata.ai_sources[]` is non-empty whenever the profile has at least one retained
      source, and each entry's `(provider, source_service)` pair is unique — no duplicate or
      overlapping source.
- [ ] `metadata.ai_sources[]` and `metadata.gateways[]` project verbatim from the
      `ai-workload-profile.json` the design was built from (same provider, source_service,
      model_families, model_evidence, models, model_observations, and gateway upstream
      correspondence) — no dropped, renamed, or fabricated source or model.
- [ ] No entry in `metadata.ai_sources[]` has `provider: "openrouter"`; OpenRouter and other
      routers appear only in `metadata.gateways[]`.
- [ ] Every `workloads[]` entry (or `models[]` when workloads is empty) has exactly one
      `design_blocks[]` row, in input order.
- [ ] Every `design_blocks[]` row has exactly one of `target_bedrock_model` /
      `target_aws_service` non-null (XOR), and its source model traces to a
      `metadata.ai_sources[]` entry or a `metadata.gateways[]` upstream.
- [ ] Every traditional-AI row (`document_extraction`/`image_analysis`/`speech_transcription`)
      has `target_bedrock_model: null`, a non-null `target_aws_service`, and (in
      `ai_architecture`) is not counted in `bedrock_models[]`.
- [ ] Every `bedrock_models[]` entry has `source_provider_price`, `bedrock_price`,
      `price_comparison`.
- [ ] `honest_assessment` overall is the weakest across `bedrock_models[]`; if
      `recommend_stay`, `honest_assessment_reason` names a non-cost blocker.
- [ ] No `bedrock_models[]` entry pairs a **bare** proprietary `openai.gpt-*` model ID with a
      `converse`/`bedrock-runtime` migration path (bare ids are mantle ids; a `bedrock-runtime`
      target carries a CRIS id: `us.`/`in.`/`global.` for GPT-5.6 Terra / Luna; `us.`/`global.` only
      for GPT-5.6 Sol, GPT-6, GPT-5.5 and GPT-5.4).
- [ ] For a retained source whose `source_service` is `azure_openai`, or whose provider resolves
      to direct OpenAI: every source model that is available on Bedrock and carried by the
      target region maps to ITSELF with `model_change: false` — not to a Claude/Nova substitute —
      and records `migration_path: "runtime_openai_cris"` by default.
- [ ] Every `bedrock_models[]` row whose `migration_path` starts with `mantle_` carries a
      `mantle_selector` from the enum above; no `runtime_*`/`converse` row carries one.
- [ ] Every `mantle_*` row carries a `mantle_requirement` whose `selector` equals the row's
      `mantle_selector`, whose `source` is `detected | user | catalog` (`catalog` iff the selector
      is `mantle_only_model_or_api`), and whose `region` is present iff the selector is
      `in_region_processing`; the selector was derived from an
      `ai_constraints.mantle_requirements` entry (or the catalog), never from the source API.
- [ ] Every non-`mantle_*` row carries the `endpoint_assumption` sentence verbatim, naming the
      `design_blocks[].workload_id`(s) whose `model_id` equals the row's `source_model_id`.
- [ ] `regional_warnings` and `multi_model_warnings` are present (`[]` when clean).
- [ ] If `agentic_profile.is_agentic == true`: `agentic_design` is present with
      `migration_approach` matching `preferences.json`; a `harness` source whose origin resolves
      to Azure-fronted OpenAI sets `source_model_provider: "open_ai"`.
- [ ] All Bedrock model IDs are Active per `vendored/ai/ai-model-lifecycle.md` (a Legacy ID is
      used only if no Active alternative exists, with the EOL date noted).
- [ ] `"App Runner"` appears nowhere in the artifact.

## Status — target-only, no producer yet

This canonical contract has no producer in this change. The CURRENT emission contract for
Azure's `aws-design-ai.json` is still
`skills/azure-to-aws/references/shared/schema-design-aws-ai.md` — the single-scalar
`metadata.ai_source` shape (MUST equal `summary.ai_source` from the profile) that `design.md`,
`design-ai.md`, and `estimate-ai.md` read and assert today. `scripts/artifact-contracts.json`'s
`azure-to-aws` entry for `aws-design-ai.json` shadows the shared `json_schema` entry with that
file's `Shape` block for exactly this reason: Azure's actual runtime output has not changed.
GCP now has its own shadow entry mirroring Azure's: `scripts/artifact-contracts.json`'s
`gcp-to-aws` entry for `aws-design-ai.json` points at
`skills/gcp-to-aws/references/shared/schema-design-aws-ai.md`, which names GCP's current
single-scalar `metadata.ai_source` emission (the shape `design-ai.md` writes today) as the
emission contract, with this file as the target. GCP's actual runtime output has not changed
either.

This document (and its companion JSON Schema, `scripts/contracts/aws-design-ai.schema.json`)
is the TARGET contract — the many-valued `ai_sources[]`/`gateways[]` shape neither skill's
`design-ai.md` emits yet. Repointing either skill's `design-ai.md` to emit this shape is
deferred runtime-adoption work, named explicitly so a future PR does not silently assume
today's runtime output already satisfies this contract. `estimate-ai.md` and
`generate-artifacts-ai.md` are unchanged and still read today's artifact shape.
