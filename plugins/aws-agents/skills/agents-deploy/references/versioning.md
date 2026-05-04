# Agent Versioning and Rollback

Every `agentcore deploy` creates a new version of your agent runtime. This reference covers how versions work, how to pin to a specific version, and how to roll back when a deploy goes wrong.

## How versioning works

- Each `agentcore deploy` produces a new runtime version
- The alias (usually `DEFAULT`) points to the currently-live version
- Old versions remain accessible by ARN for rollback
- Local dev (`agentcore dev`) always runs the current code — no version concept

## Inspecting versions

The AgentCore CLI currently manages the project config (`agentcore.json` → `agentcore deploy`) but doesn't expose version/alias operations directly. For those, use the AWS CLI against the `bedrock-agentcore-control` data plane.

```bash
# List all versions of your agent
aws bedrock-agentcore-control list-agent-runtime-versions \
  --agent-runtime-id <AGENT_RUNTIME_ID>

# Get details on a specific version
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id <AGENT_RUNTIME_ID> \
  --qualifier <VERSION>
```

The `<AGENT_RUNTIME_ID>` comes from `agentcore status --json | jq '.runtimes[0].agentRuntimeId'`.

## Invoking a specific version

By default, callers hit the alias (current version). To pin a call to a specific version, pass `qualifier` in the invoke request:

```python
response = client.invoke_agent_runtime(
    agentRuntimeArn="<AGENT_RUNTIME_ARN>",
    qualifier="3",  # invoke version 3 specifically
    payload=payload,
    runtimeSessionId=session_id,
)
```

This is useful for:

- Canary testing — send a small percentage of traffic to a new version before cutting over
- A/B comparison — run two versions in parallel and compare outputs
- Debugging — reproduce an issue against a specific version

## Rolling back

If a deploy breaks something, roll back by redeploying the previous known-good code:

```bash
# Option 1: git checkout the previous commit and redeploy
git checkout <PREVIOUS_COMMIT>
agentcore deploy -y

# Option 2: point the alias at an older version (no code rollback needed)
aws bedrock-agentcore-control update-agent-runtime-alias \
  --agent-runtime-id <AGENT_RUNTIME_ID> \
  --alias-name DEFAULT \
  --routing-configuration agentRuntimeVersion=<OLDER_VERSION>
```

Option 2 is faster — no rebuild or redeploy, just a pointer swap. Option 1 is cleaner because your code matches what's running.

## Canary deployment

Split traffic between two versions to validate a new deploy before full rollout:

```bash
aws bedrock-agentcore-control update-agent-runtime-alias \
  --agent-runtime-id <AGENT_RUNTIME_ID> \
  --alias-name DEFAULT \
  --routing-configuration \
    agentRuntimeVersion=<NEW_VERSION>,weight=10 \
    agentRuntimeVersion=<OLD_VERSION>,weight=90
```

This routes 10% of traffic to the new version. Monitor `agents-optimize` eval scores and error rates before increasing the weight.

## Version cleanup

AgentCore retains versions indefinitely — they don't auto-delete. If you've deployed hundreds of times, consider periodically deleting old versions:

```bash
aws bedrock-agentcore-control delete-agent-runtime-version \
  --agent-runtime-id <AGENT_RUNTIME_ID> \
  --version <OLD_VERSION>
```

Never delete the current live version.

## Staging targets

For teams that want separate dev/staging/prod environments, use deployment targets:

```json
// agentcore/aws-targets.json
[
  {"name": "default", "account": "<DEV_ACCOUNT>", "region": "us-east-1"},
  {"name": "staging", "account": "<STAGING_ACCOUNT>", "region": "us-east-1"},
  {"name": "production", "account": "<PROD_ACCOUNT>", "region": "us-west-2"}
]
```

```bash
agentcore deploy --target staging -y
agentcore deploy --target production -y
```

Each target gets its own runtime — versions are separate per target.

## Cross-references

- If a rollback is needed because of a specific failure, use `agents-debug` to diagnose first
- For staging/production best practices, see `agents-harden`
- For running evals against a specific version before cutover, see [`agents-optimize/references/evals.md`](../../agents-optimize/references/evals.md)
