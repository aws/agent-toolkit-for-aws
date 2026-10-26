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

- Path in `/usr/local/lib/python*/site-packages/` or similar Python location → the old Starter Toolkit is shadowing the new CLI. Uninstall it (see below).
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

**If the project was created by CLI v0** (`agentcore/agentcore.json` has `"version": 1`): v1 runs it in compatibility mode and blocks `add`/`remove`/`build`. Run `agentcore migrate` to convert it — see the main `agents-debug` skill, Step 1.

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
aws bedrock list-foundation-models \
  --region $(aws configure get region) \
  --query 'modelSummaries[?contains(modelId, `claude`) && modelLifecycle.status==`ACTIVE`].modelId' \
  --output table
```

If no Claude models appear, or if you see access errors:

1. Go to AWS Console → Amazon Bedrock → Model access
2. Click "Manage model access"
3. Enable "Anthropic Claude" models
4. Click "Save changes" — access is usually granted within a minute

**Required model for default projects:** The default model is a cross-region inference profile (e.g., `global.anthropic.claude-sonnet-5-5` — the CLI's Bedrock templates scaffold `global.` by default). The `global.` prefix routes to any commercial region; geographic prefixes (`us.`, `eu.`, `apac.`) keep inference within that geography. All prefixes require model access enabled in every destination region the profile covers. For Runtime templates the model ID is in the agent code (e.g., `app/<name>/model/load.py`); for a harness it's in `app/<name>/harness.yaml`.

### Check 6: IAM permissions

```bash
aws iam simulate-principal-policy \
  --policy-source-arn $(aws sts get-caller-identity --query Arn --output text) \
  --action-names iam:CreateRole bedrock:InvokeModel \
  --resource-arns "*" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}'
```

For deploy to work, you need:

- `iam:CreateRole` — to create execution roles
- `bedrock:InvokeModel` — to call Bedrock models
- `ecr:CreateRepository`, `ecr:PutImage` — for container builds
- `codebuild:StartBuild` — for remote builds

If permissions are missing, ask your AWS admin to attach `BedrockAgentCoreFullAccess` and `AmazonBedrockFullAccess` managed policies to your IAM user or role.

### Check 7: Docker (optional — only needed to run Container runtimes locally)

```bash
docker --version
docker info 2>&1 | head -5
```

A runtime is a Container build when its folder has a `Dockerfile` (`"build": "Container"` in `agentcore.json`; the `agent-python-strands-container` template scaffolds one). A local container tool is only needed for `agentcore dev` on such a runtime. CodeZip runtimes (the default) don't need Docker at all.

**If Docker not running:**

- macOS: Start Docker Desktop
- Linux: `sudo systemctl start docker`

**Alternatives to Docker:** the CLI also accepts Podman and Finch (it tries `docker`, then `podman`, then `finch`). For Finch, run `finch vm init` first or you'll see `Finch is installed but its VM is not initialized`.

### Where the CLI logs

The CLI writes a debug log of every command to `~/.agentcore/logs/output-<YYYY-MM-DD>.log`. Check it when a command fails with a terse message.

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
⚠️  IAM permissions: missing iam:CreateRole — deploy will fail
❌ Docker: not running — needed only for `agentcore dev` on Container runtimes (optional)

Issues to fix:
1. IAM: Ask your admin to attach BedrockAgentCoreFullAccess to your user
2. Docker: Start Docker Desktop (only needed to run Container runtimes locally)

All clear? Run `agents-get-started` to create your first project.
```

## Output

- Checklist of all prerequisites with pass/fail status
- Exact fix command for each failing check
- Clear indication of what's blocking vs. what's optional
- Pointer to `agents-get-started` skill when environment is healthy
