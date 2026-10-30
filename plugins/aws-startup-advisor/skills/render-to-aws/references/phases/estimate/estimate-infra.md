---
_fragment: infra
_of_phase: estimate
_contributes:
  - estimation-infra.json
---

# Estimate infrastructure

## Source baseline

Apply the source hierarchy without blending sources. Invoice/export and user-stated values retain their own as-of date and currency. Cache pricing is eligible only when `as_of + max_age_days` includes the estimate date, currency is USD, and every billed resource has an exact normalized plan or legacy-alias match. Plan resolution is one step: use the inventory's `plan_normalized` (the Blueprint parser and the live normalizer both compute it from `references/shared/render-plan-aliases.json`), or apply that table yourself when a captured plan carries none, then look the canonical id up exactly in the cache. A plan the table leaves null, or a canonical id with no cache row, is `unavailable`; never substitute the nearest plan. An unmatched or stale row is `unavailable`, not zero and not a partial source total.

When no source in the hierarchy yields a baseline, write `current_costs` as exactly `source: "unavailable"` with `render_monthly: null`; every other `source` carries a numeric `render_monthly`. The report renders that baseline cell as the literal text `unavailable`, and the report validator accepts only this pairing while still requiring exact amounts whenever `render_monthly` is a number.

Price Key Value from normalized memory plan IDs, including `3g` and `50g`; aliases resolve through the same shared table before lookup. Price service plans using CPU and RAM as independent captured dimensions. Price Workflow Flex as `(active_cpu_hours × 0.20) + (active_gb_hours × 0.05) + (retained_state_gb × 0.25)`, respecting the one-second 0.1 CPU/0.1 GB per-run minimum. Fixed Workflow plans use task duration multiplied by the exact hourly row. Missing task duration makes Workflow source cost unavailable.

## Rightsizing evidence gate

Load `rightsizing-thresholds.json`. A resource earns `measured` sizing only when the metric window spans at least seven days, expected-sample coverage is at least 0.80, resolution is one of 30/60/300/3600 seconds, outcomes contain points rather than successful-empty/plan-gated values, and instance series are aligned to lifecycle intervals. Do not sum replacement instances as concurrent capacity or interpolate idle gaps as zero.

If any gate fails, right-sized capacity equals capacity-preserving capacity, confidence remains `inferred`, and the explanation names every failed threshold. Down-sizing additionally requires CPU p95, memory p95, memory peak, headroom, and source minimums to pass the numeric limits in the knowledge file. AI/agent infrastructure applies the named memory-headroom multiplier, but the AI execution track stays unpriced.

Cron runtime is unavailable unless customer-provided or captured run history establishes actual duration with sufficient evidence. A schedule alone never creates monthly runtime. Workflow and task durations follow the same evidence rule.

## Dual totals and floors

For each selected AWS mapping, emit parallel `capacity_preserving` and `right_sized` line objects with quantity, unit, rate, formula, monthly amount or null, pricing source, confidence, and exclusion reason. Apply service-specific Multi-AZ handling from the cache; never use a blanket multiplier. A target-region mismatch keeps the us-east-1 amount but adds the required region note and widens confidence; it does not invent a multiplier.

For each scenario:

1. Sum only non-null rounded line amounts.
2. Record all null lines in `unpriced_line_ids`.
3. Set `is_floor` true when that list is nonempty and label the numeric value “known-cost floor,” never “total.”
4. Require every design mapping to produce a priced, no-direct-charge, or explicitly unpriced line.
5. Compute delta only from the two known-cost floors and carry incompleteness into the explanation.

Human labor, migration engineering, and downtime are considerations with no dollar amount. Commitment opportunities follow the vendored eligibility matrix and do not reduce the capacity-preserving on-demand total; Compute Savings Plans remain percent-only until 30–90 days of AWS usage establishes a floor.
