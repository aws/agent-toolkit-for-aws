# Bedrock Connector Setup for AOS/AOSS

## Creating a Bedrock Connector

### Step 1: Create IAM Role for Connector

```bash
# Service principal: opensearchservice.amazonaws.com (AOS managed domains)
# For AOSS, use ml.opensearchservice.amazonaws.com instead (see AOSS-Specific Notes below)
# Both aws:SourceAccount and aws:SourceArn conditions are required to prevent
# confused-deputy: ArnLike narrows trust to a specific domain (or collection
# for AOSS — replace the resource pattern accordingly) so other domains in
# the same account can't assume this role.
aws iam create-role --role-name OpenSearchBedrockRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "opensearchservice.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "<account>"},
        "ArnLike":      {"aws:SourceArn":     "arn:aws:es:<region>:<account>:domain/<domain-name>"}
      }
    }]
  }'
```

Attach Bedrock access (least-privilege inline policy):

```bash
aws iam put-role-policy --role-name OpenSearchBedrockRole \
  --policy-name BedrockInvokeModel \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0"}]
  }'
```

### Step 2: Create Connector

**For Titan Embeddings V2 (1024 dimensions):**

Use `awscurl` to call the OpenSearch API directly:

```
POST /_plugins/_ml/connectors/_create
{
  "name": "Amazon Bedrock Titan Embedding V2",
  "description": "Connector for Titan Text Embeddings V2",
  "version": 1,
  "protocol": "aws_sigv4",
  "parameters": {
    "region": "<region>",
    "service_name": "bedrock",
    "model": "amazon.titan-embed-text-v2:0"
  },
  "credential": {
    "roleArn": "arn:aws:iam::<account>:role/OpenSearchBedrockRole"
  },
  "actions": [{
    "action_type": "predict",
    "method": "POST",
    "url": "https://bedrock-runtime.<region>.amazonaws.com/model/amazon.titan-embed-text-v2:0/invoke",
    "headers": {"content-type": "application/json"},
    "request_body": "{\"inputText\": \"${parameters.inputText}\"}",
    "pre_process_function": "connector.pre_process.bedrock.embedding",
    "post_process_function": "connector.post_process.bedrock.embedding"
  }]
}
```

**For Cohere Embed English V3 (1024 dimensions):**

Replace model references with `cohere.embed-english-v3` and update URL and request body accordingly.

### Step 3: Register and Deploy Model

```
POST /_plugins/_ml/models/_register
{
  "name": "Bedrock Titan Embedding",
  "function_name": "remote",
  "connector_id": "<connector_id>"
}
```

Then deploy:

```
POST /_plugins/_ml/models/<model_id>/_deploy
```

> **Monitoring:** Enable CloudTrail to audit bedrock:InvokeModel calls. Set up CloudWatch alarms on invocation latency and errors.
> **Encryption:** Ensure the OpenSearch domain/collection has encryption at rest enabled (KMS) before deploying the model and ingesting embeddings.

## Supported Models

| Model | Dimensions | Use Case |
|-------|-----------|----------|
| amazon.titan-embed-text-v2:0 | 256/512/1024 | General-purpose English embeddings |
| cohere.embed-english-v3 | 1024 | High-quality English embeddings |
| cohere.embed-multilingual-v3 | 1024 | Multilingual embeddings |

## AOSS-Specific Notes

- **Trust policy**: On AOSS, the connector role must use `ml.opensearchservice.amazonaws.com` as service principal
- On AOSS, connector creation uses the same API but authentication flows through the collection endpoint
- Data access policies must grant the connector role `aoss:ReadDocument`, `aoss:WriteDocument`, and `aoss:CreateIndex` permissions on the collection
- Model deployment status can be checked via `GET /_plugins/_ml/models/<model_id>`
