---
_fragment: app-code
_of_phase: discover
_contributes:
  - ai-workload-profile.json
---

# Discover — Application Code (AI/agentic detection)

> **Fragment unit.** Scans source code, detects Azure/AI SDK imports and agentic frameworks,
> and — when AI confidence ≥ 70% — contributes `ai-workload-profile.json`. The assembler
> (`discover-assemble.md`) is its single creator; this fragment produces the content. See
> `discover.md` for how it composes into the phase. The Azure port of gcp-to-aws's
> `discover-app-code.md`: the agentic detection ports unchanged; the AI-SDK signals are
> swapped from GCP/Vertex to Azure.

**Execute ALL steps in order.** If no source code is found, exit cleanly with no output — other
Discover fragments (IaC) may still produce artifacts.

## Step 0: Self-scan for source code

Recursively scan for source and dependency manifests: `**/*.py`, `**/*.js`, `**/*.ts`, `**/*.jsx`,
`**/*.tsx`, `**/*.go`, `**/*.java`, `**/*.cs` (.NET is common on Azure); manifests
`requirements.txt`, `pyproject.toml`, `Pipfile`, `package.json`, `go.mod`, `pom.xml`,
`build.gradle`, `*.csproj`. **Exit gate:** no source or manifest → exit cleanly, no artifact.

**Secret-file exclusion (HARD).** Before reading any file, skip entirely: `.env*`,
`*.pem`/`*.key`/`*.p12`/`*.pfx`, `credentials.json`, `*-credentials.json`, `secrets.yaml`/`.yml`,
`azure.json` service-principal files. Log a skip line; never include contents. (Azure test repos
ship `.env.example` with placeholder values — still skipped.)

## Step 0.5: Auth-SDK exclusion

Recognized but excluded (no AWS recommendation): Auth0, Supabase Auth, Firebase Auth, Clerk, Okta,
Keycloak, NextAuth, and **Microsoft Entra ID auth libraries used purely for sign-in** (`msal`,
`@azure/msal-*`, `azure-identity` when used ONLY for `DefaultAzureCredential` token acquisition to
auth OTHER Azure calls). Log and skip; identity is handled by Clarify Category J, not here.

## Step 1: Detect Azure / AI SDK imports

Scan for Azure SDK and AI-provider imports. Record `file_path`, `import_statement`,
`inferred_service`, `confidence` (0.60–0.80 — inferred from code, not config).

| Import                                       | Inferred service      |
| -------------------------------------------- | --------------------- |
| `azure.storage.blob` / `@azure/storage-blob` | Blob Storage          |
| `azure.cosmos` / `@azure/cosmos`             | Cosmos DB             |
| `azure.servicebus` / `@azure/service-bus`    | Service Bus           |
| `azure.keyvault.*` / `@azure/keyvault-*`     | Key Vault             |
| `redis` / `ioredis`                          | Azure Cache for Redis |
| `azure.identity` (for data-plane calls)      | managed identity      |

The AI-relevant imports are the point of this fragment — see Step 3.

## Step 2: Infer resources from code

Map the Step-1 imports to likely Azure resources at 0.60–0.80 confidence (inferring existence, not
reading config). These supplement IaC evidence; the assembler reconciles.

## Step 2.5: WebSocket / long-connection scan

Scan active (non-commented) code for `websocket`, `WebSocket`, `socket.io`, FastAPI `WebSocket`,
`ws` package, `EventSource`, `text/event-stream`. Record `websocket_signals_found` +
`websocket_signal_files` in discovery metadata. If no source was found, do NOT set the flag
(absence of a scan is not evidence of no WebSockets).

## Step 3: Flag AI signals (Azure)

Scan source and manifests for AI patterns. Record pattern, file location, confidence.

| Pattern                            | What to look for                                                                                                                                                                                                                          | Confidence |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 3.1 Azure OpenAI (Python)          | `from openai import AzureOpenAI` / `AsyncAzureOpenAI`; a client built with `azure_endpoint=`, `api_version=`; `openai.api_type = "azure"` (legacy); env `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_DEPLOYMENT_NAME` | 98%        |
| 3.2 Azure OpenAI (Node)            | `@azure/openai`, `AzureOpenAI` from `openai` with `azureADTokenProvider`/`endpoint`; `azure-ai-inference` / `@azure-rest/ai-inference`                                                                                                    | 98%        |
| 3.3 Azure OpenAI (.NET)            | `Azure.AI.OpenAI` (`OpenAIClient` with an Azure endpoint)                                                                                                                                                                                 | 95%        |
| 3.4 OpenAI direct                  | `from openai import OpenAI` / `client.chat.completions.create()` with NO azure config; model strings `gpt-4o`, `gpt-4.1`, `o3`, `o4-mini`                                                                                                 | 98%        |
| 3.5 Anthropic                      | `anthropic`, `claude-*` model strings                                                                                                                                                                                                     | 98%        |
| 3.6 Azure AI Vision                | `azure.ai.vision.*`, `azure-cognitiveservices-vision-computervision`, `ComputerVisionClient`                                                                                                                                              | 90%        |
| 3.7 Azure AI Document Intelligence | `azure.ai.formrecognizer` / `azure.ai.documentintelligence`, `DocumentAnalysisClient`, `DocumentIntelligenceClient`                                                                                                                       | 90%        |
| 3.8 Azure AI Speech                | `azure.cognitiveservices.speech`, `SpeechConfig`, `SpeechRecognizer`, `SpeechSynthesizer`                                                                                                                                                 | 90%        |
| 3.9 Azure AI Language              | `azure.ai.textanalytics`, `TextAnalyticsClient`                                                                                                                                                                                           | 90%        |
| 3.10 Azure AI Translator           | `azure.ai.translation.*`                                                                                                                                                                                                                  | 90%        |
| 3.11 Azure Machine Learning        | `azureml`, `azure.ai.ml`, `MLClient`                                                                                                                                                                                                      | 85%        |
| 3.12 Azure AI Search (RAG)         | `azure.search.documents`, `SearchClient`, `VectorizedQuery` — with embeddings, a RAG signal                                                                                                                                               | 85%        |
| 3.13 Embeddings & RAG              | `langchain` + `AzureOpenAIEmbeddings`; `llama_index` + Azure; vector DB + embeddings                                                                                                                                                      | 85%        |

Manifest deps to check: `openai`, `azure-ai-inference`, `@azure/openai`, `Azure.AI.OpenAI`,
`azure-ai-formrecognizer`, `azure-ai-documentintelligence`, `azure-cognitiveservices-vision-computervision`,
`azure-cognitiveservices-speech`, `azure-ai-textanalytics`, `azure-ai-translation-text`, `azureml`,
`azure-ai-ml`, `azure-search-documents`, `anthropic`, `litellm`, `langchain`, `langchain-openai`,
`langchain-aws`.

## Step 3B: Agentic framework signals (ports unchanged from gcp)

| Pattern                | What to look for                                                                                              | Confidence |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- | ---------- |
| 3B.1 LangGraph         | `from langgraph`, `StateGraph(`, `add_node(`, `add_edge(`, `.compile()`                                       | 95%        |
| 3B.2 CrewAI            | `from crewai`, `Crew(`, `Agent(` with `role=`, `Task(`                                                        | 95%        |
| 3B.3 AutoGen           | `from autogen`, `AssistantAgent(`, `GroupChat(`, `ConversableAgent(`                                          | 95%        |
| 3B.4 OpenAI Agents SDK | `from openai.agents` / `from agents import`, `openai.beta.assistants`, `Runner(`                              | 95%        |
| 3B.5 Strands           | `from strands`, `Agent(` with `tools=`, `Swarm(`, `GraphBuilder(`                                             | 95%        |
| 3B.5a Pydantic AI      | `from pydantic_ai import Agent`, `Agent(model=`, `.run_sync(`                                                 | 95%        |
| 3B.5b Agno             | `from agno.agent import Agent`, `Team(`, `.print_response(`                                                   | 95%        |
| 3B.6 Custom agent loop | a loop with BOTH an LLM call AND tool dispatch from model output AND result parse-back                        | 80%        |
| 3B.7 Tool definitions  | `@tool` decorators, `tools=[{...schema...}]`, `function_declarations=`                                        | 90%        |
| 3B.8 MCP integration   | `from mcp.server` / `from mcp.client`, `mcp.json`, `MCPClient(`                                               | 90%        |
| 3B.9 Agent memory      | `ConversationBufferMemory(`, `ChatMessageHistory(`, `MemorySaver(`, vector-store retrieval into agent context | 85%        |

Manifest deps: `langgraph`, `crewai`, `pyautogen`/`autogen`, `strands-agents`, `pydantic-ai`,
`agno`, `mcp`. Note: `langchain_openai.AzureChatOpenAI` / `AzureOpenAIEmbeddings` are the Azure
forms of the LangChain LLM classes — an agentic LangGraph/CrewAI app on Azure uses these, which is
BOTH an agentic signal (3B) AND an `azure_openai` AI signal (3.1/3.2).

## Step 3.5: Agentic classification gate (ports unchanged)

1. Any 3B.1–3B.5b → `is_agentic: true`, `framework` = detected.
2. No framework but 3B.6 → `is_agentic: true`, `framework: "custom"`.
3. 3B.7 + an LLM loop → `is_agentic: true`, `framework: "custom"`.
4. ONLY 3B.8 (MCP) → `is_agentic: false`.
5. ONLY 3B.9 (memory) → `is_agentic: false`.
6. No agentic signals → `is_agentic: false`.

Multiple frameworks → `framework` = the one with the most agent definitions; record the others in
`detection_signals`. If `is_agentic: true`, run the agentic extraction (Step 5.5) and tool manifest
(Step 6.5) after Step 5.

## Step 4: AI detection gate

Confidence: LLM SDK + a second strong signal → 95%+; any one strong signal (Azure OpenAI, OpenAI,
Anthropic, an Azure Cognitive client) → 90%+; weak-only → 60–70%; none → 0%.

**False-positive checklist:** Azure AI Search alone is NOT AI (require embeddings imports —
`SearchClient` for keyword search is a regular index); `azure-identity` alone is auth, not AI;
dead/commented code excluded.

**Exit gate — confidence < 70%:**

- If `ai-workload-profile.json` already exists with `metadata.profile_source: "iac_cognitive"` (from
  `discover-iac.md`'s Cognitive-Services path): **exit cleanly, do not modify it** — the
  IaC-inferred profile is retained. Report signals + confidence.
- Otherwise: do NOT contribute `ai-workload-profile.json`. Report signals, confidence, and reason.

**Confidence ≥ 70%:** continue to Steps 5–8.

## Step 5: Extract AI model details

For each signal, extract model IDs and capabilities.

**Azure OpenAI note — deployment name vs model name.** Azure OpenAI calls pass a **deployment
name** at call time (`model=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]` or a literal like
`"gpt-4o-prod"`), not the base model name. Record the deployment string as `model_id` when that is
all the code exposes, and record the underlying base model (`gpt-4o`, `gpt-4.1`, `text-embedding-3-large`)
when a Terraform `azurerm_cognitive_deployment` or a comment reveals it. Note in `usage_context`
that the id is a deployment name when applicable.

Model-string patterns: `gpt-*`, `o1*`/`o3*`/`o4*`, `text-embedding-*`, `dall-e-*`/`gpt-image-*`,
`whisper-*`, `tts-*` (OpenAI/Azure OpenAI); `claude-*` (Anthropic). Capabilities from API calls:
`text_generation` (`chat.completions.create`), `streaming` (`stream=True`), `function_calling`
(`tools=`), `vision` (image input), `embeddings` (`embeddings.create` / `AzureOpenAIEmbeddings`),
`structured_output` (`response_format`), `image_generation` (`images.generate`), `speech_to_text` /
`text_to_speech` (audio APIs, Azure Speech). Cognitive clients → `document_extraction`
(Document Intelligence), `image_analysis` (Vision), `speech_transcription` (Speech).

## Step 5B: Disambiguate workloads by SDK method

Load `references/vendored/ai/sdk-capability-map.json`. For each AI call site: resolve the SDK method,
detect structured output (for the structured-output trio: `response_format` / `responseSchema`),
assign capability, collapse by `(model_id, sdk_method, structured_output)` into one workload with all
`call_sites`. `workload_id = "wl_" + sha256(model_id + "|" + sdk_method + "|" + ("structured" if
structured_output else "plain"))[:6]`. Azure OpenAI apps call the SAME `openai.*` SDK methods, so the
capability map covers them unchanged. Every `workloads[].model_id` must appear in `models[]`.

## Step 5.5: Agentic extraction (only if `is_agentic: true`) — ports unchanged

Per agent: `agent_id` (snake-cased), `file`, `line`, `model_id`, `tools[]`, `memory_type`
(`conversation_buffer`/`rag`/`none`/`unknown`), `role`. Classify `orchestration_pattern`
(`single`/`hierarchical`/`swarm`/`graph`/`sequential`/`unknown` — `StateGraph`/`add_edge` → `graph`;
CrewAI `Process.sequential` → `sequential`, `Process.hierarchical` → `hierarchical`). Set
`has_memory`, `memory_backend` (`redis`/`postgres`/`in_memory`/`vector_store`/`unknown`),
`has_human_in_loop`.

## Step 6: Map integration patterns

`primary_sdk` (`openai` / `@azure/openai` / `azure-ai-inference` / `Azure.AI.OpenAI` / an Azure
Cognitive SDK), `sdk_version`, `frameworks[]` (LangChain/LlamaIndex/Semantic Kernel/none),
`languages[]`, `pattern` (`direct_sdk`/`framework`/`rest_api`/`mixed`), `gateway_type`
(`llm_router` for LiteLLM/OpenRouter/Portkey/Helicone — including an `azure/<deployment>` litellm
model string; `api_gateway`; `voice_platform`; `framework`; `direct`; or null — do NOT read secret
values, only key presence), and the boolean `capabilities_summary` map. `## Step 6.5` tool manifest
(only if agentic): per tool `name`, `file`, `line`, `transport` (`function`/`api`/`mcp`/`unknown`),
`auth_hint` (`none`/`api_key`/`oauth`/`iam`/`unknown`), `used_by_agents[]`.

## Step 7: Supporting infrastructure (only if IaC ran)

Extract Azure AI infra: `azurerm_cognitive_account`, `azurerm_cognitive_deployment`,
`azurerm_machine_learning_workspace`, `azurerm_search_service`, plus managed identities / Key Vault
entries referenced by AI code. `{ address, type, file, config }`. `infrastructure: []` when no IaC.

## Step 8: Contribute ai-workload-profile.json

Build the profile per `references/shared/schema-discover-ai.md`. **`ai_source`:**

- `azure_openai` — Azure OpenAI SDK/deployments detected (the 3.1–3.3 Azure signals).
- `openai` — direct OpenAI SDK, no azure config (3.4).
- `anthropic` — Anthropic only.
- `both` — Azure-OpenAI/OpenAI + another provider (e.g. Anthropic).
- `other` — traditional ML only (Vision / Document Intelligence / Speech / Language / Azure ML) with
  no LLM SDK.

**`profile_source`:** `application_code` (fresh from code), `iac_cognitive` (pre-existing IaC-inferred),
or `merged` (both — code wins on conflict; union `infrastructure[]` by address; set
`sources_analyzed.terraform`/`.application_code` accordingly).

**CRITICAL field names** (exact): `model_id`, `service`, `detected_via`, `capabilities_used`,
`usage_context`, `pattern`, `gateway_type`, `capabilities_summary`, `ai_source`. The field is
`service`, never `azure_service`. Conditional sections: `current_costs` only if billing ran;
`infrastructure: []` if no IaC; `agentic_profile`/`tool_manifest` only if `is_agentic`.

The assembler (`discover-assemble.md`) writes the file; do not update `.phase-status.json` here.

## Output Validation Checklist

- [ ] `summary.ai_source` ∈ `azure_openai | openai | anthropic | both | other` (never `gemini`).
- [ ] `metadata.profile_source` ∈ `application_code | iac_cognitive | merged`.
- [ ] Every `models[]` entry has the exact-named fields; `detected_via` lists only analyzed sources.
- [ ] `workloads[]` present; every `workloads[].model_id` ∈ `models[].model_id`; `workload_id`
      matches `wl_[0-9a-f]{6}`.
- [ ] `integration.gateway_type` set (or null); `capabilities_summary` consistent with
      `models[].capabilities_used`.
- [ ] `is_agentic` cases: `agentic_profile`+`tool_manifest` present iff true; `agent_count` ==
      `agents[]` length; `tool_count` == deduped `tool_manifest[]` length.
- [ ] No secret VALUES anywhere (env/appsetting NAMES only); `.env*` never read.

## Scope Boundary

Discover & analysis ONLY. Do NOT name AWS services, recommend Bedrock models, estimate cost, or
plan migration — that is Design/Estimate/Generate. This fragment inventories what runs on Azure.

## Status — build step 4 (the AI detector)

Net-new for azure (gcp had `discover-app-code.md`; azure had none). This is what makes AI
detectable WITHOUT IaC — the common case, since most startups have `AzureOpenAI` in code but no
`azurerm_cognitive_account` in Terraform. Produces `ai-workload-profile.json`, the artifact the
whole AI track (clarify-ai → design-ai → estimate-ai → generate-artifacts-ai) reads. Test corpus:
`data/azure/ai-workloads/`.
