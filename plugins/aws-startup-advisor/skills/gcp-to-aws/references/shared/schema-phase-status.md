# .phase-status.json

Lightweight phase tracking. This is the SINGLE source of truth for the `.phase-status.json` schema. All steering files reference this definition.

```json
{
  "migration_id": "0226-1430",
  "run_id": "[random UUID, written once at creation]",
  "owning_skill": "GCP_TO_AWS",
  "last_updated": "2026-02-26T15:35:22Z",
  "current_phase": "design",
  "phases": {
    "discover": "completed",
    "clarify": "completed",
    "design": "in_progress",
    "estimate": "pending",
    "workshop": "pending",
    "generate": "pending",
    "feedback": "pending"
  }
}
```

**Field Definitions:**

| Field           | Type     | Set When                                                                                                                       |
| --------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `migration_id`  | string   | Created (matches folder name, never changes)                                                                                   |
| `run_id`        | UUID     | Created (random, from `uuidgen`; never changes or is reused). The run's identifier for telemetry and the plugin-to-web handoff |
| `owning_skill`  | string   | Created (`GCP_TO_AWS`; never changes). Telemetry attributes the run to it                                                      |
| `initiated_by`  | string   | Created, only when another skill started the run (e.g. `LLM_TO_BEDROCK`); otherwise absent                                     |
| `last_updated`  | ISO 8601 | After each phase update                                                                                                        |
| `current_phase` | string   | After each phase update: the next phase to run, or `complete`; authoritative when present                                      |
| `phases.<name>` | string   | Phase transitions: `"pending"` → `"in_progress"` → `"completed"`                                                               |

**Optional field — `run_mode`:**

| Value                  | Meaning                                                                         | Set by                                                      |
| ---------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `"decide"`             | User stopped at the decision — Generate available on request, never auto-loaded | Decision gate choice A (`estimate.md`)                      |
| `"decide_and_execute"` | User opted into execution artifacts — Generate may load                         | Decision gate choice C, or the decide-complete resume offer |
| _(absent)_             | Gate not yet reached — no Generate consent exists                               | —                                                           |

**Decide-complete state:** `current_phase: "complete"` + `run_mode: "decide"` + `phases.generate: "pending"` means the decision pack is done and execution was not requested. This is a **terminal-unless-asked** state, not a failure and not an incomplete run: resume offers Generate but never auto-runs it, and never re-runs Estimate. No `"skipped"` status exists — `generate` simply stays `"pending"`.

**Rules:**

- Phase status progresses: `"pending"` → `"in_progress"` → `"completed"`. Never goes backward.
- Valid phase names: discover, clarify, design, estimate, workshop, generate, feedback.
- `workshop` is an optional **sidebar** (like feedback): never appears as
  `current_phase`; `"completed"` means resolved (entered or declined).
- `migration_id` matches the `$MIGRATION_DIR` folder name (e.g., `0226-1430`).
- `run_id` and `owning_skill` are written once when the run is created and never change; `initiated_by` is optional and set only when another skill started the run.
- `run_mode` is optional; when present it must be `"decide"` or `"decide_and_execute"`. It is flow state (Generate consent), not a design constraint — it never appears in `preferences.json`.
