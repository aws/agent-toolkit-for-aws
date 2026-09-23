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

## Status — skeleton (build step 1)

The shape is the real contract. The knob set, the reprice mechanics, and the
comparison rendering land in step 6.
