# Connecting to AWS Context

Read this when the AWS Context tools are not loaded, when a call fails with an
authentication or credentials error, or when the user runs `/context-login`.

The user runs every login command in their own terminal or browser. Do not run login
commands, do not ask the user to paste tokens, keys or SAML responses, and do not read
credential files. To check whether login worked, ask the user to retry.

## Pick the mode

| Where the agent runs | Mode |
|---|---|
| The user's machine, with a browser | OAuth, in any Region. The plugin's built-in connection is us-east-1; for any other Region, run `/setup` |
| Headless, remote or behind a web backend | SigV4 with an AWS profile |

## OAuth

1. Tell the user to sign in from their client.
   - Claude Code: run `/mcp`, pick the AWS Context server, choose Authenticate.
   - Codex: run `codex mcp login <server-name>`.
   - Kiro: open the MCP panel and choose Authenticate on the AWS Context server.
2. A browser opens on AWS Sign-In. The user approves with their normal AWS console sign-in, including SAML or IAM Identity Center.
3. Ask the user to retry.

If approval fails with an access error, the user's role needs `signin:AuthorizeOAuth2Access`
and `signin:CreateOAuth2Token` on
`arn:aws:signin:*:*:service-principal/context-mcp.amazonaws.com`, in addition to the AWS
Context permissions.

## SigV4

1. The user signs in on the agent host.
   - IAM Identity Center: `aws sso login --profile <profile>`.
   - Okta SAML: `okta-aws-cli web ... --profile context-saml --write-aws-credentials`, with the values their administrator provides.
   - IAM: an existing profile.
2. Switch the connection to the local signing proxy for that profile and Region. `/setup` writes that MCP entry; if you are not already running `/setup`, ask the user to run it.
3. Ask the user to reload MCP servers and retry.

## Region

The endpoint is `https://context-mcp.<region>.api.aws/mcp`. Use the Region where the
user's graph lives. The plugin's built-in connection uses us-east-1; `/setup` connects to any other Region. AWS Context is not available in every Region; check the AWS Context
Regions list in the AWS documentation before suggesting one.

## Errors

| Error | Meaning | What to do |
|---|---|---|
| 401, or the client says the server needs authentication | Not signed in, or the token expired | Repeat the OAuth or SigV4 sign-in |
| ExpiredToken or expired credentials | The AWS profile session ended | The user reruns their login command |
| 403 saying the account is not enabled | The account is not enabled for AWS Context in this Region | Tell the user and stop |
| AccessDenied naming a `context:` action | The role lacks that permission | Name the missing action |
