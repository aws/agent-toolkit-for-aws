---
_assemble: assemble-feedback
_of_phase: feedback
_reads:
  - collect
_produces:
  - feedback.json
  - trace.json
---

# Resolve feedback

Snapshot `current_phase`, `run_mode` presence/value, all backbone phase statuses, and generated-file digests before reading feedback outputs.

On success, require `feedback.json`; require `trace.json` only when `trace_included` is true. Re-run the closed-enum and trace allowlist/privacy checks from the collector. Then update `.phase-status.json` by read-merge-write: set only `phases.feedback: "completed"` and `last_updated`. Re-read state and prove the snapshot fields are unchanged.

On collection, validation, or write failure, delete no pre-existing file and patch no output. Surface a concise recoverable message, set only `phases.feedback: "completed"` and `last_updated`, and prove `current_phase`, `run_mode`, recommendations, and generated artifacts are unchanged. Feedback failure never changes the Done-versus-Generate decision and never blocks completion.

Return control to `SKILL.md`. Do not emit a backbone handoff, advance a phase, trigger Generate, rerank recommendations, or offer feedback again.
