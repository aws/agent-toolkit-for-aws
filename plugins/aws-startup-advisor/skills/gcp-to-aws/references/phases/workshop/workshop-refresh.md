# Workshop — Refresh (patch → Design → Estimate → snapshot)

## Inner runs (artifact-only) — mandatory

Follow the canonical allowed/forbidden contract in
`references/vendored/workshop/workshop-invariants.md` § 3 for every inner
Design/Estimate run. GCP specifics: Design follows `design.md` § Inner
workshop reprice and Estimate follows `estimate.md` § Inner workshop
reprice (both skip state transitions); `phases.design`/`phases.estimate`
stay `"completed"`; `current_phase` stays `"estimate"` until
`workshop-assemble.md`.

## Baseline capture

When `scenarios/` or `scenarios/index.json` is absent:

1. `inventory_fingerprint` = SHA-256 hex of `gcp-resource-inventory.json` bytes.
2. Create `scenarios/`.
3. Copy working-tree artifacts:
   - `scenarios/scenario-001.preferences.json`
   - `scenarios/scenario-001.aws-design.json`
   - `scenarios/scenario-001.estimation-infra.json`
4. Write `scenarios/scenario-001.json` (`source: "baseline"`, summary from
   estimation-infra including three monthly tiers).
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
Leave non-knob fields (including AI/agentic constraints) untouched.

**Graviton caveat carry-forward:** If the sheet showed a Graviton risk-signal
caveat (any `graviton_profile` entry with `tier` in
`{incompatible, conditional, unknown}`) and the SA set
`cpu_architecture` to `graviton` or `mixed`, set
`preferences.workshop.graviton_note` to a short string naming the counts, e.g.
`"1 incompatible, 0 conditional — graviton applies where tier: ready"`. Clear
`graviton_note` when arch is `x86` or when no risk-signal tiers exist.

### 4–5. Inner Design then Estimate

Per **Inner runs**. Design must follow `design.md` § Inner workshop reprice
(skip handoff / phase-status). Estimate must follow `estimate.md` § Inner
workshop reprice. Chat note after Estimate:
"Workshop reprice Estimate complete; returning to workshop loop."

### 6. Snapshot

1. Next id `scenario-00N`.
2. If length would exceed 5, **warn and name** oldest non-baseline before delete.
3. Copy prefs / design / estimation into `scenarios/{id}.*`.
4. `preferences_subset`: differing knob paths vs baseline.
5. Label: summarize the subset; if `workshop.graviton_note` is set, append
   `(caveat: <graviton_note>)` to the scenario `label` and copy the note into
   the manifest as `graviton_note`.
6. When the inner estimate wrote `recommendation.outcome` (v2 decision
   fields), copy it into the manifest as
   `estimation_summary.recommendation_outcome`; omit/null otherwise — this
   feeds the compare view's Outcome column and flip callout.
7. Update index + `workshop.active_scenario_id`.

### 7. Hand back

Return to `workshop.md` → `workshop-compare.md`.
