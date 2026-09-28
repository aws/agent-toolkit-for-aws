---
_assemble: assemble-feedback
_of_phase: feedback
_reads:
  - collect (fragment contribution)
_produces:
  - feedback.json
  - trace.json
---

# Feedback — Assemble

> **Assembler unit.** The single creator of both sidebar artifacts. See `feedback.md`
> for how it is composed into the sidebar.

Finalizes `feedback.json` and `trace.json`, then re-checks the anonymization boundary
against the produced trace rather than trusting the fragment that wrote it. A leak
found here fails the sidebar's postcondition; because the action is `_warn_and_skip`,
the migration continues without the trace rather than shipping it.

## Status — skeleton (build step 1)

Wiring only; the re-check implementation lands alongside the fixtures work.
