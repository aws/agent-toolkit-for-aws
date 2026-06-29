# Sparse Vector Models Guide

This document lists the available models for Sparse Vector (Neural Sparse) Search in OpenSearch, categorized by deployment mode.

## 1. OpenSearch Node Deployment (CPU)

Deploying sparse models directly on OpenSearch Nodes.

**Note:** Running sparse encoding models on CPU OpenSearch Nodes is generally **not recommended** for high-throughput production due to latency. CPU OpenSearch Nodes are best suited for **tokenizers** in Doc-only mode search, or **low-traffic/dev** sparse encoding inference.

### 1.1 Supported Pre-trained Models

#### Tokenizers (recommended on CPU for Doc-only query time)

| Model Name | Type | Description | Recommended Use |
|------------|------|-------------|-----------------|
| `amazon/neural-sparse/opensearch-neural-sparse-tokenizer-v1` | Tokenizer | Neural sparse tokenizer with IDF-based token weights (defaults to 1 if IDF not provided). | **Search Phase** (Doc-only mode) |
| `amazon/neural-sparse/opensearch-neural-sparse-tokenizer-multilingual-v1` | Tokenizer | Multilingual neural sparse tokenizer with IDF-based token weights (defaults to 1 if IDF not provided). | **Search Phase** (Multilingual Doc-only mode) |

#### Sparse encoding models (CPU = dev/low traffic)

| Model Name | Type | Description | Recommended Use |
|------------|------|-------------|-----------------|
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-v1` | Sparse Encoder | Neural sparse encoding model (bi-encoder style). | Dev / Low traffic |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-v2-distill` | Sparse Encoder | Distilled v2 sparse encoding model. | Dev / Low traffic (or GPU for prod bi-encoder) |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v1` | Doc Encoder | Document-side sparse encoder for doc-only setups. | Dev / Low traffic |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v2-distill` | Doc Encoder | Distilled doc encoder v2. | Dev / Low traffic |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v2-mini` | Doc Encoder | Smaller "mini" doc encoder v2. | Dev / Low traffic / cost-sensitive experiments |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-distill` | Doc Encoder | v3 distilled doc encoder. | Dev / Low traffic (or GPU for prod doc-only) |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-gte` | Doc Encoder | v3 GTE-based doc encoder. | Dev / Low traffic (or GPU for prod doc-only) |
| `amazon/neural-sparse/opensearch-neural-sparse-encoding-multilingual-v1` | Sparse Encoder | Multilingual neural sparse encoding model. | Dev / Low traffic (or GPU for prod multilingual) |

### 1.2 Custom Models

**Not Supported.** Custom or fine-tuned sparse encoding models cannot be deployed on OpenSearch Nodes. You must use a SageMaker GPU Endpoint.

---

## 2. SageMaker GPU Endpoint (Recommended for Production)

Deploying sparse models on AWS SageMaker with GPU acceleration is the recommended strategy for:

- **Ingestion-time doc encoding** (Doc-only mode), and/or
- **Query-time encoding** (Bi-encoder mode).

### 2.1 Recommended Models

The models listed in 1.1.
For tokenizers, it's recommended to get deployed on OpenSearch nodes.
For deep learning models, the recommended instance type is ml.g4dn.xlarge or ml.g5.xlarge.

### 2.2 Custom Models

If you have trained a **custom** or **fine-tuned** sparse encoding model, you **must** deploy it using a SageMaker GPU Endpoint. This deployment mode supports custom model logic and weights that are not available in the pre-trained registry.

---

## 3. Configuration Combinations

### 3.1 Doc-Only Mode (Recommended for Speed/Cost)

In this mode, you decouple ingestion and search compute.

- **Ingestion (Heavy):** Run on **SageMaker GPU**
  - Model (Recommended): `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-gte`
  - Alternatives: `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-distill`
  - Newer models have better accuracy.
- **Search (Light):** Run on **OpenSearch Node (CPU)**
  - Model: `amazon/neural-sparse/opensearch-neural-sparse-tokenizer-v1`
  - Why: Search only requires tokenization, which is extremely fast on CPU.

### 3.2 Bi-Encoder Mode (Maximum Accuracy)

In this mode, query processing is heavy and requires inference.

- **Ingestion:** Run on **SageMaker GPU**
  - Model: `amazon/neural-sparse/opensearch-neural-sparse-encoding-v2-distill`
- **Search:** Run on **SageMaker GPU**
  - Model: `amazon/neural-sparse/opensearch-neural-sparse-encoding-v2-distill`
  - Why: Query time inference is too slow on CPU for most interactive applications.

### 3.3 Multilingual Doc-Only Mode

- **Ingestion (Heavy):** Run on **SageMaker GPU**
  - Model: `amazon/neural-sparse/opensearch-neural-sparse-encoding-multilingual-v1`
- **Search (Light):** Run on **OpenSearch Node (CPU)**
  - Model: `amazon/neural-sparse/opensearch-neural-sparse-tokenizer-multilingual-v1`
  - Why: Search only requires tokenization, which is extremely fast on CPU.
