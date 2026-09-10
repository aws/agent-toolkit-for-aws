# Amazon OpenSearch Serverless — Deploy Search Configuration

> The AWS MCP server is recommended for executing these commands but is not required — all steps use standard AWS CLI syntax.

Deploy indices, ML models, and pipelines to a provisioned serverless collection.

## Route by Strategy

- **Neural Sparse** → Neural Sparse Path
- **Dense Vector or Hybrid** → Dense Vector Path
- **BM25** → BM25 Path

---

## Neural Sparse Path (Automatic Semantic Enrichment)

Create index with automatic enrichment via AWS API:

```json
POST /opensearchserverless/CreateIndex
{
  "id": "<collection-id>",
  "indexName": "<index-name>",
  "indexSchema": {
    "mappings": {
      "properties": {
        "<text-field>": {
          "type": "text",
          "semantic_enrichment": {
            "status": "ENABLED",
            "language_options": "english"
          }
        }
      }
    }
  }
}
```

> **Note:** Use `aws opensearchserverless create-index` for this operation (or `call_aws opensearchserverless create-index` if the AWS MCP server is available). The `semantic_enrichment` configuration is specified in the index schema.

- `language_options`: "english" or "multi-lingual"
- System automatically deploys sparse model and creates ingest/search pipelines
- Standard `match` queries are automatically rewritten to neural sparse queries
- No manual model or pipeline management required

---

## Dense Vector Path

### 1. Create IAM Role for Bedrock

```bash
# Both aws:SourceAccount and aws:SourceArn conditions are required to prevent
# confused-deputy: ArnLike narrows trust to a specific AOSS collection so
# other collections in the same account can't assume this role.
aws iam create-role --role-name opensearch-bedrock-role \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Principal":{"Service":"ml.opensearchservice.amazonaws.com"},
      "Action":"sts:AssumeRole",
      "Condition":{
        "StringEquals":{"aws:SourceAccount":"<account>"},
        "ArnLike":     {"aws:SourceArn":    "arn:aws:aoss:<region>:<account>:collection/<collection-id>"}
      }
    }]
  }'

aws iam put-role-policy --role-name opensearch-bedrock-role \
  --policy-name BedrockInvokePolicy \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0"}]}'
```

### 2. Create ML Connector

```
POST <collection-endpoint>/_plugins/_ml/connectors/_create
{
  "name": "Amazon Bedrock Titan Embedding V2",
  "version": 1,
  "protocol": "aws_sigv4",
  "parameters": { "region": "<aws-region>", "service_name": "bedrock" },
  "credential": { "roleArn": "<iam_role_arn>" },
  "actions": [{
    "action_type": "predict",
    "method": "POST",
    "url": "https://bedrock-runtime.<aws-region>.amazonaws.com/model/amazon.titan-embed-text-v2:0/invoke",
    "headers": { "content-type": "application/json", "x-amz-content-sha256": "required" },
    "request_body": "{ \"inputText\": \"${parameters.inputText}\" }",
    "pre_process_function": "connector.pre_process.bedrock.embedding",
    "post_process_function": "connector.post_process.bedrock.embedding"
  }]
}
```

### 3. Register and Deploy Model

```
POST <collection-endpoint>/_plugins/_ml/model_groups/_register
{ "name": "bedrock_embedding_models", "description": "Bedrock embedding model group" }

POST <collection-endpoint>/_plugins/_ml/models/_register
{
  "name": "bedrock-titan-embed-v2",
  "function_name": "remote",
  "model_group_id": "<model_group_id>",
  "connector_id": "<connector_id>"
}

POST <collection-endpoint>/_plugins/_ml/models/<model-id>/_deploy
```

Test: `POST /_plugins/_ml/models/<model-id>/_predict` with `{"parameters": {"inputText": "hello world"}}`. Verify 1024-dim embeddings.

### 4. Create Ingest Pipeline

```
PUT <collection-endpoint>/_ingest/pipeline/bedrock-embedding-pipeline
{
  "processors": [{
    "text_embedding": {
      "model_id": "<model_id>",
      "field_map": { "<text-field>": "<vector-field>" }
    }
  }]
}
```

### 5. Create Index

```
PUT <collection-endpoint>/<index-name>
{
  "settings": {
    "index.knn": true,
    "index.default_pipeline": "bedrock-embedding-pipeline"
  },
  "mappings": {
    "properties": {
      "<text-field>": { "type": "text" },
      "<vector-field>": {
        "type": "knn_vector",
        "dimension": 1024
      }
    }
  }
}
```

> **Note:** Omit `engine`/`mode` unless you have confirmed support for your collection generation — NextGen rejects them (`Field parameter 'engine' is not supported`) and auto-selects the engine. NextGen support can change over time, so rather than treating this as a fixed prohibition, prefer omitting these fields and, if you need to set them, attempt creation and handle any validation error (same pattern used for OCU values in [provisioning-serverless-provision.md](provisioning-serverless-provision.md)). `space_type` is optional (defaults to L2); to use another metric, add it at the field level, e.g. `"space_type": "cosinesimil"`.

### 6. Search Pipeline (hybrid only)

```
PUT <collection-endpoint>/_search/pipeline/hybrid-search-pipeline
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.3, 0.7] } }
    }
  }]
}
```

---

## BM25 Path

Create index with text mappings:

```
PUT <collection-endpoint>/<index-name>
{ "mappings": { "properties": { "<text-field>": { "type": "text" } } } }
```

---

## Index Sample Documents & Test

After index creation (all paths):

1. Index test documents to verify setup
2. Test search queries:
   - Neural Sparse: standard `match` queries (auto-rewritten)
   - Dense Vector: `neural` query with `model_id`
   - BM25: standard `match` queries

## Next Step (optional)

- **Agentic search** (natural-language query → DSL, flow agent): see [provisioning-serverless-agentic-setup.md](provisioning-serverless-agentic-setup.md).

## Security Considerations

- **Encryption in transit:** all data-plane calls (index creation, indexing, search) MUST use HTTPS. Verify the collection endpoint starts with `https://`, because an unencrypted request exposes documents and queries in transit.
- **Encryption at rest:** indexed embeddings and document content are sensitive; AOSS encrypts at rest by default, and compliance workloads should use a customer-managed KMS key on the encryption policy (see [provisioning-serverless-provision.md](provisioning-serverless-provision.md)).
- **Least-privilege connector role:** scope the ML model connector role to the minimum data-access actions and the specific model ARN it invokes, because a broad connector role is a standing path into the data plane.
