# Fleet rollout — Windows via Microsoft Intune (Desktop + CLI)

## A. Claude Desktop — managed configuration (registry)

On Windows the app reads managed settings from the registry (the `.reg`
equivalent of the macOS managed plist). Authoring tip: on one eval device,
**Developer → Configure Third-Party Inference…** → fill in → **Export** → choose
the Windows `.reg` output, then deploy its values via Intune.

### Registry values
The app reads `REG_SZ` values placed **directly under**
`HKLM\SOFTWARE\Policies\Claude` (machine, recommended) or
`HKCU\SOFTWARE\Policies\Claude` (user). It never reads subkeys, and when any
machine value exists it ignores `HKCU` entirely — deploy the full configuration
to one hive. Every value is a string: booleans `"true"`, arrays/objects as JSON
strings. Avoid `REG_EXPAND_SZ` (counts as policy present but is unreadable).

```
inferenceProvider            = bedrock
inferenceBedrockRegion       = us-east-1
inferenceCredentialKind      = interactive
inferenceBedrockSsoStartUrl  = https://d-xxxxxxxxxx.awsapps.com/start
inferenceBedrockSsoRegion    = us-east-1
inferenceBedrockSsoAccountId = 123456789012
inferenceBedrockSsoRoleName  = BedrockInference
inferenceModels              = ["us.anthropic.claude-sonnet-5-5"]
claudeAiImport               = {"enabled":true,"bannerBehavior":"detect"}
```

(Cloud vendor profile variant: `inferenceCredentialKind = vendor-profile` plus
`inferenceBedrockProfile`; bearer token: `static` plus
`inferenceBedrockBearerToken`. See `inference-bedrock-keys.md`.) Optional:
`organizationInstructions` (≤ 3,000 chars; the Intune/ADMX text box holds a
single line — use a `.reg` or script for multi-line text).

### Deploy in Intune
Option 1 — **Settings catalog / Custom OMA-URI** (Devices → Configuration →
Create policy → Windows 10+ → Custom): add the registry values as OMA-URI
settings. Make sure the tooling writes them directly under the policy key, not
in a subkey.
Option 2 — **PowerShell platform script** (Devices → Scripts and remediations;
run as SYSTEM, 64-bit) that writes the values:

```powershell
$base = "HKLM:\SOFTWARE\Policies\Claude"
New-Item -Path $base -Force | Out-Null
$values = [ordered]@{
  inferenceProvider            = "bedrock"
  inferenceBedrockRegion       = "us-east-1"
  inferenceCredentialKind      = "interactive"
  inferenceBedrockSsoStartUrl  = "https://d-xxxxxxxxxx.awsapps.com/start"
  inferenceBedrockSsoRegion    = "us-east-1"
  inferenceBedrockSsoAccountId = "123456789012"
  inferenceBedrockSsoRoleName  = "BedrockInference"
  inferenceModels              = '["us.anthropic.claude-sonnet-5-5"]'
  claudeAiImport               = '{"enabled":true,"bannerBehavior":"detect"}'
}
foreach ($k in $values.Keys) {
  New-ItemProperty -Path $base -Name $k -Value $values[$k] -PropertyType String -Force | Out-Null
}
```

Scope to a **pilot device group** first; verify; then widen. Team/Enterprise
claude.ai owners must also allow member data export for history import
(not possible in HIPAA-ready orgs).

### Verify (pilot)

- **Help → Troubleshooting → Generate Diagnostic Report** → `managed-config.txt`
  / `provider-status.txt` validated.
- App log shows `[managedConfig] ... managedKeys: [...]` non-empty.
- User completes in-app AWS sign-in at first launch (SSO).

## B. Claude Code CLI — enforced managed settings via Intune

For fleets, deploy Claude Code's **managed settings file** instead of editing
each user's settings. Managed settings sit above every other level — users,
projects, and `--settings` cannot override them.

- **Windows path:** `C:\Program Files\ClaudeCode\managed-settings.json`
- Same JSON shape as `settings.json`; the Bedrock switch goes in `env`.
- Claude Code reads only one endpoint-managed source by default. If you already
  ship a managed policy, the script below **merges** the Bedrock `env` keys into
  it and keeps everything else. It backs up the file first and stops without
  changes if the file isn't valid JSON. Written for Windows PowerShell 5.1;
  test it on a pilot device before assigning it widely.

### B1. Platform script (Intune → Devices → Scripts and remediations; run as SYSTEM, 64-bit)

```powershell
# Deploys Claude Code CLI 3P (Bedrock) as an enforced managed policy.
# Merges the Bedrock env keys into an existing managed-settings.json instead of
# replacing it, so permissions and other org policy already in the file survive.
$ErrorActionPreference = "Stop"
$dir = "C:\Program Files\ClaudeCode"
$f   = Join-Path $dir "managed-settings.json"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$envKeys = [ordered]@{
  CLAUDE_CODE_USE_BEDROCK        = "1"
  AWS_REGION                     = "us-east-1"
  AWS_PROFILE                    = "claude-bedrock"
  ANTHROPIC_MODEL                = "us.anthropic.claude-sonnet-5-5"
  ANTHROPIC_DEFAULT_SONNET_MODEL = "us.anthropic.claude-sonnet-5-5"
  ANTHROPIC_DEFAULT_OPUS_MODEL   = "us.anthropic.claude-opus-5-5"
  ANTHROPIC_DEFAULT_HAIKU_MODEL  = "us.anthropic.claude-haiku-5-5"
}
$settings = [pscustomobject]@{}
if (Test-Path $f) {
  Copy-Item $f "$f.bak" -Force   # one rolling backup; safe to run as a Remediation
  $text = Get-Content -Path $f -Raw -Encoding UTF8
  if ($text -and $text.Trim()) {
    try { $settings = $text | ConvertFrom-Json }
    catch { throw "Existing $f is not valid JSON; fix or remove it, then re-run. Nothing was changed." }
    if ($settings -isnot [pscustomobject]) { throw "Existing $f is not a JSON object. Nothing was changed." }
  }
}
if ($null -ne $settings.env -and $settings.env -isnot [pscustomobject]) {
  throw "Existing $f has an `"env`" that is not a JSON object. Nothing was changed."
}
if ($null -eq $settings.env) {
  $settings | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{}) -Force
}
foreach ($k in $envKeys.Keys) {
  $settings.env | Add-Member -NotePropertyName $k -NotePropertyValue $envKeys[$k] -Force
}
$json = $settings | ConvertTo-Json -Depth 32
[System.IO.File]::WriteAllText($f, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Output "Claude Code managed settings merged: $f"
```

Settings: **Run this script using the logged on credentials = No** (SYSTEM),
**Run script in 64-bit PowerShell = Yes**. Assign to the pilot device group.
For drift correction, deploy the same logic as a **Remediation** (detection
script checks that the `env` keys have the expected values; remediation runs
the merge script above).

### B2. AWS profile for the CLI (per user)
Push an IAM Identity Center (SSO) profile — config only, **no secrets**. Run as a
script with **logged on credentials = Yes** (user context):

```powershell
$awsDir = Join-Path $env:USERPROFILE ".aws"
New-Item -ItemType Directory -Force -Path $awsDir | Out-Null
$cfg = Join-Path $awsDir "config"
if (-not (Test-Path $cfg)) { New-Item -ItemType File -Path $cfg | Out-Null }
if (-not (Select-String -Path $cfg -Pattern '^\[profile claude-bedrock\]' -Quiet)) {
@'

[profile claude-bedrock]
sso_session = corp
sso_account_id = 123456789012
sso_role_name = BedrockInference
region = us-east-1

[sso-session corp]
sso_start_url = https://d-xxxxxxxxxx.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
'@ | Add-Content -Path $cfg
}
```

**Human step (prescriptive prompt for users):**
> "Open PowerShell and run `aws sso login --profile claude-bedrock`. Approve the
> sign-in in your browser. Run it again whenever Claude Code reports expired
> credentials (typically every 8–12 hours)."

AWS CLI v2 must be installed (deploy it as a Win32 app if needed).

### B3. Verify (pilot device)

- Run `claude`, then `/status`. **Setting sources** must show
  `Enterprise managed settings (file)`.
- A prompt succeeds and CloudTrail shows `InvokeModel*` under the user's SSO
  identity.

### Revert
Remove the `env` keys from the managed file (or delete it) via a script or
remediation.

## WSL
Claude Code inside WSL reads `/etc/claude-code/managed-settings.json` in the
Linux distro. Deploy the same JSON there (for example, a script that runs
`wsl -u root` to write the file), and put the SSO profile in the WSL user's
`~/.aws/config`. The Windows registry/Desktop config covers the desktop app only.
