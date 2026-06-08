# Embedding Provider Chain for GenAI Sub-Skill

Load this reference when the user needs to choose or configure an embedding provider for vector search with ElastiCache (Valkey).

> **Important:** Vector search (FT.CREATE / FT.SEARCH) requires node-based ElastiCache Valkey 8.2 or later (recommend 9.0). It is not available on ElastiCache Serverless. If using serverless, see the application-side comparison approach in `semantic-cache.md`.

## Provider Chain (Decision Order)

**First, check `.elasticache/requirements.json`.** If `infrastructure.embedding_provider`, `infrastructure.embedding_model`, and `infrastructure.embedding_dim` are already set, use those values. Do not re-ask.

**If not set, ask the user:** "Do you have a preferred embedding model or provider?"

* **User names a specific model** (OpenAI, Cohere, Titan, etc.) -> Use that model. Match the DIM in FT.CREATE to its output dimensions.
* **User says Bedrock / AWS** -> Use Bedrock Titan Embed v2 (Option 1 below)
* **User has no preference, or no API access** -> Default to open-source fastembed (Option 3 below). Zero setup, zero cost, works anywhere.

**After selection:**

### A. Persist the choice to `requirements.json`

```json
{
  "infrastructure": {
    "embedding_provider": "bedrock",
    "embedding_model": "amazon.titan-embed-text-v2:0",
    "embedding_dim": 1024,
    "embedding_module": "utils/embeddings.py"
  }
}
```

### B. Generate a reusable embedding utility in the user's project

Create a file (default: `utils/embeddings.py`, or wherever fits the user's project structure) that exports:

* `generate_embedding(text: str) -> list[float]`
* `embedding_to_bytes(embedding: list[float]) -> bytes`
* `VECTOR_DIM: int`

Use the provider-specific code from the Standard Functions section below. This file is generated ONCE. Every subsequent file the model generates imports from it:

```python
from utils.embeddings import generate_embedding, embedding_to_bytes, VECTOR_DIM
```

Save the file path in `requirements.json` as `infrastructure.embedding_module` so the model never regenerates it.

## On Return Visits

If `infrastructure.embedding_module` is set in `requirements.json`, read that file to confirm it exists. If it exists, import from it. Never regenerate. If the file was deleted, regenerate it from the stored provider/model/dim values.

---

## Provider Options

| Provider | Model | Dimensions | Requires API | Best for |
|----------|-------|-----------|-------------|----------|
| Bedrock Titan | amazon.titan-embed-text-v2:0 | 256/512/1024 | Yes (Bedrock) | Production |
| Bedrock Cohere | cohere.embed-english-v3 | 1024 | Yes (Bedrock) | English-only (use cohere.embed-multilingual-v3 for multilingual) |
| fastembed | BAAI/bge-small-en-v1.5 | 384 | No | Prototyping |
| sentence-transformers | all-MiniLM-L6-v2 | 384 | No | Prototyping with more model choice |

### Option 1: Amazon Bedrock Titan Embed Text v2 (Recommended for production)

* **Model ID:** `amazon.titan-embed-text-v2:0`
* **Dimensions:** 256, 512, or 1024 (recommend 1024 for best accuracy; 256 for cost-sensitive workloads)
* **IAM permissions needed:** `bedrock:InvokeModel` on the Titan Embed model ARN

### Option 2: Amazon Bedrock Cohere Embed

* **Model ID:** `cohere.embed-english-v3` or `cohere.embed-multilingual-v3`
* **Dimensions:** 1024
* **IAM permissions needed:** `bedrock:InvokeModel` on the Cohere Embed model ARN
* **Note:** Cohere uses `texts` (list) instead of `inputText` (string), and requires `input_type`. Use `"search_document"` when storing and `"search_query"` when querying.

### Option 3: fastembed (Open-Source, No API Key Needed)

* **Install:** `pip install fastembed`
* **Default model:** `BAAI/bge-small-en-v1.5` (384 dims) or `BAAI/bge-base-en-v1.5` (768 dims)
* **Tradeoff:** Lower accuracy than Titan, but zero cost and zero setup
* **Good for:** Prototyping, development, CI/CD tests, users without AWS accounts

### Option 4: Amazon Bedrock Cohere Embed v4 (Multimodal)

* **Model ID:** `cohere.embed-v4:0`
* **Dimensions:** 256, 512, 1024, or 1536 (default 1536)
* **Context:** Up to 128k tokens
* **Multimodal:** Supports interleaved text + image inputs via `inputs` field
* **IAM permissions needed:** `bedrock:InvokeModel` on the Cohere Embed v4 model ARN
* **Note:** Uses a different request format from v3. See AWS Bedrock docs for the `inputs` field schema.

### Option 5: sentence-transformers (Open-Source, More Model Choices)

* **Install:** `pip install sentence-transformers`
* **Popular model:** `all-MiniLM-L6-v2` (384 dims)
* **Tradeoff:** Wider model selection, but heavier dependency (pulls in PyTorch)

---

## mem0 Embedder Configs

Use these in the `embedder` block of mem0's config dict. See `agent-memory.md` for the full mem0 configuration.

**Bedrock Titan:**

```json
{
  "embedder": {
    "provider": "aws_bedrock",
    "config": {
      "model": "amazon.titan-embed-text-v2:0",
      "aws_region": "us-east-1"
    }
  }
}
```

**Bedrock Cohere:**

```json
{
  "embedder": {
    "provider": "aws_bedrock",
    "config": {
      "model": "cohere.embed-english-v3",
      "aws_region": "us-east-1"
    }
  }
}
```

**fastembed / sentence-transformers:**

```json
{
  "embedder": {
    "provider": "huggingface",
    "config": {
      "model": "BAAI/bge-small-en-v1.5"
    }
  }
}
```

---

## Standard Functions (Utility File Templates)

These are the canonical implementations for the reusable embedding utility file. Use the one matching the user's chosen provider.

**Bedrock Titan:**

```python
import boto3, json, struct

_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
VECTOR_DIM = 1024

def generate_embedding(text: str) -> list[float]:
    response = _bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        # "embeddingTypes" is optional; float is the default. Include only if you need
        # a specific type (e.g., "binary"). Omitting it returns float embeddings.
        body=json.dumps({"inputText": text, "dimensions": VECTOR_DIM}),
    )
    return json.loads(response["body"].read())["embedding"]

def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{VECTOR_DIM}f", *embedding)
```

**Bedrock Cohere:**

```python
import boto3, json, struct

_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
VECTOR_DIM = 1024

def generate_embedding(text: str, query: bool = False) -> list[float]:
    response = _bedrock.invoke_model(
        modelId="cohere.embed-english-v3",
        body=json.dumps({
            "texts": [text],
            "input_type": "search_query" if query else "search_document",
            "truncate": "END",
        }),
    )
    return json.loads(response["body"].read())["embeddings"][0]

def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{VECTOR_DIM}f", *embedding)
```

**Cohere note:** Pass `query=True` when embedding a search query (retrieval), `query=False` (default) when embedding documents for storage. Other providers ignore this parameter.

**fastembed:**

```python
import struct
from fastembed import TextEmbedding

_model = TextEmbedding("BAAI/bge-small-en-v1.5")
VECTOR_DIM = 384

def generate_embedding(text: str) -> list[float]:
    return list(_model.embed([text]))[0].tolist()

def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{VECTOR_DIM}f", *embedding)
```

**sentence-transformers:**

```python
import struct
from sentence_transformers import SentenceTransformer

_model = SentenceTransformer("all-MiniLM-L6-v2")
VECTOR_DIM = 384

def generate_embedding(text: str) -> list[float]:
    return _model.encode(text).tolist()

def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{VECTOR_DIM}f", *embedding)
```

---

## Batch Embedding for Bulk Ingestion

For bulk ingestion (>1K documents), batch embedding calls to avoid per-request overhead. Titan accepts sequential calls (add exponential backoff for throttling). Cohere natively supports batching via `texts: [list]` with up to 96 texts per call.

---

## Dimension Compatibility Warning

The `FT.CREATE` index `DIM` must match your embedding model's output dimension **exactly**. If you change embedding providers, you must:

1. Drop the existing index: `FT.DROPINDEX <index_name>`
2. Delete all existing vector keys: `SCAN` + `DEL` by prefix
3. Recreate the index with the new `DIM`
4. Re-embed and re-ingest all data

This is destructive. Choose your embedding model before ingesting production data.

**Backfill warning:** After recreating an index with `FT.CREATE`, queries (`FT.SEARCH`) are **not allowed** while the index is backfilling and will return an error. Use `FT.INFO <index_name>` and check the `state` field -- wait until it reports `ready` before issuing queries.
