# ElastiCache Vector Search Constraints

This file contains all ElastiCache-specific constraints for vector search. Loaded on-demand when any genai pattern needs vector search (Mode 2 server-side or Mode 3).

---

## Platform Gate

| Requirement | Detail |
|---|---|
| Engine | ElastiCache engine version 8.2 or above for Valkey (node-based only). Note: server reports `valkey_version` as 8.1.x. ElastiCache engine version 8.2 (shown in AWS Console and API) maps to the underlying Valkey OSS version 8.1.x in `INFO server` output. Use `FT._LIST` to confirm vector search availability. |
| Serverless | NOT supported. Vector search is unavailable on serverless. |
| Data-tiering nodes | NOT supported (r6gd family) |

This is the single most common mistake. Serverless ElastiCache cannot run vector search.

## Version Detection (MUST run before any FT.* command)

Before emitting any FT.CREATE, FT.SEARCH, or other FT.* command, detect the server version and confirm vector search support. Vanilla Valkey 8.0.x does NOT have FT.CREATE. Only Valkey 8.2 or above on node-based ElastiCache supports it.

```python
from valkey.exceptions import ResponseError

def get_valkey_version(client) -> tuple[int, int]:
    """Return (major, minor) version of the connected Valkey/Redis server."""
    info = client.info("server")
    ver = info.get("valkey_version", info.get("redis_version", "0.0"))
    major, minor = int(ver.split(".")[0]), int(ver.split(".")[1])
    return major, minor

def supports_ft_search(client) -> bool:
    """True if the server supports FT.* vector search commands.

    Uses FT._LIST probing instead of version comparison because
    ElastiCache v8.2 reports valkey_version as 8.1.x, making
    version-based detection unreliable.
    """
    try:
        client.execute_command("FT._LIST")
        return True
    except ResponseError:
        return False
```

**Usage pattern:** Call `supports_ft_search(client)` once at startup. If it returns `False`, use the Python-side fallback below instead of FT.* commands. Never assume FT.CREATE is available without checking.

**Note:** Because ElastiCache v8.2 reports `valkey_version` as `8.1.x`, the `get_valkey_version` helper above should NOT be used for vector search detection. The `supports_ft_search` function probes with `FT._LIST` which is reliable regardless of reported version.

---

## Python-Side Vector Search Fallback

When the server does not support FT.* commands (Valkey < 8.2, serverless, or any environment without search), use application-side cosine similarity. This approach stores vectors as binary HASH fields and performs brute-force KNN in Python. Suitable for datasets under ~50K vectors.

```python
import struct
import math

def python_cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors using only stdlib."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def python_knn_search(client, prefix: str, query_vec: list[float],
                      vector_field: str = "embedding", k: int = 5,
                      filter_field: str = None, filter_value: str = None) -> list[dict]:
    """Brute-force KNN search using Python-side cosine similarity.

    Scans all keys matching prefix, decodes stored FLOAT32 vectors,
    computes cosine similarity, returns top-k results sorted by similarity.
    """
    cursor = 0
    results = []
    dim = len(query_vec)

    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=200)
        for key in keys:
            data = client.hgetall(key)
            if filter_field and filter_value:
                field_key = filter_field.encode() if isinstance(filter_field, str) else filter_field
                stored = data.get(field_key, b"").decode()
                if stored != filter_value:
                    continue
            vec_bytes = data.get(vector_field.encode() if isinstance(vector_field, str) else vector_field)
            if not vec_bytes or len(vec_bytes) != dim * 4:
                continue
            stored_vec = list(struct.unpack(f"{dim}f", vec_bytes))
            score = python_cosine_similarity(query_vec, stored_vec)
            key_str = key.decode() if isinstance(key, bytes) else key
            results.append({"key": key_str, "similarity": score, "data": data})

        if cursor == 0:
            break

    results.sort(key=lambda x: -x["similarity"])
    return results[:k]
```

**Integration pattern:** Use `supports_ft_search` to pick the right path at startup:

```python
client = get_client()
if supports_ft_search(client):
    ensure_index(client)
    hits = search_similar(client, query_embedding, top_k=5)
else:
    hits = python_knn_search(client, PREFIX, query_embedding, k=5)
```

---

## Command Boundary

| Command | Status on ElastiCache |
|---|---|
| FT.CREATE | Documented, supported |
| FT.SEARCH | Documented, supported |
| FT.INFO | Documented, supported |
| FT._LIST | Documented, supported |
| FT.DROPINDEX | Documented, supported |

> **⚠️ FT.AGGREGATE is NOT available on ElastiCache.** FT.AGGREGATE is supported on Amazon MemoryDB but is not supported on ElastiCache. If you need server-side aggregation over vector search results, use MemoryDB or perform aggregation client-side after FT.SEARCH.

---

## Hard Limits

| Limit | Value |
|---|---|
| Max indexes per cluster | 10 |
| Max fields per index | 50 |
| Max vector dimensions | 32768 |
| HNSW M (max edges per node) | 2,000,000 (practical recommendation: 16–64 for most workloads; higher values increase memory usage and index build time) |
| HNSW EF_CONSTRUCTION | 4096 |
| HNSW EF_RUNTIME | 4096 |
| Max prefixes per index | 16 |
| Tag field max length | 10,000 |
| Numeric field max length | 256 |

**Transaction restriction:** FT.CREATE, FT.DROPINDEX, and alias commands CANNOT run inside MULTI/EXEC, Lua scripts, or functions.

---

## Index Lifecycle / Backfill

FT.CREATE triggers a background backfill for all existing keys matching the PREFIX. Query operations attempted while an index is undergoing backfill are not allowed and are terminated with an error.

> **Backfill types:** During initial index creation (FT.CREATE), queries against the index are blocked and return an error until backfill completes. However, during scaling events (e.g., adding shards), the index may undergo backfill with reduced recall for search queries — queries are allowed but may return incomplete results.

**Check readiness with FT.INFO.** Key fields to monitor:

| Field | Meaning |
|---|---|
| `backfill_in_progress` | Whether backfill is still running |
| `backfill_percent_complete` | Estimate of backfill completion, a fractional number in the range [0..1] |
| `mutation_queue_size` | Pending mutations waiting to be indexed |
| `recent_mutations_queue_delay` | Lag between writes and indexing |
| `state` | Must be `ready` before querying |

Wait for `state=ready` before issuing FT.SEARCH.

---

## Hash Slot Constraint (Cluster Mode)

All keys queried by a single FT.SEARCH must reside in the same hash slot. Use hash tags to guarantee slot co-location:

```
doc:{myprefix}:chunk_001
doc:{myprefix}:chunk_002
```

The `{myprefix}` portion determines the slot. Without hash tags on multi-shard clusters, FT.SEARCH only returns results from the shard it executes on.

---

## Client Connection for Vector Operations

When using valkey-py or redis-py for vector operations, set `decode_responses=False`. Vector data is binary (FLOAT32 bytes) and must not be decoded as UTF-8.

```python
import valkey

client = valkey.Valkey(
    host="endpoint", port=6379,
    ssl=True, ssl_cert_reqs="required",  # validate the server cert (production default)
    # ssl_ca_certs="/path/to/ca-bundle.pem",  # only if your OS lacks a system CA store
    # Dev/tunnel ONLY (e.g. SSH tunnel to localhost, where the cert name won't match):
    # ssl_cert_reqs="none",  # INSECURE: disables cert validation; never in production
    decode_responses=False,  # CRITICAL for vector operations
)
```

If you need `decode_responses=True` for non-vector operations (session store, counters), use a separate client instance.

**Do NOT** use the high-level `valkey.commands.search` or `redis.commands.search` Python wrappers for FT.* commands. Their parameter signatures vary across library versions and produce hard-to-debug failures. Use `client.execute_command()` for all FT.CREATE, FT.SEARCH, FT.INFO, and FT.DROPINDEX calls.

**Do NOT** create the Valkey/Redis client at module level (top of file, import time). Always initialize connections inside a function or on first use. Module-level connections crash applications that import the module before the cache is reachable.

**Do NOT** call FT.CREATE at module level or import time. Create indexes lazily in an explicit setup function, guarded by an "already exists" check.

---

## Vector Binary Encoding

HASH vectors must be stored as binary little-endian IEEE 754 FLOAT32.

**Python encoding:**

```python
import struct
binary = struct.pack(f"{len(vec)}f", *vec)
```

* JSON vectors are stored as arrays (no binary encoding needed).
* Query vectors passed via PARAMS are also FLOAT32 bytes.

**Do NOT** use numpy for vector byte packing. Use only `struct.pack` from the Python standard library. numpy may not be available in all deployment environments.

---

## Distance to Similarity Conversion

FT.SEARCH returns cosine DISTANCE, not similarity.

| Value | Meaning (distance) | Meaning (similarity) |
|---|---|---|
| 0 | Identical | 1.0 |
| 2 | Opposite | 0.0 |

**Conversion:** `similarity = 1.0 - (distance / 2.0)` # Normalized to [0,1]; standard cosine similarity = 1 - distance

Cosine distance ranges from 0 (identical) to 2 (opposite). This formula normalizes to [0, 1].

Many models and tutorials use similarity (0=opposite, 1=identical). Mixing these up inverts threshold logic.

---

## FT.CREATE Schema Reference

```
FT.CREATE idx ON HASH PREFIX 1 prefix:
  SCHEMA
  embedding VECTOR HNSW 6 TYPE FLOAT32 DIM <VECTOR_DIM> DISTANCE_METRIC COSINE
  request_id TAG
  state_tags TAG SEPARATOR ,
  slot_budget_usd NUMERIC
```

Key details:

* `6` after HNSW means 3 key-value pairs follow (TYPE, DIM, DISTANCE_METRIC). The number is the total count of arguments, not the number of pairs.
* `PREFIX 1 prefix:` scopes which hashes get indexed. The `1` is the number of prefixes.
* `TAG SEPARATOR ,` is optional. The default separator is `,`. Only specify SEPARATOR if you need a different delimiter character.

---

## FT.SEARCH Query Reference

Hybrid query with pre-filters:

```
FT.SEARCH idx "(@tag:{value})=>[KNN 1 @embedding $vec AS score]"
  PARAMS 2 vec <binary_vector>
  RETURN 2 request_id score
  DIALECT 2
```

* `DIALECT 2` is required for KNN queries.
* `PARAMS 2` means 1 key-value pair follows (param name, param value). The number is the total count of arguments.
* Pre-filter goes before `=>`. Only documents matching the filter enter the KNN stage.

**Parsing FT.SEARCH results (valkey-py / redis-py with decode_responses=False):**

```python
# result = [total_count, key_name_bytes, [field_bytes, value_bytes, ...], ...]
total = int(result[0])
if total == 0:
    return None

key_name = result[1]  # bytes
fields = result[2]    # flat list: [b"field1", b"value1", b"field2", b"value2", ...]
doc = {}
for i in range(0, len(fields), 2):
    k = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
    v = fields[i+1].decode() if isinstance(fields[i+1], bytes) else fields[i+1]
    doc[k] = v

distance = float(doc["score"])
similarity = 1.0 - (distance / 2.0)  # Normalized to [0,1]; standard cosine similarity = 1 - distance
```

The result format is a flat list, not a dict. Field names and values alternate. With `decode_responses=False`, all values are bytes and must be decoded manually.

---

## FLAT vs HNSW

Use FLAT for small datasets (<10K vectors). Exact brute-force search, no graph overhead, zero tuning. Switch to HNSW when dataset grows and query latency matters.

---

## HNSW Tuning Defaults

| Parameter | Default | Effect |
|---|---|---|
| M | 16 (max 2,000,000 per AWS limits; practical recommendation: 16-64 for most workloads) | Graph connectivity; higher = better recall, more memory |
| EF_CONSTRUCTION | 200 (max 4096) | Build-time search depth; higher = better index quality, slower writes |
| EF_RUNTIME | 10 (max 4096) | Query-time search depth; higher = better recall, slower queries. Can be overridden per-query. |

---

## TAG Field Escaping

Hyphens in TAG values must be escaped in queries:

```python
escaped = value.replace("-", "\\-")
```

Spaces should be replaced with underscores before storing.

---

## Complete Vector Search Recipe

Self-contained working example. Copy and adapt. Uses only stdlib + valkey-py, lazy connection, execute_command for all FT.* calls.

```python
import struct
import valkey

VECTOR_DIM = 384  # match your embedding model's output dimensions
INDEX_NAME = "idx:items"
PREFIX = "item:"

def get_client():
    """Lazy connection. Never call at module level."""
    return valkey.Valkey(
        host="your-endpoint", port=6379,
        ssl=True, ssl_cert_reqs="required",  # validate the server cert (production default)
        # ssl_ca_certs="/path/to/ca-bundle.pem",  # only if your OS lacks a system CA store
        # Dev/tunnel ONLY (e.g. SSH tunnel to localhost, where the cert name won't match):
        # ssl_cert_reqs="none",  # INSECURE: disables cert validation; never in production
        decode_responses=False,
    )

def ensure_index(client):
    """Create index if it doesn't exist. Call once at app startup, not at import time."""
    try:
        client.execute_command(
            "FT.CREATE", INDEX_NAME,
            "ON", "HASH",
            "PREFIX", "1", PREFIX,
            "SCHEMA",
            "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32", "DIM", str(VECTOR_DIM), "DISTANCE_METRIC", "COSINE",
            "category", "TAG",
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

def store_vector(client, item_id, embedding, category=""):
    """Store a vector. embedding is a list of floats."""
    key = f"{PREFIX}{item_id}"
    client.hset(key, mapping={
        "embedding": struct.pack(f"{VECTOR_DIM}f", *embedding),
        "category": category,
    })

def search_similar(client, query_embedding, top_k=5):
    """KNN search. Returns list of {key, similarity} dicts."""
    query_bytes = struct.pack(f"{VECTOR_DIM}f", *query_embedding)

    result = client.execute_command(
        "FT.SEARCH", INDEX_NAME,
        f"*=>[KNN {top_k} @embedding $vec AS score]",
        "PARAMS", "2", "vec", query_bytes,
        "RETURN", "1", "score",
        "LIMIT", "0", str(top_k),
        "DIALECT", "2",
    )

    if int(result[0]) == 0:
        return []

    hits = []
    for i in range(1, len(result), 2):
        key = result[i].decode() if isinstance(result[i], bytes) else result[i]
        fields = result[i + 1]
        field_dict = {}
        for j in range(0, len(fields), 2):
            k = fields[j].decode() if isinstance(fields[j], bytes) else fields[j]
            v = fields[j+1].decode() if isinstance(fields[j+1], bytes) else fields[j+1]
            field_dict[k] = v
        distance = float(field_dict["score"])
        similarity = 1.0 - (distance / 2.0)  # Normalized to [0,1]; standard cosine similarity = 1 - distance
        hits.append({"key": key, "similarity": similarity})

    return hits
```

---

## Error Recovery

Common failures and how to fix them.

**App crashes on import / startup:**
Move all `valkey.Valkey()` calls and `FT.CREATE` calls out of module scope. Wrap in a `get_client()` function called inside route handlers or on first use.

**`ImportError: No module named 'numpy'`:**
Replace `numpy.array(...).tobytes()` with `struct.pack(f"{len(vec)}f", *vec)`. Never depend on numpy for vector byte packing.

**`FT.CREATE` returns an error:**
Verify the command matches the exact syntax: `FT.CREATE <name> ON HASH PREFIX 1 <prefix> SCHEMA <fields>`. The most common mistakes: missing `SCHEMA` keyword, wrong argument count after `HNSW` (must be `6` for 3 key-value pairs: TYPE, DIM, DISTANCE_METRIC), or using `INDEX` instead of `CREATE`.

**`FT.SEARCH` returns 0 results when data exists:**

1. Check index state: `FT.INFO <index_name>`, look for `state: ready`. If backfill is in progress, wait.
2. Check `DIALECT 2` is present in the query. KNN queries require it.
3. Check the query vector is FLOAT32 bytes (struct.pack), not a string or list.
4. Check the key prefix matches what FT.CREATE was given.

**`ResponseError` mentioning `valkey.commands.search`:**
Do not use the high-level Python search wrapper. Replace with `client.execute_command("FT.SEARCH", ...)` as shown in the recipe above.

**Score/similarity values seem inverted:**
COSINE distance is 0 (identical) to 2 (opposite). Convert with `similarity = 1.0 - (distance / 2.0)`. If your thresholds aren't working, verify you're comparing similarity (not distance) against the threshold.
