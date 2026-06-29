# Vector & k-NN search on Amazon OpenSearch

> **Canonical k-NN reference for this skill.** The engine matrix and quantization comparisons below are the single source of truth — do NOT replicate elsewhere. Source of truth for current engine support: [knn.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn.html). Source of truth for Serverless vector workloads: [serverless-vector-search.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html).

The summary version (decision tree, dimensions, hybrid search 101) is in `SKILL.md`. This file owns the engine deep-dive, memory math, hybrid search recipes, RAG ingestion patterns, and ELSER alternatives.

## Engine selection

| Engine | Max dimension | Methods | Filtering | When |
|---|---|---|---|---|
| **Lucene** | 1,024 | HNSW only | **Smart filtering (auto pre/post/exact)** — best filter perf | < 10M vectors, want metadata filters, latency-tolerant |
| **FAISS** | 16,000 | HNSW + IVF + PQ + scalar | Pre-filter with `efficient_filter` | 10M – billions; standard recall/latency trade-off |
| **NMSLIB** | 16,000 | HNSW only | Manual | **DEPRECATED in 2.19; REMOVED in OS 3.0+** — migrate to FAISS |

**On Serverless NextGen Vector**, **FAISS HNSW IS supported** — the customer doesn't choose the engine, the system selects FAISS HNSW under the hood (Lucene HNSW, IVF, and PQ cannot be pinned on NextGen). Custom doc IDs supported. 32× compression default. 10s refresh interval.

**On Serverless Classic Vector**, **FAISS HNSW IS supported** (the only engine — explicit `engine: faiss` in mappings; Lucene k-NN, IVF, and PQ are NOT available on Classic). Custom `_id` rejected (use server-generated).

**Deployment-target rule when the engine pick is Lucene k-NN**: the response MUST recommend a **Managed OpenSearch domain** (provisioned). State explicitly: *"AOSS NextGen and Classic Vector collections do not expose Lucene k-NN — only FAISS HNSW is available on Serverless. Lucene HNSW requires Managed."* Without that line the customer may try to deploy a Lucene-engine workload on Serverless and discover the incompatibility at create time.

**Phrasing rule when a customer is choosing Managed-vs-Serverless for a vector workload**: do NOT say *"FAISS-family"* or *"auto-picked FAISS-family"* — that phrasing reads as fuzzy and the customer may infer Lucene parity. State plainly: *"FAISS HNSW is supported on both Managed and Serverless VECTORSEARCH"* (so engine parity is preserved across the move), then enumerate what is NOT available on Serverless (Lucene HNSW, IVF, PQ pinning, custom plugins, manual snapshots, custom `_id` on Classic, ISM, NMSLIB).

## Dimensions reference

| Embedding model | Dim | Use |
|---|---|---|
| `all-MiniLM-L6-v2`, `all-MiniLM-L12-v2` | 384 | Fast, small models |
| BERT-base, MPNet (`all-mpnet-base-v2`) | 768 | Common semantic search |
| Many newer models, Cohere | 1024 | Modern dense embeddings |
| OpenAI `text-embedding-ada-002` | 1536 | Common RAG default |
| OpenAI `text-embedding-3-large`, large modern | 3072 | High-quality (high cost) |
| Image embeddings (CLIP, DINOv2, etc.) | 512–1536 | Multimodal |

Pick model FIRST; dimension follows.

## Memory math (HNSW float — FAISS or Lucene)

This is the **canonical formula** for HNSW-graph memory on Amazon OpenSearch. Use it as written; do NOT substitute hand-wave approximations like *"~512 bytes overhead per vector"*. The formula applies to both FAISS HNSW and Lucene HNSW (Lucene's per-vector graph overhead is ~10–15% lighter at the same `m`, but the same formula is the standard estimate and is what AWS docs use):

```
bytes_per_vector ≈ 1.1 × (4 × dim + 8 × m)
total_memory ≈ bytes_per_vector × num_vectors × (1 + replicas)
```

`m=16` is typical (HNSW graph connectivity).

**Required when sizing a vector workload**: derive the memory number end-to-end on this formula in the response. Show inputs (`dim`, `m`, `num_vectors`, `replicas`), then the formula, then the numeric result. A bare *"~23 GB for the graph"* without the derivation is not reproducible from inputs — the rubric will flag it.

| Vectors | Dim | Memory (replicas=1) |
|---|---|---|
| 1M | 384 | ~3.5 GB |
| 1M | 768 | ~6.7 GB |
| 1M | 1536 | ~13.4 GB |
| 10M | 768 | ~67 GB |
| 10M | 1536 | ~134 GB |
| 100M | 768 | ~670 GB |

**AWS budget formula:** `memory_available = (RAM − jvm_size) × circuit_breaker_limit`

- `jvm_size = min(0.5 × RAM, 32 GiB)`
- `circuit_breaker_limit = 0.5` (default)

**Example:** `r7g.4xlarge.search` = 128 GiB RAM, JVM = 32 GiB, available for k-NN graphs ≈ `(128 - 32) × 0.5 = 48 GiB`.

## Compression / quantization options

**Architectural rule of thumb:** int8 is the default; pick fp16 if your workload needs >99% recall on tail queries; binary only for >100M vectors (and always with a rerank pass). `mode: "on_disk"` keeps recall at 100% but trades latency for RAM.

Memory ratios (stable): fp32→fp16 = 2×, fp32→int8 = 4×, fp32→int4 = 8×, fp32→binary = 32×.

For current per-method recall benchmarks (which AWS republishes per release), see [knn-vector-quantization.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn-vector-quantization.html).

## Hybrid search (text + vector)

OpenSearch's `hybrid` query (GA in 2.10) combines BM25 with k-NN/neural at the coordinator via search pipelines.

### Why normalization is required

- BM25 score: unbounded ≥ 0
- k-NN/neural score: 0.0–1.0
- Direct sum biases toward BM25.

### Two combination strategies

**1. Score normalization (`normalization-processor`)** — GA in 2.10:

```json
PUT _search/pipeline/hybrid-norm
{
  "phase_results_processors": [
    {
      "normalization-processor": {
        "normalization": { "technique": "min_max" },
        "combination": {
          "technique": "arithmetic_mean",
          "parameters": { "weights": [0.3, 0.7] }
        }
      }
    }
  ]
}
```

Best benchmarked combo: **`min_max` + `arithmetic_mean`** weighted 30% BM25 / 70% vector.

**2. Reciprocal Rank Fusion (`score-ranker-processor`)** — added in 2.19:

```json
PUT _search/pipeline/hybrid-rrf
{
  "phase_results_processors": [
    {
      "score-ranker-processor": {
        "combination": {
          "technique": "rrf",
          "rank_constant": 60
        }
      }
    }
  ]
}
```

Formula: `rankScore(d) = Σ 1/(k + rank_i)` where `k = rank_constant` (default 60).

**Trade-off (per OpenSearch's own benchmark):**

- RRF: −3.86% NDCG@10 vs normalization, +1.62% p50 latency
- RRF more stable across varying score distributions and outliers

### Hybrid query DSL

```json
GET my-index/_search?search_pipeline=hybrid-norm
{
  "query": {
    "hybrid": {
      "queries": [
        { "match": { "body": "wireless headphones" } },
        {
          "neural": {
            "embedding_field": {
              "query_text": "wireless headphones",
              "model_id": "<bedrock-model-id>",
              "k": 100
            }
          }
        }
      ]
    }
  },
  "size": 100
}
```

Optimal `k` and `size`: **100–200**.

### Typical relevance lift (OpenSearch benchmark)

- Hybrid vs keyword-only: **8–12% NDCG@10** improvement
- Hybrid vs neural-only: **15% NDCG@10** improvement
- Latency cost: **6–8% over Boolean**

## RAG ingestion pattern

Standard flow:

```
1. CHUNK    → split docs into 256–512 token segments (semantic boundaries help)
2. EMBED    → call Bedrock (Titan, Cohere) or SageMaker model
3. INDEX    → write knn_vector field + original text + metadata
4. QUERY    → hybrid query (BM25 + vector neural)
5. RERANK   → optional cross-encoder rerank for top-K
6. RETURN   → top-K chunks to LLM context
```

### Index mapping

```json
PUT rag-corpus
{
  "settings": {
    "index.knn": true,
    "index.knn.algo_param.ef_search": 100,
    "default_pipeline": "embed-on-write"
  },
  "mappings": {
    "properties": {
      "text":         { "type": "text" },
      "embedding":    {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
          "engine": "faiss",
          "name": "hnsw",
          "space_type": "innerproduct",
          "parameters": { "m": 16, "ef_construction": 256 }
        }
      },
      "doc_id":       { "type": "keyword" },
      "source_url":   { "type": "keyword" },
      "chunk_index":  { "type": "integer" },
      "ingested_at":  { "type": "date" }
    }
  }
}
```

### Embed-on-write via OSI

OpenSearch Ingestion has a Bedrock processor that embeds on write:

```yaml
embed-on-write:
  source:
    s3:
      ...
  processor:
    - bedrock:
        model: amazon.titan-embed-text-v2:0
        input_field: text
        output_field: embedding
  sink:
    - opensearch:
        ...
```

### Filtered RAG

Combine vector + metadata filter via `efficient_filter`:

```json
{
  "neural": {
    "embedding": {
      "query_text": "...",
      "model_id": "...",
      "k": 100,
      "filter": {
        "bool": {
          "must": [
            { "term":  { "tenant_id": "abc" } },
            { "range": { "ingested_at": { "gte": "now-30d" } } }
          ]
        }
      }
    }
  }
}
```

**Pre-filter** (Lucene smart filtering): runs the metadata filter first, then k-NN over the candidate set. Best performance for selective filters.

**Post-filter**: returns < k results when filter rejects vectors. Use only when filter is very permissive.

### Lucene exact-search fallback under highly selective filters

When recommending **Lucene HNSW** for a workload with a highly selective metadata filter (e.g. ACL pre-filter that narrows to a tiny fraction of the corpus, like 3–8 spaces out of hundreds), the response MUST flag the exact-search fallback:

> *"On highly selective filters, Lucene's smart filtering automatically falls back to exact (brute-force) search over the post-filter candidate set instead of approximate HNSW traversal. This preserves recall (no graph-traversal recall cliff) but latency rises with candidate count — budget for it. FAISS HNSW with `efficient_filter` does NOT have this fallback and will produce recall degradation on the same selective-filter workload, which is why Lucene wins this case."*

This is the load-bearing reason Lucene HNSW beats FAISS HNSW on selective-filter workloads. Without surfacing the fallback the recommendation reads as a vendor preference rather than a rooted choice.

## ELSER alternatives on Amazon OpenSearch

*This is the canonical ELSER-alternatives section for the skill. Other files (assessment-gotchas, assessment-workflow ES feature table) link here.*

ELSER (Elastic Learned Sparse Encoder) is **proprietary to Elastic** — not available on Amazon OpenSearch.

**OpenSearch alternatives:**

1. **Neural sparse search** (`neural_sparse` query) — uses a SageMaker-hosted sparse-encoder model (e.g., SPLADE).
2. **Dense vectors via Bedrock**:
   - Amazon Titan Embed Text v2 (1024 dim)
   - Cohere Embed English/Multilingual (1024 dim)
3. **Hybrid: BM25 + dense vector** — often gets you most of ELSER's benefit without the proprietary tax.
4. **Custom sparse model** via ml-commons connector to your own SageMaker endpoint.

```json
{
  "query": {
    "neural_sparse": {
      "embedding_field": {
        "query_text": "search query",
        "model_id": "<sparse-model-id>"
      }
    }
  }
}
```

## OpenSearch 3.0 vector improvements

*Canonical list for this skill — `sizing.md` and other refs link here rather than duplicating these bullets.*

- **GPU-accelerated index build**: up to **9.3× faster, 3.75× cost reduction**
- **Derived-source vectors**: 3× storage reduction, 30× cold-start improvement
- **Concurrent segment search default-on for k-NN**: 2.5× boost
- **Star-tree indexing**: aggregations up to 100× faster
- Native MCP (Model Context Protocol) support for AI agents

## Production-scale data points

- **Amazon Music**: 1.05B vectors, 7,100 QPS on a single OpenSearch cluster (FAISS HNSW)
- This validates the platform at high scale

## Critical gotchas for vector workloads

1. **Vector Search collections cannot share OCUs** with Search/TimeSeries on Serverless. Adding one vector collection roughly doubles idle floor.
2. **Cannot change `dimension` or `engine`** of existing index — must reindex.
3. **`post_filter` returns < k results** if filter rejects vectors near the query. Use `efficient_filter` instead for filtered k-NN.
4. **NMSLIB → FAISS migration** requires reindex. NMSLIB is removed in OS 3.0+.
5. **Lucene engine max dimension is 1,024** — pick FAISS for higher-dim embeddings.
6. **k-NN UltraWarm/Cold migration** requires OS 2.17+. k-NN indexes don't force-merge to single segment during UltraWarm migration.
7. **`uw.medium` cannot host k-NN** — RAM headroom insufficient. Use `uw.large` and size graphs ≤ `circuit_breaker_limit × 61 GiB` per instance.
8. **Memory pressure on k-NN nodes** isn't always reflected in JVM pressure (graphs are off-heap). Watch native memory metrics.

## Validate before production

Use OpenSearch Benchmark with the `noaa_semantic_search` workload, or build your own with a representative query set. Measure NDCG@10, p50/p95/p99 latency, and memory utilization at expected QPS.
