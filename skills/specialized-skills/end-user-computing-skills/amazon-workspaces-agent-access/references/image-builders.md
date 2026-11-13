# Connecting to an Image Builder

An agent can drive an image builder the same way it drives a fleet session, typically to install and test applications and then create the image. The builder must have agent access turned on (an `AgentAccessConfig` on the builder) and be `RUNNING`; check both with `describe-image-builders` (prerequisites.md). If there's no builder yet, or its agent access is off, load the `setting-up-workspaces-applications` skill to create or configure it rather than writing those commands yourself, then come back here.

## How a builder session differs from a fleet session

- **The agent chooses the Windows account.** Every image builder has three built-in accounts, and the agent signs in as one of them. Other usernames aren't accepted.

  | Value | Account | Use it for |
  |---|---|---|
  | `ADMINISTRATOR` | Local administrator | Installing applications, Image Assistant, capturing the image |
  | `TEMPLATE_USER` | Template User | Settings that become the default profile for fleet users |
  | `TEST_USER` | Test User, no admin rights | Checking that the apps work for an ordinary user |

- **Two tools exist only on builders.** `switch_user` with `{"user": "TEST_USER"}` signs the desktop in as another of the three accounts, and returns once that account is signed in. `get_current_user` returns the account in use. Call `get_current_user` at the start of a resumed session and before any `switch_user`.
- **No application catalog tools.** Builders have no catalog, so `launch_application` and `toggle_app_switcher` don't appear.
- **One controller at a time.** A person watches in a browser through a builder streaming URL (`create-image-builder-streaming-url`). They see which account the agent is using and, with `UserControlMode: VIEW_STOP`, can stop the agent, but can't take control while it's connected. The native WorkSpaces Applications client can't connect to a builder with agent access on.
- **What the agent does ships in the image.** Files, settings and anything typed stay on the builder and are captured into the image, then into every fleet instance built from it. Remove what the work left behind before capture.

## Two ways to connect

The endpoint, SigV4 signing and connect modes are the same as for a fleet session (connection-setup.md, connection-modes.md). Either way, the request names the Windows account.

**Name the builder, and the MCP server creates the session.** This suits a statically configured MCP client, because the values stay the same from one session to the next:

| Header | `_meta` key | Value |
|---|---|---|
| `x-amzn-agentaccess-workspaces-applications-image-builder-name` | `aws.agentaccess/workspacesApplicationsImageBuilderName` | The builder's name. The account and Region come from the signed request. |
| `x-amzn-agentaccess-local-user` | `aws.agentaccess/localUser` | `ADMINISTRATOR`, `TEMPLATE_USER` or `TEST_USER` |

The server creates the builder's streaming URL with the caller's own credentials, so the caller also needs `appstream:CreateImageBuilderStreamingURL` on the builder.

```python
async with aws_iam_streamablehttp_client(
    endpoint="https://agentaccess-mcp.us-east-1.api.aws/mcp",  # the builder's Region
    aws_service="agentaccess-mcp",
    aws_region="us-east-1",  # must match the builder's Region
    headers={
        "x-amzn-agentaccess-workspaces-applications-image-builder-name": "my-builder",
        "x-amzn-agentaccess-local-user": "ADMINISTRATOR",
    },
) as (read, write, _):
    ...
```

**Or pass a builder streaming URL.** Create it right before connecting, because a builder URL is single-use, and send it as the `X-Amzn-AgentAccess-Streaming-Session-Url` header together with `x-amzn-agentaccess-local-user`:

```
aws appstream create-image-builder-streaming-url --name <builder> --validity 300 \
  --query StreamingURL --output text
```

`CreateStreamingURL` doesn't work for builders. Treat the URL as a secret, as for fleets.

Rules for both:

- **Send the local user on every request.** It's required when the session starts. When the desktop reconnects, it signs back in as the account the session last used.
- **One source per field.** The same field in both a header and `_meta` is rejected. Don't combine the builder name with stack, user ID, streaming URL or SAML inputs.
- **The builder must be `RUNNING`.** Check with `aws appstream describe-image-builders --names <builder> --query 'ImageBuilders[0].State'`.

## Adding the server to a coding agent

A coding agent such as Claude Code or Kiro can drive the builder through an entry in its own MCP config, with the builder name and local user as `--header` values. The config, and the rule to add or reconnect it only once the builder is `RUNNING`, are in connection-setup.md (From a coding agent's MCP config).

## Installing applications and creating the image

The usual job on a builder. Work through it in one session, and do every step in order. Steps 2 and 4 apply even to a single small application, because the image ships to every fleet instance and nobody tests it again before it does.

Before the agent starts, turn on screenshot storage for the builder and a CloudTrail trail with `agentaccess-mcp` data events (connection-setup.md). Replay Session isn't available on builders, so these are the only record of what the agent did.

Throughout the job:

- **Don't weaken the builder.** Never change permissions, group membership, UAC, Microsoft Defender, the firewall, update settings, services or session scripts, and never create, rename or delete a local account. If an application seems to need one of these, stop and tell the user.
- **Leave what runs on every instance alone.** Session scripts (which can run as SYSTEM), scheduled tasks, services, Run keys, startup folders and the forwarded MCP manifest run on every fleet instance. Change them only when the user's task names them.
- **Install current releases.** Use the current release of each application, and tell the user the date of the builder's base image. [Managed image updates](https://docs.aws.amazon.com/appstream2/latest/developerguide/keep-image-updated-managed-image-updates.html) keep an image's operating system and agent current.
- **After a restart, carry on.** If an installer restarts Windows, the session ends. Reconnect, call `get_current_user`, and continue from the step that was running.

1. **Get the inputs from the user:** where each application's installer comes from and any license keys. Install only from sources the user names, and use the exact URL the user gives: never a search result, and stop if the download redirects to another domain. A license key is a secret. When you ask for one, say that typing it can put it in your screenshots and screenshot storage. Type it only where the installer asks for it, and don't save it to a file. No tool copies a file from the user's machine to the builder, so each installer is either a download link the builder can reach, or an S3 location the builder's IAM role can read. For an installer that's only on the user's machine, the `setting-up-workspaces-applications` skill uploads it to S3 and creates the builder with that role.
2. **Install as `ADMINISTRATOR`.**
   - First record a baseline to compare against in step 6: local accounts and the Administrators group (`Get-LocalUser`, `Get-LocalGroupMember Administrators`), services (`Get-Service`) and listening ports (`Get-NetTCPConnection -State Listen`).
   - Download installers to `$env:TEMP` or the Downloads folder: the root of `C:` doesn't accept new files from a shell that isn't elevated. For an S3 location, run `aws s3 cp s3://<bucket>/<key> $env:TEMP\ --profile appstream_machine_role` in PowerShell, which uses the builder's role. Every account on the builder can use that role, so it should allow only `s3:GetObject` on the installer prefix. Never type credentials or a presigned URL into the builder, because screenshots and screenshot storage capture what's typed.
   - Before running an installer, check it: `Get-AuthenticodeSignature "<file>"` must show `Valid` and the publisher you expect, or `Get-FileHash "<file>"` must match a SHA-256 the user gave. Stop if neither does.
   - Run each installer, apply the configuration the workflow needs, then launch each application and take a screenshot to confirm its window opened. A file on disk doesn't show that the application starts. Installers that ask for elevation work here, unlike in a fleet session.
3. **Set fleet users' defaults as `TEMPLATE_USER`.** Settings every fleet user should start with, such as application preferences and dismissed first-run dialogs, belong in the Template User's profile. `switch_user` to `TEMPLATE_USER` and set them. Never sign in to a website or account as Template User, because `update-default-profile` copies the whole profile, cookies and tokens included, to every fleet user. Before leaving, clean the profile: sign out of the applications, clear browser data, and delete files the defaults don't need. Then `switch_user` back to `ADMINISTRATOR` and copy the profile to the default profile with `image-assistant.exe update-default-profile`. If the workflow needs no default settings, skip this step and tell the user you did.
4. **Test as `TEST_USER`.** `switch_user` to `TEST_USER`, launch each application, and check it works without admin rights. Don't go on until each one does: an application that works only for an administrator fails in every fleet session. If one doesn't, don't change permissions or security settings to make it work; stop and tell the user. Then switch back to `ADMINISTRATOR`.
5. **Clean up.** Everything on the builder goes into the image and onto every fleet instance built from it. Delete downloaded installers and temporary files, close applications, sign out of websites, and remove anything typed that shouldn't ship.
6. **Get the user's approval.** No IAM action gates image creation, because Image Assistant runs on the builder, so the user's yes is the gate. As `ADMINISTRATOR` in PowerShell on the builder (`key("super+r")`, `type_text("powershell")`, `key("Return")`), register each application, then validate the image without creating it. `image-assistant.exe` is on the path:

   ```
   image-assistant.exe add-application --name "<name>" --absolute-app-path "<path to .exe or .bat>"
   image-assistant.exe create-image --name "<image-name>" --use-latest-agent-version --tags "AgentAccessMcpSessionId" "<mcpSessionId>" --dry-run
   ```

   Run `add-application` once per application, up to 50. Each command prints a JSON status; `"status": 0` means success. The tag value is `mcpSessionId` from `get_session_info`, so the image can be traced to the session that built it. Then show the user, in one message:

   - each application with its source, version and the installer's SHA-256 (`Get-FileHash`),
   - every setting you changed and every file you left on the builder,
   - any change to what runs on every instance,
   - how local accounts, group membership, services and listening ports differ from the baseline,
   - the dry run's result,
   - that the image will always use the latest WorkSpaces Applications agent, unless they want it pinned to the installed version. Without `--use-latest-agent-version`, Image Assistant pins it, and changing that later takes a new image.

   Wait for the user's explicit yes before going on.
7. **Create the image** with the same `create-image` command without `--dry-run`, or with `--no-use-latest-agent-version` in place of `--use-latest-agent-version` if the user asked to pin the agent. Tell the user which you used. `create-image` puts the builder into `SNAPSHOTTING`, which ends the session, so it's the last thing the agent does there.

Names: an image name is up to 100 characters of letters, digits, `_`, `-` and `.`, and can't start with `aws`, `appstream` or `amazon`. An application name has no spaces and is up to 256 characters. Check names before typing them, and quote names and paths.

After that, the image is ready when `aws appstream describe-images --names <image-name> --query 'Images[0].State'` returns `AVAILABLE`, and the builder stops by itself. Don't update a fleet to the new image: tell the user to test it on a non-production fleet first. If a session ends without an image, the builder keeps billing while it runs, so stop it (`aws appstream stop-image-builder --name <builder>`) once no more work is planned on it.

## IAM

Scope builder sessions with the `agentaccess-mcp:ImageBuilderArn` condition key (`arn:aws:appstream:<region>:<account>:image-builder/<name>`), the way fleet sessions use `agentaccess-mcp:StackArn`. Limit which Windows accounts the agent may use with `agentaccess-mcp:LocalUser`:

- It's set only on requests that sign an account in: connecting, reconnecting, and `switch_user`, where it's the destination account. Use `StringEqualsIfExists` in an Allow, so requests that sign nobody in still match.
- Its values are the upper-case names above, and `StringEquals` is case-sensitive, so a policy that says `test_user` never matches.
- `switch_user` needs `agentaccess-mcp:SwitchUser`, checked against the destination account, so keep `SwitchUser` in the statement with the `LocalUser` condition, as below. `get_current_user` needs `agentaccess-mcp:GetCurrentUser`.
- It controls which account signs in, not what the agent does once signed in, and a tightened policy applies only at the next sign-in. It also limits only Agent Access sessions: anyone with `appstream:CreateImageBuilderStreamingURL` on the builder can open it in a browser and sign in as any of its accounts, so grant that action only to identities that need it. The agent needs it for the builder-name path, where the server creates the URL, so give the agent's statement `"StringEquals": {"aws:CalledViaAWSMCP": "agentaccess-mcp.amazonaws.com"}` as below, which leaves the agent's identity unable to open the builder outside Agent Access. A person who watches the session, or code that creates builder URLs for the streaming URL path, needs the action from their own identity, without that condition.

This policy lets the agent drive one builder as Administrator or Test User, but not as Template User:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "agentaccess-mcp:InvokeMcp",
        "agentaccess-mcp:GetScreenshot",
        "agentaccess-mcp:LeftClick",
        "agentaccess-mcp:TypeText",
        "agentaccess-mcp:KeyPress",
        "agentaccess-mcp:Scroll",
        "agentaccess-mcp:SwitchUser",
        "agentaccess-mcp:GetCurrentUser"
      ],
      "Resource": "*",
      "Condition": {
        "ArnLike": { "agentaccess-mcp:ImageBuilderArn": "arn:aws:appstream:<region>:<account>:image-builder/<builder>" },
        "StringEqualsIfExists": { "agentaccess-mcp:LocalUser": ["ADMINISTRATOR", "TEST_USER"] }
      }
    },
    {
      "Effect": "Allow",
      "Action": "appstream:CreateImageBuilderStreamingURL",
      "Resource": "arn:aws:appstream:<region>:<account>:image-builder/<builder>",
      "Condition": {
        "StringEquals": { "aws:CalledViaAWSMCP": "agentaccess-mcp.amazonaws.com" }
      }
    }
  ]
}
```

A policy with no `LocalUser` condition allows every Windows account, and a fleet policy with no `ImageBuilderArn` condition also drives builders. Give a role meant only for fleets this statement too:

```json
{ "Effect": "Deny", "Action": "agentaccess-mcp:*", "Resource": "*", "Condition": { "Null": { "agentaccess-mcp:ImageBuilderArn": "false" } } }
```

A builder session is an administrator desktop with no end user. The agent's IAM policy, the builder's role and the rules in the steps above are what limit what happens there. Who can change the builder's agent access settings is controlled separately by `appstream:UpdateImageBuilder`.

## Errors specific to builders

| Error | Cause | Fix |
|---|---|---|
| `InvokeMcp is not allowed for local user: <USER> by the IAM policy.` (JSON-RPC `-32602`) | The policy doesn't allow that Windows account. | The MCP session stays open: call `switch_user` with an account the policy allows. On the first connect there's no session yet, so initialize again with an allowed local user. |
| `... requires a local user via the x-amzn-agentaccess-local-user header or the aws.agentaccess/localUser _meta key: one of ADMINISTRATOR, TEMPLATE_USER, TEST_USER` | No local user on a request that signs an account in. | Add the header or `_meta` key, and send it on every request. |
| `local user must be one of ADMINISTRATOR, TEMPLATE_USER, TEST_USER` | Any other value. | Use one of the three. |
| `switch_user` fails with HTTP 403 | The policy doesn't allow `agentaccess-mcp:SwitchUser` for the destination account. The desktop stays signed in as before. | Switch to an account the policy allows, or ask for the policy to change. |
| `APP_STREAM_IMAGE_BUILDER_LOGON_FAILED` | The Windows sign-in failed, so the session ended. | Reconnect. If it repeats, check the builder's state and health with `describe-image-builders`. |
| `Image Builder not found in this region` (HTTP 400) | No builder with that name in the signed Region: the name or Region is wrong, or the builder hasn't been created yet. | Check the name and Region with `describe-image-builders`. If it was just created, wait for `RUNNING` and reconnect. |
| `The Image Builder must be in the RUNNING state to create a streaming URL.` (HTTP 400) | The builder is stopped or still starting. | Start it, or wait for `RUNNING`, then reconnect. |
