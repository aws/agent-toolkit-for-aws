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
| Enter **Generate** with a declared compliance framework but no `security_baseline_compliance` line in `estimation-infra.json` | **STOP** unless user explicitly confirms. Emit `GATE_FAIL \| phase=generate \| field=estimation-infra.json.projected_costs.breakdown.security_baseline_compliance \| reason=stale_downstream`. Estimate ran before the compliance answer was applied — budget and report totals would understate. |
| Re-run a phase **before** downstream phase completed | Allowed. Overwrite that phase's artifacts; downstream phases remain `"pending"` or must be re-run.                                                                    |

When user confirms intentional re-run: set downstream phases back to `"pending"` in `.phase-status.json` before proceeding.

**Retire stale route artifacts on a confirmed re-entry that CHANGES which route is active
(CRITICAL — not just resetting phase status).** Every downstream phase (`design.md`,
`estimate.md`, `generate.md`) selects its route by **file existence**
(`aws-design-billing.json` exists AND `aws-design.json` does not, etc.), not by reading
`.phase-status.json`'s phase flags. Resetting those flags to `"pending"` does NOT remove the
actual artifact files on disk — so if the re-run's new discovery output no longer supports a
route the PREVIOUS run activated (e.g. a working billing export is replaced by an
unrecognized one, turning `billing-profile.json` into a skip record), the old route's
artifacts (`aws-design-billing.json`, `estimation-billing.json`, `generation-billing.json`,
and any generated billing skeleton) are still present when Design/Estimate/Generate re-run,
and get silently re-selected and combined with the NEW run's other artifacts. Before
proceeding on a confirmed re-entry:

1. Determine which routes were active in the artifacts already on disk (infra: `aws-design.json`;
   billing-only: `aws-design-billing.json` with `aws-design.json` absent; AI: `aws-design-ai.json`).
2. Re-evaluate which routes the NEW discovery output supports, using the SAME rules
   `design.md`'s Routing Rules section uses (e.g. billing-only requires `billing-profile.json`
   with non-empty `services[]`).
3. For any route that was active before but is NOT supported by the new discovery output,
   **delete that route's downstream artifacts** — its `aws-design-*.json`,
   `estimation-*.json`, `generation-*.json`, and any generated skeleton/Terraform for that
   route — before Design re-runs. Do not merely reset the phase flag; the file must actually
   be gone, since every downstream phase trusts the file's existence over the phase flag.
4. Tell the user which artifacts were retired and why ("your billing export is no longer
   recognized, so the billing-only design/estimate from your previous run has been removed —
   re-run Design to pick up the new discovery output").

---

## Phase-specific checklists (summary)

Detailed checklists live in each phase file. Minimum gates:

| Phase        | Key checks                                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------------------- |
| **discover** | At least one discovery artifact; `migration-preview.json` when any artifact exists; route output gates (existing) |
| **clarify**  | `preferences.json` valid; Cloud SQL in inventory → `design_constraints.availability.value` set                    |
| **design**   | Active route artifacts present (existing gates)                                                                   |
| **estimate** | Active route artifacts present; infra route → `recommendation.path` + non-empty `migrate_if` / `stay_if`          |
| **generate** | Load `shared/validate-artifacts.md` before report; report pre-write sanity (see `generate-artifacts-report.md`); compliance-estimate staleness guard (see `generate.md` Prerequisites) |

---

## Orchestrator rule (SKILL.md)

The top-level skill MUST NOT load the next phase until the previous phase's output includes `HANDOFF_OK | phase=<previous>`. A phase completion message without `HANDOFF_OK` is not valid handoff.
