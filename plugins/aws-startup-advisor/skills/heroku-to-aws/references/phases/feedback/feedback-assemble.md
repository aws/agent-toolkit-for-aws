---
_assemble: assemble-feedback
_of_phase: feedback
_reads:
  - collect (fragment contribution)
_produces:
  - feedback.json
  - trace.json
---

# Feedback — Assemble and Complete

> **Assembler unit.** Runs after the collect fragment (`feedback-collect.md`) has
> written `feedback.json` (and optionally `trace.json`). It enforces the output
> gate, marks the migration complete in `.phase-status.json`, and owns the final
> artifact-level contract for this terminal phase.

---

## Step 5: Update Phase Status and Mark Complete

**Output gate** — verify before updating:

- `feedback.json` exists
- If `trace_included` is true, `trace.json` exists

If gate fails: **STOP**. Output: "Feedback outputs are incomplete. Fix feedback artifacts before completion."

Phase Status Update (read-merge-write):

- `phases.feedback` → `"completed"`
- `current_phase` → `"complete"`
- `last_updated` → current ISO 8601

Emit:

```
HANDOFF_OK | phase=feedback | artifacts=feedback.json,trace.json
```

Output: "Thank you for helping improve this tool. Migration planning is complete."

Return control to SKILL.md. The migration is finished.
