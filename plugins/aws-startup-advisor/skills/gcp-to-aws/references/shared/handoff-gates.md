# Handoff Gates (Fail Closed)

All phases MUST pass a handoff gate before marking `phases.<phase>` as `"completed"` in `.phase-status.json`. Load this file when executing any phase completion step.

---

## Gate protocol

1. **Re-read from disk** — Open each required artifact with the Read tool from `$MIGRATION_DIR/`. Do not rely on chat memory or prior summaries.
2. **Check every item** in the phase-specific checklist (defined in that phase's orchestrator or sub-file).
3. **On failure** — emit exactly one line per failure using the parseable format below. Do **NOT** mark the phase complete. Do **NOT** advance `current_phase`.
4. **On success** — emit one success line, then update `.phase-status.json` in the same turn.

### Parseable failure format (required)

```
GATE_FAIL | phase=<discover|clarify|design|estimate|generate> | field=<dotted.path> | reason=<missing|invalid|stale_downstream>
```

Examples:

```
GATE_FAIL | phase=estimate | field=recommendation.path | reason=missing
GATE_FAIL | phase=clarify | field=design_constraints.availability.value | reason=missing
GATE_FAIL | phase=discover | field=preferences.json | reason=stale_downstream
```

### Success format (required)

```
HANDOFF_OK | phase=<phase> | artifacts=<comma-separated list of key files verified>
```

Example:

```
HANDOFF_OK | phase=estimate | artifacts=estimation-infra.json
```

---

## On GATE_FAIL — user action only (CRITICAL)

When any gate check fails:

1. Output the `GATE_FAIL` line(s) to the user in plain language (what is missing and which phase to re-run).
2. **Do NOT modify artifacts** to pass the gate (no inventing `recommendation`, no defaulting `availability`, no patching JSON inline).
3. **Do NOT continue** to the next phase.
4. Tell the user: **"Re-run Phase N (phase name) to produce the missing field, then continue."**

Patching artifacts to satisfy a gate defeats fail-closed validation and produces reports that look complete but are not.

---

## Decide-complete is terminal, not a failure

`current_phase: "complete"` + `run_mode: "decide"` + `phases.generate: "pending"` is a **valid terminal state** (the user stopped at the decision — see `schema-phase-status.md`). It is Estimate's `HANDOFF_OK` outcome, not a `GATE_FAIL`, not an inconsistent ordering, and not an incomplete run to repair. Do not "fix" it by advancing to Generate; the only valid transition out is the decide-complete resume offer (SKILL.md state machine).

## Phase re-entry (idempotent runs)

| Situation                                            | Rule                                                                                                                                                                  |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Re-run **Discover** after **Clarify** completed      | **STOP** unless user explicitly confirms. Emit `GATE_FAIL \| phase=discover \| field=preferences.json \| reason=stale_downstream`. Downstream artifacts may be stale. |
| Re-run **Clarify** after **Design** completed        | Same — confirm with user; Design/Estimate may need re-run.                                                                                                            |
| Re-run **Estimate** after **Generate** started       | Same — confirm with user; report and Terraform may be stale.                                                                                                          |
| Re-run a phase **before** downstream phase completed | Allowed. Overwrite that phase's artifacts; downstream phases remain `"pending"` or must be re-run.                                                                    |

When user confirms intentional re-run: set downstream phases back to `"pending"` in `.phase-status.json` before proceeding.

---

## Phase-specific checklists (summary)

Detailed checklists live in each phase file. Minimum gates:

| Phase        | Key checks                                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------------------- |
| **discover** | At least one discovery artifact; `migration-preview.json` when any artifact exists; route output gates (existing) |
| **clarify**  | `preferences.json` valid; Cloud SQL in inventory → `design_constraints.availability.value` set                    |
| **design**   | Active route artifacts present (existing gates)                                                                   |
| **estimate** | Active route artifacts present; infra route → `recommendation.path` + non-empty `migrate_if` / `stay_if`          |
| **generate** | Load `shared/validate-artifacts.md` before report; report pre-write sanity (see `generate-artifacts-report.md`)   |

---

## Orchestrator rule (SKILL.md)

The top-level skill MUST NOT load the next phase until the previous phase's output includes `HANDOFF_OK | phase=<previous>`. A phase completion message without `HANDOFF_OK` is not valid handoff.
