---
name: claude-to-bedrock
description: "Use when a person or team wants to move the Claude apps they use, Claude Desktop (Chat, Cowork) and Claude Code, from Anthropic direct to Claude on Amazon Bedrock without losing claude.ai history, for example to pay with Activate credits. Asks first whether this is an individual, an IT admin rolling out with Jamf or Intune, or a user on an IT-managed computer, checks the machine read-only, then walks only that person's steps with copy-paste prompts. Imports claude.ai chats and projects with Claude Desktop's Import from Claude wizard and carries history into Claude Code. Triggers on: switch Claude to Bedrock, Claude Code on Bedrock, CLAUDE_CODE_USE_BEDROCK, keep my claude.ai history, Claude Desktop via Jamf or Intune. Also handles Bedrock model access when the goal is running Claude Desktop or Claude Code. Do not use for: app code that calls the Anthropic SDK, Agent SDK, OpenAI, or Gemini APIs, or model access for app code (llm-to-bedrock), or general Activate questions (knowledge-base-for-startups)."
---

# Claude to Bedrock: move Claude Desktop and Claude Code to Amazon Bedrock without losing history

Move **both** Claude surfaces to third-party inference on Amazon Bedrock while
keeping conversation history, for a single user or a whole fleet.

**Last updated:** 2026-11-16 (Claude Desktop 4.4212 and later; Anthropic and AWS
documentation as of November 2026).

Claude Desktop and Claude Code change often. When a screen, setting name, or key
doesn't match what the user sees, trust the current Anthropic docs
(https://claude.com/docs/third-party/claude-desktop/overview and
https://code.claude.com/docs/en/amazon-bedrock) over this skill and tell the
user. Tell admins once, at the start, that the MDM scripts are templates to
review and pilot on a few devices before a broad rollout.

## Definitions

- **"Load"** = Read the file and follow its instructions. Do not summarize or
  skip sections.
- **`<SKILL_BASE>`** = the "Base directory for this skill" the harness reports
  at load time. Every `references/...` path in this skill is relative to it. Run
  scripts as `python3 <SKILL_BASE>/references/process_export.py` (on Windows use
  `py` or `python` if `python3` isn't found); never assume the user's working
  directory.
- **HUMAN STEP** = something only the person can do (a browser sign-in, a click
  in Claude Desktop, an approval in Jamf or Intune). Give the exact prompt, then
  wait for them to say it's done.
- **Route A / B / C** = individual, IT admin, or managed user (Phase 0).

## Before you start: what changes for the user

- **Billing moves to AWS.** Inference is billed to the AWS account that hosts
  Bedrock. AWS Activate credits apply to third-party models on Amazon Bedrock,
  including Claude (see `knowledge-base-for-startups` for eligibility and
  balances). Mention this once if the person is a startup; don't promise a
  credit amount.
- **Some claude.ai features aren't available on Bedrock.** Features that need
  Anthropic-hosted inference don't come across; examples include Claude Design,
  Computer Use, and the Skills Marketplace in Claude Desktop, and Claude Code's
  WebSearch tool. This isn't a complete list: check Anthropic's third-party
  overview (linked above) for the current one, and say so before the switch so
  nobody is surprised.
- **History is a one-time copy.** Project knowledge files and chat attachments
  don't come across (see Phase 3A).

## Plan coverage (NOT Pro-only)

This migration is **plan-agnostic**. The 3P/Bedrock switch is driven by the
deployment mode + inference configuration (in-app window or MDM managed config),
which is independent of the underlying Anthropic plan. It applies to **Pro, Max,
Team, and Enterprise** plans:

- **Pro / Max:** single-user setup via the in-app "Configure third-party
  inference" window (Phase 2). Personal claude.ai accounts can always export
  their history for the import wizard.
- **Team / Enterprise:** same mechanism; typically rolled out by an admin via
  MDM (Phase 4). For history import, a **workspace owner must allow member data
  export** on claude.ai (Phase 3A; not possible in HIPAA-ready orgs). Cowork
  availability may depend on the owner enabling "unified Chat and Cowork".
- The **CLI (Claude Code)** 3P path is entirely plan-independent (env vars +
  AWS creds).

Do not assume or state "Pro only" anywhere.

## Core facts you MUST internalize (these prevent the common failure loops)

1. **History moves with Claude Desktop's built-in importer.** In 3P mode, the
   **Import from Claude** wizard (**Settings → Import & export → Import…**)
   copies claude.ai **chats and projects** into the app's local store as real
   conversations the user can continue against Bedrock. It is **off by
   default**: until `claudeAiImport.enabled` is `true`, the page says *"Import
   isn't enabled for this deployment."* It is a one-time copy (re-run to pick up
   newer chats; no duplicates). The **CLI has no importer** — CLI history needs
   the manual export (Phase 3B).
2. **The two surfaces are independent and configured differently:**
   - **CLI (Claude Code):** env vars in `~/.claude/settings.json`. You CAN edit
     these directly.
   - **Desktop:** reads its configuration at launch from an MDM profile /
     registry policy, or from the **local configuration** the in-app
     **Developer → Configure Third-Party Inference…** window writes
     (`~/Library/Application Support/Claude-3p/configLibrary/`). Use the window
     — it validates values. Hand-edited JSON fails silently on a wrong value.
     Signature of "no config found": app log line
     `[managedConfig] configuration at launch { type: 'none', managedKeys: [] }`
     and the app falls back to the 1P sign-in.
   - 3P mode uses its own data folder, `Claude-3p`, separate from the 1P
     `Claude` folder — the two modes coexist without interfering.
3. **Bedrock auth methods** (pick ONE; UI label → key value for
   `inferenceCredentialKind`): **Cloud vendor profile** → `vendor-profile`
   (named AWS profile, `inferenceBedrockProfile`); **in-app AWS sign-in** →
   `interactive` (`inferenceBedrockSso*`); bearer token → `static`
   (`inferenceBedrockBearerToken`); identity-provider sign-in → `external-idp`.
   Devs with working AWS creds → Cloud vendor profile. Fleets → in-app AWS
   sign-in (IAM Identity Center): per-user CloudTrail identity.
4. **Model IDs are Bedrock inference-profile IDs** (e.g.
   `us.anthropic.claude-sonnet-5-5`), not plain 1P names. Use only models the
   Bedrock lifecycle page lists as **Active**; Legacy models (e.g. Sonnet 4.5)
   are on an end-of-life clock. In the CLI, pin every tier
   (`ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL`): unpinned, the `sonnet`
   alias on Bedrock resolves to Claude Code's built-in default, which can lag
   the newest release.
5. **Always confirm the app is FULLY quit** (app + menu-bar/tray) before any
   desktop file operation, or the app overwrites the change on exit. Check and
   quit it yourself with the commands in `references/terminal-helpers.md`; ask
   the person to quit from the menu bar or tray only if it's still running.
   Never force-kill it.
6. **Back up before editing; never echo secrets; rotate any exposed key.** Never
   read or print `~/.aws/credentials`, SSO caches, or API keys. To check AWS
   access, run `aws sts get-caller-identity` (and `aws configure list` for where
   credentials come from) — don't infer the credential source from files.

## Workflow

### Phase 0 — Identify who is running this skill (ALWAYS FIRST)
Before any other step, ask:
> "Before we start — which describes you?
> **A.** I'm setting up Claude on my **own computer**, and no IT team manages
> Claude on it.
> **B.** I'm an **IT admin** rolling Claude out to other people (for example
> with Jamf or Intune).
> **C.** I'm using a **work computer** where IT has set up Claude (or is going
> to)."

Then confirm against the machine (commands in `references/roles-and-steps.md`):
if a Claude Desktop managed profile is present (macOS
`/Library/Managed Preferences/…com.anthropic.claudefordesktop.plist`; Windows
`HKLM\SOFTWARE\Policies\Claude`), the device is managed — treat Desktop as
**Route C** even if the person said A, and explain that their IT team controls
those settings (the in-app window's local configuration is ignored).

Follow only the route's steps; don't give admin steps to users or user steps
to admins (beyond the hand-out). Full who-does-what tables:
`references/roles-and-steps.md`.

For Routes A and C, also run the read-only **current-state check** in
`roles-and-steps.md` (Desktop installed? `Claude` / `Claude-3p` data folders?
local 3P config already applied, and is `claudeAiImport` on? CLI already on
Bedrock? `~/.claude/CLAUDE.md` present?) and skip any phase that's already done.

| Route | Do these phases | Then ask |
|---|---|---|
| **A — Individual** | 1 (CLI) → 2 (Desktop, including Enable import) → 3A (import wizard) → 3B (CLI history, optional) → 5 | AWS account + region? AWS profile or bearer token? Personal or Team/Enterprise claude.ai account? |
| **B — Admin** | 4 (fleet rollout: AWS + claude.ai prerequisites, author config, MDM deploy, pilot) → hand users the end-user message from `roles-and-steps.md` → 5 on a pilot device | Jamf or Intune? Fleet auth (IAM Identity Center recommended)? Region and models? Team/Enterprise claude.ai workspace to import from (restrict with `allowedOrganizationUuids`)? Also piloting on your own device (then also Route C there)? |
| **C — Managed user** | User-only steps: relaunch → Sign in with AWS → 3A (import wizard; skip "Enable import") → CLI `aws sso login` → 3B optional → 5 | Has IT announced the rollout? Personal or work claude.ai account for history? |

Route C rules: never have the user change settings in **Developer → Configure
Third-Party Inference…**, edit `~/.claude/settings.json` Bedrock keys, or touch
managed files. If something is missing (no Bedrock connection, "Import isn't
enabled", no **Export data** on claude.ai), give them the "message to your
admin" template from `roles-and-steps.md` and stop that step.

### CONFIRM — one notice, one question (before the first change)

The Phase 0 checks are read-only. Before you write any file, run any AWS call,
or generate scripts for an admin, show one notice that covers what you will
change and what it costs, then ask once and **wait**. Fill it in from what you
learned in Phase 0; keep every part:

> **Move Claude to Amazon Bedrock?**
>
> **What I'll change on this computer:** back up, then edit
> `~/.claude/settings.json` (Claude Code's Bedrock settings), and later, only
> if you ask, `~/.claude/CLAUDE.md` (a pointer to your old chat history). To
> save you steps I'll also open pages in your browser, quit and reopen Claude
> Desktop when a step needs it, and start AWS sign-ins that you approve in the
> browser. I won't read or edit AWS credential files (a sign-in refreshes
> AWS's own token cache) or change anything IT manages. Claude Desktop
> settings are changed by you, in the app, with my step-by-step prompts.
>
> **AWS:** I'll check which AWS account your credentials use, check whether
> Claude model access is already set up (read-only), and make one tiny test
> call to Claude on Bedrock (a few tokens, well under a cent). After the
> switch, your Claude usage is billed to that AWS account. AWS Activate credits
> can cover it if you have them.
>
> **Undo:** I'll tell you how to switch back at each step; the backups make it
> one command for Claude Code.
>
> **Would you like me to go ahead? (Yes/No)**

- **Yes** → continue with your route. A Yes covers the changes listed above,
  for the account identified. Ask again before anything not listed, such as
  creating IAM resources or submitting the Bedrock use case form.
- **No** → stop. Change nothing, and offer the steps as a written checklist the
  person can follow on their own.
- **Anything else, or no answer** → make no changes. Clarify only if needed.

Adjust the notice to the route: for **Route B** (admin), list the scripts and
profiles you'll generate instead of local file edits, and say that nothing is
deployed to devices until the admin uploads it to Jamf or Intune. Creating or
changing IAM or Identity Center resources is never covered by this Yes; it
always needs its own explicit yes (`references/aws-setup.md` section 2b).
For **Route C** (managed user), say you won't change any settings and only
walk the sign-in and import steps.

### Phase 1 — Switch the CLI to 3P (Route A)
See `references/cli-3p-setup.md`. Preferred: give the user the prompt for
Claude Code's built-in Bedrock wizard (`/setup-bedrock`, HUMAN STEP), which
checks model access and writes the settings for them. Otherwise, back up and
set these in `~/.claude/settings.json` `env` yourself:

```json
"CLAUDE_CODE_USE_BEDROCK": "1",
"AWS_REGION": "<region>",
"AWS_PROFILE": "<profile>",
"ANTHROPIC_MODEL": "us.anthropic.claude-sonnet-5-5",
"ANTHROPIC_DEFAULT_SONNET_MODEL": "us.anthropic.claude-sonnet-5-5",
"ANTHROPIC_DEFAULT_OPUS_MODEL": "us.anthropic.claude-opus-5-5",
"ANTHROPIC_DEFAULT_HAIKU_MODEL": "us.anthropic.claude-haiku-5-5"
```

Verify with a direct `aws bedrock-runtime invoke-model` using that profile, then
start a fresh shell. `ANTHROPIC_API_KEY` doesn't affect Bedrock routing, but
it does take priority over the user's Claude login once they're back on 1P — so
if the shell exports one (especially a revoked key), remove it when reverting.
For SSO profiles, also set `awsAuthRefresh` (`aws sso login --profile
<profile>`) so Claude Code starts the sign-in when credentials expire.
To revert to 1P, remove the Bedrock keys above.

### Phase 2 — Switch Claude Desktop to 3P (Route A; HUMAN STEP + your prep)
Your prep: check Bedrock model access read-only
(`references/terminal-helpers.md`) and, if the use case form is still needed,
open the Model catalog for the person; make AWS creds work (named profile resolves / generate a bearer token
via `aws-bedrock-token-generator` / set up IAM Identity Center). Then walk the
user through the in-app window; the field-by-field UI is in
`references/desktop-inapp-config.md`. Prescriptive prompt:
> "In Claude Desktop, top menu bar → **Developer → Configure Third-Party
> Inference…** (window titled 'Configure third-party inference'). Under
> **Connection**, set the provider dropdown to **aws Bedrock**. In the **BEDROCK
> CREDENTIALS** card: set **Credential kind** = **Cloud vendor profile**,
> **AWS region** = `<region>`, **AWS profile name** = `<profile>` (leave AWS
> config directory `~/.aws` and AWS CLI path blank unless custom). Under
> **MODELS → Model list**, click **+ Add** and enter
> `us.anthropic.claude-sonnet-5-5` (first entry = default). Click
> **Test connection**; on success the config saves. While you're in this window,
> also turn on history import — see the next step."
Auth variants: bearer token → that Credential kind + paste the key; in-app AWS
sign-in → fill the four SSO fields. If the Developer menu is missing, enable
developer settings, or install a local `.mobileconfig` (Phase 4).

### Phase 3 — Bring 1P history into 3P

#### 3A — Desktop: Import from Claude wizard (Routes A and C; RECOMMENDED, HUMAN STEP)
Native, supported, and the only way to get history in as **real
conversations**. See `references/desktop-import-wizard.md` for detail and
limits.

1. **Team/Enterprise only — workspace owner (on claude.ai):** **Settings →
   Organization → Data and privacy → Allow members to export their own data**.
   Off by default; skip for personal accounts. HIPAA-ready orgs can't enable
   it, so claude.ai history can't be imported for their members; say so early.
   (Route C user without **Export data** on claude.ai → "message to your
   admin" template.)
2. **Enable import (one time).** **Route C:** skip — the admin enables it in the
   managed profile; if **Settings → Import & export** says import isn't
   enabled, give the user the "message to your admin" template. **Route A**
   prompt:
   > "In **Developer → Configure Third-Party Inference…**, open **Capabilities**
   > in the left sidebar, find **Claude.ai data import**, and turn on **Enable
   > import**. Optionally also turn on export (to move chats to another device
   > later) and the import banner. Save and apply; relaunch if asked."
   This sets `claudeAiImport` = `{"enabled": true}` in the local configuration.
   If the option is missing (managed/MDM deployment), the admin must set it in
   the managed profile (Phase 4) — or use the fallback (3C).
3. **Run the wizard.** Prompt:
   > "Go to **Settings → Import & export → Import…**.
   > **Step 1 – Chats:** click **Sign in to claude.ai…**, sign in with the
   > account that has your history, choose your organization if asked, click
   > **Authorize**, then **Fetch export** — the wizard requests and downloads
   > your export itself. (Or click **Choose file…** and pick a downloaded export
   > zip.) Click **Continue**.
   > **Step 2 – Cowork & Code:** include any local sessions it finds from an
   > earlier install, or **Skip this step**.
   > **Step 3 – Review:** click **Import**. If a **Duplicates** step appears,
   > choose **Merge into existing** or **Keep separate** for each project."
4. **Continue a chat.** Prompt:
   > "Open an imported chat from the sidebar and send a message. Click **Trust
   > and resume** at the prompt — replies now come from Bedrock."
5. **Tell the user the limits:** project knowledge files and chat attachments
   are not exported by claude.ai for members (messages that referenced them
   remain); artifacts arrive as final-version output files; imported project
   instructions must be reviewed and accepted once; to let Chat read an imported
   project's folder, re-add it under the project's **Context** once; it's a
   one-time copy — re-run later for newer chats (no duplicates).

#### 3B — CLI: carry history into Claude Code (Routes A and C; optional)
The wizard does not feed the CLI. If the user wants their history as CLI
context, do the manual export (3M), run `<SKILL_BASE>/references/process_export.py`, then
write `~/.claude/CLAUDE.md` (back up/append, never overwrite) containing
`@/absolute/path/to/claude_export_md/COMBINED-1p-history.md`. Claude Code loads
it in every session.

#### 3C — Desktop fallback, only if import can't be enabled (Route A; Route C only with admin agreement)
If the admin won't enable `claudeAiImport`, give reference context instead: do
the manual export (3M) and run `process_export.py`, which also writes
`GLOBAL-INSTRUCTIONS.txt` (a pointer to the full history + topic list). Prompt:
> "In Claude Desktop, open **Settings → General → Instructions for Claude**,
> paste the text below at the end, and save. Then start a NEW chat outside any
> project to test. [contents of GLOBAL-INSTRUCTIONS.txt]"
Confirm the text actually saved: it is stored on device in
`Claude-3p/local-agent-mode-sessions/<acct>/<org>/cowork_account_settings.json`
(under `__account_profile.conversation_preferences`); if that file has no text,
the paste didn't save (common causes: pasted into claude.ai in the browser, or
into a Project's instructions). Keep it short — the text is added to every
session's system prompt. Optionally also create a **Project → From an existing
folder → `~/claude_export_md`** for deep history. If Chat can't read the files,
the user must grant folder access.

#### 3M — Manual claude.ai export (used by 3B and 3C; HUMAN STEP)
Multi-stage and browser-session-bound: you cannot download any of it yourself
(non-browser requests get a Cloudflare 403 page saved under a `.zip` name).

1. **Request:** claude.ai → Settings → Privacy → **Export data** → **Export**.
2. **Email:** Anthropic emails a download link (minutes to hours; expires 24h).
3. **Manifest:** the link downloads a small JSON manifest
   (`manifest-<org-id>-…-<date>.json`) — an index, not the data.
4. **Data files:** the manifest's `data_files[]` lists one `export_url` per file
   (`category`, `part`, `filename`), e.g. `conversations-000.zip`,
   `projects-000.zip`, `light_metadata-000.zip`; large accounts have several
   parts per category. Each must be opened individually in the signed-in
   browser and may stop working after one use.

Prompts:
> "(1) In your browser go to **claude.ai → Settings → Privacy → Export data**
> and click **Export**. (2) Click the link in Anthropic's email — it saves a
> small **JSON manifest** to Downloads. Tell me when it's there."

Read the manifest (local file) and list every entry, then:
> "Open each link below in the browser where you're signed in to claude.ai.
> Required: every `conversations-*.zip`. Optional: `projects-*`,
> `light_metadata-*`. Let each download finish before the next.
> [export_url + filename list]"

If the default browser is the signed-in one, open each link for the person,
one at a time, with the commands in `references/terminal-helpers.md`. Never
fetch with curl/wget. Verify each zip starts with `PK` (a 403 page starts with
`<!DOCTYPE html>`), then run `<SKILL_BASE>/references/process_export.py` — it reads every
part, de-duplicates, and writes per-conversation `.md`,
`COMBINED-1p-history.md`, and `GLOBAL-INSTRUCTIONS.txt` to `~/claude_export_md/`.

### Phase 4 — Fleet rollout via MDM (Route B — admin; both surfaces)
**Desktop:** push a managed configuration so every device enters 3P at launch.
Recommended fleet auth: **in-app AWS sign-in (IAM Identity Center)**.

- AWS one-time setup: `references/aws-setup.md` (section 2b can create the
  Identity Center permission set from the CLI, after a separate yes).
- macOS/Jamf: `references/mdm-macos-mobileconfig.md` (preference domain
  `com.anthropic.claudefordesktop`).
- Windows/Intune: `references/mdm-windows-intune.md` (`REG_SZ` values directly
  under `HKLM\SOFTWARE\Policies\Claude`).
- Fastest authoring: configure one device in the in-app window, then
  **Export ▾** → `.mobileconfig` / `.reg`.
- **Value encoding:** in a `.mobileconfig` or the registry, every value is a
  **string** — booleans as `"true"`, arrays/objects as JSON strings (a macOS
  profile may also use native `<array>`/`<dict>`). Linux:
  `/etc/claude-desktop/managed-settings.json` with real JSON.
- **History import for the fleet:** add `claudeAiImport` =
  `{"enabled":true}`. Optional fields: `allowedOrganizationUuids` (restricts
  import to sign-in from listed claude.ai orgs; disables file import),
  `bannerBehavior` (`detect` / `show` — prompt users to import),
  `exportEnabled`. Team/Enterprise owners must also allow member data export (not possible in HIPAA-ready orgs).
- **Org-wide standing context (optional):** `organizationInstructions` — a
  string (≤ 3,000 characters; longer is rejected, not truncated) appended to the
  system prompt in Chat, Cowork, and Code for every user.

**CLI:** deploy an **enforced managed settings file** with the Bedrock `env`
block — not per-user `~/.claude/settings.json` (users could override that).

- Paths: macOS `/Library/Application Support/ClaudeCode/managed-settings.json`;
  Windows `C:\Program Files\ClaudeCode\managed-settings.json`; Linux/WSL
  `/etc/claude-code/managed-settings.json`.
- Jamf: policy script (root) writes the file; second script appends an SSO
  profile to each user's `~/.aws/config` (config only, no secrets).
- Intune: platform script as SYSTEM writes the file (Remediation for drift);
  user-context script adds the SSO profile.
- If an org already ships a `managed-settings.json`, the reference scripts merge
  the `env` block into it (Claude Code uses one endpoint-managed source by
  default).
- Optional: add `"awsAuthRefresh": "aws sso login --profile claude-bedrock"` to
  the managed file so Claude Code starts the sign-in when credentials expire.
- Human step: each user runs `aws sso login --profile claude-bedrock` when
  credentials expire (or approves the browser sign-in `awsAuthRefresh` starts).
  Give them that exact prompt.
- Verify on a pilot: `/status` → **Setting sources** shows
  `Enterprise managed settings (file)`.

Pilot on a smart group / pilot device group FIRST; verify with **Help →
Troubleshooting → Generate Diagnostic Report** (`managed-config.txt`,
`provider-status.txt`) and the app log `[managedConfig] ... managedKeys: [...]`
non-empty.

**Hand-off to users (Route B finish):** give the admin the "admin → users"
message from `references/roles-and-steps.md`, filled in with their profile name
(`claude-bedrock`) and support channel. Users then follow Route C. Don't walk the
admin through end-user steps unless they're piloting on their own device.

### Phase 5 — Verify end to end (all routes; both surfaces)

- Desktop: a new chat uses a Bedrock model ID; no 1P email prompt.
- Desktop history: imported chats appear in the sidebar and imported projects on
  the Projects page; sending a message in one (after **Trust and resume**) gets a
  Bedrock reply. **Settings → Import & export → Import history** lists the run.
- CLI: fresh `claude` session routes via Bedrock (valid `AWS_PROFILE` creds;
  CloudTrail shows invocation); if 3B was done, it can describe past topics.

## Human-intervention checklist (always give a prescriptive prompt)

Before handing a step over, do the terminal part yourself: open the page or
file, check status read-only, or start `aws sso login`
(`references/terminal-helpers.md`). The person should only have to sign in,
click, or approve.
**Admin (Route B):**

- AWS Console / IAM Identity Center setup — `references/aws-setup.md`.
- Team/Enterprise owner: **Allow members to export their own data** on claude.ai
  (not possible in HIPAA-ready orgs; tell those users only local sessions can be imported).
- Author the config in the in-app window on a test device and **Export ▾**.
- Jamf/Intune upload + scoping + pilot — MDM reference files.
- Send users the "admin → users" message — `references/roles-and-steps.md`.

**Individual (Route A):**

- Desktop **Developer → Configure Third-Party Inference…**, including
  **Capabilities → Claude.ai data import → Enable import** — Phase 2 / 3A.
- Fallback only (import can't be enabled): paste `GLOBAL-INSTRUCTIONS.txt` into
  **Settings → General → Instructions for Claude** — Phase 3C.
- Everything in the managed-user list below.

**Managed user (Route C) — and Route A:**

- Relaunch the app; **Sign in with AWS** when prompted.
- Run the **Import from Claude** wizard (sign-in + **Authorize**) and **Trust and
  resume** on imported chats — Phase 3A.
- CLI: `aws sso login --profile <profile>` when credentials expire (or
  approve the browser sign-in that `awsAuthRefresh` starts).
- Optional: manual claude.ai export (browser-bound) for CLI history — 3M / 3B.
- Optional: personal **Instructions for Claude** (Settings → General).
- Route C, when something's missing: send the "message to your admin" template.

## Reference files

- `references/terminal-helpers.md` — open pages and files for the person, quit
  Claude Desktop safely, check Bedrock model access, start an SSO sign-in.
- `references/roles-and-steps.md` — routes, machine checks, who-does-what
  tables (Jamf + Intune), admin↔user message templates.
- `references/desktop-import-wizard.md` — Import from Claude wizard: enable,
  steps, limits, troubleshooting.
- `references/process_export.py` — manual export → Markdown + combined doc +
  GLOBAL-INSTRUCTIONS.txt.
- `references/cli-3p-setup.md` — exact CLI changes + verify + revert.
- `references/desktop-inapp-config.md` — the in-app "Configure third-party
  inference" window, field by field.
- `references/aws-setup.md` — Bedrock model access + IAM Identity Center.
- `references/mdm-macos-mobileconfig.md` — Jamf `.mobileconfig` (desktop) + CLI script.
- `references/mdm-windows-intune.md` — Intune registry (desktop) + CLI script.
- `references/inference-bedrock-keys.md` — managed-configuration key reference.
