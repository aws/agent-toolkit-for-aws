# Workshop — Compare Scenarios (GCP)

> Read-only table from `scenarios/index.json`.

## Steps

1. Load `scenarios/index.json` (if missing, tell user to Apply once for baseline).
2. For each scenario (baseline first, then by `created_at`), build columns:
   - Region ← `design_constraints.target_region.value`
   - HA ← `design_constraints.availability.value`
   - Compute ← `design_constraints.kubernetes.value` when present
   - Arch ← `design_constraints.cpu_architecture.value` when present
   - Premium / Balanced / Optimized $/mo ← `estimation_summary` tiers
   - Complexity ← `estimation_summary.complexity_tier`
   - Outcome ← `estimation_summary.recommendation_outcome` when present (omit the column when no scenario carries it)
3. Mark the active row.
4. Present:

| Scenario | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity | Outcome |
| -------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- | ------- |

**Outcome flip callout:** when any scenario's `recommendation_outcome` differs
from the baseline's, add one line under the table naming the flip and the knob
that drove it — e.g. "single-az scenario flips conditional_go → go: the
availability condition no longer applies." This is the compare view's most
decision-relevant line; never bury it.

Under the table: active vs baseline `preferences_subset`; any `region_note`;
one `{scenario}: {url}` line per non-null `estimation_summary.calculator_url`
(shareable, editable calculator.aws estimate — AWS computes regional prices
server-side there); reminder that inventory is frozen. Keep under 25 lines.
