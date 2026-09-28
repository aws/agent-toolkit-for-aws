# Design Phase: AI Workloads (Bedrock)

> Loaded by `design.md` when `ai-workload-profile.json` exists.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Load Inputs

Read `$MIGRATION_DIR/ai-workload-profile.json`:

- `summary.ai_source` — `"gemini"`, `"openai"`, `"anthropic"`, `"both"`, `"other"`
- `models[]` — Detected AI models with service, capabilities, evidence
- `integration` — SDK, frameworks, languages, gateway type, capability summary
- `infrastructure[]` — Terraform resources related to AI (may be empty)
- `current_costs` — Present only if billing data or OpenAI usage API data was provided (`source` field records which)

Read `$MIGRATION_DIR/preferences.json` → `ai_constraints` (if present). If absent: use defaults (prefer managed Bedrock, no latency constraint, no budget cap).

**Region selection for AI workloads:** If `design_constraints.target_region` was derived from GCP region proximity (not explicitly chosen by the user), verify the selected Bedrock models are available in that region. Use `aws___get_regional_availability` (AWS MCP Server) to check model availability. If the target region lacks the selected model, prefer the geographically closest AWS region where it is available.

**Load source-specific design reference based on `ai_source`:**

- `"gemini"` → load `references/design-refs/ai-gemini-to-bedrock.md`
- `"openai"` → load `references/vendored/ai/ai-openai-to-bedrock.md` **and**
  `references/shared/openai-on-bedrock.md` (the fact base: model IDs, endpoint paths, region matrix, quotas,
  caching). OpenAI's proprietary GPT models run on Bedrock, so the source model is often itself the target — the
  mapping guide's Tier 0 path is the default, not a cross-family swap.
- `"anthropic"` → load `references/vendored/ai/ai-anthropic-to-bedrock.md` (Anthropic SDK → Bedrock Converse API client swap; do NOT use ai-openai-to-bedrock.md for Anthropic SDK users)
- `"both"` → load both `ai-gemini-to-bedrock.md` and `ai-openai-to-bedrock.md`
- `"other"` or absent → load `references/design-refs/ai.md` (traditional ML rubric — Vision API, Speech API, Document AI, custom models only; do NOT use for Anthropic SDK users)

**Additional load, independent of `ai_source` above:** If any entry in `workloads[]` (from `preferences.json`, falling back to `ai-workload-profile.json`) has `capability` equal to `document_extraction`, `image_analysis`, or `speech_transcription`, ALSO load `references/design-refs/ai.md` — even when a generative `ai_source` already selected a different ref above. A workload's non-generative capability is evaluated independently of the codebase's primary LLM provider; e.g. an `ai_source: "openai"` codebase that also calls `documentai.process_document` needs both `ai-openai-to-bedrock.md` (for its GPT workload) and `ai.md` (for its Document AI workload).

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

**Skip this step if `agentic_profile` is absent from `ai-workload-profile.json`.**

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
| `gdpr`           | Target region restricted to EU (eu-west-1, eu-central-1); model IDs must use **geographic `eu.` inference profiles** — `global.` profiles route outside the EU boundary and are forbidden. Note the GCP-EU → AWS-EU transfer in the summary. Exclude any candidate with no `eu.` Geo profile, including Fable 5 / 5.1 and Mythos. Fable 5's in-region access is limited to `bedrock-mantle` in us-east-1; both use `us.` / `global.` profiles on `bedrock-runtime`.     |
| `pci`            | Part 5 plan must include: no cardholder data in prompts without tokenization; CloudTrail on Bedrock API calls; scoped IAM (no `bedrock:*`).                                                                                                                                                                                                                                                                                                                             |
| `soc2` / `ccpa`  | Part 5 plan must include CloudTrail audit logging; CCPA additionally: prompt/completion retention policy + deletion workflow for logged content. Models whose Status is `restricted` with an `aws_review` or `provider_data_share` retention opt-in (Fable / Mythos) keep prompts outside the customer's deletion control — up to 30 days for AWS review, or shared with the provider — so exclude them under CCPA unless the plan documents that retention explicitly. |

Record what was applied: every constraint that changed a model choice or region adds a `regional_warnings[]` entry (existing shape) or a Part 5 plan line naming the compliance value that forced it, and the Present Summary section MUST state which compliance regime(s) shaped the design. A design that ignores a declared compliance value is a validation failure (see Validation Checklist).

---

## Part 1: Bedrock Model Selection

**Restricted models — applies whichever guide Step 0 loaded and whatever the compliance value:** a row whose `Status` in `shared/pricing-cache.md` is `restricted (…)` (Covered Models such as Claude Fable 5 / 5.1, gated previews such as Claude Mythos) is never `recommended_model` or `backup_model` and never a default in any mapping guide. Offer one only when the user explicitly asks for a frontier model, and state its data-retention opt-in and any endpoint-specific regional or CRIS-only restrictions in the same sentence.

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
   - Q17 special features (hard override) > **same-model availability** > Q16 priority > Q18/Q21 volume and latency >
     source model baseline
   - **Same-model availability outranks Q16 priority.** If the source model is available on Bedrock and the target
     region carries it, keep it — a `balanced` or unset priority must not silently move the workload to a different
     model family. Only a Q17 hard feature override (a capability the source model cannot serve) beats it. An
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

6. **Empty workloads:** If `workloads[]` is empty, emit `aws-design-ai.json` with `"design_blocks": []` and proceed with the existing `models[]` path below as fallback.

**Fallback (no `workloads[]` or single entry):** If `workloads[]` is absent or has exactly one entry, fall through to the existing per-model logic below (backward compatible).

---

For each model in `models[]`, select the best-fit Bedrock model using the loaded design reference mapping tables. Do NOT use a hardcoded mapping — the design-ref files contain tier-organized tables with pricing and competitive analysis.

Treat model mapping as compatibility-guided, not 1:1 parity. Before cutover, require validation of prompts, tool-calling behavior, and eval metrics for the selected Bedrock model.

**If `models[]` is empty:** Skip per-model rows; output a short **placeholder strategy** (one representative Bedrock model family per `ai_source` rubric) and dependency on Clarify answers — do not fabricate `models[]` entries.

**Apply user preference overrides from `ai_constraints`:**

| Preference                | Override                                                                                                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ai_priority = "cost"`    | Prefer "Winner" column; flag if source is cheaper                                                                                                                                |
| `ai_priority = "quality"` | Prefer Claude Sonnet/Opus regardless of cost                                                                                                                                     |
| `ai_priority = "speed"`   | Prefer Claude Sonnet (fastest integration)                                                                                                                                       |
| `ai_latency = "critical"` | Prefer smaller/faster models (Haiku, Nova Lite)                                                                                                                                  |
| `ai_latency = "flexible"` | Any model; flag Batch API for 50% savings — but only for confirmed-batch models (skip the discount for models whose batch cells are `_unverified_` in `shared/pricing-cache.md`) |

**Stay-or-migrate assessment per model:**

Check the same-model case FIRST — it short-circuits the cost comparison:

- **Source model is available on Bedrock** (per `shared/openai-on-bedrock.md`) AND the target region carries it →
  `"strong_migrate"`. Set `model_change: false`. The rationale is risk (no behavior delta) plus AWS commitments,
  governance, and residency — **not** cost: Bedrock in-region is priced at OpenAI's data-residency-tier rate, about
  10% above OpenAI standard, so report a modest cost increase rather than parity. Do not downgrade the assessment for
  that ~10%, and do not claim it is free. If the workload exceeds 272K context, price it at the long-context tier
  (2.0x input, 1.5x output) — the gap is then substantial and may change the recommendation.
- Source model on Bedrock but the target region does not carry it → treat as no-same-model below, and record the
  region as the cause in `regional_warnings[]`. Do not report this as a model-quality judgment.
- Bedrock cheaper → `"strong_migrate"`
- Bedrock within 25% of source AND priority != cost → `"moderate_migrate"`
- Source > 25% cheaper AND priority = cost → `"weak_migrate"` or `"recommend_stay"`

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
| `"medium"`                | Nova / Llama / other (1× burndown) | `"low"`      | No action                                                                         |
| `"low"`                   | Any                                | `"low"`      | No action                                                                         |

Include `quota_risk` in `aws-design-ai.json` → `ai_architecture` alongside `honest_assessment`.

---

## Part 1B: Volume-Based Strategy

If `ai_token_volume` is `"high"`, generate a `tiered_strategy`:

| Tier | Traffic | Model Selection              | Use Cases                                            |
| ---- | ------- | ---------------------------- | ---------------------------------------------------- |
| 1    | 60%     | Nova Micro or Llama 4 Scout  | Classification, extraction, short answers, routing   |
| 2    | 30%     | Llama 4 Maverick or Nova Pro | Summarization, moderate generation, Q&A with context |
| 3    | 10%     | Claude Sonnet 5              | Reasoning, long-form, agentic tasks, tool use        |

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

If `models[]` contains more than one model, check for coordination patterns and generate warnings. These help the user understand that migrating multiple models requires coordinated testing, not independent swaps.

**Check and warn:**

1. **Embeddings + generation model detected** — If `models[]` contains both an embeddings model (capabilities_used includes `"embeddings"`) AND a text generation model:
   > ⚠️ "Migrating the embedding model (e.g., text-embedding-3-small → Titan Embeddings v2) requires re-embedding all documents in your vector store. Plan for re-indexing time and temporary storage. Test retrieval quality with the new embeddings before switching generation model."
   > ⚠️ "Verify vector index dimension compatibility before cutover. OpenAI text-embedding-3-small outputs 1536 dimensions; Titan Embeddings v2 is configurable (256, 512, or 1024). A mismatch will cause insert failures at the vector store layer — your index must be rebuilt at the target dimension before any data is written."

2. **Models at different price tiers** — If `models[]` contains both a mini/nano/lite model AND a flagship model (infer from model_id naming: `*-mini`, `*-nano`, `*-lite` vs flagship):
   > ⚠️ "These models appear to work as a cascade or routing pattern (cheap model for classification/filtering, expensive model for generation). Test the Bedrock replacement pair together — validate that the cheaper model's classification accuracy is preserved with its Bedrock equivalent before testing the expensive model."

3. **More than 3 models** — If `models[]` count > 3:
   > ⚠️ "Multiple models detected ([count]). Recommend a tiered migration strategy: migrate and validate one model at a time, starting with the lowest-risk (highest-volume, simplest task). See Part 1B for tiered routing recommendations."

4. **Text generation + image generation** — If `models[]` contains both text generation AND image generation capabilities:
   > ⚠️ "Image generation migration (e.g., DALL-E/gpt-image → Stability AI) requires separate evaluation. Image quality is subjective — plan for human evaluation alongside automated metrics. Default to Stable Image Core (cost-first) or Stable Image Ultra (quality-first); do not recommend Nova Canvas."

5. **Speech models** — If `models[]` contains speech-to-text or text-to-speech capabilities:
   > ⚠️ "Speech model migration targets different AWS services (Whisper → Amazon Transcribe, TTS → Amazon Polly or Nova Sonic) with different pricing models and APIs. These are not Bedrock model swaps — they require separate integration work."

Record all triggered warnings in `aws-design-ai.json` → `multi_model_warnings[]`. Each warning: `{"type": "embeddings_reindex|cascade_pair|multi_model_tiered|image_separate|speech_separate", "message": "..."}`.

---

## Part 2: Feature Parity Validation

For each capability in `integration.capabilities_summary` that is `true`, check Bedrock parity:

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

For each model in `models[]`, record:

- **Workload type**: text generation, embeddings, vision, code generation, custom model
- **Integration pattern mapping**:

| GCP Pattern  | AWS Pattern                                                               | Effort  |
| ------------ | ------------------------------------------------------------------------- | ------- |
| `direct_sdk` | Mantle Responses API (OpenAI source, model on Bedrock, region carries it) | Minimal |
| `direct_sdk` | Bedrock SDK (boto3 / AWS SDK)                                             | Medium  |
| `framework`  | LangChain/LlamaIndex + Bedrock                                            | Low     |
| `rest_api`   | Bedrock REST API                                                          | Medium  |
| `mixed`      | Match per-model                                                           | Varies  |

- **Migration complexity**: Low / Medium / High

---

## Part 4: Infrastructure Mapping

Map GCP AI infrastructure to AWS equivalents:

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

For each detected `integration.pattern` and `ai_source`, generate before/after migration examples.

**Patterns to include (matched to detected language and source):**

| Pattern                         | Source                    | Target               | Key Change                                                                                           |
| ------------------------------- | ------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------- |
| Direct SDK (OpenAI), same model | OpenAI                    | Mantle Responses API | Base URL → `.../openai/v1`, Bedrock credential, `openai.gpt-*` model ID, `bedrock-mantle:*` IAM      |
| Direct SDK                      | Vertex AI                 | boto3 Converse API   | `generate_content()` → `converse()`                                                                  |
| Direct SDK                      | OpenAI                    | boto3 Converse API   | `completions.create()` → `converse()` (use if Mantle region unavailable or Converse features needed) |
| Direct SDK                      | Anthropic                 | boto3 Converse API   | `messages.create()` → `converse()` with Claude model ID on Bedrock                                   |
| LangChain                       | ChatVertexAI / ChatOpenAI | ChatBedrock          | Swap import and model_id                                                                             |
| LlamaIndex                      | Vertex / OpenAI LLM       | BedrockConverse      | Swap import                                                                                          |
| LLM Router (LiteLLM)            | Any                       | Config change        | `model="bedrock/<model_id>"` (1 line)                                                                |
| Embeddings                      | TextEmbeddingModel        | Titan Embeddings v2  | `invoke_model` with JSON body                                                                        |
| Streaming                       | `stream=True`             | `converse_stream`    | Event loop over `contentBlockDelta`                                                                  |

**Mantle Responses API (primary path for OpenAI sources):** If `ai_source = "openai"` and the source model is on Bedrock, this is the primary option. The application keeps the OpenAI SDK and the same model; only the base URL, credential, model ID, and IAM actions change. Read `references/shared/openai-on-bedrock.md` for the exact values — three details break naive implementations: the path is `/openai/v1/responses` (not `/v1/responses`), the credential must be a Bedrock API key or token provider (not an OpenAI key), and IAM needs `bedrock-mantle:*` actions (not `bedrock:InvokeModel`). Record `migration_path: "mantle_openai_responses"` and `model_change: false`.

**This is not a zero-code change if the source uses Chat Completions.** Chat Completions support is unverified for the proprietary GPT models — every AWS sample uses Responses. If `integration` evidence shows `chat.completions.create`, plan a reshape to `responses.create` and probe the target account before committing. Only a source already on `responses.create` is close to a drop-in.

**No Converse fallback for proprietary GPT models.** The GPT-5.x models are `bedrock-mantle` only and in-region only — there is no `bedrock-runtime` path and no cross-region inference profile. If the workload needs Bedrock Guardrails, Knowledge Bases, invocation logging, or a region these models do not serve, that requires a **model change** to a Bedrock-native model (or gpt-oss), not an endpoint change. Record `migration_path: "converse"` with `model_change: true` in that case.

**Mantle throughput (medium/high volume):** quotas on `bedrock-mantle` are **per-model, per-region input TPM and output TPM — there is no RPM quota**. For `ai_token_volume = "medium"` or `"high"`, note: "Mantle enforces per-model input/output TPM quotas per region; 429s indicate a TPM ceiling, not a request-rate cap. Mitigate with exponential backoff, spreading load across minutes, and prompt caching (cached input is exempt from the input-TPM quota). There is no `bedrock-runtime` fallback for these models, so sustained growth needs a quota increase." See `references/vendored/ai/ai-migration-guardrails.md`.

**gpt-oss migration path:** If `ai_source = "openai"` and the user wants OpenAI-architecture models on the Bedrock-native runtime surface, offer `gpt-oss` as an additional path. Unlike the proprietary GPT models, gpt-oss **does** support `bedrock-runtime` (Converse / InvokeModel), so it is the option when Guardrails or invocation logging are required and an OpenAI-lineage model is preferred. It sits a capability class below the GPT-5.x frontier tier. Record `migration_path: "gpt-oss"`.

Generate concrete code examples using actual model IDs from the selected Bedrock models. Only include patterns matching the detected integration.

**OpenRouter-specific guidance** (if `gateway_type == "llm_router"` AND `detection_signals` contains OpenRouter evidence):

OpenRouter is a hosted routing service (not self-hosted like LiteLLM). It adds a margin on top of provider pricing. **First check whether the underlying model is an OpenAI model with a Mantle target** (`ai_source == "openai"`, per the Mantle guidance above) — OpenRouter is a transport layer, not a different model, so an OpenAI model routed through OpenRouter is eligible for the same same-model Mantle path a direct-SDK OpenAI source gets. Present the options below to the user:

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

Recommend **A** when `ai_source == "openai"` and a Mantle target exists (region gate passes per the Mantle guidance above); otherwise recommend **B** and present C/D as lower-effort alternatives. Record user's choice (or the recommended default if not asked) in `aws-design-ai.json` → `code_migration.openrouter_path`: `"same_model_mantle"` / `"direct"` / `"litellm"` / `"keep_openrouter"`.

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
| `ai_architecture.bedrock_models`           | array       | Per-model: `gcp_model_id`, `aws_model_id`, `capabilities_matched[]`, `capability_gaps[]`, `honest_assessment`, `source_provider_price`, `bedrock_price`, `price_comparison`, `migration_complexity`                                              |
| `ai_architecture.capability_mapping`       | object      | Per-capability: `parity` (full/partial/none), `notes`                                                                                                                                                                                            |
| `ai_architecture.code_migration`           | object      | `primary_pattern`, `framework`, `files_to_modify[]`, `dependency_changes`                                                                                                                                                                        |
| `ai_architecture.infrastructure`           | array       | GCP resource → AWS equivalent mappings with confidence                                                                                                                                                                                           |
| `ai_architecture.services_to_migrate`      | array       | GCP service → AWS service with effort and notes                                                                                                                                                                                                  |
| `regional_warnings`                        | array       | Per-service: `service`, `target_region`, `nearest_available`, `impact` (empty array if all services available)                                                                                                                                   |
| `multi_model_warnings`                     | array       | Per-warning: `type`, `message` (empty array if single model or no coordination issues)                                                                                                                                                           |
| `agentic_design`                           | object/null | Present only when `agentic_profile.is_agentic == true`. Contains `migration_approach`, path-specific config (e.g., `harness_config`). Null or absent for non-agentic workloads.                                                                  |

## Validation Checklist

- [ ] `metadata.ai_source` matches `summary.ai_source` from input
- [ ] Every model in `models[]` has a corresponding `bedrock_models` entry
- [ ] Every `bedrock_models[]` entry has pricing (`source_provider_price`, `bedrock_price`, `price_comparison`)
- [ ] Every `design_blocks[]` entry with `capability` in {`document_extraction`, `image_analysis`, `speech_transcription`} has `target_bedrock_model: null`, a non-null `target_aws_service`, and `honest_assessment: "not_applicable"` — these are NOT included in `bedrock_models[]` and do NOT need pricing here. (Estimate phase currently excludes them from cost analysis entirely — see `estimate-ai.md` "Traditional-AI workloads" note. Per-page/per-image/per-minute cost modeling for Textract/Rekognition/Transcribe is a known follow-up, not yet implemented.)
- [ ] `capability_mapping` covers every `true` capability from `capabilities_summary`
- [ ] `code_migration.primary_pattern` matches `integration.pattern`
- [ ] All model IDs use current Bedrock identifiers (Active status per `shared/ai-model-lifecycle.md`)
- [ ] No Legacy model is used as `bedrock_models[].aws_model_id` unless no Active alternative exists (with EOL date noted)
- [ ] `honest_assessment` logic is consistent (weakest model drives overall)
- [ ] If `ai_source` includes `"openai"`: every model that `shared/openai-on-bedrock.md` lists as available on Bedrock, and whose target region carries it, is mapped to **itself** with `model_change: false` — not to a Claude/Nova substitute
- [ ] If `honest_assessment == "recommend_stay"`: `honest_assessment_reason` names a non-cost blocker (cost parity alone is never sufficient for an OpenAI source)
- [ ] No `bedrock_models[]` entry pairs a proprietary `openai.gpt-*` model ID with a Converse/`bedrock-runtime` migration path (those models are mantle-only)
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
