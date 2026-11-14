---
_phase: generate
_title: "Generate Migration Artifacts"
_requires_phase: estimate
_input:
  - render-resource-inventory.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
_interactive: false
_exec:
  _agent: rw
_fragments:
  - _id: artifacts-infra
    _trigger: { _always: true }
    _file: phases/generate/generate-artifacts-infra.md
  - _id: artifacts-docs
    _trigger: { _always: true }
    _file: phases/generate/generate-artifacts-docs.md
  - _id: artifacts-report
    _trigger: { _always: true }
    _file: phases/generate/generate-artifacts-report.md
_assemble:
  _file: phases/generate/generate-assemble.md
_produces:
  - migration-report.html
  - generation-warnings.json
  - validation-report.json
  - README.md
  - terraform/
  - scripts/
  - MIGRATION_GUIDE.md
_advances_to: complete
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_phase_completed: workshop
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [render-resource-inventory.json, preferences.json, aws-design.json, estimation-infra.json]
    _on_failure: _unrecoverable
  - _assert: "run_mode is decide_and_execute; absent or decide is not execution consent"
    _on_failure: _halt_and_inform
  - _assert: "if inventory discovery_sources contains render_blueprint, Blueprint semantic validation evidence is valid, consented, and bound to the current source SHA-256; otherwise the Blueprint semantic gate is not applicable"
    _on_failure: _halt_and_inform
_postconditions:
  - _check_file_exists: [migration-report.html, generation-warnings.json, validation-report.json, README.md, MIGRATION_GUIDE.md]
    _on_failure: _halt_and_inform
  - _validate_json: [generation-warnings.json, validation-report.json]
    _on_failure: _halt_and_inform
  - _assert: "validation-report.json is passed or passed_degraded_offline under the strict Render validation contract; every independent local check passed and policy_status is POLICY_OK"
    _on_failure: _halt_and_inform
  - _assert: "deferred_shared_ai_engine and conditionally unsupported Workflow generation are warnings, never fabricated artifacts"
    _on_failure: _halt_and_inform
_forbids_files:
  - render-resource-inventory.json
  - render-resource-clusters.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
---

# Phase 5: Generate migration artifacts

Generate is opt-in. The main window re-reads `.phase-status.json` immediately before dispatch and requires `run_mode: "decide_and_execute"`; neither an absent value nor `decide` is consent.

## Main-window semantic preflight

Before the worker starts, the main window inspects the validated inventory's `discovery_sources`. If `render_blueprint` is absent, no Blueprint source or semantic evidence exists and this preflight is not applicable; continue Generate using the live/application/billing-backed inventory. If `render_blueprint` is present, the main window hashes the current regular, non-symlinked Blueprint bytes with SHA-256 and re-reads the consented semantic-validation evidence. Reuse is allowed only when all of these match the active discovery attempt: workspace ID, attempt ID, consent digest, Blueprint absolute source identity, source SHA-256, successful Render CLI validation status, and capture-manifest digest. If any field is absent, stale, or different, invalidate the evidence, disclose the exact read-only command, obtain renewed consent, and rerun the allowlisted `render blueprints validate` capture in the main window. A declined or failed revalidation halts Generate. The dispatched worker never invokes Render, validates the Blueprint, prompts, writes state, or emits `HANDOFF_OK`.

## Worker sequence

1. Re-read and validate inventory, preferences, design, and estimate inputs.
2. Emit Terraform for every supported selected target by following `generate-artifacts-infra.md`.
3. Emit cutover, migration, verification, and rollback documentation and scripts by following `generate-artifacts-docs.md`.
4. Emit the report and warnings by following `generate-artifacts-report.md`.
5. Run the file-only accounting and scan rules in `generate-assemble.md`. The worker does not create `validation-report.json`.

## Main-window validation and completion

After the worker returns, the main window performs every validation stage in `generate-assemble.md`, writes the single canonical `validation-report.json`, and evaluates this phase's postconditions. It may rename a failed report to `migration-report.incomplete.html`, but it never patches generated content to force a pass. Only after every gate passes does it write phase state, emit `HANDOFF_OK`, and advance to `complete`.

There is no skip-and-complete path. `passed_degraded_offline` is limited to an identified provider-registry failure during `terraform init` (and the consequential inability to run provider-backed `terraform validate`); formatting, local syntax where available, policy, secret, JSON Schema, report, and accounting checks still must pass.
