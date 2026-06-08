# RAG Retrieval with ElastiCache Valkey

## When to Use

RAG retrieval from ElastiCache Valkey. Best for:

- **Real-time knowledge bases**: Valkey indexes update automatically when matching keys are mutated. No batch re-indexing required.
- **Low-latency agentic AI retrieval**: Sub-millisecond vector search vs hundreds of ms from dedicated vector DBs.
- **Colocated vector + cache workloads**: The vector store lives alongside your application cache, eliminating a separate service hop.

## Deployment Requirement

Node-based Valkey 8.2 or above clusters only (recommend 9.0). Vector search is NOT available on serverless.
See `elasticache-search.md` for full platform constraints and limits.

**Cluster mode:** If running on a multi-shard cluster, use hash tags to ensure all document chunks for a single index land on the same shard:

```
doc:{corpus}:{doc_id}:{chunk_id}
```

The `{corpus}` hash tag forces slot co-location. Without this, FT.SEARCH returns partial results (it only queries the shard it executes on). See `elasticache-search.md` Hash Slot Constraint for details.

> **Note:** The code examples below use the simplified key pattern `doc:{doc_id}:{chunk_id}` which assumes a single-shard cluster. For multi-shard clusters, adapt the key pattern to include a hash tag, e.g., `doc:{corpus}:{doc_id}:{chunk_id}`, and update the index prefix accordingly.

---

## Step 1: Design the Document Schema

Use HASH keys with a consistent prefix. All keys matching the prefix are auto-indexed.

```
Key pattern: doc:{doc_id}:{chunk_id}

Fields:
  embedding    - FLOAT32 bytes (match your embedding model's dimensions)
  text         - the chunk text (plain string, not indexed for search)
  source       - source document name/path (TAG)
  category     - document category (TAG)
  created_at   - unix timestamp (NUMERIC)
  chunk_index  - position in source document (NUMERIC)
```

**Prefix-based scoping**: When the index uses `PREFIX 1 doc:`, every HASH key starting with `doc:` is automatically indexed. New keys, updated keys, and deleted keys are reflected in the index without manual intervention.

---

## Step 2: Create the Index

```python
from utils.embeddings import VECTOR_DIM

# Note: Maximum of 10 indexes can be created per cluster.
# For multi-tenant RAG, use TAG pre-filters on a shared index rather than per-tenant indexes.
client.execute_command(
    "FT.CREATE", "idx:docs",
    "ON", "HASH",
    "PREFIX", "1", "doc:",
    "SCHEMA",
    "embedding", "VECTOR", "HNSW", "6",
        "TYPE", "FLOAT32", "DIM", str(VECTOR_DIM), "DISTANCE_METRIC", "COSINE",
    "source", "TAG",
    "category", "TAG",
    "created_at", "NUMERIC",
    "chunk_index", "NUMERIC",
)
```

After creation, if matching keys already exist, Valkey backfills the index in the background. **Query operations attempted while an index is undergoing backfill are not allowed and are terminated with an error.** Wait for readiness before querying:

> **Backfill types:** During initial index creation (FT.CREATE), queries against the index are blocked and return an error until backfill completes. However, during scaling events (e.g., adding shards), the index may undergo backfill with reduced recall for search queries — queries are allowed but may return incomplete results.

```python
import time

def wait_for_index_ready(client, index_name, timeout=60):
    """Poll FT.INFO until index state is 'ready'.

    Note: FT.INFO returns a flat array with nested sub-arrays for some fields.
    This simple zip approach works for top-level fields like 'state' but is
    fragile if the response structure changes. For production use, iterate
    through the list looking for the 'state' key explicitly.
    """
    start = time.time()
    while time.time() - start < timeout:
        info = client.execute_command("FT.INFO", index_name)
        info_dict = dict(zip(info[::2], info[1::2]))
        state = info_dict.get("state") or info_dict.get(b"state")
        if state in ("ready", b"ready"):
            return True
        time.sleep(0.5)
    raise TimeoutError(f"Index {index_name} not ready after {timeout}s")
```

**Replica backfill caveat:** Backfill completion is not synchronized between primary and replicas. If your application reads from replicas, verify backfill completion on all replicas before issuing search queries. See `elasticache-search.md` for details.

---

## Step 3: Ingest Documents

Chunking, embedding, and storing in a pipeline batch:

```python
from utils.embeddings import generate_embedding, embedding_to_bytes

def ingest_documents(client, documents, batch_size=50):
    pipe = client.pipeline(transaction=False)
    count = 0

    for doc in documents:
        chunks = chunk_document(doc["text"])
        for i, chunk_text in enumerate(chunks):
            embedding = generate_embedding(chunk_text)

            key = f"doc:{doc['id']}:{i}"
            pipe.hset(key, mapping={
                "embedding": embedding_to_bytes(embedding),
                "text": chunk_text,
                "source": doc.get("source", ""),
                "category": doc.get("category", ""),
                "created_at": str(doc.get("created_at", -1)),
                "chunk_index": str(i),
            })
            count += 1

            if count % batch_size == 0:
                pipe.execute()
                pipe = client.pipeline(transaction=False)

    pipe.execute()
    return count
```

**Chunking guidance:**

| Content type | Chunk size | Overlap | Rationale |
|---|---|---|---|
| Factual Q&A, structured data, code | 256-512 tokens | 50 tokens | Precise retrieval; smaller chunks reduce noise in results |
| General documentation, how-to guides | 512-1024 tokens | 50-100 tokens | Balanced retrieval quality and context |
| Narrative content, long-form reasoning | 1024-2048 tokens | 100-200 tokens | Preserves reasoning chains and context |

Prefer chunking by semantic boundaries (paragraphs, sections, headers) over fixed-size splits when the source has structure. Fixed-size is acceptable for unstructured text.

Overlap prevents information loss at chunk boundaries. A sentence split across two chunks without overlap is lost to both. 10-20% overlap is the standard range.

Note: Bedrock Titan Embed v2 supports up to 8192 input tokens. For retrieval tasks, AWS recommends segmenting documents into logical segments such as paragraphs or sections rather than embedding at the maximum token length.

**Real-time updates**: To update a document chunk, just HSET the same key with new field values. Valkey re-indexes automatically. No rebuild needed.

---

## Step 4: Retrieve

Supports pure vector search or hybrid (vector + metadata pre-filters).

| Shape | Query String |
|-------|-------------|
| Pure vector | `*=>[KNN k @embedding $vec AS score]` |
| Vector + TAG filter | `(@category:{technical})=>[KNN k @embedding $vec AS score]` |
| Vector + numeric range | `(@created_at:[1700000000 +inf])=>[KNN k @embedding $vec AS score]` |
| Combined filters | `(@category:{technical} @created_at:[1700000000 +inf])=>[KNN k @embedding $vec AS score]` |

The filter expression is a **pre-filter**: it narrows the candidate set before KNN runs.

```python
from utils.embeddings import generate_embedding, embedding_to_bytes

def retrieve_chunks(client, query_text, category=None,
                    min_timestamp=None, top_k=5):
    query_bytes = embedding_to_bytes(generate_embedding(query_text))

    filter_parts = []
    if category:
        safe_cat = category.replace("-", "\\-")
        filter_parts.append(f"@category:{{{safe_cat}}}")
    if min_timestamp:
        filter_parts.append(f"@created_at:[{min_timestamp} +inf]")

    if filter_parts:
        pre_filter = "(" + " ".join(filter_parts) + ")"
        query_str = f"{pre_filter}=>[KNN {top_k} @embedding $vec AS score]"
    else:
        query_str = f"*=>[KNN {top_k} @embedding $vec AS score]"

    results = client.execute_command(
        "FT.SEARCH", "idx:docs", query_str,
        "PARAMS", "2", "vec", query_bytes,
        "RETURN", "3", "text", "source", "score",
        "LIMIT", "0", str(top_k),
        "DIALECT", "2",
    )

    chunks = []
    if results[0] == 0:
        return chunks

    for i in range(1, len(results), 2):
        fields = results[i + 1]
        field_dict = dict(zip(fields[::2], fields[1::2]))
        text = field_dict.get(b"text", b"").decode()
        source = field_dict.get(b"source", b"").decode()
        score = float(field_dict.get(b"score", b"0"))
        # COSINE distance is [0, 2] (0=identical, 2=opposite). Convert to [0, 1] similarity.
        similarity = 1.0 - (score / 2.0)
        chunks.append({"text": text, "source": source, "similarity": similarity})

    return chunks
```

---

## Step 5: Delete Documents

When source documents are deleted or fully replaced:

```python
def delete_document_chunks(client, doc_id):
    """Remove all chunks for a document. Index removes them automatically."""
    cursor = "0"
    prefix = f"doc:{doc_id}:"
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=100)
        if keys:
            client.delete(*keys)
        if cursor == 0:
            break
```

For bulk refresh: delete existing chunks, then re-ingest the updated document.

---

## Cross-References

- Embedding providers and utility setup: see `embedding-providers.md`
- Platform constraints, FT.SEARCH encoding, HNSW tuning: see `elasticache-search.md`
- Framework integration (LangChain, Strands): see `framework-guide.md`
