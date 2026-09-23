# Schema — ai-workload-profile.json

> **Why this file exists.** `ai-workload-profile.json` is the artifact the entire AI track
> reads: `clarify-ai.md`, `design-ai.md`, `estimate-ai.md`, and `generate-artifacts-ai.md` all
> key off it. Without one written contract they drift on field names — the §13.3b class. This
> is the Azure port of gcp-to-aws's `schema-discover-ai.md`, kept parallel so the downstream AI
> ports stay straight; the only changes are the source-provider swaps recorded in § Azure swaps.

Produced by `discover-app-code.md` when app-code AI confidence ≥ 70%, OR — as a
minimal IaC-inferred profile — by `discover-iac.md` when the inventory is Cognitive-Services /
Azure-ML strong. Both producers have landed. An infrastructure-only repo (AI in Terraform,
no application code) depends on the IaC path; an app-code-only repo depends on the app-code path.

## Shape

```jsonc
{
  "metadata": {
    "report_date": "<ISO 8601>",
    "project_directory": "<path>",
    "profile_source": "application_code", // application_code | iac_cognitive | merged
    "sources_analyzed": {
      "terraform": true,
      "application_code": false,
      "billing_data": false,
      "openai_usage_api": false
    }
  },
  "summary": {
    "overall_confidence": 0.0,
    "confidence_level": "high", // high | medium | low
    "total_models_detected": 0,
    "languages_found": [],
    "ai_source": "azure_openai", // azure_openai | openai | anthropic | both | other
    "inferred_from_iac": false
  },
  "models": [], // see § models[]; MAY be empty for iac_cognitive
  "integration": {}, // see § integration
  "infrastructure": [], // Azure AI Terraform resources; [] if no IaC
  "current_costs": {}, // ONLY if billing or usage-API ran — see § current_costs
  "detection_signals": [], // see § detection_signals[]
  "workloads": [], // ALWAYS present, [] if none — see § workloads[]
  "agentic_profile": null, // ONLY if is_agentic — see § agentic_profile
  "tool_manifest": [] // ONLY if agentic_profile exists — see § tool_manifest[]
}
```

## summary.ai_source — the routing key

`azure_openai | openai | anthropic | both | other`. This is the value `design-ai.md` routes on.

- `azure_openai` — Azure OpenAI SDK/deployments detected. **Routes identically to `openai`**
  (the shared OpenAI→Bedrock guide serves Azure OpenAI); the distinct label is kept for report
  wording and provenance (plan §19.9b).
- `openai` — direct OpenAI SDK (not via Azure).
- `anthropic` — Anthropic SDK.
- `both` — Azure-OpenAI/OpenAI + another provider (e.g. Anthropic).
- `other` — traditional ML only (Azure AI Vision, Document Intelligence, Speech, Language,
  Azure ML custom); routes to `design-refs/ai.md`.

Azure DROPS gcp's `gemini` value. An unrecognised `ai_source` must NOT be emitted — a value not
in this enum falls through `design-ai.md`'s routing to the traditional-ML path silently.

## models[]

One per detected model. **Field names are exact** (the §13.3b drift class):

```jsonc
{
  "model_id": "gpt-4o", // NOT model_name / name
  "service": "azure_openai", // NOT service_type / azure_service (see below)
  "detected_via": ["code"], // NOT detection_method — subset of code|terraform|billing
  "evidence": [{ "source": "code", "file": "app/llm.py", "line": 42, "pattern": "AzureOpenAI(" }],
  "capabilities_used": ["text_generation"], // NOT capabilities / features
  "usage_context": "chat completion endpoint" // NOT description / purpose
}
```

`service` example values for Azure: `azure_openai`, `azure_openai_embeddings`, `cognitive_vision`,
`cognitive_document_intelligence`, `cognitive_speech`, `cognitive_language`, `azure_ml`. May be
`[]` for `profile_source: iac_cognitive` — downstream MUST NOT assume non-empty.

## integration

```jsonc
{
  "primary_sdk": "openai", // Azure OpenAI apps use the openai SDK; also @azure/openai, azure-ai-inference
  "sdk_version": "1.x",
  "frameworks": [],
  "languages": ["python"],
  "pattern": "direct_sdk", // direct_sdk | framework | rest_api | mixed | unknown
  "gateway_type": null, // llm_router | api_gateway | voice_platform | framework | direct | null
  "capabilities_summary": { // boolean map
    "text_generation": true,
    "streaming": false,
    "function_calling": false,
    "vision": false,
    "embeddings": false,
    "batch_processing": false
  }
}
```

## infrastructure[]

Azure AI Terraform resources: `{ address, type, file, role?, config{} }`. `[]` if no IaC.
Type examples: `azurerm_cognitive_account`, `azurerm_cognitive_deployment`,
`azurerm_machine_learning_workspace`, `azurerm_search_service`.

## current_costs

Present ONLY if billing (Azure Cost Management export) OR the OpenAI usage API ran; omit
otherwise. `{ monthly_ai_spend, services_detected[], source, breakdown[], conflicting_sources[] }`,
`source ∈ billing_data | openai_usage_api | mixed`. `breakdown[]` (present only when `mixed`):
`{ provider, monthly_spend, source }`, `provider ∈ azure | openai`. Provider-aware merge: both →
SUM with `source: mixed`; same-provider overlap → usage API wins, displaced → `conflicting_sources[]`.

## detection_signals[]

`{ method, pattern, confidence, evidence }`, `method ∈ terraform | code | live_az | openai_usage_api`.

## workloads[]

ALWAYS present (`[]` if none). One per unique `(model_id, sdk_method, structured_output)`. This is
the downstream unit of work — but note **`preferences.json` `workloads[]` is the source of truth
after Clarify confirms them**, not this array.

```jsonc
{
  "workload_id": "wl_3a1f2c", // "wl_" + sha256(model_id + "|" + sdk_method + "|" + structured_flag)[:6]
  "model_id": "gpt-4o", // MUST be one of models[].model_id
  "sdk_method": "openai.chat.completions.create",
  "capability": "text_generation", // see enum below
  "capability_confidence": "high", // high | medium | low
  "structured_output": false,
  "call_sites": [{ "file": "app/llm.py", "line": 42 }] // non-empty, POSIX repo-relative
}
```

`capability` enum: `text_generation`, `structured_output`, `image_generation`, `embedding`,
`speech_to_text`, `text_to_speech`, `document_extraction`, `image_analysis`, `speech_transcription`,
`unknown`. The capability map is `references/vendored/ai/sdk-capability-map.json` (keys on SDK call
pattern, so Azure-OpenAI-via-openai-SDK is already covered). Azure Cognitive SDK methods
(`azure.ai.vision.*`, `azure.ai.formrecognizer.*`, `azure.cognitiveservices.speech.*`,
`azure.ai.textanalytics.*`) map to `image_analysis` / `document_extraction` / `speech_transcription`
and route to `design-refs/ai.md`.

## agentic_profile

Present ONLY if `is_agentic: true`; null otherwise. Provider-agnostic (framework-based).

```jsonc
{
  "is_agentic": true,
  "framework": "langgraph", // langgraph|crewai|autogen|openai_agents|strands|custom|none
  "agents": [
    {
      "agent_id": "a1",
      "file": "...",
      "line": 0,
      "model_id": "gpt-4o",
      "tools": [],
      "memory_type": "conversation_buffer",
      "role": "..."
    }
  ],
  "orchestration_pattern": "single", // single|hierarchical|swarm|graph|sequential|unknown
  "agent_count": 1,
  "tool_count": 0,
  "has_human_in_loop": false,
  "has_memory": false,
  "memory_backend": "unknown" // redis|postgres|in_memory|vector_store|unknown
}
```

`memory_type ∈ conversation_buffer|rag|none|unknown`.

## tool_manifest[]

Present ONLY if `agentic_profile` exists (`[]` if agentic but no tools). Provider-agnostic.
`{ name, file, line, transport, auth_hint, used_by_agents[] }`, `transport ∈ function|api|mcp|unknown`,
`auth_hint ∈ none|api_key|oauth|iam|unknown`. `used_by_agents ⊆ agents[].agent_id`; length =
`agentic_profile.tool_count`.

## Azure swaps (vs gcp-to-aws's schema-discover-ai.md)

| Location                             | gcp                         | azure                                             |
| ------------------------------------ | --------------------------- | ------------------------------------------------- |
| `summary.ai_source` enum             | `gemini`                    | `azure_openai` (gemini dropped)                   |
| `metadata.profile_source` enum       | `iac_vertex`                | `iac_cognitive`                                   |
| `models[].service` examples          | `vertex_ai_*`               | `azure_openai`, `cognitive_*`, `azure_ml`         |
| `integration.primary_sdk` example    | `google-cloud-aiplatform`   | `openai` / `@azure/openai` / `azure-ai-inference` |
| `infrastructure[].type` examples     | `google_vertex_ai_endpoint` | `azurerm_cognitive_account` etc.                  |
| `detection_signals[].method`         | `live_gcloud`               | `live_az`                                         |
| `current_costs.breakdown[].provider` | `gcp`                       | `azure`                                           |
| field-name rule                      | NOT `gcp_service`           | NOT `azure_service` — the field is `service`      |

## Validation Checklist

- [ ] `summary.ai_source` is one of `azure_openai | openai | anthropic | both | other`.
- [ ] Every `models[]` entry has `model_id`, `service`, `detected_via`, `evidence`,
      `capabilities_used`, `usage_context` (exact names).
- [ ] `workloads[]` is present; every `workloads[].model_id` is in `models[].model_id`;
      `workload_id` is unique and matches the hash rule; `call_sites` non-empty.
- [ ] `agentic_profile` is present iff at least one agentic framework/signal was detected;
      `tool_manifest` present iff `agentic_profile` is.
- [ ] `current_costs` present only if billing or usage-API ran.
- [ ] No secret values anywhere (env-var/appsetting NAMES only).

## Status — build step 3 (contract)

Written as the AI-track contract. `discover-app-code.md` is the application-code producer
(build step 4, now landed). `discover-iac.md`'s Cognitive-Services path is the
infrastructure-only producer (minimal `iac_cognitive` profile).
