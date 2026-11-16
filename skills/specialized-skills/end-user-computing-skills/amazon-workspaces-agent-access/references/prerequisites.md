# Prerequisites: an environment the agent can connect to

The agent connects to one of two things, and each needs agent access turned on by an `AgentAccessConfig` on it:

- **A stack with an associated, running fleet**, for work on fleet instances.
- **A running image builder**, for installing and testing applications before an image is captured (image-builders.md).

Creating either one, and turning on or changing its agent access settings, is the `setting-up-workspaces-applications` skill. This file covers checking what exists, and what each setting means for the agent.

## Check before connecting

These calls are read-only:

```bash
# Fleet session
aws appstream describe-stacks --names <stack> --query 'Stacks[0].AgentAccessConfig'
aws appstream list-associated-fleets --stack-name <stack>
aws appstream describe-fleets --names <fleet> \
  --query 'Fleets[0].{State:State,Available:ComputeCapacityStatus.Available}'

# Image builder session
aws appstream describe-image-builders --names <builder> \
  --query 'ImageBuilders[0].{State:State,AgentAccess:AgentAccessConfig}'
```

The environment is ready when the stack has an `AgentAccessConfig` and its fleet is `RUNNING` with `Available` above 0, or when the builder is `RUNNING` with an `AgentAccessConfig`. `Available` of 0 is also fine when this agent's user ID already has an active session on the fleet (`aws appstream describe-sessions --stack-name <stack> --fleet-name <fleet> --user-id <user-id>`), because the agent holds that desktop; reconnect to it with a streaming URL (troubleshooting.md, `No available capacity on the fleet`). Reserve agent user IDs for agents: a user ID a person also uses would reconnect the agent into that person's desktop. If anything is missing, load the `setting-up-workspaces-applications` skill (through your client's skill tool, or `retrieve_skill` when skills come from the AWS MCP server), finish its setup flow, then come back and continue from the step you were on.

The fleet or builder must also be on Windows Server with a recent WorkSpaces Applications agent. Elastic fleets, multi-session fleets, domain-joined image builders and VPC endpoints aren't supported for agent access.

## What the settings mean for the agent

The settings below come from the stack's or builder's `AgentAccessConfig`, not from connection parameters. A stack's changes reach new sessions only; a running session keeps the settings it started with. A builder's configuration changes only while the builder is stopped, and applies when it starts again.

| Setting | Effect on the agent |
|---|---|
| `COMPUTER_VISION` | The agent can take screenshots. |
| `COMPUTER_INPUT` | The agent can click, type and scroll. Requires `COMPUTER_VISION`, because the agent has to see the screen to use it. |
| `FORWARD_MCP_TOOLS` | MCP servers installed on the image appear as `forwarded___` tools (tool-forwarding.md). |
| `ScreenResolution` | `W_1280xH_720`, the only value: the agent's screen is 1280×720. Take mouse coordinates from the screenshot's own dimensions (tools-reference.md). |
| `ScreenImageFormat` | `PNG` or `JPEG` for screenshots. |
| `UserControlMode` | Whether a person can watch: `VIEW_ONLY`, `VIEW_STOP` (watch and stop the agent), or `DISABLED`. How to open the agent's session for them is in tools-reference.md (Session). |
| `ScreenshotsUploadEnabled` with `S3BucketArn` | Every screenshot is also saved to the bucket, written with the agent's own credentials (connection-setup.md, Screenshot storage). |
| `ReplaySessionEnabled` with `S3BucketArn` | Stacks only. The session is recorded and delivered to the bucket after it closes, as the agent's own identity (replay-session.md). Each desktop action is captured before it runs, so a failed capture blocks the action. |
| `KmsKeyArn` | Only with `ReplaySessionEnabled`. Captured frames are encrypted with this key under the agent's own credentials. If the key becomes unusable, every desktop action fails with a KMS error (replay-session.md). |

A missing tool usually means its action is disabled: no click tools without `COMPUTER_INPUT`, no forwarded tools without `FORWARD_MCP_TOOLS`. Retrying won't help; the setting has to change on the stack or builder, as covered by the `setting-up-workspaces-applications` skill.
