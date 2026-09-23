---
_fragment: compare
_of_phase: workshop
---

# Workshop — Compare Scenarios

> **Fragment unit.** See `workshop.md` for how it is composed into the sidebar.

Renders the priced scenarios side by side so the tradeoff is visible: what each knob
change cost or saved, and what it changed about the architecture. Comparison is
capped at five scenarios — beyond that the table stops informing a decision.

## Steps

1. Load `scenarios/index.json` (if missing, tell the user to Apply once for baseline).
2. For each scenario (baseline first, then by `created_at`), build columns:
   - Region ← `global.target_region.value`
   - HA ← `data.availability.value`
   - Compute ← `design_constraints.compute_target.value` when present
   - Arch ← `design_constraints.cpu_architecture.value` when present
   - Premium / Balanced / Optimized $/mo ← `estimation_summary` tiers (per
     `estimate-infra.md` § Scenarios — Balanced is the anchor, Premium and
     Optimized are stated adjustments off it)
   - Complexity ← `estimation_summary.complexity_tier`
   - Outcome ← `estimation_summary.recommendation_outcome` when present (omit the column when no scenario carries it)
3. Mark the active row.
4. Present:

| Scenario | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity | Outcome |
| -------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- | ------- |

**Outcome flip callout:** when any scenario's `recommendation_outcome` differs
from the baseline's, add one line under the table naming the flip and the knob
that drove it — e.g. "single-az scenario flips conditional_go → go: the
availability-downgrade condition no longer applies." This is the compare view's
most decision-relevant line; never bury it.

**Forced-architecture note:** if any scenario carries `(architecture forced by
<resource>)` in its label (see `workshop-refresh.md` § Snapshot), keep that
parenthetical visible in the Scenario column — it explains why that row's Arch
is `x86_64` even when the user asked for Graviton on the sheet.

Under the table: active vs baseline `preferences_subset`; any `region_note`;
one `{scenario}: {url}` line per non-null `estimation_summary.calculator_url`
(shareable, editable calculator.aws estimate — AWS computes regional prices
server-side there); reminder that inventory is frozen. Keep under 25 lines.

## Status — build step 6

Implemented, ported from `gcp-to-aws`'s equivalent and adapted to this skill's
knobs (region / HA posture / compute target / cpu_architecture — GCP's compare
table instead shows region / availability / kubernetes / cpu_architecture) and
its Premium/Balanced/Optimized scenario schema. Added the forced-architecture
note, which has no GCP analogue — GCP's Graviton risk-signal caveat travels as
`workshop.graviton_note` rather than a hard per-scenario label suffix, because
Azure's `forced_by` is a harder constraint than GCP's risk-signal tiers (see
`workshop-refresh.md` § Status).
