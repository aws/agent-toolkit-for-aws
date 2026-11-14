---
_phase: workshop
_title: "What-If Workshop (Optional)"
_kind: sidebar
_requires_phase: estimate
_gates: generate
_trigger: { _when: "the user opts in after Estimate or explicitly requests what-if repricing" }
_input:
  - render-resource-inventory.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
_knowledge:
  - { file: references/shared/schema-workshop-scenarios.md }
_fragments:
  - _id: sheet
    _trigger: { _always: true }
    _file: phases/workshop/workshop-sheet.md
  - _id: refresh
    _trigger: { _when: "the user chose Apply and reprice" }
    _file: phases/workshop/workshop-refresh.md
  - _id: compare
    _trigger: { _when: "the user chose Compare or a refresh completed" }
    _file: phases/workshop/workshop-compare.md
_assemble:
  _file: phases/workshop/workshop-assemble.md
_produces:
  - scenarios/index.json
_interactive: true
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_file_exists: [render-resource-inventory.json, preferences.json, aws-design.json, estimation-infra.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: scenarios/index.json
    _on_failure: _warn_and_skip
---

# What-if workshop sidebar

Follow `references/vendored/workshop/workshop-invariants.md` and the Render scenario schema. Workshop never becomes `current_phase` and has no `_advances_to`.

On every entry, before any branch, detect stale Generate or resolved decision state. After explicit confirmation, reset downstream phase status to pending, set `current_phase: estimate`, remove `run_mode`, and leave every generated file untouched. Declining confirmation stops without changes. Then set only `phases.workshop: in_progress`.

The raw bytes of `render-resource-inventory.json` are frozen. Baseline capture stores their lowercase SHA-256. Every refresh recomputes it and aborts on mismatch. The store holds at most five scenarios; eviction requires naming the victim and can never remove baseline without explicit reset consent. Exit returns to the post-Estimate decision gate.
