---
_assemble: assemble-intake
_of_phase: intake
_reads:
  - entry-point + background answers (collected inline in intake.md Steps 2–4)
_produces:
  - .phase-status.json
---

# Intake — Assemble run state

> **Assembler unit.** Intake asks the two entry questions and captures open
> context inline within `intake.md`, then writes the run's `.phase-status.json`
> (Step 5). This unit records the artifact-level contract for the phase: it is
> the single creator of `.phase-status.json`, and its postconditions (declared
> on the phase) are the phase's completion gate. See `intake.md` § Step 5 for the
> state schema (`entry_point`, `audience`, `intake = completed`, later phases
> pending/skipped per entry point).

The state contract additionally includes `target_maturity` (`prototype`, `private_beta`, or `production`), collected with the Intake questions unless a validated seed supplies it. Intake persists it verbatim; it is neither a runtime inference nor a deployment outcome.
