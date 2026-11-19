# Claude Desktop 3P managed-configuration keys (Bedrock + history import)

Source of truth: https://claude.com/docs/third-party/claude-desktop/configuration

## Where the app reads configuration

| Platform | Managed (MDM) | Local (in-app window writes this) |
|---|---|---|
| macOS | `/Library/Managed Preferences/com.anthropic.claudefordesktop.plist` (machine) or `/Library/Managed Preferences/<user>/…` (per user); profile preference domain `com.anthropic.claudefordesktop` | `~/Library/Application Support/Claude-3p/configLibrary/` |
| Windows | `HKLM\SOFTWARE\Policies\Claude` (machine, recommended) or `HKCU\SOFTWARE\Policies\Claude` | `%LOCALAPPDATA%\Claude-3p\configLibrary\` |
| Linux | `/etc/claude-desktop/managed-settings.json` (root-owned, JSON values) | `~/.config/Claude-3p/configLibrary/` |

The local `configLibrary/` is ignored when a managed profile is present.

**Value encoding (plist and registry):** write every value as a **string** —
booleans as `"true"`/`"false"`, integers as decimal strings, arrays and objects
as a single JSON string (e.g. `["us.anthropic.claude-sonnet-5-5"]`). A macOS
profile may instead use native `<array>`/`<dict>`. On Windows use `REG_SZ`
directly under the policy key (never in a subkey); avoid `REG_EXPAND_SZ`.

## Connection — Bedrock

| Key | Type | Purpose |
|---|---|---|
| `inferenceProvider` | enum | `bedrock`. |
| `inferenceBedrockRegion` | string | Region for the Bedrock runtime endpoint. |
| `inferenceBedrockBaseUrl` | string | Optional — VPC endpoint or gateway proxy (origin only). |
| `inferenceBedrockServiceTier` | enum | `flex` / `priority`; unset = on-demand. |
| `inferenceModels` | object[] (JSON) | Model list; first = default. Each entry is a plain inference-profile ID string, or an object `{"name": "<id>", "labelOverride": "<display name>"}` (also `supports1m`, `anthropicFamilyTier`, …), e.g. `["us.anthropic.claude-sonnet-5-5"]`. Required unless bearer token/credential helper (which auto-discover). |
| `inferenceCredentialKind` | enum | Forces one credential source (no fallback). One of: `static`, `helper-script`, `interactive`, `vendor-profile`, `workforce`, `external-idp`. |

Credential sources (set exactly one, and match `inferenceCredentialKind`):

| UI "Credential kind" | `inferenceCredentialKind` | Keys |
|---|---|---|
| Cloud vendor profile (AWS named profile) | `vendor-profile` | `inferenceBedrockProfile`, optional `inferenceBedrockAwsDir` (default `~/.aws`), `inferenceBedrockAwsCliPath` |
| In-app AWS sign-in (IAM Identity Center) | `interactive` | all four: `inferenceBedrockSsoStartUrl`, `inferenceBedrockSsoRegion`, `inferenceBedrockSsoAccountId`, `inferenceBedrockSsoRoleName` |
| Bearer token (Bedrock API key) | `static` | `inferenceBedrockBearerToken` |
| Credential helper | `helper-script` | `inferenceCredentialHelper` (+ args/TTL keys) |
| Identity-provider sign-in (proxy in front of Bedrock) | `external-idp` | `inferenceIdpOidc`, `inferenceBedrockBaseUrl` |

When `inferenceCredentialKind` is unset and several sources are present, the
app uses the first of: identity-provider sign-in → in-app AWS sign-in → named
profile → credential helper → bearer token.

## Capabilities — history and standing context

| Key | Type | Purpose |
|---|---|---|
| `claudeAiImport` | object (JSON) | **Claude.ai data import** — `{"enabled": true}` shows **Settings → Import & export → Import…** (the Import from Claude wizard). Optional fields: `allowedOrganizationUuids` (sign-in import from listed orgs only), `bannerBehavior` (`off`/`detect`/`show`), `exportEnabled`, `automatic3pImport`. Default: off. See `desktop-import-wizard.md`. |
| `organizationInstructions` | string | Appended to the system prompt in Chat, Cowork, and Code for every user; takes priority over personal preferences. **Max 3,000 characters** — longer values are rejected with a configuration error, not truncated. |

## CLI equivalents
Env in `~/.claude/settings.json` (single user) or the enforced Claude Code
managed settings file (fleet): `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION`,
`AWS_PROFILE` (or `AWS_BEARER_TOKEN_BEDROCK`), `ANTHROPIC_MODEL`.

## Verify a deployed config
**Help → Troubleshooting → Generate Diagnostic Report** → `managed-config.txt`
(keys present) and `provider-status.txt` (validated). App log line
`[managedConfig] configuration at launch { type: ..., managedKeys: [...] }`:
`type: 'none'` means no configuration was found; `'local'` means the in-app
window's configuration is in use.
