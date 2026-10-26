# AI Discovery Schema

**Mode boundary:** Direct BMA records actual provider/source-service/gateway provenance and never invents GCP billing, `live_gcloud`, or infrastructure evidence. GCP examples below apply only when source evidence is actually GCP/Vertex or execution is delegated from GCP.

BMA has one AI input contract: the **#415 AI workload profile**, `ai-workload-profile.json`. Its vendored schema is `references/contracts/ai-workload-profile.schema.json` (byte-identical to the canonical file). `<AI_PROFILE>` is `<run>/ai-workload-profile.json` in direct mode and `<run>/bma-input/ai-workload-profile.json` in delegated mode. The GCP public `ai-workload-profile.json` is the legacy GCP shape and is never BMA input. Every AI phase that reads the profile runs this gate first:

```
python3 <skill root>/scripts/bma-runtime.py validate-profile --profile <AI_PROFILE> [--sidecar <run>/ai-workload-sidecar.json]
```

Exit 0 means the input is valid and the phase may continue. Exit 1 means stop. A legacy-shaped document fails with `BmaLegacyProfileRejected`, which names the first legacy field. BMA has no fallback for legacy input. Do not reshape a legacy profile by hand. Direct discovery writes #415 directly, and delegated runs receive a #415 document from the GCP boundary adapter.

Convention: values shown as `X|Y` in examples mean one allowed value, not a literal pipe.

---

## ai-workload-profile.json (#415, Phase 1 output)

```json
{
  "schema_version": "1.0",
  "ai_sources": [
    {
      "provider": "google",
      "source_service": "vertex_ai",
      "model_families": ["gemini"],
      "model_evidence": "observed",
      "models": ["gemini-2.5-pro"],
      "model_observations": [
        {
          "normalized_model": "gemini-2.5-pro",
          "raw_model": "gemini-2.5-pro",
          "model_family": "gemini",
          "evidence": [
            {"provenance": "code", "confidence": "high", "detail": "src/ai/client.py:12"}
          ]
        }
      ]
    },
    {
      "provider": "openai",
      "source_service": "openai_api",
      "model_families": ["gpt"],
      "model_evidence": "not_observed",
      "models": [],
      "model_observations": []
    }
  ],
  "gateways": [
    {
      "product": "openrouter",
      "type": "llm_router",
      "upstream_evidence": "unresolved",
      "upstreams": []
    }
  ]
}
```

**Top level (closed, `additionalProperties: false`):** `schema_version` (const `"1.0"`), `ai_sources[]`, and `gateways[]`. Any other top-level key is invalid. Metadata, summaries, infrastructure, costs, and integration context are not part of this document.

**`ai_sources[]`** — one entry per provider and source_service pair. Duplicate or overlapping pairs are invalid. One provider through distinct services is valid, for example `openai/openai_api` and `openai/azure_openai`.

- `provider` — Extensible identity. It must not be `both`, `unknown`, or `openrouter`. OpenRouter is a gateway, never a provider.
- `source_service` — The service the calls go through, for example `openai_api`, `azure_openai`, `anthropic_api`, `vertex_ai`.
- `model_families` — Non-empty, unique list of families such as `claude`, `gemini`, `gpt`.
- `model_evidence` — `observed` (models are present, `models` and `model_observations` each have at least one entry) or `not_observed` (both arrays are empty).
- `models` — Unique normalized model IDs.
- `model_observations[]` — One entry per entry in `models`, with `normalized_model`, `raw_model` (the verbatim observed string), `model_family` (one of `model_families`), and a non-empty `evidence` list. Validation checks that these correspond exactly to `models`.

**Evidence:** `provenance` is one of `code`, `iac`, `live_api`, `usage_api`, `user_confirmed`. `confidence` is one of `confirmed`, `high`, `medium`, `low`. `detail` is optional. `confirmed` comes only from a user answer.

**`gateways[]`** — gateways independent of direct providers. OpenRouter appears only here.

- `product` — Gateway identity, for example `openrouter`.
- `type` — Gateway type, for example `llm_router`.
- `upstream_evidence` — `observed` (at least one upstream) or `unresolved` (`upstreams` is empty; upstreams must not be invented).
- `upstreams[]` — Each entry has `provider`, optional `source_service`, and `model_families[]` with `family`, `model_evidence`, and `models`. Provider identities follow the same rules as `ai_sources[]`.

**Derived routing:** BMA routes by `provider` and `source_service`. There is no `ai_source` enum. A profile that mixes direct providers and Azure OpenAI routes each `ai_sources[]` entry on its own. An OpenRouter gateway routes its upstreams through the BYOK path.

---

## ai-workload-sidecar.json (temporary GCP sidecar)

Workloads, the agentic profile, and the tool manifest have no #415 slot yet. Observed spend and integration context also live here, not in #415. They travel next to the #415 document in a separate sidecar file. The sidecar is **temporary**. A follow-up will fold it into #415 under a new schema version. BMA never reads these fields from `ai-workload-profile.json`.

```json
{
  "schema_version": 1,
  "kind": "BMA_GCP_AI_SIDECAR",
  "workloads": [],
  "agentic_profile": {"is_agentic": false},
  "tool_manifest": [],
  "observed_costs": {
    "monthly_ai_spend": 450,
    "services_detected": ["Vertex AI Predictions"],
    "source": "billing_data"
  },
  "integration_context": {
    "pattern": "direct_sdk",
    "frameworks": ["langchain"],
    "languages": ["python"],
    "capabilities_summary": {"text_generation": true, "streaming": true, "embeddings": true}
  }
}
```

- `schema_version` must be `1` and `kind` must be `"BMA_GCP_AI_SIDECAR"`. Keys outside the sidecar set are rejected.
- `workloads` is required and is an array. Its shape is defined below.
- `agentic_profile` and `tool_manifest` are optional and follow the agentic sections below.
- `observed_costs` is optional. It holds the observed monthly AI spend from billing or usage APIs, with the merge rules in § Usage-API merge below. Its shape is the former `current_costs` object.
- `integration_context` is optional. It holds the SDK, frameworks, languages, pattern, and capability summary that Design and Clarify read. Each key is also optional.
- `infrastructure` is optional. It is an array of source AI infrastructure resources (the former legacy `infrastructure[]`) that Design Part 4 maps to AWS equivalents. Delegated GCP runs only.
- `model_context` is optional. It is an array of `{service, model_id, capabilities_used, usage_context}` objects, one per model that had those fields. Design matches them to `ai_sources[].models` by `model_id`. Only the fields present are kept.
- `profile_origin` is optional. It is `{"terraform_primary": <bool>}`, true when the legacy profile was `iac_vertex` or `inferred_from_iac`. Clarify and Estimate use it for the Terraform-primary wording and IaC-only handling in delegated GCP runs. Direct runs derive that wording from evidence provenance.
- In delegated GCP runs the sidecar lives at `$MIGRATION_DIR/.bma-input/ai-workload-sidecar.json` (a hidden internal directory the GCP run does not publish) and is written by the GCP boundary conversion step. It carries the GCP cost, integration, infrastructure, and per-model context. In direct runs BMA writes it.
- **Follow-up:** this sidecar is temporary. A follow-up will fold `observed_costs`, `integration_context`, `infrastructure`, and `model_context` into #415 under a new schema version, and retire this file.

The sidecar is validated with `validate-profile --sidecar`. Any BMA phase that uses workloads, agentic routing, observed costs, or integration context requires the sidecar to pass.

---

## Usage-API merge (sidecar `observed_costs`)

Usage APIs (OpenAI, Anthropic, OpenRouter) and billing exports write spend into `observed_costs`. Rules, applied by the discover phase for each usage API:

- **No existing `observed_costs`** → set `{ "monthly_ai_spend", "services_detected", "source" }` from that API.
- **Existing costs for a different provider** → sum the providers, set `source: "mixed"`, and keep a per-provider `breakdown[]`. Each provider keeps its own identity. Never resolve with `max()`.
- **Existing costs for the same provider and window** → the API wins. The displaced figure goes into `observed_costs.conflicting_sources[]`, never silently resolved.
- Partial-window and cost-status stamping (`partial_window`, `cost_status`) is kept per provider where the provider's discovery doc specifies it.

**Discovery paths:** `application_code` (full profile from the code path), IaC-only (Terraform Vertex-strong discovery only, where `models` may be empty and every evidence entry has `provenance: "iac"`), or `merged` (code plus a prior IaC-only profile). None of these labels is a #415 field. The provenance lives in `evidence[].provenance`.

---

## workloads[] (sidecar, per-workload disambiguation)

Generated by `discover-app-code.md` Step 5B. Splits the detected AI usage into distinct workloads, one per unique `(model_id, sdk_method, structured_output)` tuple. Enables downstream phases to produce one Bedrock recommendation per workload.

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
- `model_id` — Same normalized model as in `ai_sources[].models` (NOT `model_name`, `source_model`)
- `sdk_method` — Fully qualified SDK method name (NOT `method`, `api_call`)
- `capability` — Inferred capability: `"text_generation"`, `"structured_output"`, `"image_generation"`, `"embedding"`, `"speech_to_text"`, `"text_to_speech"`, `"document_extraction"`, `"image_analysis"`, `"speech_transcription"`, `"unknown"` (NOT `capability_inferred`, `type`)
- `capability_confidence` — `"high"`, `"medium"`, or `"low"` (NOT `confidence`, `confidence_level`)
- `structured_output` — Boolean: true iff structured-output indicators detected in call arguments
- `call_sites` — Array of `{ "file": string, "line": integer }` — repo-relative POSIX paths

**Capability assignment rules (from `references/vendored/ai/sdk-capability-map.json`):**

| SDK Method                                                        | Default Capability                                                 | Confidence | Notes                                                                                                           |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------- |
| Methods in `sdk-capability-map.json` (not structured-output trio) | Map value                                                          | `high`     | Direct map lookup                                                                                               |
| Structured-output trio + image-output signal (`image_output_indicators` in the call, or `image_output_model_patterns` on the model_id) | `image_generation` | `high` | Checked first; image output is never a text model, even when the call also passes structured-output arguments |
| Structured-output trio + structured indicators present            | `structured_output`                                                | `high`     | Argument inspection overrides map                                                                               |
| Structured-output trio + no structured indicators                 | `text_generation`                                                  | `medium`   | Ambiguous — Clarify confirms                                                                                    |
| `documentai.*` / `vision.*` / `speech.*` methods in map           | `document_extraction`, `image_analysis`, or `speech_transcription` | `high`     | Non-generative AI service call — routes to Design's traditional-AI rubric, not the LLM model mapping tables     |
| Method not in map                                                 | `unknown`                                                          | `low`      | Clarify fallback                                                                                                |

**Validation rules:**

- `workloads[]` is always present in the sidecar (empty array if no AI detected)
- Every `workloads[].model_id` MUST exist in some `ai_sources[].models`
- `workload_id` is unique within the array and deterministic across re-runs
- `call_sites` is non-empty for every workload entry — EXCEPT a usage-only workload (see below), where the sentinel form satisfies "non-empty" without inventing a location that was never observed
- `call_sites[].file` uses repo-relative POSIX paths (forward slashes, no absolute paths) — EXCEPT the usage-only sentinel `"<usage_api>"`, which is not a real path and must not be treated as one

**Usage-only workloads (a model billed via a usage API but never located in code — e.g. `discover-openrouter-api.md` Step 4).** A usage-only model has no call site to report; do NOT invent one. Instead: `sdk_method: "usage_api"`, `structured_output: false`, `capability_confidence: "low"` (`"text_generation"` unless the usage API's own data names something more specific), and `call_sites: [{"file": "<usage_api>", "line": 0}]` — a fixed sentinel, not a real path. Every consumer of `call_sites[].file` must treat this sentinel as "no location," not as a literal file to open.

---

## agentic_profile (sidecar, conditional — present only when agentic signals detected)

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
      }
    ],
    "orchestration_pattern": "hierarchical",
    "agent_count": 1,
    "tool_count": 2,
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

## tool_manifest (sidecar, conditional — present only when agentic_profile exists)

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
