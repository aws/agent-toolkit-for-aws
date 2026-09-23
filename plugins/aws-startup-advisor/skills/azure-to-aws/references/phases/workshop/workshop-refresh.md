---
_fragment: refresh
_of_phase: workshop
---

# Workshop — Apply and Reprice

> **Fragment unit.** See `workshop.md` for how it is composed into the sidebar.

Patches the changed preferences, re-runs Design and Estimate against them, and
snapshots the result under `scenarios/`. Discover is never re-run — the inventory is
unchanged, and re-discovering would make the comparison meaningless as well as slow.

Regional dollar deltas are not available — pricing is cache-only. Rates stay
cached-file-based and the scenario is labelled accordingly rather than presented as
precise.

## Inner runs (artifact-only) — mandatory

Follow the canonical allowed/forbidden contract in
`references/vendored/workshop/workshop-invariants.md` § 3 for every inner
Design/Estimate run. Azure specifics: Design follows `design.md` § Inner
workshop reprice and Estimate follows `estimate-infra.md` § Inner workshop
reprice (both skip state transitions); `phases.design`/`phases.estimate` stay
`"completed"`; `current_phase` stays `"estimate"` until `workshop-assemble.md`.

## Baseline capture

When `scenarios/` or `scenarios/index.json` is absent:

1. `inventory_fingerprint` = SHA-256 hex of `azure-resource-inventory.json` bytes.
2. Create `scenarios/`.
3. Copy working-tree artifacts:
   - `scenarios/scenario-001.preferences.json`
   - `scenarios/scenario-001.aws-design.json`
   - `scenarios/scenario-001.estimation-infra.json`
4. Write `scenarios/scenario-001.json` (`source: "baseline"`, summary from
   `estimation-infra.json` including the three Premium/Balanced/Optimized
   monthly tiers per `estimate-infra.md` § Scenarios).
5. Write `scenarios/index.json` (`baseline` / `active` = `scenario-001`,
   `max_scenarios: 5`).
6. Ensure `preferences.workshop` exists:
   `{ "active": true, "last_sheet_at": "<now>", "active_scenario_id": "scenario-001" }`
7. If baseline-only, return to `workshop.md` for the sheet.

## Apply & reprice

### 1. Inventory guard

If fingerprint ≠ `index.inventory_fingerprint`, **STOP**:

> Inventory changed since baseline. Re-run Discover before workshop reprice.

### 2. Stale Generate guard

If generate completed, require re-entry confirm and reset generate to `pending`.

### 3. Patch preferences

Apply sheet edits. Set `workshop.active: true`, `workshop.last_sheet_at` now.
Leave non-knob fields (licensing, identity, VM/DB cutover, app_service_plans
isolation, cluster pattern confirmations) untouched — those are one-time
migration-runbook decisions, not cost-shaping knobs this sidebar reprices.

**Forced-architecture guard:** If the sheet attempted to set
`cpu_architecture` to `graviton` on a row whose `forced_by` is set, reject the
patch for that field and keep the forced value — see `workshop-sheet.md` §
Step 3.4.

### 4–5. Inner Design then Estimate

Per **Inner runs**. Design must follow `design.md` § Inner workshop reprice
(skip handoff / phase-status). Estimate must follow `estimate-infra.md` §
Inner workshop reprice. Chat note after Estimate:
"Workshop reprice Estimate complete; returning to workshop loop."

### 6. Snapshot

1. Next id `scenario-00N`.
2. If length would exceed 5, **warn and name** oldest non-baseline before delete.
3. Copy prefs / design / estimation into `scenarios/{id}.*`.
4. `preferences_subset`: differing knob paths vs baseline.
5. Label: summarize the subset (e.g. "single-az, Elastic Beanstalk, aggressive
   cost optimization"). If a forced-architecture rejection occurred during
   Step 3, append `(architecture forced by <resource>)` to the label so the
   compare view surfaces it without a separate column.
6. When the inner estimate wrote `recommendation.outcome` (one of `go`,
   `conditional_go`, `defer_for_evidence`, `stay` — asserted in `estimate.md`'s
   postconditions), copy it into the manifest as
   `estimation_summary.recommendation_outcome`; omit/null otherwise — this
   feeds the compare view's Outcome column and flip callout.
7. Update index + `workshop.active_scenario_id`.

### 7. Hand back

Return to `workshop.md` → `workshop-compare.md`.

## Status — build step 6

Implemented, ported from `gcp-to-aws`'s equivalent (which uses the region /
availability / kubernetes / cpu_architecture knob set) and adapted to this
skill's knobs (region / HA posture / compute target / cost optimization /
cpu_architecture) and its Premium/Balanced/Optimized scenario schema (GCP's
scenario schema instead uses `aws_monthly_premium`/`_balanced`/`_optimized`
under a different derivation rule — see `estimate-infra.md` § Scenarios for
this skill's version). The forced-architecture rejection in Step 3 has no GCP
analogue in the workshop layer (GCP's Graviton forcing is a risk-signal
caveat carried forward via `workshop.graviton_note`, not a hard rejection) —
Azure's `forced_by` is a harder constraint (a specific Windows resource makes
Graviton architecturally invalid, not merely risky), so the sheet and this
fragment reject the edit outright rather than carrying a soft caveat.
