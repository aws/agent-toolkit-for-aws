# Deployment

## CLI Setup

If `aws lambda-web` is not recognized, update to the latest AWS CLI version. Verify:

```bash
aws lambda-web help  # lists the web-function commands
```

## CLI Commands (`aws lambda-web`)

| Command | Purpose |
|---------|---------|
| `deploy` | Package a local directory and create or update the function in one step (see One-Command Deploy below) |
| `create-web-function` | Create function + first revision + endpoint |
| `create-web-function-endpoint` | Add additional endpoints |
| `create-web-function-revision` | Deploy new code |
| `get-web-function` | Get function state |
| `get-web-function-endpoint` | Get endpoint details (domainName, state, weights) |
| `get-web-function-revision` | Get revision details |
| `list-web-functions` | List all functions |
| `list-web-function-endpoints` | List endpoints for a function |
| `list-web-function-revisions` | List all revisions |
| `update-web-function-endpoint` | Update auth, deploy mode, revision weights |
| `delete-web-function` | Delete function |
| `delete-web-function-endpoint` | Delete an endpoint |
| `delete-web-function-revision` | Delete a revision |

## Create Function

```bash
aws lambda-web create-web-function \
  --function-name {name} \
  --revision-config '{
    "buildConfig": {"codeConfig": {"s3Object": {"bucket":"{b}","key":"{k}"}}, "runtimeConfig": {"runtime":"nodejs24.x"}},
    "serviceConfig": {"executionRoleArn": "arn:aws:iam::{acct}:role/{name}-web-role"}
  }' \
  --endpoint-config '{
    "endpointName":"default","endpointType":"HomeRegion",
    "authType":"ApplicationManaged","autoDeploymentMode":"LatestRevision"
  }' --region {region}
```

## Verify Endpoint

```bash
aws lambda-web get-web-function-endpoint \
  --function-name {name} --endpoint-name default --region {region}
# Returns domainName, state, revisionWeights, regions
```

## New Revision (Update Code)

```bash
aws s3 cp function.zip s3://{bucket}/{name}/function.zip
aws lambda-web create-web-function-revision \
  --function-name {name} \
  --build-config '{"codeConfig":{"s3Object":{"bucket":"{b}","key":"{k}"}},"runtimeConfig":{"runtime":"nodejs24.x"}}' \
  --service-config '{"executionRoleArn":"arn:aws:iam::{acct}:role/{name}-web-role"}' \
  --description "Add /metrics endpoint" \
  --region {region}
```

`autoDeploymentMode` decides whether a new revision starts serving on its own:
`LatestRevision` shifts all traffic to each new revision as you create it, while
`Disabled` leaves traffic where it is until you set `revisionWeights` yourself
(canary, blue/green, multi-region).

> **`LatestRevision` has no health gate. The traffic shift is not conditional on the revision
> starting successfully.** A revision whose code fails to load takes 100% of traffic and still
> reports `state: Active` with `stateReason: "The revision is active."`, so polling revision
> state does **not** detect this. Neither does `create-web-function`, which returns a function
> already in `Active` while the revision is still `Pending`.

Two things actually detect it:

- **`platform.initReport` in CloudWatch.** A healthy start logs
  `{"level":"INFO","type":"platform.initReport","record":{"status":"success",…}}`. A failed start
  logs `"level":"WARN"` with `"status":"failure"` and an `errorType` such as
  `Application.InitCodeError`. This is the reliable signal.
- **An external smoke test** against the endpoint domain after the shift, checking a real response
  and not just a TCP connect.

For anything serving real traffic, prefer `Disabled` with explicit `revisionWeights` so you choose
when traffic moves, and roll back by pointing the weights at the previous revision:

```bash
aws lambda-web update-web-function-endpoint \
  --function-name {name} --endpoint-name default \
  --endpoint-config '{"revisionWeights":[{"revisionId":"{previous-revision-id}","weight":100}]}' \
  --region {region}
```

Also wait on the right thing. `wait web-function-active` returns almost immediately because the
function is `Active` before the revision and endpoint are; `wait web-function-endpoint-active` is
the one that means the endpoint can serve.

## One-Command Deploy (`aws lambda-web deploy`)

`deploy` packages a local directory, uploads it, and either creates the function (first run) or
creates a new revision and points the endpoint at it (every later run). Use it when the user asks
for a single command or already deploys with it. It replaces the zip, S3
upload and create calls above for a project directory on disk; use those calls when you need your
own bucket, key or role layout, or already have a built ZIP.

```bash
npm ci --omit=dev                    # deploy uploads the directory as it is; it does not install
aws lambda-web deploy --name {name} --code . --create --auth-type {auth-type} --region {region}   # first deploy; ask the user: IamAuth or ApplicationManaged (public)
aws lambda-web deploy --name {name} --code . --region {region}              # every deploy after
```

| Flag | Effect |
|------|--------|
| `--name` | Function name (required) |
| `--code` | Local directory to package. Required on create unless `--hello-world` is used. On an existing function, omit it to change only configuration: nothing is packaged or uploaded, and the new revision keeps the deployed code |
| `--create` | Confirms creating a function or endpoint that does not exist. A non-interactive shell stops without it; an existing function never needs it |
| `--hello-world` | Scaffolds a starter HTTP server and deploys it, into `--code`, or `./{name}` when `--hello-world` is used without `--code`. New functions and empty directories only; it never overwrites code |
| `--entry-point` | Entry file relative to `--code`, when auto-detection does not find it |
| `--execution-role-arn` | Use this role. On create, omitting it creates `awscli-lambdaweb-{name}`; on update the existing role is kept |
| `--bucket-name` | Use this existing bucket for the code ZIP instead of the managed `awscli-lambdaweb-{account}-{region}-an` |
| `--env KEY=VAL` / `--unset-env KEY` | Repeatable. Merged into the existing environment on update; `--unset-env` removes a key. Not for secrets: command-line values land in shell history and process listings, and revision environment variables are readable in plaintext. Keep secrets in Secrets Manager or Parameter Store and pass only the name (see Environment Variables below) |
| `--timeout-seconds`, `--max-concurrency-per-environment`, `--application-log-level`, `--system-log-level`, `--kms-key-arn`, `--revision-description` | Revision settings. On update, anything you omit keeps its current value. `--kms-key-arn` encrypts the code and environment variables, not the log group; to encrypt logs with your own key, see [observability.md](observability.md) |
| `--endpoint-name` | Endpoint whose settings the command creates or updates (first one defaults to `dev`). Naming one that does not exist adds it, with `--create`. The new revision is served by every endpoint in `LatestRevision` mode, not only this one; pin other endpoints with `autoDeploymentMode: Disabled` |
| `--endpoint-type`, `--regions` | `HomeRegion` (default), `MultiRegion` or `PerRegion`, used only when the endpoint is created |
| `--auth-type` | `ApplicationManaged` (default, public) or `IamAuth`. Ask the user before choosing. A public endpoint has no AWS-layer auth or WAF: the app owns authentication, input validation, rate limiting and security headers, and CloudFront + AWS WAF in front adds L7 protection — see the checklist in [iam-and-security.md](iam-and-security.md) |
| `--auto-deployment-mode`, `--max-environments`, `--rate-limit`, `--description` | Endpoint settings, applied on create or when they differ from the existing endpoint |
| `--tags KEY=VAL` | Resource tags, on create only |
| `--include-hidden-files` | Include dotfiles in the bundle. They are left out by default, and `.env` is always left out |
| `--no-wait` | Return after the create or revision call instead of waiting for it to become active |

Run `aws lambda-web deploy help` for the complete list.

**Entry point.** `deploy` looks for `index.js`, `server.js` (and their `.mjs` / `.cjs` forms),
their `dist/` and `build/` variants, and `package.json` `main`. When the entry is not `index.js`
it adds a small `index.js` that imports it, because the runtime always loads `index.js`.

**Output.** With `--output json` the result carries `functionArn`, `endpointUrl` (a hostname,
without `https://`), `roleArn`, `bucketName`, `objectKey`, and on updates `revisionId`.
Progress lines go to stderr, so `--query endpointUrl --output text` gives a clean hostname for
scripts. `--no-wait` returns before the endpoint URL is known.

**A successful exit does not mean the app started.** The command waits for the revision and
endpoint to become `Active`, which happens even when the code fails to listen (see the
`LatestRevision` note above). Curl a real route after every deploy.

## Packaging

```bash
npm ci --omit=dev
zip -r function.zip index.js package.json node_modules/ public/ \
  -x "*.test.*" -x ".git/*" -x ".env" -x "node_modules/.cache/*"
```

Include: `index.js`, package.json, node_modules/, public/. See Service Limits in [SKILL.md](../SKILL.md) for the package size cap.

**If you have a build step** (esbuild for JSX or TypeScript), build *before* pruning. `npm ci --omit=dev` deletes the bundler along with the other devDependencies, so a later `npm run build` fails with `esbuild: command not found`:

```bash
npm install        # devDependencies included
npm run build      # produces index.js
zip -r function.zip index.js
```

A bundled `index.js` inlines its dependencies, so it needs no `node_modules/` in the zip at all.

## Code Source

Code always comes from S3 — `codeConfig.s3Object` is the only source, and it is required.

```json
"codeConfig": {"s3Object": {"bucket": "{bucket}", "key": "{name}/function.zip", "versionId": "{version}"}}
```

`versionId` is optional and works the same way on `create-web-function` and `create-web-function-revision`, so you can deploy updated code by re-uploading to the same key and passing the new version instead of changing the key.

## RevisionConfig Fields

`description` and `kmsKeyArn` are optional on both create commands, but they are passed differently: inside `--revision-config` for `create-web-function`, and as separate `--description` / `--kms-key-arn` flags for `create-web-function-revision`, which takes no `--revision-config`.

| Field | Purpose |
|-------|---------|
| `description` | Free-text label for the revision (helps identify revisions in `list-web-function-revisions`) |
| `kmsKeyArn` | Customer-managed KMS key ARN to encrypt the code artifact / environment variables (defaults to an AWS-managed key if unset) |

```json
"revisionConfig": {
  "description": "Add /metrics endpoint",
  "kmsKeyArn": "arn:aws:kms:{region}:{account}:key/{key-id}",
  "buildConfig": { "...": "..." },
  "serviceConfig": { "...": "..." }
}
```

## EndpointConfig Reference

| Field | Required | Values |
|-------|----------|--------|
| endpointName | Yes | Any string (typically "default") |
| endpointType | Yes | `HomeRegion`, `MultiRegion`, `PerRegion` |
| authType | Yes | `ApplicationManaged`, `IamAuth` |
| autoDeploymentMode | No | `LatestRevision` (default), `Disabled` |
| revisionWeights | Conditional | Required when `autoDeploymentMode` is `Disabled`, and rejected when it is `LatestRevision`. Array of 1–2 `{"revisionId", "weight"}` entries — revision IDs must be unique, each weight is 1–100, and the weights must sum to exactly 100. |
| regions | Conditional | The home region is always added automatically. For `HomeRegion`, omit it or list only the home region; any other region is rejected. For `MultiRegion` / `PerRegion`, at least 2 distinct regions are required — listing the home region alongside the others is fine, so it is enough to add 1 other region. |
| scalingConfig | No | `{"maxEnvironments": N}` — max concurrent execution environments for the endpoint. |
| throttleConfig | No | `{"rateLimit": N}` — max requests per second for the endpoint. |

> **Constraint:** `MultiRegion` and `PerRegion` endpoints require `autoDeploymentMode: Disabled`. `LatestRevision` is only supported for `HomeRegion` endpoints.

## Timeout

Request timeout is configurable via `serviceConfig.timeoutSeconds` (see Service Limits in [SKILL.md](../SKILL.md) for the range and default). Changing this requires a new revision.

```json
"serviceConfig": {
  "executionRoleArn": "...",
  "timeoutSeconds": 120
}
```

## Concurrency

Each execution environment handles multiple concurrent requests. Write thread-safe application code — avoid global mutable state.

Configure a non-default concurrency limit via `serviceConfig.maxConcurrencyPerEnvironment` (see Service Limits in [SKILL.md](../SKILL.md) for the range and default). Changing this requires a new revision.

```json
"serviceConfig": {
  "executionRoleArn": "...",
  "maxConcurrencyPerEnvironment": 64
}
```

See [scaling-and-concurrency.md](./scaling-and-concurrency.md) for more details.

## Endpoint Scaling and Throttling

Concurrency above is configured on the revision; these two are configured on the endpoint, so they can be changed with `update-web-function-endpoint` without creating a revision.

```json
{
    "scalingConfig": {"maxEnvironments": 20},
    "throttleConfig": {"rateLimit": 1000}
}
```

See [scaling-and-concurrency.md](./scaling-and-concurrency.md) for more details.

## Environment Variables

Set via `serviceConfig.environmentVariables` (**not** buildConfig — this is a common mistake). Changing this requires a new revision.

```json
"serviceConfig": {
  "executionRoleArn": "...",
  "environmentVariables": {"TABLE_NAME": "my-table", "NODE_ENV": "production"}
}
```

**Important UX notes:**

- There is no standalone "update env vars" command. Changing any environment variable requires creating a new revision with the full `--build-config` + `--service-config`.
- Keys starting with `AWS_LAMBDA_` are reserved and will be rejected with `InvalidParameterValueException`.
- **`NODE_ENV: production` is a Node.js optimization flag, not a deployment-stage label.**
  Express caches view templates and returns the status-code message instead of `err.stack`
  only when it is exactly `production`; libraries test `=== 'production'`, so `staging`
  silently selects the development path and leaks stack traces to callers. Keep it
  `production` in deployed revisions — see
  [Express: Set NODE_ENV to production](https://expressjs.com/en/advanced/best-practice-performance.html#set-node_env-to-production).
- **Do not put secrets here.** Environment variables are returned in plaintext by
  `get-web-function-revision`, so anyone with read access to the revision can read them.
  Keep API keys, database credentials and tokens in AWS Secrets Manager or SSM Parameter
  Store, pass only the secret name or parameter path as an environment variable, and fetch
  the value at runtime via the SDK. Grant the execution role read access to just that
  secret or parameter.

### Runtime-Injected Environment Variables

These are set by the runtime and readable from customer code (but not overridable):

| Env Var | Value | Purpose |
|---|---|---|
| `AWS_LAMBDA_HTTP_ENDPOINT` | `0.0.0.0:3000` | Host:port the runtime probes for HTTP readiness |
| `AWS_LAMBDA_INITIALIZATION_TYPE` | `native-http` | Distinguishes Web Functions from classic Lambda |
| `AWS_LAMBDA_METADATA_API` | `169.254.100.1:9001` | Internal metadata endpoint |
| `AWS_LAMBDA_METADATA_TOKEN` | *(unique per execution environment)* | Auth token for metadata API |
| `AWS_LAMBDA_RUNTIME_API` | `169.254.100.1:9001` | Runtime API endpoint |

## Logs

CloudWatch Logs, centralized to the function's home region. The log group and log levels are configurable via `serviceConfig.telemetryConfig.loggingConfig` (defaults to `/aws/lambda/web/{function-name}` at `INFO` if unset). Each function also gets a `{logGroup}.local` group holding just the logs of the region that served them. See [observability.md](observability.md) for the full logging config.
