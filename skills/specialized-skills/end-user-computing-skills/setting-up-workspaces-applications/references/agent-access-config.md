# Agent Access Configuration: stacks, image builders, and screenshot storage

Agent access is turned on by an `AgentAccessConfig` on the resource the agent connects to:

- **A stack**, when the agent works on fleet instances.
- **An image builder**, when an agent installs and tests applications before the image is captured.

This file covers the settings, how to set and change them on each resource, and the optional bucket for screenshots and Replay Session recordings. Connecting an agent once the configuration is in place is the `amazon-workspaces-agent-access` skill.

## Settings

| Field | Values | Notes |
|---|---|---|
| `Settings` (required) | `{AgentAction, Permission}` for `COMPUTER_VISION`, `COMPUTER_INPUT`, `FORWARD_MCP_TOOLS` | At least one must be `ENABLED`. `COMPUTER_INPUT` requires `COMPUTER_VISION`. Enable `FORWARD_MCP_TOOLS` only when the image has MCP servers to forward (see image-setup.md). |
| `ScreenResolution` (required) | `W_1280xH_720` | The only accepted value. |
| `ScreenImageFormat` (required) | `PNG` or `JPEG` | Default to `PNG`. |
| `UserControlMode` | `VIEW_ONLY`, `VIEW_STOP`, `DISABLED` | Default to `VIEW_STOP`, so a person can watch in a browser and stop the agent. |
| `ScreenshotsUploadEnabled` | `true` | Optional screenshot storage, below. Requires `S3BucketArn`. |
| `ReplaySessionEnabled` | `true` or `false` (default) | Optional, stacks only. Records each agent session (transcript, MP4 video and HTML report) and delivers it to `S3BucketArn` after the session closes. Requires `COMPUTER_VISION` and `S3BucketArn`. Finding and reading recordings is in the `amazon-workspaces-agent-access` skill. |
| `S3BucketArn` | `arn:aws:s3:::<bucket>` | The bucket for screenshots, Replay Session recordings, or both. Rejected unless `ScreenshotsUploadEnabled` or `ReplaySessionEnabled` is `true`. Both hold sensitive data; the bucket's rules are in Screenshot storage and Replay Session recordings, below. |
| `KmsKeyArn` | `arn:aws:kms:<region>:<account>:key/<id>` | Optional, only with `ReplaySessionEnabled`. Encrypts captured frames while AWS holds them, not the files delivered to the bucket. Must be a key ARN (an alias ARN is rejected) in the stack's Region, and the caller needs `kms:DescribeKey` on it. The key policy the agent needs is in the `amazon-workspaces-agent-access` skill. |
| `ComputerUseInterfaceId` | an interface ID, e.g. `anthropiccomputer20251124` | Optional. Serves the desktop tools in a model provider's computer-use format in place of the standard tools. Leave it unset unless the user asks for one; the supported IDs and how to choose are in the `amazon-workspaces-agent-access` skill. |

The default set for an agent environment: vision and input on, forwarding off unless the user asked for it, `VIEW_STOP`, `W_1280xH_720`, `PNG`, and screenshot storage as the user chose at the screenshot question (question 10 of [onboarding-flow.md](references/onboarding-flow.md)).

## On a stack

```bash
aws appstream create-stack --name <stack> --agent-access-config '{
  "Settings": [
    {"AgentAction": "COMPUTER_VISION", "Permission": "ENABLED"},
    {"AgentAction": "COMPUTER_INPUT", "Permission": "ENABLED"}
  ],
  "ScreenResolution": "W_1280xH_720",
  "ScreenImageFormat": "PNG",
  "UserControlMode": "VIEW_STOP"
}'
```

- **Create:** pass `--agent-access-config` to `create-stack` (step 2 of the create sequence in [create-workspace.md](references/create-workspace.md)). A stack with `AgentAccessConfig` serves agent sessions, so never add it to a stack meant for people.
- **Change:** `aws appstream update-stack --name <stack> --agent-access-config '{...}'`. Partial updates work: send only the fields that change. The update is merged with the stored configuration, so a field left out keeps its value: turn Replay Session off with an explicit `"ReplaySessionEnabled": false`, and clear one field with `--attributes-to-delete AGENT_ACCESS_CONFIG_KMS_KEY_ARN` or `AGENT_ACCESS_CONFIG_COMPUTER_USE_INTERFACE_ID`.
- **Remove:** `aws appstream update-stack --name <stack> --attributes-to-delete AGENT_ACCESS_CONFIG`.
- **When it applies:** changes reach new sessions only. A running session keeps the settings it started with.
- **What the fleet must be:** Windows Server, `ALWAYS_ON` or `ON_DEMAND`, single-session, with a recent WorkSpaces Applications agent on the image. Elastic fleets, multi-session fleets and VPC endpoints aren't supported.

## On an image builder

An image builder has no stack, so its agent access configuration lives on the builder itself, with the same fields as a stack's.

- **Create:** pass `--agent-access-config` to `create-image-builder` (step 1 of [image-setup.md](references/image-setup.md)).
- **Change, or turn it on for an existing builder:** `aws appstream update-image-builder --name <builder> --agent-access-config '{...}'`. Partial updates work as on a stack. The builder must be `STOPPED`, so stop it, update it, and start it again. The builder reads the settings when it starts.
- **Remove:** `aws appstream update-image-builder --name <builder> --attributes-to-delete AGENT_ACCESS_CONFIG`, also while stopped. One call can't both set and remove the configuration.
- **Check:** `aws appstream describe-image-builders --names <builder> --query 'ImageBuilders[0].AgentAccessConfig'`.
- **Then connect:** once the builder is `RUNNING` with the configuration, the agent connects and does the installs through the `amazon-workspaces-agent-access` skill (image-setup.md, step 2).
- **What the builder must be:** Windows, not domain-joined, and on an image with a recent agent. Launching from a current public base image with `--appstream-agent-version LATEST` covers the last part. Linux and domain-joined builders reject the configuration.
- **Who else can connect:** with agent access on, the native WorkSpaces Applications client can't connect to the builder. A person watches in a browser, opened with the command in "Opening the builder in a browser" in [image-setup.md](references/image-setup.md). While the agent is connected, that person can watch and, with `VIEW_STOP`, stop it, but can't take over the mouse and keyboard.
- **CLI and SDK support:** `update-image-builder` and the builder's `--agent-access-config` need an AWS CLI or SDK release that includes them. An older one rejects them before sending (see [troubleshooting.md](references/troubleshooting.md)).

## Screenshot storage

When it's on, every screenshot the agent takes is saved to the bucket under `agentaccess/screenshots/year=YYYY/month=MM/day=DD/<session-id>/<timestamp>.png` (`.jpeg` for JPEG). The managed MCP service uploads them with the connecting agent's own credentials. A failed upload doesn't fail the screenshot, so a misconfigured bucket fails quietly; the `amazon-workspaces-agent-access` skill covers how the agent sees the error.

Rules the bucket must meet:

- **Same account and Region** as the stack or image builder. The service checks the bucket when the stack or builder is created or updated, and rejects one that doesn't exist, belongs to another account, or is in another Region.
- **The bucket policy lets the service check it.** Grant the WorkSpaces Applications service principal, `appstream.amazonaws.com`, `s3:ListBucket` on the bucket, scoped with `aws:SourceAccount`. That one condition covers stacks and image builders. For a tighter scope, `aws:SourceArn` is the stack or image builder ARN.
- **The agent can write to it.** The agent's IAM identity needs `s3:PutObject` on `arn:aws:s3:::<bucket>/agentaccess/screenshots/*`. If the bucket's default encryption uses a customer managed KMS key, it also needs `kms:GenerateDataKey` on that key. The agent's IAM policy is part of connecting it (the `amazon-workspaces-agent-access` skill), so name both permissions in the plan.
- **It holds sensitive data.** Screenshots show whatever is on the desktop. Keep Block Public Access on, encrypt at rest (new buckets use SSE-S3 by default), deny requests that don't use TLS, and limit who can read the bucket. Recommend S3 server access logging to a log bucket the user names; don't create one unless they ask. An S3 lifecycle rule can expire old screenshots; how long to keep them is the user's decision.

### Replay Session recordings

With `ReplaySessionEnabled`, the same bucket also receives each session's transcript, video and report under `agentaccess/replay-session/`. The bucket rules above apply, and two things change:

- **The agent's identity delivers them.** It needs `s3:PutObject` on `arn:aws:s3:::<bucket>/agentaccess/replay-session/*`. If the bucket's default encryption uses a customer managed KMS key, it also needs `kms:GenerateDataKey` and `kms:Decrypt` on that key; without `kms:Decrypt` the video doesn't arrive. Name these in the plan with the screenshot permissions.
- **Recordings show the whole session,** typed input included, and the report and video open directly. `KmsKeyArn` doesn't encrypt them, so the bucket's default encryption is what protects them: use SSE-KMS with a customer managed key if the user wants a key to cover them. Deny requests that don't use TLS, keep Block Public Access on, limit read access to the `agentaccess/replay-session/` prefix with an `s3:prefix` condition, and turn on server access logging. How long to keep recordings is the user's decision.

### The screenshot question (agents only)

Question 10 of [onboarding-flow.md](references/onboarding-flow.md) has the exact wording. It offers a new bucket (the default), a bucket the user already has, or no storage. The default name is `workspaces-agent-screenshots-<account>-<region>`, which fits the 63-character bucket name limit in every Region, and one bucket can serve every agent environment in the account and Region. What each answer needs:

- **1, a new bucket.** Nothing is created until the plan is confirmed. If the user sent their own name, check it's a valid bucket name. In the plan, list the bucket and its policy as the first thing created. Create it with the commands below before `create-stack`, because the stack names the bucket.
- **2, an existing bucket.** Ask for the name, then check it before the plan:

  ```bash
  aws s3api head-bucket --bucket <bucket> --expected-bucket-owner <account>
  aws s3api get-bucket-location --bucket <bucket>    # LocationConstraint null means us-east-1
  aws s3api get-bucket-policy --bucket <bucket>
  ```

  If the bucket belongs to another account or sits in another Region, say so and offer 1 or 3. `put-bucket-policy` replaces the whole policy, so add the service-principal statement to the existing statements, never drop any, and show the change in the plan. If the bucket already grants `s3:ListBucket` to `appstream.amazonaws.com`, leave its policy alone.
- **3, no screenshots.** Leave `ScreenshotsUploadEnabled` out, and `S3BucketArn` too unless Replay Session uses the bucket. Storage can be added later with `update-stack` or `update-image-builder`.

### Creating a new bucket

```bash
aws s3api head-bucket --bucket <bucket> --expected-bucket-owner <account>   # exists already? reuse it
aws s3api create-bucket --bucket <bucket> --region <region> \
  --create-bucket-configuration LocationConstraint=<region>                # leave this flag out in us-east-1
aws s3api put-bucket-policy --bucket <bucket> --policy file://screenshot-bucket-policy.json
```

If `head-bucket` succeeds, the bucket is already this account's from an earlier run: use it and check its policy as for option 2. If `create-bucket` reports the name is taken, another account owns it, so suggest a different name. Write the policy file to the user's working directory:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowWorkSpacesApplicationsBucketCheck",
      "Effect": "Allow",
      "Principal": { "Service": "appstream.amazonaws.com" },
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": { "StringEquals": { "aws:SourceAccount": "<account>" } }
    },
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    }
  ]
}
```

A new bucket already blocks public access and encrypts objects with SSE-S3.

### At teardown

The bucket holds the record of the agent's work, so it is not part of the environment's teardown. List it in the teardown confirmation as kept. Delete it only when the user asks for that specifically: emptying it (`aws s3 rm s3://<bucket> --recursive`) and deleting it (`aws s3api delete-bucket --bucket <bucket>`) permanently remove every screenshot, so it gets its own confirmation that names the bucket. Never delete an existing bucket the user brought (option 2).
