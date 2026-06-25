# Search capability — entry point and methods guide

This file is the **entry point** for the `search` capability. It covers vector / semantic / hybrid / sparse / dense / RAG retrieval on Amazon OpenSearch Service or Serverless. Supports Bedrock connectors (Titan, Cohere), self-hosted embedding models, FAISS HNSW vs Lucene, ELSER alternatives, and hybrid scoring.

## When to use this capability

`SKILL.md` routes here when the user is asking about **search retrieval setup or design**. Concrete triggers:

- Phrases: *"semantic search"*, *"hybrid search"*, *"vector index"*, *"k-NN"*, *"build a RAG app"*, *"Bedrock embeddings"*, *"sparse vectors"*, *"dense vectors"*, *"ELSER"*, *"neural search"*, *"FAISS or Lucene"*
- Tasks: pick an embedding model, set up a Bedrock connector, configure a vector index, design hybrid scoring, evaluate retrieval quality, troubleshoot relevance

## All search files (capability index)

After loading this entry, you can discover every search-capability file from this list.

| User need | File |
|---|---|
| End-to-end semantic search setup | this file |
| Bedrock embedding connector | [`search-bedrock-connectors.md`](search-bedrock-connectors.md) |
| Pick a dense embedding model | [`search-dense-vector-models.md`](search-dense-vector-models.md) |
| Pick a sparse embedding model (ELSER alt.) | [`search-sparse-vector-models.md`](search-sparse-vector-models.md) |
| Configure index for vector / hybrid | [`search-index-config.md`](search-index-config.md) |
| Process / chunk documents for retrieval | [`search-document-processing-guide.md`](search-document-processing-guide.md) |
| Evaluate search quality | [`search-evaluation-guide.md`](search-evaluation-guide.md) |
| Query DSL recipes (BM25, multi_match, function_score) | [`search-recipes.md`](search-recipes.md) |
| Troubleshoot search issues | [`search-troubleshooting.md`](search-troubleshooting.md) |

Cross-cutting refs you may also load: [`vector-knn.md`](vector-knn.md) (vector sizing math, k-NN engines), [`sizing.md`](sizing.md), [`security.md`](security.md).

## Vector / k-NN target shape

- **Serverless NextGen Vector Search collections** use a simplified API — no `engine`/`mode` selection (system auto-picks); supports custom document IDs and 32x compression by default.
- **Serverless Classic Vector Search collections** require explicit `engine: faiss`; Lucene/IVF/PQ are NOT supported on Classic Serverless.
- **Managed Domain** supports all engines: Lucene, FAISS HNSW, FAISS IVF, FAISS PQ.
- NMSLIB is removed in OS 3.x. For the engine-by-engine breakdown, see [vector-knn.md](vector-knn.md).

## Sizing-related universal rules (apply when this capability sizes a vector index)

- **Current-generation instances.** Default to Graviton (`r7g`/`r8g` for memory-optimized; `m7g`/`m8g` for cluster managers). `r6g`/`r6gd` only with explicit justification.
- **Input honesty.** When sizing on UNKNOWN inputs, lead with `[BLOCKER — need input]` OR present 2–3 tiered bands. Never present a single point estimate built on invented numbers.

## Cross-capability handoff

- For **provisioning the underlying domain or collection**: see [`provisioning-reference.md`](provisioning-reference.md).
- For **migrating an existing search workload** into AOS: see [`assessment-workflow.md`](assessment-workflow.md).
- For **post-deploy log analytics on the same domain**: see [`log-analytics-guide.md`](log-analytics-guide.md).
- For **embedding model selection beyond Bedrock**: see [`search-dense-vector-models.md`](search-dense-vector-models.md) and [`search-sparse-vector-models.md`](search-sparse-vector-models.md).

---

## 1. BM25 (Lexical Search)

### 1.1 Overview

BM25 is the default ranking algorithm in OpenSearch. It calculates relevance based on term frequency (TF), inverse document frequency (IDF), and document length normalization.

### 1.2 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Exact Match Precision | 5/5 | Excellent for exact keyword queries |
| Semantic Understanding | 2/5 | Cannot understand synonyms or paraphrases |
| Out-of-vocabulary Handling | 1/5 | Fails completely on unseen terms |
| Domain-specific Terms | 5/5 | Excellent for technical/domain vocabulary |

**Strengths:**

- Perfect for exact keyword matching
- Handles rare/domain-specific terminology well
- No vocabulary mismatch between query and index

**Weaknesses:**

- Cannot understand semantic meaning
- Fails on synonyms (e.g., "car" vs "automobile")
- Language-dependent (requires language-specific analyzers)

### 1.3 Cost Profile

| Resource | Cost Level | Details |
|----------|------------|---------|
| Storage | 1/5 (Low) | Only inverted index, typically 10-30% of raw text size |
| Memory | 1/5 (Low) | Field data cache only when needed |
| CPU (Indexing) | 1/5 (Low) | Simple tokenization and analysis |
| CPU (Query) | 1/5 (Low) | Efficient inverted index lookup |

**Storage Estimation:**

```
Index Size ≈ Raw Text Size × 0.1 to 0.3
Example: 1GB text → 100-300MB index
```

**Scaling Behavior:**

- Cost&Latency grows sub-linearly with data size
- Horizontal scaling is straightforward
- Query complexity significantly affects latency

### 1.5 Unique Features & Query Types

BM25 supports several special query types that vector search cannot:

| Query Type | Description | Use Case |
|------------|-------------|----------|
| `prefix` | Matches terms starting with specified prefix | Autocomplete, partial matching |
| `wildcard` | Pattern matching with * and ? | Flexible string matching |
| `regexp` | Regular expression matching | Complex pattern matching |
| `fuzzy` | Tolerates spelling mistakes | Typo tolerance |
| `ngram` | Matches character n-grams | Partial word matching |
| `phrase` | Matches exact phrase in order | Exact phrase search |
| `span` | Positional queries | Near queries, ordered matching |
| `term` | Exact term matching (no analysis) | Exact value matching |

### 1.6 Language Support

| Feature | Support Level | Notes |
|---------|---------------|-------|
| English | 5/5 | Excellent with standard analyzer |
| Other Languages | 4/5 | Requires language-specific analyzers |
| Cross-lingual | 0/5 | Not supported natively |
| CJK Languages | 3/5 | Requires specialized tokenizers (kuromoji, ik, etc.) |

### 1.7 When to Use BM25

**Recommended:**

- Exact keyword/phrase search requirements
- Autocomplete and typeahead features
- Domain-specific terminology search
- Regex or wildcard pattern matching
- Maximum cost efficiency required
- Low-latency requirements at any scale

**Not Recommended:**

- Semantic similarity search
- Cross-lingual search
- Synonym handling without manual configuration
- User queries differ significantly from document terminology

---

## 2. Dense Vector Search

### 2.1 Overview

Dense vector search uses neural network embeddings to represent text as dense floating-point vectors (typically 384-1536 dimensions). Similarity is computed using cosine similarity, dot product, or L2 distance.

### 2.2 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Semantic Understanding | 5/5 | Captures meaning beyond keywords |
| Synonym Handling | 5/5 | Automatically handles synonyms |
| Cross-lingual | 5/5 | With multilingual models |
| Exact Match | 1/5 | Does not support exact keyword matches |
| Domain-specific | 3/5 | If your domain distribution differs greatly from general corpus, fine-tuning is required for good results |

**Strengths:**

- Understands semantic meaning
- Handles paraphrases and synonyms naturally
- Supports cross-lingual search with multilingual models
- Zero-shot transfer to new domains

**Weaknesses:**

- May miss exact keyword matches
- Requires embedding model
- Higher computational cost
- Quality depends heavily on embedding model choice

### 2.3 Index Algorithms (Core Structure)

#### 2.3.1 HNSW (Hierarchical Navigable Small World)

**Overview:** Graph-based approximate nearest neighbor (ANN) algorithm. Default and most popular choice.

| Aspect | Details |
|--------|---------|
| **Accuracy** | 95-99%+ recall achievable with proper tuning |
| **Build Time** | Moderate to slow |
| **Query Latency** | Fast (1-50ms typically) |
| **Memory Requirement** | High - entire graph in memory (unless using quantization) |
| **Scalability** | Good, but memory-bound |

**Memory Estimation (Raw):**

```
Memory = num_vectors × (dimensions × 4 bytes + m × 8 bytes + overhead)
Example: 10M vectors × 768 dims, m=16
Memory ≈ 10M × (768 × 4 + 16 × 8) ≈ 32GB
```

**Best For:**

- Small to medium datasets that fit in memory
- Low-latency requirements
- High accuracy requirements

#### 2.3.2 IVF (Inverted File Index)

**Overview:** Clustering-based approach that partitions vectors into clusters (buckets).

| Aspect | Details |
|--------|---------|
| **Accuracy** | 85-95% recall typical |
| **Build Time** | Slow (requires training) |
| **Query Latency** | Medium (5-100ms) |
| **Memory Requirement** | Lower than HNSW (especially with PQ) |
| **Scalability** | Better for large datasets |

**Best For:**

- Larger datasets where memory is constrained
- Can tolerate slightly lower accuracy
- Batch search workloads

#### 2.3.3 Disk-based Vector Search (mode: on_disk)

**Overview:** OpenSearch's solution for billion-scale vector search with limited memory (requires OpenSearch 2.17+). Uses **Binary Quantization (BQ)** to keep a compressed index in memory while storing full-precision vectors on disk.

| Aspect | Details |
|--------|---------|
| **Accuracy** | Good recall (uses re-ranking from disk) |
| **Build Time** | Fast (BQ training is automatic) |
| **Query Latency** | Medium (10-100ms), depends on SSD speed |
| **Memory Requirement** | Very Low (uses 1-bit BQ compressed vectors in RAM) |
| **Scalability** | Excellent for billion-scale datasets |

**Memory Estimation:**

```
Memory = num_vectors × dimensions / 8 (bits to bytes) + HNSW graph overhead
Example: 1B vectors × 768 dims (using BQ)
Memory ≈ 1B × 96 bytes ≈ 96 GB (manageable on a cluster)
vs. ~3TB for float32 vectors
```

**Best For:**

- Billion-scale datasets
- Cost-efficiency (trading RAM for SSD)
- High-throughput scenarios where RAM is the bottleneck

### 2.4 Compression & Quantization

#### 2.4.1 Product Quantization (PQ)

Compression technique that breaks vectors into sub-vectors and encodes them.

| Aspect | Details |
|--------|---------|
| **Accuracy** | 80-90% recall (lossy) |
| **Training** | Requires a training step |
| **Memory Reduction** | 10-50x compression |

#### 2.4.2 Binary Quantization (BQ)

Extreme compression using 1-bit representations.

| Aspect | Details |
|--------|---------|
| **Accuracy** | Lower than PQ generally, but faster |
| **Memory Reduction** | 32x compression (float32 -> 1 bit) |
| **Query Latency** | Ultra-fast (Hamming distance) |

### 2.5 Total Latency Composition

```
Total Latency = Embedding Inference Time + Vector Search Time (KNN)
```

1. **Embedding Inference:** 5-200ms depending on deployment (API vs GPU vs CPU)
2. **Vector Search (KNN):** 1-100ms depending on algorithm

**Critical Note:** Often, **inference time dominates** the total latency.

### 2.6 Language Support

| Feature | Support Level | Notes |
|---------|---------------|-------|
| English | 5/5 | Excellent with most models |
| Multilingual | 5/5 | With multilingual models (mE5, multilingual-e5, etc.) |
| Cross-lingual | 5/5 | Query in one language, retrieve in another |
| Low-resource Languages | 3/5 | Depends on model training data |

### 2.7 When to Use Dense Vector

**Recommended:**

- Semantic similarity search
- Cross-lingual search requirements
- Synonym and paraphrase handling needed
- Natural language queries from users
- Question-answering systems
- RAG (Retrieval Augmented Generation) applications

**Not Recommended:**

- Exact keyword matching is critical
- Highly specialized domain vocabulary not covered by model
- Extremely cost-sensitive deployments
- Real-time autocomplete/typeahead
- Sub-millisecond latency requirements

---

## 3. Sparse Vector Search

### 3.1 Overview

Sparse vector search uses learned sparse representations where most dimensions are zero. Unlike dense vectors with 384-1536 dimensions all populated, sparse vectors may have 30,000+ dimensions but only 100-500 non-zero values.

### 3.2 How Neural Sparse Works

Uses neural networks to learn sparse representations with semantic meaning:

1. Documents and queries are encoded into sparse vectors
2. Each dimension corresponds to a vocabulary token
3. Weights indicate semantic importance (not just term frequency)

**Advantages over BM25:**

- Learns semantic term expansion (e.g., "dog" activates "puppy", "canine")
- Trained on relevance signals
- Better zero-shot domain transfer

### 3.3 Search Modes: Doc-only (Recommended) vs Bi-encoder

#### 3.3.1 Doc-only Mode (Recommended)

- **Ingestion**: Documents encoded using a specialized doc-only model
- **Search**: Query processed using a simple **tokenizer** (not full model inference)

**Why recommended:** Zero query inference, low latency (10x+ faster), lower cost.

#### 3.3.2 Bi-encoder Mode

- Both documents and queries processed by the same deep neural network
- Higher relevance but higher latency

### 3.4 Index Backends

#### 3.4.1 rank_features Field (Inverted Index Based)

- Exact search (no approximation)
- Best for smaller datasets (< 50M documents)

#### 3.4.2 SEISMIC (ANN-based Sparse Search)

- Approximate nearest neighbor for sparse vectors
- Best for large-scale datasets (> 10M documents) with latency sensitivity

### 3.5 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Semantic Understanding | 4/5 | Good, but generally slightly below dense |
| Exact Match | 4/5 | Better than dense vectors |
| Term Expansion | 5/5 | Learns relevant term expansion |
| Interpretability | 5/5 | Can see which terms matched |

### 3.6 When to Use Sparse Vector

**Recommended:**

- Balance between lexical and semantic search
- Users want semantic search without query-time model inference
- Extreme fast semantic search (doc-only + SEISMIC)
- Interpretability is important
- Lower memory budget than dense vectors

**Not Recommended:**

- Cross-lingual search
- Maximum semantic understanding needed

---

## 4. Hybrid Search

### 4.1 Overview

Hybrid search combines multiple retrieval methods (BM25, dense vector, sparse vector) to leverage the strengths of each. OpenSearch supports hybrid search through the hybrid query type and score normalization.

### 4.2 Score Normalization
OpenSearch provides several normalization techniques (Min-Max, L2, Harmonic Mean, etc.) to ensure scores are comparable before combination.

### 4.3 Combination Strategy for Relevance

- **Hybrid Scope Rule**: Use at most **two retrieval methods** per hybrid query.

- **Recommended Combinations**:
  - **Dense + Sparse**: Best search relevance. Two layers of semantic understanding.
  - **Dense + BM25**: Robust baseline combining semantic understanding with exact keyword precision.

- **Not Recommended**:
  - **Sparse + BM25**: Generally redundant. Sparse vectors already capture keyword information.

### 4.4 When to Use Hybrid Search

**Recommended:**

- **Maximum Relevance**: When accuracy and recall are the top priorities.
- Mixed query types (some exact, some semantic).
- Unknown query distribution.
- Can afford additional infrastructure cost.

**Not Recommended:**

- Strict cost constraints
- Simple use cases where one method suffices
- Sub-10ms latency requirements
- Development/prototype phase (start simple)

---
