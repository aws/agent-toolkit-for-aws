---
name: aws-lambda-web-functions
description: >
  Creates and deploys Node.js HTTP web applications on AWS Lambda Web Functions. Guides users through building web apps and APIs with Express, Fastify, or Hono, packaging, deploying via the aws lambda-web CLI, and iterating. Triggers when user wants to deploy a website or web app to AWS as serverless, deploy a Node.js HTTP server to AWS, build a serverless website or API with Node.js, deploy Express/Hono/Fastify apps, set up multi-region HTTP endpoints, or explicitly mentions Lambda Web Functions. Does NOT trigger for non-Node.js runtimes, event-driven patterns (SQS, Kinesis, S3 events), or container deployments.
version: 1
---

# AWS Lambda Web Functions

> The AWS MCP server is recommended for sandboxed execution and audit logging.
>
> **If `aws lambda-web` is not recognized, update the AWS CLI (see [references/deployment.md](references/deployment.md)).** A missing command means an outdated CLI, not an unavailable feature.

Help users build and deploy Node.js HTTP applications on AWS Lambda Web Functions. Your app listens on a port, handles HTTP natively, and gets a global HTTPS URL. Develop locally with `node index.js`, deploy the same code to AWS.

## When to Use Web Functions

- Interactive HTTP traffic someone is waiting on: web app, HTTP API, or SSR site.
- The app is already a port-listening HTTP server (Express, Fastify, Hono) and should stay one — no handler rewrite, no adapter library.
- Handlers are I/O-bound (database, cache, another API, a model endpoint), so many requests share one execution environment and time spent waiting on I/O is not billed as CPU.
- Response streaming matters: SSE, chunked transfer, or proxying LLM tokens as they are produced.
- The endpoint should be reachable worldwide on one hostname without assembling CloudFront, API Gateway and Route53 by hand.
- Traffic is spiky or unpredictable and should scale to zero.

### Hard preconditions

Any "no" rules Web Functions out. Invoke the `aws-serverless` skill to find a suitable service.

- Runtime is Node.js — `nodejs24.x`. Python, Java, Go, .NET and Rust are not supported. Confirm the supported runtime list with `aws lambda-web help` or the AWS docs before routing a caller away.
- Every native dependency has an **arm64 (Graviton)** build.
- The work is an HTTP request/response (or stream) that a caller is waiting on. Queue, event-stream source (Kinesis, DynamoDB Streams), schedule, or event trigger are not supported.
- One request completes within the 900 s (15 min) request timeout.
- The app fits a 512 MB package and a 2 vCPU / 2 GB environment (see Service Limits).
- Environments are stateless — any environment can serve any request. There is no affinity between an end user's session and a specific environment.
- The app tolerates sharing an environment with concurrent requests. Strict per-request isolation is not supported.

## Use Cases

"What I'm building" → how it lands here.

| The user is building | Shape on Web Functions |
|---|---|
| JSON HTTP API or REST backend | Express or Hono router, I/O-bound handlers, DynamoDB or RDS behind it → [architecture-patterns.md](references/architecture-patterns.md) |
| Server-side-rendered site or app | Render HTML per request from `index.js`; no bundler needed unless you author JSX → [architecture-patterns.md](references/architecture-patterns.md) |
| LLM or AI gateway streaming tokens to a browser | SSE or chunked responses; raise `timeoutSeconds` to cover the whole stream, not just the first byte → [architecture-patterns.md](references/architecture-patterns.md) |
| Webhook receiver (Stripe, GitHub, Slack) | Verify the sender's signature against a signing secret from Secrets Manager **before** acting on the payload, then acknowledge fast and finish the work after responding — the environment stays running → [architecture-patterns.md](references/architecture-patterns.md) |
| Mobile or web backend-for-frontend aggregating several services | One environment fans several requests out concurrently, and time spent waiting is not billed as CPU |
| Single-page app plus its API from one deployment | `express.static` for the bundle, `/*splat` fallback for client routes → [static-assets.md](references/static-assets.md) |
| Internal service-to-service HTTP endpoint | `authType: IamAuth`, so only SigV4-signed callers reach it → [iam-and-security.md](references/iam-and-security.md) |
| Globally low-latency endpoint on a single hostname | `MultiRegion` endpoint plus a region-agnostic app → [domains-and-routing.md](references/domains-and-routing.md) |

## Workflow

Default to the `aws lambda-web` CLI — it's the quickest path. Use `aws lambda-web deploy` when the user asks for a single command or says they already deploy with it. It packages, uploads and creates or updates a project directory in one command, and `--hello-world` scaffolds and deploys a starter app (see Deploy (CLI) below). Otherwise, including for updates to an existing function, use the steps below. Use CloudFormation, CDK, SAM or Terraform when the user wants infrastructure-as-code or a repeatable production stack (see [references/infrastructure-as-code.md](references/infrastructure-as-code.md)).

1. **Scaffold** - Express is inline below; for **Hono** or **Fastify**, read [references/frameworks.md](references/frameworks.md)
2. **Choose endpoint auth** — **ask the user before deploying** (see below); endpoints are public unless they pick `IamAuth`
3. **Test locally** — `node index.js`
4. **Package** — ZIP with production deps (up to 512 MB)
5. **Deploy** — `aws lambda-web create-web-function`
6. **Verify** — get endpoint URL, then curl
7. **Iterate** — create a new revision

> **Public by default.** A `ApplicationManaged` endpoint is reachable by **anyone on the internet with the URL** — there is no AWS-layer auth and no built-in WAF, and the URL is not a secret. Before deploying, **ask the user** which they want:
>
> - **`ApplicationManaged`** (public) — the **app** must implement its own authentication/authorization, input validation, and rate limiting.
> - **`IamAuth`** (internal) — only callers with valid IAM credentials (SigV4-signed) can reach it.
>
> If the endpoint is public, the app owns its security. See [references/iam-and-security.md](references/iam-and-security.md) for the security checklist (auth, input validation, rate limiting, WAF/CloudFront, least-privilege role, secrets).

## Quick Start (Express)

```javascript
// index.js
import express from 'express';
import helmet from 'helmet';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
// The runtime probes this exact host:port for readiness.
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');

app.use(helmet());
app.use(express.static(join(__dirname, 'public')));
app.use(express.json({ limit: '10mb' }));
app.get('/api/health', (req, res) => res.json({ status: 'ok' }));
app.listen(PORT, HOST, () => console.log(`Listening on ${HOST}:${PORT}`));
```

```json
{
  "name": "my-web-app",
  "type": "module",
  "scripts": { "start": "node index.js", "dev": "node --watch index.js" },
  "dependencies": { "express": "^5.0.0", "helmet": "^8.0.0" }
}
```

`helmet` sets the security response headers (HSTS, CSP, `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`) that no AWS layer sets for you here. On an
`ApplicationManaged` endpoint the app is the only thing that can set them, so it belongs in the
scaffold rather than being added later.

## Resource Naming

All resources are project-scoped. Derive names from the function name:

| Resource | Default Pattern | Example |
|---|---|---|
| Function | `{name}` | `my-api` |
| IAM Role | `{name}-web-role` | `my-api-web-role` |
| S3 bucket | `{name}-web-{account}` | `my-api-web-1234567890` |
| S3 key | `{name}/function.zip` | `my-api/function.zip` |
| DynamoDB | `{name}-{purpose}` | `my-api-items` |

Function names must be unique across **all Regions** in the account — the same name cannot exist in two Regions, and a collision fails at create time with a conflict error.

**Ask the user** which S3 strategy they prefer:

- **Separate bucket per project** (default) — fully isolated, easy cleanup
- **Shared bucket across projects** (e.g., `{account}-web-code`) — fewer resources, key-prefix isolation
- **Custom** — user provides their own bucket name and key prefix

`aws lambda-web deploy` names its own role (`awscli-lambdaweb-{name}`) and bucket (`awscli-lambdaweb-{account}-{region}-an`).

## Deploy (CLI)

The `aws lambda-web` CLI is the primary, supported path — use it by default. The flow is:
one-time S3 code bucket (versioning + Lambda read access), then `npm ci --omit=dev` → `zip`
→ `aws s3 cp` → `aws lambda-web create-web-function` with `--revision-config` and
`--endpoint-config`, then wait for the endpoint to reach `Active`. If the project has a
build step, run it **before** the prune — `npm ci --omit=dev` removes the bundler.

When the user asks for one command or already deploys with it, `aws lambda-web deploy --name {name} --code . --create --auth-type {auth-type}` (ask the user which auth type) zips, uploads, and creates the function, a code bucket, a role and a `dev` endpoint; rerun it without `--create` to ship changes. Install dependencies first.

For the full commands, `EndpointConfig` and `RevisionConfig` field rules, packaging, timeout,
concurrency, environment variables, logging config and every `deploy` flag, see
[references/deployment.md](references/deployment.md). First-time setup (bucket, execution
role, first deploy) is in [references/getting-started.md](references/getting-started.md).
For CloudFormation, CDK or SAM, see
[references/infrastructure-as-code.md](references/infrastructure-as-code.md).

### Multi-Region

Multi-region is supported: a `MultiRegion` endpoint serves your revision from several
regions behind **one hostname**, with Route53 routing each caller to the nearest region.
`PerRegion` additionally gives each region its own domain name. Both require
`autoDeploymentMode: Disabled`, and the app must be region-agnostic — consecutive requests
from one client can land in different regions, so keep state in a replicated store, never
in the execution environment or `/tmp`.

See [references/domains-and-routing.md](references/domains-and-routing.md) for endpoint
types, domains, traffic routing and the multi-region setup commands.

## Verify

```bash
aws lambda-web get-web-function-endpoint \
  --function-name {name} --endpoint-name default --region {region}

# curl the domainName from the response
curl https://{domainName}/api/health
```

A revision that fails to start still goes `Active`, so curl a real route after every deploy. `aws lambda-web deploy` prints the endpoint as `endpointUrl` and names its first endpoint `dev`.

> Prefer waiters (`aws lambda-web wait ...`) over polling loops or `sleep`. Available: `web-function-active`, `web-function-revision-active`, `web-function-endpoint-active`, `web-function-endpoint-updated`, `web-function-endpoint-deleted`, `web-function-deleted`

## Update Code

```bash
zip -r function.zip index.js package.json node_modules/ public/ \
  -x "*.test.*" -x ".git/*" -x ".env" -x "node_modules/.cache/*"
aws s3 cp function.zip s3://{bucket}/{name}/function.zip

aws lambda-web create-web-function-revision \
  --function-name {name} \
  --build-config '{
    "codeConfig": {"s3Object": {"bucket": "{bucket}", "key": "{name}/function.zip"}},
    "runtimeConfig": {"runtime": "nodejs24.x"}
  }' \
  --service-config '{"executionRoleArn": "arn:aws:iam::{account}:role/{name}-web-role"}' \
  --region {region}
```

## Service Limits

Subject to change — check the
[Lambda quotas page](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
for the authoritative values.

| Scope | Resource | Limit |
|-------|----------|-------|
| Account | Regional vCPU limit | 2,000 |
| Account | Regional account rate limit | 100,000 RPS |
| Account | Regional per-endpoint maximum rate limit | 10,000 RPS |
| Per function | Endpoints | 10 |
| Per function | Revisions retained | 50 (oldest unreferenced revisions are deleted automatically) |
| Per function | Environment variables | 32 KB total |
| Per function | Deployment package | 512 MB |
| Per function | Function and endpoint name | 64 characters |
| Per endpoint | Endpoint rate limit | Limited by Regional per-endpoint maximum rate limit (above). User can optionally configure a lower rate limit on individual endpoints via `throttleConfig.rateLimit` |
| Per endpoint | Active revisions | 2 |
| Per environment | vCPU | 2 |
| Per environment | Memory | 2 GB |
| Per environment | Concurrency | 1–128 requests (see [scaling-and-concurrency.md](references/scaling-and-concurrency.md)) |
| Per environment | Network bandwidth | 1 Gbps |
| Per environment | `/tmp` | 512 MB |
| Per environment | File descriptors | 1,024 |
| Per environment | Processes and threads | 1,024 |
| Per environment | Init timeout | 10 seconds |
| Per request | Timeout | 3–900 s (default 30 s) |
| Per request | Header count | 6,300 |

## Cost Model

Four billing dimensions: **CPU, memory, requests, and data transfer**. Check the
[Lambda pricing page](https://aws.amazon.com/lambda/pricing/) for current rates — do not quote
rates from memory. What decides an architecture is the shape of the bill:

- **Active CPU, not wall-clock duration.** Time a request spends blocked on I/O — a database call, another API, a model endpoint — is not billed as CPU. Event Functions bill GB-seconds of wall-clock duration instead, so the same handler bills differently on each.
- **Memory is billed on consumption, not on a provisioned setting.** An environment is 2 vCPU and 2 GB (see Service Limits) and there is no memory dial, so the familiar Event Functions move of raising memory to shorten duration has no equivalent here.
- **Concurrency is the density lever.** One environment serves up to `maxConcurrencyPerEnvironment` requests, so an I/O-bound app keeps many requests in flight per environment instead of occupying one environment each.

Two consequences worth planning around:

- **I/O-bound workloads are the economical case.** A handler that spends most of its life waiting on the network, sharing an environment with other requests, costs less here than the same handler billed per-invoke on wall-clock duration.
- **CPU-bound workloads give that advantage back.** Heavy rendering, image processing or crypto burns billable CPU wherever it runs, and an environment is allocated 2 vCPU — of which a single-threaded Node process uses only one (see Anti-Patterns). For sustained high-volume CPU work, especially where committed-use discounts apply, compare **`aws-lambda-managed-instances`**.

An endpoint's scaling controls `scalingConfig.maxEnvironments` and `throttleConfig.rateLimit` can be used to limit potential cost. See [scaling-and-concurrency.md](references/scaling-and-concurrency.md) for more details.

## IAM Setup

Trust policy principal: `lambda.amazonaws.com`

IAM actions use the `lambda:` prefix. Resource ARN: `arn:aws:lambda:{region}:{account}:web-function/{name}`

Action names match the API operations — `lambda:CreateWebFunction`, `lambda:CreateWebFunctionRevision`, `lambda:CreateWebFunctionEndpoint`, `lambda:UpdateWebFunctionEndpoint`, plus the `Get*`, `List*`, and `Delete*` variants. See [references/iam-and-security.md](references/iam-and-security.md) for the full policy.

Resource ARN must include `/*` wildcard for endpoint/revision operations:

```
"Resource": ["arn:aws:lambda:{region}:{account}:web-function/{name}", "arn:aws:lambda:{region}:{account}:web-function/{name}/*"]
```

The **caller** also needs `s3:GetObject` + `s3:GetObjectVersion` on the code bucket (not just the execution role).

See [references/iam-and-security.md](references/iam-and-security.md) for full policy examples.

## Anti-Patterns

What it looks like → why it fails → what to do instead.

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| Expecting a CPU-bound handler to use the whole environment | An execution environment is allowed 2 vCPU, but Node is single-threaded, so one process uses one of them and the second sits idle | For CPU-bound work, use `worker_threads` (or `cluster`) to occupy both. Leave I/O-bound handlers single-threaded — they are not CPU-limited |
| Zipping a `node_modules` built on an x86 machine (laptop or x86 CI) | Execution environments are arm64, so an x86 native binary will not load. Packages such as `sharp`, `canvas`, `bcrypt` and other native addons ship per-architecture builds | Install and build on arm64 — an arm64 CI runner, a Graviton host, or a container run with `--platform linux/arm64` — then zip |
| Writing response bytes while the request body is still uploading (full-duplex streaming) | The request path is half-duplex: the whole request body is forwarded before any response is read, so a large upload that expects an interleaved response stalls until the timeout. Small bodies fit socket buffers and appear to work, which hides it in testing | Read the request to completion, then stream the response. Keep streaming in the server-to-client direction |
| Wrapping the app in a handler adapter (`serverless-express`, `@vendia/serverless-express`, `aws-lambda-fastify`) | There is no handler to export. The runtime loads `index.js` and expects a listening HTTP server; an adapter never binds a port, so readiness never passes and the environment is not usable | Delete the adapter and call `app.listen(...)` on the host and port from `AWS_LAMBDA_HTTP_ENDPOINT` |
| Hardcoding `app.listen(3000)`, or binding `localhost` / `127.0.0.1` | The runtime probes the exact address it advertises. A mismatched port or a loopback-only bind never answers that probe | Parse `AWS_LAMBDA_HTTP_ENDPOINT` and bind that host and port |
| Module-level mutable state holding per-request data — a `currentUser`, a request-scoped cache, a counter | One execution environment serves many concurrent requests in a single process, so requests read each other's values. This is a correctness and data-leak bug, not a performance one | Keep per-request data in the request scope; share only immutable config and SDK clients at module level |
| Writing session or upload state to `/tmp` and expecting it on the next request | `/tmp` is per environment and shared between concurrent requests; the next request may land on a different environment, or a different Region on a multi-region endpoint | Keep state in DynamoDB, S3 or ElastiCache; use unique filenames for genuinely temporary files |
| Treating the endpoint URL as access control — "nobody knows this domain" | An `ApplicationManaged` endpoint is reachable by anyone on the internet with the URL. No AWS-layer auth, no built-in WAF, and the URL is not a secret | Implement auth in the app, or use `IamAuth`; add CloudFront + WAF for L7 protection → [iam-and-security.md](references/iam-and-security.md) |
| Secrets in `serviceConfig.environmentVariables` | `get-web-function-revision` returns environment variables in plaintext to anyone with read access to the revision | Keep the secret in Secrets Manager or SSM, pass only its name or path, fetch at runtime |
| Running `npm ci --omit=dev` before the build step | Pruning devDependencies deletes the bundler, so the build then fails with `esbuild: command not found` | Build first, prune afterwards — or zip the bundled output → [deployment.md](references/deployment.md) |
| Expecting an `update-*` call to change code, runtime, timeout, env vars or concurrency in place | All of those live on the immutable revision | Create a new revision. Only endpoint-level settings (auth, weights, scaling, throttle) update in place |
| Re-uploading to the same S3 key and expecting a redeploy | A revision is pinned to an object version; CloudFormation reports "No changes to deploy" | Use a new key, or pass the new `versionId` |
| Concluding the feature does not exist because `aws lambda-web` is missing | Absence means an outdated CLI, not a missing capability | Update the AWS CLI → [deployment.md](references/deployment.md) |
| Reusing one function name in two Regions | Function names are unique across **all** Regions in an account; the second create fails with a conflict | Suffix the Region, or use one function with a `MultiRegion` endpoint |
| `app.get('*', ...)` as an SPA fallback on Express 5 | path-to-regexp v8 rejects a bare `*` and throws at startup, so the app never boots | Use `'/*splat'` → [static-assets.md](references/static-assets.md) |

## Troubleshooting — Start Here

The five that account for most failed first deploys. Full symptom → cause → fix tables are in
[troubleshooting.md](references/troubleshooting.md).

| Symptom | Cause | Fix | Verify |
|---|---|---|---|
| Endpoint never reaches `Active`; state goes `Failed` | The app never bound the advertised host and port, so readiness never passed | Bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT` | `get-web-function-endpoint` reports `Active`, then curl `domainName` |
| 500 with `Cannot find module '/var/task/index.js'` | Entry point is not `index.js` — `.mjs`, `server.js`, or nested in `dist/` | Deploy with `aws lambda-web deploy --entry-point {file}`, or rename the entry point to `index.js` at the ZIP root | `unzip -l function.zip` lists `index.js` at the top level |
| Stuck in `Pending` past 10 minutes | Execution-role trust policy principal is not `lambda.amazonaws.com` | Fix the trust policy, then create a new revision | `aws iam get-role` shows the correct principal |
| `create-web-function-revision` returns 500 with no message | The **caller** lacks `s3:GetObject` / `s3:GetObjectVersion` on the code bucket — not the execution role | Add both to the caller's policy | The revision reaches `Active` |
| `invalid choice: 'lambda-web'`, or `Unknown parameter "BuildConfig"` | Outdated AWS CLI; or PascalCase JSON keys | Update the CLI; use camelCase (`buildConfig`, `codeConfig`) | `aws lambda-web help` lists the web-function commands |

## Migration

Moving an existing Node.js HTTP app here is mostly a delete-code exercise — the adapter, the
handler export and the API Gateway wiring all go away, and the router itself does not change.

Four source shapes each have a step-by-step path, a preflight checklist, the features with no
equivalent, and a traffic-cutover procedure: an adapter-wrapped app, API Gateway + Lambda
proxy, a Lambda function URL, and a container on Fargate, App Runner or EC2.
See [migration.md](references/migration.md).

## When to Load Reference Files

Match on meaning, not exact wording — any trigger word in a row should pull that file.

| Read this | Trigger words |
|---|---|
| [getting-started.md](references/getting-started.md) | first deploy, get started, set up, prerequisites, hello world, `--hello-world`, starter app, new project, from scratch, S3 code bucket, execution role, bootstrap, my first web function |
| [frameworks.md](references/frameworks.md) | Express, Fastify, Hono, TypeScript, `.ts`, type stripping, ESM, `type: module`, scaffold, project structure, entry point, `index.js`, router, middleware |
| [deployment.md](references/deployment.md) | deploy, redeploy, ship, release, CLI, `aws lambda-web`, `aws lambda-web deploy`, one command, revision, endpoint, packaging, ZIP, `npm ci`, timeout, environment variables, env vars, canary, blue/green, traffic weights, rollback, `versionId` |
| [scaling-and-concurrency.md](references/scaling-and-concurrency.md) | scaling controls, concurrency, `maxConcurrencyPerEnvironment`, `scalingConfig`, `maxEnvironments`, `throttleConfig`, `rateLimit`, throttling, RPS limit, vCPU quota |
| [infrastructure-as-code.md](references/infrastructure-as-code.md) | CloudFormation, CFN, CDK, `CfnResource`, escape hatch, SAM, Terraform, HashiCorp, HCL, infrastructure as code, IaC, template, stack, `AWS::Lambda::WebFunction`, repeatable deployment, pipeline |
| [static-assets.md](references/static-assets.md) | static files, static assets, CSS, JS bundle, images, favicon, `public/`, `express.static`, SPA, single-page app, client-side routing, fallback route, bundling, esbuild, Vite, cache headers |
| [domains-and-routing.md](references/domains-and-routing.md) | multi-region, multiregion, global, latency routing, Route53, domain, custom domain, hostname, HTTPS, TLS, endpoint type, `HomeRegion`, `MultiRegion`, `PerRegion`, CORS, auth type, `ApplicationManaged`, `IamAuth` |
| [iam-and-security.md](references/iam-and-security.md) | IAM, policy, permissions, role, trust policy, `PassRole`, least privilege, AccessDenied, security, auth, authentication, authorization, public endpoint, WAF, DDoS, rate limiting, secrets, KMS, encryption, security headers, `helmet` |
| [observability.md](references/observability.md) | logs, logging, log group, log level, CloudWatch, metrics, monitoring, alarms, tracing, CloudTrail, audit, structured logging, health check, which region served, debug in production |
| [architecture-patterns.md](references/architecture-patterns.md) | SSR, server-side rendering, React, JSX, streaming, SSE, server-sent events, LLM, AI gateway, token streaming, long-lived connection, webhook, background task, fire and forget, API backend, DynamoDB, connection pooling, thread safety, concurrency model |
| [troubleshooting.md](references/troubleshooting.md) | error, fails, failing, broken, not working, 500, 502, 403, 404, `ECONNREFUSED`, `ERR_MODULE_NOT_FOUND`, module not found, stuck, `Pending`, `Failed`, never becomes active, AccessDenied, ParamValidation, no logs, debug, why doesn't |
| [migration.md](references/migration.md) | migrate, migration, move, port, switch, convert, coming from, replace, `serverless-express`, adapter, wrapper, handler export, function URL, API Gateway proxy, Fargate, App Runner, containerized, lift and shift |

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's **own bundled files** — the `references/` documents — from different places. Determine how the skill was loaded before you read a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool call.** The skill is **not installed on the local filesystem**; its reference files do not exist on disk. You MUST fetch each reference through the same `retrieve_skill` tool by passing the `file` parameter (for example, `file="references/deployment.md"`). Do NOT `file_read` these paths from the local or working directory, and do NOT search the filesystem for them — they are not there, and any local file that happens to match the name is unrelated to this skill.
- **Installed locally** (the skill lives in a local skills directory such as `.claude/skills/aws-lambda-web-functions/`, `~/.claude/skills/aws-lambda-web-functions/`, or `.kiro/skills/aws-lambda-web-functions/`). Read references from the local skill directory using the relative paths shown throughout this document.

This distinction applies **only** to the skill's own packaged files. The user's application code — `index.js`, `package.json`, `public/`, the `function.zip` you build — is always read from and written to the user's working directory regardless of how the skill was loaded. Never fetch or write customer data through `retrieve_skill`.

## Critical Rules

1. **Node 24 only** — `nodejs24.x` is the only runtime; runtime support can change, so confirm with `aws lambda-web help` or the AWS docs before assuming a newer version is unavailable
2. **Entry point is `index.js`** — the runtime loads `/var/task/index.js`, not `.mjs`. When your entry file has another name (`server.js`, `app.mjs`), `aws lambda-web deploy` detects it or takes `--entry-point` and ships a small `index.js` that imports it; a ZIP you build yourself needs `index.js` at its root
3. **Bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT`** — the runtime probes that exact address, so a hardcoded port that does not match it, or a loopback-only bind, fails readiness and the environment is not usable. There is no `PORT` env var
4. **`"type": "module"` in package.json** — required for ESM imports from `index.js`
5. **No handler exports** — your app is an HTTP server
6. **Write thread-safe code** — one execution environment serves many concurrent requests; avoid global mutable state
7. **Code, runtime, timeout, env vars and concurrency all live on the revision** — changing any of them requires a new revision, not an in-place update
8. **Background tasks work natively** — the environment stays running after response
9. **Streaming native** — chunked transfer-encoding, SSE out of the box
10. **TypeScript works natively** — Node 24 type stripping, use `index.js` shim + `import type`
11. **Code comes only from a ZIP in S3** — `deploy` builds and uploads it for you; otherwise supply it through `codeConfig.s3Object` and bundle shared code into the package. For container images and a layers equivalent, confirm against `aws lambda-web create-web-function-revision help` or the API reference rather than assuming either is available
