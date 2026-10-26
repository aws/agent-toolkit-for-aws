# doctor

Check your environment and tell you exactly what's needed to use the AgentCore CLI.

## When to use

- `agentcore` command not found or CLI isn't behaving correctly
- `agentcore create` or `agentcore deploy` fails immediately with an environment error
- Developer isn't sure if their environment is configured correctly
- Something that used to work stopped working after an OS or tool update

Do NOT use for:

- Creating a new project or getting started → use `agents-get-started`
- Deploy failures that aren't environment-related (CDK errors, IAM) → use `agents-deploy`
- Agent runtime errors → use `agents-debug`

## Input

No arguments required.

## Process

Run each check and report the result. For anything missing, give the exact fix command — don't just say "install X."

### Check 1: AgentCore CLI

```bash
agentcore --version
```

**If the command errors instead of returning a version:**

Run `which agentcore` to see what's installed:

- A Python-tool path — a `.../bin/agentcore` from pip, pipx, or `uv tool` (e.g. `~/.local/bin/agentcore`, a virtualenv's `bin/`) → the old Starter Toolkit is shadowing the new CLI. Uninstall it (see below).
- Path in a Node.js-based location but still errors → the Node.js version may be wrong. Continue to Check 2.
- No path returned → the CLI isn't installed.

**If not found:**

```bash
npm install -g @aws/agentcore
```

Requires Node.js 20.12 or later. If `npm` isn't available, install Node.js first: https://nodejs.org

**If the version is below 1.0.0:** the skills assume CLI v1. Upgrade with:

```bash
npm install -g @aws/agentcore@latest
# or, from an installed CLI:
agentcore update
```

`agentcore update --check` reports whether an update is available without installing it.

**If the project was created by CLI v0** (`agentcore/agentcore.json` has `"version": 1`): v1 runs it in compatibility mode and blocks `add`/`remove`/`build`/`export`. Commit first (`git add -A && git commit`): migrate refuses a dirty git tree even to print the plan, and a fresh v0 project starts dirty. Then run `agentcore migrate` to print the plan (nothing changes), show it to the developer, and only after they approve run `agentcore migrate --yes` (`--target <name>` if deployed to several). In an agent's non-TTY shell it never prompts.

**If old Starter Toolkit is installed** (Python-based `agentcore` command):

```bash
# Uninstall the old CLI first
pip uninstall bedrock-agentcore-starter-toolkit
# or: pipx uninstall bedrock-agentcore-starter-toolkit
# or: uv tool uninstall bedrock-agentcore-starter-toolkit

# Then install the new CLI
npm install -g @aws/agentcore
```

### Check 2: Node.js version

```bash
node --version
```

Requires Node.js 20.12 or later (the package's `engines.node` is `>=20.12.0`). If older:

- macOS: `brew install node` or download from https://nodejs.org
- Linux: use `nvm install 22` (https://github.com/nvm-sh/nvm)

`npm` is also required: `agentcore create` runs `npm install` for the project's CDK app (unless `--skip-install`), deploy runs the CDK app, and TypeScript runtimes install and run with npm. A missing tool shows up as `'npm' was not found on your PATH. Install Node.js: https://nodejs.org/`.

### Check 3: uv (Python package manager)

```bash
uv --version
```

`uv` manages Python virtual environments for your agent code. It's required for Python templates and Python runtimes (`agentcore create` runs `uv sync`, `agentcore dev` runs the agent with `uv run`). TypeScript-only projects don't need it. A missing `uv` shows up as `'uv' was not found on your PATH. Install uv: https://docs.astral.sh/uv/getting-started/installation/`.

**If not found:**

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip
pip install uv

# Or via Homebrew
brew install uv
```

After installing, restart your terminal or run `source ~/.bashrc` (or `~/.zshrc`).

**git** is also checked by `agentcore create` (it initializes a repository) unless you pass `--skip-git`.

### Check 4: AWS credentials

```bash
aws sts get-caller-identity
```

**If AWS CLI not found:**

```bash
# macOS
brew install awscli

# Or download from https://aws.amazon.com/cli/
```

**If credentials not configured:**

```bash
aws configure
# Enter: AWS Access Key ID, Secret Access Key, default region, output format
```

**If using SSO:**

```bash
aws sso login --profile your-profile
```

**Check the region:** The CLI resolves the region from `--region`, then `AWS_REGION`, `AWS_DEFAULT_REGION`, the active profile, and finally `us-east-1`. It must match the region where you've enabled Bedrock model access and where you'll deploy. The first `agentcore deploy` records the account and region as the `default` entry in `agentcore/aws-targets.json`.

### Check 5: Bedrock model access

```bash
# Same region fallback the CLI uses (aws configure get region is empty when the region comes from AWS_REGION)
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}; REGION=${REGION:-us-east-1}

# The project's model is an inference profile (global./us./eu./apac.), which list-foundation-models doesn't show
aws bedrock get-inference-profile --region "$REGION" \
  --inference-profile-identifier global.anthropic.claude-sonnet-5-5 \
  --query '{id:inferenceProfileId,status:status}'

# Foundation models behind the profiles
aws bedrock list-foundation-models --region "$REGION" \
  --query 'modelSummaries[?contains(modelId, `claude`) && modelLifecycle.status==`ACTIVE`].modelId' \
  --output table
```

Substitute the model ID the project actually uses (see below). If the profile isn't found, no Claude models appear, or you see access errors:

1. Go to AWS Console → Amazon Bedrock → Model access
2. Click "Manage model access"
3. Enable "Anthropic Claude" models
4. Click "Save changes" — access is usually granted within a minute

**Required model for default projects:** The default model is a cross-region inference profile (e.g., `global.anthropic.claude-sonnet-5-5` — the CLI's Bedrock templates scaffold `global.` by default). The `global.` prefix routes to any commercial region; geographic prefixes (`us.`, `eu.`, `apac.`) keep inference within that geography. All prefixes require model access enabled in every destination region the profile covers. For Runtime templates the model ID is in the agent code (e.g., `app/<name>/model/load.py`); for a harness it's in `app/<name>/harness.yaml`.

### Check 6: IAM permissions

```bash
# simulate-principal-policy needs an IAM ARN, not the STS assumed-role ARN that SSO and
# assumed-role credentials return. get-role also supplies the path (SSO roles live under
# /aws-reserved/sso.amazonaws.com/), so don't build the role ARN by hand.
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
case "$CALLER_ARN" in
  *:assumed-role/*) PRINCIPAL_ARN=$(aws iam get-role --role-name "$(echo "$CALLER_ARN" | cut -d/ -f2)" --query Role.Arn --output text) ;;
  *) PRINCIPAL_ARN="$CALLER_ARN" ;;
esac

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=<REGION>

aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names sts:AssumeRole \
  --resource-arns "arn:aws:iam::${ACCOUNT}:role/cdk-*" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}'

# Concrete actions: simulating a literal 'cloudformation:*' always returns implicitDeny
aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names cloudformation:DescribeStacks cloudformation:CreateChangeSet cloudformation:DescribeChangeSet \
    cloudformation:ExecuteChangeSet cloudformation:DeleteChangeSet cloudformation:GetTemplate \
    cloudformation:DeleteStack cloudformation:DescribeStackEvents \
  --resource-arns "arn:aws:cloudformation:${REGION}:${ACCOUNT}:stack/AgentCore-*" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}'

aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names cloudformation:DescribeStacks \
  --resource-arns "arn:aws:cloudformation:${REGION}:${ACCOUNT}:stack/CDKToolkit/*" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}'

aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names bedrock:InvokeModel \
  --resource-arns "*" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}'
```

For deploy to work, you need:

- `sts:AssumeRole` on the CDK bootstrap roles (`cdk-*`) — CDK deploys and publishes assets through them
- CloudFormation on the `AgentCore-*` stacks (the actions above) — the project stack is `AgentCore-<project>-<target>`; CloudFormation creates the execution roles under that stack name, so you don't need `iam:CreateRole` yourself
- `cloudformation:DescribeStacks` on `stack/CDKToolkit/*` — every deploy reads the bootstrap stack
- With credentials in the project: `bedrock-agentcore:{Create,Get,Update}{ApiKey,Oauth2}CredentialProvider` and Secrets Manager — the CLI provisions credential providers itself
- For Transaction Search (best effort): `xray:UpdateTraceSegmentDestination` and `logs:PutResourcePolicy` — if denied, deploy prints `skipping Transaction Search: ...` and continues
- Permission to create the `CDKToolkit` bootstrap stack (CloudFormation, IAM, S3, ECR, SSM) the first time an account/region is used, unless an admin has already bootstrapped it
- `bedrock:InvokeModel` — to call Bedrock models from `agentcore dev`

`BedrockAgentCoreFullAccess` and `AmazonBedrockFullAccess` are broad and still don't grant the CDK bootstrap-role or CloudFormation access above. Ask your AWS admin for those specifically, scoped to the ARNs shown.

### Check 7: Docker (optional — only needed to run Container runtimes locally)

```bash
docker --version
docker info --format '{{.ServerVersion}}'   # prints a version only if the daemon is running
```

A runtime is a Container build when its folder has a `Dockerfile` (`"build": "Container"` in `agentcore.json`; the `agent-python-strands-container` template scaffolds one). A local container tool is only needed for `agentcore dev` on such a runtime. CodeZip runtimes (the default) don't need Docker at all.

**If Docker not running:**

- macOS: Start Docker Desktop
- Linux: `sudo systemctl start docker`

**Alternatives to Docker:** the CLI also accepts Podman and Finch (it tries `docker`, then `podman`, then `finch`). For Finch, run `finch vm init` first or you'll see `Finch is installed but its VM is not initialized`.

### Where the CLI logs

The CLI writes a debug log of every command to `~/.agentcore/logs/output-<YYYY-MM-DD>.log`. Check it when a command fails with a terse message. The file is shared by every CLI session that day, so filter to the run you care about by its `cliSessionId` field, e.g. `jq -c 'select(.cliSessionId=="<ID>")' ~/.agentcore/logs/output-$(date +%Y-%m-%d).log` (take the ID from the last lines of the file).

---

## Summary output format

Report results as a clear checklist:

```
AgentCore Environment Check

✅ AgentCore CLI: 1.0.0
✅ Node.js: v22.11.0
✅ uv: 0.4.18
✅ AWS credentials: configured (account: 123456789012, region: us-east-1)
✅ Bedrock model access: Claude models enabled
⚠️  IAM permissions: can't assume cdk-* bootstrap roles — deploy will fail
❌ Docker: not running — needed only for `agentcore dev` on Container runtimes (optional)

Issues to fix:
1. IAM: Ask your admin for sts:AssumeRole on arn:aws:iam::<ACCOUNT>:role/cdk-* and cloudformation:* on AgentCore-* stacks
2. Docker: Start Docker Desktop (only needed to run Container runtimes locally)

All clear? Run `agents-get-started` to create your first project.
```

## Output

- Checklist of all prerequisites with pass/fail status
- Exact fix command for each failing check
- Clear indication of what's blocking vs. what's optional
- Pointer to `agents-get-started` skill when environment is healthy
