# Runtime Versioning And Rollback

The refactored AgentCore CLI can inspect Runtime versions and endpoints.
Versions are created through project deployment; the Runtime version and
endpoint groups do not expose mutation commands.

## Inspect Versions

Use the Runtime ID, not its ARN:

```bash
agentcore runtime version list --id <RUNTIME_ID> --json
agentcore runtime version get \
  --id <RUNTIME_ID> \
  --version <VERSION> \
  --json
```

Record the version, creation time, status, and configuration needed to identify
the current and candidate versions.

## Inspect Endpoints

```bash
agentcore runtime endpoint list --id <RUNTIME_ID> --json
agentcore runtime endpoint get \
  --id <RUNTIME_ID> \
  --qualifier <ENDPOINT_NAME> \
  --json
```

Invoke a selected endpoint when validating a deployment:

```bash
agentcore runtime invoke \
  --id <RUNTIME_ID> \
  --qualifier <ENDPOINT_NAME> \
  --payload file://payload.json \
  --json
```

Use a unique session ID when the test must be isolated from earlier
conversations.

## Deploy A New Version

Build the current project, inspect the artifact, and deploy it:

```bash
agentcore project build
agentcore project deploy
agentcore project status
```

These project lifecycle commands currently have no documented
command-specific flags, so keep them bare.

After deployment, list the Runtime versions and endpoints again to confirm what
changed.

## Plan A Rollback

Before changing traffic:

1. Record the current endpoint and target version.
2. Identify and test the last known-good version.
3. Define rollback criteria and ownership.
4. Preserve logs and evaluation results from the failed version.
5. Choose the project's supported rollback mechanism.

To restore known-good source through the project workflow, check out the
approved revision, then run:

```bash
agentcore project build
agentcore project deploy
agentcore project status
```

When the deployment system supports changing an endpoint target directly, use
its service API, AWS SDK, or IaC workflow. Do not invent `runtime endpoint
update` or other mutation commands that are absent from the CLI.

## Plan A Canary

The refactored CLI does not expose weighted Runtime endpoint mutation. Configure
traffic shifting through the project's supported service API, AWS SDK, IaC, or
deployment pipeline.

For each canary:

1. Validate the candidate version with direct invocation.
2. Record baseline latency, errors, and evaluation scores.
3. Shift a small, explicit share of traffic.
4. Monitor against predefined success and rollback thresholds.
5. Increase traffic gradually or restore the recorded target.

Use `agents-optimize` for evaluation and observability guidance.

## Constraints

- Never delete or redirect the active version without a tested recovery path.
- Never use a Runtime ARN where a refactored CLI command requires an ID.
- Never claim an endpoint changed based only on an inspection command.
- Never emit legacy root commands or undocumented project flags.
