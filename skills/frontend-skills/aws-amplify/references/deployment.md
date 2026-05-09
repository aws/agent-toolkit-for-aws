# Deployment

> **Prerequisites:** Backend defined in `amplify/backend.ts` with `defineBackend({ auth, data })`.

## Prerequisites

Before deploying, verify:

- `npx ampx --version` returns a valid version
- `aws sts get-caller-identity` succeeds
- Node.js ≥ 18.x installed
- `.gitignore` includes `node_modules/`, `.env*`, `amplify_outputs.json`,
  `.amplify/`

**`amplify_outputs.json` is gitignored** — it is generated at build
time, NOT committed to source control:

- **Local dev:** `npx ampx sandbox` generates it automatically
- **CI/CD:** `npx ampx pipeline-deploy` generates it during the build phase
- **Other frontend apps in a monorepo:** Use
  `npx ampx generate outputs --app-id <backend-app-id>` to generate it
- Project is a Gen2 project (Gen2 uses `amplify/backend.ts` + `defineBackend()`)

## Sandbox Deployment

Deploy a personal development environment:

```bash
AWS_REGION=us-east-1 npx ampx sandbox --once
```

Use the `--once` flag in agent and CI environments — without
it, the command starts a file watcher that never exits. If prompted to
bootstrap, run `npx ampx sandbox --once` again after bootstrapping
completes.

Verify `amplify_outputs.json` was generated in the project root.

## CI/CD Setup

### Create the Amplify App

```bash
REPO="github.com/<user>/<repo>"
APP_ID=$(aws amplify create-app \
  --name my-app \
  --repository "$REPO" \
  --access-token "$(gh auth token)" \
  --query 'app.appId' --output text)
```

Use `github.com/user/repo` format — **not** `https://`.

### IAM Service Role

Create a dedicated role for Amplify backend deployments:

```bash
ROLE_NAME="AmplifyBackendRole-${APP_ID}"

# 1. Create the role with Amplify trust policy
aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "amplify.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

# 2. Attach the backend deploy policy
aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmplifyBackendDeployFullAccess

# 3. Attach the role to the app
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
aws amplify update-app --app-id "$APP_ID" --iam-service-role-arn "$ROLE_ARN"
```

All three steps are required — missing the role causes
`AccessDeniedException` during deployment.

### Create Branch

```bash
aws amplify create-branch --app-id "$APP_ID" --branch-name main
```

### amplify.yml

Create `amplify.yml` in the project root. Set `baseDirectory` per
framework:

| Framework        | baseDirectory                 |
| ---------------- | ----------------------------- |
| Vite (React/Vue) | `dist`                        |
| CRA              | `build`                       |
| Next.js (export) | `out`                         |
| Next.js (SSR)    | `.next`                       |
| Angular          | `dist/<project-name>/browser` |

**Wrong `baseDirectory` = blank page in production** (silent failure).
Always match the framework table above.

```yaml
version: 1
backend:
  phases:
    build:
      commands:
        - npm ci --cache .npm --prefer-offline
        - npx ampx pipeline-deploy --branch $AWS_BRANCH --app-id $AWS_APP_ID
frontend:
  phases:
    build:
      commands:
        - npm ci
        - npm run build
  artifacts:
    baseDirectory: dist # Change per framework (see table above)
    files:
      - '**/*'
  cache:
    paths:
      - .npm/**/*
      - node_modules/**/*
```

> **Note:** `$AWS_BRANCH` and `$AWS_APP_ID` are automatically set by Amplify Hosting. For custom CI/CD pipelines (GitHub Actions, CodePipeline), set these manually or use your pipeline's equivalent variables.

### Monorepo Configuration

For monorepos, set `appRoot` in `amplify.yml` to the subdirectory
containing the Amplify app:

```yaml
appRoot: packages/web
```

**WARNING:** `appRoot` must have **NO leading slash**.
`appRoot: packages/web` (correct) vs `appRoot: /packages/web` (wrong)

Monorepo rules:

- Only **ONE** app runs `npx ampx pipeline-deploy`; other apps use
  `npx ampx generate outputs --app-id <backend-app-id>` to get their
  `amplify_outputs.json`.
- Run `npm ci` at the **repo root**, NOT inside `appRoot`.

### Trigger Deployment

```bash
aws amplify start-job --app-id "$APP_ID" --branch-name main --job-type RELEASE
```

## Secrets Management

**Sandbox:** Set secrets via CLI:

```bash
echo -n "<value>" | npx ampx sandbox secret set MY_API_KEY
```

> **Security:** Avoid passing secret values as CLI arguments or via `echo` — these appear in shell history and `/proc`. Instead, use `npx ampx sandbox secret set MY_SECRET` which prompts for input interactively, or pipe from a secure source: `aws ssm get-parameter --name /path/to/secret --with-decryption --query Parameter.Value --output text | npx ampx sandbox secret set MY_SECRET --from-stdin`

Pipe the value via stdin — without the pipe, the command
prompts interactively.

> **Important:** Use `echo -n` (no trailing newline) when piping values to `secret set`. (The documented approach uses an interactive prompt; piping with `echo -n` is a practical alternative for scripts.)

This stores the secret for your personal sandbox environment.
**Branch environments (production):** Secrets are managed through the **Amplify console** (App settings → Environment variables → Secrets), NOT via CLI. The `ampx sandbox secret` command only works for local sandbox environments.

Alternatively, use the AWS CLI for non-secret environment variables:

```bash
aws amplify update-app --app-id "$APP_ID" \
  --environment-variables MY_API_KEY=<value>
```

> **Important:** `--environment-variables` stores values as **plain text**.
> For sensitive values (API keys, tokens), use `npx ampx sandbox secret set`
> (sandbox) or `npx ampx secret set --branch` (production) which stores in
> SSM SecureString.
>
> **Note:** Under the hood, Amplify Gen2 `secret()` references are backed by AWS Systems Manager Parameter Store (SecureString parameters). Review access policies on the `/amplify/` parameter path in your account to ensure only authorized roles can read production secrets.

Reference secrets in functions using `secret()` — see
[functions-and-api.md](functions-and-api.md) for the pattern.

## Multi-Environment

Use branch-based environments — each Git branch deploys independently:

```bash
# Create a staging branch
git checkout -b staging
git push origin staging
aws amplify create-branch --app-id "$APP_ID" --branch-name staging
aws amplify start-job --app-id "$APP_ID" --branch-name staging --job-type RELEASE
```

Each branch gets isolated backend resources (Cognito pool, AppSync API,
DynamoDB tables). Set branch-specific secrets separately.

## Custom Domains

Associate a custom domain with the Amplify app:

```bash
aws amplify create-domain-association \
  --app-id "$APP_ID" \
  --domain-name example.com \
  --sub-domain-settings '[
    {"prefix": "", "branchName": "main"},
    {"prefix": "staging", "branchName": "staging"}
  ]'
```

Amplify auto-provisions an SSL certificate. Add the
provided CNAME records to your DNS for verification. Check status:

```bash
aws amplify get-domain-association --app-id "$APP_ID" --domain-name example.com
```

## Amplify Hosting

Amplify Hosting provides framework-aware builds with SSR support for
Next.js. The build pipeline auto-detects the framework from
`package.json`. For SSR apps, Amplify deploys a Lambda@Edge or
CloudFront function — no manual CloudFront configuration needed.

Production URL format: `https://<branch>.<app-id>.amplifyapp.com`

## Deployment Validation

After deployment, check job status with `aws amplify list-jobs --app-id "$APP_ID" --branch-name main --query 'jobSummaries[0].status'` and verify `amplify_outputs.json` endpoints match expected values.

## Post-Deployment

**Rollback:** Revert via Git and redeploy:

```bash
git revert HEAD --no-edit
git push origin main
# Amplify auto-triggers a new build from the push
```

For CI/CD, manually trigger: `aws amplify start-job --app-id "$APP_ID"
--branch-name main --job-type RELEASE`.

### `InvalidCredentialError: Failed to load default AWS region`

Despite the error name, this is a missing **region**, not a credential issue:

```bash
export AWS_REGION=us-east-1
```

### AppSync API Limit (25 per account)

Each sandbox creates an AppSync API. Frequent sandbox creation/deletion can leave orphaned APIs. If deployment fails with "LimitExceededException":

1. Check: AWS Console → AppSync → APIs → delete unused
2. Request limit increase via Service Quotas

## Links

- [Fullstack Branching](https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/)
- [Secrets and Variables](https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/secrets-and-vars/)
- [Mono and Multi-Repos](https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/mono-and-multi-repos/)
- [Custom Pipelines](https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/custom-pipelines/)
- [Sandbox Environments](https://docs.amplify.aws/react/deploy-and-host/sandbox-environments/)
- [Sandbox Setup](https://docs.amplify.aws/react/deploy-and-host/sandbox-environments/setup/)
