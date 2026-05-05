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

Requires Node.js 20+. If `npm` isn't available, install Node.js first: https://nodejs.org

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

Requires Node.js 20.x or later. If older:

- macOS: `brew install node` or download from https://nodejs.org
- Linux: use `nvm install 20` (https://github.com/nvm-sh/nvm)

### Check 3: uv (Python package manager)

```bash
uv --version
```

`uv` manages Python virtual environments for your agent code. It's required for Python agents.

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

**Check the region:** The region in `aws configure` must match the region where you've enabled Bedrock model access and where you'll deploy.

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

**Required model for default projects:** The default model is a cross-region inference profile (e.g., `global.anthropic.claude-sonnet-4-5-20250929-v1:0` — the CLI scaffolds `global.` by default). The `global.` prefix routes to any commercial region; geographic prefixes (`us.`, `eu.`, `apac.`) keep inference within that geography. All prefixes require model access enabled in every destination region the profile covers. Check `agentcore.json` after `agentcore create` for the exact model ID used.

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

### Check 7: Docker (optional — only needed for Container builds)

```bash
docker --version
docker info 2>&1 | head -5
```

Docker is only required if you're using `--build Container`. CodeZip builds (the default) don't need Docker locally — they use AWS CodeBuild.

**If Docker not running:**

- macOS: Start Docker Desktop
- Linux: `sudo systemctl start docker`

**Alternatives to Docker:** AgentCore also supports Podman and Finch.

---

## Summary output format

Report results as a clear checklist:

```
AgentCore Environment Check

✅ AgentCore CLI: 0.9.1
✅ Node.js: v20.11.0
✅ uv: 0.4.18
✅ AWS credentials: configured (account: 123456789012, region: us-east-1)
✅ Bedrock model access: Claude models enabled
⚠️  IAM permissions: missing iam:CreateRole — deploy will fail
❌ Docker: not running — needed for Container builds (optional)

Issues to fix:
1. IAM: Ask your admin to attach BedrockAgentCoreFullAccess to your user
2. Docker: Start Docker Desktop (only needed for Container builds)

All clear? Run `agents-get-started` to create your first project.
```

## Output

- Checklist of all prerequisites with pass/fail status
- Exact fix command for each failing check
- Clear indication of what's blocking vs. what's optional
- Pointer to `agents-get-started` skill when environment is healthy
