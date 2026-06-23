# Amazon OpenSearch Service Domain — Agentic Search Setup

Configure conversational agents with QueryPlanningTool for natural language search. Requires OpenSearch 3.3+ on a managed AOS domain. Uses Bedrock Claude as reasoning model.

## Step 1: Create IAM Role for Bedrock Access

```bash
# Service principal: opensearchservice.amazonaws.com (AOS managed domains with agentic search)
# Both aws:SourceAccount and aws:SourceArn conditions are required to prevent
# confused-deputy: without aws:SourceArn, any OpenSearch domain in the same
# account could assume this role; ArnLike narrows trust to a specific domain.
aws iam create-role --role-name opensearch-bedrock-agent-role \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Principal":{"Service":"opensearchservice.amazonaws.com"},
      "Action":"sts:AssumeRole",
      "Condition":{
        "StringEquals":{"aws:SourceAccount":"<account>"},
        "ArnLike":     {"aws:SourceArn":    "arn:aws:es:<region>:<account>:domain/<domain-name>"}
      }
    }]
  }'

aws iam put-role-policy --role-name opensearch-bedrock-agent-role \
  --policy-name BedrockClaudeInvokePolicy \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"arn:aws:bedrock:<region>::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0"}]}'
```

## Step 2: Map ML Role

If fine-grained access control is enabled, map your IAM role to the `ml_full_access` role:

```
PUT <domain-endpoint>/_plugins/_security/api/rolesmapping/ml_full_access
{
  "backend_roles": ["<iam_role_arn>"]
}
```

## Step 3: Create Bedrock Claude Connector

```
POST <domain-endpoint>/_plugins/_ml/connectors/_create
{
  "name": "Amazon Bedrock Claude 3.5 Sonnet",
  "version": 1,
  "protocol": "aws_sigv4",
  "credential": { "roleArn": "<iam_role_arn>" },
  "parameters": {
    "region": "<aws_region>",
    "service_name": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "system_prompt": "You are a helpful assistant that plans and executes search queries.",
    "temperature": 0.0,
    "top_p": 0.9,
    "max_tokens": 2000
  },
  "actions": [{
    "action_type": "predict",
    "method": "POST",
    "headers": { "content-type": "application/json" },
    "url": "https://bedrock-runtime.${parameters.region}.amazonaws.com/model/${parameters.model}/converse",
    "request_body": "{ \"system\": [{\"text\": \"${parameters.system_prompt}\"}], \"messages\": ${parameters.messages}, \"inferenceConfig\": {\"temperature\": ${parameters.temperature}, \"topP\": ${parameters.top_p}, \"maxTokens\": ${parameters.max_tokens}} }"
  }]
}
```

## Step 4: Register and Deploy Model

```
POST <domain-endpoint>/_plugins/_ml/models/_register?deploy=true
{
  "name": "Bedrock Claude 3.5 Sonnet for Agentic Search",
  "function_name": "remote",
  "connector_id": "<connector_id>"
}
```

Test:

```
POST <domain-endpoint>/_plugins/_ml/models/<model-id>/_predict
{ "parameters": { "messages": [{ "role": "user", "content": [{ "text": "hello" }] }] } }
```

## Step 5: Create Conversational Agent

```
POST <domain-endpoint>/_plugins/_ml/agents/_register
{
  "name": "Agentic Search Agent",
  "type": "conversational",
  "llm": { "model_id": "<model_id>", "parameters": { "max_iteration": 15 } },
  "memory": { "type": "conversation_index" },
  "parameters": { "_llm_interface": "bedrock/converse" },
  "tools": [{ "type": "QueryPlanningTool" }],
  "app_type": "os_chat"
}
```

## Step 6: Create Agentic Search Pipeline

```
PUT <domain-endpoint>/_search/pipeline/agentic-search-pipeline
{
  "request_processors": [{ "agentic_query_translator": { "agent_id": "<agent_id>" } }]
}
```

## Step 7: Test Agentic Search

```
GET <domain-endpoint>/<index-name>/_search?search_pipeline=agentic-search-pipeline
{
  "query": {
    "agentic": {
      "query_text": "Find all documents about machine learning published in the last year",
      "query_fields": ["title", "content", "publish_date"]
    }
  }
}
```

The agent analyzes the natural language question, examines index mappings, generates OpenSearch DSL, and returns results.
