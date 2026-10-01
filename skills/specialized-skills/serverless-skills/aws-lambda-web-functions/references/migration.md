# Migration

Moving an existing Node.js HTTP app to Lambda Web Functions. Most of the work is deleting code:
the adapter, the handler export, and the API Gateway wiring all go away.

## Contents

- [Preflight — confirm before committing](#preflight--confirm-before-committing)
- [Path 1 — Express/Fastify behind an adapter](#path-1--expressfastify-behind-an-adapter)
- [Path 2 — API Gateway + Lambda proxy](#path-2--api-gateway--lambda-proxy)
- [Path 3 — Lambda function URL](#path-3--lambda-function-url)
- [Path 4 — Container on Fargate, App Runner or EC2](#path-4--container-on-fargate-app-runner-or-ec2)
- [Features with no direct equivalent](#features-with-no-direct-equivalent)
- [Observability deltas when migrating from Event Functions](#observability-deltas-when-migrating-from-event-functions)
- [Cutting traffic over](#cutting-traffic-over)
- [Post-migration verification](#post-migration-verification)

## Preflight — confirm before committing

Walk these before rewriting anything. A "no" means Web Functions is the wrong destination —
see the decision gates in [SKILL.md](../SKILL.md).

- [ ] The app is Node.js, or can run on `nodejs24.x`. Runtime support can change, so confirm the supported runtimes with `aws lambda-web help` or the AWS docs rather than assuming this is the only one.
- [ ] Every native dependency has an arm64 build, and the deployment package is built on arm64. Execution environments are Graviton, so an x86-built native addon will not load.
- [ ] The entry point can become `index.js` at the root of the ZIP.
- [ ] No request needs longer than the 900 s (15 min) per-request timeout.
- [ ] The app is safe to run with several concurrent requests in one process — no module-level per-request state. This is the single most common source of post-migration bugs, because Event Functions gave every request its own environment and hid the problem.
- [ ] Nothing depends on state surviving in the environment or `/tmp` between requests.
- [ ] The package, including `node_modules`, fits in 512 MB.
- [ ] 2 vCPU / 2 GB per environment is enough (see Service Limits in [SKILL.md](../SKILL.md)).

## Path 1 — Express/Fastify behind an adapter

The common shape: an Express or Fastify app wrapped by `serverless-express`,
`@vendia/serverless-express`, `aws-lambda-fastify`, or a hand-rolled event translator.

The router does not change. The wrapper does.

**Before:**

```javascript
// handler.js
import serverlessExpress from '@vendia/serverless-express';
import app from './app.js';

export const handler = serverlessExpress({ app });
```

**After:**

```javascript
// index.js — the runtime loads exactly this path
import app from './app.js';

// The runtime probes this exact host:port for readiness.
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST, () => console.log(`Listening on ${HOST}:${PORT}`));
```

Steps:

1. Remove the adapter from `package.json` and delete the handler module.
2. Rename or shim the entry point to `index.js`, and add `"type": "module"` if you use `import`.
3. Add the `app.listen(...)` call above. Do not hardcode a port.
4. Audit for concurrency safety — see the preflight checklist. Search for module-level `let`/`var` that a request writes to.
5. Run it locally with `node index.js` and curl it. Local and deployed behaviour are now the same code path, which they were not under the adapter.
6. Package and deploy per [deployment.md](deployment.md).

What you can delete along the way: base64 request/response encoding, `isBase64Encoded`
handling, API Gateway event shape translation, and any `context.callbackWaitsForEmptyEventLoop`
workaround — background work now continues naturally after the response.

## Path 2 — API Gateway + Lambda proxy

Two options, and the choice is about which API Gateway features you actually use.

**Option A — replace the API with the endpoint.** Simplest, and the reason to migrate. The
endpoint gives you a managed HTTPS domain directly. Move into the app: CORS (a middleware such
as `cors`), request validation, and authorization (validate the JWT or session in the app).

Choose `authType` deliberately rather than taking a default. Use `IamAuth` for
service-to-service traffic, so only SigV4-signed callers reach the endpoint. Reach for
`ApplicationManaged` only when the endpoint genuinely must be public, and treat that as a
commitment rather than a convenience, because nothing authenticates in front of the app. Its own
authentication must be implemented and verified against the new endpoint before any traffic
shifts to it. A public endpoint also needs defence in depth beyond authentication: front it with
AWS WAF and set the standard security response headers (HSTS, CSP, X-Frame-Options), which
`helmet` handles for Express and Fastify. See [iam-and-security.md](iam-and-security.md).

**Option B — keep API Gateway in front of the endpoint.** Keep this when you depend on usage
plans and API keys, Cognito or Lambda authorizers, request/response mapping, mTLS, edge WAF, or
WebSocket APIs. Treat the endpoint domain as the HTTP integration target.

Either way, translate the handler as in Path 1 — the event-shape code goes away.

| API Gateway concept | Where it goes |
|---|---|
| Proxy integration event → `req` | Native `req`/`res`; delete the translation layer |
| `event.requestContext.authorizer` claims | Validate the token in the app, or keep API Gateway (Option B) |
| Stage variables | `serviceConfig.environmentVariables` on the revision |
| Stage-level canary | `revisionWeights` on the endpoint (at most 2 revisions, summing to 100) |
| Per-method throttling | `throttleConfig.rateLimit`, which is endpoint-wide rather than per-method or per-client |
| CORS configuration | Middleware in the app → [domains-and-routing.md](domains-and-routing.md) |
| Access logs | CloudWatch Logs from the app → [observability.md](observability.md) |

## Path 3 — Lambda function URL

The closest existing shape — a function already reachable over HTTPS without API Gateway.

1. Drop the handler export; add a listening server as in Path 1.
2. `authType` here has exactly two values, `ApplicationManaged` and `IamAuth` (see [iam-and-security.md](iam-and-security.md)). A function URL's `NONE` corresponds to the first and `AWS_IAM` to the second; confirm that mapping against the API reference before relying on it for an access-control decision.
3. Response streaming via `awslambda.streamifyResponse` becomes ordinary Node streaming — write to the response as you go. See [architecture-patterns.md](architecture-patterns.md).
4. There is no reserved- or provisioned-concurrency setting. Bound scale with `throttleConfig.rateLimit` (RPS) or `scalingConfig.maxEnvironments` (see [scaling-and-concurrency.md](scaling-and-concurrency.md)); `throttleConfig.rateLimit: 0` is the equivalent of the `reservedConcurrency: 0` kill switch.
5. The domain changes, so update clients and any DNS records that pointed at the function URL.

## Path 4 — Container on Fargate, App Runner or EC2

The app is probably already a listening HTTP server, so the code is close. The packaging is not.

1. There is no OCI image path — the artifact is a ZIP in S3. Reproduce the image's install step with `npm ci --omit=dev` and zip the result.
2. Anything the Dockerfile installed outside npm (system packages, native binaries, headless browsers, ImageMagick) has no equivalent. If the app needs it, this is not a Web Functions workload — check `aws-lambda-microvms`, or ECS/EKS.
3. Long-lived in-process state (a warm cache, a loaded model, in-memory sessions) does not survive; move it to a shared store.
4. Replace the container health check with the readiness contract: bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT` within the 10 s init timeout.
5. Sidecars, cron inside the container, and background daemons have no equivalent. Move scheduled work to EventBridge Scheduler plus an Event Function.

## Features with no direct equivalent

Plan replacements for these before you migrate, not after:

| Feature | Replacement |
|---|---|
| Reserved / provisioned concurrency | Bound scale with `throttleConfig.rateLimit` or `scalingConfig.maxEnvironments` → [scaling-and-concurrency.md](scaling-and-concurrency.md). `throttleConfig.rateLimit: 0` is the kill switch that `reservedConcurrency: 0` gives you on Event Functions |
| Lambda layers | No layers concept in the revision API. Bundle shared code into the ZIP |
| Event source mappings (SQS, Kinesis, DynamoDB Streams) | Keep an Event Function for those paths — `aws-serverless`. A Web Function serves HTTP only |
| Container (OCI) image deployment | `codeConfig.s3Object` is the only code source in `BuildConfig` |
| In-environment scheduled work | EventBridge Scheduler + an Event Function |
| Non-Node runtimes | Event Functions; for custom OS needs check `aws-lambda-microvms` |

Feature availability changes, so confirm the layers and container-image rows against
`aws lambda-web create-web-function-revision help` or the API reference before ruling either out.

A mixed application is normal and expected: HTTP surface on a Web Function, queue and stream
consumers on Event Functions, in the same account and stack.

## Observability deltas when migrating from Event Functions

A new app is fine with the defaults. A migrated app is not: three things move, and each one fails
silently rather than erroring.

**The log group path changes.** Logs go to `/aws/lambda/web/{function-name}`, plus a
`{logGroup}.local` group holding only the logs of the region that served the request. The Event
Functions path `/aws/lambda/{function-name}` is **not** created, so
`aws logs filter-log-events --log-group-name /aws/lambda/{name}` returns
`ResourceNotFoundException`. Anything scoped to the old path silently collects nothing:

- [ ] Log shipper subscription filters repointed at `/aws/lambda/web/`.
- [ ] IAM policies whose `Resource` is scoped to `/aws/lambda/*` widened or repointed — a policy
      written for the old prefix does not match the new group.
- [ ] CloudWatch dashboards and metric filters repointed.
- [ ] Alarms that watched the old group repointed, since an alarm on a log group that never
      receives data does not fire.

**Three Event Functions environment variables are absent.** `AWS_LAMBDA_LOG_STREAM_NAME`,
`AWS_LAMBDA_LOG_GROUP_NAME` and `AWS_LAMBDA_FUNCTION_NAME` are all unset. Migrated structured
logging or tracing code that reads any of them logs an empty value instead of failing, which is
worse than an error because it looks like it works. Read `AWS_LAMBDA_HTTP_ENDPOINT` for the bind
address; for correlation use the `requestId` the platform already injects into every log line, or
the `lambda-web-request-id` and `lambda-web-logstream` response headers.

**The CLI namespace splits.** `aws lambda list-functions` returns only Event Functions and will
**not** show your Web Functions — they are under `aws lambda-web list-web-functions`. Scripts,
runbooks and inventory tooling that enumerate functions with the `lambda` namespace silently
under-report after a migration.

## Cutting traffic over

Do not repoint DNS as the first step.

1. Deploy the Web Function alongside the existing stack and curl its endpoint directly.
2. Compare responses against the old endpoint for the routes that matter — status codes, headers, and content type, not just the body.
3. Load-test at expected concurrency so the multi-concurrency behaviour surfaces before customers find it. Watch for cross-request state bleed, not just latency.
4. Shift traffic at the DNS or CDN layer, keeping the old stack warm and ready to take traffic back.
5. Keep the old stack until error rates and p99 latency have been stable across a full traffic cycle, then decommission.

For canarying between revisions of the Web Function itself — as opposed to between old and new
stacks — use `revisionWeights` on the endpoint. See [deployment.md](deployment.md).

## Post-migration verification

- [ ] Endpoint state is `Active` and `curl https://{domainName}/` returns the expected response.
- [ ] A concurrency test at realistic load shows no cross-request data bleed.
- [ ] Logs arrive in the configured log group → [observability.md](observability.md).
- [ ] The log group is encrypted with a KMS key. HTTP request and response logs routinely carry tokens, headers and PII, so encrypt by default rather than treating it as a judgement call.
- [ ] `authType` matches intent — `ApplicationManaged` endpoints are public.
- [ ] The execution role carries only the permissions the app actually uses.
- [ ] No secrets moved into `environmentVariables` during the port. Keep them in AWS Secrets Manager or SSM Parameter Store (`SecureString`) and fetch them at runtime.
- [ ] Every route validates and sanitises its input in the app — a schema library such as Zod, Joi or ajv in middleware. If the source sat behind API Gateway, its request validation on bodies, query parameters and headers is gone, and losing it is silent.
- [ ] `ApplicationManaged` endpoints sit behind CloudFront and AWS WAF for L7 protection — rate limiting, bot control, IP reputation. The managed domain has no WAF of its own.
- [ ] A CloudWatch alarm on endpoint error rate exists before the traffic shift.
