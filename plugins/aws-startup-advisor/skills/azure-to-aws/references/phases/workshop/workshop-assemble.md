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

# Workshop — Resolve the Sidebar

> **Assembler unit.** The single creator of `scenarios/index.json`. See
> `workshop.md` for how it is composed into the sidebar.

Writes the scenario index, marks `phases.workshop` as `"completed"`, and returns
control so the post-Estimate gate can be re-presented. Resolving includes the
decline path: a user who enters and leaves without repricing still resolves the
sidebar, which lifts the `_gates: generate` hold.

`scenarios/index.json`'s contract is in
`references/shared/schema-workshop-scenarios.md`.

## When exiting the workshop

Workshop exit returns to the **decision gate** in `estimate-assemble.md` §
Step 2 — never directly to Generate. The user chooses **A** (done for now) or
**C** (generate) there; the active scenario carries into either choice.

1. Set `preferences.workshop.active` to `false` (keep `active_scenario_id`).
2. Ensure `scenarios/index.json` exists (baseline-only is enough).
3. Update `.phase-status.json` (read-merge-write):
   - `phases.workshop` → `"completed"`
   - `current_phase` **stays** `"estimate"` (the decision gate sets the next
     state based on the user's choice)
   - `last_updated` → now
4. Emit:

   ```
   HANDOFF_OK | phase=workshop | artifacts=scenarios/index.json | return_to=decision_gate
   ```

5. Output: "Workshop done. Active scenario: `{id}`." Then re-present the
   decision gate from `estimate-assemble.md` § Step 2 (options **A** and **C**
   — the workshop was just explored, so omit **B**), with the gate's
   verdict/cost lines refreshed from the **active scenario's** estimate.

## Soft postcondition

If scenarios are missing after an empty entry, warn and still mark workshop
`"completed"` + return to the decision gate — do not block the gate.

## Status — build step 6

Implemented, ported from `gcp-to-aws`'s equivalent (which returns to its
`estimate.md` § Decision gate) and adapted to point at this skill's decision
gate location: `estimate-assemble.md` § Step 2 (Azure's Estimate phase splits
the assembler out from the phase manifest — `estimate.md` — the way Clarify
does, so the gate itself lives in the assembler file, not in `estimate.md`).
No other behavior differs — the sidebar-resolve contract (`_gates: generate`,
decline-still-resolves, `current_phase` stays `"estimate"`) is identical to
GCP's per `references/vendored/workshop/workshop-invariants.md` § 2.
