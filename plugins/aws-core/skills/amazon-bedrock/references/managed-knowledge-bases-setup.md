# Create a Bedrock **Managed** Knowledge Base (MKB) with a Data Source

> The AWS MCP server is recommended for executing these commands (sandboxed execution + audit logging) but is not required — all steps use standard AWS CLI syntax; the streaming retrieval consumer (see [managed KB retrieval](managed-knowledge-bases-retrieval.md)) uses boto3.

## Overview

A **Managed Knowledge Base (MKB)** manages the vector store, parsing, and retrieval for you. Compared with the Customer-managed path ([customer-managed KB setup](knowledge-bases-setup.md)), you do **not** provision or select a vector store, and the IAM role only needs **data-source connector access** (not vector-store permissions). The data source uses the **managed connector** shape, not the Customer-managed `s3Configuration` shape. Parsing/chunking options and the connector set evolve — consult the create-KB docs rather than assuming a fixed set.

Use this managed path by default. Use [customer-managed KB setup](knowledge-bases-setup.md) only if the user explicitly asks for a Customer-managed KB (see the KB decision guide in `SKILL.md`).

**SDK floor:** MKB create/connect APIs require boto3/botocore >= 1.43.64 — the `MANAGED` KB type and `MANAGED_KNOWLEDGE_BASE_CONNECTOR` are absent below that floor. Verify your installed version (`aws --version` / `pip show botocore`).

## Parameters

- **kb_name** (required)
- **data_source_type** (required): the managed connector set is **expanding** and must not be hardcoded — discover the set via `aws bedrock-agent create-data-source help` or the "Connect a data source to your managed knowledge base" doc. (Some connectors like S3 are credential-free; others need Secrets Manager credentials — check the connector docs.)
- **region** (optional; MKB is GA in a subset of regions — verify coverage via the [Bedrock endpoints docs](https://docs.aws.amazon.com/general/latest/gr/bedrock.html) before assuming availability)
- **embedding**: managed by default (`embeddingModelType: MANAGED`). Optional custom embedding model at create time (see Step 2).

**Constraints for parameter acquisition:** verify required inputs are present; ask once, upfront, for anything missing. Do not re-confirm values the user already gave.

## Steps

**General constraints:** present the steps before starting; explain each step before running it; respect an abort at any point.

### 1. Create the IAM service role (connector access only)

The managed KB still needs a service role for the data-source connector — but **not** vector-store permissions (the store is managed). Trust `bedrock.amazonaws.com` with confused-deputy protection:

```bash
aws iam create-role --role-name AmazonBedrockExecutionRoleForKB-<kb_name> \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<account-id>"},"ArnLike":{"aws:SourceArn":"arn:aws:bedrock:<region>:<account-id>:knowledge-base/*"}}}]}'
```

Attach only the connector's data-access permissions — check the [connector docs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html) for the exact permissions your chosen connector requires. Common patterns:

- **S3 (example — credential-free):** `s3:ListBucket` + `s3:GetObject` on the bucket / objects.
- **Credentialed connectors (e.g. Confluence):** `secretsmanager:GetSecretValue` on the credentials secret.
- **Web Crawler (example):** no data-source credentials needed.

Example scoped S3 permission policy (attach to the role) — use resource-level ARNs, never `Resource: "*"`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::<bucket-name>"},
    {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::<bucket-name>/*"}
  ]
}
```

For managed-embedding KBs you do **not** need `bedrock:InvokeModel` on the role (embeddings are AWS-managed). Add it only if you select a **custom** embedding model in Step 2. Refer to the [KB service-role docs](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html); after creation, tighten `knowledge-base/*` to the specific KB ID.

### 2. Create the Managed Knowledge Base

Zero-config managed default (no storage configuration, no chunking configuration):

```bash
aws bedrock-agent create-knowledge-base --name <kb_name> \
  --role-arn arn:aws:iam::<account-id>:role/AmazonBedrockExecutionRoleForKB-<kb_name> \
  --knowledge-base-configuration '{"type":"MANAGED","managedKnowledgeBaseConfiguration":{"embeddingModelType":"MANAGED"}}'
```

- You MUST set `type: MANAGED` and MUST NOT pass `--storage-configuration` — the vector store is managed. (A Customer-managed `VECTOR` KB with a `storageConfiguration` is the Customer-managed path, not this one.)
- **Encryption key:** the example uses Bedrock's default AWS-owned key, which encrypts the KB at rest and is sufficient for most workloads. Add `serverSideEncryptionConfiguration.kmsKeyArn` inside `managedKnowledgeBaseConfiguration` when you need control over the encryption key (rotation, access policy, audit) — e.g. compliance-driven workloads (see Security Considerations).
- **Optional custom embedding** (immutable after create): `managedKnowledgeBaseConfiguration.embeddingModelType = CUSTOM` + `embeddingModelArn` (+ optional `embeddingModelConfiguration`, `serverSideEncryptionConfiguration.kmsKeyArn`). This makes it a *custom-embedding* MKB; the role then needs `bedrock:InvokeModel` on that model ARN.
- Creation is **asynchronous** (returns HTTP 202). Poll `aws bedrock-agent get-knowledge-base --knowledge-base-id <kb-id>` until `status` is `ACTIVE` before adding the data source.
- **IAM propagation:** the freshly-created role may not be assumable immediately (IAM eventual consistency). If `create-knowledge-base` returns an "unable to assume role" / validation error right after Step 1, wait ~10s and retry before treating it as a real failure.

### 3. Create the data source (managed connector)

The managed KB uses `type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with a `connectorParameters` document. **This is NOT the Customer-managed `s3Configuration.bucketArn` shape.**

> ⚠️ **TRAP — blog vs docs.** Some AWS blog posts show a managed KB using the Customer-managed `dataSourceConfiguration.type = "S3"` with `s3Configuration.bucketArn` and `start_ingestion_job`. For a managed KB the data source MUST use `MANAGED_KNOWLEDGE_BASE_CONNECTOR` + `connectorParameters.connectionConfiguration.bucketName`. Do not copy the blog shape.

**S3 (credential-free happy path — do this first):**

```bash
aws bedrock-agent create-data-source --knowledge-base-id <kb-id> --name <ds_name> \
  --data-source-configuration '{"type":"MANAGED_KNOWLEDGE_BASE_CONNECTOR","managedKnowledgeBaseConnectorConfiguration":{"connectorParameters":{"type":"S3","version":"1","connectionConfiguration":{"bucketName":"<bucket>","bucketOwnerAccountId":"<account-id>"}}}}'
```

Optional on the managed connector config: `deletionProtectionConfiguration` (status + threshold % — check the API docs for the default and applicability), `mediaExtractionConfiguration` (image/audio/video toggles).

**Generic connector procedure (Confluence, SharePoint, or any other supported connector):** do NOT hardcode a per-connector blueprint. Instead: (a) read the connector's AWS doc; (b) gather its required connection fields + the exact Secrets Manager key format for the chosen auth type; (c) create the secret; (d) grant the role `secretsmanager:GetSecretValue`; (e) assemble `connectorParameters` with `type`, `version: "1"`, and the connector's connection block. Confluence is the reference example of the credentialed pattern (hostUrl/hostType/authType/credentialsSecretArn).

For any other connector, follow its AWS doc for the connection block — the supported connector set evolves, so don't assume a fixed list.

`CreateDataSource` for the managed connector is **asynchronous**: poll `aws bedrock-agent get-data-source --knowledge-base-id <kb-id> --data-source-id <ds-id>` until the data source is `AVAILABLE` before ingesting.

### 4. Ingest / sync

Start ingestion and poll to completion:

```bash
aws bedrock-agent start-ingestion-job --knowledge-base-id <kb-id> --data-source-id <ds-id>
aws bedrock-agent get-ingestion-job --knowledge-base-id <kb-id> --data-source-id <ds-id> --ingestion-job-id <job-id>
```

Do not tell the user the KB is ready before ingestion reaches `COMPLETE` — querying before then returns empty results. If the API/docs for your connector expose a managed "sync" verb instead of `start-ingestion-job`, use that; verify against the docs.

### 5. Verify

Verify with the **`Retrieve`** API — `RetrieveAndGenerate` is the Customer-managed path; if you specifically need it on MKB, verify support against the docs (see [managed KB retrieval](managed-knowledge-bases-retrieval.md)):

```bash
aws bedrock-agent-runtime retrieve --knowledge-base-id <kb-id> --retrieval-query '{"text":"<test-query>"}'
```

Report the number of results and top scores. If empty: confirm ingestion `COMPLETE`, the query is relevant, and the data source is `AVAILABLE`.

### 6. Enable CloudTrail data-event logging (for query auditing)

`Retrieve` and `GetDocumentContent` on the KB are CloudTrail **data events**, which are **not logged by default** (unlike management events such as `CreateKnowledgeBase`, which are captured automatically). You SHOULD enable data-event logging for the `AWS::Bedrock::KnowledgeBase` resource type on production KBs — add a data-event selector to a CloudTrail trail (or event data store) after the KB is created, so KB access (which can surface any ingested data) is auditable and access failures can be alarmed on. Refer to the [Bedrock CloudTrail docs](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html) for the exact selector configuration.

## Connectors

The supported connector set and its per-type availability change frequently — and AWS's own docs vary on the exact list — so do **not** rely on a static matrix. Discover the connectors via `aws bedrock-agent create-data-source help` or the "Connect a data source to your managed knowledge base" doc. Some connectors (such as S3) are credential-free; others require Secrets Manager credentials — check the connector docs for each type's requirements. If the user needs a source MKB does not support, that is when a Customer-managed KB applies — but only pursue it when the user explicitly asks.

## Security Considerations

- **Least-privilege role.** Grant only the connector's data-access permissions (S3 read, or Secrets Manager `GetSecretValue`); do not attach vector-store or broad `bedrock:*` permissions. Add `bedrock:InvokeModel` only for a custom embedding model, scoped to that model ARN.
- **Confused-deputy protection.** Keep the `aws:SourceAccount` + `aws:SourceArn` conditions on the role trust policy; tighten `knowledge-base/*` to the specific KB ID after creation.
- **Credentials in Secrets Manager.** For credentialed connectors, store credentials in AWS Secrets Manager (never inline); the role reads them via `GetSecretValue`.
- **Sensitive source data.** Documents may contain PII/PHI which becomes retrievable once ingested. Classify/redact before ingesting; apply document-level ACL permission filtering at retrieval where the connector supports it — check the connector docs for per-type support.
- **Encrypt the source data store.** Ensure the connected source (e.g. the S3 bucket) has server-side encryption enabled (SSE-KMS preferred) before connecting it as a data source.
- **Encryption.** MKB encrypts at rest with an AWS-owned key by default (sufficient for most workloads). Specify a **customer-managed KMS key** via `serverSideEncryptionConfiguration.kmsKeyArn` at create time when you need control over key rotation, access, and audit (e.g. compliance-driven workloads). All data-plane calls use TLS.
- **Monitoring.** `CreateKnowledgeBase` / `CreateDataSource` / `StartIngestionJob` are CloudTrail management events; alarm on ingestion failures for all production workloads, and encrypt the CloudWatch Logs log group with a customer-managed KMS key (ingestion metadata/errors can expose source-document content or connection details). Also enable **CloudTrail data-event logging** for `AWS::Bedrock::KnowledgeBase` from creation onward — `Retrieve` / query calls are data events and are not logged by default, so enabling them makes KB access auditable. Refer to the [Bedrock CloudTrail docs](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html).
- **References.** [Amazon Bedrock security best practices](https://docs.aws.amazon.com/bedrock/latest/userguide/security-best-practices.html) and [Identity and access management for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html).
