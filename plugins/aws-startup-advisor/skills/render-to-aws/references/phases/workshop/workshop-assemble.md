---
_assemble: assemble-workshop
_of_phase: workshop
_reads:
  - sheet
  - refresh
  - compare
_produces:
  - scenarios/index.json
---

# Resolve workshop

Before exit, verify the working preferences, design, and estimate byte digests equal the active scenario manifest and the raw inventory fingerprint still equals baseline. On failure keep workshop in progress and stop.

On success, mark `phases.workshop: "completed"`, retain `current_phase: "estimate"`, and leave `run_mode` absent so the decision gate fires. Preserve the active scenario, every prior scenario, and all earlier Generate outputs. Emit the sidebar handoff with `return_to=decision_gate`; never advance directly to Generate.
