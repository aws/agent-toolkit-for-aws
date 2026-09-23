# AI Discovery Schema

Schema for `ai-workload-profile.json`. Produced by:

- **`discover-app-code.md`** when application-code AI confidence >= 70%, or
- **`discover-iac.md`** when **Vertex-strong** Terraform evidence is present (see that file’s Step 7d), producing a minimal **IaC-inferred** profile so Clarify Category F can run without app code.

**Convention**: Values shown as `X|Y` in examples indicate allowed alternatives — use exactly one value per field, not the literal pipe character.

---

## ai-workload-profile.json (Phase 1 output)

Focused profile of AI/ML workloads including models, capabilities, integration patterns, and supporting infrastructure.

```json
{
  "metadata": {
    "report_date": "2026-02-26",
    "project_directory": "/path/to/project",
    "profile_source": "application_code|iac_vertex|merged",
    "sources_analyzed": {
      "terraform": true,
      "application_code": true,
      "billing_data": false,
      "openai_usage_api": false
    }
  },

  "summary": {
    "overall_confidence": 0.95,
    "confidence_level": "very_high",
    "total_models_detected": 2,
    "languages_found": ["python"],
    "ai_source": "gemini|openai|anthropic|both|other",
    "inferred_from_iac": false
  },

  "models": [
    {
      "model_id": "gemini-pro",
      "service": "vertex_ai_generative",
      "detected_via": ["code", "terraform"],
      "evidence": [
        {
          "source": "code",
          "file": "src/ai/client.py",
          "line": 12,
          "pattern": "GenerativeModel(\"gemini-pro\")"
        },
        {
          "source": "terraform",
          "file": "vertex.tf",
          "resource": "google_vertex_ai_endpoint.main",
          "pattern": "Vertex AI endpoint resource"
        }
      ],
      "capabilities_used": ["text_generation", "streaming"],
      "usage_context": "Recommendation engine - generates product recommendations from user profiles"
    },
    {
      "model_id": "text-embedding-004",
      "service": "vertex_ai_embeddings",
      "detected_via": ["code"],
      "evidence": [
        {
          "source": "code",
          "file": "src/embeddings/indexer.py",
          "line": 5,
          "pattern": "VertexAIEmbeddings()"
        }
      ],
      "capabilities_used": ["embeddings"],
      "usage_context": "Document indexing for semantic search"
    }
  ],

  "integration": {
    "primary_sdk": "google-cloud-aiplatform",
    "sdk_version": "1.38.0",
    "frameworks": ["langchain"],
    "languages": ["python"],
    "pattern": "direct_sdk",
    "gateway_type": "llm_router|api_gateway|voice_platform|framework|direct|null",
    "capabilities_summary": {
      "text_generation": true,
      "streaming": true,
      "function_calling": false,
      "vision": false,
      "embeddings": true,
      "batch_processing": false
    }
  },

  "infrastructure": [
    {
      "address": "google_vertex_ai_endpoint.main",
      "type": "google_vertex_ai_endpoint",
      "file": "vertex.tf",
      "config": {
        "display_name": "recommendation-endpoint",
        "location": "us-central1"
      }
    },
    {
      "address": "google_service_account.vertex_sa",
      "type": "google_service_account",
      "file": "iam.tf",
      "role": "supports_ai",
      "config": {
        "account_id": "vertex-ai-sa"
      }
    }
  ],

  "current_costs": {
    "monthly_ai_spend": 450,
    "services_detected": ["Vertex AI Predictions", "Generative AI API"],
    "source": "billing_data|openai_usage_api|mixed",
    "breakdown": [
      { "provider": "openai", "monthly_spend": 105, "source": "openai_usage_api" },
      { "provider": "gcp", "monthly_spend": 345, "source": "billing_data" }
    ],
    "conflicting_sources": []
  },

  "detection_signals": [
    {
      "method": "terraform",
      "pattern": "google_vertex_ai_endpoint resource",
      "confidence": 0.95,
      "evidence": "Found resource 'main' in vertex.tf"
    },
    {
      "method": "code",
      "pattern": "google.cloud.aiplatform import",
      "confidence": 0.95,
      "evidence": "Found in src/ai/client.py line 3"
    }
  ]
}
```

**Profile source and IaC inference:**

- `metadata.profile_source` — `"application_code"` (full profile from code path), `"iac_vertex"` (minimal profile from Terraform Vertex-strong discovery only), or `"merged"` (code + pre-existing IaC profile combined in `discover-app-code.md`).
- `summary.inferred_from_iac` — `true` when the profile was produced or substantially completed without application code analysis (IaC-only or unknown integration until Clarify). `false` when code analysis drove model/SDK detection.

**CRITICAL Field Names** (use EXACTLY these keys):

- `model_id` — Model identifier string (NOT `model_name`, `name`)
- `service` — GCP service category (NOT `service_type`, `gcp_service`)
- `detected_via` — Array of detection sources (NOT `detection_method`, `source`)
- `capabilities_used` — Array of capability strings per model (NOT `capabilities`, `features`)
- `usage_context` — Human-readable description of what the model does (NOT `description`, `purpose`)
- `pattern` — Integration pattern in `integration` object: `direct_sdk`, `framework`, `rest_api`, `mixed`, or `unknown` when not inferable (typical for IaC-only profiles) (NOT `integration_type`, `method`)
- `gateway_type` — Gateway/router type in `integration` object: `"llm_router"`, `"api_gateway"`, `"voice_platform"`, `"framework"`, `"direct"`, or `null`
- `capabilities_summary` — Boolean map in `integration` object (NOT `capabilities`, `feature_flags`)
- `ai_source` — Source AI provider in `summary` object: `"gemini"`, `"openai"`, `"anthropic"`, `"both"`, or `"other"`

**Key Fields:**

- `metadata.sources_analyzed` — Which data sources were provided (affects which sections are populated)
- `summary.overall_confidence` — Combined detection confidence from all signals
- `models[]` — Each distinct AI model/service detected, with evidence and capabilities. **May be empty** for `profile_source: "iac_vertex"` when no model IDs can be inferred from Terraform alone; Clarify and Design must not assume non-empty.
- `integration.pattern` — How the app connects to AI (`direct_sdk`, `framework`, `rest_api`, `mixed`, or `unknown` for IaC-only)
- `integration.capabilities_summary` — Union of all capabilities across all models
- `infrastructure[]` — Terraform resources related to AI (empty array if no Terraform provided)
- `current_costs` — Present ONLY if billing data OR OpenAI usage API data was provided; omitted entirely otherwise. `source` records provenance. Merge is provider-aware: billing CSVs measure GCP/Vertex spend, the usage API measures OpenAI spend — when both exist for DIFFERENT providers, `monthly_ai_spend` is their SUM with `source: "mixed"` and the per-provider split in `breakdown[]` (never max/pick-one — that drops a provider). Same-provider overlap: the usage API wins and the displaced figure lands in `conflicting_sources[]` (never silently resolved). `breakdown` is present only for `source: "mixed"`.
- `detection_signals[]` — Raw signals from AI detection for transparency. `method` values include `terraform`, `code`, `live_gcloud`, and `openai_usage_api`.

**Conditional sections:**

- `current_costs` — Include ONLY if billing data was provided (billing discovery ran) or OpenAI usage API discovery ran (`discover-openai-api.md`). Omit entirely if neither.
- `infrastructure` — Set to `[]` if no Terraform files were provided (IaC discovery did not run).
- `agentic_profile` — Include ONLY if agentic signals detected (`is_agentic: true`). Omit entirely otherwise.
- `tool_manifest` — Include ONLY if `agentic_profile` exists. Set to `[]` if agentic but no tools detected.
- `workloads` — Always present. Empty array `[]` if no AI call sites detected.

---

## workloads[] (per-workload disambiguation)

Generated by `discover-app-code.md` Step 5B. Splits the detected AI usage into distinct workloads — one per unique `(model_id, sdk_method, structured_output)` tuple. Enables downstream phases to produce one Bedrock recommendation per workload.

```json
{
  "workloads": [
    {
      "workload_id": "wl_3a1f2c",
      "model_id": "gemini-2.5-flash",
      "sdk_method": "ai.models.generateContent",
      "capability": "text_generation",
      "capability_confidence": "medium",
      "structured_output": false,
      "call_sites": [
        { "file": "lib/gemini.ts", "line": 11 }
      ]
    },
    {
      "workload_id": "wl_8e22b4",
      "model_id": "gemini-2.5-flash",
      "sdk_method": "ai.models.generateContent",
      "capability": "structured_output",
      "capability_confidence": "high",
      "structured_output": true,
      "call_sites": [
        { "file": "lib/gemini.ts", "line": 27 }
      ]
    }
  ]
}
```

**CRITICAL Field Names** (use EXACTLY these keys):

- `workload_id` — Deterministic hash: `"wl_" + sha256(model_id + "|" + sdk_method + "|" + structured_flag)[:6]` (NOT `id`, `name`)
- `model_id` — Same model_id as in `models[]` (NOT `model_name`, `source_model`)
- `sdk_method` — Fully qualified SDK method name (NOT `method`, `api_call`)
- `capability` — Inferred capability: `"text_generation"`, `"structured_output"`, `"image_generation"`, `"embedding"`, `"speech_to_text"`, `"text_to_speech"`, `"document_extraction"`, `"image_analysis"`, `"speech_transcription"`, `"unknown"` (NOT `capability_inferred`, `type`)
- `capability_confidence` — `"high"`, `"medium"`, or `"low"` (NOT `confidence`, `confidence_level`)
- `structured_output` — Boolean: true iff structured-output indicators detected in call arguments
- `call_sites` — Array of `{ "file": string, "line": integer }` — repo-relative POSIX paths

**Capability assignment rules (from `data/sdk-capability-map.json`):**

| SDK Method                                                        | Default Capability                                                 | Confidence | Notes                                                                                                           |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------- |
| Methods in `sdk-capability-map.json` (not structured-output trio) | Map value                                                          | `high`     | Direct map lookup                                                                                               |
| Structured-output trio + structured indicators present            | `structured_output`                                                | `high`     | Argument inspection overrides map                                                                               |
| Structured-output trio + no structured indicators                 | `text_generation`                                                  | `medium`   | Ambiguous — Clarify confirms                                                                                    |
| `documentai.*` / `vision.*` / `speech.*` methods in map           | `document_extraction`, `image_analysis`, or `speech_transcription` | `high`     | GCP non-generative AI service call — routes to Design's traditional-AI rubric, not the LLM model mapping tables |
| Method not in map                                                 | `unknown`                                                          | `low`      | Clarify fallback                                                                                                |

**Validation rules:**

- `workloads[]` is always present (empty array if no AI detected)
- Every `workloads[].model_id` MUST exist in `models[].model_id`
- `workload_id` is unique within the array and deterministic across re-runs
- `call_sites` is non-empty for every workload entry
- `call_sites[].file` uses repo-relative POSIX paths (forward slashes, no absolute paths)

---

## agentic_profile (conditional — present only when agentic signals detected)

Generated by `discover-app-code.md` Step 3.5 when agentic framework signals are found. Captures agent architecture, orchestration patterns, and memory usage.

```json
{
  "agentic_profile": {
    "is_agentic": true,
    "framework": "langgraph|crewai|autogen|openai_agents|strands|custom|none",
    "agents": [
      {
        "agent_id": "research-agent",
        "file": "src/agents/researcher.py",
        "line": 45,
        "model_id": "gpt-4o",
        "tools": ["web_search", "document_reader"],
        "memory_type": "conversation_buffer|rag|none|unknown",
        "role": "Researches topics and gathers information"
      },
      {
        "agent_id": "writer-agent",
        "file": "src/agents/writer.py",
        "line": 22,
        "model_id": "gpt-4o-mini",
        "tools": ["file_write"],
        "memory_type": "none",
        "role": "Writes reports from research output"
      }
    ],
    "orchestration_pattern": "hierarchical",
    "agent_count": 2,
    "tool_count": 3,
    "has_human_in_loop": false,
    "has_memory": true,
    "memory_backend": "in_memory"
  }
}
```

**CRITICAL Field Names** (use EXACTLY these keys):

- `agent_id` — Agent identifier (NOT `name`, `agent_name`, `id`)
- `framework` — Agentic framework detected (NOT `agentic_framework`, `agent_framework`, `orchestration_framework`)
- `orchestration_pattern` — How agents coordinate (NOT `pattern`, `orchestration_type`, `coordination`)
- `memory_type` — Per-agent memory type (NOT `memory`, `memory_kind`)
- `memory_backend` — System-level memory storage (NOT `memory_store`, `backend`)
- `has_human_in_loop` — Boolean (NOT `human_in_loop`, `hitl`)

**Allowed values:**

- `framework`: `"langgraph"`, `"crewai"`, `"autogen"`, `"openai_agents"`, `"strands"`, `"custom"`, `"none"`
- `orchestration_pattern`: `"single"`, `"hierarchical"`, `"swarm"`, `"graph"`, `"sequential"`, `"unknown"`
- `agents[].memory_type`: `"conversation_buffer"`, `"rag"`, `"none"`, `"unknown"`
- `memory_backend`: `"redis"`, `"postgres"`, `"in_memory"`, `"vector_store"`, `"unknown"`

**Classification rules for `orchestration_pattern`:**

| Pattern        | Evidence                                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------------- |
| `single`       | One agent definition, no delegation or coordination                                                                 |
| `hierarchical` | One orchestrator agent delegates to specialist agents (agents-as-tools, manager/worker)                             |
| `swarm`        | Multiple agents share memory/state, no fixed hierarchy                                                              |
| `graph`        | Explicit node/edge definitions, conditional routing between agents (LangGraph `StateGraph`, Strands `GraphBuilder`) |
| `sequential`   | Agents execute in fixed order (pipeline), output of one feeds next                                                  |
| `unknown`      | Agentic signals detected but orchestration pattern unclear                                                          |

**Key fields:**

- `is_agentic` — Always `true` when this section exists (redundant but explicit for downstream gates)
- `framework` — Primary agentic framework; if multiple detected, use the one with the most agent definitions
- `agents[]` — Each distinct agent/role detected; include all that can be identified from code
- `agents[].model_id` — The LLM model this agent uses; `"unknown"` if not extractable from code
- `agents[].tools` — Tool names attached to this agent; empty array `[]` if no tools detected
- `agent_count` — Must equal length of `agents[]` array
- `tool_count` — Total unique tools across all agents (deduplicated)

---

## tool_manifest (conditional — present only when agentic_profile exists)

Generated by `discover-app-code.md` Step 6.5. Inventories tool definitions found in agent code. This is discovery only — no migration recommendations.

```json
{
  "tool_manifest": [
    {
      "name": "web_search",
      "file": "src/tools/search.py",
      "line": 10,
      "transport": "api",
      "auth_hint": "api_key",
      "used_by_agents": ["research-agent"]
    },
    {
      "name": "document_reader",
      "file": "src/tools/reader.py",
      "line": 5,
      "transport": "function",
      "auth_hint": "none",
      "used_by_agents": ["research-agent"]
    },
    {
      "name": "file_write",
      "file": "src/tools/writer.py",
      "line": 8,
      "transport": "function",
      "auth_hint": "none",
      "used_by_agents": ["writer-agent"]
    }
  ]
}
```

**CRITICAL Field Names** (use EXACTLY these keys):

- `name` — Tool name as defined in code (NOT `tool_name`, `tool_id`, `id`)
- `transport` — How the tool communicates (NOT `transport_type`, `type`, `protocol`)
- `auth_hint` — Detected authentication pattern (NOT `auth`, `auth_type`, `authentication`)
- `used_by_agents` — Array of `agent_id` values that reference this tool (NOT `agents`, `consumers`)

**Allowed values:**

- `transport`: `"function"` (local Python/JS/Go function), `"api"` (HTTP/REST call), `"mcp"` (MCP server), `"unknown"`
- `auth_hint`: `"none"`, `"api_key"`, `"oauth"`, `"iam"`, `"unknown"`

**Classification rules for `transport`:**

| Transport  | Evidence                                                                                       |
| ---------- | ---------------------------------------------------------------------------------------------- |
| `function` | `@tool` decorator on a local function, inline function definition, no network call in body     |
| `api`      | HTTP client calls (`requests.get`, `httpx`, `fetch`) inside tool body, external URL references |
| `mcp`      | MCP client imports, MCP server URL in tool config, `mcp.client` usage                          |
| `unknown`  | Tool schema defined but implementation not inspectable or ambiguous                            |

**Classification rules for `auth_hint`:**

| Auth hint | Evidence                                                            |
| --------- | ------------------------------------------------------------------- |
| `none`    | No credentials, tokens, or auth headers in tool implementation      |
| `api_key` | API key env var, `Authorization: Bearer` header, `x-api-key` header |
| `oauth`   | OAuth flow, token refresh, `client_id`/`client_secret` patterns     |
| `iam`     | AWS SigV4, boto3 client usage, IAM role assumption                  |
| `unknown` | Auth pattern not determinable from code inspection                  |

**Validation rules:**

- Every `agent_id` in `used_by_agents` MUST exist in `agentic_profile.agents[].agent_id`
- `tool_manifest` length MUST equal `agentic_profile.tool_count` (deduplicated tool count)
- If `agentic_profile` exists but no tools detected: set `tool_manifest: []` and `agentic_profile.tool_count: 0`
