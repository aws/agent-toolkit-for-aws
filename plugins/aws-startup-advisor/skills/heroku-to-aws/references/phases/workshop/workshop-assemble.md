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

# Workshop — Assemble (sidebar resolve)

> Marks the workshop sidebar resolved and returns control to the backbone.
> Does **not** set `current_phase` to `workshop` (forbidden for sidebars).
> Per `references/vendored/workshop/workshop-invariants.md` § 2: a skill that
> DEFINES a post-Estimate decision gate (heroku-to-aws does) must
> re-present that gate on exit — **never**
> auto-advance `current_phase` to `"generate"` directly. The gate (not this
> assembler) sets the next state from the user's A/C choice.

## When exiting the workshop

Workshop exit returns to the **Decision gate** in `estimate-assemble.md` §
"Post-Estimate: Decision Gate" — never directly to Generate. The user chooses
**A** (done for now) or **C** (generate) there; the active scenario carries
into either choice.

1. Set `preferences.workshop.active` to `false` (keep `active_scenario_id`).
2. Ensure `scenarios/index.json` exists (baseline-only is enough if user entered
   then exited without Apply).
3. Update `.phase-status.json` (read-merge-write):
   - `phases.workshop` → `"completed"` (sidebar resolved — participated)
   - `current_phase` **stays** `"estimate"` (the Decision gate sets the next
     state based on the user's choice)
   - Do **not** touch `run_mode` here — the gate is the only writer.
   - `last_updated` → now
4. Emit:

   ```
   HANDOFF_OK | phase=workshop | artifacts=scenarios/index.json | return_to=decision_gate
   ```

5. Output: "Workshop done. Active scenario: `{id}`." Then re-present the
   Decision gate from `estimate-assemble.md` (options **A** and **C** — the
   workshop was just explored, so omit **B**), with the gate's verdict/cost
   lines refreshed from the **active scenario's** `estimation-infra.json`.

## When declining at Estimate offer (no entry)

Handled in `estimate-assemble.md` / `SKILL.md` — set `phases.workshop` to
`"completed"` without requiring `scenarios/`. Participation signal = presence of
`scenarios/index.json`.

## Soft postcondition

If the user exits without any scenario directory (edge case), emit
`_warn_and_skip` for the scenarios postcondition and still mark workshop
`"completed"` — then return to the Decision gate per above (never advance to
Generate directly, even on this soft path).
