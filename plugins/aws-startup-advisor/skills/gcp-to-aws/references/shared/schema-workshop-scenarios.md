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
