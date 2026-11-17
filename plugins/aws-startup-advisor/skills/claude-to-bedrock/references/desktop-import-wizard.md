# Claude Desktop 3P — "Import from Claude" wizard

Brings a copy of a user's **claude.ai conversations and projects** into Claude
Desktop on 3P, plus any Cowork/Claude Code sessions on the machine from an
earlier install. Imported items land in the app's local session store and can
be continued against the organization's own inference provider (e.g. Bedrock).

Source: Anthropic, "Import history from claude.ai"
(https://claude.com/docs/third-party/claude-desktop/import). Verified end to end
on Claude Desktop 4.4212 in Bedrock 3P mode.

## Prerequisites

1. **Claude Desktop is running in 3P mode** (Bedrock configured; see
   `desktop-inapp-config.md`).
2. **Import is enabled** — `claudeAiImport.enabled = true`. Default is off;
   until then **Settings → Import & export** shows *"Import isn't enabled for
   this deployment. Contact your organization's administrator to turn it on."*
   and has no **Import…** button.
   - **Single machine:** **Developer → Configure Third-Party Inference… →
     Capabilities → Claude.ai data import → Enable import**, then save/apply
     (relaunch if asked). This writes the local configuration.
   - **Fleet:** set it in the managed profile (see "Managed configuration"
     below).
3. **Team/Enterprise claude.ai workspaces only:** a workspace owner turns on
   **Settings → Organization → Data and privacy → Allow members to export their
   own data** on claude.ai (off by default). Each member can export only their
   own history. Personal accounts can always export.
   - **HIPAA-ready claude.ai organizations can't turn member export on**, so
     neither Step 1 path works for their members. Tell the user up front. Step 2
     (local sessions) still works if `allowedOrganizationUuids` isn't set.
4. **Version:** Claude Desktop **4.23118.0 or later** is recommended. Earlier
   versions can show *"Update Claude to import from claude.ai"* or *"That
   doesn't look like a claude.ai export"* for a valid export, and show no error
   code on failure (see Troubleshooting).

## Run the wizard

**Settings → Import & export → Import…** opens **Import from Claude**. Three
steps; skip any you don't need.

### Step 1 — Chats (claude.ai conversations and projects)

- **Sign in to claude.ai… (recommended):** the browser opens claude.ai → sign in
  → choose the organization if there's more than one → **Authorize** (the only
  permission granted is a one-time export of the user's own data). Back in the
  app, click **Fetch export**; the wizard requests and downloads the export and
  shows a summary (e.g. "7 chats, 1 project").
- **Choose file…:** use an export the user downloaded from claude.ai
  (**Settings → Privacy → Export data**; the emailed link expires after 24 h).
- Click **Continue** (or **Skip this step**).

### Step 2 — Cowork & Code (local sessions)
Lists Cowork and Claude Code sessions found on this machine from an earlier
install (for example the 1P Claude Desktop profile), with a time-range selector
and an option to add another folder (a backup, or one copied from another
machine). Sessions are copied, not moved.

### Step 3 — Review
Summarizes what will be added → **Import**. Imported chats appear in the
sidebar; imported projects on the **Projects** page.

### Step 4 — Duplicates (only if needed)
If an imported project has the same name as an existing one: **Merge into
existing** (moves chats/sessions into the existing project) or **Keep separate**
(imported one gets a numbered name, e.g. "Northwind (1)").

## Continue an imported chat
Open it from the sidebar and send a message. The first time, the app asks for
confirmation — **Trust and resume** (claude.ai imports) or **Continue** (sessions
from an earlier 3P configuration). Replies come from the configured provider,
not claude.ai.

## What is and isn't included

- **Included:** the user's own chats and projects. Imported project custom
  instructions are shown for review and must be **accepted** before they apply.
- **Artifacts** arrive as the conversation's output files (final version only;
  very large artifact content is cut and the conversation says so).
- **Not included:** contents of project knowledge files and chat attachments —
  claude.ai never includes them in a member's own export (both the sign-in and
  file paths). Messages that referenced them remain.
- **Project folders in Chat:** to let Chat read an imported project's folder,
  open the project → **Context → + → Choose a folder** → note the dimmed
  folder's path → **Choose a different folder** → select that path → start a new
  conversation. Do this once per imported project.
- **One-time copy:** new claude.ai activity doesn't sync. Re-run the import to
  pick up newer chats; existing imports are matched and skipped (no duplicates).
- **Undo:** **Settings → Import & export → Import history → Remove** deletes the
  copied sessions and their projects.

## Managed configuration (fleet)
`claudeAiImport` is an object. In a `.mobileconfig` or the Windows registry,
write it as a JSON **string** (a macOS profile may also use a native `<dict>`):

```json
{"enabled": true, "bannerBehavior": "detect"}
```

| Field | Type | Effect |
|---|---|---|
| `enabled` | boolean, default `false` | Shows **Import…** in Settings → Import & export. |
| `allowedOrganizationUuids` | string[] | Import only by sign-in, only from these claude.ai org IDs; file import and local-session import are turned off. Empty/unreadable list = no import. |
| `bannerBehavior` | `off` / `detect` / `show` | Prompt to import on a new chat or task (`detect` = only if earlier sessions are found). |
| `exportEnabled` | boolean, default `false` | Adds **Export…** (zip of this device's chats, Cowork tasks, Code sessions). Requires `enabled`. Treat zips as sensitive. |
| `automatic3pImport` | boolean | Separate background copy of this computer's earlier **3P** sessions (also brings memory, instructions, scheduled tasks, plugins, skills — unreviewed). Not needed for 1P → 3P. On by default for orgs managed from the Enterprise Admin Console (unless turned off there); off elsewhere unless set. Runs once per computer and doesn't depend on `enabled`. |

Each import is reported to the OpenTelemetry collector with its organization ID
when `otlpDesktopLogLevel` is `info`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Import isn't enabled for this deployment" | Turn on **Capabilities → Claude.ai data import → Enable import** (or set `claudeAiImport` in the managed profile) and relaunch. |
| No **Export data** option on claude.ai (Team/Enterprise) | Workspace owner enables **Allow members to export their own data** (unless the org is HIPAA-ready; see next rows). |
| Sign-in refused | `allowedOrganizationUuids` is set and the account/org isn't listed — use a listed org. |
| Imported chat can't see project files in Chat | Re-add the project folder under **Context** (see above). |
| Want newer chats | Run the wizard again — no duplicates are created. |
| No **Export data** on claude.ai and the org is HIPAA-ready | Not fixable: member export can't be enabled. Use Step 2 for local sessions only. |
| *"The import can't start until a one-time download finishes"* or *"Downloading the program that converts your chats…"* | The app is fetching the Claude CLI binary it uses to import. Wait a few minutes and run the import again. If it keeps failing, the admin follows Anthropic's "Cowork workspace or Claude CLI fails to download" steps. |
| **Import failed** with a code such as `IMPORTER_EXIT` | Use each export `.zip` exactly as downloaded (not renamed or re-zipped; on Windows keep the full path under 260 characters). If you signed in, click **Import** again without closing the wizard (closing deletes the fetched export). Still failing: **Help → Troubleshooting → Generate Diagnostic Report → Export to file** before quitting, and send it with the code to the admin. |
| *"Update Claude to import from claude.ai"* (before 4.23118.0) | Close the wizard, send any message in a **new** conversation and wait for the reply (this downloads the current binary), then reopen the wizard. |
| Export came as several `.zip` files | In **Choose file…**, select all of them together. |
