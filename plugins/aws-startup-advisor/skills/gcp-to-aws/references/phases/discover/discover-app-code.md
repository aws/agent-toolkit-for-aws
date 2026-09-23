# Discover Phase: App Code Discovery

> Self-contained application code discovery sub-file. Scans for source code, detects GCP SDK imports, infers resources, flags AI signals, and if AI confidence >= 70%, extracts detailed AI workload information and generates `ai-workload-profile.json`.
> If no source code files are found, exits cleanly with no output.

**Dead-end handling:** If this file exits without producing artifacts (no source code found, or AI confidence < 70%), report to the parent orchestrator: what signals were found (if any), the confidence level, and that the user should provide Terraform files or billing exports to proceed with migration planning.

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

Before scanning for GCP imports, check for third-party auth SDK imports. These are **recognized but excluded** from migration — they carry no AWS recommendation.

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
2. Do **not** infer a GCP resource or recommend an AWS replacement
3. Do **not** include in the AI signal scan or any output artifact

## Step 1: Detect GCP SDK Imports

Scan source files for GCP service imports:

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

## Step 2: Infer Resources from Code

Map SDK imports to likely GCP resources. These are inferred — they supplement IaC evidence but at lower confidence:

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

## Step 2.7: Graviton (ARM64) Compatibility Scan

After Step 2.5, assess each detected compute workload for Graviton (ARM64) compatibility and emit a `graviton_profile` entry per service. **Load** `references/shared/schema-graviton.md` for the detection-signal tables and the `graviton_profile` schema; **load** `references/shared/graviton.md` for tier definitions.

For each compute workload (web service, worker, function, container) detected from source code and manifests:

1. Determine the **language runtime** from the dependency manifest. Python, Node.js, Go, PHP, Ruby, and pure-JVM Java (Corretto/OpenJDK, no JNI) → `tier: "ready"`.
2. Scan for **risk signals** (downgrade to `conditional`): native C extensions (`node-gyp`, niche Python C packages), native gem extensions, JNI (`System.loadLibrary`, `JNI_OnLoad`), recompile-required languages (Rust/C/C++ without x86 assembly), `platform: linux/amd64` pinned in `docker-compose.yml` or build config.
3. Scan for **blockers** (`tier: "incompatible"`): GPU/CUDA usage (`import cuda`, `torch.cuda`, `nvidia`) → caveat `"route to G5/G6"`; Windows/.NET Framework targets.
4. If a `Dockerfile` is present, record whether its `FROM` base image has a multi-arch variant as a `signal`.

Write a `graviton_profile` array into the discovery output (alongside `models[]`/`workloads[]` when present, otherwise in the discovery metadata). Each entry uses the schema in `schema-graviton.md` with `source: "app_code"`. `graviton_profile` is an empty array when no compute workloads are detected.

If **no source code files were found** (Step 0 exit gate), do **not** emit `graviton_profile` from this file — `discover-iac.md` will emit coarser profiles from `machine_type` signals, and Clarify will confirm architecture.

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
- `openai` (OpenAI SDK — many GCP-hosted apps use OpenAI rather than Vertex AI)
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

**If multiple frameworks detected:** Set `framework` to the one with the most agent definitions. Record others in `detection_signals`.

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

- **If** `$MIGRATION_DIR/ai-workload-profile.json` **already exists** with `metadata.profile_source` = `"iac_vertex"` (from `discover-iac.md` Step 7d — strong Vertex Terraform): **exit cleanly** without deleting or modifying that file. Report to the parent orchestrator: signals found, confidence below 70%, and that the **IaC-inferred AI profile is retained** for Clarify.
- **Otherwise:** Do **not** generate `ai-workload-profile.json`. Report signals found, confidence level, and reason for not generating the AI profile. The inferred resources from Steps 1-2 remain available for other sub-files (e.g., discover-iac.md may use them for evidence merge). If no other sub-discoverer produces artifacts, the parent orchestrator will inform the user to provide Terraform files or billing exports.

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
  - Look for Gemini model string patterns: `gemini-pro`, `gemini-1.5-*`, `gemini-2.0-*`, `gemini-2.5-*`, `gemini-3-*`, `gemini-3.1-*` — including versioned variants like `gemini-2.5-flash-latest`, `gemini-2.5-flash-preview-*`, `gemini-2.5-flash-thinking`, `gemini-2.5-pro-preview-*`. Normalize all `gemini-2.5-flash-*` variants to `model_id: "gemini-2.5-flash"` (or `"gemini-2.5-flash-thinking"` if the thinking variant is explicit). Normalize all `gemini-2.5-pro-*` variants to `model_id: "gemini-2.5-pro"`. Record the raw string in `detection_signals` for reference.
  - **Gemini 1.5 Legacy:** Normalize `gemini-1.5-flash*` → `model_id: "gemini-1.5-flash"` and `gemini-1.5-pro*` → `model_id: "gemini-1.5-pro"`. Set `lifecycle_status: "legacy"` and `eol_date: "2025-09-24"` on these model entries in `ai-workload-profile.json`. Surface in the AI Context Summary during Clarify: "⚠️ Gemini 1.5 Flash/Pro is past EOL (Sep 2025). Plan to upgrade the source model to 2.5 Flash/Pro as part of or before the AWS migration."

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

**Load** `data/sdk-capability-map.json` from the plugin source. If missing or malformed, halt with diagnostic: `"[Discover] Failed to load sdk-capability-map.json"`.

**For each AI call site detected in Steps 3–5:**

1. **Resolve the SDK method** — the fully qualified method name (e.g., `ai.models.generateContent`, `openai.chat.completions.create`, `openai.images.generate`). Match against `sdk-capability-map.json` entries using exact, case-sensitive equality.

2. **Detect structured output** — for methods in `structured_output_trio` (`chat.completions.create`, `messages.create`, `generateContent`), check if the call passes any of: `response_format`, `responseSchema`, or `responseMimeType: 'application/json'`. If yes → `structured_output: true`, `capability: "structured_output"`, `confidence: "high"`. If no → `structured_output: false`, `capability: "text_generation"`, `confidence: "medium"`.

3. **Assign capability from map** — for methods NOT in the structured-output trio, use the map value directly with `confidence: "high"`. For methods not in the map at all → `capability: "unknown"`, `confidence: "low"`.

4. **Collapse by workload tuple** — group call sites sharing the same `(model_id, sdk_method, structured_output)` into a single workload entry. Record all `call_sites` (file + line).

5. **Generate workload_id** — deterministic hash: `"wl_" + sha256(model_id + "|" + sdk_method + "|" + ("structured" if structured_output else "plain"))[:6]`

**Output:** Add a `workloads` array to the `ai-workload-profile.json` output alongside the existing `models[]` field.

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
- Every model_id in `workloads[]` MUST also appear in `models[]` (backward compatibility)
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

- **Gateway/router type** (`gateway_type`): Detect whether AI calls go through a gateway, router, or framework. This critically affects migration effort (gateway users can migrate in 1-3 days vs 1-3 weeks for direct SDK).

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

  Set `gateway_type` to `null` if no AI signals were detected or detection is ambiguous.

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

## Step 7: Capture Supporting Infrastructure

**Only if Terraform files were found (IaC discovery also ran)**, extract AI-related infrastructure resources:

- **AI resources**: `google_vertex_ai_endpoint`, `google_vertex_ai_model`, `google_vertex_ai_featurestore`, `google_vertex_ai_index`, `google_vertex_ai_tensorboard`, etc.
- **Supporting resources** that serve AI primaries:
  - Service accounts used by AI endpoints
  - VPC connectors attached to AI services
  - Secret Manager entries referenced by AI code (API keys, credentials)
  - Cloud Storage buckets used for model artifacts or training data

For each resource, capture: `address`, `type`, `file`, and relevant `config`.

If no Terraform files were provided, set `infrastructure: []`.

---

## Step 8: Generate ai-workload-profile.json

Load `references/shared/schema-discover-ai.md` and generate output following the `ai-workload-profile.json` schema.

### Pre-existing IaC profile (`profile_source: "iac_vertex"`)

If `$MIGRATION_DIR/ai-workload-profile.json` **already exists** with `metadata.profile_source` = `"iac_vertex"`:

1. Execute Steps 5–7 to build the **code-derived** profile content as usual.
2. **Merge** into the final file written to `$MIGRATION_DIR/ai-workload-profile.json`:
   - Set `metadata.profile_source` to **`"merged"`**.
   - Set `metadata.sources_analyzed.terraform` to **`true`** when Terraform was present in the project (IaC discovery ran).
   - Set `metadata.sources_analyzed.application_code` to **`true`**.
   - **Code wins on conflict** for `models[]`, `integration`, `summary.ai_source`, `summary.overall_confidence`, `summary.confidence_level`, and `detection_signals` (code-derived signals take precedence; you may append non-duplicate Terraform `detection_signals` entries).
   - **`infrastructure[]`:** Union by resource `address`. Include all Vertex-related entries from the IaC profile plus any from Step 7; where the same `address` appears, prefer the entry with richer `config` (typically Step 7 after code).
   - Set `summary.inferred_from_iac` to **`false`** when Step 5–6 populated models or integration from code; if `models[]` is still empty after code analysis, keep `inferred_from_iac` consistent with whether Clarify still needs to disambiguate (default **`false`** once code path ran at ≥70% confidence).
3. If no pre-existing `iac_vertex` file, generate a fresh profile with `metadata.profile_source` = **`"application_code"`**.

**CRITICAL field names** — use EXACTLY these keys:

- `model_id` (not model_name, name)
- `service` (not service_type, gcp_service)
- `detected_via` (not detection_method, source)
- `capabilities_used` (not capabilities, features)
- `usage_context` (not description, purpose)
- `pattern` in integration (not integration_type, method)
- `gateway_type` in integration (not gateway, router_type)
- `capabilities_summary` (not capabilities, feature_flags)
- `ai_source` in summary (not provider, source_provider)

**Determining `ai_source`:**

- `"gemini"` — Only Gemini/Vertex AI generative models detected (patterns 2.3)
- `"openai"` — Only OpenAI SDK/models detected (patterns 2.4)
- `"anthropic"` — Only Anthropic SDK detected (pattern 2.5, `anthropic` package, `claude-*` model strings) with no Gemini or OpenAI signals
- `"both"` — Both Gemini and OpenAI detected in the same codebase; or Anthropic + any other provider
- `"other"` — Traditional ML only (custom models, Vision API, Speech API, Document AI) with no LLM SDK detected

**Note:** Anthropic SDK users are migrating to Bedrock-hosted Claude models, not to SageMaker. Setting `ai_source: "anthropic"` ensures Design routes to the correct Bedrock migration path rather than the traditional ML rubric.

**Conditional sections:**

- `current_costs` — Include ONLY if billing data was provided (billing discovery ran). Omit entirely if no billing data.
- `infrastructure` — Set to `[]` if no Terraform files were provided (IaC discovery did not run).
- `agentic_profile` — Include ONLY if `is_agentic: true` from Step 3.5. Omit entirely if not agentic.
- `tool_manifest` — Include ONLY if `agentic_profile` exists. Set to `[]` if agentic but no tools detected in Step 6.5.

After generating the output file, the parent `discover.md` handles the phase status update — do not update `.phase-status.json` here.

---

## Output Validation Checklist — ai-workload-profile.json

- `metadata.profile_source` is one of: `"application_code"`, `"iac_vertex"`, `"merged"`
- `metadata.sources_analyzed` reflects which data sources were actually provided
- `summary.overall_confidence` matches the detection confidence from Step 4
- `summary.total_models_detected` matches the length of `models` array
- `summary.ai_source` is set correctly: `"gemini"`, `"openai"`, `"anthropic"`, `"both"`, or `"other"` based on detected LLM SDKs
- Every entry in `models` has `model_id`, `service`, `detected_via`, `evidence`, `capabilities_used`, and `usage_context`
- `models[].detected_via` only contains sources that were actually analyzed (`"code"`, `"terraform"`, `"billing"`)
- `models[].evidence` array has at least one entry per source listed in `detected_via`
- `models[].capabilities_used` only lists capabilities with evidence from code analysis
- `integration.capabilities_summary` is consistent with the union of all `models[].capabilities_used`
- `integration.gateway_type` is set: one of `"llm_router"`, `"api_gateway"`, `"voice_platform"`, `"framework"`, `"direct"`, or `null`
- `infrastructure` is empty array `[]` if no Terraform was provided
- `current_costs` section is present ONLY if billing data was provided; omitted entirely otherwise
- `detection_signals` matches the signals found in Step 3
- All field names use EXACT required keys
- `workloads[]` is present (empty array if no AI call sites; one entry per distinct `(model_id, sdk_method, structured_output)` tuple)
- Every `workloads[].model_id` also appears in `models[].model_id`
- `workloads[].capability_confidence` is one of: `"high"`, `"medium"`, `"low"`
- `workloads[].workload_id` matches pattern `wl_[0-9a-f]{6}`
- If `is_agentic: true`: `agentic_profile` section exists with all required fields
- If `is_agentic: true`: `agentic_profile.agent_count` equals length of `agentic_profile.agents[]`
- If `is_agentic: true`: `agentic_profile.tool_count` equals length of `tool_manifest[]` (deduplicated)
- If `is_agentic: true`: `agentic_profile.framework` is one of: `"langgraph"`, `"crewai"`, `"autogen"`, `"openai_agents"`, `"strands"`, `"pydantic_ai"`, `"agno"`, `"custom"`, `"none"`
- If `is_agentic: true`: `agentic_profile.orchestration_pattern` is one of: `"single"`, `"hierarchical"`, `"swarm"`, `"graph"`, `"sequential"`, `"unknown"`
- If `is_agentic: true`: every `agent_id` in `tool_manifest[].used_by_agents` exists in `agentic_profile.agents[].agent_id`
- If `is_agentic: true`: `tool_manifest[].transport` is one of: `"function"`, `"api"`, `"mcp"`, `"unknown"`
- If `is_agentic: true`: `tool_manifest[].auth_hint` is one of: `"none"`, `"api_key"`, `"oauth"`, `"iam"`, `"unknown"`
- If `is_agentic: false`: `agentic_profile` and `tool_manifest` are ABSENT from output (not present with null/false values)

---

## Design Phase Integration

The Design phase (`references/phases/design/design.md`) uses `ai-workload-profile.json`:

1. **`summary.ai_source`** — Routes to the correct design reference: `"gemini"` → `ai-gemini-to-bedrock.md`, `"openai"` → `ai-openai-to-bedrock.md`, `"anthropic"` → `ai-anthropic-to-bedrock.md` (Anthropic SDK → Bedrock Converse API client swap), `"both"` → load both Gemini and OpenAI refs, `"other"` → `ai.md` (traditional ML / Vision API / Speech API only)
2. **`models`** — Determines which Bedrock models to recommend via the model selection decision tree
3. **`integration.capabilities_summary`** — Validates Bedrock feature parity (e.g., if `function_calling` is `true`, selected Bedrock model must support tool use)
4. **`integration.pattern`** and **`integration.primary_sdk`** — Determines code migration guidance (direct SDK swap vs framework provider swap vs REST endpoint change)
5. **`integration.gateway_type`** — Determines migration effort and approach: `"llm_router"` or `"framework"` → config change (1-3 days); `"direct"` → full SDK swap (1-3 weeks)
6. **`integration.frameworks`** — If LangChain is used, migration may be simpler (swap provider, keep chains)
7. **`infrastructure`** — Identifies supporting AWS resources needed (IAM roles, VPC config)
8. **`current_costs.monthly_ai_spend`** — Baseline for cost comparison in estimate phase
9. **`agentic_profile`** (if present) — Routes to agentic design path: determines migration approach (retarget / Harness / Strands), maps tools to AgentCore Gateway targets, configures AgentCore Memory
10. **`tool_manifest`** (if present) — Inventories tools for AgentCore Gateway or Harness tool configuration

---

## Scope Boundary

**This phase covers Discover & Analysis ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: Inventory what exists in GCP. Nothing else.**
