---
_assemble: assemble-estimation
_of_phase: estimate
_reads:
  - infra
_produces:
  - estimation-infra.json
---

# Assemble estimate and decision gate

Canonicalize line order by source resource ID, scenario, AWS service, then line ID bytes. Recompute the premium, balanced, optimized and like-for-like sums from rounded lines; reject supplied totals that differ. Require `rightsizing_delta.monthly = like_for_like.known_cost_monthly_usd - balanced.known_cost_monthly_usd`, `premium ≥ balanced ≥ optimized`, and recompute the Optimized discount from the `references/vendored/estimate/commitment-discount-ranges.json` rates, service caps and Generation 7+ gate on the `knowledge/estimate/estimate-defaults.json` `commitment_eligibility` subtotal only, rounding each eligible line's discount to whole dollars half-to-even before summing; require matching floor flags/unpriced IDs. Require `projected_costs.aws_monthly_premium`, `aws_monthly_balanced` and `aws_monthly_optimized` to equal `scenarios.premium`, `scenarios.balanced` and `scenarios.optimized` `.known_cost_monthly_usd`; the report validator rejects a report whose estimate breaks any of the three equalities. Re-run source-price freshness and right-sizing gates rather than trusting confidence labels. Validate and atomically write `estimation-infra.json`.

After outer `HANDOFF_OK`, mark Estimate completed but retain `current_phase: "estimate"`. Seed workshop pending if absent and offer workshop versus proceed. Workshop entry sets only `phases.workshop: "in_progress"`; decline sets it completed. After workshop resolution, present Done-for-now versus Generate:

- Done writes `run_mode: "decide"`, leaves Generate pending, sets `current_phase: "complete"`, and then runs the fail-open web handoff in `references/shared/web-handoff.md` before the closing message. That closing message names `plan.json` and carries the AWS Startups Migrate link only when the writer printed `PLAN_OK`.
- Generate writes `run_mode: "decide_and_execute"` and sets `current_phase: "generate"`.

Never auto-select Generate; the Generate choice defers the web handoff to the end of Generate. An inner workshop reprice writes and validates artifacts only: it emits no phase handoff, changes no backbone status, and returns to the workshop loop.
