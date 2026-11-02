# Workshop Scenarios — Artifact Contract (GCP)

> Port of the Heroku what-if workshop contract for `gcp-to-aws`. Discovery
> inventory is **frozen**; workshop mutates `preferences.json` knobs, refreshes
> Design + Estimate, and snapshots the active priced design.

## Directory layout

```
$MIGRATION_DIR/
├── gcp-resource-inventory.json    # FROZEN
├── preferences.json               # active scenario preferences
├── aws-design.json                # active scenario design
├── estimation-infra.json          # active scenario estimate
└── scenarios/
    ├── index.json
    ├── scenario-001.json
    ├── scenario-001.preferences.json
    ├── scenario-001.aws-design.json
    ├── scenario-001.estimation-infra.json
    └── …
```

Max **5** scenarios. Warn + name eviction before deleting oldest non-baseline.

## `scenarios/index.json`

```json
{
  "baseline_scenario_id": "scenario-001", // REQUIRED
  "active_scenario_id": "scenario-002", // REQUIRED
  "max_scenarios": 5, // REQUIRED
  "inventory_fingerprint": "<sha256 hex of gcp-resource-inventory.json>", // REQUIRED
  "scenarios": [ // REQUIRED
    {
      "scenario_id": "scenario-001",
      "label": "baseline",
      "created_at": "2026-07-19T19:00:00Z",
      "source": "baseline",
      "manifest": "scenarios/scenario-001.json"
    }
  ]
}
```

Use these full field names consistently in capture, refresh, compare, and
restore. `baseline` / `active` and per-manifest `is_baseline` / `is_active` are
not aliases. Both selected IDs must identify a listed scenario, the baseline
must remain listed, `max_scenarios` is exactly 5, and IDs are unique.

## `scenarios/scenario-NNN.json` (manifest)

```json
{
  "scenario_id": "scenario-002", // REQUIRED
  "label": "single-az database",
  "created_at": "2026-07-19T20:15:00Z",
  "source": "baseline|workshop", // REQUIRED
  "graviton_note": "1 incompatible — graviton applies where tier: ready",
  "preferences_subset": {
    "design_constraints.availability.value": "single-az"
  },
  "preferences_fingerprint": "<sha256 of saved preferences bytes>",
  "aws_design_fingerprint": "<sha256 of saved design bytes>",
  "estimation_summary": { // REQUIRED
    "aws_monthly_premium": 0,
    "aws_monthly_balanced": 0,
    "aws_monthly_optimized": 0,
    "complexity_tier": "small|medium|large",
    "pricing_source": "cached|cached_fallback|unavailable",
    "region_note": null,
    "graviton_note": null,
    "calculator_url": null,
    "recommendation_outcome": "go|conditional_go|defer_for_evidence|stay"
  },
  "paths": { // REQUIRED
    "preferences": "scenarios/scenario-002.preferences.json",
    "aws_design": "scenarios/scenario-002.aws-design.json",
    "estimation_infra": "scenarios/scenario-002.estimation-infra.json"
  }
}
```

`source` is `baseline` for the original capture and `workshop` for later applies.
The subset contains only edited knob paths; optional fingerprints, summary notes,
and outcome may be omitted. When supplied, hash the saved bytes, not reserialized
JSON. Each path must exist and point to the matching scenario's complete artifact.

## `preferences.json` → `workshop` object

```json
"workshop": {
  "active": true,
  "last_sheet_at": "2026-07-19T20:00:00Z",
  "active_scenario_id": "scenario-002",
  "graviton_note": "1 incompatible — graviton applies where tier: ready"
}
```

Clarify does **not** write this. Workshop creates/patches it.
`graviton_note` is optional — set when the sheet showed Graviton risk-signal
tiers and the SA picked `graviton` or `mixed` (see `workshop-sheet.md`).
Only `active`, `last_sheet_at`, and `active_scenario_id` may differ between
active preferences and the selected snapshot after selection or restoration.
Keep `graviton_note` and other semantic fields equal to the saved scenario.

## v1 knobs (sheet)

| Path                                        | Notes                                       |
| ------------------------------------------- | ------------------------------------------- |
| `design_constraints.target_region.value`    | AWS region                                  |
| `design_constraints.availability.value`     | HA posture                                  |
| `design_constraints.kubernetes.value`       | When present                                |
| `design_constraints.cpu_architecture.value` | `graviton` \| `x86` \| `mixed` when present |

Cross-skill arch defaults: heroku workshop defaults x86;
GCP uses Clarify's `graviton`/`x86`/`mixed` vocabulary.

## Fingerprint

`inventory_fingerprint` = SHA-256 hex of `gcp-resource-inventory.json` bytes.
Abort refresh on drift.

## Scenario manifest extras

Each `scenario-NNN.json` manifest's `estimation_summary` carries the three
monthly tiers, `complexity_tier`, `pricing_source`, optional
`graviton_note`/`region_note`, optional `recommendation_outcome` (copy
`recommendation.outcome` from the inner estimate when it wrote v2 decision
fields, else omit/null — feeds the compare view's Outcome column and flip
callout), and `calculator_url` — always `null`. No shareable AWS Pricing
Calculator link is produced; no calculator MCP is configured. Regional price differences are surfaced via cache-tier comparison
notes instead.
