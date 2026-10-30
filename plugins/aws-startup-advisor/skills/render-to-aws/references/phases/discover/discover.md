---
_phase: discover
_title: "Discover Render Resources"
_init: true
_input: workspace
_interactive: false
_exec:
  _agent: rw
_fragments:
  - _id: blueprint
    _trigger: { _when: "the active $MIGRATION_DIR/live-capture/manifest.json lists a transport=blueprint capture written by the main-window pre-work (Step 2)" }
    _file: phases/discover/discover-blueprint.md
  - _id: live
    _trigger: { _when: "the active $MIGRATION_DIR/live-capture/manifest.json is bound to the current consented attempt and lists at least one transport=cli or transport=rest capture written by the main-window pre-work (Step 1)" }
    _file: phases/discover/discover-live.md
  - _id: app-code
    _trigger: { _when: "the active $MIGRATION_DIR/live-capture/manifest.json lists a transport=application capture written by the main-window pre-work (Step 2)" }
    _file: phases/discover/discover-app-code.md
  - _id: billing
    _trigger: { _when: "the active $MIGRATION_DIR/live-capture/manifest.json lists a transport=billing capture written by the main-window pre-work (Step 2)" }
    _file: phases/discover/discover-billing.md
_assemble:
  _file: phases/discover/discover-assemble.md
_produces:
  - render-resource-inventory.json
  - render-resource-clusters.json
  - { file: ai-workload-profile.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
  - { file: render-ai-discovery.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
_advances_to: clarify
_re_entry_guard:
  _stale_if_completed: clarify
  _stale_artifact: preferences.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _assert: "the main-window pre-work (see '## Pre-dispatch main-window actions' in the body) recorded either a local-only attempt identity or an explicit workspace selection and read-only live-discovery consent disposition (a live decline invalidated every stale live manifest), activated $MIGRATION_DIR/live-capture/manifest.json listing every triggered producer output with a matching digest, and wrote $MIGRATION_DIR/live-capture/normalize-result.json with status ok bound to this attempt_id from the main window's own normalize-render-capture.py run; no helper execution remains for the dispatched worker"
    _on_failure: _halt_and_inform
  - _assert: "at least one Blueprint, application source, current-spend input, or fresh consented live capture is available"
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: [render-resource-inventory.json, render-resource-clusters.json]
    _on_failure: _halt_and_inform
  - _validate_json: [render-resource-inventory.json, render-resource-clusters.json]
    _on_failure: _halt_and_inform
  - _assert: "every resource has a canonical Render kind, deterministic identity, field provenance, confidence, and exactly one accounting disposition; every disagreement is retained in drift[]"
    _on_failure: _halt_and_inform
  - _assert: "no secret values, credentials, connection information, application text, or database and Key Value contents occur in produced artifacts"
    _on_failure: _halt_and_inform
  - _assert: "when ai-workload-profile.json exists it validates against references/contracts/ai-workload-profile.schema.json (shared #415 contract), render-ai-discovery.json exists and validates against references/shared/schema-render-ai-discovery.json, and neither artifact carries an execution block"
    _on_failure: _halt_and_inform
_forbids_files:
  - preferences.json
  - aws-design.json
  - estimation-infra.json
  - "terraform/**"
---

# Phase 1: Discover Render resources

## Pre-dispatch main-window actions

Run Steps 0 to 3 in this order, all BEFORE `_preconditions` is evaluated and before any fragment is dispatched. This phase is `_interactive: false` / `_exec: {_agent: rw}`: the dispatched worker (`agents/generic-phase-worker-rw.md`) has Read, Grep, Glob, Write, and Edit only and must report `WORKER_BLOCKED` if shell execution is needed, so every consent prompt, Render command, and Python helper runs here in the main window. The DSL's closed check vocabulary has no "perform an action" kind, so these steps are prose; the second `_preconditions` `_assert` only verifies that they happened. Run every helper as `uv run --project "$SKILL_BASE/scripts" --frozen python ...` with the arguments in `references/shared/script-abis.md`.

### Step 0 — initialize the run

Perform `_init` state setup per `INTERPRETER.md` § `_init: true` before any producer touches `$MIGRATION_DIR`: resolve resume-vs-fresh, set `$MIGRATION_DIR`, and on a fresh run create the directory, `.gitignore`, and `.phase-status.json` exactly as that section specifies. Cancellation terminates the phase without running Steps 1 to 3.

### Step 1 — attempt identity, live consent, and live capture

The main window first determines whether the user selected live capture. For a local-only Blueprint, application, or billing run, it does not require the Render CLI, authentication, workspace enumeration, workspace confirmation, or live consent. It mints a UUIDv4 attempt ID, computes a deterministic `local_identity` from the canonical producer paths and input digests, and writes a local manifest with `identity_scope: local`, null `workspace_id`, `consent_digest`, and `ownership_index_digest`, and no CLI/REST entries. Canonical outputs use the explicit `local:<digest>` identity and never describe it as a confirmed Render workspace. Blueprint-backed Generate still requires renewed main-window semantic validation before execution.

Only when live capture is selected does the main window check for exactly Render CLI 2.30.0, check authentication without initiating `render login`, enumerate accessible workspaces, ask the user to confirm exactly one workspace ID, and present the read-only consent gate with the exact CLI categories and GET-only API scope.

For every live consent decision or re-entry, mint a new UUIDv4 attempt ID and consent digest. Before capture, atomically replace any old active marker with an invalid disposition and remove stale manifest/index activation; a decline leaves no active live manifest but does not disable selected local producers. Write a fresh ownership index only from sanitized workspace-scoped CLI inventory, hash its exact bytes, and bind every child CLI/REST capture (`capture-render-cli.py`, `capture-render-api.py`) to that ownership-index digest and the same attempt/workspace/consent tuple. Each manifest entry records the child capture's exact RFC3339 timestamp, workspace, accepted status, page count (REST only), output path/digest, and ownership-index digest. Atomically activate the manifest only after every listed field and file reconciles with its sanitized child envelope; an earlier index generation or mismatched timestamp/status/page count is stale and must fail closed. Never initiate browser login, reuse stale captures, or treat process exit success as ownership proof.

### Step 2 — run every local producer in the main window

Run each local producer only when its input exists, and write its output under `$MIGRATION_DIR/live-capture/`:

1. Blueprint: when `**/render.yaml` exists, run `parse-render-blueprint.py` with absolute `--source`, `--workspace-root`, `--migration-dir`, and `--output "$MIGRATION_DIR/live-capture/blueprint.json"`, plus `--semantic-evidence` when a current digest-bound `render blueprints validate` result exists. Structural validation against the pinned official schema occurs inside the helper before any normalization. Accept only `BLUEPRINT_OK`; otherwise record no Blueprint entry.
2. Application: when supported application source or dependency manifests exist, run `scan-render-application.py` with absolute `--workspace-root`, `--migration-dir`, and `--output "$MIGRATION_DIR/live-capture/application.json"`. The scanner never executes source. Accept only `APP_SCAN_OK`.
3. Billing: when the user supplied a Render invoice, billing export, or monthly amount, run `parse-render-billing.py` with absolute `--source`, `--workspace-root`, `--migration-dir`, and `--output "$MIGRATION_DIR/live-capture/billing.json"`. Accept only `BILLING_OK`. If no billing source is present, record nothing; current spend is then reported as unavailable.

Append one entry per successful producer to the attempt manifest per `references/shared/schema-live-capture-manifest.json`: `transport` (`blueprint`, `application`, or `billing`), `category` (the same word as the transport), `captured_at`, `workspace_id` (the manifest's own value), `status: ok`, `page_count: null`, `ownership_index_digest` (null for every Blueprint, application, and billing entry, including entries in a live manifest; only CLI and REST entries carry the active digest), `path`, and the lowercase SHA-256 `digest` of the exact written bytes. Activate the manifest atomically only after every listed digest matches the file on disk. A producer failure writes no output and adds no entry; the main window owns the diagnostic.

### Step 3 — run the normalizer in the main window

With the manifest active, run `normalize-render-capture.py` as `normalize-render-capture.py --migration-dir "$MIGRATION_DIR" --attempt-id <attempt_id> --manifest "$MIGRATION_DIR/live-capture/manifest.json" --output-inventory "$MIGRATION_DIR/render-resource-inventory.json" --output-clusters "$MIGRATION_DIR/render-resource-clusters.json" --output-ai-profile "$MIGRATION_DIR/ai-workload-profile.json" --output-ai-discovery "$MIGRATION_DIR/render-ai-discovery.json"`. All four output paths are passed on every invocation; the normalizer writes both AI artifacts when the application capture carries AI output and removes both atomically in the same transaction when it does not, so a non-AI rerun never leaves stale AI artifacts behind.

Record the outcome atomically in `$MIGRATION_DIR/live-capture/normalize-result.json` as `{"schema_version": "1.0", "attempt_id": "<attempt_id>", "status": "ok" | "failed", "code": null | "<stable_code>", "inventory_digest": "sha256:<hex>" | null, "clusters_digest": "sha256:<hex>" | null}`: `NORMALIZE_OK` yields `status: ok` with the SHA-256 digests of the exact bytes written; `NORMALIZE_FAIL | code=<code>` yields `status: failed` with that code, null digests, and untouched artifacts, and the second `_preconditions` `_assert` then halts before dispatch.

### What the dispatched worker does

The dispatched `rw` worker never runs `uv`, Python, Render, or any shell command; it reads the manifest-listed JSON and the normalizer outputs, cross-checks them against the fragment and assembler contracts, and reports `WORKER_DONE` or `WORKER_BLOCKED`. It performs no network requests, Render commands, prompts, state writes, or handoff. Only the main window may run consented commands. The main window re-reads outputs, applies postconditions, and alone emits `HANDOFF_OK`.
