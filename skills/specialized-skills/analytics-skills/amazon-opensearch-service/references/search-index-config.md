# Index Configuration for AOS/AOSS

## Creating Indices with Vector Fields

### Semantic Search Index (k-NN enabled)

```
PUT /my-index
{
  "settings": {
    "index": {
      "knn": true,
      "default_pipeline": "my-ingest-pipeline"
    }
  },
  "mappings": {
    "properties": {
      "text": {"type": "text"},
      "embedding": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {"engine": "faiss", "name": "hnsw", "space_type": "l2"}
      }
    }
  }
}
```

### Hybrid Search Index (BM25 + vector)

```
PUT /my-hybrid-index
{
  "settings": {
    "index": {"knn": true, "default_pipeline": "hybrid-ingest-pipeline"}
  },
  "mappings": {
    "properties": {
      "title": {"type": "text"},
      "content": {"type": "text"},
      "content_embedding": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {"engine": "faiss", "name": "hnsw", "space_type": "l2"}
      }
    }
  }
}
```

## Ingest Pipeline Configuration

### Neural Ingest Pipeline

```
PUT /_ingest/pipeline/my-ingest-pipeline
{
  "processors": [{
    "text_embedding": {
      "model_id": "<model_id>",
      "field_map": {"text": "embedding"}
    }
  }]
}
```

## Search Pipeline Configuration

### Hybrid Search Pipeline (normalization + combination)

```
PUT /_search/pipeline/hybrid-search-pipeline
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": {"technique": "min_max"},
      "combination": {"technique": "arithmetic_mean", "parameters": {"weights": [0.3, 0.7]}}
    }
  }]
}
```

### Example Hybrid Query

```
POST /my-hybrid-index/_search?search_pipeline=hybrid-search-pipeline
{
  "query": {
    "hybrid": {
      "queries": [
        {"match": {"content": "search query"}},
        {"neural": {"content_embedding": {"query_text": "search query", "model_id": "<model_id>", "k": 10}}}
      ]
    }
  }
}
```

## AOSS Constraints

- AOSS supports HNSW with Faiss engine only (no IVF, no Lucene engine). NMSLIB is removed in OS 3.x. For the engine matrix, see [vector-knn.md](vector-knn.md).
- AOSS collections are either SEARCH or VECTORSEARCH type — choose VECTORSEARCH for k-NN
- Index names must not start with underscore on AOSS
- AOSS does not support ISM policies — lifecycle is managed at the collection level

> Ensure AOSS encryption at rest is enabled before indexing embeddings. Use SigV4 authentication for all operations.
