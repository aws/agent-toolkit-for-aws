# API Gateway Reference

Exact quotas and the handful of gotchas worth pinning down. Assumes you know the basics: choose **REST API** when you need WAF / API keys / usage plans / request validation / built-in caching / edge-optimized / canary / VTL / resource policies, otherwise **HTTP API** (lower latency, native JWT, built-in CORS, auto-deploy); under Lambda **proxy** integration the **Lambda must return CORS headers** (the console "Enable CORS" button doesn't apply); the **#1 cause of 502** is a malformed proxy response (`body` must be a `JSON.stringify`'d string in the `{statusCode, headers, body}` shape); REST API has **no native generic JWT** (use Cognito or a Lambda authorizer), HTTP API has a **native JWT authorizer** for any OIDC IdP.

## Contents

- [REST vs HTTP API comparison](#rest-vs-http-api-comparison)
- [Integration timeouts and payloads](#integration-timeouts-and-payloads)
- [Throttling and quotas](#throttling-and-quotas)
- [Lambda authorizers](#lambda-authorizers)
- [WebSocket APIs](#websocket-apis)
- [CORS gotchas](#cors-gotchas)

---

## REST vs HTTP API comparison

Default to **HTTP API** (lower latency, lower cost, simpler); reach for **REST API** only when you need one of its exclusive features:

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

---

## Integration timeouts and payloads

| | REST API | HTTP API |
|---|---|---|
| Integration timeout | 50ms–29s (default 29s; **raisable only for Regional/private**) | **30s hard max** (lowerable, not raisable) |
| Payload size | 10 MB | 10 MB |
| Endpoint types | Edge, Regional, Private | Regional only |
| Response streaming | Yes (proxy, STREAM mode) | No |

> **REST API streaming caveats:** no built-in caching, no VTL transforms, no WAF inspection of streamed content; 2 MBps cap after the first 10 MB (Function URLs cap after 6 MB).

---

## Throttling and quotas

Throttling applies most-specific → least-specific: per-client/method (usage plan + API key, REST only) → per-method → account-level → AWS Regional (hard). Token bucket: empty bucket → `429 Too Many Requests`; burst allows temporary spikes.

### Account-level

Confirm the current account-level steady-state RPS and burst limits for the Region rather than assuming a default — they vary by Region and are adjustable:

```bash
aws service-quotas get-service-quota --service-code apigateway --quota-code L-8A5B8E43
```

### REST API

| Resource | Default | Adjustable? |
|---|---|---|
| Resources per API | 300 | Yes |
| Stages per API | 10 | Yes |
| API keys per account | 10,000 | No |
| Usage plans per account | 300 | Yes |
| Custom domains per Region | 120 | Yes |
| Header value size | 10,240 bytes | No |
| Cache TTL | 0–3600s | No |
| Mapping template size | 300 KB | No |

### HTTP API

| Resource | Default | Adjustable? |
|---|---|---|
| Routes per API | 300 | Yes |
| Stages per API | 10 | Yes |
| Integrations per API | 300 | No |
| Custom domains per Region | 120 | Yes |
| VPC links per Region | 10 | Yes |

Client-side 429 handling: exponential backoff with jitter, respect `Retry-After`, rate-limit to stay under known limits.

---

## Lambda authorizers

| Feature | TOKEN | REQUEST |
|---|---|---|
| Identity source | Single header (bearer token) | Headers, query strings, stage vars, `$context` |
| Cache key | Token header value | All specified identity sources combined |
| Available on | REST API only | REST API + HTTP API |
| Recommendation | Legacy | **Preferred for new APIs** |

Caching: default TTL **300s** (range 0–3600). **A cached policy applies to ALL methods/resources.** If any specified identity source is missing/null/empty → **401 without invoking Lambda**.

The authorizer must return an IAM policy: `{ principalId, policyDocument: { Version, Statement: [{ Action: "execute-api:Invoke", Effect: "Allow"|"Deny", Resource: methodArn }] }, context: {...} }`. HTTP API JWT authorizers need no Lambda — configure `issuer` + `audience` directly on the API.

---

## WebSocket APIs

Routes: `$connect` (auth, store connectionId), `$disconnect` (best-effort cleanup), `$default` (catch-all / non-JSON), plus custom routes selected by `$request.body.action`. Server pushes via the `@connections` API (`PostToConnectionCommand` / `post_to_connection`).

| Limit | Value |
|---|---|
| Idle connection timeout | 10 minutes |
| Max connection duration | 2 hours |
| Message payload | 128 KB (hard limit) |

Close codes: **1001** idle/max-duration, 1003 unsupported binary, 1006 abnormal (no close frame), **1008** throttled, **1009** message too large, 1011 internal error, 1012 service restart.

Store `connectionId` in DynamoDB with a **TTL attribute set to now + 7200s** (the 2-hour max duration) so stale connections are auto-cleaned even when `$disconnect` is missed — enable DynamoDB TTL on that attribute.

---

## CORS gotchas

The common, non-obvious failures (basic header setup is well understood):

| Mistake | Fix |
|---|---|
| Binary media types `*/*` break OPTIONS (502) | Set `contentHandling: CONVERT_TO_TEXT` on the OPTIONS integration |
| `Allow-Origin: *` with `credentials: include` | Specify the exact origin, not a wildcard |
| Not redeploying after CORS changes | Redeploy the stage |
| Gateway 4XX/5XX responses lack CORS headers | Add CORS headers to gateway responses too |

For the full step-by-step procedure of wiring CORS, throttling, and access logging when connecting a Lambda, use the **connecting-lambda-to-api-gateway** skill (see SKILL.md routing). For 502/504 deep debugging, see [troubleshooting.md](troubleshooting.md).
