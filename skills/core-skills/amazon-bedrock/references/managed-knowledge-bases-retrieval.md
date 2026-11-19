# Managed Knowledge Base (MKB) — Retrieval & Query Reference

> The AWS MCP server is recommended for executing these commands but is not required. `Retrieve` uses standard AWS CLI syntax; `AgenticRetrieveStream` is streaming and therefore **SDK-only** (boto3), shown inline below.

## Querying a Managed KB: use `Retrieve` or `AgenticRetrieveStream`

On a **managed** knowledge base, query with **`Retrieve`** (single-shot chunks) or **`AgenticRetrieveStream`** (agentic, streaming). `RetrieveAndGenerate` (a fully-synthesized answer with citations) is the Customer-managed path — see [customer-managed KB retrieval](knowledge-bases-retrieval.md). If you specifically need `RetrieveAndGenerate` behavior on a managed KB, verify support against the docs rather than assuming it is or isn't available.

## Query API decision

| API | Endpoint | When | Transport |
|---|---|---|---|
| `Retrieve` | `bedrock-agent-runtime` | Single-shot chunks for your own prompt/ranking | CLI or SDK |
| `AgenticRetrieveStream` | `bedrock-agent-runtime` | Agent plans → retrieves → evaluates → iterates across multiple KBs (how many: the `retrievers` row of the agentic retrieval guide's request-field table); optional synthesized answer | **SDK only** (streaming; not the AWS CLI) |
| `RetrieveAndGenerate` | `bedrock-agent-runtime` | Customer-managed path (synthesized answer); verify MKB support against the docs | CLI or SDK |

## Retrieve (single-shot)

```bash
aws bedrock-agent-runtime retrieve --knowledge-base-id <kb-id> --retrieval-query '{"text":"<query>"}'
```

Pass `numberOfResults` and a metadata `filter` under `retrievalConfiguration.managedSearchConfiguration`, not `vectorSearchConfiguration`, which is the Customer-managed wrapper. `managedSearchConfiguration` has no `overrideSearchType`: the service chooses the search strategy, so a semantic-only search cannot be requested. Its other options control reranking (`rerankingModelType`, `rerankingConfiguration`). The filter operator syntax is the same as in the [customer-managed retrieval reference](knowledge-bases-retrieval.md#metadata-filtering-syntax), except that a managed KB rejects `startsWith` and `stringContains`, boolean filter values, non-integer numbers, metadata keys that don't match `[a-zA-Z0-9_][a-zA-Z0-9_-]*`, and more than 10 filters in one `andAll` or `orAll`. Test each filter a caller sends against the KB. Metadata attributes must have been present on the ingested documents to be filterable.

## AgenticRetrieveStream (agentic, streaming, SDK-only)

The AWS CLI cannot consume the response stream, so use boto3. Requires boto3/botocore >= 1.43.64 (which includes `agentic_retrieve_stream`; absent below that floor) — verify your installed version.

```python
import boto3

def agentic_retrieve(kb_ids, question, region="us-east-1", generate=True):
    """Run AgenticRetrieveStream against one or more MANAGED knowledge bases and
    print the streamed answer. `kb_ids` is a list of managed KB IDs (the `retrievers` row of the agentic retrieval guide's request-field table states the maximum per request)."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Provide a non-empty question.")
    if not kb_ids or not all(isinstance(k, str) and k.strip() for k in kb_ids):
        raise ValueError("Provide at least one knowledge base ID; each must be a non-empty string.")
    client = boto3.client("bedrock-agent-runtime", region_name=region)
    resp = client.agentic_retrieve_stream(
        messages=[{"role": "user", "content": [{"text": question}]}],
        retrievers=[
            {"configuration": {"knowledgeBase": {"knowledgeBaseId": kb_id}}}
            for kb_id in kb_ids  # multiple KBs per request; the agentic retrieval guide's `retrievers` row states the max
        ],
        generateResponse=generate,  # to guard generated answers: policyConfiguration (below) needs CUSTOM, or set False and guard your own generation
        # Optional: agenticRetrieveConfiguration controls the planner/reranker models
        #   agenticRetrieveConfiguration={
        #       "foundationModelType": "MANAGED",   # or CUSTOM (+ foundationModelConfiguration)
        #       "maxAgentIteration": 5,             # check the API docs for the allowed range/default
        #       "rerankingModelType": "MANAGED",    # MANAGED | CUSTOM | NONE
        #   },
        # Optional guardrail — needs foundationModelType CUSTOM (+ foundationModelConfiguration); BLOCK only:
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
- `retrievers` accepts multiple managed KBs (the maximum is in the `retrievers` row of the request-field table in the [agentic retrieval guide](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-agentic-retrieve.html); read it there); each is `{"configuration": {"knowledgeBase": {"knowledgeBaseId": ...}}}`, with optional `retrievalOverrides` and a `description`.
- `generateResponse=False` returns retrieval results without a synthesized answer.
- Read the stream to completion; the terminal `result` event carries the retrieved references/citations.

## Considerations (from the API contract)

- **Managed KBs only.** `AgenticRetrieveStream` targets managed knowledge bases.
- **Guardrails, per API.** `Retrieve` takes `guardrailConfiguration` and reports `guardrailAction` ([Retrieve API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html)). `AgenticRetrieveStream` takes `policyConfiguration`, supports only the `BLOCK` action, and accepts a guardrail only with `foundationModelType` `CUSTOM`, which also needs an explicit model ([agentic retrieval guide](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-agentic-retrieve.html)).
- **Models you provide (custom mode).** A planning, embedding or reranking model you name (`CUSTOM`) is yours and is invoked with **your** IAM credentials; with `MANAGED` the service selects the model. Take the caller's required permissions from the agentic retrieval guide.
- **Limits.** The maximum number of retrievers per request is stated in the `retrievers` row of the request-field table in the [agentic retrieval guide](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-agentic-retrieve.html); results per retriever and the maximum iteration count are optional settings in the request. Read their limits on that page rather than assuming. The request rate and query length are service quotas ([managed KB quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-quotas.html)).
- **Pagination.** `nextToken` continues a multi-part response.

## Security Considerations

- **When you run the read for the customer, get an explicit yes first.** `Retrieve`, `RetrieveAndGenerate`, `AgenticRetrieveStream`, `GetDocumentContent`, or `s3:GetObject` on a corpus document returns document text, and two things follow: the text lands in this conversation and its logs, and the call runs under your role rather than an end user's, so the document-level ACLs and `userContext` filters the application enforces do not apply. Before any such read, ask the customer for an explicit yes to that read and give both reasons. A specific request ("show me the full text of the top document"), a query string, a Region or a general "go ahead" is not that yes; ask once and wait. Configuration reads (`get-*` / `list-*`, object listings with sizes) return no document text and need no yes. Rule: [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → "Content-returning reads".
- **Retrieved chunks can expose sensitive data.** Results (and the generated answer) return whatever the caller is authorized to see. Redact/classify PII/PHI before ingestion; use document-level ACL filtering via `userContext` where the connector supports it.
- **Guardrails on the generated answer.** If the customer wants a guardrail on the agentic answer, it goes in `policyConfiguration`, which needs `foundationModelType` `CUSTOM` with an explicit model and takes only `BLOCK`; in `MANAGED` mode the agentic call takes no guardrail. Which mode to use is the customer's trade-off ([managed KB API](references/bedrock-kb-migration/managed-kb-api.md), "If the user plans to adopt the agentic surface"). Other ways to guard answers: `Retrieve` takes `guardrailConfiguration`, and with `generateResponse` false the app guards its own generation.
- **Least-privilege model access.** Scope the caller's model-invoke permissions (the actions the agentic retrieval guide lists) to the specific planner/reranking/embedding model ARNs used — not `foundation-model/*`.
- **Audit + logging.** `Retrieve` / `AgenticRetrieveStream` are CloudTrail **data events** (not logged by default); enable data-event logging for `AWS::Bedrock::KnowledgeBase` to attribute who queried what. Always encrypt CloudWatch Logs log groups that receive Bedrock data events / retrieval traces with a customer-managed KMS key — retrieval results can expose any ingested data, not only PII.
- **Encryption in transit.** All data-plane calls use TLS; ensure endpoints are HTTPS.
- **Validate untrusted query input + rate-limit.** When the query text comes from end users, validate and sanitize it (enforce a max length, reject unexpected input) before calling `Retrieve` / `AgenticRetrieveStream`, and apply client-side rate limiting (per-user caps) to avoid abuse and service-quota exhaustion.
- **References.** [Amazon Bedrock security best practices](https://docs.aws.amazon.com/bedrock/latest/userguide/security-best-practices.html) and [Identity and access management for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html).
