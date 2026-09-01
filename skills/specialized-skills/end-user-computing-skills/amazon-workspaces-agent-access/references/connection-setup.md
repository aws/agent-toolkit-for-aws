# Connecting to the Agent Access MCP Server

## Endpoint and auth

- **Endpoint:** `https://agentaccess-mcp.{region}.api.aws/mcp` (Streamable HTTP transport).
- **Signing:** every request is SigV4-signed with service name `agentaccess-mcp`.
- **IAM:** grant the caller the specific `agentaccess-mcp` actions the agent uses, scoped by the `agentaccess-mcp:StackArn` condition key (see [IAM permissions](#iam-permissions-least-privilege)).
- **Signing region MUST match the fleet region.** Signing for a different region than the fleet lives in is rejected with `400 Bad Request` (cross-region mismatch). Set `AWS_REGION` / the MCP signing region to the fleet's region and use the matching regional endpoint.
- There is **no AWS CLI/SDK command** that invokes the desktop tools — interaction is MCP-only. The CLI/SDK is used only for setup (streaming URL, fleet/stack config).
- **Connect mode:** you can also control how the connection waits for the desktop via the `X-Amzn-AgentAccess-Connect-Mode` header (`BLOCKING` default, or `POLLING`), sent alongside the auth headers below — see connection-modes.md.

## IAM permissions (least privilege)

The service has **no resource ARN hierarchy** — the only resource scoping is the `agentaccess-mcp:StackArn` condition key (the AppStream stack ARN, derived from the streaming URL or supplied via the SAML path). So least privilege = **enumerate only the actions your agent calls** and **scope them by stack**.

Available actions: `InvokeMcp` (initialize / `tools/list` / ping — required to connect), `GetScreenshot`, `LeftClick`, `DoubleClick`, `TripleClick`, `RightClick`, `MiddleClick`, `TypeText`, `KeyPress`, `HoldKey`, `Scroll`, `MovePointer`, `LeftClickDrag`, `LeftMouseDown`, `LeftMouseUp`, `CheckConnectionStatus`, `CallForwardedTool`. This list is illustrative — consult the current [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/) for the authoritative, complete set of `agentaccess-mcp` actions.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "agentaccess-mcp:InvokeMcp",
      "agentaccess-mcp:GetScreenshot",
      "agentaccess-mcp:LeftClick",
      "agentaccess-mcp:TypeText",
      "agentaccess-mcp:KeyPress",
      "agentaccess-mcp:Scroll"
    ],
    "Resource": "*",
    "Condition": {
      "ArnLike": { "agentaccess-mcp:StackArn": "arn:aws:appstream:<region>:<account>:stack/<stack>" }
    }
  }]
}
```

Add the specific actions your agent uses (e.g. other click/drag tools, `HoldKey`, `MovePointer`, `CheckConnectionStatus` for POLLING, `CallForwardedTool` for forwarding). For *setup* the caller also needs `appstream:CreateStreamingURL` (and `appstream:DescribeFleets`), on the setup principal.

> `agentaccess-mcp:*` with `Resource: *` (as some AWS docs show) also works but is broader than necessary — prefer the enumerated, stack-scoped policy above.

Prefer an **IAM role** (EC2 instance profile, ECS task role, or Lambda execution role) over an IAM user with long-lived access keys for the principal that signs MCP requests and calls `CreateStreamingURL`.

## Choose your path by fleet type

| Fleet type | Session auth | How it's passed |
|---|---|---|
| Non-domain-joined | Streaming URL from `CreateStreamingURL` | `X-Amzn-AgentAccess-Streaming-Session-Url` **header** |
| Domain-joined (Active Directory) | Signed base64 SAML assertion + stack ARN | MCP **`_meta`/metadata** field (not a header) |

## Non-domain-joined fleets (streaming URL)

1. Generate a streaming URL:

   ```
   aws appstream create-streaming-url \
     --stack-name <stack> --fleet-name <fleet> \
     --user-id <user> --validity 3600 \
     --query StreamingURL --output text
   ```

   Sets how long the URL stays valid for *initiating* a connection: `Validity` accepts 1–604800 seconds (7 days); the API default is 60 seconds. The streaming URL is a **bearer credential** that grants desktop access — use the shortest validity that covers your connection window (e.g. 300 s if the agent connects immediately) to limit the exposure window. Once connected, how long the session runs is governed by the fleet's `MaxUserDurationInSeconds` and disconnect/idle timeouts, not by this value (see session-lifecycle.md).
2. Pass it on every request as the `X-Amzn-AgentAccess-Streaming-Session-Url` header.

> **Treat the streaming URL as a secret.** It is a bearer token — retrieve it ephemerally at connect time; do not log it, persist it to disk, or pass it through insecure channels. If your orchestrator logs MCP headers, redact `X-Amzn-AgentAccess-Streaming-Session-Url`.

Python (`mcp-proxy-for-aws` signs each request; requires Python 3.10+ — running it via `uvx mcp-proxy-for-aws ...` avoids system-Python version issues):

```python
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    headers={"X-Amzn-AgentAccess-Streaming-Session-Url": streaming_url},
) as (read, write, _):
    ...
```

## Domain-joined fleets (SAML / Domain Join)

Domain-joined streaming instances must be accessed through SAML federation; a streaming URL is not used. **Certificate-Based Authentication (CBA)** is required for agent sessions.

The encoded SAML assertion exceeds HTTP header size limits, so it is injected via the MCP `_meta` field. `mcp-proxy-for-aws` 1.6.1+ exposes this as the `metadata` parameter:

```python
async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    metadata={
        # Verified _meta keys read by the server's input_resolver:
        "aws.agentaccess/workspacesApplicationsSamlAssertion": saml_response,  # signed, base64-encoded assertion
        "aws.agentaccess/workspacesApplicationsStackArn": stack_arn,           # AppStream stack ARN for the AD user
    },
) as (read, write, _):
    ...
```

The MCP server provisions a desktop session bound to the AD user identity in the assertion. Prerequisites: an IAM SAML provider registered with your IdP certificate, an IAM role trusting that provider, and a base64 assertion from your IdP (Okta, Entra ID, Ping, etc.).

> **Keep federation material ephemeral and secret.** The SAML assertion is sensitive — do not log or persist it. Issue short-lived assertions (e.g. 5–15 min) and scope the assumed IAM role's `MaxSessionDuration` to the minimum the agent's task needs. Store IdP signing credentials in AWS Secrets Manager.

## Connection methods (transport-level)

| Method | Auth handling | Use case |
|---|---|---|
| Direct via `mcp-proxy-for-aws` | Signs each request locally | SDK integrations, custom agents |
| AgentCore Gateway | Gateway signs on your behalf; can auto-provision sessions | Managed deployments, no streaming-URL management |
| AgentCore Harness | Fully managed orchestration | Zero-code agents |

## Concurrency

Only one agent can connect to a given session at a time, and a named user (`UserId`) can have only one active session per fleet at a time. To run agents in parallel, give each its own session/user.
