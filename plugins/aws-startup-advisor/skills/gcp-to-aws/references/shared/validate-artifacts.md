# Validate Artifacts (Pre-Report)

> **Read-only validation.** Load at the start of `generate-artifacts-report.md` (Step 0) and before writing `migration-report.html`. Do NOT modify artifacts during this step.

On any failure: emit `GATE_FAIL` per `shared/handoff-gates.md`, skip report generation, tell the user which phase to re-run. **Do NOT patch JSON to pass validation.**

---

## How to run

1. Read each file below from `$MIGRATION_DIR/` using the Read tool.
2. Mark each check PASS or FAIL based on file contents (not memory).
3. If **any required** check FAILs → stop; do not write `migration-report.html`.
4. If all required checks PASS → proceed to report generation.

Optional checks: skip section in report if FAIL (do not halt).

---

## Required checks (max 15 — halt report on FAIL)

| #  | Check                   | PASS when                                                                                                                                                                        | On FAIL                                                                                       |
| -- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1  | Estimation exists       | At least one of `estimation-infra.json`, `estimation-ai.json`, `estimation-billing.json` exists                                                                                  | `GATE_FAIL \| phase=generate \| field=estimation-* \| reason=missing` — re-run Estimate       |
| 2  | Design exists           | At least one of `aws-design.json`, `aws-design-ai.json`, `aws-design-billing.json` exists                                                                                        | `GATE_FAIL \| phase=generate \| field=aws-design-* \| reason=missing` — re-run Design         |
| 3  | Preferences             | `preferences.json` exists and parses as JSON                                                                                                                                     | `GATE_FAIL \| phase=generate \| field=preferences.json \| reason=missing` — re-run Clarify    |
| 4  | Recommendation (infra)  | If `estimation-infra.json` exists: `recommendation.path` ∈ `{migrate_optimized, migrate_phased, stay}`                                                                           | `GATE_FAIL \| phase=estimate \| field=recommendation.path \| reason=missing`                  |
| 5  | Recommendation lists    | If `estimation-infra.json` exists: `migrate_if` and `stay_if` are non-empty arrays                                                                                               | `GATE_FAIL \| phase=estimate \| field=recommendation.migrate_if \| reason=missing`            |
| 6  | Preview complexity      | If `migration-preview.json` exists: `complexity_signal` is present                                                                                                               | `GATE_FAIL \| phase=discover \| field=complexity_signal \| reason=missing`                    |
| 7  | Cloud SQL availability  | If `gcp-resource-inventory.json` contains `google_sql_database_instance` AND `estimation-infra.json` exists: `preferences.json` → `design_constraints.availability.value` is set | `GATE_FAIL \| phase=clarify \| field=design_constraints.availability.value \| reason=missing` |
| 8  | AI profile consistency  | If `aws-design-ai.json` exists → `ai-workload-profile.json` exists                                                                                                               | `GATE_FAIL \| phase=discover \| field=ai-workload-profile.json \| reason=missing`             |
| 9  | Generation plan (infra) | If `estimation-infra.json` exists → `generation-infra.json` exists                                                                                                               | `GATE_FAIL \| phase=generate \| field=generation-infra.json \| reason=missing`                |
| 10 | Docs                    | `MIGRATION_GUIDE.md` and `README.md` exist                                                                                                                                       | `GATE_FAIL \| phase=generate \| field=MIGRATION_GUIDE.md \| reason=missing`                   |

---

## Optional checks (do not halt — omit report sections)

| #  | Check                   | If FAIL                                                                                                                                                                        |
| -- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 11 | AI generation plan      | If `estimation-ai.json` exists but not `generation-ai.json` → omit Appendix D.5                                                                                                |
| 12 | Startup credits         | If no `STARTUP_PROGRAMS.md` and no `startup_program_status` in preferences → omit tier-specific credits callout                                                                |
| 16 | Startup program honesty | When `startup_program_status.value == "unknown"`, run `python3 scripts/validate-startup-program-artifacts.py --migration-dir $MIGRATION_DIR` — must exit 0 before `HANDOFF_OK` |
| 13 | Bedrock monitoring      | If `ai-migration/setup_bedrock.sh` is missing or lacks its budget and anomaly step → omit Bedrock anomaly row                                                                  |
| 14 | Observability breakdown | If no observability key in `projected_costs.breakdown` → omit observability note                                                                                               |
| 15 | Deferred services       | If no `Deferred — specialist engagement` in design → omit deferred callout                                                                                                     |

---

## Pre-write sanity (repeat immediately before HTML write)

After building report content in memory, re-read from disk and confirm these **three** checks (defense in depth — context may drift during long Generate):

1. `estimation-infra.json` → `recommendation.path_label` OR fallback documented in Step 1 is available for Section 0.
2. `migration-preview.json` → `complexity_signal` present (if file exists).
3. Planned HTML includes `<section id="decision-summary">` — see `generate-artifacts-report.md` HTML skeleton.

If any pre-write check fails: do not write the file; emit `GATE_FAIL` and stop.

---

## Output when all required checks pass

```
VALIDATE_OK | checks=10/10 | ready=migration-report.html
```

Then proceed to `generate-artifacts-report.md` Step 1.
