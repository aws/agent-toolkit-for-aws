# Remote Execution

Deploy and manage AWS Batch/Fargate infrastructure for ATX transformations at scale.
All Lambda calls are executed by you — users never interact with Lambdas directly.

Remote mode deploys to the user's own AWS account. Key resources:

- Results stored in S3 (`atx-custom-output-{accountId}`) with KMS encryption, 30-day lifecycle
- Source code uploaded to S3 (`atx-source-code-{accountId}`) with 7-day lifecycle
- CloudWatch dashboard: `ATX-Transform-CLI-Dashboard` for monitoring jobs
- 8 Lambda functions for job management (trigger, status, terminate, list)
- AWS Batch/Fargate for container execution — costs nothing when idle
- To find the account: `aws sts get-caller-identity --query Account --output text`

## Infrastructure Check

Before checking, determine the active AWS region (from `AWS_REGION`, `AWS_DEFAULT_REGION`,
or `aws configure get region`) and tell the user which region is being used.

Then check deployment status:

```bash
aws cloudformation describe-stacks --stack-name AtxInfrastructureStack \
  --query 'Stacks[0].StackStatus' --output text || echo "NOT_DEPLOYED"
```

If deployed (`CREATE_COMPLETE` or `UPDATE_COMPLETE`): proceed to job submission.
If `NOT_DEPLOYED` or any other status: get explicit user consent before deploying.

## User Consent Prompt

Explain what gets created: AWS Batch (Fargate), 8 Lambda functions, S3 buckets (KMS encrypted),
CloudWatch dashboard, IAM roles. If using the pre-built image, no Docker is needed and no ECR
repository is created in their account. If using a custom image, an ECR repository is created
and the container is built locally. One-time setup.
Do NOT deploy until user confirms.

## Deployment

### Pre-built vs Custom Image

The infrastructure supports two container modes:

**Pre-built image (default):** A public ECR image with Java (8, 11, 17, 21, 25),
Python (3.8–3.14), Node.js (16–24), Maven, Gradle, and common build tools.
No Docker required on the user's machine. Use this when the pre-built image
has everything the transformation needs (source runtime, target runtime, build
tools, and any other dependencies).

**Custom image (fallback):** If the transformation requires a language, tool, or
version not in the pre-built image, you clone the infrastructure repo,
customize the Dockerfile, and build locally. This requires Docker on the user's
machine.

You determine which mode to use during Step 6 (Verify Runtime Compatibility)
in SKILL.md. Do NOT ask the user to choose — you decide automatically based
on whether the pre-built image has everything needed for the transformation.

### Pre-built Image Runtimes

The pre-built image includes:

- **Java**: 8, 11, 17, 21, 25 (Amazon Corretto) with Maven and Gradle 9.4
- **Python**: 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14 (dnf + pyenv)
- **Node.js**: 16, 18, 20, 22, 24 (nvm) with yarn, pnpm, TypeScript, ts-node
- **Build tools**: gcc, g++, make, patch
- **CLI tools**: AWS CLI v2, ATX CLI, git, jq, curl, unzip, tar
- **OS**: Amazon Linux 2023 (x86_64)

If the transformation target is in this list, use the pre-built image path.

### Pre-built Image Path (No Docker Required)

Clone and run setup — Docker is NOT required:

```bash
ATX_INFRA_DIR="$HOME/.aws/atx/custom/remote-infra"
if [ -d "$ATX_INFRA_DIR" ]; then
  git -C "$ATX_INFRA_DIR" add -A
  git -C "$ATX_INFRA_DIR" commit -m "Local customizations" -q 2>/dev/null || true
  git -C "$ATX_INFRA_DIR" pull -q
else
  git clone -b atx-remote-infra --single-branch https://github.com/aws-samples/aws-transform-custom-samples.git "$ATX_INFRA_DIR"
fi
```

If `git pull` reports a merge conflict, resolve it by keeping both the upstream
changes and the user's customizations in the `CUSTOM LANGUAGES AND TOOLS` section
of the Dockerfile, then commit the merge.

Ensure `prebuiltImageUri` is set in `cdk.json` (it should be set to "public.ecr.aws/d9h8z6l7/aws-transform:latest" by default). Then deploy:

```bash
cd "$ATX_INFRA_DIR" && ./setup.sh
```

The setup script skips the Docker prerequisite check and container build when
`prebuiltImageUri` is configured. First deploy takes ~3-5 minutes (no image build).

### Custom Image Path (Docker Required)

If the transformation requires a runtime (source or target) or any other software not in the pre-built image,
clone/update the repo, clear the pre-built URI, customize the Dockerfile, and deploy:

```bash
ATX_INFRA_DIR="$HOME/.aws/atx/custom/remote-infra"
if [ -d "$ATX_INFRA_DIR" ]; then
  git -C "$ATX_INFRA_DIR" add -A
  git -C "$ATX_INFRA_DIR" commit -m "Local customizations" -q 2>/dev/null || true
  git -C "$ATX_INFRA_DIR" pull -q
else
  git clone -b atx-remote-infra --single-branch https://github.com/aws-samples/aws-transform-custom-samples.git "$ATX_INFRA_DIR"
fi

cd "$ATX_INFRA_DIR" && sed -i.bak 's|"prebuiltImageUri": ".*"|"prebuiltImageUri": ""|' cdk.json
```

Customize the Dockerfile (see Container Customization below), then deploy:

```bash
cd "$ATX_INFRA_DIR" && ./setup.sh
```

This path requires Docker installed and running. First deploy takes ~5-10 minutes
(container build). CDK auto-detects Dockerfile changes and rebuilds the image.

### Deployment Failures

If `setup.sh` fails, it prints the specific prerequisite that's missing. Fix that
one thing and re-run — the script is idempotent.

If deployment fails partway through (e.g., CloudFormation stack stuck in
`ROLLBACK_COMPLETE` or `UPDATE_ROLLBACK_FAILED`), run teardown first, then retry:

```bash
cd "$ATX_INFRA_DIR" && rm -f cdk.context.json && ./teardown.sh && ./setup.sh
```

This cleans up the half-deployed state, clears cached CDK context, and starts fresh.
The teardown script handles stacks in any state, including failed rollbacks.

### Attach IAM Policies

After deployment, generate and attach the runtime policy so the caller has
permissions to invoke Lambdas, upload/download from S3, use KMS, etc.:

```bash
cd "$ATX_INFRA_DIR" && npx ts-node generate-caller-policy.ts
```

This produces two JSON files in `$ATX_INFRA_DIR`:

- `atx-runtime-policy.json` — Day-to-day operations (Lambda invoke, S3, KMS, Secrets Manager, logs)
- `atx-deployment-policy.json` — One-time CDK deploy/destroy (CloudFormation, ECR, IAM, Batch, VPC)

Attach the runtime policy to the caller:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)

# Create the managed policy (ignore EntityAlreadyExists, fail on other errors)
if ! create_output=$(aws iam create-policy --policy-name ATXRuntimePolicy \
  --policy-document "file://$ATX_INFRA_DIR/atx-runtime-policy.json" 2>&1); then
  echo "$create_output" | grep -q "EntityAlreadyExists" \
    || { echo "Failed to create policy: $create_output" >&2; exit 1; }
fi

# Attach to the caller (handles IAM users, IAM roles, and SSO/assumed roles)
if echo "$CALLER_ARN" | grep -q ":user/"; then
  IDENTITY_NAME=$(echo "$CALLER_ARN" | awk -F'/' '{print $NF}')
  aws iam attach-user-policy --user-name "$IDENTITY_NAME" \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/ATXRuntimePolicy"
elif echo "$CALLER_ARN" | grep -Eq ":assumed-role/|:role/"; then
  ROLE_NAME=$(echo "$CALLER_ARN" | sed 's/.*:\(assumed-\)\{0,1\}role\///' | cut -d'/' -f1)
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/ATXRuntimePolicy"
fi
```

If the attachment fails (insufficient IAM permissions, or an SSO-managed role with
name starting with `AWSReservedSSO_`), inform the user:

- The policy JSON is at `$ATX_INFRA_DIR/atx-runtime-policy.json`
- They need their AWS administrator to create and attach it to their identity
- For SSO users, it must be added to their IAM Identity Center permission set

Verify the policy is working by invoking a Lambda:

```bash
aws lambda invoke --function-name atx-list-jobs --payload '{}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

If this succeeds, the runtime policy is active. If not, the attachment hasn't
taken effect yet — wait a few seconds and retry.

If the caller also needs to deploy/destroy infrastructure (not just run jobs),
repeat the above with `atx-deployment-policy.json` and policy name `ATXDeploymentPolicy`.

## Lambda Function Names

After deployment, the Lambda functions are available with these names:

- `atx-trigger-job` — Submit a single transformation job
- `atx-get-job-status` — Get status of a single job
- `atx-terminate-job` — Terminate a running job
- `atx-list-jobs` — List all jobs
- `atx-trigger-batch-jobs` — Submit a batch of jobs
- `atx-get-batch-status` — Get batch status
- `atx-terminate-batch-jobs` — Terminate all jobs in a batch
- `atx-list-batches` — List all batches

## MCP Configuration (Optional)

If the user has a local ATX MCP configuration, include it inline with job
submissions so the containers can use it. Check for a local config:

```bash
cat ~/.aws/atx/mcp.json 2>/dev/null
```

If it exists, include the contents as the `mcpConfig` field in the `atx-trigger-job`
or `atx-trigger-batch-jobs` payload. For example:

```bash
aws lambda invoke --function-name atx-trigger-job \
  --payload '{"source":"...","command":"...","jobName":"...","mcpConfig":<contents of mcp.json>}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

The MCP config travels with the job request — do NOT upload it separately via
`atx-configure-mcp`. Skip this step if no local MCP config exists.

## Job Submission

**Limits:** Maximum 512 repositories per session. Submit in batches of up to 128
jobs each via `atx-trigger-batch-jobs`. If you have more than 128 jobs, split them
into multiple Lambda calls (e.g., 500 repos = 4 calls of 128 + 128 + 128 + 116).
Each call returns its own `batchId` — track all of them for monitoring. AWS Batch
runs all jobs in a batch concurrently. If the total repo count exceeds 512, stop
and ask the user to reduce the list.

**Repo analysis:** Do NOT scan or inspect repository contents locally in remote
mode. The repos may not be available on the local machine. Let the user specify
which TDs to apply, or use the TD already selected in the plugin.

**Deployment failures:** If `setup.sh` or `cdk deploy` fails for any reason, run
`./teardown.sh` first to clean up the partial state, then retry `./setup.sh`.
Do not try to manually fix individual CloudFormation errors.

**Source restrictions:** The `source` field accepts HTTPS git URLs, SSH git URLs
(with `atx/ssh-key` configured), or S3 paths within the CDK-managed source bucket
(`atx-source-code-{account}`). The container's IAM role cannot read from arbitrary
S3 buckets. If the user provides zips in their own S3 bucket, copy them to the
managed source bucket first (see Step 1 in SKILL.md).

Single job:

```bash
aws lambda invoke --function-name atx-trigger-job \
  --payload '{"source":"<url-or-s3>","command":"atx custom def exec -n <td> -p /source/<project> -x -t","jobName":"<name>"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Batch:

```bash
aws lambda invoke --function-name atx-trigger-batch-jobs \
  --payload '{"batchName":"<name>","jobs":[{"source":"<url>","command":"atx custom def exec -n <td> -p /source/<project> -x -t","jobName":"<name>"}]}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

## SSH URL Handling

SSH git URLs (`git@github.com:org/repo.git` or `ssh://git@github.com/org/repo.git`)
are passed directly to the Lambda — the container clones them remotely. This requires
an SSH private key stored in Secrets Manager as `atx/ssh-key`. See Step 1 in SKILL.md
for setup instructions.

If the SSH key is not configured, the clone will fail inside the container. Do NOT
fall back to cloning locally — guide the user through SSH key setup instead.

## Polling

Poll every 60 seconds for the first 10 polls, then every 5 minutes after.
Report only on status change.

```bash
aws lambda invoke --function-name atx-get-job-status \
  --payload '{"jobId":"<id>"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout

aws lambda invoke --function-name atx-get-batch-status \
  --payload '{"batchId":"<id>"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

## Results Location

Do NOT download results locally. Results stay in S3. Present the S3 path to the user:

```
Results: s3://atx-custom-output-{account-id}/transformations/<job-name>/<conversation-id>/
  code.zip  — zipped transformed source code
  logs.zip  — ATX conversation logs
```

If the user explicitly asks to download, provide the command but let them run it:

```
aws s3 cp s3://atx-custom-output-{account-id}/transformations/<job-name>/<conversation-id>/code.zip ./code.zip
```

## Private Repository Access

**Note:** If the user has private repos, credentials should already be configured
during Step 1 (Collect Repositories) in SKILL.md. This section documents the
mechanism for reference.

The container fetches credentials from AWS Secrets Manager at startup. Three secret types:

**`atx/github-token`** — plain string GitHub PAT for private HTTPS repo cloning:

```bash
aws secretsmanager create-secret --name "atx/github-token" --secret-string "<token>"
```

**`atx/ssh-key`** — plain string SSH private key for private SSH repo cloning:

```bash
aws secretsmanager create-secret --name "atx/ssh-key" --secret-string "$(cat <path-to-your-private-key>)"
```

**`atx/credentials`** — JSON array of credential files for any tool/registry (see Container Customization below).

Setup (requires user consent):

1. Explain which secrets will be created in their AWS account
2. Get explicit confirmation and credentials from the user
3. Create the secret(s)
4. Container entrypoint auto-fetches at startup — no image rebuild needed
5. User can delete anytime: `aws secretsmanager delete-secret --secret-id "atx/github-token" --region "$REGION" --force-delete-without-recovery`

AWS credentials for ATX CLI are handled automatically by the IAM task role (refreshed every 45 min).

## Monitoring

CloudWatch dashboard: `ATX-Transform-CLI-Dashboard`

- Job Tracking: completion rates, success/failure trends
- Lambda Metrics: invocation counts, duration, errors
- Real-time Logs: stream transformation progress

Dashboard URL (construct dynamically using the caller's region):

```bash
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null)}}
REGION=${REGION:-us-east-1}
echo "https://${REGION}.console.aws.amazon.com/cloudwatch/home#dashboards/dashboard/ATX-Transform-CLI-Dashboard"
```

Include this link in the final output when remote execution completes.

## Container Customization

The default container includes Java (8, 11, 17, 21, 25), Python (3.8–3.14), Node.js
(16–24), Maven, Gradle, gcc/g++, make, and common build tools.

If a transformation requires a language or tool not included, you handle this
automatically during Step 6 (Verify Container Compatibility) — see SKILL.md. The
Dockerfile has a clearly marked `CUSTOM LANGUAGES AND TOOLS` section where new
`RUN` commands should be inserted. After editing, redeploy with `cd "$ATX_INFRA_DIR" && ./setup.sh` — CDK
auto-detects Dockerfile changes and rebuilds the image.

### Adding Languages or Tools

```dockerfile
# Example: Add Rust (install as atxuser so binaries land in /home/atxuser/.cargo)
USER atxuser
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
USER root
ENV PATH="/home/atxuser/.cargo/bin:$PATH"
```

### Private Package Registries

Credentials are fetched from AWS Secrets Manager at container startup — never baked into the image.

**`atx/github-token`** (plain string) — GitHub PAT for private repo cloning.

**`atx/credentials`** (JSON array) — Generic credential files for any tool or registry. Each entry writes a file into the container at startup:

```json
[
  {"path": "/home/atxuser/.npmrc", "content": "//npm.company.com/:_authToken=TOKEN"},
  {"path": "/home/atxuser/.m2/settings.xml", "content": "<settings>...</settings>"},
  {"path": "/home/atxuser/.config/pip/pip.conf", "content": "[global]\nindex-url = https://pypi.company.com/simple"},
  {"path": "/home/atxuser/.gem/credentials", "content": "---\n:rubygems_api_key: KEY", "mode": "0600"},
  {"path": "/home/atxuser/.cargo/credentials.toml", "content": "[registry]\ntoken = \"TOKEN\""},
  {"path": "/home/atxuser/.nuget/NuGet.Config", "content": "<?xml version=\"1.0\"?>..."}
]
```

Create the secret:

```bash
aws secretsmanager create-secret --name "atx/credentials" \
  --secret-string '[{"path":"/home/atxuser/.npmrc","content":"//npm.company.com/:_authToken=TOKEN"}]'
```

This works for any language or tool added to the Dockerfile — npm, Maven, pip, RubyGems, Cargo, NuGet, etc. The `mode` field is optional (defaults to `0644`).

### Version Switching at Runtime

The container supports runtime version switching via environment variables passed as container overrides.
The `environment` field on the job MUST match the exact target version of the
transformation — not the closest available version. For example, if upgrading to
Java 23, set `"JAVA_VERSION":"23"` (not `"21"`). If the target version was added
to the Dockerfile and entrypoint per Step 6, the switcher will activate it.

Via Lambda (recommended):

```bash
aws lambda invoke --function-name atx-trigger-job \
  --payload '{"source":"...","jobName":"...","command":"atx ...","environment":{"JAVA_VERSION":"23","NODE_VERSION":"22","PYTHON_VERSION":"3.13"}}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Via direct Batch submission:

```bash
aws batch submit-job \
  --container-overrides '{
    "environment": [
      {"name": "JAVA_VERSION", "value": "23"},
      {"name": "PYTHON_VERSION", "value": "3.13"},
      {"name": "NODE_VERSION", "value": "22"}
    ]
  }' ...
```

Available: Java 8/11/17/21/25, Python 3.8–3.14, Node.js 16/18/20/22/24.
Python accepts both short (`13`) and full (`3.13`) formats.

See `$ATX_INFRA_DIR/container/README.md` for full customization reference including Docker BuildKit secrets for secure credential handling.

## Pricing

Do NOT quote specific prices or cost estimates to the user. If the user asks about
pricing, direct them to: https://aws.amazon.com/transform/pricing/

The remote infrastructure (Batch, Lambda, S3) has no fixed costs — all services are
pay-per-use and cost nothing when idle.

## Cleanup

The remote infrastructure costs nothing when idle — Fargate is pay-per-task,
Lambdas are pay-per-invoke, and S3 storage is minimal.

After every remote execution completes (all jobs finished or failed), prompt the
user with the following:

> Your remote infrastructure is still deployed in your AWS account. All services
> are pay-per-use only — there are no fixed costs when idle. You can leave it in
> place for future transformations, or tear it down now.
>
> For pricing details: https://aws.amazon.com/transform/pricing/
>
> If you tear down:
>
> - All ATX resources are completely removed from your account
> - KMS key deletion is scheduled (7-day AWS minimum wait)
> - S3 buckets, secrets, IAM policies, log groups — all deleted
> - You'll need to re-run setup (~5-10 min) next time you use remote mode
>
> Would you like to keep the infrastructure or tear it down?

If the user chooses to tear down:

```bash
cd "$ATX_INFRA_DIR" && ./teardown.sh
```

If the user chooses to keep it, confirm: "Infrastructure will stay deployed. Next
time you run remote transformations, everything will be ready immediately."
