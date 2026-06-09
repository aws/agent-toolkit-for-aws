# Session Store Implementation Guide

Session state, message history, and resumable conversations with ElastiCache Valkey. Plain data structures, no vector search, no embedding model. Works on serverless.

> **Serverless eviction policy:** Serverless caches use `volatile-lru` (not configurable), which only evicts keys that have a TTL set. Always set a TTL on every key. Keys without a TTL will never be evicted and can cause OOM errors. The `allkeys-lru` policy recommended in some best-practice guides applies only to node-based clusters.

## Key Design

```
{conv:session_id}:messages     # JSON-encoded list of message dicts
{conv:session_id}:metadata     # JSON-encoded conversation metadata
conv:user:{user_id}:sessions   # sorted set of session_ids, score = timestamp
```

**Hash tag note:** The `{conv:session_id}` hash tag ensures messages and metadata keys hash to the same slot on cluster-mode-enabled caches (including serverless). Without a hash tag, pipeline operations on these keys are non-atomic across slots and a mid-pipeline failure could leave partial state. The `conv:user:{user_id}:sessions` index key does not share a hash tag with the message/metadata keys, so it hashes to a different slot. This is acceptable because the index is advisory (listing sessions), not transactional.

## Store and Load Pattern (Custom)

Use this when you're not on the Strands framework and need direct control over session storage.

```python
# pip install valkey
# For serverless or cluster-mode-enabled node-based clusters:
#   from valkey.cluster import ValkeyCluster
# For cluster-mode-disabled node-based clusters:
#   import valkey  (use valkey.Valkey)
import json
import time
import valkey

CONVERSATION_TTL = 30 * 24 * 60 * 60  # 30 days (adjust to your retention policy)

_client = None

def get_client():
    """Lazy client initialization. Never create connections at module level.

    For serverless or cluster-mode-enabled node-based clusters, use
    valkey.cluster.ValkeyCluster instead of valkey.Valkey.
    Serverless is always cluster-mode-enabled. The single serverless
    endpoint abstracts slots to one virtual node, so ValkeyCluster
    works transparently. For cluster-mode-disabled node-based clusters,
    valkey.Valkey is correct.
    """
    global _client
    if _client is None:
        _client = valkey.ValkeyCluster(
            host="your-endpoint.serverless.use1.cache.amazonaws.com",  # serverless format; node-based differs
            port=6379, ssl=True, ssl_cert_reqs="required",  # verify server cert against trusted CAs (secure default)
            # ssl_cert_reqs="none",  # tunnel/dev ONLY (e.g. local SSH tunnel); never in production
            decode_responses=True, socket_timeout=5,
        )
    return _client

def save_session(session_id: str, messages: list[dict], metadata: dict,
                 user_id: str = None):
    """Persist conversation state. Call after each turn."""
    msg_key = f"{{conv:{session_id}}}:messages"
    meta_key = f"{{conv:{session_id}}}:metadata"
    client = get_client()

    pipe = client.pipeline()
    pipe.set(msg_key, json.dumps(messages, default=str))
    pipe.expire(msg_key, CONVERSATION_TTL)
    pipe.set(meta_key, json.dumps(metadata, default=str))
    pipe.expire(meta_key, CONVERSATION_TTL)

    if user_id:
        # Note: idx_key hashes to a different slot than {conv:session_id} keys.
        # On cluster-mode-enabled caches (including serverless), this pipeline
        # becomes a multi-slot pipeline. ValkeyCluster handles this transparently
        # by splitting commands across slots, but atomicity is only guaranteed
        # within a single slot. If you need atomic user-index updates, issue
        # the ZADD/EXPIRE separately outside the pipeline.
        idx_key = f"conv:user:{user_id}:sessions"
        pipe.zadd(idx_key, {session_id: time.time()})
        pipe.expire(idx_key, CONVERSATION_TTL)

    pipe.execute()

def load_session(session_id: str) -> dict | None:
    """Load persisted conversation. Returns {messages, metadata} or None."""
    client = get_client()
    raw_messages = client.get(f"{{conv:{session_id}}}:messages")
    if not raw_messages:
        return None
    raw_metadata = client.get(f"{{conv:{session_id}}}:metadata")
    return {
        "messages": json.loads(raw_messages),
        "metadata": json.loads(raw_metadata) if raw_metadata else {},
    }

def list_user_sessions(user_id: str, limit: int = 20) -> list[str]:
    """Most recent sessions first."""
    return get_client().zrevrange(f"conv:user:{user_id}:sessions", 0, limit - 1)
```

## Strands Integration

The `strands-valkey-session-manager` package (community package, v0.1.0+ — MIT license, maintained by jeromevdl) provides a drop-in `ValkeySessionManager`. Five lines of setup:

```python
import valkey
from strands import Agent
from strands_valkey_session_manager import ValkeySessionManager

_strands_client = None

def get_strands_client():
    """Lazy client initialization. Never create connections at module level.
    Uses ValkeyCluster for serverless (cluster-mode-enabled).
    For cluster-mode-disabled node-based clusters, use valkey.Valkey instead.
    """
    global _strands_client
    if _strands_client is None:
        _strands_client = valkey.ValkeyCluster(
            host="your-endpoint.serverless.use1.cache.amazonaws.com", port=6379, ssl=True,
            ssl_cert_reqs="required", decode_responses=True,  # in-VPC EKS with real cert verification
            # tunnel/dev alternative: ssl_cert_reqs="none" (skips cert verification; not for production)
        )
    return _strands_client

def create_agent(session_id: str = "user-42") -> Agent:
    client = get_strands_client()
    session_mgr = ValkeySessionManager(session_id=session_id, client=client)
    return Agent(system_prompt="You are a helpful assistant.", session_manager=session_mgr)

# Usage:
# agent = create_agent("user-42")
# response = agent("My name is Alex and I'm building a RAG pipeline.")
```

The session manager stores three key types in Valkey: `session:{id}` (session record), `session:{id}:agent:{agent_id}` (agent state), and `session:{id}:agent:{agent_id}:message:{msg_id}` (individual messages).

## TTL Recommendations

| Scope | Recommended TTL |
|-------|----------------|
| Active session | 24 hours |
| Resumable session | 720 hours (~30 days) |
| Session index per user | 90 days |

---

## Cross-References

* Semantic memory (vector-based recall across sessions): see `agent-memory.md`
* LangChain/LlamaIndex/Strands framework integration: see `framework-guide.md`
