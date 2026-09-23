---
_fragment: ai
_of_phase: design
_contributes:
  - aws-design-ai.json
---

# Design — AI Workloads (Bedrock)

> **Self-writing fragment.** Unlike `design-infra.md` (which contributes arrays to the
> assembler), this fragment is the SOLE writer of its own artifact, `aws-design-ai.json`
> — a separate file from `aws-design.json` (§19.10). It runs only when
> `ai-workload-profile.json` exists. See `design.md` for how it is composed into the phase.
> Do not "fix" this to contribute into `design-assemble.md`: the two design artifacts are
> independent by decision, matching gcp-to-aws so the estimate/generate AI ports stay a
> straight lift.

**Execute ALL steps in order. Do not skip or optimize.**

## Step 0: Load inputs

Read `$MIGRATION_DIR/ai-workload-profile.json`:

- `summary.ai_source` — `"azure_openai"`, `"openai"`, `"anthropic"`, `"both"`, `"other"`
- `models[]` — detected AI models with service, capabilities, evidence
- `integration` — SDK, frameworks, languages, gateway type, capability summary
- `infrastructure[]` — Azure AI resources related to AI (may be empty)
- `current_costs` — present only if billing or usage-API data was provided
- `workloads[]`, `agentic_profile`, `tool_manifest[]` (see `references/vendored/ai/` refs)

Read `$MIGRATION_DIR/preferences.json` → `ai_constraints` (if present). If absent, use
defaults (prefer managed Bedrock, no latency constraint, no budget cap).

**Load the source-specific design reference based on `ai_source`:**

- `"azure_openai"` or `"openai"` → load `references/vendored/ai/ai-openai-to-bedrock.md`
  **and** `references/shared/openai-on-bedrock.md` (the fact base: Bedrock model IDs, endpoint
  paths, region matrix, quotas). Azure OpenAI serves OpenAI models, so the source model is
  usually itself the target — the mapping guide's Tier 0 (same-model) path is the default, not
  a cross-family swap. `azure_openai` routes IDENTICALLY to `openai`; the distinct label is
  kept only for report wording and provenance (§19.9(b)).
- `"anthropic"` → load `references/vendored/ai/ai-anthropic-to-bedrock.md` (Anthropic SDK →
  Bedrock Converse client swap).
- `"both"` → load `references/vendored/ai/ai-openai-to-bedrock.md` and, if an Anthropic model
  is also present, `ai-anthropic-to-bedrock.md`.
- `"other"` or absent → load `references/design-refs/ai.md` (traditional-ML rubric — Azure AI
  Vision, Document Intelligence, Speech, Language, Translator, Azure ML custom models).

**Additional load, independent of `ai_source`:** if any `workloads[]` entry has `capability`
in {`document_extraction`, `image_analysis`, `speech_transcription`}, ALSO load
`references/design-refs/ai.md` — a workload's traditional-AI capability is evaluated
independently of the codebase's primary LLM provider.

**Missing-rubric guard.** If a reference this step must load is not on disk, HALT (write the
artifact with a `halt` object naming the missing file, then fail the gate) — the same guard as
`index.md` and `design-infra.md`. Do not map from your own knowledge.

## Step 0.5: Regional availability validation

Read `preferences.json` → `design_constraints.target_region` (default `us-east-1`). Call
`aws___get_regional_availability` (AWS MCP Server) for each candidate Bedrock model, and — if
`agentic_profile.is_agentic` — for `bedrock-agentcore`. Unavailable services go to
`regional_warnings[]` (do NOT block; flag and proceed with an alternative-region note). If the
call fails, use the static table in
`references/vendored/ai/ai-migration-guardrails.md` and set `metadata.regional_validation:
"fallback_static"`.

## Step 0.6: Agentic design routing

Skip if `agentic_profile` is absent. If `agentic_profile.is_agentic == true`:

1. Load `references/vendored/ai/ai-migration-guardrails.md` once.
2. Read `preferences.json` → `ai_constraints.agentic.migration_approach` and route:

| `migration_approach` | Action                                                                                                                                                                                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `"retarget"`         | Standard model-swap (Parts 1–6). Framework stays; only the model layer changes. Load `references/vendored/ai/ai-migration-guardrails.md` retarget notes.                                                                                         |
| `"harness"`          | Load `references/vendored/ai/design-ref-harness.md`. If absent, proceed model-layer only + a user note. Set `harness_config.source_model_provider` to `"open_ai"` for an `azure_openai`/`openai` source (§19.9(b)), `"anthropic"` for anthropic. |
| `"strands"`          | Load `references/vendored/ai/design-ref-agentic-to-agentcore.md`.                                                                                                                                                                                |
| `"undecided"`        | Treat as `"retarget"`; note it in the summary.                                                                                                                                                                                                   |

The agentic ref ADDS agent infrastructure on top of the model-layer design (Parts 1–6 still
run); it does not replace it.

## Step 0.7: Apply compliance constraints

Read `preferences.json` → `design_constraints.compliance`. Skip only when the value is
absent, `[]`, `["none"]`, or `["unknown"]` (record the caveat when `unknown`). Named
frameworks apply BEFORE Part 1 as hard filters:
`hipaa` → BAA-eligible Bedrock models + KMS-encrypted invocation logs; `fedramp` → GovCloud
region, re-run Step 0.5, a `regional_warnings[]` entry per unavailable model; `gdpr` → EU
region with geographic `eu.` inference profiles (`global.` forbidden); `pci`/`soc2`/`ccpa` →
CloudTrail on Bedrock API calls + the Part 5 logging lines. Every constraint that changed a
choice adds a `regional_warnings[]` entry or a Part 5 line, and the summary names the regime.

## Part 1: Bedrock model selection

**Iterate per `workloads[]` entry** (read from `preferences.json` — Clarify may have edited or
confirmed rows; fall back to the profile's `workloads[]` only if preferences has none). For
each workload:

1. Use `capability` to select the target class:

   | Capability                                          | Target                                                               |
   | --------------------------------------------------- | -------------------------------------------------------------------- |
   | `text_generation` / `structured_output` / `unknown` | Bedrock text/reasoning — apply the override hierarchy below          |
   | `image_generation`                                  | Stability AI (Core / Ultra)                                          |
   | `embedding`                                         | Amazon Titan Embed Text v2                                           |
   | `speech_to_text`                                    | Amazon Transcribe                                                    |
   | `text_to_speech`                                    | Amazon Polly                                                         |
   | `document_extraction`                               | `target_aws_service: "textract"` — see `ai.md` (NOT a Bedrock model) |
   | `image_analysis`                                    | `target_aws_service: "rekognition"` — see `ai.md`                    |
   | `speech_transcription`                              | `target_aws_service: "transcribe"` — see `ai.md`                     |

   For the three traditional-AI capabilities: leave `target_bedrock_model: null`, set
   `target_aws_service`, skip the override hierarchy, and set `honest_assessment:
   "not_applicable"`.

2. For text/reasoning: apply the override hierarchy — Q17 special features (hard override) >
   **same-model availability** > Q16 priority > Q18/Q21 volume & latency > source baseline.
   Same-model availability outranks a `balanced`/unset priority: if the source model is on
   Bedrock and the region carries it, keep it (`model_change: false`).

3. Emit one `design_blocks[]` row per workload (see `references/shared/schema-design-aws-ai.md`
   for the exact shape and the `target_bedrock_model` XOR `target_aws_service` rule). Preserve
   input order. Set `confidence_warning` when `capability_confidence == "low"`.

**Stay-or-migrate (check same-model FIRST):** source model on Bedrock AND region carries it →
`strong_migrate`, `model_change: false` (the rationale is risk + governance, not cost; Bedrock
in-region runs ~10% above OpenAI standard — report a modest increase, not parity, and never
claim free). Bedrock cheaper → `strong_migrate`. Within 25% and priority≠cost →
`moderate_migrate`. Source >25% cheaper and priority=cost → `weak_migrate`/`recommend_stay`.
Overall = weakest across models. `recommend_stay` REQUIRES a non-cost reason in
`honest_assessment_reason` when the source provider's models are on Bedrock.

**Quota risk** (per `references/vendored/ai/bedrock-quotas.md`): high/very_high volume →
`quota_risk: "high"` + a pre-migration quota-increase flag; medium + Claude (5× burndown) →
`"medium"`; else `"low"`. Record on each `bedrock_models[]` entry.

## Part 1B: Volume-based strategy

If `ai_token_volume == "high"`, emit `tiered_strategy` (Tier1 60% cheap, Tier2 30% mid, Tier3
10% flagship) and note Bedrock Intelligent Prompt Routing when the selected models are one
family. Null otherwise. Cross-family routing (and the Mantle-vs-Converse client split for
proprietary GPT models) still needs app-level/LiteLLM routing — "all on Bedrock" does not
unify the two client surfaces.

## Part 1C: Multi-model coordination warnings

If `models[]` > 1, emit `multi_model_warnings[]` for: embeddings+generation (re-embed/re-index,
dimension check), price-tier cascade pairs, >3 models (tiered migration), text+image (separate
eval), and speech models (Transcribe/Polly are separate services, not Bedrock swaps). Types:
`embeddings_reindex | cascade_pair | multi_model_tiered | image_separate | speech_separate`.

## Part 2: Feature parity

For each `true` capability in `integration.capabilities_summary`, record `capability_mapping`
parity (`full|partial|none`) against Bedrock (Converse, streaming, tool use, Titan embeddings,
multimodal, Batch Inference, Knowledge Bases, AgentCore). Record `capability_gaps[]` for
Partial/None.

## Part 3: Integration pattern → effort

Map `integration.pattern`: `direct_sdk` (Azure OpenAI/OpenAI, model on Bedrock, region carries
it) → Mantle Responses API, minimal; `direct_sdk` → Bedrock SDK/Converse, medium; `framework`
→ LangChain/LlamaIndex + Bedrock, low; `rest_api` → Bedrock REST, medium; `mixed` → per-model.

## Part 4: Infrastructure mapping

Map Azure AI infrastructure to AWS:

| Azure resource                                                 | AWS equivalent                                                             |
| -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `Microsoft.CognitiveServices/accounts` (`kind: OpenAI`)        | Bedrock model access (serverless, no infra)                                |
| `Microsoft.CognitiveServices/accounts/deployments`             | config source — the deployed model name is the mapping input, not a target |
| `Microsoft.MachineLearningServices/workspaces` online endpoint | SageMaker Endpoint                                                         |
| `Microsoft.MachineLearningServices` batch endpoint / job       | SageMaker Batch Transform / training                                       |
| `Microsoft.Search/searchServices` (vector index for RAG)       | OpenSearch Serverless or Bedrock Knowledge Base                            |
| managed identity with AI data-plane role                       | IAM role with Bedrock/AI-service permissions (`inferred`)                  |

## Part 5: Code migration plan

Generate before/after examples per detected `integration.pattern` and `ai_source`. For an
`azure_openai`/`openai` source with the model on Bedrock, the **Mantle Responses API** is the
primary path (`migration_path: "mantle_openai_responses"`, `model_change: false`): the app
keeps the OpenAI SDK; only the base URL (`.../openai/v1/responses`), credential (a Bedrock API
key/token provider), model ID, and IAM (`bedrock-mantle:*`) change. Read
`references/shared/openai-on-bedrock.md` for exact values. If the source uses Chat Completions,
plan a reshape to `responses.create`. No Converse fallback exists for proprietary GPT models
(mantle-only, in-region only): needing Guardrails/Knowledge Bases/logging/an unsupported region
forces a `converse` path with `model_change: true` to a Bedrock-native model (or `gpt-oss`).
Anthropic-SDK sources → boto3 Converse client swap. Record `code_migration.openrouter_path`
when a router was detected (`same_model_mantle|direct|litellm|keep_openrouter`).

## Part 6: Write output

Write `aws-design-ai.json` to `$MIGRATION_DIR/` per `references/shared/schema-design-aws-ai.md`
(the authoritative shape). `metadata.ai_source` MUST equal the profile's `summary.ai_source`.
`design_blocks[]` in input order; every row obeys the `target_bedrock_model` XOR
`target_aws_service` rule; `regional_warnings[]` and `multi_model_warnings[]` always present
(`[]` when clean); `agentic_design` only when agentic.

## Completion gate (fail closed)

Before returning control to `design.md`, require `aws-design-ai.json` to exist and pass the
Validation Checklist in `references/shared/schema-design-aws-ai.md`. If it fails: STOP and
output "design-ai did not produce a valid aws-design-ai.json; do not complete Phase 3."

> **`_assert` has no teeth.** This gate is prose the model both produces and evaluates — CI
> binds it but never runs it. Judge correctness by the Python oracle for the AI fixture (step
> 5) and by what a fresh-context run gets wrong, never by "the gate passed."

## Present summary (≤ 25 lines)

Overall honest assessment; the source→Bedrock model comparison (price + assessment per model);
integration pattern and complexity; capability gaps; and — prominently, if `weak_migrate`/
`recommend_stay` — the reason. Name any compliance regime that shaped the design.

## Status — build step 2 (AI design route)

The design half of the AI capability. Its consumers — `estimate-ai.md` (reads
`aws-design-ai.json` → `estimation-ai.json`) and `generate-artifacts-ai.md` — land in step 3.
`ai-workload-profile.json` (this fragment's input) is produced by `discover-app-code.md`, which
lands in step 4; until then the AI route is reachable only for an estate whose Cognitive
Services / Azure ML resources were detected from IaC.
