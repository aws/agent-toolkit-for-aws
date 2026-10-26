# Design Phase: AI Workloads (Bedrock)

> Loaded by `design.md` when `ai-workload-profile.json` exists.
> **Input gate:** before reading any AI profile field, run `bma-runtime.py validate-profile --profile $AI_PROFILE --sidecar $AI_SIDECAR` (the sidecar is required when present). `$AI_PROFILE` is `$MIGRATION_DIR/ai-workload-profile.json` in direct mode and `$MIGRATION_DIR/.bma-input/ai-workload-profile.json` in delegated mode (`$AI_SIDECAR` is `$AI_SIDECAR` in direct mode and `$MIGRATION_DIR/.bma-input/ai-workload-sidecar.json` in delegated mode). Exit 1 stops this phase. Legacy-shaped input is rejected by name (`BmaLegacyProfileRejected`).

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Load Inputs

Read `$AI_PROFILE` (#415) and `$AI_SIDECAR` after the input gate passes:

- `ai_sources[]` — provider, `source_service`, `model_families`, `model_evidence`, and `models` for each AI source
- `gateways[]` — gateway `product`, `type`, `upstream_evidence`, and `upstreams`
- sidecar `integration_context` — SDK, frameworks, languages, `pattern`, and `capabilities_summary` (present when discovery recorded them)
- sidecar `observed_costs` — present only if usage API or billing data was provided (`source` field records which)
- sidecar `infrastructure[]` — source AI infrastructure resources (Terraform, delegated GCP runs only; may be absent or empty)
- sidecar `model_context[]` — per-model `capabilities_used` and `usage_context`, matched to `ai_sources[].models` by `model_id`
- sidecar `workloads[]`, `agentic_profile`, and `tool_manifest`

**Derived label (output only):** `metadata.ai_source` in `aws-design-ai.json` is computed from the provider set: one `google` provider → `"gemini"`, one `openai` → `"openai"`, one `anthropic` → `"anthropic"`, more than one provider → `"both"`, no provider → `"other"`. Routing never reads this label. It reads the provider set.

Read `$MIGRATION_DIR/preferences.json` → `ai_constraints` (if present). If absent: use defaults (prefer managed Bedrock, no latency constraint, no budget cap).

**Region selection for AI workloads:** Direct mode uses compliance → one explicit supported/primary application region → Q4 latency preference → `us-east-1`; it never infers a source cloud. Delegated GCP mode preserves compliance → captured GCP region → Q4 → `us-east-1`. When a region was derived rather than explicitly chosen, verify the selected Bedrock models there with `aws___get_regional_availability` (AWS MCP Server). If unavailable, prefer the geographically closest supported AWS region.

**Load source-specific design reference based on the provider set in `ai_sources[]`** (one entry per `(provider, source_service)` pair):

- `google` (`source_service` `vertex_ai`) → load `references/design-refs/ai-gemini-to-bedrock.md` and the canonical provider guide `references/vendored/ai/ai-gemini-to-bedrock.md`
- `openai` (`source_service` `openai_api`) → load `references/vendored/ai/ai-openai-to-bedrock.md` **and**
  `references/shared/openai-on-bedrock.md` (the fact base: model IDs, endpoint paths, region matrix, quotas,
  caching). OpenAI's proprietary GPT models run on Bedrock, so the source model is often itself the target — the
  mapping guide's Tier 0 path is the default, not a cross-family swap.
- `anthropic` (`source_service` `anthropic_api`) → load `references/vendored/ai/ai-anthropic-to-bedrock.md` (Anthropic SDK → Bedrock Converse API client swap; do NOT use ai-openai-to-bedrock.md for Anthropic SDK users)
- More than one provider → load every reference matching a provider that has at least one model with `model_evidence: "observed"`. Each provider is routed on its own, and the same model name through two services is routed per service.
- No provider with observed models, or only traditional-ML evidence → load `references/design-refs/ai.md` (traditional ML rubric — Vision API, Speech API, Document AI, custom models only; do NOT use for Anthropic SDK users)

**Additional load, independent of the provider routing above:** If `gateways[]` contains an OpenRouter gateway (`type: "llm_router"`), load `references/vendored/ai/ai-openrouter-to-bedrock.md` and preserve every upstream provider/family/exact-model association. If any entry in `workloads[]` (from `preferences.json`, falling back to `ai-workload-profile.json`) has `capability` equal to `document_extraction`, `image_analysis`, or `speech_transcription`, ALSO load `references/design-refs/ai.md` — even when a generative provider already selected a different ref above. A workload's non-generative capability is evaluated independently of the codebase's primary LLM provider; e.g. an `ai_source: "openai"` codebase that also calls `documentai.process_document` needs both `ai-openai-to-bedrock.md` (for its GPT workload) and `ai.md` (for its Document AI workload).

---

## Step 0.5: Regional Availability Validation

Read target region from `preferences.json` → `design_constraints.target_region` (default: `us-east-1`).

Call `aws___get_regional_availability` from the AWS MCP Server for:

1. Each Bedrock model ID being considered (from the loaded model mapping tables)
2. If `agentic_profile.is_agentic == true`: check `bedrock-agentcore` (Runtime)
3. If `agentic_profile.is_agentic == true` AND `ai_constraints.agentic.migration_approach == "harness"`: check `bedrock-agentcore` harness capability

**If any recommended service is unavailable in target region:**

- Add to `regional_warnings[]` in output: `{"service": "...", "target_region": "...", "nearest_available": "...", "impact": "..."}`
- Note in user summary with alternative region suggestion
- Do NOT block the design — proceed with the recommendation and flag the constraint

**If MCP call fails:** Use the static table in `references/vendored/ai/ai-migration-guardrails.md` as fallback. Add `"regional_validation": "fallback_static"` to output metadata.

---

## Step 0.6: Agentic Design Routing

**Skip this step if `agentic_profile` is absent from `ai-workload-sidecar.json`.**

If `agentic_profile.is_agentic == true`:

1. Load `references/vendored/ai/ai-migration-guardrails.md` (shared warnings — load once, do not reload in sub-files)
2. Read `preferences.json` → `ai_constraints.agentic.migration_approach`
3. Route based on approach:

| `migration_approach` | Action                                                                                                                                                                                                                                                                                                                                                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"retarget"`         | Continue with standard model-swap design below (Parts 1–6). The existing framework stays; only the model layer changes. Load `references/shared/retarget-gotchas.md` for framework-specific migration pitfalls to include in the code migration plan (Part 5).                                                                                            |
| `"harness"`          | Load `references/vendored/ai/design-ref-harness.md`. If file does not exist: continue with standard model-swap design, add note to user summary: "AgentCore Harness design reference not yet available. Proceeding with model-layer migration only. For Harness guidance, see https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html" |
| `"strands"`          | Load `references/vendored/ai/design-ref-agentic-to-agentcore.md`.                                                                                                                                                                                                                                                                                         |
| `"undecided"`        | Treat as `"retarget"` (safest default). Note in user summary: "No migration approach selected — defaulting to retarget (keep framework, swap model layer). Re-run Clarify to select a different approach."                                                                                                                                                |

**Regardless of approach:** Continue with Parts 1–6 below for model selection and mapping. The agentic design ref (Harness/Strands) adds agent infrastructure on top of the model-layer design — it does not replace it.

---

## Step 0.7: Apply Compliance Constraints

Read `preferences.json` → `design_constraints.compliance` (from full-flow Q2 or AI-only Q1.5). **Skip this step only when the value is `none`, `unknown`, or absent** (`unknown` = defaulted, never user-confirmed — behaves like `none` for model/region selection but the report caveat is REQUIRED; absent = pre-Q1.5 preferences; treat as `none` with the report caveat intact). Otherwise, apply BEFORE Part 1 model selection — these are hard filters, not preferences:

| Compliance value | Constraint applied in this design                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hipaa`          | Candidate models restricted to **BAA-eligible Bedrock models** — verify eligibility per model via `aws___search_documentation` (AWS MCP Server) before shortlisting. Add to the code migration plan (Part 5): Bedrock invocation logging keeps ORIGINAL content in CloudWatch (Guardrails PII masking does not apply to logs) — require KMS encryption + restricted IAM on the log group. Prefer us-east-1/us-west-2.                                                   |
| `fedramp`        | Target region forced to **GovCloud** (us-gov-east-1/us-gov-west-1); re-run Step 0.5 regional validation against GovCloud — the model catalog is materially smaller, and a `regional_warnings[]` entry is REQUIRED for every candidate model not available there.                                                                                                                                                                                                        |
| `gdpr`           | Target region restricted to EU (eu-west-1, eu-central-1); model IDs must use **geographic `eu.` inference profiles** — `global.` profiles route outside the EU boundary and are forbidden. Document source-to-AWS cross-border transfer only when source evidence identifies one; delegated GCP mode retains the GCP-EU → AWS-EU note. Exclude any candidate with no `eu.` Geo profile, including Fable 5 / 5.1 and Mythos. Fable 5's in-region access is limited to `bedrock-mantle` in us-east-1; both use `us.` / `global.` profiles on `bedrock-runtime`.     |
| `pci`            | Part 5 plan must include: no cardholder data in prompts without tokenization; CloudTrail on Bedrock API calls; scoped IAM (no `bedrock:*`).                                                                                                                                                                                                                                                                                                                             |
| `soc2` / `ccpa`  | Part 5 plan must include CloudTrail audit logging; CCPA additionally: prompt/completion retention policy + deletion workflow for logged content. Models whose Status is `restricted` with an `aws_review` or `provider_data_share` retention opt-in (Fable / Mythos) keep prompts outside the customer's deletion control — up to 30 days for AWS review, or shared with the provider — so exclude them under CCPA unless the plan documents that retention explicitly. |

Record what was applied: every constraint that changed a model choice or region adds a `regional_warnings[]` entry (existing shape) or a Part 5 plan line naming the compliance value that forced it, and the Present Summary section MUST state which compliance regime(s) shaped the design. A design that ignores a declared compliance value is a validation failure (see Validation Checklist).

---

## Part 1: Bedrock Model Selection

**New-target eligibility — before every selection or same-model shortcut, including the
per-model fallback:** apply `references/vendored/ai/bedrock-pricing-cache.md`'s target policy and the
model lifecycle restrictions first. Active availability alone does not make a model eligible.
For an Opus 4.8 source, follow the Opus 5.5 mapping in
`references/vendored/ai/ai-anthropic-to-bedrock.md`, subject to region, compliance and feature
constraints; never retain Opus 4.8 as a new target or automatic fallback. If no eligible
target satisfies those constraints, report the block instead. Preserve source model IDs and
historical pricing, and retain the explicitly accepted, verified Opus 4.6 Batch alternative.
Derive `model_change` from the final source/target identities: Opus 4.8 → 5.5 requires
`model_change: true`; an eligible exact same-model selection remains false.

**Restricted models — applies whichever guide Step 0 loaded and whatever the compliance value:** a row whose `Status` in `references/vendored/ai/bedrock-pricing-cache.md` is `restricted (…)` (Covered Models such as Claude Fable 5 / 5.1, gated previews such as Claude Mythos) is never `recommended_model` or `backup_model` and never a default in any mapping guide. Offer one only when the user explicitly asks for a frontier model, and state its data-retention opt-in and any endpoint-specific regional or CRIS-only restrictions in the same sentence.

**Multi-workload iteration (when `workloads[]` is present):**

If `preferences.json` contains a non-empty `workloads[]` array (written by Clarify after user confirmation), iterate per workload instead of per model. **Design MUST read workloads from `preferences.json` (not `ai-workload-profile.json`)** because Clarify may have edited, dropped, or re-confirmed rows.

Fallback: if `preferences.json` has no `workloads[]` field but `ai-workload-profile.json` does, use the profile's `workloads[]` directly (no user edits were made).

For each `workloads[]` entry:

1. **Use the workload's `capability` to select the Bedrock target class:**

   | Capability             | Target Class                                                      | Default Model / Service                                            |
   | ---------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------ |
   | `text_generation`      | Text/reasoning                                                    | Apply override hierarchy below                                     |
   | `structured_output`    | Text/reasoning (same models support structured output)            | Apply override hierarchy below                                     |
   | `image_generation`     | Image generation                                                  | Stability AI (Core / Ultra)                                        |
   | `embedding`            | Embedding                                                         | Amazon Titan Embed Text v2                                         |
   | `speech_to_text`       | Speech-to-text                                                    | Amazon Transcribe                                                  |
   | `text_to_speech`       | Text-to-speech                                                    | Amazon Polly                                                       |
   | `document_extraction`  | Traditional AI (non-Bedrock) — see `references/design-refs/ai.md` | AWS Textract (variant per detected GCP Document AI processor type) |
   | `image_analysis`       | Traditional AI (non-Bedrock) — see `references/design-refs/ai.md` | AWS Rekognition                                                    |
   | `speech_transcription` | Traditional AI (non-Bedrock) — see `references/design-refs/ai.md` | AWS Transcribe                                                     |
   | `unknown`              | Text/reasoning (default)                                          | Apply override hierarchy below                                     |

   **`document_extraction`, `image_analysis`, `speech_transcription` are not Bedrock models.** For these three capabilities:
   - Do NOT set `target_bedrock_model` — leave it `null`.
   - Set `target_aws_service` instead (e.g., `"textract"`, `"rekognition"`, `"transcribe"`) using the mapping from `references/design-refs/ai.md`.
   - Skip the override hierarchy in step 2 below — Q16–Q19 preferences (quality/speed/cost model tuning) don't apply to these services; there is no model tier to select.
   - `honest_assessment` (Part 1 continued, below) does not apply — these are feature/service swaps, not a cost-driven model migration decision. Set `honest_assessment: "not_applicable"` for these workloads in the output.

2. **For text/reasoning capabilities:** Apply the override hierarchy from `ai_constraints`:
   - Q17 special features (hard override within eligible targets) > **same-model availability among eligible targets** > Q16 priority > Q18/Q21 volume and latency >
     source model baseline
   - **Eligible same-model availability outranks Q16 priority.** If the source model is eligible as a new target, available on Bedrock and the target
     region carries it, keep it — a `balanced` or unset priority must not silently move the workload to a different
     model family. Within the eligible pool, only a Q17 hard feature override (a capability the source model cannot serve) beats it. An
     explicit `ai_priority = "cost"` does not override it either; it adds a cost alternative alongside the same-model
     recommendation (see the mapping guide's Tier 2).
   - This ensures single-workload sophistication is preserved per workload

3. **Emit one `design_block` per workload** in `aws-design-ai.json`:

   ```json
   "design_blocks": [
     {
       "workload_id": "wl_3a1f2c",
       "model_id": "gemini-2.5-flash",
       "target_bedrock_model": "amazon.nova-lite-v1:0",
       "target_aws_service": null,
       "capability": "text_generation",
       "capability_confidence": "medium",
       "rationale": "text_generation + medium confidence + balanced priority → Nova Lite",
       "confidence_warning": null
     },
     {
       "workload_id": "wl_8b4e91",
       "model_id": "documentai.process_document",
       "target_bedrock_model": null,
       "target_aws_service": "textract",
       "capability": "document_extraction",
       "capability_confidence": "high",
       "rationale": "document_extraction (GCP Document AI) → AWS Textract per references/design-refs/ai.md",
       "confidence_warning": null
     }
   ]
   ```

   **Field contract addition:** `target_aws_service` is `null` for all Bedrock-model capabilities (`text_generation`, `structured_output`, `image_generation`, `embedding`, `speech_to_text`, `text_to_speech`, `unknown`) and is one of `"textract"`, `"rekognition"`, `"transcribe"` for the three traditional-AI capabilities. `target_bedrock_model` and `target_aws_service` are mutually exclusive — exactly one is non-null per `design_block`.

4. **Confidence warning:** Set `confidence_warning` to a non-null string (identifying the workload and noting manual review required) when `capability_confidence == "low"`. Null for `high` and `medium`.

5. **Preserve input order:** `design_blocks[]` order matches `workloads[]` order.

6. **Empty workloads:** If `workloads[]` is empty, emit `aws-design-ai.json` with `"design_blocks": []` and proceed with the existing `ai_sources[].models` path below as fallback.

**Fallback (no `workloads[]` or single entry):** If `workloads[]` is absent or has exactly one entry, fall through to the existing per-model logic below (backward compatible).

---

For each model in `ai_sources[].models`, select the best-fit Bedrock model using the loaded design reference mapping tables. Do NOT use a hardcoded mapping — the design-ref files contain tier-organized tables with pricing and competitive analysis.

Treat model mapping as compatibility-guided, not 1:1 parity. Before cutover, require validation of prompts, tool-calling behavior, and eval metrics for the selected Bedrock model.

**If `ai_sources[].models` is empty:** Skip per-model rows; output a short **placeholder strategy** (one representative Bedrock model family per provider rubric) and dependency on Clarify answers — do not fabricate `ai_sources[].models` entries.

**Apply user preference overrides from `ai_constraints`:**

| Preference                | Override                                                                                                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ai_priority = "cost"`    | Prefer "Winner" column; flag if source is cheaper                                                                                                                                |
| `ai_priority = "quality"` | Prefer Claude Sonnet/Opus regardless of cost                                                                                                                                     |
| `ai_priority = "speed"`   | Prefer Claude Sonnet (fastest integration)                                                                                                                                       |
| `ai_latency = "critical"` | Prefer smaller/faster models (Haiku, Nova Lite)                                                                                                                                  |
| `ai_latency = "flexible"` | Any model; flag Batch API for 50% savings — but only for confirmed-batch models (skip the discount for models whose batch cells are `_unverified_` in `references/vendored/ai/bedrock-pricing-cache.md`) |

**Stay-or-migrate assessment per model:**

Check the same-model case FIRST after eligibility filtering and final target selection;
otherwise use the cost-comparison cases below with `model_change` reflecting the selected target:

- **Selected target is the same eligible source model**, available on Bedrock AND carried by the target region →
  `"strong_migrate"`. Set `model_change: false`. The rationale is risk (no behavior delta) plus AWS commitments,
  governance, and residency — **not** an assumed cost saving. Price the actual model and inference option using
  the model-specific rules below; same identity does not imply cost parity or a universal premium.

  If source pricing is unavailable, retain that unavailable comparison. Derive the
  difference from verified source and selected target inference/context-tier rates.
- Source model on Bedrock but the target region does not carry it → treat as no-same-model below, and record the
  region as the cause in `regional_warnings[]`. Do not report this as a model-quality judgment.
- Bedrock cheaper → `"strong_migrate"`
- Bedrock within 25% of source AND priority != cost → `"moderate_migrate"`
- Source > 25% cheaper AND priority = cost → `"weak_migrate"` or `"recommend_stay"`

**Model-specific same-model pricing:** for OpenAI GPT targets, read
`references/shared/openai-on-bedrock.md`: verified In-Region/Geo options use the
data-residency-tier premium, while supported Global CRIS uses standard-rate parity.
Report the actual option; do not downgrade solely for the modest verified premium.
**GPT-5.6/GPT-6 only:** above 272K context, apply 2.0x input and 1.5x output rates only when
the selected model and inference option support that tier; the resulting gap may change
the assessment. GPT-5.5/5.4 have no 1M tier. **Opus 5.5:** use the selected region/profile's
flat rates from `references/vendored/ai/bedrock-pricing-cache.md` throughout the full 1M context;
do not apply the GPT multiplier. Verify other models' tiers individually.

Overall assessment = weakest across all models. If any `"recommend_stay"`, flag prominently.

**`recommend_stay` requires a non-cost reason when the source provider's models are on Bedrock.** For an OpenAI
source, a ~10% premium alone is usually too small to justify staying, but a long-context workload priced at the 1M
tier can be. Beyond cost, these justify `recommend_stay`: a fixed
region with no suitable model, Realtime API dependence, image/speech/embedding capabilities that map to other AWS
services rather than to an OpenAI model, Assistants API with file search / vector stores / code interpreter, or a
confirmed unsupported API surface. Record which one in `honest_assessment_reason`.

**Model comparison table** (include in output and user summary): Model, Provider, Max Context, Input/Output Price per 1M, Price Comparison, Streaming, Function Calling, Assessment.

**Quota risk assessment** (per `references/vendored/ai/bedrock-quotas.md`):

After selecting models, assess quota risk based on `ai_token_volume` from `preferences.json`:

| `ai_token_volume`         | Selected Model Family              | `quota_risk` | Action                                                                            |
| ------------------------- | ---------------------------------- | ------------ | --------------------------------------------------------------------------------- |
| `"high"` or `"very_high"` | Any                                | `"high"`     | Flag: "Request Bedrock quota increase before migration (allow 1–5 business days)" |
| `"medium"`                | Claude (5× burndown)               | `"medium"`   | Flag: "Monitor TPM usage; quota increase may be needed at peak"                   |
| `"medium"`                | Astra runtime (10× output burndown) | `"medium"` | Flag: "Verify input TPM + 10 × output TPM against the selected CRIS quota" |
| `"medium"`                | Verified 1× models (e.g. Nova / Llama) | `"low"` | No action |
| `"medium"`                | Unverified model/endpoint quota | `"medium"` | Flag: "Verify quota dimensions before estimating throughput" |
| `"low"`                   | Any                                | `"low"`      | No action                                                                         |

Include `quota_risk` in `aws-design-ai.json` → `ai_architecture` alongside `honest_assessment`.

---

## Part 1B: Volume-Based Strategy

If `ai_token_volume` is `"high"`, generate a `tiered_strategy`:

| Tier | Traffic | Model Selection              | Use Cases                                            |
| ---- | ------- | ---------------------------- | ---------------------------------------------------- |
| 1    | 60%     | Nova Micro or Llama 4 Scout  | Classification, extraction, short answers, routing   |
| 2    | 30%     | Llama 4 Maverick or Nova Pro | Summarization, moderate generation, Q&A with context |
| 3    | 10%     | Claude Sonnet 5.5              | Reasoning, long-form, agentic tasks, tool use        |

Set `tiered_strategy: null` for low/medium volume.

**Intelligent Prompt Routing — automated alternative to manual tiering:**
If `ai_token_volume` is `"high"` AND the selected models are within the same family
(e.g., Claude Haiku + Claude Sonnet, or Nova Lite + Nova Pro), note Bedrock Intelligent
Prompt Routing as an option. It automatically routes each request to the cheapest model
that can handle it at adequate quality — the AWS-native automation of the tiered strategy above.

> Intelligent Prompt Routing only routes within a single model family. It does NOT replace
> cross-family routing (e.g., Claude ↔ GPT-5.6). Note that even though both families are now on
> Bedrock, Claude is reached via `bedrock-runtime`/Converse and the proprietary GPT models via
> `bedrock-mantle`/Responses — two different client surfaces. A router spanning them still needs
> app-level or LiteLLM routing with two client paths; being "all on Bedrock" does not unify them.
> One-line caveat: adds a routing-prediction latency hop; verify model support at
> docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html before recommending.

---

## Part 1C: Multi-Model Coordination Warnings

If `ai_sources[].models` contains more than one model, check for coordination patterns and generate warnings. These help the user understand that migrating multiple models requires coordinated testing, not independent swaps.

**Check and warn:**

1. **Embeddings + generation model detected** — If the detected models include both an embeddings workload (a `workloads[]` entry with `capability: "embedding"`, or a sidecar `model_context[]` entry whose `capabilities_used` includes `"embeddings"`) AND a text generation model:
   > ⚠️ "Migrating the embedding model (e.g., text-embedding-3-small → Titan Embeddings v2) requires re-embedding all documents in your vector store. Plan for re-indexing time and temporary storage. Test retrieval quality with the new embeddings before switching generation model."
   > ⚠️ "Verify vector index dimension compatibility before cutover. OpenAI text-embedding-3-small outputs 1536 dimensions; Titan Embeddings v2 is configurable (256, 512, or 1024). A mismatch will cause insert failures at the vector store layer — your index must be rebuilt at the target dimension before any data is written."

2. **Models at different price tiers** — If `ai_sources[].models` contains both a mini/nano/lite model AND a flagship model (infer from model_id naming: `*-mini`, `*-nano`, `*-lite` vs flagship):
   > ⚠️ "These models appear to work as a cascade or routing pattern (cheap model for classification/filtering, expensive model for generation). Test the Bedrock replacement pair together — validate that the cheaper model's classification accuracy is preserved with its Bedrock equivalent before testing the expensive model."

3. **More than 3 models** — If `ai_sources[].models` count > 3:
   > ⚠️ "Multiple models detected ([count]). Recommend a tiered migration strategy: migrate and validate one model at a time, starting with the lowest-risk (highest-volume, simplest task). See Part 1B for tiered routing recommendations."

4. **Text generation + image generation** — If `workloads[]` contains both text generation AND image generation capabilities:
   > ⚠️ "Image generation migration (e.g., DALL-E/gpt-image → Stability AI) requires separate evaluation. Image quality is subjective — plan for human evaluation alongside automated metrics. Default to Stable Image Core (cost-first) or Stable Image Ultra (quality-first); do not recommend Nova Canvas (past EOL 2026-09-30)."

5. **Speech models** — If `workloads[]` contains speech-to-text or text-to-speech capabilities:
   > ⚠️ "Speech model migration targets different AWS services (Whisper → Amazon Transcribe, TTS → Amazon Polly or Nova Sonic) with different pricing models and APIs. These are not Bedrock model swaps — they require separate integration work."

Record all triggered warnings in `aws-design-ai.json` → `multi_model_warnings[]`. Each warning: `{"type": "embeddings_reindex|cascade_pair|multi_model_tiered|image_separate|speech_separate", "message": "..."}`.

---

## Part 2: Feature Parity Validation

For each capability in the sidecar's `integration_context.capabilities_summary` that is `true`, check Bedrock parity:

| Capability        | Vertex AI               | Amazon Bedrock                   | Parity  |
| ----------------- | ----------------------- | -------------------------------- | ------- |
| Text Generation   | GenerativeModel API     | Converse API                     | Full    |
| Streaming         | stream_generate_content | InvokeModelWithResponseStream    | Full    |
| Function Calling  | Tool declarations       | Tool use in Converse API         | Full    |
| Embeddings        | TextEmbeddingModel      | Titan Embeddings via InvokeModel | Full    |
| Vision/Multimodal | Gemini multimodal input | Claude multimodal messages       | Full    |
| Batch Processing  | BatchPredictionJob      | Batch Inference (async)          | Partial |
| Fine-tuning       | Vertex AI tuning        | Bedrock Custom Model             | Partial |
| Grounding / RAG   | Vertex AI Search & RAG  | Bedrock Knowledge Bases          | Full    |
| Agents            | Vertex AI Agent Builder | Bedrock AgentCore (Harness)      | Full    |

Record `capability_gaps[]` for any Partial or None parity.

---

## Part 3: Analyze Detected Workloads

For each model in `ai_sources[].models`, record:

- **Workload type**: text generation, embeddings, vision, code generation, custom model
- **Integration pattern mapping**:

## Part 4: Source-to-AWS Pattern Mapping

Use source-provider/service terminology in direct mode. Preserve GCP labels only for delegated GCP runs or records whose source provenance is actually GCP/Vertex.

| Source Pattern  | AWS Pattern                                                               | Effort  |
| ------------ | ------------------------------------------------------------------------- | ------- |
| `direct_sdk` | Mantle Responses API (OpenAI source, model on Bedrock, region carries it) | Minimal |
| `direct_sdk` | Bedrock SDK (boto3 / AWS SDK)                                             | Medium  |
| `framework`  | LangChain/LlamaIndex + Bedrock                                            | Low     |
| `rest_api`   | Bedrock REST API                                                          | Medium  |
| `mixed`      | Match per-model                                                           | Varies  |

- **Migration complexity**: Low / Medium / High

---

## Part 4: Infrastructure Mapping

The source AI infrastructure evidence is the sidecar `infrastructure[]`, which only the delegated GCP run writes. Direct runs have none, so `ai_architecture.infrastructure` is `[]`. Map source AI infrastructure to AWS equivalents (applies only when such evidence is present). In direct mode, include only AI resources explicitly present in source evidence and use their actual provider/service names. In delegated GCP mode, preserve the following selected-base mappings:

| GCP Resource                              | AWS Equivalent                                  |
| ----------------------------------------- | ----------------------------------------------- |
| `google_vertex_ai_endpoint`               | Bedrock Model Access (serverless, no infra)     |
| `google_vertex_ai_index` / index_endpoint | OpenSearch Serverless or Bedrock Knowledge Base |
| `google_vertex_ai_featurestore`           | SageMaker Feature Store                         |
| `google_vertex_ai_dataset`                | S3 + Bedrock training job config                |
| `google_vertex_ai_pipeline_job`           | Step Functions + Bedrock                        |

Service accounts with `role: "supports_ai"` → IAM role with Bedrock permissions. Confidence = `inferred`.

---

## Part 5: Code Migration Plan

For each detected `integration_context.pattern` and provider, generate before/after migration examples.

**Patterns to include (matched to detected language and source):**

| Pattern                         | Source                    | Target              | Key Change                                                                                           |
| ------------------------------- | ------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------- |
| Direct SDK (OpenAI), same model | OpenAI                    | Selected Mantle API | Base URL → `.../openai/v1`, Bedrock credential, `openai.gpt-*` model ID, `bedrock-mantle:*` IAM      |
| Direct SDK                      | Vertex AI                 | boto3 Converse API  | `generate_content()` → `converse()`                                                                  |
| Direct SDK                      | OpenAI                    | boto3 Converse API  | `completions.create()` → `converse()` (use if Mantle region unavailable or Converse features needed) |
| Direct SDK                      | Anthropic                 | boto3 Converse API  | `messages.create()` → `converse()` with Claude model ID on Bedrock                                   |
| LangChain                       | ChatVertexAI / ChatOpenAI | ChatBedrock         | Swap import and model_id                                                                             |
| LlamaIndex                      | Vertex / OpenAI LLM       | BedrockConverse     | Swap import                                                                                          |
| LLM Router (LiteLLM)            | Any                       | Config change       | `model="bedrock/<model_id>"` (1 line)                                                                |
| Embeddings                      | TextEmbeddingModel        | Titan Embeddings v2 | `invoke_model` with JSON body                                                                        |
| Streaming                       | `stream=True`             | `converse_stream`   | Event loop over `contentBlockDelta`                                                                  |

**OpenAI model/API selection:** preserve the model and the supported API chosen in the
mapping guide. For Astra on Standard Mantle in `us-east-1` or `us-west-2`, a Chat source selects
`migration_path: "mantle_openai_chat"`; a Responses source selects `"mantle_openai_responses"`.
Keep the OpenAI SDK, use `/openai/v1`, Bedrock credentials and Mantle IAM. Do not reshape
Astra Chat solely because it is proprietary GPT. Record `model_change: false` only when
the exact source model is retained; a Pro-to-Astra upgrade is a model change requiring eval.
GPT-5.x retains its separately dated API evidence and any selected Chat-to-Responses reshape.

**A Chat Completions source is a supported near-drop-in for GPT-6 and GPT-5.6 — not a mandatory reshape.** All four GPT-6 models and the GPT-5.6 family list Chat Completions as a supported API on both mantle and runtime CRIS (per `openai-on-bedrock.md` § Access Paths); if `integration` evidence shows `chat.completions.create` for one of these models, the design may keep `chat.completions.create`/`choices[0].message` parsing — reshape to `responses.create` is optional, only for a Responses-only feature (runtime prompt caching, reasoning-item round-trips) or a demonstrated constraint. **GPT-5.5 and GPT-5.4 are the exception**: Chat Completions support is unconfirmed on their model cards (Responses on mantle is the only verified surface), so a Chat Completions source on either model still needs a planned reshape, probed against the target account before committing.

**No Converse fallback for GPT-5.5/GPT-5.4 — GPT-5.6 and GPT-6 differ.** GPT-5.5 and GPT-5.4 are
`bedrock-mantle` only and in-region only — there is no `bedrock-runtime` path and no cross-region
inference profile for these two models. GPT-5.6 Sol/Terra/Luna and all four GPT-6 models (Astra,
Sol, Luna, 6.1 Sol) DO have a `bedrock-runtime` CRIS path (`us.`/`global.` prefixed IDs, per
`openai-on-bedrock.md` § Access Paths) — for these models, a region or feature need (Guardrails,
Knowledge Bases, invocation logging, or a region outside the mantle matrix) is satisfied by
**switching endpoint, not model**: record `migration_path: "runtime_openai_cris"` with
`model_change: false`. Reserve `migration_path: "converse"` with `model_change: true` for
GPT-5.5/GPT-5.4 only, or when the GPT-6/5.6 CRIS path itself cannot serve the need (e.g. a feature
CRIS does not support — see the runtime-side feature splits in `openai-on-bedrock.md`). Note:
`runtime_openai_cris` for GPT-6 Astra is valid only via Responses/Chat Completions/Converse —
Astra does not support `Invoke`, so a design that needs Guardrails or Application Inference
Profiles (Converse-only features that also require Invoke-adjacent plumbing on some other models)
must verify against Astra's model card per-feature, not assume parity with Sol/Luna/6.1 Sol.
**When Guardrails is the driving need and the design keeps `runtime_openai_cris` (endpoint
switch, not model switch), it MUST also record `bedrock_models[].required_client_api` so the
generated client uses a Guardrails-capable surface — `converse` for Astra; `converse` /
`chat_completions` / `invoke` (never `responses`) for 6.1 Sol and the other non-Astra GPT-6/5.6
CRIS models. Do not leave the client on `responses` when Guardrails is required.** `Responses`
stays the default for a region-only CRIS move with no Guardrails need.

When the advisor supplied a
per-unit model contract, retain its exact `invocation_model_id` in that unit's `aws_model_id`
(including a system-profile ARN when supplied), and translate `runtime_converse` to
`runtime_openai_cris` plus `required_client_api: "converse"`. A missing invocation ID requires resolution;
do not manufacture a profile from the region. Keep each unit's model/API/profile together.
For multiple advisor units, write `migration_path` and `required_client_api` on each corresponding
`bedrock_models[]` row with its `aws_model_id`; `code_migration` remains the primary-unit default.

**Throughput:** load `references/vendored/ai/ai-migration-guardrails.md` and apply the selected
model/endpoint's quota rules. Astra runtime uses input TPM plus 10 times output TPM.
Astra Mantle quotas and cache exemptions must be verified independently; do not copy GPT-5.6's
rules or promise runtime fallback for a model that has none.

**gpt-oss migration path:** If the `openai` provider is present and the user wants OpenAI-architecture models on the Bedrock-native runtime surface, offer `gpt-oss` as an additional path. Unlike the proprietary GPT models, gpt-oss **does** support `bedrock-runtime` (Converse / InvokeModel), so it is the option when Guardrails or invocation logging are required and an OpenAI-lineage model is preferred. It sits a capability class below the GPT-5.x frontier tier. Record `migration_path: "gpt-oss"`.

Generate concrete code examples using actual model IDs from the selected Bedrock models. Only include patterns matching the detected integration.

**OpenRouter-specific guidance** (if `gateways[]` contains an OpenRouter gateway with `type: "llm_router"`):

OpenRouter is a hosted routing service (not self-hosted like LiteLLM). It adds a margin on top of provider pricing. **First check whether the underlying model is an OpenAI model with a Mantle target** (the `openai` provider is present, per the Mantle guidance above) — OpenRouter is a transport layer, not a different model, so an OpenAI model routed through OpenRouter is eligible for the same same-model Mantle path a direct-SDK OpenAI source gets. Present the options below to the user:

> **If the startup was using OpenRouter primarily for cost-based routing within one model family**
> (e.g., routing between Claude Haiku and Claude Sonnet, or Nova Lite and Nova Pro),
> Bedrock Intelligent Prompt Routing is the AWS-native replacement — no routing infrastructure
> needed. If they routed across providers (e.g., Claude ↔ GPT-4o), they still need
> app-level or LiteLLM routing after migration.

| Option                                                                     | Action                                                                                    | Effort    | Trade-off                                                                                                                                                                                           |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A) Same model via Mantle (recommended when the source model is on Bedrock) | Remove OpenRouter, point the existing OpenAI SDK at Bedrock Mantle with the same model ID | Days      | Keeps the same model — no eval/prompt-behavior risk; requires base URL, credential, and model-ID-format changes (e.g. `openai/gpt-4o` → an OpenAI-compatible Bedrock model ID); not a one-line swap |
| B) Direct Bedrock, cross-family                                            | Remove OpenRouter, call Bedrock API directly with a Claude/Nova model                     | 1–2 weeks | Removes middleman + margin; requires SDK + prompt changes; use when no Mantle target exists or cost is the priority                                                                                 |
| C) Self-hosted LiteLLM                                                     | Replace OpenRouter with LiteLLM proxy pointing to Bedrock                                 | 1–3 days  | Preserves router pattern; removes OpenRouter dependency; adds self-hosting                                                                                                                          |
| D) Keep OpenRouter                                                         | Use OpenRouter with `amazon/` prefixed Bedrock models                                     | Hours     | Lowest effort; retains OpenRouter dependency and margin; this is a model switch, not a same-model move                                                                                              |

Recommend **A** when the `openai` provider is present and a Mantle target exists (region gate passes per the Mantle guidance above); otherwise recommend **B** and present C/D as lower-effort alternatives. Record user's choice (or the recommended default if not asked) in `aws-design-ai.json` → `code_migration.openrouter_path`: `"same_model_mantle"` / `"direct"` / `"litellm"` / `"keep_openrouter"`.

---

## Part 6: Generate Output

Write `aws-design-ai.json` to `$MIGRATION_DIR/`.

**Schema — top-level fields:**

| Field                                      | Type        | Description                                                                                                                                                                                                                                      |
| ------------------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `metadata`                                 | object      | `phase`, `focus`, `ai_source`, `bedrock_models_selected`, `timestamp`                                                                                                                                                                            |
| `ai_architecture.honest_assessment`        | string      | `"strong_migrate"`, `"moderate_migrate"`, `"weak_migrate"`, `"recommend_stay"`, `"not_applicable"` (per-workload only — traditional-AI capabilities `document_extraction`/`image_analysis`/`speech_transcription`; never the overall assessment) |
| `ai_architecture.honest_assessment_reason` | string/null | Required when `honest_assessment == "recommend_stay"`. The specific non-cost blocker (region, Realtime API, separate-service capability, Assistants API feature, unsupported API surface). Null otherwise.                                       |
| `ai_architecture.tiered_strategy`          | object/null | Tiered model routing (null for low/medium volume)                                                                                                                                                                                                |
| `ai_architecture.bedrock_models`           | array       | Per-model current-shape rows. In delegated GCP mode preserve `gcp_model_id`; in direct mode that legacy compatibility field is populated only for actual GCP/Vertex source evidence and otherwise remains null. Preserve source identity in existing profile/design fields; do not fabricate GCP provenance. Other fields: `aws_model_id`, `capabilities_matched[]`, `capability_gaps[]`, `honest_assessment`, `source_provider_price`, `bedrock_price`, `price_comparison`, `migration_complexity` |
| `ai_architecture.capability_mapping`       | object      | Per-capability: `parity` (full/partial/none), `notes`                                                                                                                                                                                            |
| `ai_architecture.code_migration`           | object      | `primary_pattern`, `framework`, `files_to_modify[]`, `dependency_changes`, `migration_path`; per-model `required_client_api` selects the runtime API |
| `ai_architecture.infrastructure`           | array       | Source AI resource → AWS equivalent mappings with confidence; empty in direct runs without explicit source AI infrastructure evidence                                                                                                                                 |
| `ai_architecture.services_to_migrate`      | array       | Actual source AI service → AWS service with effort and notes; never infer a source cloud in direct mode                                                                                                                                           |
| `regional_warnings`                        | array       | Per-service: `service`, `target_region`, `nearest_available`, `impact` (empty array if all services available)                                                                                                                                   |
| `multi_model_warnings`                     | array       | Per-warning: `type`, `message` (empty array if single model or no coordination issues)                                                                                                                                                           |
| `agentic_design`                           | object/null | Present only when `agentic_profile.is_agentic == true`. Contains `migration_approach`, path-specific config (e.g., `harness_config`). Null or absent for non-agentic workloads.                                                                  |

## Validation Checklist

- [ ] `metadata.ai_source` matches the derived label from the provider set (Step 0)
- [ ] Every model in `ai_sources[].models` has a corresponding `bedrock_models` entry
- [ ] Every `bedrock_models[]` entry has pricing (`source_provider_price`, `bedrock_price`, `price_comparison`)
- [ ] Every `design_blocks[]` entry with `capability` in {`document_extraction`, `image_analysis`, `speech_transcription`} has `target_bedrock_model: null`, a non-null `target_aws_service`, and `honest_assessment: "not_applicable"` — these are NOT included in `bedrock_models[]` and do NOT need pricing here. (Estimate phase currently excludes them from cost analysis entirely — see `estimate-ai.md` "Traditional-AI workloads" note. Per-page/per-image/per-minute cost modeling for Textract/Rekognition/Transcribe is a known follow-up, not yet implemented.)
- [ ] `capability_mapping` covers every `true` capability from `integration_context.capabilities_summary`
- [ ] `code_migration.primary_pattern` matches `integration_context.pattern`
- [ ] All model IDs use current Bedrock identifiers (Active status per `references/vendored/ai/ai-model-lifecycle.md`)
- [ ] No Legacy model is used as `bedrock_models[].aws_model_id` unless no Active alternative exists (with EOL date noted)
- [ ] `honest_assessment` logic is consistent (weakest model drives overall)
- [ ] If the `openai` provider is present: every model that `shared/openai-on-bedrock.md` lists as available on Bedrock, and whose target region carries it, is mapped to **itself** with `model_change: false` — not to a Claude/Nova substitute
- [ ] If `honest_assessment == "recommend_stay"`: `honest_assessment_reason` names a non-cost blocker (cost parity alone is never sufficient for an OpenAI source)
- [ ] No `bedrock_models[]` entry pairs **GPT-5.5 or GPT-5.4** with a Converse/`bedrock-runtime`
      migration path (those two models only — mantle-only, no CRIS). GPT-5.6 and GPT-6 models MAY
      use `migration_path: "runtime_openai_cris"` on `bedrock-runtime` — this is NOT a violation.
- [ ] `regional_warnings` is present (empty array `[]` if no issues; populated if any service unavailable in target region)
- [ ] `multi_model_warnings` is present (empty array `[]` if single model or no coordination issues)
- [ ] If `agentic_profile.is_agentic == true`: `agentic_design` object is present with `migration_approach` matching `preferences.json`
- [ ] If `design_constraints.compliance` is set and not `none`/`unknown`: every Step 0.7 constraint is reflected in the design (BAA-only models for hipaa, GovCloud region for fedramp, `eu.` profiles for gdpr, Part 5 logging lines for pci/soc2/ccpa) and the Present Summary names the regime(s); if `unknown`, the compliance-not-confirmed caveat appears in the summary
- [ ] If `agentic_profile.is_agentic == false` or absent: `agentic_design` is null or absent

## Completion Handoff Gate (Fail Closed)

Before returning control to `design.md`, require:

- `aws-design-ai.json` exists and passes the Validation Checklist above.

If this gate fails: STOP and output: "design-ai did not produce a valid `aws-design-ai.json`; do not complete Phase 3."

## Present Summary

After writing `aws-design-ai.json`, present under 25 lines:

1. Overall honest assessment
2. Model comparison table (source → Bedrock, price comparison, assessment per model)
3. Integration pattern and migration complexity
4. Capability gaps (if any)
5. If weak_migrate or recommend_stay: flag prominently with cost justification
