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
_interactive: true
_preconditions:
  - _check_phase_completed: discover
    _on_failure: _halt_and_inform
_postconditions:
  - _check_file_exists: feedback.json
    _on_failure: _warn_and_skip
  - _validate_json: feedback.json
    _on_failure: _warn_and_skip
  - _assert: "trace.json contains no resource names, ARM resource IDs, subscription IDs, tenant IDs, file paths, or exact dollar figures"
    _on_failure: _warn_and_skip
---

# Sidebar: Feedback (Optional)

## Orientation

Five optional questions plus an anonymized trace. This is a **sidebar**: off-backbone,
entered only by its `_trigger`, and it returns control rather than advancing. It
declares no `_gates` — feedback blocks nothing.

Resolving this sidebar means it was offered and dealt with. A decline still marks
`phases.feedback` as `"completed"`, so the migration can terminate cleanly. Whether
the user actually participated is a separate signal: `feedback.json` exists only if
they engaged.

Where the sidebar is offered is orchestration prose — see SKILL.md § Sidebar
Placement.

> **Plan-share links are GATED OFF.** The share landing page is not yet live (404).
> Do not offer, generate, or present a share link here.

## Status — skeleton (build step 1)

Wiring only: one fragment and an assembler. The question set and the trace builder
land alongside the fixtures work.

## Step: Run the sidebar

1. Run `feedback-collect.md`.
2. Run `feedback-assemble.md`.
3. Return control. Do not advance `current_phase`.
