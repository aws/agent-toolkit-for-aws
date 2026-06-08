# Semantic Agent Memory Implementation Guide

User preferences, learned facts, and cross-session recall via vector similarity search. Requires node-based Valkey 8.2 or above (recommend 9.0).

For conversation persistence (session state, message history, resumable sessions), see `session-store.md` instead.

---

## 1. Semantic Memory with mem0 + Valkey

mem0 provides a memory layer that extracts facts from conversations, deduplicates them, and retrieves by semantic similarity. It has a first-class Valkey connector (`provider: "valkey"`) that uses native `FT.CREATE`/`FT.SEARCH`.

### Configuration

```python
from mem0 import Memory
from utils.embeddings import VECTOR_DIM  # Your project's embedding dimension constant (e.g., 1024 for Titan V2)

config = {
    "vector_store": {
        "provider": "valkey",
        "config": {
            "index_name": "app_memory",
            "embedding_model_dims": VECTOR_DIM,
            "valkey_url": "valkeys://your-endpoint.cache.amazonaws.com:6379",
            "index_type": "hnsw",
            "hnsw_m": 16,
            "hnsw_ef_construction": 200,
            "hnsw_ef_runtime": 10,
        }
    },
    "embedder": {
        # Provider-specific. See embedding-providers.md for mem0 embedder
        # configs for Bedrock Titan, Cohere, fastembed, sentence-transformers.
    },
}

memory = Memory.from_config(config)
```

For HNSW parameter tuning guidance, see `elasticache-search.md`.

### Short-Term vs Long-Term Memory

| Dimension | Short-term | Long-term |
|-----------|-----------|-----------|
| Scope | Session/Recent (days) | User (90 days) |
| TTL | 720 hours (~30 days) | 90 days |
| Content | Current task context, active preferences | Persistent preferences, learned facts |
| Identity | session_id as user_id (anonymous), or user_id with session as run_id (authenticated) | user_id |

Use `memory_type` in metadata to distinguish:

```python
from datetime import datetime, timedelta

def add_short_term(messages, session_id, user_id=None):
    metadata = {"memory_type": "short_term",
                "expires_at": (datetime.now() + timedelta(hours=720)).timestamp()}
    if user_id:
        memory.add(messages, user_id=user_id, agent_id="myapp",
                   run_id=session_id, metadata=metadata)
    else:
        memory.add(messages, user_id=session_id, agent_id="myapp",
                   run_id="global", metadata=metadata)

def add_long_term(messages, user_id):
    metadata = {"memory_type": "long_term",
                "expires_at": (datetime.now() + timedelta(days=90)).timestamp()}
    memory.add(messages, user_id=user_id, agent_id="myapp",
               run_id="global", metadata=metadata)
```

> **Note:** The `expires_at` field is stored as metadata only. It does not automatically expire keys in Valkey. Your application must handle key expiration separately (e.g., by calling `EXPIRE` on the underlying keys, or by running a periodic cleanup job that filters on `expires_at` and deletes expired entries).

### Add and Search

```python
messages = [
    {"role": "user", "content": "I prefer size 12 wide width shoes"},
    {"role": "assistant", "content": "Noted, I'll filter for size 12 wide."},
]
memory.add(messages, user_id="user_001", agent_id="myapp", run_id="global")

results = memory.search(
    query="What shoe size does this customer wear?",
    user_id="user_001",
    limit=5,
)
# mem0's search() returns a similarity score (higher = more similar),
# which is the inverse of raw FT.SEARCH COSINE distance (lower = more similar).
for entry in results["results"]:
    if entry.get("score", 0) >= 0.7:
        print(f"Memory: {entry['memory']}  (score: {entry['score']:.2f})")
```

**Important:** Always pass a truthy `run_id` (default to `"global"`).

---

## 2. Semantic Memory Without mem0

For teams that don't want the mem0 dependency, use the Valkey search commands directly. The building blocks (FT.CREATE schema, binary encoding, FT.SEARCH with TAG filters, result parsing) are all in `elasticache-search.md`.

Key differences from the generic patterns there:

* **Prefix:** `memory:{uuid}` to scope the index
* **Schema fields:** `user_id` TAG (isolation), `memory_type` TAG (short/long), `created_at` NUMERIC, `memory` TAG.

> **Note:** ElastiCache supports three field types for FT.CREATE: TAG, NUMERIC, and VECTOR. TAG fields support exact-match filtering. The TEXT field type (which supports full-text search) is only available on MemoryDB, not ElastiCache.

* **Query pattern:** always pre-filter by `user_id` before KNN: `(@user_id:{user123})=>[KNN 5 @embedding $vec AS score]`
* **TTL:** 90 days for long-term, 30 days for short-term, applied via EXPIRE after HSET

Use `generate_embedding()` and `embedding_to_bytes()` from the shared embedding utility. See `embedding-providers.md`.

---

## 3. Key Design Principles

**Namespace by user_id.** Every memory query should filter by `user_id` to isolate data across users. In mem0, this is automatic (pass `user_id=` to every call). In raw Valkey, use a TAG filter: `@user_id:{user123}`.

**Scope by agent_id.** In multi-agent systems, use `agent_id` to separate memories per agent. One agent's learned facts should not bleed into another's context.

**Scope by run_id within a session.** Use `run_id` to associate memories with a specific session or run. This lets you query "what did the agent learn in this session?" separately from "what does the agent know about this user overall?"

**Search threshold: 0.7.** A cosine similarity of 0.7 is a good default for memory relevance. Below that, results tend to be tangentially related rather than genuinely useful. Tune based on your embedding model and use case.

---

## Cross-References

* Conversation persistence (session state, no vector search): see `session-store.md`
* Embedding model selection and configuration: see `embedding-providers.md`
* ElastiCache platform constraints, FT.SEARCH encoding, HNSW tuning: see `elasticache-search.md`
* LangChain/LlamaIndex framework integration: see `framework-guide.md`
