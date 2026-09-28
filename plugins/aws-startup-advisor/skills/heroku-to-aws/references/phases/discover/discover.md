---
_phase: discover
_title: "Discover Heroku Resources"
_init: true
_input: workspace
_fragments:
  - _id: terraform
    _trigger: { _always: true }
    _file: phases/discover/discover-terraform.md
  - _id: live
    _trigger: { _when: "$MIGRATION_DIR/live-capture/manifest.json exists (the live-capture pre-work ran — see Orientation § Live capture)" }
    _file: phases/discover/discover-live.md
  - _id: billing
    _trigger: { _glob: "**/*{billing,invoice}*.{csv,json}" }
    _file: phases/discover/discover-billing.md
_assemble:
  _file: phases/discover/discover-assemble.md
_produces:
  - heroku-resource-inventory.json
_advances_to: clarify
_interactive: false
_exec:
  _agent: rw
_re_entry_guard:
  _stale_if_completed: clarify
  _stale_artifact: preferences.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _assert: "at least one Heroku source is available: a .tf file containing a heroku_* resource exists in the workspace, OR $MIGRATION_DIR/live-capture/manifest.json exists. Evaluating this check is where live capture is offered: if no heroku_* Terraform is found, load references/phases/discover/discover-live-capture.md in the MAIN window and run it (consent-gated); fail this check only after the user declines live capture or capture cannot run"
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: heroku-resource-inventory.json
    _on_failure: _halt_and_inform
  - _validate_json: heroku-resource-inventory.json
    _on_failure: _halt_and_inform
  - _assert: "heroku-resource-inventory.json has at least one resource entry, and metadata has discovery_timestamp and total_apps_discovered set"
    _on_failure: _halt_and_inform
  - _assert: "every resource in resources[] has resource_id, resource_type, heroku_app, and config fields"
    _on_failure: _halt_and_inform
  - _assert: "no forbidden clustering fields are present (cluster_id, creation_order_depth, edges, dependencies, must_migrate_together)"
    _on_failure: _halt_and_inform
  - _assert: "metadata.discovery_sources reflects which sub-discoveries actually produced data; if heroku_* Terraform files were FOUND in the workspace (not merely that the terraform fragment ran — it always runs and may exit empty), resources[] contains at least one Terraform-sourced resource"
    _on_failure: _halt_and_inform
  - _assert: "if the live fragment ran ($MIGRATION_DIR/live-capture/manifest.json exists), resources[] contains at least one live-sourced resource, a live_metadata section is present, and 'live' appears in metadata.discovery_sources"
    _on_failure: _halt_and_inform
  - _assert: "no config var VALUES appear anywhere in the inventory — config entries carry key names only"
    _on_failure: _halt_and_inform
  - _assert: "if a billing/invoice file was present in the workspace, heroku-resource-inventory.json has a billing_profile section"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - discovery-summary.md
  - "*.txt"
  - "terraform/**"
---

# Phase 1: Discover Heroku Resources

## Orientation

Inventory what exists on Heroku into a single flat `heroku-resource-inventory.json`
in `$MIGRATION_DIR/`. This phase is composed of FRAGMENTS (independent discoverers)
plus one ASSEMBLER, declared in the frontmatter `_fragments`/`_assemble` — the
interpreter runs each fragment whose `_trigger` is true (loading its `_file` only
then), then the assembler. Read each unit file for its own contract; this phase
owns only lifecycle + the cross-cutting `_postconditions`.

Two facts the contract can't express: Procfile/app.json parsing is integrated into
the terraform fragment (there is no standalone Procfile fragment) — when present
alongside Terraform, they supplement resource data with commands, buildpacks, and
declared add-ons. Billing data, when present, is embedded in
`heroku-resource-inventory.json` (not a separate file); all user communication
is via output messages only (no report/log files).

### Live capture (main-window pre-work)

Live discovery reads the user's Heroku account through their authenticated Heroku
CLI — read-only, consent-gated, key-names-only for config vars. It is split in two
because the dispatched `rw` worker has no shell and cannot converse with the user:

1. **Capture** (`discover-live-capture.md`) — runs in the MAIN window, after
   `_init` and before the phase's work is dispatched. It asks for consent, preflights
   the CLI (`heroku auth:whoami`), runs an exact-command allowlist of list/info
   commands, and writes raw output to `$MIGRATION_DIR/live-capture/` plus a
   `manifest.json` index. It writes NO inventory entries.
2. **Parse** (`discover-live.md`, the `live` fragment) — runs in the worker with the
   other fragments. Its `_trigger` is the manifest's existence; it maps captures to
   inventory entries with `source: "live"`.

**Explicit ordering (cold start):** run `_init` state setup FIRST (create
`$MIGRATION_DIR`, write `.phase-status.json`), THEN evaluate the source
`_precondition` — offering and running capture as part of that evaluation — then
dispatch the phase's work. Capture writes into `$MIGRATION_DIR/live-capture/`, so
it cannot run before `_init` has created the run directory.

**When to offer capture:** while evaluating the source `_precondition`, scan the
workspace first (free). If NO `heroku_*` Terraform is found, offer live capture as
the primary source — load `discover-live-capture.md` — instead of failing the check.
If Terraform IS found, still offer capture once as an optional live cross-check
("catch resources managed outside Terraform"); a decline is fine and is not
re-asked. Never run capture without explicit consent.

**Source-of-truth rule (for the assembler):** when both Terraform and live entries
exist, live is authoritative for current state (config values, plans, quantities);
Terraform supplements structure and provenance. Disagreements are surfaced as drift,
never silently resolved — see `discover-assemble.md` § Merge & Drift Rules.

---

## Handoff

After the interpreter emits `HANDOFF_OK | phase=discover`, build the user-facing
completion message from the inventory contents:

- "Discovered X total resources across Y apps."
- If billing data available: "Parsed billing data ($Z/month)."
- If live discovery ran: "Live discovery captured N apps via the Heroku CLI."
- If both live and Terraform ran: "Drift check: N resources live but not in Terraform, M in Terraform but not live, K config conflicts (live values used)."
- If Terraform secondary: "Supplemented with Terraform-sourced resources (N conflicts resolved)."
- If Pipeline detected: "Detected N pipeline(s) (detect-only)."
- If Cedar/Fir mixed: "Generation detection: N Cedar, M Fir, P unknown."

Format: "Discover phase complete. [artifact summaries] Next required step: Phase 2 — Clarify. Load `references/phases/clarify/clarify.md` now. Do not load Design, Estimate, or Generate until Clarify completes and `.phase-status.json` marks `phases.clarify` as `completed`."

---

## Error Handling

Non-fatal discovery errors and their handling (fatal source/gate failures are handled by `_preconditions`/`_postconditions` + `INTERPRETER.md` § `_on_error`):

| Error Category                                     | Behavior                                                                                       |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Terraform parse error (malformed HCL)              | Log warning, skip malformed blocks, continue                                                   |
| Procfile/app.json parse error                      | Record warning per-app, continue                                                               |
| Generation detection unresolvable (no stack attr)  | Set `heroku_generation` to `unknown`, continue                                                 |
| Pipeline detection from Terraform incomplete       | Record with available data, continue                                                           |
| Live capture partially failed (some apps 403 etc.) | Parse the `ok` captures, mark failed apps `discovery_failed`, confidence `reduced`, continue   |
| Live capture declined or CLI unavailable           | Skip the `live` fragment (no manifest → trigger never fires), continue with file-based sources |

---

## Scope Boundary

**This phase covers Heroku Discovery ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: Inventory what exists on Heroku. Nothing else.**
