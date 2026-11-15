---
_assemble: assemble-estimation
_of_phase: estimate
_reads:
  - infra
_produces:
  - estimation-infra.json
---

# Assemble estimate and decision gate

Canonicalize line order by source resource ID, scenario, AWS service, then line ID bytes. Recompute both scenario sums from rounded lines; reject supplied totals that differ. Require `delta_monthly_usd = right_sized.known_cost_monthly_usd - capacity_preserving.known_cost_monthly_usd` and require matching floor flags/unpriced IDs. Re-run source-price freshness and right-sizing gates rather than trusting confidence labels. Validate and atomically write `estimation-infra.json`.

After outer `HANDOFF_OK`, mark Estimate completed but retain `current_phase: "estimate"`. Seed workshop pending if absent and offer workshop versus proceed. Workshop entry sets only `phases.workshop: "in_progress"`; decline sets it completed. After workshop resolution, present Done-for-now versus Generate:

- Done writes `run_mode: "decide"`, leaves Generate pending, and sets `current_phase: "complete"`.
- Generate writes `run_mode: "decide_and_execute"` and sets `current_phase: "generate"`.

Never auto-select Generate and do not emit `plan.json`. An inner workshop reprice writes and validates artifacts only: it emits no phase handoff, changes no backbone status, and returns to the workshop loop.
