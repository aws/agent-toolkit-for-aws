# Claude Desktop (Cowork) — in-app "Configure third-party inference" window

Screenshot-accurate walkthrough of the exact UI (verified against Claude Desktop,
Oct 2026). This is the supported, reliable way to switch the desktop app to 3P
Bedrock for a single machine (and to Export an MDM profile for fleets).

## Open the window
Top menu bar → **Developer → Configure Third-Party Inference…**
The window title is **"Configure third-party inference"**. Top-right has:

- a **config-profile dropdown** (shows **"Default"**) — the active config set.
- an **Export ▾** button — exports the current config as a `.mobileconfig`
  (macOS) or `.reg` (Windows) for MDM. Use this to author your fleet profile.
Left nav: **Connection**, Capabilities, Connectors, Telemetry & updates, Limits,
Appearance, Plugins, Egress, Source. All inference setup is under **Connection**.

## Connection → provider
"Choose where Claude Desktop sends inference requests." Set the dropdown to
**"aws Bedrock"**.

## BEDROCK CREDENTIALS card (has a "Test connection" button)
Fill per your chosen auth method. Field-by-field (exact UI labels):

| UI field | What to enter | Maps to key |
|---|---|---|
| **Credential kind** | dropdown — choose the source; "When set, only that source is used (no fallback)." For AWS profile auth choose **"Cloud vendor profile"** (saved as `vendor-profile`). | `inferenceCredentialKind` |
| **AWS region*** (required) | e.g. `us-east-1` (region where your Claude models are enabled) | `inferenceBedrockRegion` |
| **Bedrock base URL** | optional — only for VPC endpoints or gateway proxies (host origin only) | `inferenceBedrockBaseUrl` |
| **Bedrock service tier** | leave **(on-demand)** unless using flex/priority | `inferenceBedrockServiceTier` |
| **AWS profile name** | e.g. `default` (a profile in `~/.aws` with the Bedrock policy in `aws-setup.md`) | `inferenceBedrockProfile` |
| **AWS config directory** | `~/.aws` (default; "Choose…" to change) | `inferenceBedrockAwsDir` |
| **AWS CLI path** | leave blank to use PATH, or absolute e.g. `/usr/local/bin/aws` | `inferenceBedrockAwsCliPath` |
| **Custom inference headers** | optional routing/tenant headers (org IDs, Bedrock Guardrails). **No credentials here.** | custom headers |

Notes:

- **"Cloud vendor profile"** = the named-profile method (uses your `~/.aws`
  creds). For a **bearer token** instead, choose that Credential kind and paste
  the Bedrock API key; for **in-app AWS sign-in (SSO)** choose that kind and fill
  the SSO fields.
- Click **Test connection** — it signs in if needed and sends a short request to
  a model from your Model list. Add at least one model first (this method does
  not auto-discover).

## MODELS section

- **"Use 1M wherever it's available"** — optional 1M-context toggle.
- **Model list*** (required) — "Models to show in the picker. First entry is the
  default." Click **+ Add** and enter Bedrock **inference-profile IDs**. Example
  entries seen in the field:

  ```
  us.anthropic.claude-sonnet-5-5
  us.anthropic.claude-opus-5-5
  us.anthropic.claude-haiku-5-5
  ```

  (The `global.` prefix also appears in some deployments, e.g.
  `global.anthropic.claude-sonnet-5-5`. Use the prefix that matches
  your region's inference profiles — `us.` for US regions.)
- **Default model effort** — optional (low/medium/high/xhigh/max).
- **"Always start with the default model"** — optional.
- **"Show estimated cost"** — optional.

## MODEL CATALOG (for restricted/mirror networks)

- **Model catalog metadata** toggle — fetch picker names/descriptions.
- **Model catalog URL** — point to an internal mirror of Anthropic's published
  catalog instead of downloads.claude.ai (useful for locked-down fleets).

## NETWORK PROXY (optional, enterprise networks)

- **Proxy server URL** (e.g. `http://proxy.example.com:8080`) — routes app +
  agent traffic through your HTTP proxy.
- **Proxy auto-config (PAC) URL** — wins over the proxy URL when both set.

## WORKSPACE VM NETWORK (optional)

- **Enable IPv6 in the workspace VM** — only if Cowork agent tools must reach
  IPv6-only hosts.

## CAPABILITIES → Claude.ai data import (turn on for history import)
In the left sidebar, open **Capabilities** and find **Claude.ai data import**
(key `claudeAiImport`):

- **Enable import** — required. Adds **Import…** to **Settings → Import &
  export**, which opens the **Import from Claude** wizard for claude.ai chats
  and projects (see `desktop-import-wizard.md`). Off by default; without it that
  page says "Import isn't enabled for this deployment."
- **Export** (optional) — adds **Export…** to move this device's chats and
  sessions to another device as a zip.
- **Banner** (optional) — prompt to import when starting a new chat or task
  (`detect` = only if earlier sessions are found).

Save/apply and relaunch if prompted. Also under Capabilities:
**Organization instructions** (`organizationInstructions`, ≤ 3,000 characters)
adds standing instructions to every Chat, Cowork, and Code session.

## Finish

1. Click **Test connection** — confirm success.
2. The config saves to the selected config-profile (top-right dropdown).
3. For a single machine you're done — new chats route through Bedrock; the model
   picker shows your Model list entries. No 1P email sign-in appears.
4. For a fleet: click **Export ▾** → save the `.mobileconfig` (macOS) / `.reg`
   (Windows) and deploy via Jamf/Intune (see the MDM reference files). Export is
   the fastest way to author a correct managed profile.

## If the Developer menu is missing
Enable developer settings (the profile's `developer_settings.json` has
`allowDevTools: true`), restart the app, and re-open the menu. If still absent,
install the exported `.mobileconfig` locally (double-click → approve in System
Settings → Profiles) — the app reads it as a managed config at launch.
