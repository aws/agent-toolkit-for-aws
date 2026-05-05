# Knowledge Bases — Retrieval & Query Reference

## Table of Contents

- Query API Decision Table
- Metadata Filtering Syntax
- Retrieval Configuration
- Session Management
- Generation Configuration
- Security Considerations

## Query API Decision Table

Three APIs — agents pick the wrong one. Use this table:

| Use Case | API | Endpoint | When |
|----------|-----|----------|------|
| Synthesize answer from docs | `RetrieveAndGenerate` | `bedrock-agent-runtime` | Most common RAG pattern. Model reads chunks and generates answer with citations. |
| Get raw chunks for custom processing | `Retrieve` | `bedrock-agent-runtime` | You want to rank, filter, or feed chunks to a different model. |
| Full prompt control | `Converse` with manual context | `bedrock-runtime` | You retrieve chunks yourself, build a custom prompt, and call the model directly. |

Most common pattern: `aws bedrock-agent-runtime retrieve-and-generate --input '{"text":"<query>"}' --retrieve-and-generate-configuration '{"type":"KNOWLEDGE_BASE","knowledgeBaseConfiguration":{"knowledgeBaseId":"<kb-id>","modelArn":"<model-arn>"}}'`

**Input limit**: The `--input` text field has a maximum of 1000 characters. Exceeding this causes a `ValidationException`. For longer queries, truncate or summarize before sending.

## Metadata Filtering Syntax

Bedrock-specific filter syntax — not in model training data. Filters narrow retrieval to relevant documents before semantic search.

**Operators:**

| Operator | Type | Example |
|----------|------|---------|
| `equals` | Exact match | `{"equals": {"key": "department", "value": "engineering"}}` |
| `notEquals` | Exclude | `{"notEquals": {"key": "status", "value": "archived"}}` |
| `greaterThan` | Number | `{"greaterThan": {"key": "year", "value": 2024}}` |
| `greaterThanOrEquals` | Number (inclusive) | `{"greaterThanOrEquals": {"key": "year", "value": 2024}}` |
| `lessThan` | Number | `{"lessThan": {"key": "year", "value": 2026}}` |
| `lessThanOrEquals` | Number (inclusive) | `{"lessThanOrEquals": {"key": "year", "value": 2026}}` |
| `in` | Match any in list | `{"in": {"key": "category", "value": ["guide", "tutorial"]}}` |
| `notIn` | Exclude list | `{"notIn": {"key": "type", "value": ["draft", "deprecated"]}}` |
| `startsWith` | Prefix match (string) | `{"startsWith": {"key": "path", "value": "/docs/api"}}` |
| `stringContains` | Substring (string) | `{"stringContains": {"key": "title", "value": "setup"}}` |
| `listContains` | List attribute contains value (string) | `{"listContains": {"key": "tags", "value": "security"}}` |

**Vector store limitations for operators:** `startsWith` and `stringContains` are currently best supported with Amazon OpenSearch Serverless vector stores. Neptune Analytics GraphRAG supports the `stringContains` string variant but not the list variant. `listContains` is currently best supported with Amazon OpenSearch Serverless. S3 vector buckets do NOT support `startsWith` or `stringContains`. If you use these operators with an unsupported vector store, the filter is silently ignored.

Refer to the latest AWS documentation on Bedrock Knowledge Base RetrievalFilter for the full current operator list.

**Combining filters:**

```json
{
  "andAll": [
    {"equals": {"key": "department", "value": "engineering"}},
    {"greaterThan": {"key": "epoch_modification_time", "value": 1704067200}}
  ]
}
```

```json
{
  "orAll": [
    {"equals": {"key": "type", "value": "guide"}},
    {"equals": {"key": "type", "value": "tutorial"}}
  ]
}
```

**Constraints:**

- Metadata attributes MUST be defined during KB creation or data source configuration — you cannot filter on attributes that weren't declared as filterable
- You MUST verify that the user's KB has metadata configured before constructing filter queries — filtering on undeclared attributes silently returns no results
- For KBs with >1000 documents, You SHOULD recommend metadata filtering for retrieval quality
- **Security use case**: Metadata filtering can enforce document-level access control — assign role/permission metadata attributes (e.g., `access_level: "admin"`) during ingestion, then filter at query time based on the calling user's role to restrict which documents they can retrieve

## Retrieval Configuration

Non-obvious defaults agents get wrong:

| Parameter | Default | Guidance |
|-----------|---------|----------|
| `overrideSearchType` | Not set (Bedrock decides) | When omitted, Bedrock automatically selects the search strategy best suited for your vector store configuration. For OpenSearch Serverless, RDS (including Aurora PostgreSQL), or MongoDB Atlas with a filterable text field, you can explicitly set to `HYBRID` (keyword + semantic) or `SEMANTIC` (vector only). For all other vector stores, only `SEMANTIC` is available. Consider `HYBRID` when supported for keyword-heavy queries. |
| `numberOfResults` | 5 | Increase for broad questions (10-20), decrease for specific lookups (3-5). More results = higher latency. |

**Score confidence threshold**: Set to filter low-relevance results.

- Too high → no results returned (common failure)
- Too low → noisy, irrelevant results
- Start with 0.5, tune based on evaluation
- Refer to the latest AWS documentation on Bedrock Knowledge Base retrieval configuration for current options

## Session Management

For multi-turn RAG conversations:

**Constraints:**

- You MUST pass `sessionId` in `RetrieveAndGenerate` calls for multi-turn conversations — omitting it causes each query to be independent, silently losing all conversation context
- You MUST NOT generate or set `sessionId` yourself — Amazon Bedrock auto-generates it on the first request; reuse the returned value for subsequent turns
- For HIPAA/GDPR workloads, You MUST encrypt session data with a customer-managed KMS key via `--session-configuration '{"kmsKeyArn":"<kms-key-arn>"}'` — session data includes conversation history which may contain sensitive retrieved content

- Context from previous turns carries forward automatically when `sessionId` is passed
- Sessions expire after a timeout — start a new session if expired

## Generation Configuration

For `RetrieveAndGenerate` only:

- **Model selection**: Specify which model generates the answer (can differ from the embedding model — this is NOT a mismatch, despite what agents assume)
- **Prompt template**: Override the default RAG prompt to customize how the model uses retrieved chunks
- **Guardrail integration**: Apply guardrails to the generated response via `guardrailConfiguration`
- Refer to the latest AWS documentation on Bedrock RetrieveAndGenerate configuration for current options

## Security Considerations

These are retrieval-specific security controls. For general Bedrock security, see the parent skill's Security Considerations section.

### Sensitive data in retrieved chunks

Retrieved chunks are the primary vector for sensitive data exposure in RAG applications. If source documents contain PII/PHI and are not sanitized before ingestion, that sensitive data will be retrieved from the vector store and can leak to users.

**Key risks:**

- Retrieved chunks appear in the API response `citations[].retrievedReferences[].content.text` field — this raw text may contain PII even if the generated response is sanitized by guardrails
- Guardrails are applied to the **input** (the augmented prompt, which includes retrieved chunks) and the **generated response** — but they are NOT applied to the raw `retrievedReferences` returned in the API response at runtime
- Application logging that captures the full API response will log sensitive chunk content

**Mitigations:**

- Redact or mask PII/PHI from source documents **before** ingestion into the knowledge base
- Use metadata filtering for document-level access control (see Metadata Filtering section above)
- Apply guardrails to filter sensitive content in the generated response
- Do not log the full `retrievedReferences` content in application logs for PII-sensitive workloads

### Audit retrieval calls with CloudTrail

`Retrieve` and `RetrieveAndGenerate` calls are logged as CloudTrail **data events** (not management events — they are not logged by default). To enable auditing of who queried what from the knowledge base, configure advanced event selectors with resource type `AWS::Bedrock::KnowledgeBase`. Refer to the latest [AWS documentation on Bedrock CloudTrail logging](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html).
