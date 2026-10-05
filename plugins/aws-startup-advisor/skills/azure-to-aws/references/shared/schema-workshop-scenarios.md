# Schema — `scenarios/index.json` and the workshop preference patch

Contract for the workshop sidebar's artifact. `workshop-assemble.md` is its single
creator. The cross-skill invariants that govern the workshop itself live in
`references/vendored/workshop/workshop-invariants.md` and win on any disagreement
with this file.

## `scenarios/index.json`

```jsonc
{
  "phase": "workshop",
  "baseline_scenario_id": "baseline",
  "scenarios": [
    {
      "scenario_id": "baseline",
      "label": "As designed",
      "created_at": "<ISO 8601>",
      "preference_patch": {}, // only the knobs that differ from baseline
      "totals": {
        "non_optimized_monthly": 0,
        "right_sized_monthly": 0
      },
      "pricing_source": "cached", // cached | cached_stale | live | cached_fallback
      "design_snapshot": "scenarios/<scenario_id>/aws-design.json",
      "estimate_snapshot": "scenarios/<scenario_id>/estimation-infra.json"
    }
  ]
}
```

- **`preference_patch` records only the delta**, not a whole preferences file. A full
  copy per scenario is a drift surface, and the delta is also what the comparison view
  wants to display.
- **Both totals per scenario.** A scenario that reports only one of the two is not
  comparable against the baseline, which reports both.
- **`pricing_source` is per scenario, not per run.** Regional dollar deltas are not
  available — pricing is cache-only. A scenario priced from the cached file after a
  region change is labelled `cached_fallback` and presented as approximate rather
  than precise.
- Comparison is capped at five scenarios. Beyond that the table stops informing a
  decision.

## Manifest fields written outside the sidebar

Three per-scenario manifest fields are owned by `estimate-assemble.md` § Scenario
reconciliation, not by the workshop. They exist because a decision-gate correction or
a Step 3b cutover answer can re-price the working tree **after** scenarios were saved,
and `workshop-invariants.md` § 4 requires the working artifacts to match the active
scenario.

| Field               | Type             | Written when                                                                                                          |
| ------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------- |
| `stale`             | boolean          | `true` on every non-active scenario after a gate-side write **changed the estimate**; `false` (or absent) otherwise — a provenance-only write (an unchanged Step 3b answer) leaves it alone |
| `stale_reason`      | string or `null` | with `stale: true` — which row changed at the decision gate and that this scenario was priced before it                                                                                     |
| `corrected_at_gate` | string or `null` | on the active scenario, the dotted key of the row the gate corrected or confirmed (Step 3b, changed or not); its snapshot copies were overwritten in place                                   |

The sidebar never sets these. A new snapshot starts with `stale: false` and the other
two `null`. `workshop-compare.md` suffixes `(stale)` to a stale row and the report's
what-if table labels it; neither re-prices it — the next sidebar Apply snapshots a
fresh scenario against the corrected working tree.

## Status — implemented

The shape above is the contract. The knob set, reprice, and comparison
rendering are in `references/phases/workshop/`.
