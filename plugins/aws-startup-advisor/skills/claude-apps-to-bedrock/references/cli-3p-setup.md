# CLI (Claude Code) — switch to 3P on Amazon Bedrock

The CLI is configured via env vars in `~/.claude/settings.json`. There are two
ways to set them. Both write the same `env` block.

## Option A: built-in setup wizard (recommended when the user is at the keyboard)

Claude Code has a Bedrock setup wizard. It detects AWS profiles in `~/.aws`,
checks which Claude models the account can invoke, lets the user pin them, and
saves the result to `~/.claude/settings.json`. It is interactive, so it's a
HUMAN STEP. Prompt:
> "In a terminal, run `claude`. At the login prompt choose **3rd-party
> platform → Amazon Bedrock**. If you're already signed in and see the chat
> prompt, type `/setup-bedrock` in full (it's hidden from the command menu
> until Bedrock is on). Pick your AWS profile, set the region to `<region>`, and
> pin `us.anthropic.claude-sonnet-5-5` as Sonnet, `us.anthropic.claude-opus-5-5`
> as Opus, and `us.anthropic.claude-haiku-5-5` as Haiku. Tell me when it's done."

Afterwards, read `~/.claude/settings.json` to confirm the `env` block (it holds
no secrets for a profile-based setup), then run the Verify step below. Re-run
`/setup-bedrock` any time to change credentials, region, or pins.

## Option B: edit settings.json directly (you, the agent, can do this)

Use this when the user prefers it or the wizard isn't available. Back up:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak.$(date +%Y%m%d-%H%M%S)
```

Set these keys in the `env` object of `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": "us-east-1",
    "AWS_PROFILE": "default",
    "ANTHROPIC_MODEL": "us.anthropic.claude-sonnet-5-5",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "us.anthropic.claude-sonnet-5-5",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "us.anthropic.claude-opus-5-5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "us.anthropic.claude-haiku-5-5"
  }
}
```

- `AWS_REGION` must be a region where the Claude models are enabled.
- `AWS_PROFILE` must resolve to credentials with the Bedrock policy in `aws-setup.md` (invoke plus inference-profile discovery).
  (A `credential_process`/SSO profile is fine — the CLI uses the resolved creds.)
- `ANTHROPIC_MODEL` is a Bedrock **inference-profile ID**, not a 1P name.
- `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` pin what the `sonnet`, `opus`,
  and `haiku` aliases (and the `/model` picker) resolve to. Without them, the
  aliases use Claude Code's built-in Bedrock defaults, which can lag the newest
  release. `ANTHROPIC_DEFAULT_HAIKU_MODEL` also sets the background-task model
  (it replaces the deprecated `ANTHROPIC_SMALL_FAST_MODEL`). Use only models
  that are Active on Bedrock and enabled in your account.

## Verify (before trusting it)

```bash
# creds resolve to the intended account:
AWS_PROFILE=default aws sts get-caller-identity

# Bedrock actually invokes in the region:
printf '%s' '{"anthropic_version":"bedrock-2023-05-31","max_tokens":8,"messages":[{"role":"user","content":"say ok"}]}' > /tmp/t.json
AWS_PROFILE=default aws bedrock-runtime invoke-model \
  --region us-east-1 \
  --model-id us.anthropic.claude-sonnet-5-5 \
  --body fileb:///tmp/t.json --cli-binary-format raw-in-base64-out /tmp/o.json
cat /tmp/o.json; rm -f /tmp/t.json /tmp/o.json
```

Then start a FRESH shell and run `claude`. Confirm with `/status` or by asking
the model; `claude` should now route through Bedrock.

## Carry 1P context into every CLI session (automatic)
Create `~/.claude/CLAUDE.md` (global user memory, auto-loaded every session):

```markdown
# Global user memory
## Past Claude conversation history (1P export)
Treat the imported file as background reference about my past work and topics.
@/absolute/path/to/claude_export_md/COMBINED-1p-history.md
```

The `@<path>` import pulls the consolidated history into every CLI session.

## Credential expiry (human step)
If the profile uses temporary credentials (IAM Identity Center/SSO, or a
`credential_process` helper) and they expire, the CLI fails to reach Bedrock.

To have Claude Code start the sign-in itself, add `awsAuthRefresh` at the top
level of `~/.claude/settings.json` (next to `env`, not inside it):

```json
{
  "awsAuthRefresh": "aws sso login --profile <profile>",
  "env": { "AWS_PROFILE": "<profile>" }
}
```

Claude Code runs it only when credentials are actually expired (it checks with
STS first), shows the browser URL or code, and retries the request. The user
still approves the sign-in in the browser. Behind a VPN or TLS-inspecting proxy
that interrupts the browser flow, this can open sign-in tabs in a loop; if that
happens, remove `awsAuthRefresh` and use the manual prompt:
> "Your AWS session expired. Run `aws sso login --profile <profile>` (or your
> organization's credential refresh command), approve it in the browser, then
> retry in Claude Code."

## Revert CLI to 1P
Remove the Bedrock env keys above (or restore the backup). The CLI then talks
directly to Anthropic using the user's logged-in Claude account / API key.

## Fleet note
For many devices, don't edit each user's `~/.claude/settings.json`. Deploy the
same `env` block as an **enforced managed settings file** via MDM:

- macOS: `/Library/Application Support/ClaudeCode/managed-settings.json`
- Windows: `C:\Program Files\ClaudeCode\managed-settings.json`
- Linux/WSL: `/etc/claude-code/managed-settings.json`

For SSO fleets, `awsAuthRefresh` can go in the managed file too.
Managed settings override user/project settings and can't be bypassed. Verify
with `/status` → **Setting sources** shows `Enterprise managed settings (file)`.
Templates: `mdm-macos-mobileconfig.md` (Jamf) and `mdm-windows-intune.md` (Intune).
