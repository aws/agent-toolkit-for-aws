# Discover Phase: App Code Discovery

> Self-contained source-neutral application code discovery. Scans source and dependency manifests for AI providers, SDKs, frameworks, gateways, models, capabilities, and call sites. At AI confidence >= 70%, it writes the #415 `ai-workload-profile.json` and the temporary `ai-workload-sidecar.json` (workloads, agentic profile, tool manifest). In delegated GCP mode only, the explicitly marked adapter sections may also preserve selected-base GCP SDK/resource evidence. `$AI_PROFILE` is `$MIGRATION_DIR/ai-workload-profile.json` in direct mode and `$MIGRATION_DIR/.bma-input/ai-workload-profile.json` in delegated mode (`$AI_SIDECAR` is `$AI_SIDECAR` in direct mode and `$MIGRATION_DIR/.bma-input/ai-workload-sidecar.json` in delegated mode) (the GCP adapter writes the delegated input there; the public GCP file keeps its legacy content).
> If no source code files are found, exits cleanly with no output.

**Dead-end handling:** If this file exits without producing artifacts (no source code found, or AI confidence < 70%), report the signals found (if any) and confidence level. In direct mode, ask for supported application source/dependency evidence or explicit OpenAI, Anthropic, or OpenRouter provider-usage intent. In delegated GCP mode only, ask for Terraform files or billing exports.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Self-Scan for Source Code

Recursively scan the entire target directory tree for source code and dependency manifests:

**Source code:**

- `**/*.py` (Python)
- `**/*.js`, `**/*.ts`, `**/*.jsx`, `**/*.tsx` (JavaScript/TypeScript)
- `**/*.go` (Go)
- `**/*.java` (Java)
- `**/*.scala`, `**/*.kt`, `**/*.rs` (Other)

**Dependency manifests:**

- `requirements.txt`, `setup.py`, `pyproject.toml`, `Pipfile` (Python)
- `package.json`, `package-lock.json`, `yarn.lock` (JavaScript)
- `go.mod`, `go.sum` (Go)
- `pom.xml`, `build.gradle` (Java)

**Exit gate:** If NO source code files or dependency manifests are found, **exit cleanly**. Return no output artifacts. Other sub-discovery files may still produce artifacts.

**Secret file exclusion (HARD — no exceptions):** Before scanning any file, skip the following paths entirely — do NOT read, parse, or include their contents in any output artifact:

- `.env*` (matches `.env`, `.env.local`, `.env.production`, `.env.staging`, and any other `.env` variant)
- `credentials.json`, `service-account.json`, `*-service-account.json`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `secrets.yaml`, `secrets.yml`

If any of these files are encountered during the recursive scan, log: "Skipped [filename] — potential secret file excluded from discovery scope." Do NOT include them in source file counts or any output.

---

## Step 0.5: Auth SDK Exclusion List

Before scanning for AI provider imports, check for third-party auth SDK imports. These are **recognized but excluded** from migration — they carry no AWS recommendation.

| Import Pattern                                                           | Auth Provider      |
| ------------------------------------------------------------------------ | ------------------ |
| `auth0` / `@auth0/` / `auth0-python`                                     | Auth0              |
| `@supabase/supabase-js` / `supabase` (with `.auth`)                      | Supabase Auth      |
| `firebase-admin` (with `.auth`) / `firebase/auth` / `@angular/fire/auth` | Firebase Auth      |
| `@clerk/` / `clerk-sdk-python`                                           | Clerk              |
| `@okta/` / `okta-sdk-python` / `okta-jwt-verifier`                       | Okta               |
| `keycloak` / `@keycloak/keycloak-admin-client` / `python-keycloak`       | Keycloak           |
| `next-auth` / `@auth/core`                                               | NextAuth / Auth.js |

If any auth SDK import is detected:

1. Log: "Detected [provider] auth SDK in [file] — excluded from migration scope. Keep your existing auth solution."
2. Do **not** infer a source-cloud resource or recommend an AWS replacement
3. Do **not** include in the AI signal scan or any output artifact

## Step 1: Delegated GCP SDK Adapter

**Mode gate:** Run Steps 1 and 2 only when the invocation context is `mode: delegated` with outer owner `GCP_TO_AWS`. Direct BMA MUST skip both sections and MUST NOT infer source-cloud infrastructure from ordinary application imports. This adapter preserves existing GCP behavior without making the canonical direct runtime GCP-dependent.

In delegated GCP mode, scan source files for GCP service imports:

- `google.cloud` (Python: `from google.cloud import ...`)
- `@google-cloud/` (JS/TS: `import ... from '@google-cloud/...'`)
- `cloud.google.com/go` (Go: `import "cloud.google.com/go/..."`)
- `com.google.cloud` (Java: `import com.google.cloud.*`)

For each import found, record:

- `file_path` — Source file containing the import
- `import_statement` — The actual import line
- `inferred_gcp_service` — Which GCP service this maps to
- `confidence` — 0.60-0.80 (lower than IaC since we're inferring from code, not reading config)

---

## Step 2: Delegated GCP Resource Inference

In delegated GCP mode only, map SDK imports to likely GCP resources. These are inferred — they supplement IaC evidence but at lower confidence:

| Import pattern               | Inferred GCP resource |
| ---------------------------- | --------------------- |
| `google.cloud.storage`       | Cloud Storage bucket  |
| `google.cloud.firestore`     | Firestore database    |
| `google.cloud.pubsub`        | Pub/Sub topic         |
| `google.cloud.bigquery`      | BigQuery dataset      |
| `google.cloud.sql`           | Cloud SQL instance    |
| `google.cloud.run`           | Cloud Run service     |
| `google.cloud.functions`     | Cloud Functions       |
| `google.cloud.secretmanager` | Secret Manager        |
| `redis` / `ioredis`          | Redis instance        |

Confidence for inferred resources: 0.60-0.80 (inferring existence, not reading infrastructure config).

---

## Step 2.5: WebSocket Signal Scan

After Step 2 (Infer Resources from Code), scan source files for WebSocket / long-lived connection patterns:

| Pattern         | Evidence                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| WebSocket API   | `websocket`, `WebSocket`, `socket.io`, `@nestjs/websockets`, FastAPI `WebSocket`, `ws` package imports |
| SSE / long-poll | `EventSource`, `text/event-stream`, long-polling handlers                                              |

Record in discovery metadata (do not write a separate file):

- `websocket_signals_found`: `true` if any pattern matches active (non-commented) code
- `websocket_signal_files`: array of file paths where matches were found

If **no matches**, set `websocket_signals_found: false`. Clarify Step 2 uses this to skip Q9 with `websocket: false` extracted **only when this step ran** (source files were found).

If **no source code files were found** (Step 0 exit gate), do **not** set `websocket_signals_found` — Clarify must ask Q9; absence of a scan is not evidence of no WebSockets.

---

## Step 2.7: Infrastructure architecture profiling is not applicable

BMA does not infer or write compute-architecture (`graviton_profile`) inventory in any mode. That remains owned by a source-cloud infrastructure skill when one participates: in delegated GCP mode the GCP controller already ran its own `discover-app-graviton.md` before loading this file; do not emit, modify, or drop its `graviton_profile`. Continue to Step 3 without changing the neutral AI profile.

---

## Step 3: Flag AI Signals

Scan source code files and dependency manifests for AI-relevant patterns. For each match, record the pattern, file location, and confidence score.

| Pattern                       | What to look for                                                                                                                                          | Confidence |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 2.1 Google AI Platform SDK    | Imports: `google.cloud.aiplatform` (Python), `@google-cloud/aiplatform` (JS), `cloud.google.com/go/aiplatform` (Go), `com.google.cloud.aiplatform` (Java) | 95%        |
| 2.2 BigQuery ML SDK           | `google.cloud.bigquery` + ML operations; SQL containing `CREATE MODEL` or `ML.*`                                                                          | 85%        |
| 2.3 LLM SDKs (Gemini)         | Imports: `google.generativeai`, `vertexai.generative_models`, Gemini model strings (`gemini-pro`, `gemini-2.5-flash`, etc.)                               | 98%        |
| 2.4 LLM SDKs (OpenAI)         | Imports: `openai`, `from openai import OpenAI`, `client.chat.completions.create()`, model strings (`gpt-4o`, `gpt-4.1`, `o3`, etc.)                       | 98%        |
| 2.5 LLM SDKs (Other)          | Imports: `anthropic`, `cohere`, `mistralai`, other LLM provider SDKs                                                                                      | 98%        |
| 2.6 Document/Vision/Speech AI | Imports: `google.cloud.documentai*`, `google.cloud.vision*`, `google.cloud.speech*`, `google.cloud.translate*`, `google.cloud.dialogflow*`                | 90%        |
| 2.7 Embeddings & RAG          | `langchain` + `VertexAIEmbeddings`; `llama_index` + Vertex AI; vector database usage with embeddings                                                      | 85%        |

Also check dependency manifests for AI/ML SDK dependencies:

- `google-cloud-aiplatform`
- `google-cloud-vertexai`
- `google-cloud-bigquery-ml`
- `google-cloud-language`
- `google-cloud-vision`
- `google-cloud-speech`
- `openai` (OpenAI SDK — applications on any hosting environment may use OpenAI directly)
- `anthropic` (Anthropic SDK)
- `litellm` (LLM router — indicates gateway usage)
- `langchain`, `langchain-google-vertexai`, `langchain-openai`, `langchain-aws` (orchestration frameworks)

---

## Step 3B: Agentic Framework Signals

Scan source code and dependency manifests for agentic framework patterns. These are separate from AI model signals — they indicate agent orchestration, not just LLM usage.

| Pattern                | What to look for                                                                                                                                               | Confidence |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 3B.1 LangGraph         | `from langgraph` imports, `StateGraph(`, `add_node(`, `add_edge(`, `.compile()`                                                                                | 95%        |
| 3B.2 CrewAI            | `from crewai` imports, `Crew(`, `Agent(` with `role=`, `Task(` class definitions                                                                               | 95%        |
| 3B.3 AutoGen           | `from autogen` imports, `AssistantAgent(`, `GroupChat(`, `ConversableAgent(`                                                                                   | 95%        |
| 3B.4 OpenAI Agents SDK | `from openai.agents` or `from agents import`, `openai.beta.assistants`, `Runner(`                                                                              | 95%        |
| 3B.5 Strands Agents    | `from strands` imports, `Agent(` with `tools=`, `Swarm(`, `GraphBuilder(`                                                                                      | 95%        |
| 3B.5a Pydantic AI      | `from pydantic_ai import Agent`, `from pydantic_ai.models` imports, `Agent(model=`, `.run_sync(`, `.run(`                                                      | 95%        |
| 3B.5b Agno             | `from agno.agent import Agent`, `from agno.models` imports, `Agent(model=`, `Team(`, `.print_response(`                                                        | 95%        |
| 3B.6 Custom agent loop | `while` loop body containing BOTH an LLM call (completions/generate) AND tool execution (function dispatch from model output) AND result parsing back to model | 80%        |
| 3B.7 Tool definitions  | `@tool` decorators, `function_declarations=`, `tools=[{...schema...}]`, tool schema objects with `name`+`description`+`parameters`                             | 90%        |
| 3B.8 MCP integration   | `from mcp.server` or `from mcp.client`, `mcp.json` config files, `MCPClient(`                                                                                  | 90%        |
| 3B.9 Agent memory      | `ConversationBufferMemory(`, `ChatMessageHistory(`, `MemorySaver(`, vector store retrieval feeding agent context                                               | 85%        |

Also check dependency manifests for agentic framework dependencies:

- `langgraph` (LangGraph)
- `crewai` (CrewAI)
- `pyautogen` or `autogen` (AutoGen)
- `openai` with agents imports (OpenAI Agents SDK — same package, different import path)
- `strands-agents` (Strands Agents SDK)
- `pydantic-ai` (Pydantic AI)
- `agno` (Agno)
- `mcp` (Model Context Protocol SDK)

---

## Step 3.5: Agentic Classification Gate

Determine whether the codebase contains agentic workflows. Execute these rules in order:

1. If ANY framework signal from 3B.1–3B.5b detected → set `is_agentic: true`, set `framework` to the detected framework name
2. If NO framework signal BUT 3B.6 (custom agent loop) detected → set `is_agentic: true`, set `framework: "custom"`
3. If 3B.7 (tool definitions) detected WITH an LLM call in a loop pattern → set `is_agentic: true`, set `framework: "custom"`
4. If ONLY 3B.8 (MCP integration) detected WITHOUT an agent loop → set `is_agentic: false` (MCP alone does not imply agent orchestration)
5. If ONLY 3B.9 (agent memory) detected WITHOUT an agent loop or framework → set `is_agentic: false`
6. If NO agentic signals detected → set `is_agentic: false`

**If multiple frameworks detected:** Set `framework` to the one with the most agent definitions. Record the others in the discovery notes.

**If `is_agentic: false`:** Skip Steps 5.5 and 6.5. Continue to Step 4.

**If `is_agentic: true`:** Continue to Step 4, then execute Steps 5.5 and 6.5 after Step 5.

---

## Step 4: AI Detection Gate

Compute overall AI confidence from all signals found in Step 3:

```text
IF (Multiple strong signals: LLM SDK + AI Platform SDK)
  THEN confidence = 95%+ (very high)

IF (Any one strong signal: LLM SDK, AI Platform SDK, Generative AI imports)
  THEN confidence = 90%+ (high)

IF (Weaker signals only: BigQuery ML, variable patterns)
  THEN confidence = 60-70% (medium)

IF (No signals found)
  THEN confidence = 0% (no AI workload detected)
```

### False Positive Checklist

Before finalizing AI detection, verify signals are genuine:

- **BigQuery alone is not AI** — Require `google_bigquery_ml_model` or `CREATE MODEL` SQL. A `google_bigquery_dataset` by itself is standard analytics.
- **Vector database alone is not AI** — Require embeddings library imports (langchain, llama-index). A Firestore/Datastore by itself is a regular database.
- **Dead/commented-out code excluded** — Only count active code.

**Exit gate:** If overall AI confidence < 70%:

- **If** `$AI_PROFILE` **already exists** as an IaC-only #415 profile (every evidence entry has `provenance: "iac"`, from `discover-iac.md` Step 7d — strong Vertex Terraform): **exit cleanly** without deleting or modifying that file. Report to the parent orchestrator: signals found, confidence below 70%, and that the **IaC-inferred AI profile is retained** for Clarify.
- **Otherwise:** Do **not** generate `ai-workload-profile.json`. Report signals found, confidence level, and reason for not generating the AI profile. In delegated GCP mode, inferred resources from Steps 1-2 remain available to GCP sub-discoverers and the parent may request Terraform files or billing exports. In direct mode, request supported application source/dependency evidence or explicit OpenAI, Anthropic, or OpenRouter provider-usage intent; do not request Terraform or billing inputs.

**If confidence >= 70%**, continue to Steps 5-8 below.

---

## Step 5: Extract AI Model Details

For each AI signal found during detection, extract model-level details:

**From application code:**

Scan files that contained AI signals for specific model information:

- **Model identifiers** — Look for model name strings passed to constructors or API calls:

  **Gemini/Vertex AI patterns:**
  - `GenerativeModel("gemini-pro")` -> model_id: `"gemini-pro"`
  - `aiplatform.Model.list(filter='display_name="my-model"')` -> model_id: `"my-model"`
  - `TextEmbeddingModel.from_pretrained("text-embedding-004")` -> model_id: `"text-embedding-004"`
  - Look for Gemini model string patterns: `gemini-pro`, `gemini-1.5-*`, `gemini-2.0-*`, `gemini-2.5-*`, `gemini-3-*`, `gemini-3.1-*` — including versioned variants like `gemini-2.5-flash-latest`, `gemini-2.5-flash-preview-*`, `gemini-2.5-flash-thinking`, `gemini-2.5-pro-preview-*`. Normalize all `gemini-2.5-flash-*` variants to `model_id: "gemini-2.5-flash"` (or `"gemini-2.5-flash-thinking"` if the thinking variant is explicit). Normalize all `gemini-2.5-pro-*` variants to `model_id: "gemini-2.5-pro"`. Record the raw string as that model's `raw_model` in `model_observations`.
  - **Gemini 1.5 Legacy:** Normalize `gemini-1.5-flash*` → `model_id: "gemini-1.5-flash"` and `gemini-1.5-pro*` → `model_id: "gemini-1.5-pro"`. Keep the normalized `model_id` in `ai_sources[].models`. BMA treats `gemini-1.5-pro` as retired and leaves its pricing unavailable. The same applies to the other IDs in BMA's `RETIRED_MODELS` list (shut-down Imagen and Gemini image-preview models); keep their raw IDs in `ai_sources[].models` so BMA can flag them as retired, not priced. Surface in the AI Context Summary during Clarify: "⚠️ Gemini 1.5 Flash/Pro is past EOL (Sep 2025). Plan to upgrade the source model to 2.5 Flash/Pro as part of or before the AWS migration."

  **OpenAI patterns:**
  - `client.chat.completions.create(model="gpt-4o")` -> model_id: `"gpt-4o"`
  - `openai.ChatCompletion.create(model="gpt-4")` -> model_id: `"gpt-4"` (legacy API)
  - `client.embeddings.create(model="text-embedding-3-small")` -> model_id: `"text-embedding-3-small"`
  - Model strings in config files or environment variables: `OPENAI_MODEL`, `MODEL_NAME`, etc.
  - Look for model string patterns: `gpt-*`, `o1*`, `o3*`, `o4*`, `text-embedding-*`, `dall-e-*`, `gpt-image-*`, `whisper-*`, `tts-*`

  **Anthropic patterns:**
  - `anthropic.Anthropic().messages.create(model="claude-*")` -> model_id: `"claude-*"`
  - Look for model string patterns: `claude-3-*`, `claude-sonnet-*`, `claude-haiku-*`, `claude-opus-*`

- **Capabilities used** — Determine from API calls and method signatures:
  - `text_generation`: `generate_content()`, `predict()`, `messages.create()`, `chat.completions.create()`
  - `streaming`: `generate_content(stream=True)`, `stream()`, `stream=True` in OpenAI calls, async iterators
  - `function_calling`: `tools=` parameter, `function_declarations=`, `functions=` (OpenAI legacy), tool definitions
  - `vision`: image bytes, image URLs, or multimodal content passed as input
  - `embeddings`: `TextEmbeddingModel`, `VertexAIEmbeddings`, `client.embeddings.create()`, embedding API calls
  - `batch_processing`: batch predict calls, bulk processing patterns
  - `json_mode`: `response_format={"type": "json_object"}` (OpenAI), structured output schemas
  - `image_generation`: `client.images.generate()` (gpt-image / DALL-E legacy), Imagen API calls
  - `speech_to_text`: `client.audio.transcriptions.create()` (Whisper)
  - `text_to_speech`: `client.audio.speech.create()` (TTS)

- **Usage context** — Infer from the combination of:
  - File path and module name (e.g., `src/search/indexer.py` -> search/indexing)
  - Class and function names (e.g., `RecommendationEngine.get_recommendations` -> recommendations)
  - Import statements (e.g., `from langchain.embeddings` -> embeddings/RAG)
  - Surrounding code context (what data flows in and out of the AI call)

**From Terraform (if IaC discovery also ran):**

- Vertex AI endpoint configurations (display name, location, machine type)
- Model deployment settings (traffic split, scaling)
- Resource addresses for cross-referencing with code

**From billing data (if billing discovery also ran):**

- Which AI services have billing line items
- Monthly spend per AI service

---

## Step 5B: Disambiguate AI Workloads by SDK Method

After extracting model details (Step 5), split the detected AI usage into distinct **workloads** — one per unique combination of `(model_id, sdk_method, structured_output)`. This enables downstream phases to produce one Bedrock recommendation per workload instead of collapsing multiple capabilities into a single recommendation.

**Load** `references/vendored/ai/sdk-capability-map.json` from the plugin source. If missing or malformed, halt with diagnostic: `"[Discover] Failed to load sdk-capability-map.json"`.

**For each AI call site detected in Steps 3–5:**

1. **Resolve the SDK method and classify the call** — resolve the fully qualified method name (e.g., `ai.models.generateContent`, `openai.chat.completions.create`, `openai.images.generate`), then run:

   `python3 <skill root>/scripts/bma-runtime.py classify-ai-call --source <file> --line <line> --model <model_id> --method <method>`

   The script applies the map rules and prints JSON with `capability`, `capability_confidence`, and `structured_output`. Use its output as written; do not re-derive the capability by hand. Methods not in the map return `capability: "unknown"`, `capability_confidence: "low"`.

   The rules it applies, in order:
   - For methods in `structured_output_trio`, image output is checked first: the call's arguments contain one of the map's `image_output_indicators` (for example `responseModalities: [Modality.IMAGE]`), or the model_id contains one of `image_output_model_patterns` (for example `gemini-3.1-flash-image`, `imagen-*`, `dall-e-*`, `gpt-image-*`). Match → `capability: "image_generation"`, `capability_confidence: "high"`, `structured_output: false`. Image output is not text, so it never falls through to the text rule.
   - Next, for trio methods without image output: if the call passes any of `response_format`, `responseSchema`, or `responseMimeType` → `capability: "structured_output"`, `capability_confidence: "high"`, `structured_output: true`. Otherwise → `capability: "text_generation"`, `capability_confidence: "medium"`, `structured_output: false`.
   - For methods NOT in the trio, the map value is used with `capability_confidence: "high"`.

2. **Collapse by workload tuple** — group call sites sharing the same `(model_id, sdk_method, structured_output)` into a single workload entry. Record all `call_sites` (file + line).

3. **Generate workload_id** — deterministic hash: `"wl_" + sha256(model_id + "|" + sdk_method + "|" + ("structured" if structured_output else "plain"))[:6]`

**Output:** Write the `workloads` array to the sidecar `ai-workload-sidecar.json`. It does not go into the #415 profile.

```json
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
  },
  {
    "workload_id": "wl_c97d10",
    "model_id": "imagen-3.0-generate-001",
    "sdk_method": "ai.models.generateImages",
    "capability": "image_generation",
    "capability_confidence": "high",
    "structured_output": false,
    "call_sites": [
      { "file": "lib/imagen.ts", "line": 60 }
    ]
  }
]
```

**Rules:**

- `workloads[]` is an empty array when no AI call sites are detected
- `call_sites[].file` uses repo-relative POSIX paths
- Every model_id in `workloads[]` MUST also appear in some `ai_sources[].models` entry of the #415 profile
- If a method is in the structured-output trio AND the model is multimodal (Gemini, GPT-4o, Claude) AND structured output is NOT detected → set `capability_confidence: "medium"` (ambiguous — Clarify will confirm)

---

**Skip this step entirely if `is_agentic: false` from Step 3.5.**

For each detected agent in the codebase, extract:

1. **Agent identifier** (`agent_id`) — Class name, variable name, or function name that defines the agent. Use snake_case normalized form (e.g., `ResearchAgent` → `"research-agent"`, `research_agent` → `"research-agent"`).

2. **File and line** — Source file and line number where the agent is defined.

3. **Model ID** — The LLM model this agent uses. Look for:
   - Constructor parameter: `Agent(model="gpt-4o")`, `Agent(llm=ChatOpenAI(model="gpt-4o"))`
   - Config reference: model string in config file referenced by agent
   - Set to `"unknown"` if model is not extractable from code

4. **Tools list** — Tool names attached to this agent. Look for:
   - `tools=[web_search, calculator]` → `["web_search", "calculator"]`
   - `@tool` decorated functions passed to agent
   - Tool schema objects in `function_declarations` or `tools` parameter
   - Set to `[]` if no tools detected

5. **Memory type** — Classify per-agent memory:
   - `"conversation_buffer"` — `ConversationBufferMemory`, `ChatMessageHistory`, message list accumulation
   - `"rag"` — Vector store retrieval feeding agent context, `RetrievalQA`, knowledge base lookup
   - `"none"` — No memory pattern detected for this agent
   - `"unknown"` — Memory detected but type indeterminate

6. **Role** — Human-readable description of what this agent does. Infer from:
   - System prompt or `role=` parameter
   - Class/function docstring
   - Variable name and surrounding context
   - Keep to one sentence

**Classify orchestration pattern** from the overall agent architecture:

| Pattern        | Evidence                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `single`       | One agent definition, no delegation or coordination                                                                       |
| `hierarchical` | One orchestrator agent delegates to specialist agents (agents-as-tools, manager/worker)                                   |
| `swarm`        | Multiple agents share memory/state, no fixed hierarchy (CrewAI `process=Process.hierarchical` is hierarchical, not swarm) |
| `graph`        | Explicit node/edge definitions, conditional routing between agents (`StateGraph`, `GraphBuilder`, `add_edge`)             |
| `sequential`   | Agents execute in fixed order, output of one feeds next (`process=Process.sequential` in CrewAI, pipeline patterns)       |
| `unknown`      | Agentic signals detected but orchestration pattern unclear from code                                                      |

**Determine system-level memory:**

- `has_memory`: `true` if ANY agent has memory OR if shared memory store detected
- `memory_backend`: Classify from imports/config:
  - `"redis"` — Redis client imports, `RedisMemory`, Redis URL in config
  - `"postgres"` — PostgreSQL connection for memory/history storage
  - `"in_memory"` — In-process memory only (default `ConversationBufferMemory`, Python dicts)
  - `"vector_store"` — Pinecone, Weaviate, ChromaDB, pgvector for memory retrieval
  - `"unknown"` — Memory detected but backend indeterminate

**Determine human-in-the-loop:**

- `has_human_in_loop`: `true` if any of:
  - `HumanInputRun`, `human_input` tool, `input()` calls in agent loop
  - Approval/confirmation patterns before tool execution
  - `handoff_to_user` tool or similar delegation to human

---

## Step 6: Map Integration Patterns

Determine how the application integrates with AI services:

- **Primary SDK**: Which Google AI SDK is used
  - `google-cloud-aiplatform` (Vertex AI Platform SDK)
  - `google-generativeai` (Gemini API)
  - `vertexai` (Vertex AI SDK for Python)
  - `@google-cloud/aiplatform` (Node.js)
  - `cloud.google.com/go/aiplatform` (Go)

- **SDK version**: Extract from dependency files (`requirements.txt`, `package.json`, `go.mod`, etc.)

- **Frameworks**: Does the code use orchestration frameworks?
  - LangChain (`from langchain...`)
  - LlamaIndex (`from llama_index...`)
  - Semantic Kernel
  - No framework (raw SDK calls)

- **Languages**: Which programming languages contain AI code?

- **Integration pattern**: Classify as one of:
  - `direct_sdk` — Direct Google SDK calls (e.g., `aiplatform.init()`, `model.predict()`) or OpenAI SDK calls
  - `framework` — Via LangChain, LlamaIndex, or similar
  - `rest_api` — Raw HTTP calls to Vertex AI or OpenAI endpoints
  - `mixed` — Combination of the above

- **Gateway/router type** (`gateways[].type`): Detect whether AI calls go through a gateway, router, or framework. This critically affects migration effort (gateway users can migrate in 1-3 days vs 1-3 weeks for direct SDK).

  Scan for these patterns and classify:

  | Pattern                                                                                                           | Gateway Type     | Evidence                                  |
  | ----------------------------------------------------------------------------------------------------------------- | ---------------- | ----------------------------------------- |
  | `from litellm import completion` / `litellm` in dependencies                                                      | `llm_router`     | LiteLLM — multi-provider router           |
  | `base_url` containing `openrouter.ai` in source code                                                              | `llm_router`     | OpenRouter — multi-provider router (code) |
  | Env var `OPENAI_BASE_URL` containing `openrouter.ai` in `.env`, `docker-compose.yml`, CI config, or shell scripts | `llm_router`     | OpenRouter — env-configured router        |
  | Env var `OPENROUTER_API_KEY` or `OR_API_KEY` present in `.env`, `docker-compose.yml`, CI config, or shell scripts | `llm_router`     | OpenRouter — API key detected             |
  | Env var `LITELLM_PROXY_BASE_URL` or `LITELLM_API_KEY` present in any config file                                  | `llm_router`     | LiteLLM proxy — env-configured            |
  | `portkey` imports or `x-portkey-` headers                                                                         | `llm_router`     | Portkey — AI gateway                      |
  | `helicone` imports or `x-helicone-` headers                                                                       | `llm_router`     | Helicone — AI gateway                     |
  | Kong, Apigee, or custom API gateway routing to AI endpoints                                                       | `api_gateway`    | API gateway proxying AI calls             |
  | `from vapi_python import Vapi` / Vapi SDK                                                                         | `voice_platform` | Vapi — voice AI platform                  |
  | `bland` SDK or Bland.ai API calls                                                                                 | `voice_platform` | Bland.ai — voice AI platform              |
  | `retell` SDK or Retell API calls                                                                                  | `voice_platform` | Retell — voice AI platform                |
  | `from langchain` with provider imports                                                                            | `framework`      | LangChain orchestration framework         |
  | `from llama_index` with provider imports                                                                          | `framework`      | LlamaIndex orchestration framework        |
  | Direct SDK calls only (no router/gateway/framework)                                                               | `direct`         | Direct API integration                    |

  **Env var scan scope for gateway detection:** Check these files for `OPENAI_BASE_URL`, `OPENROUTER_API_KEY`, `OR_API_KEY`, `LITELLM_PROXY_BASE_URL`, `LITELLM_API_KEY`:
  - `.env`, `.env.local`, `.env.production`, `.env.staging`, `.env.*` (any environment file)
  - `docker-compose.yml`, `docker-compose.*.yml`
  - `.github/workflows/*.yml`, `.gitlab-ci.yml`, `cloudbuild.yaml`, `Jenkinsfile`
  - Shell scripts: `*.sh`, `Makefile`
  - `fly.toml`, `railway.toml`, `render.yaml`, `vercel.json`, `netlify.toml`

  **Do NOT read secret values** — only check for the presence of the key name. Log: "Detected [KEY_NAME] in [file] — classified as llm_router (OpenRouter/LiteLLM)."

  Set `gateways[].type` to `null` (no gateway entry) if no AI signals were detected or detection is ambiguous.

Build the **capabilities summary** — a flat boolean map of which AI capabilities are actively used across all detected models:

```json
{
  "text_generation": true,
  "streaming": true,
  "function_calling": false,
  "vision": false,
  "embeddings": true,
  "batch_processing": false
}
```

A capability is `true` only if there is evidence from code analysis that it is actively used.

---

## Step 6.5: Extract Tool Manifest (Only if `is_agentic: true`)

**Skip this step entirely if `is_agentic: false` from Step 3.5.**

Catalog all tool definitions found in agent code. This is inventory only — do NOT include migration recommendations, AWS equivalents, or effort estimates.

For each tool detected in Step 5.5 (from agent `tools` lists) or Step 3B.7 (tool definitions):

1. **Name** — Tool name as defined in code (function name, `name` field in schema, decorator argument)

2. **File and line** — Source file and line number where the tool is defined or imported

3. **Transport classification** — How the tool communicates:
   - `"function"` — Local function with `@tool` decorator, no network calls in body, pure computation or file I/O
   - `"api"` — HTTP client calls in tool body (`requests.get`, `httpx.post`, `fetch`, external URL references)
   - `"mcp"` — MCP client imports, MCP server URL in tool config, tool served via MCP protocol
   - `"unknown"` — Tool schema defined but implementation not inspectable (e.g., imported from external package)

4. **Auth hint** — Detected authentication pattern in tool implementation:
   - `"none"` — No credentials, tokens, or auth headers visible
   - `"api_key"` — API key env var (`os.environ["API_KEY"]`), `Authorization: Bearer` header, `x-api-key` header
   - `"oauth"` — OAuth flow, token refresh logic, `client_id`/`client_secret` patterns
   - `"iam"` — AWS SigV4, boto3 client usage, IAM role assumption, GCP service account credentials
   - `"unknown"` — Auth pattern not determinable from code inspection

5. **Used by agents** — Array of `agent_id` values (from Step 5.5) that reference this tool. A tool may be used by multiple agents.

**Deduplication:** If the same tool is used by multiple agents, create one `tool_manifest` entry with all agent IDs in `used_by_agents`. Do not duplicate tool entries.

---

## Step 8: Generate the #415 profile and the sidecar

Load `references/shared/schema-discover-ai.md` and write two files under `$MIGRATION_DIR`:

1. `$AI_PROFILE` — the #415 document. Group the detected models into `ai_sources[]` by `(provider, source_service)`. Gemini/Vertex models map to `google`/`vertex_ai`, OpenAI SDK models to `openai`/`openai_api`, Azure OpenAI endpoints to `openai`/`azure_openai`, and Anthropic SDK models to `anthropic`/`anthropic_api`. Each entry has `model_families`, `model_evidence` (`observed` when a model was located, otherwise `not_observed` with empty `models` and `model_observations`), `models`, and one `model_observations` entry per model with `raw_model`, `model_family`, and at least one `evidence` item (`provenance` `code`, `confidence` from Step 4).
2. `$AI_SIDECAR` — `schema_version` `1`, `kind` `"BMA_GCP_AI_SIDECAR"`, `workloads` (Step 5B, always present, empty when no call sites), and `agentic_profile` and `tool_manifest` only when Step 3.5 found agents.

OpenRouter is never an `ai_sources` entry. Record it under `gateways[]` with `upstream_evidence: "observed"` and its upstreams only when code shows the upstream provider prefixes. Otherwise record `upstream_evidence: "unresolved"` with `upstreams: []`.

Run the gate before reporting the phase complete:

```
python3 <skill root>/scripts/bma-runtime.py validate-profile --profile $AI_PROFILE --sidecar $AI_SIDECAR
```

Exit 0 is required. Exit 1 is a stop. Do not reshape the output to pass the gate.

### Pre-existing IaC profile

If `$AI_PROFILE` already exists as an IaC-only #415 profile (every evidence entry has `provenance: "iac"`):

1. Execute Steps 5–6 to build the code-derived content as usual.
2. Merge into the final file. Code evidence (`provenance: "code"`) wins where code and IaC report the same `(provider, source_service)` pair. Keep an IaC-only pair only when code found nothing for it, and keep its `iac` evidence.
3. Re-run the gate on the merged file.

If no pre-existing IaC profile exists, generate a fresh profile from code.

**CRITICAL field names** — use EXACTLY these keys:

- `ai_sources[].provider` and `source_service` (not `ai_source`, `service`, `provider_name`)
- `model_families`, `model_evidence`, `models`, `model_observations` (not `models[].model_id`, `detected_via`)
- `model_observations[].normalized_model`, `raw_model`, `model_family`, `evidence` (not `model_name`, `capabilities_used`)
- `evidence[].provenance` — one of `code`, `iac`, `live_api`, `usage_api`, `user_confirmed` (not `source`, `detected_via`)
- `evidence[].confidence` — one of `confirmed`, `high`, `medium`, `low`
- `gateways[].product`, `type`, `upstream_evidence`, `upstreams` (not `gateway_type`, `router_type`)

**Determining `provider`:**

- `google` — Gemini/Vertex AI generative models (patterns 2.3)
- `openai` — OpenAI SDK or Azure OpenAI models (patterns 2.4); `source_service` tells direct from Azure
- `anthropic` — Anthropic SDK and `claude-*` model strings (pattern 2.5)
- Traditional ML only (Vision, Speech, Document AI, custom models) does not produce an `ai_sources` entry. Route it to the traditional-AI rubric in `design-refs/ai.md`.

A provider may appear more than once through different `source_service` values. Two entries with the same `(provider, source_service)` pair are invalid.

**Conditional sections (sidecar only):**

- `agentic_profile` — Include ONLY if `is_agentic: true` from Step 3.5. Omit otherwise.
- `tool_manifest` — Include ONLY if `agentic_profile` exists. Set to `[]` if agentic but no tools detected in Step 6.5.

After writing the files, the parent `discover.md` handles the phase status update. Do not update `.phase-status.json` here.

---

## Output Validation Checklist — ai-workload-profile.json and sidecar

- `schema_version` is `"1.0"` and the profile has only `schema_version`, `ai_sources`, and `gateways`
- `validate-profile` exits 0 with the sidecar
- Every `ai_sources` pair `(provider, source_service)` is unique, and no provider is `both`, `unknown`, or `openrouter`
- `model_evidence` is `observed` only when `models` and `model_observations` are non-empty
- `model_observations` corresponds exactly to `models`, and each `model_family` is in `model_families`
- Every `provenance` value is in the #415 enum, and every `evidence` entry has a `confidence`
- OpenRouter appears only under `gateways[]`, and `upstream_evidence: "unresolved"` has `upstreams: []`
- `workloads[]` is present in the sidecar (empty array if no AI call sites; one entry per distinct `(model_id, sdk_method, structured_output)` tuple)
- Every `workloads[].model_id` also appears in some `ai_sources[].models` entry
- `workloads[].capability_confidence` is one of: `"high"`, `"medium"`, `"low"`
- `workloads[].workload_id` matches pattern `wl_[0-9a-f]{6}`
- If `is_agentic: true`: `agentic_profile` exists in the sidecar with all required fields
- If `is_agentic: true`: `agentic_profile.agent_count` equals length of `agentic_profile.agents[]`
- If `is_agentic: true`: `agentic_profile.tool_count` equals length of `tool_manifest[]` (deduplicated)
- If `is_agentic: true`: `agentic_profile.framework` is one of: `"langgraph"`, `"crewai"`, `"autogen"`, `"openai_agents"`, `"strands"`, `"pydantic_ai"`, `"agno"`, `"custom"`, `"none"`
- If `is_agentic: true`: `agentic_profile.orchestration_pattern` is one of: `"single"`, `"hierarchical"`, `"swarm"`, `"graph"`, `"sequential"`, `"unknown"`
- If `is_agentic: true`: every `agent_id` in `tool_manifest[].used_by_agents` exists in `agentic_profile.agents[].agent_id`
- If `is_agentic: true`: `tool_manifest[].transport` is one of: `"function"`, `"api"`, `"mcp"`, `"unknown"`
- If `is_agentic: true`: `tool_manifest[].auth_hint` is one of: `"none"`, `"api_key"`, `"oauth"`, `"iam"`, `"unknown"`
- If `is_agentic: false`: `agentic_profile` and `tool_manifest` are ABSENT from the sidecar (not present with null/false values)

---

## Downstream Consumption

Design (`references/phases/design/design.md`) reads the two files this way:

1. **`ai_sources[].provider` and `source_service`** — Route to the design reference. `google` → `design-refs/ai-gemini-to-bedrock.md`, `openai`/`openai_api` → `vendored/ai/ai-openai-to-bedrock.md`, `anthropic` → `vendored/ai/ai-anthropic-to-bedrock.md`, `openai`/`azure_openai` → the Azure OpenAI reference. More than one source loads each matching reference.
2. **`ai_sources[].models`** — Determines which Bedrock models to recommend. Retired models are flagged, not priced.
3. **`gateways[]`** — An OpenRouter gateway loads `vendored/ai/ai-openrouter-to-bedrock.md`.
4. **Sidecar `workloads[]`** — One Bedrock recommendation per workload.
5. **Sidecar `agentic_profile` and `tool_manifest`** — Route to the agentic design path and AgentCore tool configuration.
6. **Sidecar `observed_costs` and `integration_context`** — Observed spend and integration context. Present when discovery recorded them.

---

## Scope Boundary

**This phase covers Discover & Analysis ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: inventory the AI application and API workload. In delegated GCP mode, also preserve the explicitly gated GCP source evidence. Nothing else.**
