# Amazon OpenSearch Service Domain — Deploy Search Configuration

Deploy index configuration, ML models, and pipelines to a provisioned domain.

## Step 1: Migrate Index Configuration

Create the index with mappings from local setup:

```
PUT <domain-endpoint>/<index-name>
{
  "settings": { ... },
  "mappings": { ... }
}
```

Configure replicas (1-2) for high availability.

## Step 2: Deploy ML Models (semantic/hybrid search)

### Pretrained models from OpenSearch repository:

```
POST <domain-endpoint>/_plugins/_ml/models/_register?deploy=true
{
  "name": "huggingface/sentence-transformers/all-MiniLM-L12-v2",
  "version": "1.0.1",
  "model_format": "TORCH_SCRIPT"
}
```

### Remote Bedrock models:

See [provisioning-agentic-setup.md](provisioning-agentic-setup.md) Steps 1-2 for IAM role and connector setup pattern.

Test inference:

```
POST <domain-endpoint>/_plugins/_ml/models/<model-id>/_predict
{ "parameters": { "inputText": "hello world" } }
```

## Step 3: Create Ingest Pipelines

```
PUT <domain-endpoint>/_ingest/pipeline/<pipeline-name>
{
  "description": "Embedding pipeline",
  "processors": [{
    "text_embedding": {
      "model_id": "<model_id>",
      "field_map": { "<text-field>": "<vector-field>" }
    }
  }]
}
```

Attach to index:

```
PUT <domain-endpoint>/<index-name>/_settings
{ "index.default_pipeline": "<pipeline-name>" }
```

## Step 4: Create Search Pipelines (hybrid search)

```
PUT <domain-endpoint>/_search/pipeline/<search-pipeline-name>
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.3, 0.7] } }
    }
  }]
}
```

## Step 5: Index Sample Documents & Test

Index test documents and verify pipeline processing with appropriate search queries.

## Next Step

- **Agentic search**: Proceed to [provisioning-agentic-setup.md](provisioning-agentic-setup.md)
- **All other strategies**: Deployment complete.

## Security Considerations

- Ensure encryption at rest is enabled on the domain before deploying ML models or embedding pipelines
- Enable CloudTrail to audit model deployments and data access
- Enforce HTTPS for all API operations
