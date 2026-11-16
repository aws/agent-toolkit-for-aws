# Image Setup: from image requirements to a usable image

The guided path from the environment summary's image requirements to an image the fleet can use. You orchestrate the launchable parts (builder instance, polling). The work inside the builder, installing applications and capturing the image, is done either by an agent connected to the builder through agent access, or by the user in a browser session from instructions you write.

## Decide: do you need a custom image?

- **Trial, or standard apps only** → skip this file. Use a public base image directly: `aws appstream describe-images --type PUBLIC`, pick the newest Windows Server base as in [fleet-stack-recommendations.md § OS & licensing](references/fleet-stack-recommendations.md) (highest version, then latest date in the name, never by `CreatedTime`), and proceed to create-workspace.md.
- **Custom applications required** → build an image, below.

## Decide: who installs the applications?

For agent environments, ask once you know a custom image is needed, even when the request says the desktop is for an agent: the agent that uses the desktop doesn't have to be the one that installs the apps. Question 3 of [onboarding-flow.md](references/onboarding-flow.md) has the exact wording: an AI agent (the default) or the user. When you answer a question about getting apps onto an image instead of running the flow, describe both paths.

- **1, an agent installs.** The builder gets agent access (step 1 below), and the installs are done through the `amazon-workspaces-agent-access` skill, either by you, if this session can reach the Agent Access MCP server, or by the user's own agent. Ask for what the agent can't find on its own, one question per turn: first where each application's installer comes from (Installer sources, below), then, only for an app that needs one, its license key. A license key is a secret. When you ask for one, say that the agent types it into the installer, so it can show up in the agent's screenshots and any Replay Session recording. Keep the key out of the plan, the environment summary and any file. The agent installs only from sources the user names.
- **2, the user installs.** Create the builder without agent access, and write the steps for the user.

For human environments, use option 2.

## Installer sources

Nothing the agent can call copies a file from the user's machine to the builder (the agent access tools are mouse, keyboard and screenshots), so each installer has to come from somewhere the builder can download it.

- **First check what the base image already has.** The [base image release notes](https://docs.aws.amazon.com/appstream2/latest/developerguide/base-image-version-history.html) list the software on each public image, and it differs between Windows Server versions. Don't assume an app is there because it's common.
- **A download link** the builder can reach, such as the publisher's official download. Ask for one first. When the user names a well-known free application without a source, use its publisher's official download and name it as the source in the plan. The plan's go-ahead covers it, and the user can pick another source by changing the plan, so don't ask about it as a separate question inside the plan.
- **A file only on the user's machine.** Put it in S3 and let the builder read it with an IAM role. Each of these is in the confirmed plan:
  1. Upload it to a private bucket in the user's account and Region, an existing one they name or a new one: `aws s3 cp <file> s3://<bucket>/installers/<file name>`. A new bucket keeps Block Public Access on and default encryption at rest, gets a bucket policy that denies requests without TLS (`aws:SecureTransport` is `false`), and should have S3 server access logging on so uploads and downloads can be audited.
  2. Create an IAM role that `appstream.amazonaws.com` can assume (`sts:AssumeRole`), with the trust policy condition `"StringEquals": {"aws:SourceAccount": "<account>"}` so only this account's resources can use it, and allowed only `s3:GetObject` on `arn:aws:s3:::<bucket>/installers/*`. If an existing bucket encrypts with a customer managed KMS key, also allow `kms:Decrypt` on that key, or the download is denied. Pass the role as `--iam-role-arn` on `create-image-builder` (Flow, step 1); the caller needs `iam:PassRole` on it.
  3. On the builder, download it with the role's credential profile: `aws s3 cp s3://<bucket>/installers/<file name> $env:TEMP\ --profile appstream_machine_role`. The AWS CLI is on the public Windows base images. The download goes through the builder's network interface in the user's VPC, so the builder needs default internet access in a public subnet, or a private subnet with a NAT gateway or an S3 gateway endpoint. Check this before creating the builder.

  Give each of these its own line in the plan: the bucket and its settings, the upload command, and the builder IAM role with the one permission it gets. The user is approving a new IAM role, so it can't be folded into an "installer source" line.

  Never type credentials or a presigned URL into the builder: screenshots and Replay Session recordings capture what's typed. The role stays on the builder and isn't part of the image. The uploaded file stays in the bucket until the user asks to delete it. The role is deleted with the builder (Flow, step 5).
- **No source.** When the user has neither a link nor the file for an app, say it can't be installed without an installer and leave it off for now: show it as "Not included" in the plan and continue with the other apps. If no apps remain, say so and ask about the apps again. Don't search for or guess a download link for an app that isn't a well-known free application.

## License-included applications

For people, Office, Visio and Project can be licensed through AWS, so they need no installer or license key. They can't be used for unattended agent work (fleet-stack-recommendations.md § OS & licensing). Take the current applications, versions and Windows Server requirements from the [license-included applications page](https://docs.aws.amazon.com/appstream2/latest/developerguide/license-included-applications.html), and the exact names from `SoftwaresToInstall` in the [CreateImageBuilder API reference](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateImageBuilder.html).

- **Install them when creating the builder** with `--softwares-to-install` and those names, for example `Microsoft_Office_2024_LTSC_Professional_Plus_64Bit`. On an existing builder, use `associate-software-to-image-builder`, then `start-software-deployment-to-image-builder`. Use `--appstream-agent-version LATEST`, since the feature needs a recent agent.
- **All of them use one version and one architecture**, and that version must support the image's Windows Server version, as listed on the license-included applications page.
- **Billing:** every user streaming from a fleet built from the image is billed for them monthly, whether or not they open them. Say so in the plan and link the pricing page.
- **Check progress** with `describe-software-associations --associated-resource <builder ARN>` until each is `INSTALLED`. On `FAILED_TO_INSTALL`, read `DeploymentError`, then retry with `start-software-deployment-to-image-builder --retry-failed-deployments`. They aren't activated on the builder; activation happens in fleet sessions.

## Flow

You run step 1 and do the hand-off in step 2 yourself. While the builder starts, poll `describe-image-builders` in short calls (about 20 seconds apart) and report its state.

1. **Launch an image builder** (mutating and billable, so it goes in the confirmed plan):

   ```bash
   aws appstream create-image-builder \
     --name <workflow>-builder \
     --instance-type <same family as the planned fleet> \
     --image-name <public base image name> \
     --vpc-config SubnetIds=<subnet>,SecurityGroupIds=<sg> \
     --enable-default-internet-access \
     --appstream-agent-version LATEST \
     --disable-imdsv1 \
     --agent-access-config '{
       "Settings": [
         {"AgentAction": "COMPUTER_VISION", "Permission": "ENABLED"},
         {"AgentAction": "COMPUTER_INPUT", "Permission": "ENABLED"}
       ],
       "ScreenResolution": "W_1280xH_720",
       "ScreenImageFormat": "PNG",
       "UserControlMode": "VIEW_STOP"
     }'
   ```

   For `--image-name`, use the newest Windows Server base image, picked as in the first bullet of this file. Leave out `--agent-access-config` when the user installs (option 2). Add `--iam-role-arn <role ARN>` when an installer comes from S3, and `--softwares-to-install` for license-included applications (both sections above). When an agent installs, add the screenshot bucket from question 10 if the user chose one (`"S3BucketArn"` and `"ScreenshotsUploadEnabled": true`, see [agent-access-config.md](references/agent-access-config.md)). Match the instance family to the planned fleet: GPU vs non-GPU affects image compatibility (one-way door). `--enable-default-internet-access` lets the builder download installers and needs a public subnet. The builder starts `PENDING`; poll until `RUNNING`.

   To use an existing builder for agent installs, it needs agent access turned on while stopped: `stop-image-builder`, `update-image-builder --agent-access-config '{...}'`, then `start-image-builder`.

2. **Hand off the builder.**
   - **An agent installs:** load the `amazon-workspaces-agent-access` skill and follow its image builder reference, which covers connecting to `<workflow>-builder` as `ADMINISTRATOR` and steps 3 and 4 below: installing, testing, cleaning up and creating the image. Pass it the application list, the installer sources and any license keys. If you do the installs yourself, add the Agent Access server to your MCP config, or reconnect it, only after the builder is `RUNNING`: a server started earlier fails to connect and stays without desktop tools. The agent access skill's connection reference has the config. If you can't reconnect it yourself, ask the user to, and don't reach the builder another way. Once `create-image` has run, the session ends; come back here and continue with step 5. To let the user watch, give them the command in "Opening the builder in a browser" below.
   - **The user installs:** give the user the command in "Opening the builder in a browser" below. They sign in by choosing **Administrator** on the **Local User** tab.
3. **Install and test the applications.** Work from the environment summary's application list: install each application, apply any workflow-specific configuration, and check that each one launches.
   - **An agent installs:** it follows the agent access skill's image builder reference: install as `ADMINISTRATOR`, put the settings every fleet user should start with in the Template User's profile and copy it to the default profile, and test as `TEST_USER`. The image isn't captured until each application has launched as `TEST_USER`.
   - **The user installs:** write the steps for the user, who runs them in the builder session.
4. **Register applications and capture.** Two equivalent paths inside the builder. Prefer the CLI, because the commands can be written out exactly:
   - **Image Assistant CLI** (`image-assistant.exe`, present on builders launched with `--appstream-agent-version LATEST`), run as the administrator: `add-application` for each app (name, absolute launch path, optional optimization manifest), optionally `update-default-profile`, then `create-image --name <image-name>`.
   - **Image Assistant GUI**: the desktop wizard. Add apps, optimize, configure, review, create.

   Everything on the builder goes into the image and onto every fleet instance built from it. Before capturing, remove what the work left behind: downloaded installers, open files that aren't part of the image, browser sign-ins, and anything typed into a window that shouldn't ship. Capturing puts the builder into `SNAPSHOTTING`, which ends the session; the new image starts `PENDING`.
5. **Poll and clean up.** `describe-images --names <image-name>` until `AVAILABLE`, then **stop the builder** (`stop-image-builder`), which bills while running, and delete it if no further builds are planned. When the builder is deleted, also delete the installer role this flow created (`aws iam delete-role-policy`, then `aws iam delete-role`), after confirming both with the user. A role the user brought stays.
6. **Continue** to [create-workspace.md](references/create-workspace.md) with the new image's name or ARN.

## Opening the builder in a browser

A builder streaming URL grants access to the builder, so the user creates it in their own
terminal and the command opens it in the browser without printing it. Give the user the command
for their operating system, with the real values, to run in a terminal window that has AWS
credentials for account `<account>`. Put it on a line of its own with no backticks, so it copies
cleanly. Do not run it yourself, and never put a builder streaming URL in your reply, a file or a
log.

```
open "$(aws appstream create-image-builder-streaming-url --name <workflow>-builder --region <region> --validity 60 --query StreamingURL --output text)"
```

On Linux, use `xdg-open` in place of `open`. In PowerShell on Windows:

```
Start-Process (aws appstream create-image-builder-streaming-url --name <workflow>-builder --region <region> --validity 60 --query StreamingURL --output text)
```

The URL only has to start the session, so 60 seconds is enough. To open the builder again, the
user runs the command again.

## MCP servers for tool forwarding

When the user wants their own MCP tools forwarded to the agent (question 9 of onboarding-flow.md), the servers are part of the image. Install them system-wide during step 3, and add a manifest at `C:/ProgramData/NICE/dcv/mcp_server_redirection_config.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "C:/path/to/python.exe",
      "args": ["C:/mcpServerPath/filesystem.py", "C:/Users/Public/Documents"]
    },
    "weather": {
      "command": "C:/Program Files/my-mcp/weather.exe"
    }
  }
}
```

- **stdio only.** Each entry launches a process that speaks MCP over stdin and stdout. Remote HTTP or SSE servers aren't supported; wrap one in a local stdio server if needed.
- **`command` (absolute path, required) and `args` (optional) only.** There is no field for environment variables or a working directory. Servers inherit the session environment and run as the session user.
- **Forward slashes in paths.** JSON treats `\` as an escape, and Windows accepts `/` in absolute paths.
- **UTF-8 without a byte order mark.** The service rejects a manifest that has one. Windows PowerShell 5.1's `Out-File -Encoding utf8` writes one, so save it another way.
- **Quick tools.** Each forwarded call must return within 5 seconds.

Also set `FORWARD_MCP_TOOLS` to `ENABLED` on the stack ([agent-access-config.md](references/agent-access-config.md)), and use an image with a WorkSpaces Applications agent that supports forwarding. How the forwarded tools appear to the agent, and the IAM permission to call them, are in the `amazon-workspaces-agent-access` skill.

## Session scripts (pre-warm the agent's session)

For Always-On/On-Demand fleets, session scripts live **on the image** (they're specified within the image; the `SessionScriptS3Location` API field is Elastic-fleet-only). Use them to prepare the environment before the agent connects, for example to pre-launch the target application so the agent skips the app-startup wait, and to clean up after sessions end. Scripts run in user or system context per the image's session-scripts configuration file, and stdout can be logged to S3. The logs go to a bucket the service creates and manages in the account, encrypted in transit and at rest; script output can still hold sensitive data, so don't print secrets and limit who can read that bucket. If the workflow benefits, add the scripts during step 3 and note them in the environment summary.

## Image lifecycle (after the first build)

- **Patching:** use managed image updates. `aws appstream create-updated-image --existing-image-name <img> --new-image-name <img>-YYYYMMDD` produces a new image with the latest Windows, driver and agent updates (add `--dry-run` to just check whether updates are available). Then point the fleet at it with `UpdateFleet` (may require the fleet stopped). Schedule this: an agent fleet on an unpatched image is a security posture problem.
- **Application changes:** repeat the builder flow using the current image as the base. There is no in-place image edit.
- **Cross-region / cross-account:** `CopyImage` to move an image to another region; `UpdateImagePermissions` to share it with another account.

## Facts that prevent surprises

- **The builder bills while running.** Stop it as soon as the image is `AVAILABLE`. (Per-user RDS SAL fees are *not* charged for image builder connections.)
- **`CreateStreamingURL` does not work on builders.** Use `create-image-builder-streaming-url`.
- **An agent can act inside a builder only with agent access on the builder.** Without it, installs, Image Assistant and capture happen in the user's browser session, and your job is to write precise, paste-able steps and commands.
- **Agent access on a builder has limits:** Windows only, not domain-joined, no native client connections, and changes only while the builder is stopped. Details are in [agent-access-config.md](references/agent-access-config.md).
- **Updating an image later** means repeating this flow from the current image as the base; fleets pick up the new image via `UpdateFleet`, which may require the fleet stopped.
- Domain-joined image needs (`DomainJoinInfo` on the builder) and IAM-role-on-image needs (`IamRoleArn`) exist but are admin decisions: flag, don't default. A domain-joined builder can't have agent access.
