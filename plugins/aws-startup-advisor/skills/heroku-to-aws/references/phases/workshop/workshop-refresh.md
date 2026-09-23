---
_fragment: refresh
_of_phase: workshop
---

# Workshop — Refresh (patch → Design → Estimate → snapshot)

> Runs after the user confirms **Apply & reprice**, or for one-time **baseline
> capture** when `scenarios/index.json` is missing.

## Inner runs (artifact-only) — mandatory

Follow `references/vendored/workshop/workshop-invariants.md` § 3 (canonical
allowed/forbidden contract) for every inner Design/Estimate run. Heroku
specifics: leave `phases.design` and `phases.estimate` as `"completed"`;
the inner Estimate skips the post-Estimate workshop offer; `current_phase`
stays `"estimate"` until `workshop-assemble.md`.

## Baseline capture (no Design yet)

When `scenarios/` or `scenarios/index.json` is absent:

1. Compute `inventory_fingerprint` = SHA-256 hex of
   `$MIGRATION_DIR/heroku-resource-inventory.json` bytes.
2. Create `scenarios/`.
3. Copy working-tree artifacts to:
   - `scenarios/scenario-001.preferences.json`
   - `scenarios/scenario-001.aws-design.json`
   - `scenarios/scenario-001.estimation-infra.json`
4. Write `scenarios/scenario-001.json` manifest with
   `source: "baseline"`, `label: "baseline"`, fingerprints, and
   `estimation_summary` from current `estimation-infra.json`
   (`projected_costs.*`, `complexity_tier`, `pricing_source.status`,
   `workshop.region_note` or `null`).
5. Write `scenarios/index.json` with `baseline_scenario_id` /
   `active_scenario_id` = `scenario-001`, `max_scenarios: 5`.
6. Ensure `preferences.workshop` exists:
   `{ "active": true, "cpu_architecture": "<existing or x86_64>",
     "last_sheet_at": "<now>", "active_scenario_id": "scenario-001" }`
   Write preferences back if created/updated.
7. If this invocation was baseline-only (no sheet apply), **stop** and return to
   `workshop.md` to present the sheet.

## Apply & reprice

### 1. Inventory guard

Recompute inventory fingerprint. If it differs from
`scenarios/index.json.inventory_fingerprint`, **STOP**:

> Inventory changed since baseline. Re-run Discover before workshop reprice.

### 2. Stale Generate guard — already enforced at Entry, not repeated here

`workshop.md` § Entry step 2 ("Stale Generate/decide guard") is the single
authoritative point that detects a stale Generate/decide state (completed,
in-progress, or a resolved decide-complete with `run_mode` set) and resets
`phases.generate` and downstream phases to `"pending"`. It runs before
`workshop-refresh.md` is ever reached, on every path into this phase (Apply &
reprice, Compare scenarios, or exiting workshop without touching this file at
all). By the time this step runs, `phases.generate` has therefore already
been reset if it needed to be.

That guard does NOT delete anything Generate wrote — a previous execution
pack (`terraform/`, `generation-*.json`, etc.) is left on disk untouched,
since files under `terraform/` may carry customer edits (`generate-terraform.md`
tells users to fill in `terraform.tfvars` and hand-edit `baseline.tf`/
`variables.tf`) that no filename-based rule can safely distinguish from
still-pristine generated output. The Decision gate's `--mode decision`
validator determines "pre-execution" from `.phase-status.json`'s
`phases.generate` value, not from whether those files exist — so a stale
execution pack coexisting with a fresh decision is the expected, supported
state, not something this step needs to resolve.

Do not re-check `phases.generate == "completed"` here — a second check at
this point would never fire, since Entry step 2 already reset it on this same
invocation.

If `workshop-refresh.md` is ever invoked without having passed through
`workshop.md` § Entry, treat that as an interpreter bug.

### 3. Patch preferences

Apply sheet edits to `$MIGRATION_DIR/preferences.json`:

- Update knob paths from the sheet.
- Set `metadata.timestamp` to now.
- Set `workshop.active: true`, `workshop.last_sheet_at` to now,
  `workshop.cpu_architecture` from the sheet.
- Leave non-knob fields untouched.

### 4. Re-run Design (inner)

Execute Design per **Inner runs** above against the frozen inventory + patched
preferences. Overwrite `$MIGRATION_DIR/aws-design.json`. Do not touch inventory.

### 5. Re-run Estimate (inner)

Execute Estimate per **Inner runs** above. Overwrite
`$MIGRATION_DIR/estimation-infra.json`. Chat note only:
"Workshop reprice Estimate complete; returning to workshop loop."

### 6. Snapshot new scenario

1. Allocate next id: `scenario-00N` where N = max existing + 1 (zero-pad 3).
2. If `index.json.scenarios.length` would exceed 5, **before deleting**: warn the
   user with the scenario id and label that will be evicted (oldest non-baseline),
   then delete that scenario's manifest + three artifact copies and drop it from
   `index.json.scenarios[]`. Never delete `baseline_scenario_id` unless the user
   explicitly resets the workshop.
3. Copy working-tree preferences / aws-design / estimation-infra into
   `scenarios/{id}.*`.
4. Build `preferences_subset`: dot-paths whose values differ from
   `scenario-001.preferences.json` (workshop knobs only — region, availability,
   database_ha, redis_ha, compute_target.default, cost_optimization,
   workshop.cpu_architecture).
5. Write `scenarios/{id}.json` with `source: "workshop"`, label summarizing the
   subset (e.g. `arm64 + multi-az`), fingerprints, estimation_summary
   (include all three monthly tiers + `region_note` from estimation-infra if
   present).
6. Update `index.json`: append scenario, set `active_scenario_id`, set
   `preferences.workshop.active_scenario_id` to match; write preferences.

### 7. Hand back

Return to `workshop.md` → run `workshop-compare.md`.
