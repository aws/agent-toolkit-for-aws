---
_phase: feedback
_title: "Feedback (Optional)"
_kind: sidebar
_requires_phase: discover
_trigger: { _when: "the user opts in after the post-Estimate decision resolves" }
_input: "**/.phase-status.json"
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
  - "terraform/**"
---

# Feedback sidebar

Feedback is private, optional, non-gating, and offered once. This sidebar loads only after explicit opt-in following the post-Estimate Done/Generate decision. It has no `_advances_to` and no `_gates`.

A decline is resolved by `SKILL.md`: set only `phases.feedback: "completed"`, record that the one offer was resolved in phase state, and create no feedback or trace file. Do not load this phase. An accepted offer sets only `phases.feedback: "in_progress"` before collection. A collection or persistence failure is recoverable: set only `phases.feedback: "completed"`, disclose that no feedback was saved, preserve any backbone terminal/current phase and `run_mode` byte-for-byte, and continue. There is no retry prompt and no second offer after Generate.
