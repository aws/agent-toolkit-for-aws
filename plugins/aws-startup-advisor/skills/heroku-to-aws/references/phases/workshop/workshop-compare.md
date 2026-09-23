---
_fragment: compare
_of_phase: workshop
---

# Workshop — Compare Scenarios

> Render a side-by-side table from `scenarios/index.json` and each scenario
> manifest. Read-only — does not Design or Estimate.

## Step 1: Load index

Read `$MIGRATION_DIR/scenarios/index.json`. If missing, tell the user to Apply &
reprice once (baseline capture) and stop.

## Step 2: Build rows

For each entry in `index.scenarios[]` (stable order: baseline first, then by
`created_at`):

1. Read the manifest at `entry.manifest`.
2. From the baseline preferences copy and this scenario's preferences copy,
   resolve display columns:
   - Region ← `global.target_region`
   - HA ← `data.database_ha` if present else `global.availability`
   - Compute ← `design_constraints.compute_target.default` (or legacy `.value`)
   - Arch ← `workshop.cpu_architecture` or `x86_64`
3. From `estimation_summary`: Premium / Balanced / Optimized $/mo and
   `complexity_tier` (all three tiers — pitch compares Graviton Optimized vs
   Multi-AZ Premium, not Balanced alone).
4. Mark the row active when `scenario_id == index.active_scenario_id`.

## Step 3: Present

Output a markdown table:

| Scenario                | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity |
| ----------------------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- |
| baseline                | …      | …  | …       | …    | …            | …             | …              | …          |
| scenario-002 _(active)_ | …      | …  | …       | …    | …            | …             | …              | …          |

Under the table:

- One line of knob deltas for the active scenario vs baseline
  (`preferences_subset` from the active manifest).
- If any scenario has a non-null `region_note`, quote it once (note: regional
  deltas are qualitative; rates are cache-based).
- `estimation_summary.calculator_url` is always `null` — no shareable calculator
  link is produced.
- Remind: discovery inventory is frozen; Generate uses the **active** working-tree
  artifacts.

Keep under 25 lines total.
