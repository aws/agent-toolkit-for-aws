---
_phase: clarify
_title: "Clarify Requirements"
_requires_phase: discover
_input:
  - heroku-resource-inventory.json
_fragments:
  - _id: interview
    _trigger: { _always: true }
    _file: phases/clarify/clarify-interview.md
_assemble:
  _file: phases/clarify/clarify-assemble.md
_produces:
  - preferences.json
_advances_to: design
_re_entry_guard:
  _stale_if_completed: design
  _stale_artifact: aws-design.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: discover
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: heroku-resource-inventory.json
    _on_failure: _unrecoverable
  - _validate_json: heroku-resource-inventory.json
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: preferences.json
    _on_failure: _halt_and_inform
  - _validate_json: preferences.json
    _on_failure: _halt_and_inform
  - _assert: "all Validation Checklist items in clarify-assemble.md pass"
    _on_failure: _halt_and_inform
  - _assert: "if heroku-resource-inventory.json contains Postgres add-ons, then data.database_ha and global.migration_approach are both set (non-null)"
    _on_failure: _halt_and_inform
  - _assert: "if global.migration_approach is interim_cutover_data_first, then global.target_exit_date is non-null and a valid future date"
    _on_failure: _halt_and_inform
  - _assert: "if Fir-generation apps were detected, then global.fir_intent is set (non-null)"
    _on_failure: _halt_and_inform
  - _assert: "if Private Space peering was detected and subnet IDs were required, then network.subnet_ids is a non-empty array"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - aws-design.json
  - "terraform/**"
---

# Phase 2: Clarify Requirements

**Phase 2 of 6** — Ask adaptive questions before design begins, then interpret answers into ready-to-apply design constraints.

> **HARD GATE — Clarify before Design:** Do not load `references/phases/design/design.md` (or any later phase) until this phase finishes **and** `$MIGRATION_DIR/.phase-status.json` records `phases.clarify` as `"completed"`. Writing `preferences.json` without updating phase status is a protocol violation. If the user asks to skip questions, use documented defaults and still complete this phase (including phase status).

The output — `preferences.json` — is consumed directly by Design and Estimate without any further interpretation.

Questions are organized into **three batches** (≤7 per batch) presented sequentially. A standalone **fast-path** mode exists for simple stacks (< 5 apps, no Private Spaces, no Kafka).

---

## Step 1: Run the Interview

Load `references/phases/clarify/clarify-interview.md` and follow it. It handles the
prior-run check, determines fast-path eligibility, selects the active question set,
and presents the questions in progressive batches — interpreting each answer. It
contains the full Question Catalog and Defaults Table.

---

## Step 2: Assemble and Validate

Load `references/phases/clarify/clarify-assemble.md` (the phase's assembler) and
follow it to assemble the final `preferences.json`, run the validation checklist +
completion handoff gate, and update `.phase-status.json`. It owns the artifact-level
contract for this phase.

---

## Scope Boundary

**This phase covers requirements gathering ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Detailed AWS architecture or service configurations
- Code migration examples or SDK snippets
- Detailed cost calculations
- Migration timelines or execution plans
- Terraform generation
- Dyno-to-Fargate sizing decisions
- Database instance class selection

**Your ONLY job: Understand what the user needs. Nothing else.**
