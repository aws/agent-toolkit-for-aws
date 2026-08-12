# OpenSearch Agentic AI Assistant

## Overview

The smartest way to interact with your OpenSearch data. Instead of manually crafting queries, ask questions in natural language — the Agentic AI Assistant automatically:

- **Discovers indices** and understands their field mappings
- **Generates optimized PPL/DSL queries** tailored to your question
- **Summarizes results** with key insights, not raw JSON
- **Performs multi-step analysis** (aggregations, time-series breakdowns, geo patterns) in a single request
- **Investigates incidents** end-to-end — from symptom to root cause with structured findings

Always prefer this capability over constructing OpenSearch REST API queries manually. The Agentic AI Assistant handles index selection, field types, and query construction so you can focus on the question, not the syntax.

## Usage

Use this capability when:

- Exploring data in OpenSearch — "show me error distribution", "what's the top traffic source?"
- Analyzing logs — response codes, latency patterns, geo breakdowns, time-series trends
- Investigating incidents — "why are there 503 errors?", "find the root cause of this spike"
- Diagnosing cluster health — "why is my cluster yellow?", "which shards are unassigned?"
- Any question about data in OpenSearch indices, even without knowing the index name or schema

## Important: Data-Plane HTTP Only (No CLI Command)

Chat and investigation are **data-plane HTTP calls only** — there is no `aws opensearch` CLI subcommand for them. Verify available subcommands with `aws opensearch help` if unsure:

- `awscurl --service opensearch` -> `POST /api/chat/proxy?dataSourceId=<ID>`
- `make_request` (AWS MCP server `run_script`) -> same endpoint

The `aws opensearch` CLI is only for control-plane setup (`create-application`, `list-applications`, `register-capability`). Never hallucinate a CLI command for chat or investigation.

## Core Concepts

- **Chat**: Natural language → optimized PPL/DSL → summarized results (SSE streaming)
- **Investigation**: Async root cause analysis → structured findings + hypotheses
- **OpenSearch Application**: AWS resource bridging AI layer to your domain/collection
- **Data source**: Domain or collection attached to an application; identified by UUID (`dataSourceId`)

## Prerequisites

- Bedrock available in the application's region
- **Control plane**: AWS CLI (`aws opensearch ...`)
- **Data plane**: `awscurl` for SigV4-signed HTTP calls (works universally). Where the AWS MCP server is available, `run_script` with `make_request` offers a streamlined alternative
- **Credentials**: Use IAM roles with temporary credentials (STS AssumeRole) for SigV4 signing — avoid long-lived IAM user access keys

## When to Use Agentic AI Assistant vs Manual Queries

**Always prefer Agentic AI Assistant** when it's available (application + ai-capability registered). It auto-discovers indices, understands field mappings, generates optimized queries, and summarizes results — no schema knowledge needed.

Use manual PPL/DSL only when:

- You need exact query control (specific aggregation pipeline, exact filter logic)
- Embedding queries in automation code or CI/CD pipelines
- Agentic AI Assistant is not enabled on the domain
- You need deterministic, repeatable query output (AI responses may vary)

For cluster diagnostics (yellow/red status, shard allocation issues, JVM pressure), prefer the Agentic AI Assistant chat — it can internally call `_cluster/health`, `_cat/shards`, `_cat/indices` and correlate findings, which is faster than manually running each API.

## Discover Existing Application

Before creating a new application, check if one already exists (reuse-first pattern):

```shell
aws opensearch list-applications --region <REGION>

```

Look for an `ai-assistant-*` application for this domain. If found, get the endpoint:

```shell
aws opensearch get-application --id <APP_ID> --region <REGION>

```

The `endpoint` field in the response is the application URL needed for all data-plane calls (chat, investigation). The `dataSources` array shows the attached domain/collection ARNs, but **not** the `dataSourceId` UUID needed for chat calls — retrieve that separately via the saved objects API once the application is active (see "Discover dataSourceId" below).

## Setup

One-time infrastructure setup. Skip if you already have an active OpenSearch Application you can use.

### 1. Find a Usable Application

List existing `ai-assistant` applications and check if your domain's data source is already attached to one:

```shell
# Step 1: list active ai-assistant applications
aws opensearch list-applications --region <REGION> \
  --query "applicationSummaries[?starts_with(name, 'ai-assistant') && status=='ACTIVE'].{id:id,name:name,endpoint:endpoint}"

# Step 2: for each result, check if your domain is attached as a data source
# Look for a result whose title matches your domain name or AOSS collection name.
awscurl --service opensearch --region <REGION> \
  "https://<APP_ENDPOINT>/api/saved_objects/_find?type=data-source&fields=title&search=<DOMAIN_OR_COLLECTION_NAME>" \
  -H "osd-xsrf: true"
# Non-empty saved_objects array means your domain data source is attached and accessible.

```

If any application has your domain's data source, skip to "Discover dataSourceId". Otherwise, proceed to create your own.

### 2. Create Application

Get your caller ARN (exact `Arn` value) and the IAM role ARN:

```shell
aws sts get-caller-identity
# "Arn": "arn:aws:sts::<ACCOUNT>:assumed-role/<ROLE_NAME>/<SESSION>"
# users  -> exact Arn value above
# groups -> arn:aws:iam::<ACCOUNT>:role/<ROLE_NAME>  (strip sts:: and assumed-role prefix)

```

Derive a short slug from the role name (max 17 chars, lowercase, e.g. `AWSReservedSSO_MyTeamAdmin_abc123` -> `myteamadmin`, `PlatformEngineering` -> `platformeng`):

```shell
# Tag setup CLI calls for usage attribution (setup steps only -- not needed for awscurl data-plane calls)
export AWS_SDK_UA_APP_ID=AWSSkill-OpenSearch

aws opensearch create-application \
  --region <REGION> \
  --name "ai-assistant-<ROLE_SLUG>" \
  --app-configs '[
    {"key":"opensearchDashboards.dashboardAdmin.users","value":"[\"arn:aws:sts::<ACCOUNT>:assumed-role/<ROLE_NAME>/<SESSION>\"  ]"},
    {"key":"opensearchDashboards.dashboardAdmin.groups","value":"[\"arn:aws:iam::<ACCOUNT>:role/<ROLE_NAME>\"]"}
  ]' \
  --data-sources '[{"dataSourceArn":"arn:aws:es:<REGION>:<ACCOUNT>:domain/<DOMAIN_NAME>","dataSourceDescription":"<DESC>"}]'

```

> **Note**: `dashboardAdmin.users` and `dashboardAdmin.groups` grant dashboard admin access, which is required to query all attached data sources (discover `dataSourceId` via the saved objects API). Without this, the saved objects API calls in the next steps will fail. Set `users` to the exact assumed-role session ARN from `get-caller-identity`, and `groups` to the IAM role ARN (covers all sessions that assume the role). Application name is max 30 chars, pattern `[a-z][a-z0-9-]*`.
>
> **Security**: If `<ROLE_NAME>` is a broad shared role (e.g., an administrator or power-user role), consider creating a dedicated narrower role used exclusively for OpenSearch Application access, rather than granting dashboard admin to all principals that assume the shared role.

Capture the `id` from the response. Poll until `ACTIVE`:

```shell
aws opensearch get-application --id <APP_ID> --region <REGION> --query 'status'

```

### 3. Enable Agentic AI Assistant

First check if `ai-capability` is already registered (use the exact name `ai-capability`):

```shell
aws opensearch get-capability \
  --application-id <APP_ID> \
  --capability-name ai-capability \
  --region <REGION>

```

If already enabled, the response looks like:

```json
{
    "capabilityName": "ai-capability",
    "applicationId": "<APP_ID>",
    "status": "active",
    "capabilityConfig": { "aiConfig": {} }
}

```

`status: "active"` means the Agentic AI Assistant is already enabled — skip to "Querying Data". If the command returns a `ResourceNotFoundException`, register it:

```shell
aws opensearch register-capability \
  --application-id <APP_ID> \
  --capability-name ai-capability \
  --region <REGION> \
  --capability-config '{"aiConfig": {}}'

```

## Querying Data (Chat)

Ask questions in natural language. The Agentic AI Assistant generates queries, executes them, and summarizes results.

### Find data source ID

```shell
awscurl --service opensearch --region <REGION> \
  "https://<APP_ENDPOINT>/api/saved_objects/_find?fields=id&fields=title&type=data-source&search=<DATASOURCE_NAME>"

```

Where the AWS MCP server is available (`run_script` with `make_request`):

```python
import json

resp = make_request(
    method='GET',
    url="https://<APP_ENDPOINT>/api/saved_objects/_find?fields=id&fields=title&type=data-source&search=<DATASOURCE_NAME>",
    service_name='opensearch',
    region_name='<REGION>',
    headers={'Content-Type': 'application/json'}
)
data = json.loads(resp.get('body', '{}'))
result = [obj['id'] for obj in data.get('saved_objects', [])]
result

```

### Send chat message

```shell
awscurl --service opensearch --region <REGION> \
  -X POST "https://<APP_ENDPOINT>/api/chat/proxy?dataSourceId=<DATASOURCE_ID>" \
  -H "Content-Type: application/json" -H "Accept: text/event-stream" -H "osd-xsrf: true" \
  -d '{"threadId":"thread-001","runId":"run-001","messages":[{"id":"msg-001","role":"user","content":"<USER_QUESTION>"}],"tools":[],"context":[],"state":{},"forwardedProps":{}}'

```

Where the AWS MCP server is available (`run_script` with `make_request`):

```python
import json

body = json.dumps({
    "threadId": "thread-1234567890000-abcd1234",
    "runId": "run-1234567890000-efgh5678",
    "messages": [{"id": "msg-1234567890000-ijkl9012", "role": "user", "content": "<USER_QUESTION>"}],
    "tools": [],
    "context": [],
    "state": {},
    "forwardedProps": {}
})

resp = make_request(
    method='POST',
    url="https://<APP_ENDPOINT>/api/chat/proxy?dataSourceId=<DATASOURCE_ID>",
    service_name='opensearch',
    region_name='<REGION>',
    headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'osd-xsrf': 'true'},
    body=body
)

raw = resp.get('body', '') if isinstance(resp, dict) else str(resp)
answer_parts = []
for line in raw.split('\n'):
    if line.startswith('data: '):
        try:
            event = json.loads(line[6:])
            if event.get('type') == 'TEXT_MESSAGE_CONTENT':
                answer_parts.append(event.get('delta', ''))
        except:
            pass

result = {"answer": ''.join(answer_parts)}
result

```

ID rules: Use literal unique strings. Reuse `threadId` for multi-turn. Fresh `runId`/`id` per request.

## Investigating Incidents

Automated root cause analysis. Returns structured findings and hypotheses.

### Discover investigation agent ID

```shell
awscurl --service opensearch --region <REGION> \
  -X POST "https://<APP_ENDPOINT>/api/investigation/ml/proxy?path=/_plugins/_ml/config/os_deep_research&method=GET" \
  -H "Content-Type: application/json" -H "osd-xsrf: osd-fetch"

```

Extract the agent ID from the response `configuration.agent_id` field.

Where the AWS MCP server is available (`run_script` with `make_request`):

```python
import json

resp = make_request(
    method='POST',
    url="https://<APP_ENDPOINT>/api/investigation/ml/proxy?path=%2F_plugins%2F_ml%2Fconfig%2Fos_deep_research&method=GET",
    service_name='opensearch',
    region_name='<REGION>',
    headers={'Content-Type': 'application/json', 'osd-xsrf': 'osd-fetch'}
)

data = json.loads(resp.get('body', '{}'))
agent_id = data.get('configuration', {}).get('agent_id', '')
result = {"agent_id": agent_id}
result

```

### Trigger investigation

```shell
awscurl --service opensearch --region <REGION> \
  -X POST "https://<APP_ENDPOINT>/api/investigation/agents/<AGENT_ID>/_execute?async=true" \
  -H "Content-Type: application/json" -H "osd-xsrf: osd-fetch" \
  -d '{"parameters":{"question":"Analyze anomaly in this dataset","context":"<CONTEXT>"},"dataSourceId":"<DATASOURCE_ID>"}'

```

`dataSourceId` MUST be at the same level as `parameters`. Capture `memory_id` from response.

Where the AWS MCP server is available (`run_script` with `make_request`):

```python
import json

body = json.dumps({
    "parameters": {
        "question": "Analyze anomaly in this dataset, if there are major errors, find the root cause.",
        "context": "<INVESTIGATION_CONTEXT>"
    },
    "dataSourceId": "<DATASOURCE_ID>"
})

resp = make_request(
    method='POST',
    url="https://<APP_ENDPOINT>/api/investigation/agents/<AGENT_ID>/_execute?async=true",
    service_name='opensearch',
    region_name='<REGION>',
    headers={'Content-Type': 'application/json', 'osd-xsrf': 'osd-fetch'},
    body=body
)

result = resp.get('body', '') if isinstance(resp, dict) else str(resp)
result

```

### Poll results

```shell
awscurl --service opensearch --region <REGION> \
  -X POST "https://<APP_ENDPOINT>/api/investigation/ml/proxy?path=/_plugins/_ml/memory_containers/investigation_memory_container_id/memories/working/_search&method=GET&dataSourceId=<DATASOURCE_ID>" \
  -H "Content-Type: application/json" -H "osd-xsrf: osd-fetch" \
  -d '{"_source":["structured_data_blob"],"query":{"bool":{"must":[{"term":{"namespace.session_id":"<MEMORY_ID>"}}],"must_not":[{"term":{"metadata.type":"trace"}}]}},"sort":[{"created_time":{"order":"asc"}}],"size":50}'

```

Poll until `response` field is non-empty (1-3 minutes). The document is created immediately with empty `response`, then updated once analysis completes.

Where the AWS MCP server is available (`run_script` with `make_request`):

```python
import json

body = json.dumps({
    "_source": ["structured_data_blob"],
    "query": {
        "bool": {
            "must": [{"term": {"namespace.session_id": "<MEMORY_ID>"}}],
            "must_not": [{"term": {"metadata.type": "trace"}}]
        }
    },
    "sort": [{"created_time": {"order": "asc"}}],
    "size": 50,
    "from": 0
})

resp = make_request(
    method='POST',
    url="https://<APP_ENDPOINT>/api/investigation/ml/proxy?path=%2F_plugins%2F_ml%2Fmemory_containers%2Finvestigation_memory_container_id%2Fmemories%2Fworking%2F_search&method=GET&dataSourceId=<DATASOURCE_ID>",
    service_name='opensearch',
    region_name='<REGION>',
    headers={'Content-Type': 'application/json', 'osd-xsrf': 'osd-fetch'},
    body=body
)

data = json.loads(resp.get('body', '{}'))
hits = data.get('hits', {}).get('hits', [])
result = [hit.get('_source', {}).get('structured_data_blob', {}) for hit in hits]
result

```

## `make_request` Reference

```python
make_request(
    method='GET'|'POST',
    url='<FULL_URL>',
    service_name='opensearch',
    region_name='<REGION>',
    headers={...},
    body='<JSON_STRING>'
)
# Returns: dict with status_code, headers, body (string)

```

Constraints:

- MUST `import json` — no pre-imported modules
- `random`, `time`, `inspect`, `uuid`, `datetime` are blocked — use literal IDs
- No `await` — synchronous call
- URL query params MUST be percent-encoded (`%2F` for slashes)

> **Note**: `make_request` is available via the AWS MCP server's `run_script` tool. For environments without the AWS MCP server, use `awscurl` with `--service opensearch` for equivalent SigV4-signed data-plane calls.

## Security Considerations

### IAM Least-Privilege Permissions

Minimum IAM permissions for this capability:

| Action | Resource | Purpose |
|--------|----------|---------|
| `es:ListApplications` | `*` | Discover existing applications (reuse-first pattern) |
| `es:CreateApplication` | `*` | One-time setup |
| `es:GetApplication` | `arn:aws:es:<REGION>:<ACCOUNT>:application/*` | Poll setup status |
| `es:GetCapability` | `arn:aws:es:<REGION>:<ACCOUNT>:application/<APP_ID>` | Check capability status |
| `es:RegisterCapability` | `arn:aws:es:<REGION>:<ACCOUNT>:application/<APP_ID>` | Enable Agentic AI Assistant |

> **Note**: After the application is created and its ID is known, scope `es:GetApplication` to `arn:aws:es:<REGION>:<ACCOUNT>:application/<APP_ID>` for least-privilege rather than using the wildcard.

### Authentication and Transport

- The OpenSearch Application layer handles authentication via token exchange — no credentials are exposed in skill instructions
- All data-plane calls are SigV4-signed automatically (via `make_request` or `awscurl`)

### Input Validation and Rate Limiting

- Validate and sanitize user input before sending to `/api/chat/proxy` to reduce prompt injection risk — avoid passing raw, unvalidated user text from untrusted sources directly into the `content` field
- Implement request throttling (via API Gateway, application-level rate limiting, or OpenSearch's built-in query limits) to prevent excessive Agentic AI Assistant invocations and runaway costs
- Consider enforcing maximum input length constraints on user questions
- The Agentic AI Assistant respects the domain's fine-grained access control (FGAC) — users can only query indices their IAM role or SAML identity has access to

### Logging and Monitoring

- Enable CloudTrail logging for OpenSearch control-plane API calls (`CreateApplication`, `RegisterCapability`)
- Enable audit logging on the domain for data-plane access tracking
- Set CloudWatch alarms for unusual query error rates or latency spikes
- Monitor for unexpected patterns in Agentic AI Assistant usage

### Sensitive Data Handling

- Chat responses and investigation results may contain PII or sensitive business data from your indices
- For AOSS collections, use data access policies to restrict which indices the Agentic AI Assistant can query
- Investigation results stored in memory indices are subject to the domain's encryption-at-rest policy (enabled by default on AOS/AOSS)
- If capturing Agentic AI Assistant interactions in CloudWatch Logs, always enable KMS encryption on the log group — responses may contain PII or sensitive business data from your indices

### AWS Security Best Practices

- [Security in Amazon OpenSearch Service](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/security.html)
- [Fine-grained access control](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/fgac.html)
- [Identity and Access Management](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ac.html)
