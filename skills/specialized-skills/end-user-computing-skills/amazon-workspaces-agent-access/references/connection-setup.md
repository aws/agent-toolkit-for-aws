# Connecting to the Agent Access MCP Server

## Endpoint and auth

- **Endpoint:** `https://agentaccess-mcp.{region}.api.aws/mcp` (Streamable HTTP transport).
- **Signing:** every request is SigV4-signed with service name `agentaccess-mcp`. As an alternative, MCP clients that support OAuth 2.1 can authorize through AWS Sign-In with bearer tokens, the same way as for the AWS MCP Server; every request is still checked against the caller's IAM policies. On that path the agent acts with the permissions of the role the person signed in with, which is often a broad console role, so sign in with a role limited to the `agentaccess-mcp` actions the agent needs.
- **IAM:** grant the caller the specific `agentaccess-mcp` actions the agent uses, scoped by the `agentaccess-mcp:StackArn` condition key, or `agentaccess-mcp:ImageBuilderArn` for an image builder (see [IAM permissions](#iam-permissions-least-privilege)).
- **Signing region MUST match the fleet region.** Signing for a different region than the fleet lives in is rejected with `400 Bad Request` (cross-region mismatch). Set `AWS_REGION` / the MCP signing region to the fleet's region and use the matching regional endpoint.
- There is **no AWS CLI/SDK command** that invokes the desktop tools — interaction is MCP-only. Around the connection, the CLI/SDK creates streaming URLs and checks that the environment is ready (prerequisites.md). Creating or configuring fleets, stacks and image builders is the `setting-up-workspaces-applications` skill.
- **Connect mode:** you can also control how the connection waits for the desktop via the `X-Amzn-AgentAccess-Connect-Mode` header (`BLOCKING` default, or `POLLING`), sent alongside the auth headers below — see connection-modes.md.

## IAM permissions (least privilege)

The service has **no resource ARN hierarchy** — resource scoping is by condition key: `agentaccess-mcp:StackArn` (the AppStream stack ARN, from the stack header, the streaming URL, or the stack ARN you send on a domain-joined fleet) for fleet sessions, and `agentaccess-mcp:ImageBuilderArn` for image builder sessions (image-builders.md). So least privilege = **enumerate only the actions your agent calls** and **scope them by stack or builder**.

Available actions: `InvokeMcp` (initialize / `tools/list` / ping — required to connect), `GetScreenshot`, `LeftClick`, `DoubleClick`, `TripleClick`, `RightClick`, `MiddleClick`, `TypeText`, `KeyPress`, `HoldKey`, `Scroll`, `MovePointer`, `LeftClickDrag`, `LeftMouseDown`, `LeftMouseUp`, `GetClipboard`, `SetClipboard`, `CheckConnectionStatus`, `CallForwardedTool`, `LaunchApplication`, `ToggleAppSwitcher`, `GetSessionInfo`, `ExecuteSequence`, `Wait`, and on image builders `SwitchUser` and `GetCurrentUser`. This list is illustrative — consult the current [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/) for the authoritative, complete set of `agentaccess-mcp` actions.

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

Add the specific actions your agent uses (e.g. other click/drag tools, `HoldKey`, `MovePointer`, `GetClipboard` and `SetClipboard` where the session has clipboard access, `CheckConnectionStatus` for POLLING, `GetSessionInfo` to read the session's IDs, e.g. to find its Replay Session recording, `CallForwardedTool` for forwarding). To create streaming URLs yourself, the principal that creates them also needs `appstream:CreateStreamingURL` (and `appstream:DescribeFleets` to check the fleet). If the stack saves screenshots, the signing identity needs `s3:PutObject` on the bucket (see [Screenshot storage](#screenshot-storage)). On a domain-joined fleet the federated role that connects also needs `appstream:Stream` on the stack (see [Domain-joined fleets](#domain-joined-fleets-active-directory)). For `execute_sequence`, allow `ExecuteSequence` plus each step's own action (e.g. `TypeText` for a `type_text` step, `Wait` for a `wait` step) and `GetScreenshot` for its final screenshot. If any one is denied, the whole sequence is refused and no step runs.

> `agentaccess-mcp:*` (as some AWS docs show) is broader than needed, so don't use it. Use the enumerated, stack-scoped policy above.

Prefer an **IAM role** (EC2 instance profile, ECS task role, or Lambda execution role) over an IAM user with long-lived access keys for the principal that signs MCP requests and calls `CreateStreamingURL`. On a domain-joined fleet the signing principal is the federated role session instead (see [Domain-joined fleets](#domain-joined-fleets-active-directory)).

## Choose your path

| Target | Session identified by | How it's passed |
|---|---|---|
| Non-domain-joined fleet | Stack name or ARN, and a user ID (from the caller's `SourceIdentity` or a header); the server creates the session | `x-amzn-agentaccess-workspaces-applications-stack` and `x-amzn-agentaccess-workspaces-applications-user-id` **headers** |
| Non-domain-joined fleet | Streaming URL from `CreateStreamingURL` | `X-Amzn-AgentAccess-Streaming-Session-Url` **header** |
| Domain-joined fleet (Active Directory), preferred | The caller's own federated IAM session (SAML or OIDC) + stack ARN only | Stack ARN in the `x-amzn-agentaccess-workspaces-applications-stack-arn` header **or** `_meta`, not both |
| Domain-joined fleet, legacy | Signed base64 SAML assertion + stack ARN | MCP **`_meta`/metadata** field (not a header) |
| Image builder | Builder name, or a builder streaming URL, plus the Windows account | Headers or `_meta`; see image-builders.md |

## Non-domain-joined fleets (stack and user ID)

Pass the stack and user ID as headers on every request, and the MCP server creates the streaming session. This suits an MCP client you configure statically: it can hold a fixed pair of headers but can't generate a streaming URL or replace one when it expires.

- `x-amzn-agentaccess-workspaces-applications-stack`: the stack name or ARN.
- `x-amzn-agentaccess-workspaces-applications-user-id`: the session's user ID, up to 32 characters. When the caller's credentials carry a `SourceIdentity`, the server uses it and you can leave the header out; a header that differs from it is rejected. Without a `SourceIdentity`, the header is required, and a connection with neither fails with `UserId is required: provide SourceIdentity or x-amzn-agentaccess-workspaces-applications-user-id header`.

```python
async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    headers={
        "x-amzn-agentaccess-workspaces-applications-stack": "my-stack",
        "x-amzn-agentaccess-workspaces-applications-user-id": "my-stack-agent-01",
    },
) as (read, write, _):
    ...
```

**Permissions for this path.** The server finds the stack's fleet and creates the streaming URL with the caller's own credentials, so the caller also needs `appstream:ListAssociatedFleets`, `appstream:DescribeFleets` and `appstream:CreateStreamingURL`. Grant them with `"StringEquals": {"aws:CalledViaAWSMCP": "agentaccess-mcp.amazonaws.com"}`, so the agent's identity can create a streaming URL only through Agent Access. A person who runs the watch command, or code that creates streaming URLs for the streaming URL path, needs `appstream:CreateStreamingURL` from their own identity, without that condition. A user ID that already has an active session attaches to that session, so an agent identity that can pick any user ID could reach a person's live desktop. IAM can't limit the user ID that `CreateStreamingURL` takes (the `appstream:userId` condition key applies only to `appstream:Stream`). So make the agent's role require a `SourceIdentity` (its trust policy allows `sts:SetSourceIdentity` with `"Null": {"sts:SourceIdentity": "false"}`): the server then uses it as the user ID and rejects a header that differs, so each agent's user ID comes from its own session.

Use the user IDs the environment was planned with: one active session per user ID per fleet, and each unique user ID counts toward the per-user fee on Windows Server fleets.

## From a coding agent's MCP config

A coding agent such as Claude Code or Kiro can drive the desktop itself through an entry in its MCP config. `mcp-proxy-for-aws` runs the connection as a local server and sends each `--header` on every request. The config pins version 1.8.0. For a fleet session, name the stack and user ID:

```json
{
  "mcpServers": {
    "agentaccess": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws==1.8.0",
        "https://agentaccess-mcp.us-west-2.api.aws/mcp",
        "--service", "agentaccess-mcp",
        "--region", "us-west-2",
        "--header", "x-amzn-agentaccess-workspaces-applications-stack=my-stack",
        "--header", "x-amzn-agentaccess-workspaces-applications-user-id=my-stack-agent-01"
      ]
    }
  }
}
```

For an image builder, the two headers are `x-amzn-agentaccess-workspaces-applications-image-builder-name=<builder>` and `x-amzn-agentaccess-local-user=ADMINISTRATOR` instead (image-builders.md). Use the environment's Region in both the endpoint and `--region`, and add `"--profile", "<profile>"` to sign with a named AWS profile. Most clients add their own prefix to tool names, so `screenshot` can show up as `mcp__agentaccess__agentaccess___screenshot`.

The client connects once, when it starts the server, and doesn't retry on its own. So add or reconnect the entry only once the environment is ready: the fleet `RUNNING` with `ComputeCapacityStatus.Available` of 1 or more, or the builder `RUNNING` (prerequisites.md).

- **A server started earlier has no desktop tools.** Its first request fails, for example with `Image Builder not found in this region` or `The Image Builder must be in the RUNNING state to create a streaming URL.` for a builder, and the client lists the server as failed or with no tools.
- **Reconnect once the environment is ready.** In Claude Code that's `/mcp`; in other clients, restart the session. If you're the agent and can't reconnect it yourself, ask the user to and wait. Don't write your own MCP client, read the user's client config files, or reach the endpoint another way.
- **The first connect waits for the desktop**, which can take longer than a client's MCP startup timeout. If the server still has no tools after a reconnect, raise that timeout (`MCP_TIMEOUT`, in milliseconds, for Claude Code) and reconnect again.

## Non-domain-joined fleets (streaming URL)

Use this path when you need control over session creation, such as the URL's validity period.

1. Generate a streaming URL:

   ```
   aws appstream create-streaming-url \
     --stack-name <stack> --fleet-name <fleet> \
     --user-id <user> --validity 300 \
     --query StreamingURL --output text
   ```

   Sets how long the URL stays valid for *initiating* a connection: `Validity` accepts 1–604800 seconds (7 days); the API default is 60 seconds. The streaming URL is a **bearer credential** that grants desktop access — use the shortest validity that covers your connection window (e.g. 300 s if the agent connects immediately) to limit the exposure window. Once connected, how long the session runs is governed by the fleet's `MaxUserDurationInSeconds` and disconnect/idle timeouts, not by this value (see session-lifecycle.md).
2. Pass it on every request as the `X-Amzn-AgentAccess-Streaming-Session-Url` header.

> **Treat the streaming URL as a secret.** It is a bearer token — retrieve it ephemerally at connect time; do not log it, persist it to disk, or pass it through insecure channels. If your orchestrator logs MCP headers, redact `X-Amzn-AgentAccess-Streaming-Session-Url`.

Python (`mcp-proxy-for-aws` signs each request and needs Python 3.11+). Install the pinned release with `pip install "mcp-proxy-for-aws==1.8.0"`:

```python
import logging

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

logging.getLogger("mcp_proxy_for_aws").setLevel(logging.ERROR)  # keep the streaming URL out of its logs

async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    headers={"X-Amzn-AgentAccess-Streaming-Session-Url": streaming_url},
) as (read, write, _):
    ...
```

## Domain-joined fleets (Active Directory)

Domain-joined streaming instances log the agent on to Windows as an AD user with **Certificate-Based Authentication (CBA)**, which is required for agent sessions; complete the WorkSpaces Applications CBA prerequisites first. A streaming URL is not used. The AD identity comes from a federated IAM role session, and there are two ways to supply it.

### Preferred: the caller's federated session plus the stack ARN

Connect with credentials from a federated role session that carries the user's AD attributes, and send **only the stack ARN**. There is no SAML assertion to capture or pass: the service reads the AD identity from the caller's session.

The session tags decide which AD account the agent logs on as, and they can name any AD user, administrators included. Give each agent a dedicated, least-privileged AD account, never a person's or an administrator's, and limit the accounts a role accepts with an `aws:RequestTag/UserPrincipalName` condition in its trust policy.

- **SAML:** credentials from `AssumeRoleWithSAML` through the same IdP setup that federates users to the fleet for CBA. As CBA already requires, the assertion's `NameID` is the user's UPN (`user@ad-dns-name`), it sets the `https://aws.amazon.com/SAML/Attributes/PrincipalTag:UserPrincipalName` and `https://aws.amazon.com/SAML/Attributes/PrincipalTag:ObjectSid` attributes, and the role's trust policy allows `sts:TagSession`.
- **OIDC** (any OIDC IdP, such as Entra ID, Okta, Auth0, Ping or Keycloak): credentials from `AssumeRoleWithWebIdentity` against an IAM OIDC identity provider for the IdP's issuer. Map these session tags into the IdP's token:
  - `UserPrincipalName`, the AD UPN in `user@ad-dns-name` form. It names the Windows user, so a missing or malformed value makes the desktop logon fail.
  - `ObjectSid`, the AD `objectSid` (`S-1-5-21-...`) of the same user.
  - In the nested `https://aws.amazon.com/tags` claim form, tag values are arrays, even for one value.
- **OIDC trust policy:** allow `sts:TagSession` (or STS silently drops the tags) and `sts:SetSourceIdentity`, have the token set `source_identity`, and require it with `"Null": {"sts:SourceIdentity": "false"}`. Require `<issuer>:aud` to equal the IdP client ID and `<issuer>:sub` to match the agent's identity, where `<issuer>` is the provider URL without `https://`; otherwise any token from the same issuer, for any client, can assume the role. A SAML role's trust policy keeps its `SAML:aud` condition. `Null` conditions on `aws:RequestTag/UserPrincipalName` and `aws:RequestTag/ObjectSid` turn a token missing either into a clear `AccessDenied` at STS.
- **OIDC session source:** use the `AssumeRoleWithWebIdentity` session directly. A session from IAM Identity Center, or one chained through a further `AssumeRole`, is rejected, because only a direct web-identity session proves the tags came from the IdP.
- **Permissions:** the role needs `appstream:Stream` on the stack, as its own statement (the `agentaccess-mcp:StackArn` condition key does not apply to it), plus what the stack's settings need, because this role is the signing identity: the `agentaccess-mcp` actions above and `s3:PutObject` for [Screenshot storage](#screenshot-storage) or Replay Session (replay-session.md):

  ```json
  { "Effect": "Allow", "Action": "appstream:Stream", "Resource": "arn:aws:appstream:<region>:<account>:stack/<stack>" }
  ```

```python
import boto3
from botocore.credentials import Credentials
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

# The federated role session that carries the AD identity. OIDC shown; for SAML use
# assume_role_with_saml. The tags come from the IdP's token, never from the caller.
# idp_token: the IdP's ID token, or a JWT access token whose audience the IAM OIDC provider accepts.
c = boto3.client("sts", region_name="us-east-1").assume_role_with_web_identity(
    RoleArn=role_arn, WebIdentityToken=idp_token,
    RoleSessionName=f"agent-{user_id}",  # unique per user, so CloudTrail tells them apart
)["Credentials"]
creds = Credentials(c["AccessKeyId"], c["SecretAccessKey"], c["SessionToken"])

async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    credentials=creds,       # or aws_profile="<profile for the federated role>"
    headers={"x-amzn-agentaccess-workspaces-applications-stack-arn": stack_arn},  # stack ARN only
) as (read, write, _):
    ...
```

- Send the stack ARN on every request, in the header **or** as the `aws.agentaccess/workspacesApplicationsStackArn` `_meta` key, never both (`400`).
- Use the `...-stack-arn` header, not the `...-stack` header from the non-domain-joined path: that one makes the server create a streaming URL, which does not work for a domain-joined fleet.
- The stack must be in the caller's own account (`403` otherwise). A session stays on the stack it started on; a later request naming another stack is rejected with `404`.
- The session ends when the federated credentials it started from expire (see session-lifecycle.md). Reconnect with fresh credentials.

### Legacy: SAML assertion plus the stack ARN

Callers that cannot use their own federated session can still pass a signed, base64-encoded SAML assertion with the stack ARN. The encoded assertion exceeds HTTP header size limits, so it is injected via the MCP `_meta` field. `mcp-proxy-for-aws` exposes this as the `metadata` parameter. It logs the whole `_meta`, assertion included, at INFO, so set its logger to ERROR first:

```python
logging.getLogger("mcp_proxy_for_aws").setLevel(logging.ERROR)

async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # use YOUR fleet's region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the fleet's region — mismatch is rejected with 400
    metadata={
        # Exact _meta keys the server reads:
        "aws.agentaccess/workspacesApplicationsSamlAssertion": saml_response,  # signed, base64-encoded assertion
        "aws.agentaccess/workspacesApplicationsStackArn": stack_arn,           # AppStream stack ARN for the AD user
    },
) as (read, write, _):
    ...
```

The MCP server provisions a desktop session bound to the AD user identity in the assertion. Prerequisites: an IAM SAML provider registered with your IdP certificate, an IAM role trusting that provider, and a base64 assertion from your IdP (Okta, Entra ID, Ping, etc.). The assertion expires within minutes and is needed for every new session, which is why the federated-session path above is preferred.

> **Keep federation material ephemeral and secret.** The SAML assertion and the federated role credentials are sensitive — do not log or persist them. Issue short-lived assertions and tokens and scope the assumed IAM role's `MaxSessionDuration` to the minimum the agent's task needs. Store IdP signing credentials in AWS Secrets Manager, and restrict who can edit the IdP claim mapping and the IAM identity provider, because they decide which AD user the agent logs on as.

## Screenshot storage

If the stack or builder has screenshot storage on (`ScreenshotsUploadEnabled` with `S3BucketArn`), the server saves every screenshot to that bucket under `agentaccess/screenshots/year=YYYY/month=MM/day=DD/<session-id>/<timestamp>.png`, where the session ID is the WorkSpaces Applications streaming session ID.

- **The upload uses the signing identity's credentials.** It needs `s3:PutObject` on `arn:aws:s3:::<bucket>/agentaccess/screenshots/*`, and `kms:GenerateDataKey` on the key if the bucket encrypts with a customer managed KMS key. Give the `s3:PutObject` statement two `StringEquals` conditions: `"s3:ResourceAccount": "<account>"`, so screenshots never go to a bucket of the same name in another account after yours is deleted, and `"aws:CalledViaAWSMCP": "agentaccess-mcp.amazonaws.com"`, so the agent's identity can write screenshots only through Agent Access.
- **Expire old screenshots.** They can hold PII, typed secrets and license keys, so add a lifecycle rule that expires `agentaccess/screenshots/` after your retention period.
- **A failed upload doesn't fail the screenshot.** The agent still gets the image. The tool result's `_meta` carries `s3Url` on success or `screenshotUploadError` on failure, and the CloudTrail data event for the call records the same field. Check one of them after the first screenshot of a run, because a missing permission otherwise goes unnoticed.
- Creating the bucket and its policy is the `setting-up-workspaces-applications` skill.

## Connection methods (transport-level)

| Method | Auth handling | Use case |
|---|---|---|
| Direct via `mcp-proxy-for-aws` | Signs each request locally | SDK integrations, custom agents |
| AgentCore Gateway | Gateway signs on your behalf; can auto-provision sessions | Managed deployments, no streaming-URL management |
| AgentCore Harness | Fully managed orchestration | Zero-code agents |

## Concurrency

Only one agent can connect to a given session at a time, and a named user (`UserId`) can have only one active session per fleet at a time. To run agents in parallel, give each its own session/user.
