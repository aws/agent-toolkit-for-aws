# GenAI, Search & Vector Workloads

**When to use:** The user wants to implement semantic caching, conversational memory, RAG, vector search, recommendation engines, or any GenAI/LLM pattern with ElastiCache. Also useful when the user asks about caching LLM responses (exact or semantic match).
**When not needed:** The user is working on traditional caching patterns (session store, leaderboard, rate limiting), general setup, monitoring, or migration without a GenAI component.

## Loading

Read this file first. Load files listed below on demand based on the routing decision.

| File | Load when |
|------|-----------|
| `elasticache-search.md` | Any pattern needing vector search (Mode 2 server-side or Mode 3). Contains platform gate, version detection, limits, encoding, backfill, AND a Python-side cosine fallback for when FT.* is unavailable. **ALWAYS load this file before generating vector code** so the version guard and fallback are included. |
| `semantic-cache.md` | User wants semantic caching for LLM/API responses. Step-by-step: FT.CREATE, embed, FT.SEARCH, threshold, store. |
| `session-store.md` | User wants session state, message history, resumable conversations, or Strands session management. Plain data structures, serverless OK. |
| `agent-memory.md` | User wants semantic agent memory, cross-session recall via similarity, or mem0 integration. Requires node-based Valkey 8.2 or above (recommend 9.0). |
| `rag-retrieval.md` | User wants RAG, knowledge base retrieval, or document search. Step-by-step: schema, index, ingest, hybrid query. |
| `framework-guide.md` | User mentions a specific framework (Strands, mem0, LangChain) or asks how to connect their AI app. |
| `embedding-providers.md` | User needs to choose or configure an embedding provider. Bedrock Titan v2 preferred, open-source fallback (fastembed, sentence-transformers). |

## Check for existing context

Before starting, read `.elasticache/requirements.json` if it exists. If the `genai` section is set (`mode`, `mode_2_path`, `framework`), use those values instead of re-asking. If `infrastructure.embedding_module` is set and the file exists, import from it.

## Three-Way GenAI Routing

Before recommending a pattern, classify the user's need into one of these three modes. Many teams asking for "RAG cache" actually need semantic response reuse (Mode 2), not full vector search (Mode 3). Ask a clarifying question before jumping to the heaviest option.

### Mode 1: Plain Cache

Standard caching of LLM or API responses by exact key match. No vector index needed.

When to use: the user wants to avoid repeated identical LLM calls. Responses are looked up by an exact key (prompt hash, request fingerprint, or deterministic cache key).

Deployment: **serverless Valkey**. This is just regular SET/GET. Route to `data-modeling` sub-skill for key schema and TTL guidance.

### Mode 2: Semantic Response Cache

Cache LLM responses with semantic similarity matching so "nearly identical" prompts return a cached response.

When to use: the user wants fuzzy cache hits, where semantically close prompts share a cached response.

Two implementation paths:

- **Application-side embedding comparison**: app computes embeddings, stores as plain keys, does similarity math client-side. Serverless OK. Works on ANY Valkey/Redis version.
- **Server-side vector similarity**: Valkey performs the similarity search via FT.SEARCH. Requires node-based Valkey 8.2 or above (recommend 9.0).

Ask the user which approach they prefer. Default to application-side unless they have high query volume AND confirmed Valkey 8.2 or above node-based. If the user's Valkey version is < 8.2, application-side is the ONLY option. Always load `elasticache-search.md` and use the `supports_ft_search()` version check before generating any FT.* code.

Deployment: **serverless Valkey** for application-side; **node-based Valkey 8.2 or above (recommend 9.0)** for server-side.
Load: `semantic-cache.md`, `elasticache-search.md` (if server-side), `embedding-providers.md`

### Mode 3: Full Vector Search

Vector indexing, KNN/ANN queries, RAG retrieval, recommendation via embeddings, agent memory with vector recall, or any workload that requires Valkey to maintain and query a vector index.

When to use: the user needs to store many embeddings and retrieve the top-K most similar. Typical for RAG knowledge bases, agent memory, recommendation engines, semantic search, catalog search.

Deployment: **node-based Valkey 8.2 or above** (mandatory; recommend 9.0). No serverless.
Load: `elasticache-search.md` plus the relevant pattern file (`rag-retrieval.md`, `agent-memory.md`, or `semantic-cache.md`), `embedding-providers.md`, `framework-guide.md` (if framework mentioned)

### How to classify

1. Does the user need similarity matching at all? If no, use **Mode 1**.
2. Is the similarity matching scoped to caching LLM responses? If yes, use **Mode 2** and ask application-side vs server-side.
3. Does the user need to index, store, and query a corpus of embeddings? If yes, use **Mode 3**.

## Hard Routing Rules (non-negotiable)

1. **Vector search MUST use node-based Valkey 8.2 or above (recommend 9.0).** Serverless does NOT support vector search. Never recommend serverless for vector search workloads, not even as a temporary or future option.

2. **Global Datastore MUST use node-based clusters.** If the GenAI workload requires multi-Region replication, it must be node-based.

3. **Vector search is NOT available on data tiering node types (r6gd family).** Do not recommend r6gd instances for any workload requiring vector search.

4. **Changing embedding providers requires full re-indexing.** If the user wants to switch embedding models, warn that ALL existing vectors must be deleted and re-embedded. This is destructive. Confirm before proceeding.

## Common Mistakes to Avoid

1. Do NOT generate FT.CREATE or FT.SEARCH code without first loading `elasticache-search.md` and including the `supports_ft_search()` guard.
2. Do NOT use numpy for vector byte packing. Use `struct.pack` only.
3. When using raw valkey-py/redis-py client directly, do NOT use the high-level `redis.commands.search` or `valkey.commands.search` Python wrappers for FT.* commands. Use `execute_command()` instead. When using supported frameworks like `langgraph-checkpoint-aws` (ValkeyStore) or Mem0, their built-in abstractions (e.g., `store.search()`, `store.put()`, `m.add()`, `m.search()`) are acceptable.
4. Do NOT recommend serverless for any Mode 3 workload or Mode 2 server-side.
5. Do NOT generate inline embedding code. Always import from the shared utility file (`infrastructure.embedding_module`).
6. Do NOT assume the user's Valkey version supports vector search. Always check with `supports_ft_search()`.
7. Do NOT skip the embedding provider selection step. The FT.CREATE DIM must match the embedding model's output dimensions exactly.
8. Be aware of an inconsistency in AWS docs regarding the HNSW M parameter: the FT.CREATE command doc states the maximum is 512, while the vector search limits page (vector-search-features-limits.md) states the maximum is 2,000,000. Treat the limits page as authoritative for parametric restrictions.

## Data-Plane Access

Mode 2 (server-side) and Mode 3 workloads need data-plane access to run FT.CREATE, FT.SEARCH, JSON operations, and other Valkey commands. The primary path is the valkey-py client (`pip install valkey`). Connect through the cache endpoint (via the jump host or SSM tunnel covered in setup). The agent writes Python that runs each command via `execute_command()`, consistent with the guidance in "Common Mistakes to Avoid" rule 3.

## Engine Requirement

All GenAI patterns require **Valkey**. Vector search patterns specifically require **Valkey 8.2 or above on node-based clusters (recommend 9.0)**.

> Vector search is available with Valkey 8.2 or above on node-based clusters in all AWS Regions at no additional cost. Not supported on data-tiering instances (r6gd) or serverless caches.

If the user doesn't have a cache yet, hand off to `setup` and ensure node-based Valkey 8.2 or above is selected (recommend 9.0) when vector search is needed.

## Workflow

1. Classify the user's need (Mode 1/2/3). If `genai.mode` is already set in `requirements.json`, skip classification.
2. Persist the mode to `requirements.json` under `genai.mode`. If Mode 2, also persist `genai.mode_2_path` (`"app-side"` or `"server-side"`).
3. If Mode 2 (server-side) or Mode 3: check `requirements.json` for `infrastructure.embedding_module`. If set and the file exists, import from it. If not set, load `embedding-providers.md`, ask the user for their preferred model, generate the reusable utility file in their project, and persist the choice.
4. Load the relevant reference files per the table above
5. If vector search is needed, verify node-based Valkey 8.2 or above (recommend 9.0; load `elasticache-search.md` for constraints)
6. Walk through the pattern-specific implementation guide. All generated code imports from the embedding utility created in step 3 rather than generating inline embedding code.
7. If the user mentions a framework, load `framework-guide.md` and persist the choice to `genai.framework` in `requirements.json`.

## After implementation

### Update requirements artifact

After the pattern is implemented, update `.elasticache/requirements.json`. GenAI owns the `genai` section. Read the existing file first, merge your updates, then write it back. Do not overwrite fields owned by setup or requirements.

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."
