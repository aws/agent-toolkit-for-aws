# Managed Knowledge Base (MKB) — Retrieval & Query Reference

> The AWS MCP server is recommended for executing these commands but is not required. `Retrieve` uses standard AWS CLI syntax; `AgenticRetrieveStream` is streaming and therefore **SDK-only** (boto3), shown inline below.

## Querying a Managed KB: use `Retrieve` or `AgenticRetrieveStream`

On a **managed** knowledge base, query with **`Retrieve`** (single-shot chunks) or **`AgenticRetrieveStream`** (agentic, streaming). `RetrieveAndGenerate` (a fully-synthesized answer with citations) is the Customer-managed path — see [customer-managed KB retrieval](knowledge-bases-retrieval.md). If you specifically need `RetrieveAndGenerate` behavior on a managed KB, verify support against the docs rather than assuming it is or isn't available.

## Query API decision

| API | Endpoint | When | Transport |
|---|---|---|---|
| `Retrieve` | `bedrock-agent-runtime` | Single-shot chunks for your own prompt/ranking | CLI or SDK |
| `AgenticRetrieveStream` | `bedrock-agent-runtime` | Agent plans → retrieves → evaluates → iterates across multiple KBs (check the quota); optional synthesized answer | **SDK only** (streaming; not the AWS CLI) |
| `RetrieveAndGenerate` | `bedrock-agent-runtime` | Customer-managed path (synthesized answer); verify MKB support against the docs | CLI or SDK |

## Retrieve (single-shot)

```bash
aws bedrock-agent-runtime retrieve --knowledge-base-id <kb-id> --retrieval-query '{"text":"<query>"}'
```

Metadata filtering, `numberOfResults`, and `overrideSearchType` work as for other KBs — the filter operator syntax is identical to the [customer-managed retrieval reference](knowledge-bases-retrieval.md#metadata-filtering-syntax); pass it under `retrievalConfiguration.vectorSearchConfiguration.filter`. Metadata attributes must have been present on the ingested documents to be filterable.

## AgenticRetrieveStream (agentic, streaming, SDK-only)

The AWS CLI cannot consume the response stream, so use boto3. Requires boto3/botocore >= 1.43.64 (which includes `agentic_retrieve_stream`; absent below that floor) — verify your installed version.

```python
import boto3

def agentic_retrieve(kb_ids, question, region="us-east-1", generate=True):
    """Run AgenticRetrieveStream against one or more MANAGED knowledge bases and
    print the streamed answer. `kb_ids` is a list of managed KB IDs (check the service quota for the max retrievers per request)."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Provide a non-empty question.")
    if not kb_ids or not all(isinstance(k, str) and k.strip() for k in kb_ids):
        raise ValueError("Provide at least one knowledge base ID; each must be a non-empty string.")
    client = boto3.client("bedrock-agent-runtime", region_name=region)
    resp = client.agentic_retrieve_stream(
        messages=[{"role": "user", "content": [{"text": question}]}],
        retrievers=[
            {"configuration": {"knowledgeBase": {"knowledgeBaseId": kb_id}}}
            for kb_id in kb_ids  # multiple KBs per request; check the service quota for the max
        ],
        generateResponse=generate,  # for production, attach a guardrail via policyConfiguration (below) before exposing generated answers
        # Optional: agenticRetrieveConfiguration controls the planner/reranker models
        #   agenticRetrieveConfiguration={
        #       "foundationModelType": "MANAGED",   # or CUSTOM (+ foundationModelConfiguration)
        #       "maxAgentIteration": 5,             # check the API docs for the allowed range/default
        #       "rerankingModelType": "MANAGED",    # MANAGED | CUSTOM | NONE
        #   },
        # Optional guardrail — check the API docs for supported action modes (e.g. BLOCK):
        #   policyConfiguration={"bedrockGuardrailConfiguration": {"guardrailId": "<id>", "guardrailVersion": "<v>"}},
        # Optional ACL identity for document-level filtering:
        #   userContext={"userId": "<user>"},
    )

    answer, citations = [], []
    for event in resp["stream"]:
        if "responseEvent" in event:            # incremental generated answer chunks
            block = event["responseEvent"].get("output", {})
            if block.get("text"):
                answer.append(block["text"])
        elif "result" in event:                 # final result: retrieved refs + citations
            citations.append(event["result"])
        elif "traceEvent" in event:             # planner/iteration trace (optional to log)
            pass
        else:                                    # exception events surface as their own keys
            for k in ("validationException", "accessDeniedException", "throttlingException",
                      "resourceNotFoundException", "conflictException", "serviceQuotaExceededException",
                      "dependencyFailedException", "internalServerException", "badGatewayException"):
                if k in event:
                    raise RuntimeError(f"AgenticRetrieveStream {k}: {event[k].get('message')}")
    # NOTE: `answer` / `citations` may contain sensitive data (PII/PHI) from the KB —
    # do not log or surface without redaction / appropriate access controls.
    return "".join(answer), citations
```

- `messages` uses Converse-style content blocks (`[{"text": ...}]`).
- `retrievers` accepts multiple managed KBs (check the service quota for the max); each is `{"configuration": {"knowledgeBase": {"knowledgeBaseId": ...}}}`, with optional `retrievalOverrides` and a `description`.
- `generateResponse=False` returns retrieval results without a synthesized answer.
- Read the stream to completion; the terminal `result` event carries the retrieved references/citations.

## Considerations (from the API contract)

- **Managed KBs only.** `AgenticRetrieveStream` targets managed knowledge bases.
- **Guardrails.** Attach via `policyConfiguration`; check the AgenticRetrieveStream docs for which guardrail action modes (e.g. BLOCK, MASK) are supported on this path — not all modes may be available.
- **You provide the models.** The planner / embedding / reranking models are invoked with **your** IAM credentials — the caller's role needs `bedrock:InvokeModel` on those model ARNs.
- **Quotas.** Retrievers per request, results per call, and max iterations are governed by service quotas — check values rather than assuming.
- **Pagination.** `nextToken` continues a multi-part response.

## Security Considerations

- **Retrieved chunks can expose sensitive data.** Results (and the generated answer) return whatever the caller is authorized to see. Redact/classify PII/PHI before ingestion; use document-level ACL filtering via `userContext` where the connector supports it.
- **Guardrails on the generated answer.** Attach a Bedrock guardrail via `policyConfiguration` for the synthesized response; verify which action modes (e.g. BLOCK, MASK) the API supports rather than assuming, and don't rely on a mode you haven't confirmed.
- **Least-privilege model access.** Scope the caller's `bedrock:InvokeModel` to the specific planner/reranking/embedding model ARNs used — not `foundation-model/*`.
- **Audit + logging.** `Retrieve` / `AgenticRetrieveStream` are CloudTrail **data events** (not logged by default); enable data-event logging for `AWS::Bedrock::KnowledgeBase` to attribute who queried what. Always encrypt CloudWatch Logs log groups that receive Bedrock data events / retrieval traces with a customer-managed KMS key — retrieval results can expose any ingested data, not only PII.
- **Encryption in transit.** All data-plane calls use TLS; ensure endpoints are HTTPS.
- **Validate untrusted query input + rate-limit.** When the query text comes from end users, validate and sanitize it (enforce a max length, reject unexpected input) before calling `Retrieve` / `AgenticRetrieveStream`, and apply client-side rate limiting (per-user caps) to avoid abuse and service-quota exhaustion.
- **References.** [Amazon Bedrock security best practices](https://docs.aws.amazon.com/bedrock/latest/userguide/security-best-practices.html) and [Identity and access management for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html).
