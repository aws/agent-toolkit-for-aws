# Domains and Routing

## Default Domain

Every endpoint gets a managed HTTPS domain (TLS automatic, no configuration):

- Single-region: `{endpointId}.{generated}.lambda-web.{region}.on.aws`
- Multi-region: `{endpointId}.lambda-web.global.on.aws`

## Endpoint Types

**HomeRegion** — single region, lower cost, good for dev/test:

```json
{"endpointType": "HomeRegion"}
```

**MultiRegion** — Route53 latency-based routing across the configured regions:

```json
{"endpointType": "MultiRegion", "autoDeploymentMode": "Disabled", "revisionWeights": [{"revisionId": "{rev}", "weight": 100}], "regions": ["us-west-2", "eu-west-1"]}
```

**PerRegion** — a separate endpoint per region: like `MultiRegion`, but each region also gets its own domain name, so a region can be addressed directly as well as through the shared domain:

```json
{"endpointType": "PerRegion", "autoDeploymentMode": "Disabled", "revisionWeights": [{"revisionId": "{rev}", "weight": 100}], "regions": ["us-west-2", "eu-west-1"]}
```

> **Important:** `MultiRegion` and `PerRegion` endpoints require `autoDeploymentMode: Disabled` — `LatestRevision` is only supported for `HomeRegion`. When Disabled, you must explicitly specify `revisionWeights`.

Multi-region is a property of an *endpoint*, not of the function: you add one to an
existing function, and the function's home region is fixed when it is created.

- **The home region is added for you.** List the *additional* regions, and make the call
  from the home region.
- **Revisions must already be `Active`** before they can appear in `revisionWeights`.
- **Auto-deployment is unavailable.** Every code update becomes two calls:
  `create-web-function-revision`, then `update-web-function-endpoint`.
- **The app must be region-agnostic.** Consecutive requests from one client can land in
  different regions, so keep state in a replicated store, never in the execution environment or `/tmp`.

```bash
aws lambda-web create-web-function-endpoint \
  --function-name {name} \
  --endpoint-name global \
  --endpoint-type MultiRegion \
  --auth-type ApplicationManaged \
  --auto-deployment-mode Disabled \
  --revision-weights '[{"revisionId":"{rev}","weight":100}]' \
  --regions us-west-2 eu-west-1 \
  --region us-east-1        # home region — endpoint spans us-east-1 + us-west-2 + eu-west-1
```

## Auth Types

| Type | Exposure | Use case |
|------|----------|----------|
| `ApplicationManaged` | **Public — anyone on the internet with the URL; no AWS-layer auth.** | Public websites/APIs where the **app** handles its own auth (JWT, sessions, API keys). Authorization header passed through to your code. |
| `IamAuth` | Private — only IAM-signed (SigV4) callers. | Internal / service-to-service endpoints. |

For public websites, use `ApplicationManaged` — but the app is then responsible for its own authentication, authorization, input validation, and rate limiting. See [iam-and-security.md](iam-and-security.md#security-considerations).

**L7 protection.** There is no built-in WAF on the managed domain, and `throttleConfig.rateLimit` is endpoint-wide rather than per-client. For production `ApplicationManaged` workloads that need L7 DDoS protection, bot mitigation or IP filtering, put your own CloudFront distribution with AWS WAF in front of the endpoint and treat the endpoint domain as the origin.

## Traffic Routing

- `autoDeploymentMode: LatestRevision` — new revisions get 100% traffic immediately
- `autoDeploymentMode: Disabled` — manual control, enables canary/blue-green

For canary or blue-green, `revisionWeights` splits traffic across at most **2** revisions and the weights must sum to exactly **100** (e.g. `90`/`10`). To finish a rollout, replace the pair with a single entry at `100` — a weight of `0` is invalid, so drop the retired revision rather than zeroing it.

## CORS

Configure in your app code (Lambda Web Functions doesn't manage CORS):

```javascript
// Express
import cors from 'cors';
app.use(cors({ origin: 'https://myapp.example.com' }));
```

```javascript
// Hono
import { cors } from 'hono/cors';
app.use('/api/*', cors({ origin: 'https://myapp.example.com' }));
```

## HTTPS

All endpoints enforce HTTPS. Your app receives plain HTTP on the internal port — no TLS handling needed in your code.

## Protocol version: HTTP/1.1 only

The managed domain serves **HTTP/1.1**. A client offering HTTP/2 in ALPN is answered with
`http/1.1`; there is no h2 negotiation, and no HTTP/3. Confirm for yourself with
`curl -sv --http2 https://{domainName}/` and read the ALPN lines.

This matters before you design, not after: HTTP/2 multiplexing, header compression and server push
are all unavailable, so a browser client pays a connection per parallel request. If you need
HTTP/2 at the edge, terminate it on CloudFront — see [Putting CloudFront in front](#putting-cloudfront-in-front).

## Compression: none, and `Accept-Encoding` is ignored

Response bodies are returned **uncompressed regardless of the request's `Accept-Encoding`**. No
`content-encoding` header comes back for `gzip`, `br`, or `gzip, deflate, br`, and the transferred
byte count is identical in every case, including `identity`. On text-heavy JSON that is a large
multiple of what a compressed response would cost in egress, and it usually shows up on the bill
before it shows up anywhere else.

Two fixes, and they compose:

```javascript
// In the app — compress before the response leaves the environment.
import compression from 'compression';
app.use(compression());
```

Or compress at the edge, by enabling automatic compression on a CloudFront distribution in front
of the endpoint. Compressing in the app is the one that also reduces bytes out of the environment.

## Custom domains

There is no native custom-domain or certificate configuration on a Web Function endpoint. The
endpoint is reachable only on its generated `{endpointId}.{generated}.lambda-web.{region}.on.aws`
name, and
nothing in `endpoint-config` accepts a domain name or an ACM certificate ARN. Confirm against
`aws lambda-web create-web-function-endpoint help` rather than assuming one can be attached.

No production site ships public traffic on the generated name, so the answer for a custom domain is
CloudFront in front.

## Putting CloudFront in front

One distribution solves four separate problems: a custom domain, HTTP/2 at the edge, compression,
and L7 protection. If you need any one of them, this is the shape.

1. **Origin.** Use the endpoint's `domainName` as a custom origin, HTTPS only. It is a public
   hostname, so there is no origin access identity to configure.
2. **Certificate.** Request or import an ACM certificate **in `us-east-1`**, which is where
   CloudFront reads certificates from regardless of where the function runs, and attach it to the
   distribution as an alternate domain name.
3. **DNS.** Point your record at the distribution — a Route 53 A/AAAA **alias** record for an apex
   domain, or a `CNAME` for a subdomain, or the equivalent at an external DNS provider.
4. **HTTP/2.** Enable it on the distribution. The edge speaks HTTP/2 to the browser and HTTP/1.1
   to the endpoint, which is the only way to get HTTP/2 for these apps.
5. **Compression.** Turn on automatic compression so text responses are compressed at the edge
   even if the app does not compress them.
6. **L7 protection.** Attach AWS WAF for rate limiting, bot control and IP reputation. The managed
   domain has none of its own, and `throttleConfig.rateLimit` is endpoint-wide rather than
   per-client.

The endpoint stays publicly reachable on its generated name after you put CloudFront in front, so
the distribution is not by itself an access control.
If only CloudFront should reach the app, enforce that in the app, for example by requiring a shared
secret header that the distribution adds and the app verifies.
