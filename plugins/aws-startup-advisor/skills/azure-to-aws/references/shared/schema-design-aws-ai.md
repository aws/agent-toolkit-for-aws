# Schema — aws-design-ai.json

> **Why this file exists.** `aws-design.json` had no schema once and a capability run
> reverse-engineered its shape from postconditions, inventing key names the golden did not
> share (§13.3a). The AI design artifact is the same risk one layer over: `design-ai.md`
> produces it, `estimate-ai.md` and `generate-artifacts-ai.md` consume it, and a prose-only
> contract drifts between the three by construction. This file is the single written contract
> for `aws-design-ai.json`. It is the AI analogue of `schema-design-aws.md`, and it is
> deliberately kept parallel to gcp-to-aws's `aws-design-ai.json` shape so the estimate and
> generate ports stay straight (§19.10).

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
    "ai_source": "azure_openai", // MUST equal summary.ai_source from the profile
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
  `migration_path` (see below), `quota_risk` (`low|medium|high`). Traditional-AI capabilities
  do NOT appear here — they are `design_blocks[]` rows with `target_aws_service`.
- **`capability_mapping`** — per capability that is `true` in the profile's
  `integration.capabilities_summary`: `{ parity: "full|partial|none", notes }`.
- **`code_migration`** — `primary_pattern` (matches profile `integration.pattern`),
  `framework`, `files_to_modify[]`, `dependency_changes`, and — when the source is Azure
  OpenAI / OpenAI — `openrouter_path` when a router was detected
  (`same_model_mantle|direct|litellm|keep_openrouter`).
- **`infrastructure[]`** — Azure AI infra resource → AWS equivalent, with confidence.
- **`services_to_migrate[]`** — Azure AI service → AWS service, effort, notes.

## migration_path vocabulary

`mantle_openai_responses` (Azure OpenAI / OpenAI source, model on Bedrock, region carries it —
keep the SDK, `model_change: false`) · `converse` (Bedrock-native Converse/`bedrock-runtime`;
set `model_change: true` when a proprietary GPT model must move off mantle for Guardrails /
Knowledge Bases / logging / an unsupported region) · `gpt-oss` (OpenAI-lineage model on the
Bedrock-native runtime) · `direct` (framework-agnostic Bedrock SDK swap). A proprietary
`openai.gpt-*` model ID is NEVER paired with a `converse`/`bedrock-runtime` path — those models
are mantle-only.

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
`migration_approach == "harness"` carry `harness_config` (with `source_model_provider`, which
is `"open_ai"` for an `azure_openai` source — see §19.9(b)); when `"strands"` carry the
AgentCore Runtime config from `vendored/ai/design-ref-agentic-to-agentcore.md`.

## halt

Present ONLY when the AI design is failing its gate. `{ reason, blocking[] }` where each
`blocking[]` entry is `{ kind, identifier, why, action }`. The AI design halts when a routed
rubric file (`ai.md`, `ai-azure-openai-to-bedrock.md`, or a `vendored/ai/*` ref) named by
`index.md` is not on disk — the same missing-rubric guard the infra design uses.

## Validation Checklist

- [ ] `metadata.ai_source` equals `summary.ai_source` from `ai-workload-profile.json`.
- [ ] Every `workloads[]` entry (or `models[]` when workloads is empty) has exactly one
      `design_blocks[]` row, in input order.
- [ ] Every `design_blocks[]` row has exactly one of `target_bedrock_model` /
      `target_aws_service` non-null (XOR).
- [ ] Every traditional-AI row (`document_extraction`/`image_analysis`/`speech_transcription`)
      has `target_bedrock_model: null`, a non-null `target_aws_service`, and (in
      `ai_architecture`) is not counted in `bedrock_models[]`.
- [ ] Every `bedrock_models[]` entry has `source_provider_price`, `bedrock_price`,
      `price_comparison`.
- [ ] `honest_assessment` overall is the weakest across `bedrock_models[]`; if
      `recommend_stay`, `honest_assessment_reason` names a non-cost blocker.
- [ ] No `bedrock_models[]` entry pairs a proprietary `openai.gpt-*` model ID with a
      `converse`/`bedrock-runtime` migration path (mantle-only).
- [ ] If `ai_source` is `azure_openai` or `openai`: every source model that is available on
      Bedrock and carried by the target region maps to ITSELF with `model_change: false` — not
      to a Claude/Nova substitute.
- [ ] `regional_warnings` and `multi_model_warnings` are present (`[]` when clean).
- [ ] If `agentic_profile.is_agentic == true`: `agentic_design` is present with
      `migration_approach` matching `preferences.json`; a `harness` source with an
      `azure_openai` origin sets `source_model_provider: "open_ai"`.
- [ ] All Bedrock model IDs are Active per `vendored/ai/ai-model-lifecycle.md` (a Legacy ID is
      used only if no Active alternative exists, with the EOL date noted).
- [ ] `"App Runner"` appears nowhere in the artifact.

## Status — build step 2 (AI design route)

Written alongside `design-ai.md`. The estimate/generate AI consumers (`estimation-ai.json`,
`generation-ai.json`) land in step 3 and read this contract.
