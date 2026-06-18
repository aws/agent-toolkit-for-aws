# Troubleshooting AOS Search

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `AccessDeniedException` on connector creation | Missing IAM permissions | Verify role has `es:ESHttpPost` and data access policy grants ML actions |
| `Model deployment stuck in DEPLOYING` | Resource limits | Check `GET /_plugins/_ml/models/<id>` status; may need to undeploy unused models |
| `ConnectorAccessControlDisabledException` | ML access control not enabled | Enable via `PUT /_cluster/settings {"persistent": {"plugins.ml_commons.connector_access_control_enabled": true}}` |
| `k-NN search returns 0 results` | Index not refreshed or wrong dimension | Verify embedding dimension matches index mapping; force refresh with `POST /index/_refresh` |
| `403 on AOSS collection` | Data access policy missing | Create/update data access policy to include the IAM principal |
| `Bedrock throttling (429)` | Rate limit exceeded | Implement exponential backoff; request quota increase via Service Quotas |

## Debugging Steps

### Connector Not Returning Embeddings

1. Verify Bedrock model access: `aws bedrock list-foundation-models --region <region>`
2. Test connector: `POST /_plugins/_ml/models/<model_id>/_predict {"parameters": {"inputText": "test"}}`
3. Check connector role can invoke Bedrock: `aws iam simulate-principal-policy --policy-source-arn <role-arn> --action-names bedrock:InvokeModel`

### AOSS Authentication Failures

1. Verify SigV4 credentials: `aws sts get-caller-identity`
2. Check data access policy includes your IAM principal for the collection
3. Verify network policy allows access from your IP/VPC
4. Ensure collection type matches workload (VECTORSEARCH for k-NN)

### Ingest Pipeline Failures

1. Check pipeline exists: `GET /_ingest/pipeline/my-pipeline`
2. Simulate: `POST /_ingest/pipeline/my-pipeline/_simulate {"docs": [{"_source": {"text": "test"}}]}`
3. If model timeout: check model is deployed and healthy via `GET /_plugins/_ml/models/<id>`
