# Semantic Cache Implementation Guide

## When to use

Semantic cache for LLM/API responses. Avoids redundant inference calls when prompts are semantically similar (not just exact match). Two deployment options:

* **Application-side comparison** (serverless OK): Generate embeddings in app code, compare locally. No vector index needed in Valkey, just store/retrieve by key. Works with ElastiCache Serverless.
* **Server-side vector similarity** (node-based Valkey 8.2 or above required; recommend 9.0): FT.SEARCH with KNN finds the nearest cached prompt. Sub-millisecond lookup. Requires ElastiCache node-based with search enabled.

This guide covers the server-side approach. For the application-side approach (serverless OK, any Valkey version), use the `python_knn_search` fallback in `elasticache-search.md` with semantic cache key patterns below.

**Before using any FT.* code below**, call `supports_ft_search(client)` from `elasticache-search.md`. If it returns `False`, use the Python-side fallback instead.

## Key design

Use a dual-key pattern. Separate the vector index hash from the response payload:

```
semcache:vec:{request_id}   # HASH: embedding, request_id, timestamp, filter fields
semcache:rr:{request_id}    # HASH: request_text, response_text, created_at
```

Why separate keys: the vector index only scans the `vec:` prefix. Response payloads can be large (full LLM output) and do not need indexing. Keeping them out of the index reduces memory pressure on HNSW graph traversal.

**Cluster mode:** If running on a multi-shard cluster, use hash tags to ensure all keys for a single index land on the same shard:

```
semcache:vec:{myapp}:{request_id}
semcache:rr:{myapp}:{request_id}
```

The `{myapp}` hash tag forces slot co-location. Without this, FT.SEARCH returns partial results (it only queries the shard it executes on). See `elasticache-search.md` Hash Slot Constraint for details. For single-shard clusters, hash tags are optional since all keys land on the same shard.

```python
PREFIX_VECTOR = "semcache:vec:"
PREFIX_RR     = "semcache:rr:"
INDEX_NAME    = "idx:semcache"
```

## Step 1: Create the index

```python
import time
import uuid
from utils.embeddings import VECTOR_DIM

def create_index(client):
    """Create HNSW COSINE vector index. Idempotent."""
    try:
        client.execute_command(
            "FT.CREATE", INDEX_NAME,
            "ON", "HASH",
            "PREFIX", "1", PREFIX_VECTOR,
            "SCHEMA",
            "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(VECTOR_DIM),
                "DISTANCE_METRIC", "COSINE",
            "request_id", "TAG",
            "scope", "TAG", "SEPARATOR", ",",
            "timestamp", "NUMERIC",
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise
```

**Index limit:** A maximum of 10 indexes can be created per cluster. For multi-tenant designs, use TAG-based filtering within a single index rather than creating per-tenant indexes.

**HNSW tuning parameters:** The index above uses HNSW defaults (`M=16`, `EF_CONSTRUCTION=200`, `EF_RUNTIME=10`). For semantic cache workloads, the default `EF_RUNTIME` of 10 may yield suboptimal recall; consider increasing it (e.g., 50-200) via the `EF_RUNTIME` query modifier on `FT.SEARCH` to improve cache hit detection. Higher `M` values (e.g., 32+) improve recall at the cost of memory. `EF_CONSTRUCTION` values of 200-400 are generally sufficient. See the [vector search overview](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/vector-search-overview.html) for detailed guidance on tuning these parameters.

## Step 2: Cache lookup (FT.SEARCH)

All code below uses the shared embedding utility:

```python
from utils.embeddings import generate_embedding, embedding_to_bytes, VECTOR_DIM
```

```python
SIMILARITY_THRESHOLD = 0.90  # default cosine similarity; tune per use case

def cache_lookup(client, query_vec: bytes, threshold: float = SIMILARITY_THRESHOLD) -> dict | None:
    """Search for a semantically similar cached prompt using a precomputed query
    embedding (bytes from embedding_to_bytes). Returns hit dict or None."""

    result = client.execute_command(
        "FT.SEARCH", INDEX_NAME,
        "*=>[KNN 1 @embedding $vec AS score]",
        "PARAMS", "2", "vec", query_vec,
        "RETURN", "2", "request_id", "score",
        "DIALECT", "2",
    )

    if not result or int(result[0]) == 0:
        return None

    # Parse result: [total_hits, key_name, [field, value, ...]]
    # With decode_responses=False, all values are bytes
    fields = result[2]
    doc = {}
    for i in range(0, len(fields), 2):
        k = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
        v = fields[i+1].decode() if isinstance(fields[i+1], bytes) else fields[i+1]
        doc[k] = v

    # Cosine distance to similarity: distance 0=identical, 2=opposite.
    similarity = 1.0 - (float(doc["score"]) / 2.0)

    if similarity < threshold:
        return None

    # Fetch the cached response from the rr key
    request_id = doc["request_id"]
    rr_key = f"{PREFIX_RR}{request_id}"
    rr_data = client.hgetall(rr_key)
    if not rr_data:
        return None

    # Decode bytes keys/values from hgetall
    response_text = rr_data.get(b"response_text", b"").decode()

    return {
        "response": response_text,
        "similarity": similarity,
        "request_id": request_id,
    }
```

## Step 3: Cache store (HSET)

```python
def cache_store(client, prompt: str, response: str, embedding_bytes: bytes,
                scope: str = "", ttl: int = 3600):
    """Store prompt+response pair. Sets TTL on both keys."""
    request_id = str(uuid.uuid4())
    now = time.time()

    # Vector key (indexed)
    vec_key = f"{PREFIX_VECTOR}{request_id}"
    client.hset(vec_key, mapping={
        "embedding": embedding_bytes,
        "request_id": request_id,
        "timestamp": str(now),
        "scope": scope if scope else "",
    })

    # Response key (not indexed)
    rr_key = f"{PREFIX_RR}{request_id}"
    client.hset(rr_key, mapping={
        "request_text": prompt,
        "response_text": response,
        "created_at": str(now),
    })

    if ttl > 0:
        # Add random jitter to spread out cache invalidations and prevent
        # thundering herd when many entries expire simultaneously.
        import random
        jitter = random.randint(0, max(1, ttl // 10))  # up to 10% jitter
        client.expire(vec_key, ttl + jitter)
        client.expire(rr_key, ttl + jitter)
```

## Step 4: Full flow

```python
def semantic_cache_query(client, prompt: str, llm_fn, threshold: float = 0.90,
                         scope: str = "", ttl: int = 3600) -> dict:
    """
    Complete semantic cache flow.
    llm_fn: callable that takes a prompt string and returns response string.
    """
    # Compute the query embedding once and reuse it for lookup and store.
    embedding_bytes = embedding_to_bytes(generate_embedding(prompt))

    # Lookup
    hit = cache_lookup(client, embedding_bytes, threshold=threshold)
    if hit:
        return {"response": hit["response"], "source": "cache", "similarity": hit["similarity"]}

    # Miss: call LLM
    response = llm_fn(prompt)

    # Store (reuses the embedding already computed above)
    cache_store(client, prompt, response, embedding_bytes, scope=scope, ttl=ttl)

    return {"response": response, "source": "llm", "similarity": 0.0}
```

## Similarity thresholds

> **Note:** ElastiCache vector search uses cosine distance (1 - cosine_similarity), where 0 = identical and 1 = orthogonal. A distance threshold of 0.10 corresponds to cosine similarity ≥ 0.90.

Starting recommendations:

| Use case | Threshold | Notes |
|----------|-----------|-------|
| Factual Q&A, API calls | 0.90 - 0.95 | Strict. Wrong answer is costly. |
| Customer support / FAQ | 0.85 - 0.90 | Moderate. Slightly paraphrased questions should hit. |
| General chat, creative | 0.70 - 0.85 | Lenient. Accept broader semantic matches. |
| Sub-agent (tool dispatch) | 0.65 - 0.70 | Very lenient. From production: THRESHOLD_SUBAGENT = 0.70 |

Lower threshold = more cache hits but higher risk of returning a semantically incorrect answer. Start strict (0.92) and lower based on observed false-hit rate.

## Advanced: hybrid filtering

Add TAG or NUMERIC pre-filters to scope cache hits before vector similarity runs. This narrows the candidate set so KNN only compares within a relevant subset.

```python
# Pre-filter by model version and user segment, then KNN
pre_filter = "(@scope:{bedrock_claude_v4} @timestamp:[1700000000 +inf])"
query = f"{pre_filter}=>[KNN 1 @embedding $vec AS score]"

result = client.execute_command(
    "FT.SEARCH", INDEX_NAME, query,
    "PARAMS", "2", "vec", query_vec,
    "RETURN", "2", "request_id", "score",
    "DIALECT", "2",
)
```

Filter patterns:

* `@scope:{model_v2}` filters TAG field to exact token
* `@timestamp:[{cutoff} +inf]` filters NUMERIC to recent entries only
* Multiple filters combine with implicit AND inside parentheses
* Escape hyphens in TAG values: `my\\-value`
