# Index Configuration for AOS/AOSS

> OpenSearch REST calls in this file go through the `aws_opensearch` capability in `run_script` where the AWS MCP server is available, or `awscurl` otherwise; see [`data-plane-requests.md`](data-plane-requests.md).

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

### Index a Document Through the Pipeline

`my-index` sets `default_pipeline`, so a plain write runs the `text_embedding` processor (otherwise add `?pipeline=my-ingest-pipeline`):

```
POST /my-index/_doc
{"text": "OpenSearch supports semantic search with Bedrock embeddings."}
```

Verify the vector was written before building queries. Wait a few seconds for refresh (about 5 s on AOSS NextGen vector collections, 60 s on Classic), then run:

```
GET /my-index/_search
{"size": 1, "_source": true}
```

`"_source": true` is required because NextGen vector collections omit vectors from search responses by default. The hit must contain a 1024-element `embedding` array:

- 0 hits: the document is not searchable yet (refresh delay); wait and retry.
- A hit without `embedding`: the pipeline did not run; check `default_pipeline` on the index.
- The `POST /my-index/_doc` itself returned an error: check the model deployment (`GET /_plugins/_ml/models/<model_id>`).

Source: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html

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
