# Fleet rollout — macOS via Jamf (Desktop + CLI)

## A. Claude Desktop — managed configuration profile (`.mobileconfig`)

Push a Configuration Profile with preference domain
`com.anthropic.claudefordesktop`. macOS installs it under
`/Library/Managed Preferences/`, and the app reads it at launch to enter 3P.
A managed profile takes precedence over (and disables) the local configuration
written by the in-app window.

**Encoding:** every value is a string — booleans `true`/`false`, arrays and
objects as one JSON string (a native `<array>`/`<dict>` is also accepted on
macOS).

### Template — In-app AWS sign-in (recommended for fleets)
Replace the SSO values with those from `aws-setup.md`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadType</key>            <string>Configuration</string>
  <key>PayloadVersion</key>         <integer>1</integer>
  <key>PayloadIdentifier</key>      <string>com.yourorg.claude.bedrock</string>
  <key>PayloadUUID</key>            <string>REPLACE-WITH-UUID</string>
  <key>PayloadDisplayName</key>     <string>Claude Desktop — Bedrock 3P</string>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadType</key>        <string>com.anthropic.claudefordesktop</string>
      <key>PayloadVersion</key>     <integer>1</integer>
      <key>PayloadIdentifier</key>  <string>com.yourorg.claude.bedrock.inner</string>
      <key>PayloadUUID</key>        <string>REPLACE-WITH-UUID-2</string>
      <key>inferenceProvider</key>          <string>bedrock</string>
      <key>inferenceBedrockRegion</key>     <string>us-east-1</string>
      <key>inferenceCredentialKind</key>    <string>interactive</string>
      <key>inferenceBedrockSsoStartUrl</key><string>https://d-xxxxxxxxxx.awsapps.com/start</string>
      <key>inferenceBedrockSsoRegion</key>  <string>us-east-1</string>
      <key>inferenceBedrockSsoAccountId</key><string>123456789012</string>
      <key>inferenceBedrockSsoRoleName</key><string>BedrockInference</string>
      <key>inferenceModels</key>
      <string>["us.anthropic.claude-sonnet-5-5"]</string>
      <!-- Lets users run Settings → Import & export → Import… (claude.ai history) -->
      <key>claudeAiImport</key>
      <string>{"enabled":true,"bannerBehavior":"detect"}</string>
      <!-- Optional: org-wide instructions for every session (max 3,000 chars) -->
      <!-- <key>organizationInstructions</key><string>…</string> -->
    </dict>
  </array>
</dict>
</plist>
```

Cloud vendor profile variant: `inferenceCredentialKind` = `vendor-profile` plus
`inferenceBedrockProfile`. Bearer-token variant: `static` plus
`inferenceBedrockBearerToken`. See `inference-bedrock-keys.md`. Generate UUIDs
with `uuidgen`.

To restrict history import to your claude.ai workspace, use
`{"enabled":true,"allowedOrganizationUuids":["<org-uuid>"]}` (sign-in import
only). Team/Enterprise owners must also allow member data export on claude.ai
(not possible in HIPAA-ready orgs).

Fastest authoring path: on one eval device, **Developer → Configure Third-Party
Inference…** → fill in → **Export** the `.mobileconfig`, then use that as your
Jamf template.

### Deploy in Jamf

1. Jamf Pro → **Computers → Configuration Profiles → New**.
2. **Application & Custom Settings → Upload** (or External Applications) →
   preference domain `com.anthropic.claudefordesktop` → paste the plist dict /
   upload the `.mobileconfig`.
3. **Scope** to a pilot Smart Group first; verify; then widen.
4. User signs in with AWS at first launch (in-app, browser) — expected for SSO.

### Verify (pilot)

- App log: `[managedConfig] configuration at launch { type: 'profile',
  managedKeys: [ ...inferenceBedrock... ] }` (non-empty).
- **Help → Troubleshooting → Generate Diagnostic Report** → `managed-config.txt`
  / `provider-status.txt` validated.

## B. Claude Code CLI — enforced managed settings via Jamf

For fleets, deploy Claude Code's **managed settings file** instead of editing
each user's `~/.claude/settings.json`. Managed settings sit above every other
level — users, projects, and `--settings` cannot override them.

- **macOS path:** `/Library/Application Support/ClaudeCode/managed-settings.json`
- Same JSON shape as `settings.json`; the Bedrock switch goes in `env`.
- Claude Code reads only one endpoint-managed source by default. If you already
  ship a `managed-settings.json` (permissions, login method, etc.), the script
  below **merges** the Bedrock `env` keys into it and keeps everything else. It
  backs up the file first and stops without changes if the file isn't valid JSON.
  It uses the built-in `osascript` JavaScript engine, so no `jq` or Python is needed.

### B1. Policy script (Jamf Pro → Settings → Scripts; runs as root)

```bash
#!/bin/bash
# Deploys Claude Code CLI 3P (Bedrock) as an enforced managed policy.
# Merges the Bedrock env keys into an existing managed-settings.json instead of
# replacing it, so permissions and other org policy already in the file survive.
set -euo pipefail
DIR="/Library/Application Support/ClaudeCode"
F="$DIR"/managed-settings.json
mkdir -p "$DIR"
[ -f "$F" ] && cp "$F" "$F.bak"   # one rolling backup; safe to run on every check-in
/usr/bin/osascript -l JavaScript - "$F" <<'JS'   # prints the result line
ObjC.import('Foundation');
function run(argv) {
  const path = argv[0];
  const env = {
    CLAUDE_CODE_USE_BEDROCK: "1",
    AWS_REGION: "us-east-1",
    AWS_PROFILE: "claude-bedrock",
    ANTHROPIC_MODEL: "us.anthropic.claude-sonnet-5-5",
    ANTHROPIC_DEFAULT_SONNET_MODEL: "us.anthropic.claude-sonnet-5-5",
    ANTHROPIC_DEFAULT_OPUS_MODEL: "us.anthropic.claude-opus-5-5",
    ANTHROPIC_DEFAULT_HAIKU_MODEL: "us.anthropic.claude-haiku-5-5"
  };
  let settings = {};
  const fm = $.NSFileManager.defaultManager;
  if (fm.fileExistsAtPath(path)) {
    const raw = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
    if (raw.isNil()) {
      throw new Error("Existing " + path + " is not readable as UTF-8 text. Nothing was changed.");
    }
    const text = ObjC.unwrap(raw).trim();
    if (text) {
      try { settings = JSON.parse(text); }
      catch (e) { throw new Error("Existing " + path + " is not valid JSON; fix it or remove it, then re-run. Nothing was changed."); }
      if (typeof settings !== "object" || settings === null || Array.isArray(settings)) {
        throw new Error("Existing " + path + " is not a JSON object. Nothing was changed.");
      }
    }
  }
  const cur = settings.env;
  if (cur !== undefined && cur !== null && (typeof cur !== "object" || Array.isArray(cur))) {
    throw new Error("Existing " + path + " has an \"env\" that is not a JSON object. Nothing was changed.");
  }
  settings.env = Object.assign({}, cur || {}, env);
  const out = $(JSON.stringify(settings, null, 2) + "\n");
  if (!out.writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, null)) {
    throw new Error("Could not write " + path);
  }
  return "merged " + Object.keys(env).length + " env keys into " + path;
}
JS
chown root:wheel "$F"
chmod 644 "$F"
```

Attach it to a **Policy** scoped to the pilot Smart Group (trigger: Recurring
Check-in, frequency Once per computer). Replace region/model with your values.

### B2. AWS profile for the CLI (per user)
The CLI needs AWS credentials for `AWS_PROFILE`. Push an IAM Identity Center
(SSO) profile — config only, **no secrets**. Run as a policy script (Jamf passes
the logged-in username as `$3`):

```bash
#!/bin/bash
set -euo pipefail
U="$3"; H=$(dscl . -read "/Users/$U" NFSHomeDirectory | awk '{print $2}')
mkdir -p "$H/.aws"; C="$H/.aws/config"; touch "$C"
if ! grep -q "^\[profile claude-bedrock\]" "$C"; then
  cat >> "$C" <<'CFG'

[profile claude-bedrock]
sso_session = corp
sso_account_id = 123456789012
sso_role_name = BedrockInference
region = us-east-1

[sso-session corp]
sso_start_url = https://d-xxxxxxxxxx.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
CFG
fi
chown -R "$U" "$H/.aws"
```

**Human step (prescriptive prompt for users):**
> "Open Terminal and run `aws sso login --profile claude-bedrock`. Approve the
> sign-in in your browser. Run it again whenever Claude Code reports expired
> credentials (typically every 8–12 hours)."

The same `claude-bedrock` profile can back the Desktop app if you use the
"Cloud vendor profile" credential kind there.

### B3. Verify (pilot device)

- Run `claude`, then `/status`. The **Setting sources** line must show
  `Enterprise managed settings (file)`.
- A prompt succeeds and routes through Bedrock (CloudTrail shows the
  `InvokeModel*` call under the user's SSO identity).

### Revert
Remove the `env` keys from the managed file (or delete the file if it only held
them) via a Jamf policy. Users fall back to their own settings.
