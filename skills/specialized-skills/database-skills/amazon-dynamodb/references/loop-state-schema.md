# loop_state.json schema

`loop_state.json` is the compact genealogy file the iterative design loop
(`${SKILL_DIR}/scripts/iterate_design.py`) appends to once per round. It exists
so the agent can show cross-round deltas ("round 2's PK sharding cut W1
throttles from 1450 → 0 and dropped p99 70 ms") and the user's decisions
without re-reading each round's large artifacts. It is deliberately small —
a handful of scalars per round — so the agent can read it every round at
negligible token cost. It is the third compact artifact the loop produces,
alongside `design_findings.json` and `cost_report.md`. (`${SKILL_DIR}` is
defined in SKILL.md "Resolving the skill's own paths".)

## Shape

```json
{
  "loop_id": "a1b2c3d4",
  "model_path": "dynamodb_data_model.json",
  "created_at": "2026-06-24T20:00:00Z",
  "current_schema_fingerprint": "e4baa84e1ef7",
  "active_manifest": "ddb-skill-bench-20260624-ab12cd34-",
  "rounds": [
    {
      "round": 0,
      "timestamp": "2026-06-24T20:05:00Z",
      "mode": "representative",
      "scale_factor": 0.15,
      "applied_diff": null,
      "schema_fingerprint": "e4baa84e1ef7",
      "deploy_decision": "deploy",
      "headline": {
        "extrapolated_monthly_usd": 21450.0,
        "calculator_monthly_usd": 20088.0,
        "hot_pattern_throttles": { "W1": 1450 },
        "p99_ms_by_pattern": { "W1": 120.0, "Q1": 18.0 },
        "max_gsi_amplification": 0.0,
        "top_key_share_by_pattern": { "W1": 0.41 }
      },
      "delta_vs_prev": {
        "monthly_usd_pct": null,
        "throttle_delta": {},
        "p99_delta_ms": {},
        "gsi_amp_delta": null
      },
      "finding_signals": ["key_skew_patterns"],
      "user_decision": null
    }
  ]
}
```

## Fields

### Top level

| Field | Meaning |
|---|---|
| `loop_id` | Short id for this loop session. |
| `model_path` | The design JSON the loop iterates (single source of truth). |
| `created_at` | When the loop started (ISO; passed in via `--timestamp`, defaults to now). |
| `current_schema_fingerprint` | Fingerprint of the latest design. Drives the reuse-vs-redeploy decision next round: if the new design's fingerprint matches and a deployment is active, the next round REUSES it. |
| `active_manifest` | Resource prefix of the live deployment (or `null`). |
| `rounds` | Append-only list, one entry per `iterate_design.py` invocation. |

### Per-round entry

| Field | Meaning |
|---|---|
| `round` | Zero-based index. |
| `timestamp` | When the round ran (ISO; passed in). |
| `mode` | Benchmark mode (`representative` by default). |
| `scale_factor` | The scale the round drove at. |
| `applied_diff` | The literal user-agreed change applied at the START of this round (`merge` object or `ops` list), or `null`. This is the genealogy of *what changed and when*. |
| `schema_fingerprint` | Fingerprint of the design as benchmarked this round (key schema + GSIs + streams; RPS/item-size changes do NOT change it). |
| `deploy_decision` | `deploy` \| `reuse` \| `calculator-only` (\| `deploy(dry-run)`). How this round got its numbers. |
| `headline` | Small numeric snapshot used for cross-round deltas — `extrapolated_monthly_usd`, `calculator_monthly_usd`, `hot_pattern_throttles{}`, `p99_ms_by_pattern{}`, `max_gsi_amplification`, `top_key_share_by_pattern{}`. Deliberately scalars, not the full summary. |
| `delta_vs_prev` | Computed at write time against the previous round's `headline` — `monthly_usd_pct`, `throttle_delta{}`, `p99_delta_ms{}`, `gsi_amp_delta`. `null`/empty on round 0. |
| `finding_signals` | The set of `signal` strings from this round's `design_findings.json` — enough to see the trajectory ("`key_skew_patterns` gone after sharding") without re-reading each findings file. |
| `user_decision` | Filled at the START of the next round by the agent: what the user chose for THIS round's findings ("sharded PK on W1", "no change — accepted as deviation"). Closes the human-driven loop and is the paper trail for Artifact #5 deviations. |

## How the loop uses it

- **Reuse vs redeploy:** `iterate_design.py` compares the new design's fingerprint to `current_schema_fingerprint`. Unchanged + active manifest → `reuse` (no redundant tables, no orphans). Key/GSI/stream change → `deploy` (gated by `--yes-deploy`; the agent surfaces that the prior `teardown.sh` should run first). RPS/item-size-only change → `reuse`.
- **Deltas:** the agent reads the last two rounds' `headline` (or just `delta_vs_prev`) to report whether a change helped — the core of "feedback the user iterates on."
- **Decisions:** before applying the next change, the agent records what the user decided for the prior round in `user_decision`.
