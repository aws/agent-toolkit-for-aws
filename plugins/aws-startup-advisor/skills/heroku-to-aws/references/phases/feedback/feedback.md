---
_phase: feedback
_title: "Feedback (Optional)"
_kind: sidebar
_requires_phase: discover
_input: "**/.phase-status.json"
_trigger: { _when: "the user opts in to providing feedback at a feedback sidebar" }
_fragments:
  - _id: collect
    _trigger: { _always: true }
    _file: phases/feedback/feedback-collect.md
_assemble:
  _file: phases/feedback/feedback-assemble.md
_produces:
  - feedback.json
  - trace.json
_preconditions:
  - _check_phase_completed: discover
    _on_failure: _halt_and_inform
_postconditions:
  - _check_file_exists: feedback.json
    _on_failure: _warn_and_skip
  - _validate_json: feedback.json
    _on_failure: _warn_and_skip
_forbids_files:
  - README.md
  - "*.txt"
  - "terraform/**"
---

# Phase 6: Feedback (Optional)

Collects user feedback. Reuses the shared feedback infrastructure (trace builder) adapted for Heroku-to-AWS's flat resource model. (Plan-share links are GATED OFF until the landing page ships — see `feedback-collect.md` Step 3.)

**Execute ALL steps in order. Do not skip or deviate.**

---

## Sub-Files

- **feedback-collect.md** → the collection work: detect IDE/version, build the anonymized trace, present the survey link, and write `feedback.json` (share-link generation is gated off in its Step 3).
- **feedback-assemble.md** → the assembler: output gate, phase-status update, and marking the migration complete.

This is an **optional sidebar phase** (`_kind: sidebar`), not a step on the linear backbone. It is entered only when the user opts in at a feedback sidebar (its `_trigger`), and it returns control to the flow rather than advancing a `current_phase` — so it has no `_advances_to`. SKILL.md decides where the feedback sidebar is offered (see the Feedback & Sharing Sidebars section there).

---

## Prerequisites

Read `$MIGRATION_DIR/.phase-status.json`. Verify `phases.discover == "completed"`.
If not: **STOP**. Output: "Feedback requires at least the Discover phase to be completed."

---

## Step 1: Collect Feedback

Load `references/phases/feedback/feedback-collect.md` and follow it. It detects the
IDE + plugin version, builds the anonymized trace (`trace.json`), presents the survey
link, and writes `feedback.json` (share-link generation is gated off in its Step 3).

---

## Step 2: Assemble and Complete

Load `references/phases/feedback/feedback-assemble.md` (the phase's assembler) and
follow it to enforce the output gate, update `.phase-status.json`, and mark the
migration complete. It owns the final artifact-level contract for this phase.
