---
name: signing-in-to-aws
description: |
  Gets AWS credentials for CLI/SDK access via `aws login`, or `aws signup` for a developer with no AWS account, creating the account on the way. Activates when a developer needs to authenticate to AWS for local development, when an AWS operation or AWS MCP Server tool fails due to missing or expired credentials, or when someone asks about setting up AWS access or creating an AWS account. Triggers: "set up AWS", "configure AWS", "aws login", "aws signup", "get credentials", "authenticate", "session expired", "token expired", "no credentials", "create an AWS account", "sign up for AWS", "I don't have an AWS account", "no AWS account", "AccessDeniedException" with no configured credentials, "Authentication required" or "Auth required" from an AWS MCP Server tool.
---

# Sign In — Get CLI/SDK Credentials

Help developers get AWS credentials for local development using `aws login`, or `aws signup` when they say they have no AWS account. Both open a browser flow that ends with short-term, auto-rotating credentials that refresh every 15 minutes and remain valid for up to 12 hours. A developer with no AWS account creates one in the same browser flow; the sign-in page routes new and existing customers to the right place, so you never need to ask whether they already have an account.

**Important:**

- You MUST run `aws login`, `aws signup`, and `aws --version` in the user's local shell, not via MCP/API tools.
- You MUST ask the user for confirmation before running `aws login` or `aws signup`. Do not tell the user to run the command themselves. Ask if YOU should run it (e.g., "Ready for me to run `aws login`?" or "Shall I proceed with `aws login --profile staging`?"). Wait for their response before proceeding.
- The command waits for the whole browser flow, including account creation, which can take several minutes. Leave it running unless the user asks you to stop it or to run it again, for example with a different Region.

## Prerequisites

The `aws login` command requires **AWS CLI version 2.32.0 or later**. The `aws signup` command, used only when the user says they have no AWS account, requires a newer release; the flow below checks for it.

Check the installed version:

```bash
aws --version
```

If the CLI is not installed or is below 2.32.0, inform the user and ask if they'd like to install/update (link them to the [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)), or if they'd prefer to continue without this skill's guidance. The user installs or updates the CLI from the guide; do not install or update it yourself, with an installer script or a package manager. If they choose to continue without upgrading, respond to their original request as you normally would without this skill.

## Flow

### Lead with the recommendation

In your first response, name the fix. Unless the user says they have no AWS account, it is `aws login`: it gives short-term, auto-rotating credentials, requires AWS CLI 2.32.0 or later, and covers missing, expired, invalid, or rejected credentials. For missing credentials, add that its sign-in page also lets a new customer create an account, unless the user says their access worked before. When credentials work but the user wants a different account, a second profile, or to replace long-term access keys, the fix is `aws login --profile <name>`. When the user says they have no AWS account, lead with `aws signup` instead (or `aws login` on a CLI without `signup`) and say "create an account" rather than "log in". In every other case, do not mention `aws signup`. For an authentication error from an AWS MCP Server tool, follow [Authentication Error From an AWS MCP Server Tool](#authentication-error-from-an-aws-mcp-server-tool) instead: there the fix may be an MCP sign-in or restart rather than `aws login`. Do not stop at "let me check your CLI version" — name the remediation up front so the user knows where this is going, then describe the precondition checks you'll run before invoking it.

### Precondition checks (run before asking confirmation)

Run these read-only checks via the local shell to inform your plan. They need no confirmation. Report what you find, but do not gate the recommendation on user-supplied output:

1. `aws --version`: confirm the CLI is 2.32.0 or later. If not installed or too old, link the [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and ask the user as described in [Prerequisites](#prerequisites); continue once the CLI is 2.32.0 or later.
2. `aws sts get-caller-identity` — check current credentials.
   - **Succeeds**: Show the user their Account and Arn. Ask whether to keep these or set up different credentials. If they want to switch, recommend `aws login --profile <name>` so the existing default isn't overwritten. If they said they have no AWS account of their own, run step 3 and use `aws signup --profile <name>` instead.
   - **Fails** (missing, expired, invalid, or rejected credentials): proceed with `aws login` on the default profile, unless the user said they have no AWS account (then step 3).
3. `aws signup help` — only when the user said they have no AWS account. If the CLI reports an invalid choice, use `aws login`; any other result, including an error about rendering help, means `signup` exists, so use `aws signup` below.
4. *(Only if Step 2 succeeded and the user wants different credentials)* `aws configure list` — if `access_key` starts with `AKIA`, explain that long-term access keys are less secure (never expire, persist on disk as secrets, grant indefinite access if leaked) and that `aws login` provides short-term credentials that auto-rotate every 15 minutes, expire automatically, and require no manual rotation.

### Confirm and run the command

Once preconditions are clear, ask the user for confirmation specifically for the `aws login` or `aws signup` invocation. The read-only checks above need none. Do not tell the user to run the command themselves; ask if you should run it (e.g., "Ready for me to run `aws login`?" or "Shall I proceed with `aws login --profile staging`?"). Wait for their response, then run the command (with `--profile <name>` if needed).

A browser tab opens. Tell the user to complete it: a user who said they have no AWS account creates one there, and anyone else signs in. Wait for the command to exit; it waits for the whole flow.

### Verify

After the command completes, run `aws sts get-caller-identity` (with `--profile` if used) to confirm success. If a named profile was used, remind the user to pass `--profile` or set `AWS_PROFILE`.

## Handling Errors

### "command not found" or version too old

The CLI is not installed or below 2.32.0. Link the [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and ask the user as described in [Prerequisites](#prerequisites).

### `aws signup` is not a valid choice

The installed CLI predates the `signup` command. Run `aws login` instead; the sign-in page also offers sign-up.

### Browser doesn't open

Suggest `aws login --remote` which provides a URL and code for cross-device authentication (e.g., when using a remote server without a browser).

### Permission error after login

The IAM identity needs the `SignInLocalDevelopmentAccess` managed policy attached (to the user, role, or group). Root users do not need it. Tell the user to ask their administrator to add it, or attach it themselves if they have IAM permissions.

### Access denied by an SCP right after creating an account

The profile's region is probably not the new account's home region. Tell the user, ask which region their new account is in (they can check the AWS Management Console), then set it with `aws configure set region <region>` (with `--profile` if used).

### GovCloud or China regions

`aws login` is not available in AWS GovCloud (US) or AWS China regions. Do not mention this exception proactively — only relevant if the user explicitly states they are in one of these partitions.

## Authentication Error From an AWS MCP Server Tool

If an AWS MCP Server tool such as `run_script` returns an authentication error ("Authentication required", "Auth required", or a 401), the AI tool has no AWS session for the server. What fixes it depends on how the AI tool connects:

- **Through the MCP Proxy for AWS (SigV4)**, where the MCP config runs `mcp-proxy-for-aws`: the proxy signs with the CLI credentials of the first profile in `AWS_MCP_PROXY_PROFILES`, the proxy's `--profile` argument, or `AWS_PROFILE` (in that order), or the default profile when none is set. Run `aws sts get-caller-identity` with that profile (`--profile <name>`), and also with the `aws_profile` the failing tool call passed, if it passed one, since the proxy signs that call with it. If it fails, follow the flow above with `aws login --profile <name>` for a named profile. If the user's working credentials are in a different profile, tell them to point the proxy at it (its `--profile` argument or `AWS_PROFILE`) instead of signing in again. If it succeeds, the CLI credentials are fine; skip the keep-or-switch question and do not rerun `aws login`. In both cases, tell the user to restart or reconnect the MCP server in the AI tool so it picks up the credentials.
- **Directly to the remote endpoint (OAuth)**, where the MCP config points at the `https://aws-mcp.<region>.api.aws/mcp` URL itself and does not run `mcp-proxy-for-aws` (a SigV4 config also contains that URL, as an argument to the proxy): CLI credentials are not used, so working CLI credentials do not fix this and a failing `aws sts get-caller-identity` does not cause it. This path does not need the AWS CLI, so skip the CLI version check and do not ask the user to install the CLI for it. Tell the user to re-authenticate the AWS MCP Server from the AI tool (its MCP sign-in or reconnect step, which opens AWS Sign-in in the browser). If the browser does not open, append `?oauth=initialize` to the server URL. A 400 page after signing in means the IAM principal needs the `AWSMCPSignInOAuthAccessPolicy` managed policy.

If you cannot tell which one the AI tool uses, name both briefly. Run the flow above only when the AWS CLI is installed and `aws sts get-caller-identity` fails, since the user also needs working CLI credentials for local AWS commands.

## Users With Existing `aws sso login` Workflows

If the user mentions `aws sso login` or has an existing SSO configuration, do NOT redirect them to `aws login`. These are different commands for different situations:

- `aws sso login` is for users whose organization has configured AWS IAM Identity Center (SSO). They have profiles in `~/.aws/config` pointing at an SSO start URL. Respect their established workflow.
- If their `aws sso login` is failing, help troubleshoot within their context: expired SSO session, revoked authorization, cached token issues (`~/.aws/sso/cache/`), or Identity Center configuration changes.

## Fallback to `aws configure`

Do NOT mention `aws configure` in your initial response or include it as a table row alongside `aws login`. Only offer it as an alternative if:

1. The user explicitly declines `aws login` or asks for alternatives
2. The user states they are in GovCloud or China regions (where `aws login` is unavailable)

When offering it, explain that long-term access keys are less secure: they persist on disk as plaintext, never expire automatically, and grant indefinite access if leaked.

## When NOT to Use This Skill

- User is setting up CI/CD credentials — they need IAM roles or OIDC federation, not `aws login`

## Key Points

- Do not front-load troubleshooting — keep the initial response simple and address errors only if they occur
- `aws login` works with root users, IAM users and federation with IAM

## Additional Resources

- [Sign in through the AWS CLI](https://docs.aws.amazon.com/signin/latest/userguide/command-line-sign-in.html)
- [Installing or updating the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [SignInLocalDevelopmentAccess managed policy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SignInLocalDevelopmentAccess.html)
- [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
