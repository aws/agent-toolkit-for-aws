---
name: agents-deploy
description: >
  Prepare, deploy, inspect, or troubleshoot AgentCore projects. Use for
  deployment readiness, IAM and region checks, failed infrastructure
  deployments, Runtime version inspection, endpoint inspection, rollback
  planning, and canary planning. Uses the refactored AgentCore CLI command
  tree. Use agents-harden for production security.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  cli-surface: refactor
---

# Deploy

Build and deploy an AgentCore project, inspect the deployed resources, or
diagnose a failed deployment.

## When To Use

- A project is ready to build or deploy.
- A deployment failed or appears stuck.
- The deployed project or Runtime needs inspection.
- A rollout, rollback, or canary plan is needed.

Use `agents-harden` for production security reviews and `agents-build` for
capabilities that must be added before deployment.

## Workflow

### 1. Inspect The Project

Read the project configuration, source, dependency files, and deployment
artifacts. Determine:

- the expected AWS account and region,
- the resources the project creates,
- the model IDs and external dependencies it uses,
- the current deployment state,
- whether this is a first deployment, update, or recovery.

The refactored CLI has no root version flag, so do not perform a CLI version
check.

### 2. Run Preflight Checks

Confirm the active AWS identity and region using the credential profile required
by the project or repository:

```bash
aws sts get-caller-identity --profile <PROFILE>
aws configure get region --profile <PROFILE>
```

Check model availability, IAM permissions, quotas, container tooling, and any
project-specific prerequisites before changing AWS resources. Use the
repository's established IaC validation commands when the project contains
CloudFormation, CDK, Terraform, or another deployment system.

### 3. Build The Project

```bash
agentcore project build
```

Inspect build output before deploying. Resolve dependency, packaging, container,
and configuration failures at the first actionable error.

### 4. Deploy The Project

```bash
agentcore project deploy
```

The command currently has no documented command-specific flags. Do not add
legacy flags such as `-y`, `--target`, `--dry-run`, or `--diff`.

### 5. Check Deployment Status

```bash
agentcore project status
```

Use service-specific inspection when more detail is needed. For example:

```bash
agentcore runtime list --json
agentcore memory list --json
agentcore gateway list --json
```

## Inspect A Deployed Runtime

Use Runtime IDs, not ARNs:

```bash
agentcore runtime get --id <RUNTIME_ID> --json
agentcore runtime version list --id <RUNTIME_ID> --json
agentcore runtime endpoint list --id <RUNTIME_ID> --json
```

The Runtime command group supports read-only inspection and invocation. It does
not expose Runtime create, update, or delete commands, and Runtime endpoint and
version groups are read-only.

Read [`references/versioning.md`](references/versioning.md) before planning a
rollout, rollback, or endpoint change.

## Diagnose A Failed Deployment

1. Capture the exact build or deployment command.
2. Find the first failing operation, not only the final summary.
3. Record the target account, region, and caller identity.
4. Identify the affected resource and deployment mechanism.
5. Inspect `~/.agentcore/logs/` when the CLI was run with `--debug`.
6. Check the underlying service, CloudFormation, or pipeline events.
7. Correct the cause, then rerun the bare build, deploy, or status command.

Useful AWS checks include:

```bash
aws cloudformation describe-stack-events \
  --stack-name <STACK_NAME> \
  --profile <PROFILE>

aws service-quotas list-service-quotas \
  --service-code bedrock-agentcore \
  --profile <PROFILE>
```

Common failure classes:

- **IAM denial:** identify the denied action, resource, principal, and
  permissions boundary or service control policy involved.
- **Region mismatch:** align the CLI region, AWS profile, project
  configuration, model availability, and resource ARNs.
- **Packaging failure:** fix the first dependency, container, or artifact
  error, then rerun `agentcore project build`.
- **CloudFormation failure:** inspect the first failed stack event and the
  corresponding resource logs.
- **Quota failure:** confirm current usage and request the specific quota
  increase.
- **Resource still creating:** inspect the resource through its refactored CLI
  group or service API before retrying.

Do not translate failures into obsolete root-level deployment, status, or log
commands.

## Quality Criteria

- Build, deployment, and status use the `agentcore project` command group.
- Project lifecycle commands remain bare until their flags are documented.
- Runtime inspection uses IDs and the `runtime version` or `runtime endpoint`
  groups.
- No root version flag, aliases, or legacy root commands are emitted.
- AWS mutations follow the repository's credential and approval requirements.
