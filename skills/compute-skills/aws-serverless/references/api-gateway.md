# API Gateway Reference

Quick-reference for REST API, HTTP API, WebSocket API — debugging, configuration, and quotas.

## Contents

- [REST vs HTTP API Comparison](#rest-vs-http-api-comparison)
- [CORS Debugging](#cors-debugging)
- [Lambda Authorizers](#lambda-authorizers)
- [Throttling and Quotas](#throttling-and-quotas)
- [WebSocket APIs](#websocket-apis)
- [502/504 Debugging](#502504-debugging)

---

## REST vs HTTP API Comparison

### Decision Tree

```
Need any of these? → REST API
  ├── API keys / usage plans / per-client throttling
  ├── Request validation (built-in)
  ├── Request/response body transformation (VTL)
  ├── Caching (built-in)
  ├── Private API endpoints
  ├── Edge-optimized endpoints
  ├── Canary deployments
  ├── Execution logs / X-Ray tracing
  ├── Resource policies
  ├── Mock integrations
  └── Response streaming

None of the above? → HTTP API (lower latency, simpler)
```

### Feature Comparison

| Feature | REST API | HTTP API |
|---|---|---|
| **Latency** | Higher | Lower |
| **Endpoint types** | Edge, Regional, Private | Regional only |
| **AWS WAF** | Yes | No |
| **API keys / usage plans** | Yes | No |
| **Per-client throttling** | Yes | No |
| **Request validation** | Yes | No |
| **Body transformation (VTL)** | Yes | No |
| **Parameter mapping** | Yes | Yes |
| **Caching (built-in)** | Yes | No |
| **Custom domains** | Yes | Yes |
| **Lambda authorizers** | Yes (TOKEN + REQUEST) | Yes (REQUEST only) |
| **JWT authorizers (native)** | No | Yes |
| **IAM auth** | Yes | Yes |
| **Cognito (native)** | Yes | Yes (via JWT) |
| **Resource policies** | Yes | No |
| **Mutual TLS** | Yes | Yes |
| **CORS setup** | Manual OPTIONS method | Built-in config |
| **Automatic deployments** | No | Yes |
| **Canary deployments** | Yes | No |
| **Custom gateway responses** | Yes | No |
| **Execution logs** | Yes | No |
| **Access logs (CloudWatch)** | Yes | Yes |
| **Access logs (Firehose)** | Yes | No |
| **X-Ray tracing** | Yes | No |
| **Mock integrations** | Yes | No |
| **Private integrations (NLB)** | Yes | Yes |
| **Private integrations (ALB)** | Yes | Yes |
| **Private integrations (Cloud Map)** | No | Yes |
| **Response streaming** | Yes | No |
| **Console test invocations** | Yes | No |
| **Integration timeout** | 50ms–29s (configurable) | 30s hard max |
| **Payload size** | 10 MB | 10 MB |

> **REST API streaming caveats:** Response streaming via REST API proxy integration does not support built-in caching, response transforms (VTL), or WAF inspection of streamed content. Idle timeouts apply, and a 2 MBps bandwidth cap applies after the first 10 MB (Function URLs apply the cap after 6 MB).

---

## CORS Debugging

### Proxy vs Non-Proxy

| Aspect | Proxy integration | Non-proxy integration |
|---|---|---|
| Who returns CORS headers? | **Your Lambda function** | **API Gateway** (method response) |
| OPTIONS method needed? | Yes (or use mock) | Yes (mock integration) |
| Where to configure? | In your code | In API Gateway console/IaC |

### Debugging Flowchart

```
"Cross-Origin Request Blocked"?
│
├─ YES → Which integration type?
│  │
│  ├─ PROXY → Lambda MUST return CORS headers
│  │  ├─ Access-Control-Allow-Origin
│  │  ├─ Access-Control-Allow-Methods
│  │  └─ Access-Control-Allow-Headers
│  │
│  └─ NON-PROXY → Configure in API Gateway:
│     ├─ Create OPTIONS method (mock integration)
│     ├─ Add 200 response with CORS headers
│     └─ Add CORS headers to actual method responses
│
├─ OPTIONS returning 200?
│  ├─ NO  → OPTIONS method missing or misconfigured
│  └─ YES → Check actual method response headers
│
└─ 502 on OPTIONS?
   └─ Binary media types set to */* → fix below
```

### Common CORS Mistakes

| # | Mistake | Fix |
|---|---|---|
| 1 | No CORS headers in Lambda (proxy integration) | Add headers to every Lambda response |
| 2 | Missing OPTIONS method (REST API, non-proxy) | Create OPTIONS with mock integration |
| 3 | Binary media types `*/*` breaks OPTIONS | Set `contentHandling: CONVERT_TO_TEXT` on OPTIONS |
| 4 | `Allow-Origin: *` with `credentials: include` | Specify exact origin, not wildcard |
| 5 | Not redeploying API after CORS changes | Redeploy the stage |
| 6 | Missing `Allow-Headers` for custom headers | List all headers the client sends |
| 7 | Gateway 4XX/5XX responses lack CORS headers | Add CORS headers to gateway responses |

### Lambda CORS Headers — Python

```python
def handler(event, context):
    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "https://example.com",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET,PUT,DELETE",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
        },
        "body": json.dumps({"message": "success"}),
    }
```

### Lambda CORS Headers — TypeScript

```typescript
export const handler = async (event: any) => ({
  statusCode: 200,
  headers: {
    "Access-Control-Allow-Origin": "https://example.com",
    "Access-Control-Allow-Methods": "OPTIONS,POST,GET,PUT,DELETE",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
  },
  body: JSON.stringify({ message: "success" }),
});
```

### Binary Media Types `*/*` Fix

```bash
# Fix OPTIONS integration request
aws apigateway update-integration \
  --rest-api-id API_ID --resource-id RES_ID \
  --http-method OPTIONS \
  --patch-operations op='replace',path='/contentHandling',value='CONVERT_TO_TEXT'

# Fix OPTIONS integration response
aws apigateway update-integration-response \
  --rest-api-id API_ID --resource-id RES_ID \
  --http-method OPTIONS --status-code 200 \
  --patch-operations op='replace',path='/contentHandling',value='CONVERT_TO_TEXT'
```

---

## Lambda Authorizers

### TOKEN vs REQUEST Authorizer

| Feature | TOKEN | REQUEST |
|---|---|---|
| Identity source | Single header (bearer token) | Headers, query strings, stage vars, `$context` |
| Cache key | Token header value | All specified identity sources |
| Token validation regex | Yes | No |
| Fine-grained policies | Limited | Yes (multiple sources) |
| Available on | REST API only | REST API + HTTP API |
| **Recommendation** | Legacy | **Preferred** |

> **Use REQUEST authorizers for new APIs.** TOKEN is legacy.

### Caching Behavior

| Setting | Detail |
|---|---|
| Default TTL | 300 seconds |
| Range | 0 (disabled) – 3600 seconds |
| Cache key (TOKEN) | Header value from token source |
| Cache key (REQUEST) | All specified identity sources combined |
| **Critical** | Cached policy applies to **ALL methods/resources** |

If any specified identity source is missing/null/empty → 401 returned **without** invoking Lambda.

### REQUEST Authorizer — Python

```python
def lambda_handler(event, context):
    token = event["headers"].get("Authorization", "")
    is_authorized = verify_token(token)  # Your auth logic

    return {
        "principalId": "user",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": "Allow" if is_authorized else "Deny",
                "Resource": event["methodArn"],
            }],
        },
        "context": {"userId": "user", "scope": "read:items"},
    }
```

### REQUEST Authorizer — TypeScript

```typescript
import { APIGatewayAuthorizerResult, APIGatewayRequestAuthorizerEvent } from "aws-lambda";

export const handler = async (
  event: APIGatewayRequestAuthorizerEvent
): Promise<APIGatewayAuthorizerResult> => {
  const token = event.headers?.Authorization ?? "";
  const isAuthorized = verifyToken(token); // Your auth logic

  return {
    principalId: "user",
    policyDocument: {
      Version: "2012-10-17",
      Statement: [{
        Action: "execute-api:Invoke",
        Effect: isAuthorized ? "Allow" : "Deny",
        Resource: event.methodArn,
      }],
    },
    context: { userId: "user", scope: "read:items" },
  };
};
```

### HTTP API JWT Authorizer (Native — No Lambda)

No Lambda function needed. Configure directly on the API:

```yaml
# SAM / CloudFormation
MyHttpApi:
  Type: AWS::Serverless::HttpApi
  Properties:
    Auth:
      DefaultAuthorizer: MyJwtAuth
      Authorizers:
        MyJwtAuth:
          AuthorizationScopes:
            - read:items
          IdentitySource: $request.header.Authorization
          JwtConfiguration:
            issuer: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123
            audience:
              - my-client-id
```

Supports any OIDC-compliant IdP (Cognito, Auth0, Okta, etc.).

---

## Throttling and Quotas

### Throttling Hierarchy (Applied in Order)

```
Most specific → Least specific:

1. Per-client / per-method  (usage plan + API key)   ← REST only
2. Per-method               (stage method settings)
3. Account-level            (all APIs in account/Region)
4. AWS Regional             (hard limit, not changeable)
```

### Token Bucket Algorithm

- Tokens added at steady-state rate (RPS)
- Bucket holds up to burst capacity
- Each request = 1 token
- Empty bucket → `429 Too Many Requests`
- Burst allows temporary spikes above steady-state

### Account-Level Defaults

| Quota | Default | Adjustable? |
|---|---|---|
| Steady-state RPS (per Region) | 10,000 | Yes |
| Burst capacity | 5,000 | Set by AWS based on RPS |
| Smaller Regions (Cape Town, Milan, Jakarta…) | 2,500 RPS / 1,250 burst | Yes |

### REST API Quotas

| Resource | Default | Adjustable? |
|---|---|---|
| Integration timeout | 50ms–29s (default 29s) | Yes (Regional/private only) |
| Payload size | 10 MB | No |
| Header value size | 10,240 bytes | No |
| Cache TTL | 0–3600s | No |
| Resources per API | 300 | Yes |
| Stages per API | 10 | Yes |
| API keys per account | 10,000 | No |
| Usage plans per account | 300 | Yes |
| Custom domains per Region | 120 | Yes |
| Mapping template size | 300 KB | No |

### HTTP API Quotas

| Resource | Default | Adjustable? |
|---|---|---|
| Integration timeout | 30s max | No |
| Payload size | 10 MB | No |
| Routes per API | 300 | Yes |
| Stages per API | 10 | Yes |
| Integrations per API | 300 | No |
| Custom domains per Region | 120 | Yes |
| VPC links per Region | 10 | Yes |

### Usage Plans (REST API Only)

- Per-client rate limits (RPS) and burst limits via API keys
- Daily/weekly/monthly quotas per key
- Method-level throttling within a plan (e.g., `GET /pets` = 100 RPS)

### Client-Side 429 Handling

- Exponential backoff with jitter
- Respect `Retry-After` header
- Client-side rate limiting to stay under known limits

---

## WebSocket APIs

### Route Architecture

```
Client connects    → $connect    (auth, store connectionId)
Client sends msg   → route selection → custom route or $default
Server pushes data → @connections API (POST to connectionId)
Client disconnects → $disconnect (cleanup connectionId)
```

### Route Selection

- Expression: `$request.body.action` (routes on JSON `action` field)
- Non-JSON messages → always `$default`

### Predefined Routes

| Route | When | Required? | Notes |
|---|---|---|---|
| `$connect` | Connection initiated | No | Auth here; connection pending until integration completes |
| `$disconnect` | Connection closed | No | Best-effort; connection already closed |
| `$default` | No matching route / non-JSON | No | Catch-all fallback |

### Connection Management — Python

```python
import boto3, json

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("WebSocketConnections")

def connect_handler(event, context):
    table.put_item(Item={"connectionId": event["requestContext"]["connectionId"]})
    return {"statusCode": 200, "body": "Connected"}

def send_to_client(endpoint_url, connection_id, data):
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)
    client.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps(data).encode("utf-8"),
    )
```

### Connection Management — TypeScript

```typescript
import { ApiGatewayManagementApiClient, PostToConnectionCommand } from "@aws-sdk/client-apigatewaymanagementapi";

async function sendToClient(endpoint: string, connectionId: string, data: object) {
  const client = new ApiGatewayManagementApiClient({ endpoint });
  await client.send(new PostToConnectionCommand({
    ConnectionId: connectionId,
    Data: Buffer.from(JSON.stringify(data)),
  }));
}
```

### WebSocket Quotas

| Resource | Limit |
|---|---|
| Idle connection timeout | 10 minutes |
| Max connection duration | 2 hours |
| Message payload | 128 KB (hard limit) |

### WebSocket Close Codes

| Code | Meaning |
|---|---|
| 1001 | Idle timeout or max duration exceeded |
| 1003 | Unsupported binary media type |
| 1005 | No status code present (reserved, not sent on wire) |
| 1006 | Abnormal closure — no close frame received |
| 1008 | Throttled (too many requests) |
| 1009 | Message exceeds size limit |
| 1011 | Internal server error |
| 1012 | Service restart |

---

## 502/504 Debugging

### 502 Bad Gateway — Flowchart

```
502 Bad Gateway
│
├─ Lambda proxy integration?
│  └─ YES → Check response format (most common cause):
│     ├─ statusCode: integer (string is coerced, missing defaults to 200)
│     ├─ headers: object with string values
│     ├─ body: string (JSON.stringify, not raw object)
│     └─ Unhandled exception? → Check CloudWatch Logs
│
├─ Lambda authorizer?
│  ├─ Must return valid IAM policy format
│  ├─ Check authorizer Lambda logs
│  └─ Authorizer timeout is separate from integration timeout
│
├─ HTTP integration?
│  ├─ Backend reachable from API Gateway?
│  ├─ Valid HTTP response from backend?
│  └─ VPC link healthy? (private integration)
│
└─ Other causes:
   ├─ Payload > 10 MB
   ├─ Binary media types */* (breaks OPTIONS)
   └─ Stage variable → wrong Lambda alias
```

### Correct Lambda Response Format

The **most common cause of 502** is an incorrect response format in Lambda proxy integrations.

**Python — Correct:**

```python
def handler(event, context):
    return {
        "isBase64Encoded": False,           # boolean
        "statusCode": 200,                  # integer, NOT string
        "headers": {                        # object with string values
            "Content-Type": "application/json",
        },
        "body": json.dumps({"key": "val"}) # MUST be string
    }
```

**TypeScript — Correct:**

```typescript
export const handler = async (event: any) => ({
  isBase64Encoded: false,
  statusCode: 200,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ key: "val" }),  // MUST be string
});
```

**Common mistakes -> 502:**

```python
return {"statusCode": 200, "body": {"key": "val"}}     # body not a string -> 502
return "just a string"                                   # not a JSON object -> 502
# Note: string statusCode ("200") and missing statusCode are silently handled (no 502)
```

### 504 Timeout — Flowchart

```
504 Endpoint Request Timed Out
│
├─ Step 1: Enable CloudWatch logging
│  ├─ REST: execution logs + access logs
│  ├─ HTTP: access logs only
│  └─ Include: $context.integrationLatency, $context.integration.status
│
├─ Step 2: Identify timeout source
│  ├─ REST API: integration timeout configurable 50ms–29s
│  ├─ HTTP API: 30s max (can be lowered, cannot be raised)
│  └─ Was integration invoked?
│     ├─ NO  → Transient network failure; retry
│     └─ YES → Backend too slow
│
├─ Step 3: Reduce integration runtime
│  ├─ Move non-critical work to async (SQS, Step Functions)
│  ├─ Increase Lambda memory (faster CPU)
│  ├─ Provisioned concurrency (eliminate cold starts)
│  └─ Check downstream dependencies (DB, external APIs)
│
└─ Step 4: Increase timeout (REST only)
   ├─ Request via Service Quotas console
   ├─ Update integration timeout value AND redeploy
   └─ Note: may reduce account throttle quota
```

### CloudWatch Insights Queries

**Find all 5xx errors:**

```
fields @timestamp, @message, @logStream
| filter status >= 500 and status < 600
| sort @timestamp desc
| display @timestamp, httpMethod, resourcePath, status, requestId
```

**Find timeout errors:**

```
fields @timestamp, @message
| filter @message like "Execution failed due to a timeout error"
| sort @timestamp desc
```

**Find slow integrations (>10s):**

```
fields @timestamp, integrationLatency, status, resourcePath
| filter integrationLatency > 10000
| sort integrationLatency desc
```

### Automated Troubleshooting

**AWSSupport-TroubleshootAPIGatewayHttpErrors** — Systems Manager runbook:

- Validates API, resource, operation, and stage
- Analyzes CloudWatch logs automatically
- Requires: `apigateway:GET`, `logs:GetQueryResults`, `logs:StartQuery`, `ssm:*`
- Available in Systems Manager console → Automation
