# Create a Bedrock Knowledge Base with Data Source

## Table of Contents

- Overview
- Parameters
- Steps: Validate Prerequisites, Select Chunking Strategy, Select and Configure Vector Store, Create Knowledge Base, Create Data Source, Run Initial Ingestion, Verify Knowledge Base
- Security Considerations

## Overview

Deterministic procedure for creating a Bedrock Knowledge Base with a data source,
configuring chunking strategy and vector store, running initial ingestion, and
verifying the KB is queryable. This procedure is invoked from the bedrock skill
when a user wants to build a RAG application.

## Parameters

- **kb_name** (required): Name for the Knowledge Base
- **data_source_type** (required): `s3` | `web_crawler` | `confluence` | `sharepoint` | `salesforce` | `custom` — additional types may be available, check `aws bedrock-agent create-data-source help` for current options
- **s3_bucket** (required if S3): S3 bucket containing source documents
- **s3_prefix** (optional): Prefix to scope documents within the bucket
- **chunking_strategy** (optional): `fixed_size` | `semantic` | `hierarchical` | `none` — see Step 2 for guidance
- **vector_store** (optional): `opensearch_serverless` | `aurora_postgresql` | `pinecone` | `redis` | `mongo_db_atlas` | `neptune_analytics` | `opensearch_managed_cluster` | `s3_vectors` — see Step 3 for guidance
- **embedding_model** (optional): Default `amazon.titan-embed-text-v2:0`

**Constraints for parameter acquisition:**

- You MUST verify all required parameters (`kb_name`, `data_source_type`, and data source details) are provided. If any are missing, ask for them upfront in a single prompt.
- If all required parameters are provided, proceed to Step 1 — do not ask the user to confirm what they already specified.
- For optional parameters not specified by the user, you SHOULD select reasonable values based on the guidance in Steps 2 and 3, you MUST inform the user what you chose and why, and proceed

## Steps

**General constraints:**

- You MUST present an overview of the steps before starting
- You MUST explain to the user what step is being executed and why before running each command
- You MUST respect the user's decision to abort at any point
- You MUST inform the user which vector store you are creating before proceeding (Step 3 creates infrastructure). If the user specified a preference, use it. Otherwise, use the simplest option, state your choice, and proceed

### 1. Validate Prerequisites

**Constraints:**

- You MUST verify the AWS CLI is available and configured before proceeding
- You MUST inform the user about any missing tools and ask if they want to proceed
- You MUST verify the data source exists and contains documents
- You MUST verify supported file formats for S3: PDF, TXT, MD, HTML, DOC, DOCX, CSV, XLS, XLSX
- You MUST verify the embedding model is accessible: `aws bedrock list-foundation-models --region <region>`
- You MUST NOT proceed if the data source is empty
- For non-S3 data sources, You MUST verify additional permissions:
  - **SharePoint**: **App-Only authentication is recommended** (OAuth 2.0 is not recommended per AWS docs). Configure APP permissions via the SharePoint App-Only grant flow — no Microsoft Graph API permissions needed. Security Defaults and MFA do not need to be disabled for App-Only. See the [SharePoint connector docs](https://docs.aws.amazon.com/bedrock/latest/userguide/sharepoint-data-source-connector.html) for current requirements.
  - **Confluence**: Supports Basic auth (API token) or OAuth 2.0 (client credentials). Basic requires space read permissions. OAuth 2.0 requires additional scope configuration. See the [Confluence connector docs](https://docs.aws.amazon.com/bedrock/latest/userguide/confluence-data-source-connector.html) for current requirements.
  - **Salesforce**: Connected app with appropriate OAuth scopes
  - **Web Crawler**: URL scope configuration, robots.txt compliance
- You MUST inform the user that non-S3 data sources have permission requirements beyond what the console wizard sets up

### 2. Select Chunking Strategy

**Constraints:**

- You SHOULD ask the user about their document types if chunking_strategy is not specified
- You SHOULD recommend based on document type:

| Strategy | Best For | Tradeoff |
|----------|----------|----------|
| `fixed_size` | FAQs, short articles, uniform documents | Simple but may split semantic units. Chunk size 200-300 tokens, 10-20% overlap. |
| `semantic` | Long-form content, technical docs, reports | Better quality but slower ingestion. |
| `hierarchical` | Structured docs with chapters/sections (manuals, legal) | Best retrieval quality for structured docs but most complex. |
| `none` | Pre-chunked data, documents under 300 tokens | No processing. |

- If documents contain tables or complex figures, You MUST recommend enabling **advanced parsing (FM-based)** because standard chunking breaks tables across chunks, destroying structure
- You MUST NOT use default chunking for documents with complex tables or figures
- You MUST warn the user that the chunking strategy cannot be changed after data source creation — this choice is irreversible (the data source must be deleted and recreated to change chunking)
- You MUST inform the user which chunking strategy you are using before creating the data source — the chunking configuration cannot be changed after data source creation (you must delete and recreate the data source to change it)
- Refer to the latest AWS documentation on Bedrock Knowledge Base chunking strategies for current configuration parameters

### 3. Select and Configure Vector Store

**Constraints:**

- You SHOULD ask the user about existing infrastructure if vector_store is not specified
- You SHOULD recommend based on this decision matrix:

| Vector Store | Best When | Setup Complexity |
|-------------|-----------|-----------------|
| S3 Vectors | Simplest setup, AWS-managed, no infrastructure to configure | Low — Bedrock can auto-create |
| OpenSearch Serverless | No existing vector DB, most use cases, need advanced filtering | Medium — create collection + index |
| Aurora PostgreSQL | Already using Aurora, cost-sensitive | Medium — enable pgvector extension |
| Pinecone | Already using Pinecone | Low — create index + store API key in Secrets Manager |
| Redis Enterprise Cloud | Need lowest latency | Medium — create cluster with vector search module |
| MongoDB Atlas | Already using MongoDB | Medium — create vector index + store credentials in Secrets Manager |
| Neptune Analytics | Graph-based RAG use cases | Medium — create graph + configure |
| OpenSearch Managed Cluster | Existing self-managed OpenSearch | Medium — configure domain + index |

Additional vector stores may be available — refer to the latest [AWS documentation on KB vector store setup](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html) for current options.

- Refer to the latest AWS documentation on Bedrock Knowledge Base vector store setup for configuration steps
- If using S3 Vectors:
  - S3 Vectors uses a dedicated vector bucket (`vectorBucketArn`), not a regular S3 bucket
  - Refer to the latest [AWS documentation on Bedrock Knowledge Base S3 Vectors storage configuration](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_S3VectorsConfiguration.html) for the correct storage configuration parameters
- If using OpenSearch Serverless:
  - You MUST create a VECTORSEARCH type collection
  - You MUST verify the data access policy includes the Bedrock service role ARN
  - You MUST verify vector index field names (vector field, text field, metadata field) match the KB creation request
  - Creation sequence matters — You MUST follow this exact order: create collection → create vector index with correct field mappings → then create KB. Creating the KB before the vector index is ready causes cryptic configuration errors.
- If using Pinecone:
  - You MUST verify the API key is valid and not regenerated since storage in Secrets Manager
  - Index dimensions MUST match the embedding model dimensions
- You MUST NOT proceed to KB creation until the vector store is fully configured and accessible
- For vector stores that require credentials (Pinecone, Redis, MongoDB Atlas, and Aurora PostgreSQL via RDS Data API), credentials MUST be stored in AWS Secrets Manager — never pass credentials directly. The KB service role needs `secretsmanager:GetSecretValue` permission on the secret ARN.

### 4. Create IAM Service Role and Knowledge Base

**Constraints:**

- You MUST NOT skip the IAM role — KB creation will fail without it
- You MUST create the role and ALL policies BEFORE calling `create-knowledge-base`
- After creating the IAM role, you MUST allow time for IAM propagation before using it in `create-knowledge-base`. If you get an error indicating Bedrock cannot assume the role, retry with exponential backoff up to 3 attempts. IAM role creation is eventually consistent — newly created roles may not be immediately assumable by AWS services (see [IAM eventual consistency](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_general.html#troubleshoot_general_eventual-consistency))
- For the full and latest set of permissions for all vector store types, refer to [Create a service role for Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html)

#### Step 4a: Create the IAM service role

Trust policy allows `bedrock.amazonaws.com` to assume the role with confused deputy protection (source: [AWS docs — KB trust relationship](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html#kb-permissions-trust)):

```bash
aws iam create-role \
  --role-name AmazonBedrockExecutionRoleForKB-<kb_name> \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "bedrock.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "<account-id>"},
        "ArnLike": {"aws:SourceArn": "arn:aws:bedrock:<region>:<account-id>:knowledge-base/*"}
      }
    }]
  }'
```

#### Step 4b: Attach model invocation permissions

Source: [AWS docs — KB model permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html#kb-permissions-access-models)

```bash
aws iam put-role-policy \
  --role-name AmazonBedrockExecutionRoleForKB-<kb_name> \
  --policy-name BedrockModelInvocation \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["bedrock:ListFoundationModels", "bedrock:ListCustomModels"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel"],
        "Resource": ["arn:aws:bedrock:<region>::foundation-model/<embedding-model-id>"]
      }
    ]
  }'
```

Replace `<embedding-model-id>` with the chosen embedding model (default: `amazon.titan-embed-text-v2:0`).

#### Step 4c: Attach data source permissions

Attach permissions matching the data source type selected in Step 1:

- **S3**: `s3:ListBucket` and `s3:GetObject` on the bucket
- **Confluence, SharePoint, Salesforce**: `secretsmanager:GetSecretValue` for the credentials secret

Refer to [AWS docs — KB data source permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html#kb-permissions-access-ds) for the exact policy for each data source type.

#### Step 4d: Attach vector store permissions

Attach permissions matching the vector store selected in Step 3:

- **S3 Vectors**: `s3vectors:PutVectors`, `s3vectors:GetVectors`, `s3vectors:DeleteVectors`, `s3vectors:QueryVectors`, `s3vectors:GetIndex` on the vector index ARN (`arn:aws:s3vectors:<region>:<account-id>:bucket/<bucket-name>/index/<index-name>`)
- **OpenSearch Serverless**: `aoss:APIAccessAll` on the collection ARN
- **Aurora PostgreSQL**: `rds:DescribeDBClusters`, `rds-data:BatchExecuteStatement`, `rds-data:ExecuteStatement` on the cluster ARN
- **Other vector stores** (Neptune, Pinecone, Redis, MongoDB): see docs

Refer to [AWS docs — KB service role permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html) for the exact policy JSON for each vector store type.

#### Step 4e: Create the Knowledge Base

```bash
aws bedrock-agent create-knowledge-base \
  --name <kb_name> \
  --role-arn arn:aws:iam::<account-id>:role/AmazonBedrockExecutionRoleForKB-<kb_name> \
  --knowledge-base-configuration '{"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":"arn:aws:bedrock:<region>::foundation-model/<embedding-model-id>"}}' \
  --storage-configuration '<storage-config-from-step-3>'
```

- You MUST specify the embedding model (default: `amazon.titan-embed-text-v2:0`)
- You MUST configure the storage configuration matching the vector store from Step 3
- If `create-knowledge-base` fails with an error indicating Bedrock cannot assume the role, wait and retry with exponential backoff up to 3 attempts
- As a security best practice, after the KB is created, update the trust policy to replace `knowledge-base/*` with the specific KB ID

### 5. Create Data Source

**Constraints:**

- You MUST create the data source: `aws bedrock-agent create-data-source --knowledge-base-id <kb-id> --name <name> --data-source-configuration '...'`
- You MUST inform the user which chunking strategy you are using before creating the data source — the chunking configuration cannot be changed after data source creation (you must delete and recreate the data source to change it)
- For S3 data sources:
  - The KB service role MUST have `s3:GetObject` and `s3:ListBucket` on the bucket
  - You MUST specify the chunking configuration from Step 2
- You MUST configure the data source with the chunking strategy selected in Step 2
- You MUST NOT assume the data source is ready immediately — it needs ingestion

### 6. Run Initial Ingestion

**Constraints:**

- You MUST start ingestion: `aws bedrock-agent start-ingestion-job --knowledge-base-id <kb-id> --data-source-id <ds-id>`
- You MUST poll ingestion status until `COMPLETE` or `FAILED`: `aws bedrock-agent get-ingestion-job --knowledge-base-id <kb-id> --data-source-id <ds-id> --ingestion-job-id <job-id>`
- You MUST NOT tell the user the KB is ready before ingestion completes because querying before ingestion returns empty results
- If ingestion status is `FAILED`, You MUST check:
  - S3 permissions (service role needs `s3:GetObject` + `s3:ListBucket`)
  - File format support (unsupported formats are silently skipped)
  - Vector store index dimension matches embedding model
  - Vector store is accessible (data access policy, network connectivity)
- You MUST report the number of documents processed and any failures to the user

### 7. Verify Knowledge Base

**Constraints:**

- You MUST run a test query to verify documents are indexed: `aws bedrock-agent-runtime retrieve --knowledge-base-id <kb-id> --retrieval-query '{"text":"<test-query>"}'`
- You MUST report the number of results and their relevance scores to the user
- If no results are returned, You MUST check:
  - Ingestion job completed successfully (Step 6)
  - Query is relevant to the ingested documents
  - Vector store is properly configured (Step 3)
- You SHOULD also verify end-to-end answer generation works: `aws bedrock-agent-runtime retrieve-and-generate --input '{"text":"<test-query>"}' --retrieve-and-generate-configuration '{"type":"KNOWLEDGE_BASE","knowledgeBaseConfiguration":{"knowledgeBaseId":"<kb-id>","modelArn":"<model-arn>"}}'`
- You SHOULD recommend the user test with 2-3 different queries to validate retrieval quality

## Security Considerations

These are KB-creation-specific security controls. For general Bedrock security, see the parent skill's Security Considerations section.

### Encryption

Knowledge bases support customer-managed KMS keys at multiple encryption points. For HIPAA/GDPR workloads, You MUST recommend customer-managed KMS for all applicable points:

1. **Transient data during ingestion** — data is temporarily stored during chunking/embedding. Encrypt by adding `kms:GenerateDataKey` and `kms:Decrypt` permissions for your KMS key to the KB service role
2. **Vector store encryption** — OpenSearch Serverless collections and S3 Vectors support KMS encryption at creation time
3. **S3 source data encryption** — if source documents in S3 are encrypted with a customer-managed KMS key, the KB service role needs `kms:Decrypt` permission with `kms:ViaService` condition for `s3.<region>.amazonaws.com`
4. **Session encryption during retrieval** — encrypt `RetrieveAndGenerate` session data via `--session-configuration '{"kmsKeyArn":"<kms-key-arn>"}'` (covered in [KB retrieval reference](knowledge-bases-retrieval.md))

Amazon Bedrock uses TLS encryption for communication with third-party data source connectors and vector stores where the provider supports TLS. Refer to the latest [AWS documentation on KB encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/encryption-kb.html).

### Sensitive data in source documents

Source documents may contain PII/PHI. Once ingested, sensitive data is stored in the vector store and returned in retrieval results.

**Constraints:**

- You MUST ask the user whether source documents contain PII/PHI before starting ingestion
- If PII/PHI is present, You MUST recommend pre-ingestion redaction of sensitive data before ingesting into the knowledge base
- You SHOULD recommend applying guardrails during retrieval to mask/block PII in responses (see [guardrails reference](guardrails.md))
- You SHOULD recommend metadata filtering for role-based access control to restrict which documents different users can retrieve

### Monitoring

KB management operations (`CreateKnowledgeBase`, `CreateDataSource`, `StartIngestionJob`) are logged as CloudTrail management events by default. For compliance workloads, You SHOULD recommend setting up CloudWatch alarms on ingestion job failures. Refer to the latest [AWS documentation on Bedrock CloudTrail logging](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html).
