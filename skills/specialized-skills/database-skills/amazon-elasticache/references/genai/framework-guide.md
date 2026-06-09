# Framework Integration Guide

How to connect popular AI/ML frameworks to ElastiCache Valkey. This file covers framework-specific wiring only. For full implementation patterns, see the dedicated guides linked in each section.

---

## 1. Strands Agents

**Package:** `strands-valkey-session-manager` (community package, v0.1.0+ — MIT license, maintained by jeromevdl)

Import: `from strands_valkey_session_manager import ValkeySessionManager`

Implements Strands' `SessionManager` interface. Persists conversation messages, agent state, and session metadata to Valkey automatically. Serverless OK.

For full setup code and key design patterns, see `session-store.md`.

Strands does not include a built-in semantic cache. Wrap the agent call with cache check/store logic using the approach in `semantic-cache.md`.

---

## 2. mem0

**Package:** `mem0`

Native Valkey vector store provider (`provider: "valkey"`). Handles index creation, embedding storage, and similarity search internally. Requires node-based Valkey 8.2 or later (recommend 9.0).

Key wiring points:

* Use `valkeys://` URL scheme (the `s` enables TLS). Port 6379 for node-based.
* The `llm` block is required for mem0's fact extraction. Use Bedrock:

  ```python
  "llm": {
      "provider": "aws_bedrock",
      "config": {
          "model": "us.anthropic.claude-sonnet-4-6-v1:0",
          "max_tokens": 512,
      }
  }
  ```

* Always pass a `user_id` to `memory.add()` and `memory.search()` for user-scoped memory isolation.
* Key config fields: `embedding_model_dims` (e.g., `1024` for Titan V2) and `index_type` (`flat` or `hnsw`).

For full mem0 config, HNSW parameters, short/long-term memory patterns, and identity model, see `agent-memory.md`. For mem0 embedder configs per provider, see `embedding-providers.md`.

---

## 3. LangChain / LangGraph

**Package:** `langgraph-checkpoint-aws` (install with `pip install 'langgraph-checkpoint-aws[valkey]'`)

### Checkpointing (ValkeySaver)

Persist LangGraph agent state across invocations.

```python
from langgraph_checkpoint_aws import ValkeySaver

with ValkeySaver.from_conn_string(
    "valkeys://your-cluster.serverless.use1.cache.amazonaws.com:6379",
    ttl_seconds=3600,
) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "session-1"}}
    result = graph.invoke({"messages": [HumanMessage(content="Hello")]}, config)
```

### LLM Caching (ValkeyCache)

Exact-match caching of LLM responses (no vector search needed, works on serverless).

```python
from langgraph_checkpoint_aws import ValkeyCache

cache = ValkeyCache.from_conn_string(
    "valkeys://your-cluster.serverless.use1.cache.amazonaws.com:6379",
    prefix="llm_cache:",
    ttl=3600,
)
```

Use `valkeys://` URL scheme for TLS.

### Semantic Caching (ValkeyStore)

Vector-based semantic caching of LLM responses (requires node-based Valkey 8.2 or later; recommend 9.0).

```python
from langgraph_checkpoint_aws import ValkeyStore, ValkeyIndexConfig

index_config = ValkeyIndexConfig(
    collection_name="semantic_cache",
    embed=embeddings,
    fields=["query"],
    index_type="HNSW",
    dims=1024,
)

store = ValkeyStore.from_conn_string(
    "valkeys://your-cluster.cache.amazonaws.com:6379",
    index=index_config,
)
store.setup()
```

Unlike ValkeyCache (exact-match), ValkeyStore uses vector search to match semantically similar queries. For full implementation, see `semantic-cache.md`.

---

## 4. ElastiCache TLS Connection Reference

All frameworks must use TLS when connecting to ElastiCache.

| Client / Framework | TLS mechanism | Example |
|---|---|---|
| valkey-py | `ssl=True, ssl_cert_reqs="required"` (use `"none"` only for tunnel/dev) | `valkey.Valkey(host=..., ssl=True, ssl_cert_reqs="required")` |
| valkey-glide | `use_tls=True` + `TlsAdvancedConfiguration(use_insecure_tls=True)` | See valkey-glide docs |
| URL-based (LangChain) | `valkeys://` scheme | `valkeys://endpoint:6379` |
| mem0 | `valkeys://` URL scheme in `valkey_url` config | `valkeys://your-cluster.cache.amazonaws.com:6379` |
| Strands session manager | Pass a TLS-configured `valkey.Valkey` client | See `session-store.md` |

### Port Reference

| Cluster type | Default port | Notes |
|---|---|---|
| Node-based (primary) | 6379 | Standard Valkey port |
| Node-based (reader) | 6379 | Same port as primary; use the reader endpoint address |
| Serverless (primary) | 6379 | Single endpoint |
| Serverless (reader) | 6380 | Eventually-consistent reads routed to closest node (could be primary). Obtain the address from the `ReaderEndpoint` attribute in `DescribeServerlessCaches`. |

**Security group note:** For serverless caches, your VPC security group must allow inbound TCP on both port 6379 (primary) and port 6380 (reader). If you only open 6379, reader-endpoint connections will fail silently.

For raw valkey-py and valkey-glide connection examples, see `elasticache-search.md`. For IAM authentication setup, see the setup sub-skill (`references/setup/auth-model-selector.md`).
