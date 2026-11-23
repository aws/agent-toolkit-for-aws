# Terminal helpers: what the agent runs so the person only clicks Approve

Use these to cut down human steps, only after the CONFIRM step. None of them
reads or edits credential files. Never run them for Route C or on a device IT
manages, except opening a page. If a command isn't available (for example
`xdg-open` on a machine with no desktop session), fall back to the written
prompt for that step.

## Open a page or file for the person

Open links in the person's default browser instead of asking them to copy URLs.
Only open a claude.ai link if the default browser is the one where they're
signed in to claude.ai; otherwise give them the link.

| Platform | Command |
|---|---|
| macOS | `open "<url-or-file>"` |
| Windows (PowerShell) | `Start-Process "<url-or-file>"` |
| Linux | `xdg-open "<url-or-file>"` |

Useful targets:

- Bedrock Model catalog (use case form):
  `https://console.aws.amazon.com/bedrock/home?region=<region>#/model-catalog`.
  If it lands elsewhere, tell the person to choose **Model catalog** in the
  left menu.
- claude.ai settings (manual export, Phase 3M): `https://claude.ai/settings`,
  then tell them to open **Privacy → Export data**.
- Each `export_url` in the claude.ai export manifest (Phase 3M). Open one at a
  time and wait for each download to finish. Never fetch these with curl or
  wget.
- A generated `.mobileconfig` on a test Mac you're piloting (Route B only,
  never on a managed device): `open` registers the profile. The person then approves it in **System Settings** (search for
  "Profiles"). macOS doesn't allow installing a profile without that approval.

## Make sure Claude Desktop is fully quit (before any Desktop file step)

macOS: check, ask the app to quit, then check again.

```bash
pgrep -x Claude >/dev/null && osascript -e 'tell application "Claude" to quit'
sleep 10; pgrep -x Claude >/dev/null && echo "still running" || echo "quit"
```

The first time, macOS may ask whether the terminal app can control "Claude";
tell the person to click **OK** (or quit the app themselves). If the app shows
a quit dialog, they answer it. If it's still running, ask the person to quit it from the menu bar icon
(**Quit Claude**). Never force-kill it (`kill -9`); that can lose the change
you're about to make. To reopen it afterwards: `open -a Claude`.

Windows: don't check by process name. Claude Code's own `claude.exe` matches
too, so the result can't be trusted. Ask the person to quit Claude Desktop from
the system-tray icon (**Quit**) and confirm before you continue.

## Check Bedrock model access (read-only)

```bash
aws bedrock get-use-case-for-model-access --region <region> --query 'length(formData)'
```

- A number means the account has already submitted the Anthropic use case
  form. Skip that step.
- `ResourceNotFoundException` means it hasn't been submitted (or isn't visible
  to this role). Open the Model catalog link above and give the use case form
  prompt (HUMAN STEP).
- `AccessDeniedException` means the role can't read it
  (`bedrock:GetUseCaseForModelAccess`). Fall back to the test invocation in
  `cli-3p-setup.md`, which fails with an access error until access is granted.

Don't submit the form yourself with `put-use-case-for-model-access`. Its
`formData` format isn't published, and the answers describe the person's
business and use case. Those are theirs to give, in the console.

## Start an SSO sign-in

`aws sso login --profile <profile>` opens the browser and blocks until the
person approves, which can outlast a tool call's time limit. Run it in the
background, tell them to approve the request in the browser, then poll
`aws sts get-caller-identity --profile <profile>` until it succeeds (stop
after about 5 minutes and ask). On a machine without a browser, run it with
`--use-device-code` and read them the code. A sign-in refreshes the AWS SSO
token cache under `~/.aws/sso/cache`; don't open or print those files.
