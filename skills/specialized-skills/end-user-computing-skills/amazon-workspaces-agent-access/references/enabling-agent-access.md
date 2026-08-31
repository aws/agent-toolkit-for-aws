# Enabling Agent Access (prerequisites & stack setup)

Before an agent can connect, **agent access must be enabled on the stack**. This is an admin/setup step, distinct from the agent-side connection in connection-setup.md.

## Prerequisites

- An active WorkSpaces Applications **fleet** (Always-On or On-Demand) — **Elastic and multi-session fleets are not supported**, and only **Windows Server** images are supported.
- A **stack associated with that fleet** (agents cannot connect to a stack without an associated fleet).
- The fleet running a recent WorkSpaces Applications Agent.
- AWS permissions to create/manage stacks; the connecting agent needs the specific `agentaccess-mcp` actions it calls, scoped by the `agentaccess-mcp:StackArn` condition key — avoid a blanket `agentaccess-mcp:*` (see connection-setup.md → IAM permissions).
- (Optional) For screenshot storage: an S3 bucket whose policy grants the AppStream service principal access, and the connecting agent needs `s3:PutObject` on it. Scope the service-principal grant with `aws:SourceAccount` / `aws:SourceArn` (confused-deputy protection), enable encryption **at rest** (SSE-S3 or SSE-KMS), and enforce encryption **in transit** (bucket policy denying requests where `aws:SecureTransport` is `false`).
- **VPC endpoints are not supported** for agent access.

## How you enable it

Agent access is enabled by supplying an **`AgentAccessConfig`** when you **`CreateStack`** (or add it later with **`UpdateStack`**). If `AgentAccessConfig` is present, agent access is on and the stack is configured with agent-specific settings instead of the human-user settings.

`AgentAccessConfig` required fields: `Settings` (≥1), `ScreenResolution`, `ScreenImageFormat`.

**Agent actions** (`Settings[].AgentAction`, each with `Permission: ENABLED|DISABLED`) — you must enable **at least one** capability:

| AgentAction | Enables |
|---|---|
| `COMPUTER_VISION` | Agent can take screenshots of the desktop |
| `COMPUTER_INPUT` | Agent can click, type, scroll — **requires `COMPUTER_VISION` also ENABLED** |
| `FORWARD_MCP_TOOLS` | Forwards MCP tools on the session to the agent (see tool-forwarding.md) |

Other fields:
- `ScreenResolution` — `W_1280xH_720` is the **only** value the API accepts (single-value enum).
- `ScreenImageFormat` — `PNG` or `JPEG`.
- `S3BucketArn` + `ScreenshotsUploadEnabled: true` — optional screenshot storage.
- `UserControlMode` — `VIEW_ONLY`, `VIEW_STOP` (observer can stop the agent), or `DISABLED`.

## CLI example

```bash
aws appstream create-stack \
    --name your-stack-name \
    --agent-access-config '{
        "Settings": [
            {"AgentAction": "COMPUTER_VISION", "Permission": "ENABLED"},
            {"AgentAction": "COMPUTER_INPUT", "Permission": "ENABLED"}
        ],
        "ScreenResolution": "W_1280xH_720",
        "ScreenImageFormat": "PNG"
    }'
```

Enable only the capabilities the workflow needs — this baseline (vision + input) covers standard desktop automation. `FORWARD_MCP_TOOLS` is optional and only needed for the tool-forwarding workflow; add `{"AgentAction": "FORWARD_MCP_TOOLS", "Permission": "ENABLED"}` when setting that up (see tool-forwarding.md).

To add screenshot storage, include `"S3BucketArn": "arn:aws:s3:::your-bucket", "ScreenshotsUploadEnabled": true`.

## Updating / removing

- **Update:** `aws appstream update-stack --name <stack-name> --agent-access-config '{...}'` supports partial updates — send only the fields you want to change.
- **Remove agent access:** `aws appstream update-stack --name <stack-name> --attributes-to-delete AGENT_ACCESS_CONFIG`.
- Config changes take effect on **new** sessions; already-running sessions keep the settings they launched with.

## After enabling

The agent connects to `https://agentaccess-mcp.{region}.api.aws/mcp` and authenticates the session (streaming URL, or SAML for domain-joined) — see connection-setup.md. Agent behavior is governed by the stack's `AgentAccessConfig`, not by parameters on the connection.
