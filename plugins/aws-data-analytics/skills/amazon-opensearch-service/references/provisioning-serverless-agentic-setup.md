# Amazon OpenSearch Serverless — Agentic Search Setup (Flow Agent)

Configure agentic search on an Amazon OpenSearch Serverless collection using a **flow agent** with `QueryPlanningTool`. Uses Bedrock Claude as the reasoning model.

Serverless collections MUST use a flow agent (`type: flow`); conversational agents are not supported on AOSS, because Amazon OpenSearch Serverless does not provide the stateful conversation-memory backing that conversational agents require. Verify agent-type support against the AWS docs (or `aws opensearchserverless` API capabilities) before assuming this limitation still holds. Flow agents are stateless — each query is planned and executed independently. For stateful multi-turn agentic search (memory + RAG), use an Amazon OpenSearch Service **domain** instead; see [`provisioning-agentic-setup.md`](provisioning-agentic-setup.md).

## Prerequisites

- A **NextGen** collection, ACTIVE — see [`provisioning-serverless-provision.md`](provisioning-serverless-provision.md).
- Index created with data — see [`provisioning-serverless-deploy-search.md`](provisioning-serverless-deploy-search.md).
- The collection's data access policy MUST include the `agent` ResourceType (Step 4), because pipeline-invoked agentic queries fail with `403 Forbidden` without it.
- The AWS MCP server is recommended for executing these commands but is not required — steps use standard AWS CLI and `awscurl` syntax. IAM/policy steps use `aws` CLI; the data-plane `_plugins/_ml` and `_search/pipeline` calls (Steps 2, 3, 5, 6) are OpenSearch REST requests — send them with `awscurl` (AOSS uses `--service aoss --region <region>`), e.g. `awscurl --service aoss --region <region> -X POST "<collection-endpoint>/_plugins/_ml/models/_register?deploy=true" -H 'Content-Type: application/json' -d '<body>'`.

## Step 1: Create IAM Role for Bedrock Access

```bash
aws iam create-role --role-name opensearch-bedrock-agent-role \
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

aws iam put-role-policy --role-name opensearch-bedrock-agent-role \
  --policy-name BedrockClaudeInvokePolicy \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"bedrock:InvokeModel","Resource":["arn:aws:bedrock:<region>::foundation-model/<model-id>","arn:aws:bedrock:<region>:<account>:inference-profile/<inference-profile-id>"]}]}'
```

Scope `Resource` to the exact model and inference-profile you call — the same `<model-id>` referenced in the connector `parameters.model` (Step 2). Do NOT use a `foundation-model/*` wildcard, because it grants invoke on every Bedrock model in the region and this example is frequently copy-pasted as-is into production.

## Step 2: Register Model with Inline Connector

Register the model and its connector in one call. The connector `request_body` MUST use the agent-framework template variables (`user_prompt`, `_chat_history`, `_interactions`, `tool_configs`), because the flow agent injects planning context through these variables at query time.

Set `parameters.model` to a model ID you have verified exists, because Bedrock model IDs change as new versions ship and the one shown below may have been superseded. Look up available IDs first with `aws bedrock list-foundation-models` or `aws bedrock list-inference-profiles`, and use the same ID in the IAM policy ARN (Step 1) and the `QueryPlanningTool` model_id (Step 3).

```bash
awscurl --service aoss --region <region> \
  -X POST "<collection-endpoint>/_plugins/_ml/models/_register?deploy=true" \
  -H 'Content-Type: application/json' \
  -d '{
  "name": "agentic search base model",
  "function_name": "remote",
  "connector": {
    "name": "Bedrock Claude Connector",
    "version": 1,
    "protocol": "aws_sigv4",
    "parameters": {
      "region": "<aws_region>",
      "service_name": "bedrock",
      "model": "<model-id>",
      "system_prompt": "You are a search query planning assistant."
    },
    "credential": { "roleArn": "<iam_role_arn>" },
    "actions": [{
      "action_type": "predict",
      "method": "POST",
      "url": "https://bedrock-runtime.${parameters.region}.amazonaws.com/model/${parameters.model}/converse",
      "headers": { "content-type": "application/json" },
      "request_body": "{ \"system\": [{\"text\": \"${parameters.system_prompt}\"}], \"messages\": [${parameters._chat_history:-}{\"role\":\"user\",\"content\":[{\"text\":\"${parameters.user_prompt}\"}]}${parameters._interactions:-}]${parameters.tool_configs:-} }"
    }]
  }
}'
```

Wait until model state is `DEPLOYED` before continuing, because the agent registration in Step 3 references a deployed model.

## Step 3: Create Flow Agent

```bash
awscurl --service aoss --region <region> \
  -X POST "<collection-endpoint>/_plugins/_ml/agents/_register" \
  -H 'Content-Type: application/json' \
  -d '{
  "name": "Agentic Search Agent",
  "type": "flow",
  "description": "Flow agent for natural language search with query planning",
  "tools": [{
    "type": "QueryPlanningTool",
    "description": "A general tool to answer any question",
    "parameters": {
      "model_id": "<model_id>",
      "response_filter": "$.output.message.content[0].text"
    }
  }]
}'
```

- `type` MUST be `flow` (see rationale above).
- Use only `QueryPlanningTool`, because it introspects the index mapping internally and generates the DSL; additional tools are not needed for stateless query translation.
- The model is referenced inside the tool's `parameters` — do NOT add a top-level `llm` block, because flow agents resolve the model through the tool, not an agent-level LLM binding.
- `response_filter` extracts the LLM text from the Bedrock Converse response shape.

## Step 4: Data Access Policy for Pipeline Search (CRITICAL)

The IAM role in the connector's `credential.roleArn` MUST be a principal in the collection's data access policy with all four ResourceTypes — `collection`, `index`, `model`, and `agent`. Pipeline-invoked `agentic` queries fail with `403 Forbidden` without this, because the pipeline uses the connector's IAM role (not the caller's identity) to read mappings, execute the generated DSL, invoke the model, and execute the agent. Direct `_execute` calls can still succeed because they run under the caller's identity, which masks the misconfiguration.

You MUST merge the new `model` and `agent` rules into the **existing** policy rather than replacing it, because `update-access-policy` overwrites the entire policy body and silently drops any rules already present (e.g., the `WriteDocument`/`CreateIndex` grants from provisioning Step 3).

```bash
# 1. Retrieve the current policy and note its policyVersion
aws opensearchserverless get-access-policy --type data \
  --name <collection-name>-data --region <region>
# 2. Copy the existing Rules array from the output, then append the model and
#    agent rules below to it. Use the returned policyVersion in step 3.
```

> **⚠️ Least-privilege NOTE — `aoss:*` on `model`/`agent` is a platform constraint, not a
> discretionary grant.** AOSS does not expose granular data-access actions for the `model` and `agent`
> ResourceTypes, so `aoss:*` is the narrowest functional grant for these two rules — no tighter action
> list exists to substitute. It is broader than least-privilege ideally allows, so treat
> it as a standing gap to tighten, not a permanent target: track it against an open ticket
> (`<tracking-ticket-url>`) and re-check on every AOSS agentic-search version bump and on a recurring
> (quarterly) audit. If AWS exposes granular actions for these ResourceTypes, replace `aoss:*` with
> the specific actions AND narrow the `model/*/*` and `agent/*/*` resources to the specific model and
> agent IDs this collection uses (see the note after the command block). The `collection` and `index`
> rules below are already scoped to minimum actions and should stay that way.

```bash
# 3. Update with the MERGED policy (existing rules + new model/agent rules):
aws opensearchserverless update-access-policy --type data \
  --name <collection-name>-data \
  --policy-version <current-version> \
  --policy '[{
    "Rules":[
      {"Resource":["collection/<collection-name>"],"Permission":["aoss:DescribeCollectionItems"],"ResourceType":"collection"},
      {"Resource":["index/<collection-name>/*"],"Permission":["aoss:DescribeIndex","aoss:ReadDocument"],"ResourceType":"index"},
      {"Resource":["model/*/*"],"Permission":["aoss:*"],"ResourceType":"model"},
      {"Resource":["agent/*/*"],"Permission":["aoss:*"],"ResourceType":"agent"}
    ],
    "Principal":["<caller-principal-arn>","<iam_role_arn>"]
  }]'
```

Notes on this policy:

- **`model` and `agent` MUST use the `*/*` pattern**, not `model/<collection-name>/*` — this matches the guidance in [`provisioning-serverless-provision.md`](provisioning-serverless-provision.md), because ML connectors and agents are registered at the account level rather than scoped under the collection name; using the collection-scoped pattern causes the very `403` this step prevents. As noted in the WARNING above, AOSS exposes no granular data-access actions for the `model`/`agent` resource types, so `aoss:*` is the narrowest functional grant for those two rules — tighten it (both permission and resource) if AWS exposes granular actions; re-check [serverless-data-access.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-data-access.html) on the audit cadence above.
- **Scope `collection` and `index` to the minimum documented actions** (shown above) rather than `aoss:*`, because least-privilege limits blast radius if the connector role is compromised. A read-only agentic index needs only describe/read; add `aoss:WriteDocument` only if the same role also ingests.
- List **both** the caller principal (for manual API calls) and the connector IAM role (for pipeline-invoked calls).
- The connector role must also hold the IAM permissions `aoss:APIAccessAll` (and `aoss:DashboardsAccessAll` for Dashboards) on the collection, because data access policy grants alone are insufficient to reach the data plane.

## Step 5: Create Agentic Search Pipeline

```bash
awscurl --service aoss --region <region> \
  -X PUT "<collection-endpoint>/_search/pipeline/agentic-search-pipeline" \
  -H 'Content-Type: application/json' \
  -d '{
  "request_processors": [{ "agentic_query_translator": { "agent_id": "<agent_id>" } }]
}'
```

The pipeline above is the **secure default**: it plans and executes the query but does NOT surface the generated `dsl_query` or `agent_steps_summary` to callers.

> **Sensitive-data warning:** the `agentic_context` response processor attaches `dsl_query` and `agent_steps_summary` to the response `ext` block, exposing internal index field names, the generated query logic, and potentially sensitive filter values to every caller of the pipeline. Leave it OFF in production. Enable it **only** for an authorized debugging session by adding a `response_processors` block to the pipeline, and remove it afterward:
>
> ```json
> "response_processors": [{ "agentic_context": { "agent_steps_summary": true, "dsl_query": true } }]
> ```
>
> If enabled for debugging, ensure any CloudWatch Logs receiving these responses are encrypted with a customer-managed KMS key and access is restricted to authorized personnel only, because the exposed query logic and field names must not be logged to unencrypted logs.

## Step 6: Test Agentic Search

```bash
awscurl --service aoss --region <region> \
  -X GET "<collection-endpoint>/<index-name>/_search?search_pipeline=agentic-search-pipeline" \
  -H 'Content-Type: application/json' \
  -d '{
  "query": { "agentic": { "query_text": "Find documents about machine learning" } }
}'
```

The response includes search hits. The agent analyzes the question, introspects the index mapping via `QueryPlanningTool`, generates DSL, and executes it. The generated DSL is returned in `ext.dsl_query` only when the `agentic_context` response processor is enabled for debugging (Step 5); with the secure default it is not surfaced to callers.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 Forbidden` on pipeline query, but `_execute` works | Connector IAM role missing from data access policy | Add the role as a principal with all four ResourceTypes (Step 4) |
| Model stuck below `DEPLOYED` | Bedrock region/model unavailable or IAM invoke denied | Verify the model is enabled in the region and the role policy allows `bedrock:InvokeModel` on that model ARN |
| Empty / malformed DSL | `response_filter` does not match the Converse output shape | Confirm `response_filter` is `$.output.message.content[0].text` |

## Security Considerations

- **Audit logging:** Enable AWS CloudTrail so that `_plugins/_ml` model/agent registration and agentic search API calls are recorded — this attributes who created connectors/agents and who ran queries.
- **Anomaly monitoring:** Set CloudWatch alarms on the collection's `4xx`/`5xx` error rates and on unusual agentic query volume, because a spike can indicate a misconfigured or abused pipeline.
- **Encryption at rest:** AOSS encrypts all data at rest by default (AWS-owned key). For compliance workloads, use a customer-managed KMS key on the encryption policy — see [`provisioning-serverless-provision.md`](provisioning-serverless-provision.md).
- **Bedrock role hygiene:** Review the `opensearch-bedrock-agent-role` trust policy and attached permissions on a regular cadence, and keep the `bedrock:InvokeModel` resource scoped to the specific model ARN (Step 1), because a broad role is a standing invoke path into every model in the region.
- **Sensitive-field exposure:** The LLM generates DSL from natural language and can surface any field in the index. If the index contains PII or other sensitive fields, apply field-level access control or a response filter, because an unconstrained query planner may return fields the caller should not see.
- **Encryption in transit:** AOSS enforces HTTPS-only access to the data plane. Verify the collection endpoint starts with `https://` before issuing any query or index call, because an unencrypted request would expose the query and results in transit.
- **Input validation & rate limiting:** `query_text` is arbitrary natural language passed to an LLM that generates executable DSL. Apply input validation (length limits, disallowed patterns) to mitigate prompt injection, and throttle/rate-limit the pipeline endpoint, because crafted prompts can manipulate DSL generation and high volume drives runaway Bedrock invocation cost.
- **AWS WAF (defense in depth):** if the endpoint is reachable from outside a trusted VPC, front it with AWS WAF using request-size limits and rate-based rules, because WAF blocks oversized/known-malicious requests at the edge before they reach the LLM query planner.
