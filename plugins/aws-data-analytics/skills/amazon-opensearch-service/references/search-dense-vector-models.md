# Dense Vector Models Guide

This document lists model options for Dense Vector Search in OpenSearch, categorized by deployment mode, with practical recommendations.

> Key takeaways:
>
> - **OpenSearch node (CPU) pretrained models tend to be older baselines**: convenient for quick starts, but **not SOTA** for retrieval quality.
> - **Default recommendation for most users: Amazon Titan Embeddings (via Amazon Bedrock)** for strong quality + managed ops.
> - **External Embedding API Services**: OpenSearch can work with **any embedding service** via ML Commons Connectors; the list below is just common examples.

---

## 1. OpenSearch Node Deployment (CPU)

Deploy models directly on OpenSearch nodes using CPU inference.

### When to use

- Dev / POC / low QPS workloads
- Environments where you cannot run GPU endpoints
- You prioritize simplicity over best retrieval quality

### Caveat

- The pretrained models available on OpenSearch nodes are generally **older** and may not match the quality of newer retrieval-optimized models (e.g., E5/BGE or vendor-managed models like Titan).

### 1.1 Supported Pre-trained Models (examples)

OpenSearch provides a repository of pre-trained models that can be registered directly.

| Model Name | Dimensions | Description | Size | Latency (Approx) |
|------------|------------|-------------|------|------------------|
| `huggingface/sentence-transformers/all-MiniLM-L6-v2` | 384 | Good speed/quality tradeoff for English. | 22M | Low (5–15ms) |
| `huggingface/sentence-transformers/all-mpnet-base-v2` | 768 | Often higher quality than MiniLM, slower. | 110M | Medium (20–50ms) |
| `huggingface/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | Multilingual baseline for many languages. | 120M | Medium (10–30ms) |
| `huggingface/sentence-transformers/multi-qa-MiniLM-L6-cos-v1` | 384 | Tuned for QA-style semantic search. | 22M | Low (5–15ms) |

### 1.2 Custom Models

**Not Supported.** Custom or fine-tuned dense embedding models cannot be deployed on OpenSearch Nodes. You must use a SageMaker GPU Endpoint.

---

## 2. SageMaker GPU Endpoint (Recommended for Custom / High-QPS)

Deploy models on AWS SageMaker with GPU acceleration for high throughput and low latency. This is the recommended approach for:

- High QPS / large batch ingestion
- Larger or retrieval-optimized models (E5/BGE family, etc.)
- Custom/fine-tuned models and custom inference logic

### 2.1 Recommended Models (examples)

Any model compatible with Hugging Face Text Embeddings Inference (TEI) or a custom SageMaker inference script can be used.

| Model Name | Dimensions | Description | Recommended Instance |
|------------|------------|-------------|---------------------|
| `intfloat/e5-base-v2` | 768 | Strong retrieval performance; widely used. | `ml.g5.xlarge` |
| `intfloat/multilingual-e5-base` | 768 | Strong multilingual retrieval. | `ml.g5.xlarge` |
| `BAAI/bge-base-en-v1.5` | 768 | High-quality English retrieval. | `ml.g5.xlarge` |
| `BAAI/bge-m3` | 1024 | Multilingual + multi-granularity; heavier. | `ml.g5.xlarge` |

### 2.2 Custom Models

If you have a **custom** or **fine-tuned dense embedding model**, deploy it using a SageMaker GPU Endpoint. This mode supports custom model weights and custom inference logic that you control.

---

## 3. External Embedding API Services (Managed Providers)

Use managed API services to generate embeddings. OpenSearch connects via the **ML Commons Connector**.

**Important:** OpenSearch can integrate with **any embedding provider/service** as long as:

- You can call an HTTP endpoint from OpenSearch (or from the connector runtime),
- The service returns a numeric embedding vector,
- You can configure authentication and request/response transformation.

So the providers below are **examples of common choices**, not an exhaustive list.

### 3.1 Common Providers (Examples)

| Provider | Model Names (Examples) | Dimensions (Typical) | Notes |
|----------|-------------------------|----------------------|------|
| **Amazon Bedrock** *(Default recommendation)* | `amazon.titan-embed-text-v2`, `cohere.embed-english-v3`, `cohere.embed-multilingual-v3` | 1024, 1024, 1024 | Fully managed, integrated with AWS IAM. Titan v2 supports variable dimensions. |
| **OpenAI** | `text-embedding-3-small`, `text-embedding-3-large`, `text-embedding-ada-002` | 1536, 3072, 1536 | Widely adopted; requires API key. |
| **Cohere** | `embed-english-v3.0`, `embed-multilingual-v3.0` | 1024 | Strong retrieval-focused embeddings. |

### Why default recommend Amazon Titan

- Strong general-purpose embedding quality
- Fully managed + straightforward operations on AWS
- IAM-based auth and Bedrock integration reduces operational overhead

---

## Summary of Trade-offs

| Deployment Mode | Latency | Cost | Maintenance | Scalability | Best For |
|-----------------|---------|------|-------------|-------------|----------|
| **OpenSearch node (CPU)** | Medium/High | Low (shared) | Medium | Limited by cluster | Dev/POC, low QPS, simple setups |
| **SageMaker (GPU)** | Low | High (dedicated) | Low/Medium | High | Production ingestion + high QPS + custom models |
| **External API** | Medium/High (network) | Usage-based | Very Low | High | Fast rollout, managed quality, minimal ops |

---

## Practical Tips (Common Gotchas)

- **Dimensions must match** your index mapping (`knn_vector` dimension).
- If your model recommends **normalization** (common for cosine similarity), apply it consistently at ingestion and query time.
- For E5/BGE-style retrieval models, follow their recommended query/document formatting (e.g., prefixes) for best results.
