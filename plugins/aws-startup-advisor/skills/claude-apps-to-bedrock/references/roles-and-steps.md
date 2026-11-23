# Who does what — individual, admin, and managed user

Use this to route the conversation (SKILL.md Phase 0) and to tell each person
only the steps that are theirs.

## The three routes

| Route | Who | Configures 3P | Imports history |
|---|---|---|---|
| **A — Individual (self-managed)** | Own computer; no IT team manages Claude on it | The user, in the in-app window + their own CLI `settings.json` | The user |
| **B — Admin** | IT/admin rolling out to many people via Jamf, Intune, or another MDM | The admin, via MDM (managed profile + CLI managed settings) | Each user (admin only enables it) |
| **C — Managed user** | Work computer where IT has deployed (or will deploy) Claude | Nobody on the device — it comes from the admin's profile | The user |

An admin who also pilots on their own Mac follows Route B, then Route C on the
pilot device.

## Confirm the route from the machine

A managed profile overrides the in-app window's local configuration, so check
before guiding a Route A user through settings that would be ignored.

macOS:

```bash
# Desktop managed profile (machine-wide or per-user)
ls -l "/Library/Managed Preferences/com.anthropic.claudefordesktop.plist" \
      "/Library/Managed Preferences/$USER/com.anthropic.claudefordesktop.plist" 2>/dev/null
# CLI enforced managed settings
ls -l "/Library/Application Support/ClaudeCode/managed-settings.json" 2>/dev/null
```

Windows (PowerShell):

```powershell
Get-ItemProperty "HKLM:\SOFTWARE\Policies\Claude","HKCU:\SOFTWARE\Policies\Claude" -ErrorAction SilentlyContinue
Test-Path "C:\Program Files\ClaudeCode\managed-settings.json"
```

- Desktop profile present → the device is managed → **Route C** for Desktop
  (even if the person said A). Tell them their IT team controls these settings.
- Only the CLI managed file present → CLI is managed; Desktop may still be
  self-configured.
- Nothing present and the person says C → their admin hasn't deployed yet; give
  them the "message to your admin" template below.

## Check where the user already stands (Routes A and C)

Run these read-only checks before planning, so you skip work that's done and
don't describe folders as "will be created" when they exist.

macOS:

```bash
ls -d /Applications/Claude.app 2>/dev/null                         # Desktop installed?
ls -d "$HOME/Library/Application Support/Claude" \
      "$HOME/Library/Application Support/Claude-3p" 2>/dev/null   # 1P / 3P data folders
# Local 3P config the in-app window applied (provider, credential kind, region, models, import):
python3 - <<'PY'
import json, os
d = os.path.expanduser("~/Library/Application Support/Claude-3p/configLibrary")
try:
    m = json.load(open(f"{d}/_meta.json")); c = json.load(open(f"{d}/{m['appliedId']}.json"))
    print({k: c.get(k) for k in ("inferenceProvider", "inferenceCredentialKind",
          "inferenceBedrockRegion", "inferenceBedrockProfile", "claudeAiImport")})
    print("models:", [x if isinstance(x, str) else x.get("name") for x in c.get("inferenceModels", [])])
except FileNotFoundError:
    print("no local 3P configuration yet")
PY
grep -E "CLAUDE_CODE_USE_BEDROCK|AWS_REGION|AWS_PROFILE|ANTHROPIC_MODEL" ~/.claude/settings.json  # CLI on Bedrock?
ls -l ~/.claude/CLAUDE.md 2>/dev/null                              # CLI history already linked?
```

Never print credential values from the config (`inferenceBedrockBearerToken`,
API keys); the snippet above reads only non-secret fields.

Windows equivalents: app typically under `%LOCALAPPDATA%\AnthropicClaude`
(MSIX/enterprise installs differ), `%APPDATA%\Claude` (1P data),
`%LOCALAPPDATA%\Claude-3p\configLibrary\` (3P local config),
`%USERPROFILE%\.claude\settings.json`.

Interpretation:

- `Claude-3p` with an applied Bedrock config → Desktop is already on 3P; go
  straight to verifying it and the import (enable import if `claudeAiImport` is
  missing).
- `claudeAiImport` absent or `enabled` not true → Route A: turn on **Enable
  import**; Route C: ask the admin.
- CLI Bedrock keys present → CLI already switched; just verify.

## Admin steps (Route B)

### One-time, outside the MDM

| # | Step | Where |
|---|---|---|
| A1 | Enable the Claude models in Bedrock for the region | AWS Console → Bedrock |
| A2 | Create an IAM Identity Center permission set with the Bedrock policy in `aws-setup.md` (session 8–12 h), assign users/groups; record start URL, SSO region, account ID, permission-set name | AWS Console → IAM Identity Center |
| A3 | Team/Enterprise only: **Allow members to export their own data** (otherwise users can't import history; not possible in HIPAA-ready orgs) | claude.ai → Settings → Organization → Data and privacy (workspace owner) |
| A4 | Author the configuration on one test device: Bedrock + in-app AWS sign-in + model list + **Capabilities → Claude.ai data import → Enable import** (optional: banner, organization instructions) → **Export ▾** | Claude Desktop → Developer → Configure Third-Party Inference |

### In the MDM

| # | Jamf (macOS) | Intune (Windows) |
|---|---|---|
| M1 | Install Claude Desktop — Policy with the package | Install Claude Desktop — Win32 app |
| M2 | Configuration Profile, preference domain `com.anthropic.claudefordesktop` (Bedrock keys + `claudeAiImport`) | `REG_SZ` values directly under `HKLM\SOFTWARE\Policies\Claude` (Settings catalog / OMA-URI, or a SYSTEM script), or the exported `.reg` |
| M3 | CLI: policy script (root) writes `/Library/Application Support/ClaudeCode/managed-settings.json` | CLI: SYSTEM platform script writes `C:\Program Files\ClaudeCode\managed-settings.json` (Remediation for drift) |
| M4 | AWS CLI v2 + per-user `claude-bedrock` SSO profile in `~/.aws/config` (config only) | AWS CLI v2 + per-user SSO profile in `%USERPROFILE%\.aws\config` (user-context script) |
| M5 | Scope to a pilot Smart Group → verify → widen | Assign to a pilot device group → verify → widen |
| M6 | Changes: edit the profile (redeploys). Rollback: remove from scope | Changes: edit the policy/script. Rollback: unassign |

Pilot verification: **Help → Troubleshooting → Generate Diagnostic Report**
(`managed-config.txt` lists the keys, `provider-status.txt` validated); CLI
`/status` shows `Enterprise managed settings (file)`. Templates:
`mdm-macos-mobileconfig.md`, `mdm-windows-intune.md`.

## User steps (Routes A and C)

| # | Step | When | Route |
|---|---|---|---|
| U0 | Configure Desktop in **Developer → Configure Third-Party Inference…** (Bedrock, model list, **Enable import**) and the CLI `settings.json` | Once | **A only** |
| U1 | Relaunch Claude Desktop after the profile/config is in place | Once | A, C |
| U2 | **Sign in with AWS** in the app (browser → AWS access portal → company login), if the setup uses in-app AWS sign-in | First launch; again when the portal session expires | A, C |
| U3 | **Import history:** **Settings → Import & export → Import…** (or the banner) → **Sign in to claude.ai** → **Authorize** → **Fetch export** → local sessions (include/skip) → **Review → Import** → resolve duplicates | Once; repeat for newer chats | A, C |
| U4 | **Trust and resume** on the first message in an imported chat; **accept** imported project instructions; re-add a project folder under **Context** if Chat needs its files | First use | A, C |
| U5 | CLI: `aws sso login --profile <profile>` (if SSO), new terminal, `/status` | First time; when creds expire | A, C |
| U6 | Optional: CLI history via manual export → `process_export.py` → `~/.claude/CLAUDE.md` | Once, if wanted | A, C |
| U7 | Optional: personal **Settings → General → Instructions for Claude** | Anytime | A, C |

**Route C users never:** open the Configure Third-Party Inference window to
change settings, edit `settings.json` / managed files, or handle AWS keys. If
something is missing (no Bedrock connection, Import not enabled), they ask
their admin.

## Template — admin → users (Route B hands this out)

> **Subject: Claude is moving to our company's AWS account — 10 minutes, one time**
>
> Claude Desktop and Claude Code now run through our AWS account. Your settings
> are already configured. Please:
>
> 1. **Quit and reopen Claude Desktop.**
> 2. Click **Sign in with AWS** and sign in with your company login.
> 3. Bring your old chats over: **Settings → Import & export → Import…** →
>    **Sign in to claude.ai** → **Authorize** → **Fetch export** → **Import**.
>    The first time you reply in an old chat, click **Trust and resume**.
> 4. Claude Code users: in Terminal run `aws sso login --profile claude-bedrock`,
>    then open a new terminal window.
>
> Files you uploaded to claude.ai projects or chats don't come over — re-attach
> any you still need. Questions: [support channel].

## Template — managed user → admin (Route C, when something's missing)

> Hi <IT/admin>, I'm moving to Claude on our AWS (Bedrock) setup.
> [Pick what applies:]
>
> - Settings → Import & export says "Import isn't enabled for this deployment."
>   Could you enable **Claude.ai data import** (`claudeAiImport` with
>   `enabled: true`) in our managed Claude Desktop profile?
> - Claude Desktop isn't connected to Bedrock on my machine (it asks me to sign
>   in to a Claude account). Could you check the managed profile is scoped to my
>   device?
> - claude.ai doesn't show **Export data** for our workspace. Could a workspace
>   owner turn on **Allow members to export their own data**? (If we're a
>   HIPAA-ready org this isn't possible; then I'll skip importing history.)
> Thanks!
