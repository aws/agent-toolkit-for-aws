---
name: agents-deploy
description: >
  Use when deploying your agent to AWS, or when a deploy has failed.
  Handles pre-flight checks, local builds, CDK/IAM/quota error diagnosis,
  deployment targets, version management, rollback, and teardown.
  Triggers on: "deploy my agent", "agentcore deploy", "agentcore build",
  "deploy failed", "CDK error", "rollback", "canary deploy", "pin
  version", "redeploy", "deploy stuck", "deployment target".
  Not for production hardening — use agents-harden. Not for adding
  capabilities before deploy — use agents-build or agents-connect.
  Not for VPC configuration errors — use agents-build.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  requires-cli: ">=1.0.0"
---

# deploy

Deploy your AgentCore agent to AWS, or diagnose why a deploy failed.

## When to use

- You're ready to deploy and want to check config first
- `agentcore deploy` failed with an error
- You want to build the deployable artifacts locally without deploying
- You want to deploy to a specific target (staging, production)
- You need to roll back to a previous version, pin to a specific version, or set up a canary
- You want to remove resources or tear a deployment down

## Input

`$ARGUMENTS` is optional:

```
/agents-deploy                     # interactive — pre-flight check or diagnose failure
/agents-deploy preflight           # check config, account, and region before deploying
/agents-deploy diagnose            # diagnose a failed deploy (paste error or read logs)
/agents-deploy preview             # build and synthesize locally without deploying
/agents-deploy rollback            # roll back to a previous version
```

## Process

### Step 0: Verify CLI version

Run `agentcore --version`. This skill requires v1.0.0 or later. If the version is older, tell the developer to run `npm install -g @aws/agentcore@latest` (or `agentcore update`) before proceeding.

If `agentcore/agentcore.json` has no `"version": 2`, it's a v0 project. v1 deploys it in compatibility mode (it runs the latest v0 CLI's deploy) but blocks `agentcore build` and most project changes. Migrating keeps deployed resources. Run `agentcore migrate` to print the plan (nothing changes), show it to the developer, and only after they approve run `agentcore migrate --yes` (`--target <name>` if deployed to several). Commit first: migrate refuses a dirty git tree. In an agent's non-TTY shell it never prompts.

### Step 1: Determine the situation

Read `agentcore/agentcore.json` and `agentcore/aws-targets.json` if they exist.

Ask (or infer from context):

> "Are you:
>
> 1. About to deploy and want to check everything first
> 2. Dealing with a failed deploy — what error did you see?
> 3. Needing to roll back or pin a specific version?"

If the developer needs versioning, rollback, or canary deployment, load [`references/versioning.md`](references/versioning.md) and follow its instructions.

---

## Path A: Pre-flight validation

Run these checks before `agentcore deploy`:

### Check 1: Build locally

Show the developer this command to run:

```bash
agentcore build
```

`build` brings each Runtime's entry in `agentcore.json` up to date with its code (build type, runtime version, entrypoint — it prints what changed), checks each Runtime's folder has what its build needs (`pyproject.toml` + entrypoint, `package.json` + `main.ts`, or a `Dockerfile`), validates `agentcore.json` and any `harness.yaml`, and synthesizes the CDK app into `agentcore/cdk/cdk.out/` (one `AgentCore-<project>-<target>.template.json` per target, or a single `AgentCore-<project>` template before the first deploy). Nothing is deployed — malformed config fails here. One caveat: a project with credentials (`agentcore add credentials ...`) can't fully build until a first deploy has provisioned them; the CLI says so.

There's no separate `validate` command and no `--dry-run` / `--diff` flag on `deploy` in v1. `agentcore build` checks and synthesizes but shows no diff. To see what a deploy would change in an already-deployed target, diff the synthesized template against the live stack with the CDK app's own CDK CLI:

```bash
agentcore build
cd agentcore/cdk && node node_modules/aws-cdk/bin/cdk diff --app cdk.out AgentCore-<project>-<target>
```

Don't use `npx cdk` inside `agentcore/cdk/`: the vended `package.json` declares its own `"bin": {"cdk": ...}`, so `npx cdk` runs the project's CDK app instead of the CDK CLI. `cdk.out/` isn't cleaned between builds, so ignore stale template files for targets you no longer have.

### Check 2: Verify account and region

`agentcore deploy` deploys to the target named by `--target` (default `default`) in `agentcore/aws-targets.json`, using **that target's account and region**. The `--region` flag doesn't override a target's region.

- **No `default` target yet** (fresh project, `aws-targets.json` is `[]`): the first `agentcore deploy` creates it from the active credentials' account (STS) and the CLI's region — `--region`, then `AWS_REGION` / `AWS_DEFAULT_REGION`, then the active profile, then `us-east-1`. Check that's the account and region the developer intends *before* the first deploy.
- **Target exists:** the active credentials must belong to the target's `account`, or deploy stops with "Deployment target '…' expects AWS account …, but the active credentials belong to …".

Show the developer these commands to verify:

```bash
# The account you're actually authenticated as
aws sts get-caller-identity

# The region the CLI would use for a new default target
echo "${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}"

# Existing deployment targets
cat agentcore/aws-targets.json
```

### Check 3: Verify Bedrock model access

Show the developer this command to check enabled models in the target region:

```bash
# The target's region, or the CLI's fallback chain for a first deploy
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}; REGION=${REGION:-us-east-1}

# The scaffolded model is an inference profile, which list-foundation-models doesn't list
aws bedrock get-inference-profile --region "$REGION" \
  --inference-profile-identifier <MODEL_ID> \
  --query '{id:inferenceProfileId,status:status}'

# Foundation models behind it
aws bedrock list-foundation-models --region "$REGION" \
  --query 'modelSummaries[?modelLifecycle.status==`ACTIVE`].modelId' \
  --output table
```

Cross-region inference profile IDs use a geographic prefix (`us.`, `eu.`, `apac.`) or `global.` to control where inference runs. The CLI scaffolds `global.` by default (e.g., `global.anthropic.claude-sonnet-5-5`), which routes to any commercial region. Geographic prefixes keep inference within that geography (e.g., `eu.` stays in EU regions). All prefixes require model access enabled in every destination region the profile covers. Check the Bedrock docs for which regions are included in each profile prefix.

For Runtimes the model ID is in code (`app/<name>/model/load.py` or `load.ts`); for a Harness it's `model.*.modelId` in `app/<name>/harness.yaml`.

### Check 4: Verify IAM permissions

Show the developer the permissions needed and this verification command:

```bash
# SSO and assumed-role credentials return an STS ARN, which simulate-principal-policy rejects
# ("Invalid ARN"). Resolve the IAM role ARN, including its path (SSO roles live under
# /aws-reserved/sso.amazonaws.com/), with get-role.
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
case "$CALLER_ARN" in
  *:assumed-role/*) PRINCIPAL_ARN=$(aws iam get-role --role-name "$(echo "$CALLER_ARN" | cut -d/ -f2)" --query Role.Arn --output text) ;;
  *) PRINCIPAL_ARN="$CALLER_ARN" ;;
esac

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=<REGION>

# CDK deploys through the bootstrap roles (cdk-<qualifier>-deploy-role-..., cdk-...-file-publishing-role-...)
aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names sts:AssumeRole \
  --resource-arns "arn:aws:iam::${ACCOUNT}:role/cdk-*" \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table

# The project stack is AgentCore-<project>-<target>
aws iam simulate-principal-policy \
  --policy-source-arn "$PRINCIPAL_ARN" \
  --action-names 'cloudformation:*' \
  --resource-arns "arn:aws:cloudformation:${REGION}:${ACCOUNT}:stack/AgentCore-*" \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
```

You don't need to pre-check IAM role names: the execution roles are created by CloudFormation under the stack name (`AgentCore-<project>-<target>-...`), through the CDK deploy role. If the account/region isn't bootstrapped yet, the deploying identity also needs permission to create the `CDKToolkit` bootstrap stack (CloudFormation, IAM, S3, ECR, SSM).

### Run the deploy

```bash
agentcore deploy                          # deploy to the default target
agentcore deploy --target staging         # deploy to a named target
agentcore deploy --json                   # machine-readable result; progress stays on stderr
agentcore deploy --debug                  # debug logging
```

A deploy:

1. Verifies the AWS account against the target (creating the `default` target on first deploy)
2. Syncs Runtime builds from code, provisions credential providers (`agentcore add credentials ...`), and synthesizes the CDK app
3. Enables CloudWatch Transaction Search (best effort; turn off with `agentcore config transactionSearch false`)
4. Bootstraps CDK in the target account/region if needed
5. Deploys the stack `AgentCore-<project>-<target>` (container images are built in AWS CodeBuild — no local Docker needed)

There's no confirmation prompt on a normal deploy. `--yes` is only needed when the project declares no resources and the deploy would delete the target's stack (see [Removing resources and tearing down](#removing-resources-and-tearing-down)).

After a successful deploy the CLI suggests `agentcore invoke`. The stack ARN for each target is recorded in `agentcore/.cli/deployed-state.json`; commit that file (the generated `.gitignore` keeps it) so teammates' `status`, `invoke`, and `logs` find the deployment.

**Memory provisioning note:** If your project includes memory, deploy takes a few minutes longer while the memory resource becomes ACTIVE. This is normal — not an error. Check status:

```bash
agentcore status --json
```

Each resource is listed with `deploymentState` (`deployed` with its ARN, or `local-only` if the stack hasn't published it yet). For memory details, `agentcore memory get --id <MEMORY_ID>` (the ID is the last segment of the memory ARN).

---

## Path B: Diagnose a failed deploy

### Step B1: Read the error

If the developer pasted an error, diagnose it directly. If not, re-run with `--debug` or read the CLI's log file (JSON lines, one file per day; subprocess output such as CDK synth goes here):

```bash
ls -lt ~/.agentcore/logs/
tail -100 ~/.agentcore/logs/output-$(date +%Y-%m-%d).log
```

### Step B2: Match to known failure patterns

**IAM permission error:**

```
User: arn:aws:iam::123456789012:user/dev is not authorized to perform: iam:CreateRole
```

Fix: Attach the required IAM permissions (see Check 4 above). The deploying identity needs to assume the CDK bootstrap roles (`arn:aws:iam::<ACCOUNT>:role/cdk-*`) and manage the `AgentCore-*` CloudFormation stack; CloudFormation creates the execution roles itself. If the error names `iam:CreateRole` directly, the account likely isn't bootstrapped yet and the identity is creating the `CDKToolkit` stack.

**Account mismatch:**

```
Deployment target 'default' expects AWS account 111122223333, but the active credentials belong to 444455556666.
```

Fix: switch to credentials for the target's account (`AWS_PROFILE=...`), or deploy to a target that matches (`--target <name>`). Don't edit the account in `aws-targets.json` for a target that's already deployed unless you mean to deploy a fresh copy to the other account.

**No such target / no targets:**

```
Project 'MyProject' has no deployment target named 'staging'. .../agentcore/aws-targets.json defines: default.
```

Fix: only `default` is created automatically. Add named targets to `agentcore/aws-targets.json` (see [Deploying to multiple targets](#deploying-to-multiple-targets)).

**Unsupported region for the default target:**

```
Cannot create the default deployment target for project '…': '<region>' is not an AgentCore-supported region.
```

Fix: re-run with `--region <region>` or set `AWS_REGION` to an AgentCore region.

**CDK dependencies missing:**

```
CDK dependencies are missing for project '…'. Run 'npm install' in …/agentcore/cdk.
```

Fix: run `npm install` in `agentcore/cdk/` (common after creating a project with `--skip-install`, or a fresh clone).

**CDK library too old:**

```
This project uses @aws/agentcore-cdk <version>, but this CLI requires 1.0.0 or newer for full compatibility.
```

Fix: set `"@aws/agentcore-cdk": "1.0.0"` (or newer) in `agentcore/cdk/package.json`, run `npm install` in `agentcore/cdk/`, then build or deploy again.

**CDK bootstrap failure:**

The CLI bootstraps the target account/region automatically (`bootstrapping aws://<account>/<region>`). If that step fails, it's almost always permissions on the `CDKToolkit` stack (CloudFormation, S3, ECR, IAM). Fix the permissions and re-run; as a fallback an admin can bootstrap with the CDK CLI the project already installed (not `npx cdk`, which runs the project's own app — see Check 1):

```bash
cd agentcore/cdk && node node_modules/aws-cdk/bin/cdk bootstrap aws://<YOUR_ACCOUNT_ID>/<REGION>
```

**Runtime build precheck failed:**

```
runtime "agent": no pyproject.toml in app/agent/.
runtime "agent": no Dockerfile in app/agent/, and agentcore.json says this is a Container build.
```

Fix: add the missing file, or follow the CLI's message to switch the build type in `agentcore.json`. A `Dockerfile` in the Runtime folder switches it to a container build; it never switches back automatically.

**Container image build failed:**

Images are built natively on ARM64 in AWS CodeBuild. Check the base image supports `linux/arm64`, the app listens on `0.0.0.0:8080`, and `uv.lock` is committed if the Dockerfile runs `uv sync --frozen`. In VPC mode, `networkConfig.vpcId` is required for container builds.

**Model access denied during invoke after deploy:**

```
ValidationException: The provided model identifier is invalid
```

Fix: Enable the model in the Bedrock console → Model access in the target region, and make sure the model ID in code (Runtime) or `harness.yaml` (Harness) matches an enabled model or inference profile.

**Empty project:**

```
Project '…' declares no resources to deploy, so deploying to target '…' would delete stack '…' and every resource in it. Re-run with --yes to confirm, or restore the resources the project should have.
```

Fix: if the teardown is intended, re-run with `--yes`. Otherwise restore the resources (e.g. `git checkout agentcore/agentcore.json`).

**Memory stuck in CREATING:**

This is unusual — normal provisioning takes a few minutes. Check `agentcore status` and `agentcore memory get --id <MEMORY_ID>`. If stuck, try removing and re-adding the memory resource (`agentcore remove memory --name <Name>`, deploy, then `agentcore add memory --name <Name>` and deploy again).

**Service quota exceeded:**

```
LimitExceededException: Account limit for AgentCore runtimes exceeded
```

Fix: Request a quota increase in the AWS console → Service Quotas → Amazon Bedrock AgentCore.

### Step B3: After fixing, re-run

```bash
agentcore deploy
```

If the same error recurs, check `agentcore status` to see the current state of every resource the project declares:

```bash
agentcore status
agentcore status --target staging
```

---

## Deploying to multiple targets

Define targets in `agentcore/aws-targets.json` (`name` starts with a letter and contains letters, digits, and hyphens; `region` must be an AgentCore region):

```json
[
  {
    "name": "default",
    "account": "123456789012",
    "region": "us-east-1"
  },
  {
    "name": "staging",
    "description": "Staging environment",
    "account": "123456789012",
    "region": "us-east-1"
  },
  {
    "name": "production",
    "description": "Production environment",
    "account": "987654321098",
    "region": "us-west-2"
  }
]
```

Deploy to a specific target (with credentials for that target's account):

```bash
agentcore deploy --target staging
agentcore deploy --target production
```

Each target gets its own stack (`AgentCore-<project>-<target>`) and its own copies of every resource. `status`, `invoke`, `logs`, and `traces` take the same `--target` flag.

## Extending the CDK app

`agentcore/cdk/` is a vended CDK app you own:

- `bin/cdk.ts` reads the project and creates one stack per target using `@aws/agentcore-cdk` (pinned at `1.0.0` in `agentcore/cdk/package.json`; the CLI warns below 1.0.0). Leave it alone — logic changes come through library updates.
- `lib/cdk-stack.ts` instantiates `AgentCoreApplication`. Add your own resources there and grant access with `this.application.runtime("<name>")` or `this.application.harness("<name>")` (both are `iam.IGrantable` and have `addEnvironmentVariable`).

Run `agentcore deploy` to apply changes. `agentcore status` reports only resources declared in `agentcore.json`, not ones you add in the stack. If a Runtime or Harness uses an existing execution role, CDK can't change its permissions — add them to that role yourself.

## Removing resources and tearing down

```bash
agentcore remove runtime --name <Name>                         # also: harness, memory, gateway, credential, evaluator, ...
agentcore remove gateway-target --name <Name> --gateway <Gateway>
agentcore remove runtime-endpoint --name <Name> --runtime <Runtime>
agentcore deploy                                               # applies the removal to AWS
```

`remove` only edits the project; the next `agentcore deploy` deletes the resource from the target. Code under `app/` is left in place.

To delete everything deployed to a target, work through these steps in order. Repeat for each target with `--target <name>` (and `--region` on the `harness` / `aws` commands if the target isn't in your default region).

Before running any command below, show the developer the target name, account and region (from `agentcore/aws-targets.json`) and the resources and log groups that will be deleted, and wait for explicit confirmation. Never run this against a production-looking target without that confirmation.

**0. Save the deployed IDs.** Run `agentcore status --json` and note the Runtime/Harness IDs and ARNs. You need them in step 1 and to match log groups in step 4, and they're gone from `status` once the stack is deleted.

**1. Delete named Harness endpoints first.** Harness endpoints created with `agentcore harness endpoint create` (e.g. a `prod` pin from [versioning](references/versioning.md)) aren't in the stack, and the service refuses to delete a Harness that still has them — the stack ends up `DELETE_FAILED` with `Harness ... has endpoints that must be deleted before the harness can be deleted` (409 `ConflictException`). Runtime endpoints are declared in `agentcore.json` and go away with the stack.

```bash
agentcore harness endpoint list --id <HARNESS_ID>
agentcore harness endpoint delete --id <HARNESS_ID> --qualifier <ENDPOINT_NAME>   # every endpoint except DEFAULT
```

Wait until `harness endpoint list` shows only `DEFAULT` (endpoint deletion takes a few minutes) before the next step.

**2. Delete the stack.**

```bash
agentcore remove all --yes
agentcore deploy --yes
```

The second command deletes the stack `AgentCore-<project>-<target>`. If it fails with `DELETE_FAILED`, fix the cause it names (usually step 1) and run `agentcore deploy --yes` again.

`remove all` empties `agentcore.json` for **every** target, not just this one. If other targets should stay deployed, restore the file once this target's stack is gone (`git checkout agentcore/agentcore.json`), and don't run `deploy --yes` against the others while it's empty.

**3. Confirm the stack is gone** — include `DELETE_FAILED`, or a stuck stack won't show up:

```bash
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE ROLLBACK_COMPLETE DELETE_IN_PROGRESS DELETE_FAILED \
  --query "StackSummaries[?starts_with(StackName, 'AgentCore-<project>-')].[StackName,StackStatus]" --output table
```

**4. Clean up what survives the stack.** These aren't CloudFormation resources, so deleting the stack leaves them behind:

- **Runtime log groups** — one per endpoint: `/aws/bedrock-agentcore/runtimes/<RUNTIME_ID>-<ENDPOINT>` (e.g. `...-DEFAULT`, `...-prod`).
- **Harness log groups** — a Harness logs through the service Runtime that backs it: `/aws/bedrock-agentcore/runtimes/harness_<HARNESS_NAME>-<suffix>-<ENDPOINT>` (the backing ID is `.harness.environment.agentCoreRuntimeEnvironment.agentRuntimeId` in `agentcore harness get --id <HARNESS_ID> --json`).
- **Online-eval results** — `/aws/bedrock-agentcore/evaluations/results/<ONLINE_EVAL_CONFIG_ID>` (e.g. `<project>_<target>_<name>-<suffix>`).
- **Code-evaluator Lambda logs** — `/aws/lambda/<project>-<target>-eval-<EvaluatorName>`.

List the log groups for this target (match them against the IDs you saved in step 0). In these names each `-` in the target name becomes `_` (target `prod-us` gives `<project>_prod_us_...`):

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/<project>_<target>_ \
  --query 'logGroups[].logGroupName' --output text | tr '\t' '\n'
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/harness_<project>_<target>_ \
  --query 'logGroups[].logGroupName' --output text | tr '\t' '\n'
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/evaluations/results/<project>_<target>_ \
  --query 'logGroups[].logGroupName' --output text | tr '\t' '\n'
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/<project>-<target>-eval- \
  --query 'logGroups[].logGroupName' --output text | tr '\t' '\n'
```

A project converted by `agentcore migrate` keeps its v0 resource names, which have no `<target>` segment — match those log groups against the IDs from step 0 instead of by prefix.

Show the list to the developer and delete only after they confirm:

```bash
aws logs delete-log-group --log-group-name <LOG_GROUP_NAME>   # for each one that belongs to this target
```

- **Eval datasets and recommendations** (from `agents-optimize`) are service-side and not in the stack:

  ```bash
  agentcore eval dataset list --json
  agentcore eval dataset delete --id <DATASET_ID>
  agentcore eval recommendation list --json
  agentcore eval recommendation delete --id <RECOMMENDATION_ID>
  ```

  Run with no flags, the `eval`, `identity`, `runtime`, `harness`, `memory`, and `gateway` commands open the interactive TUI, which fails without a terminal (`interactive mode requires a TTY`) — pass `--json` (or the command's flags) from an agent shell.

- **Batch evaluations** have no delete command (`eval batch-evaluation` has `evaluate`, `simulate`, `get`, `list`, `stop`); completed jobs stay listed.

Leave account-wide settings alone unless you mean to change them for every project: the `CDKToolkit` bootstrap stack, CloudWatch Transaction Search, and the shared batch-evaluation results log group.

## Exporting a Harness to code

When a Harness needs logic its config can't express, convert it to a Runtime you own:

```bash
agentcore export harness --name <HarnessName>                       # in-project harness
agentcore export harness --arn <HARNESS_ARN> --project-name <Name>  # a deployed harness, outside a project
```

This generates a Runtime (named `<HarnessName>Agent` unless you pass `--target-agent-name`) using the Strands Harness SDK. Deploy it like any other Runtime.

## Output

- Pre-flight check results with specific fixes for any issues found
- Diagnosis of deploy failure with the specific fix
- Deploy command to run after fixes are applied
