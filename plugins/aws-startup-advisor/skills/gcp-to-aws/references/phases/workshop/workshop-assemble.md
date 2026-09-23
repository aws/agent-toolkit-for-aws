# Workshop — Assemble (sidebar resolve)

> Marks the workshop sidebar resolved and returns control to the backbone.
> Does **not** set `current_phase` to `workshop`.

## When exiting the workshop

Workshop exit returns to the **Decision gate** in `estimate.md` — never
directly to Generate. The user chooses A (done for now) or C (generate) there;
the active scenario carries into either choice.

1. Set `preferences.workshop.active` to `false` (keep `active_scenario_id`).
2. Ensure `scenarios/index.json` exists (baseline-only is enough).
3. Update `.phase-status.json` (read-merge-write):
   - `phases.workshop` → `"completed"`
   - `current_phase` **stays** `"estimate"` (the Decision gate sets the next
     state based on the user's choice)
   - `last_updated` → now
4. Emit:

   ```
   HANDOFF_OK | phase=workshop | artifacts=scenarios/index.json | return_to=decision_gate
   ```

5. Output: "Workshop done. Active scenario: `{id}`." Then re-present the
   Decision gate from `estimate.md` (options A and C — the workshop was just
   explored, so omit B), with the gate's verdict/cost lines refreshed from the
   **active scenario's** estimate.

## Soft postcondition

If scenarios are missing after an empty entry, warn and still mark workshop
`"completed"` + return to the Decision gate — do not block the gate.
