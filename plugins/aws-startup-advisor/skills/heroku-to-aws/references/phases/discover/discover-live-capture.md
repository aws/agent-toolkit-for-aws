# Discover Phase: Live Capture (Main Window — Interactive Pre-Work)

> Interactive CLI capture step for live discovery. **This file is NOT a fragment.**
> It runs in the MAIN window because it converses with the user and uses the shell —
> two things the dispatched `rw` worker cannot do. `discover.md` § Orientation says
> when to load it: after `_init`, before the phase's work is dispatched.
>
> Its only output is raw CLI captures under `$MIGRATION_DIR/live-capture/` plus a
> `manifest.json` index. The `live` FRAGMENT (`discover-live.md`) parses those files
> into inventory entries inside the worker. This file never writes inventory entries.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Exact-command allowlist.** Run ONLY commands that appear as rows in the Capture
   Command Table (Step 3). Read and write commands share namespaces in the Heroku CLI
   (`addons` lists; `addons:upgrade` mutates; `addons:upgrade` and `addons:downgrade`
   are the same command). No namespace-prefix reasoning: if a command is not a table
   row, do not run it.
2. **Never capture secrets.**
   - NEVER run `heroku auth:token` — it prints the API token to stdout.
   - Config vars: capture KEY NAMES ONLY, using the key filter in Step 3 row 5. NEVER
     write raw `heroku config` output (values are secrets) to disk, to chat, or into
     any artifact. If neither `jq` nor `python3` is available for filtering, SKIP
     config capture entirely and record a `skipped` entry in the manifest.
3. **Always explicit flags.** Some commands change scope based on the working
   directory (`heroku addons` implies `--app` inside an app's git repo). Always pass
   `--all` or `-a <app>` explicitly. Never use the global `--prompt` flag.
4. **No mutations, no logins.** Never run `heroku login` (browser-interactive — hand
   off to the user per Step 2). Never run any create / set / add / attach / scale /
   upgrade / destroy / rename / remove command.
5. **Capture to files, not chat.** Redirect stdout to files under
   `$MIGRATION_DIR/live-capture/`. Do not paste large outputs into the conversation.
   (`.migration/` is gitignored by `_init`, so captures cannot be committed.)

---

## Step 1: Consent Gate

Output exactly, then wait for the user's choice:

```
─── Live Heroku Discovery (read-only) ───

I can inventory your Heroku account directly using your authenticated
Heroku CLI. This runs LIST/INFO commands only:

  ✓ Captured: app names, regions, stacks, dyno types and counts,
    add-on plans and prices, domain names, pipeline stages, Private
    Space peering info, and config var KEY NAMES.
  ✗ Never captured: config var values, credentials, API tokens,
    source code, or database contents. No command that creates,
    changes, or deletes anything will run.

Output is written to .migration/<run>/live-capture/ (gitignored).

[A] Proceed with live discovery
[B] Skip — use workspace files only
```

- **[A]** → continue to Step 2.
- **[B]** → do not run any Heroku command. Return to `discover.md` and record that
  live capture was declined. If no `heroku_*` Terraform exists either, the phase's
  `_preconditions` will fail normally.

## Step 2: Preflight

1. **CLI installed:** run `heroku --version`.
   - Missing → tell the user: "The Heroku CLI isn't installed. Install it
     (https://devcenter.heroku.com/articles/heroku-cli) and tell me to continue, or
     choose to skip live discovery." Wait. If skipped → exit as in Step 1 [B].
2. **Authenticated:** run `heroku auth:whoami`.
   - Success → record the account email for the manifest.
   - Failure (not logged in, or token expired) → tell the user: "Your Heroku CLI
     isn't authenticated (or the session expired). Run `heroku login` in your
     terminal — it needs a browser, so I can't run it for you — then tell me to
     continue." Wait. If the user declines → exit as in Step 1 [B].

## Step 3: Capture

Create `$MIGRATION_DIR/live-capture/`. Then:

**3a. App list and selection guard.** Run row 1 first. If it returns more than 25
apps, list the app names and ask the user which apps to include (`all` is a valid
answer). Record the selected set as `apps_selected`. All per-app rows below run only
for selected apps.

**3b. Capture Command Table.** Run each applicable row, redirecting stdout to the
named file. `<app>`, `<pipeline>`, `<space>` iterate over the selected apps and the
account's pipelines/spaces from rows 9 and 11.

| #  | Command                                      | Output file                   | Scope                                                                                                                                                         |
| -- | -------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | `heroku apps --all --json`                   | `apps.json`                   | account                                                                                                                                                       |
| 2  | `heroku apps:info -a <app> --json`           | `app-<app>.json`              | per app                                                                                                                                                       |
| 3  | `heroku ps -a <app> --json`                  | `ps-<app>.json`               | per app                                                                                                                                                       |
| 4  | `heroku addons --all --json`                 | `addons.json`                 | account                                                                                                                                                       |
| 5  | `heroku config -a <app> --json \| jq 'keys'` | `config-keys-<app>.json`      | per app — KEYS ONLY (see fallback below)                                                                                                                      |
| 6  | `heroku domains -a <app> --json`             | `domains-<app>.json`          | per app                                                                                                                                                       |
| 7  | `heroku pg:info -a <app>`                    | `pg-<app>.out`                | apps with a heroku-postgresql add-on (from row 4)                                                                                                             |
| 8  | `heroku redis:info -a <app>`                 | `redis-<app>.out`             | apps with a heroku-redis add-on (from row 4)                                                                                                                  |
| 8b | `heroku kafka:info -a <app>`                 | `kafka-<app>.out`             | apps with a heroku-kafka add-on; needs the kafka CLI plugin — if the command is unavailable, record `skipped` (plan data from row 4 is sufficient for sizing) |
| 9  | `heroku pipelines --json`                    | `pipelines.json`              | account                                                                                                                                                       |
| 10 | `heroku pipelines:info <pipeline> --json`    | `pipeline-<pipeline>.json`    | per pipeline from row 9                                                                                                                                       |
| 11 | `heroku spaces --json`                       | `spaces.json`                 | account (empty result is normal — most startups have no spaces)                                                                                               |
| 12 | `heroku spaces:info -s <space> --json`       | `space-<space>.json`          | per space from row 11                                                                                                                                         |
| 13 | `heroku spaces:peerings -s <space> --json`   | `space-peerings-<space>.json` | per space from row 11                                                                                                                                         |

Text captures use the `.out` extension (not `.txt`) so they can never collide with
the phase's `_forbids_files: "*.txt"` scope boundary, regardless of how a host
scopes that glob.

**Row 5 fallback:** if `jq` is unavailable, use
`heroku config -a <app> --json | python3 -c "import json,sys; print(json.dumps(sorted(json.load(sys.stdin))))"`.
If neither filter runtime exists, skip row 5 for all apps and record `skipped` in the
manifest — never capture unfiltered config output.

**3c. Per-command error handling:**

| Error                                          | Behavior                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 403 / forbidden on a team app                  | Record the capture as `failed` with the reason; continue with remaining apps                        |
| Command not found (missing CLI plugin, row 8b) | Record `skipped`; continue                                                                          |
| Timeout / transient network error              | Retry once; on second failure record `failed`; continue                                             |
| 401 / token expired mid-run                    | STOP capturing. Hand off as in Step 2.2. On resume, re-run Step 3 from the top (captures overwrite) |
| Rate limited (429)                             | Unexpected at this call volume — wait 60s, retry once, then record `failed`                         |

## Step 4: Write the Manifest

Write `$MIGRATION_DIR/live-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "cli_version": "<heroku --version output>",
  "account": "<auth:whoami email>",
  "apps_selected": ["my-web-app"],
  "captures": [
    { "command": "heroku apps --all --json", "file": "apps.json", "status": "ok", "note": null },
    {
      "command": "heroku config -a my-web-app --json | jq 'keys'",
      "file": "config-keys-my-web-app.json",
      "status": "ok",
      "note": null
    }
  ]
}
```

`status` ∈ `ok | failed | skipped`. Every attempted or deliberately skipped row gets
an entry. The manifest is the fragment's index — its existence is also the `live`
fragment's `_trigger`.

## Step 5: Return to `discover.md`

Tell the user in one line how many apps were captured and whether any captures
failed or were skipped, then continue the phase per `discover.md` (the dispatched
worker will parse `live-capture/` via the `live` fragment). Do NOT parse captures
here, do NOT write inventory entries, and do NOT update `.phase-status.json`.
