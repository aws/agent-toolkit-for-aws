# Workshop Scenarios — Artifact Contract

> Schema for Heroku what-if workshop snapshots under `$MIGRATION_DIR/scenarios/`.
> Discovery inventory is **frozen**; workshop only mutates `preferences.json`,
> refreshes Design + Estimate, and snapshots the active priced design.

## Directory layout

```
$MIGRATION_DIR/
├── heroku-resource-inventory.json   # FROZEN — workshop never rewrites
├── preferences.json                 # active scenario preferences
├── aws-design.json                  # active scenario design
├── estimation-infra.json            # active scenario estimate
└── scenarios/
    ├── index.json
    ├── scenario-001.json            # manifest (baseline)
    ├── scenario-001.preferences.json
    ├── scenario-001.aws-design.json
    ├── scenario-001.estimation-infra.json
    └── …
```

Max **5** scenarios. When a sixth would be added, **warn and name** the oldest
non-baseline scenario (id + label) that will be evicted, then delete its files
and drop it from `index.json.scenarios[]`. Never delete `baseline_scenario_id`
unless the user explicitly resets the workshop.

## `preferences.json` → `workshop` object

Optional object assembled/patched by the workshop (not by Clarify interview):

```json
"workshop": {
  "active": true,
  "cpu_architecture": "x86_64",
  "last_sheet_at": "2026-07-19T20:00:00Z",
  "active_scenario_id": "scenario-002"
}
```

| Field                | Type    | Rules                                             |
| -------------------- | ------- | ------------------------------------------------- |
| `active`             | boolean | `true` while the user is in workshop mode         |
| `cpu_architecture`   | string  | `"x86_64"` (default) or `"arm64"`                 |
| `last_sheet_at`      | string  | ISO 8601 UTC of last sheet apply                  |
| `active_scenario_id` | string  | matches a `scenario_id` in `scenarios/index.json` |

Omit `workshop` entirely on Clarify-first assemble. Workshop refresh creates it.

## `scenarios/index.json`

```json
{
  "baseline_scenario_id": "scenario-001",
  "active_scenario_id": "scenario-002",
  "max_scenarios": 5,
  "inventory_fingerprint": "<sha256 hex of heroku-resource-inventory.json>",
  "scenarios": [
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

`inventory_fingerprint` is recorded at baseline capture. Every workshop refresh
MUST recompute the fingerprint of `heroku-resource-inventory.json` and abort with
an error if it differs (inventory changed — user must re-Discover).

## `scenarios/scenario-NNN.json` (manifest)

```json
{
  "scenario_id": "scenario-003",
  "label": "arm64 + multi-az",
  "created_at": "2026-07-19T20:15:00Z",
  "source": "workshop",
  "preferences_subset": {
    "global.target_region": "us-west-2",
    "workshop.cpu_architecture": "arm64"
  },
  "preferences_fingerprint": "<sha256 of preferences.json>",
  "aws_design_fingerprint": "<sha256 of aws-design.json>",
  "estimation_summary": {
    "aws_monthly_premium": 0,
    "aws_monthly_balanced": 0,
    "aws_monthly_optimized": 0,
    "complexity_tier": "small",
    "pricing_source": "cached",
    "region_note": null,
    "calculator_url": null
  },
  "paths": {
    "preferences": "scenarios/scenario-003.preferences.json",
    "aws_design": "scenarios/scenario-003.aws-design.json",
    "estimation_infra": "scenarios/scenario-003.estimation-infra.json"
  }
}
```

`preferences_subset` lists only knobs that differ from the baseline scenario's
preferences (dot-paths). `source` is `"baseline"` for scenario-001 and
`"workshop"` for later applies.

## Fingerprints

SHA-256 hex of the raw file bytes (no JSON re-serialize). Use the same algorithm
for inventory, preferences, and design so the fixture asserter can verify
byte-stability of discovery.
