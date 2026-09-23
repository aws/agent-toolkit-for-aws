---
_assemble: assemble-design
_of_phase: design
_reads:
  - mapping-engine (fragment contribution)
  - eks-mapping (fragment contribution, when EKS selected)
_produces:
  - aws-design.json
---

# Design — Assemble and Validate aws-design.json

> **Assembler unit.** Runs after the mapping fragments (`design-mapping.md`, and
> `design-eks.md` when EKS is selected) have populated the in-memory design object.
> It writes the final `aws-design.json`, runs the output route gates + completion
> handoff gate, and updates `.phase-status.json`. It owns the artifact-level
> contract for this phase (its postconditions ARE the handoff gate).

---

## Step 6: Write `aws-design.json`

Write the completed design object to `$MIGRATION_DIR/aws-design.json`. The written
artifact's structure (valid JSON; `services[]` or `deferred[]` non-empty;
`vpc_design` present; per-entry required fields) is validated by the Completion
Handoff Gate below (this phase's `_postconditions`, re-read from disk).

---

## Step 7: Check Outputs

**Route output gates (fail closed):**

- If inventory had formation resources → `services[]` MUST contain at least one Elastic Beanstalk, Fargate, or EKS entry (unless all dyno types were unrecognized or all formations were `release` processes).
- If inventory had `heroku-postgresql` add-ons with recognized plans → `services[]` MUST contain RDS or Aurora entries.
- If inventory had `heroku-redis` add-ons with recognized plans → `services[]` MUST contain ElastiCache entries.
- If inventory had `heroku-kafka` add-ons with recognized plans → `services[]` MUST contain MSK entries.
- If inventory had pipelines → `warnings[]` MUST contain pipeline detect-only warnings.

---

## Completion Handoff Gate (Fail Closed)

The completion checks are declared in this phase's `_postconditions` frontmatter and
enforced per `INTERPRETER.md` § Gate protocol: re-read `aws-design.json` from disk, run
the mechanical checks (`_check_file_exists` / `_validate_json`) and the `_assert`
judgment checks (phase/timestamp/services shape, per-entry required fields, vpc_design
mode, total_services match, no Fir-specific Terraform), plus the route output gates from
Step 7, then emit `GATE_FAIL` (STOP; do not patch artifacts) or
`HANDOFF_OK | phase=design | artifacts=aws-design.json` and advance.

---

## Step 8: Update Phase Status and Hand Off

> **Inner workshop reprice:** When Design is invoked from
> `workshop-refresh.md`, stop after writing `aws-design.json` (and soft
> validation). Skip this Step 8 and do **not** emit `HANDOFF_OK` — see
> `workshop-refresh.md` § Inner runs.

Only after `HANDOFF_OK`, apply the phase-status update protocol (`INTERPRETER.md` § The interpreter loop) — mark `phases.design` completed and advance per `_advances_to` — in the **same turn** as the output message below.

Output to user — build message from design contents:

- "Designed X AWS services across Y apps."
- If deferred add-ons: "Deferred N add-on(s) to specialist engagement."
- If Fir detected: "Fir-generation workloads noted as deferred (detect-only)."
- If pipeline warnings: "N pipeline(s) detected (CI/CD requires manual config)."
- VPC mode: "VPC design: [existing VPC referenced | new VPC generated with N subnets]."

Format: "Phase 3 of 6 complete (Design). [artifact summaries] Remaining: Estimate → Generate (+ optional Feedback). Next required step: Phase 4 — Estimate. Load `references/phases/estimate/estimate.md` now."

---

## Output Files

This phase's artifacts are declared in `_produces` (`aws-design.json`; `.phase-status.json` is updated per Step 8) and its scope boundary (files it must NOT create) in `_forbids_files`. All user communication is via output messages only (no report/summary files).

---

## Error Handling

Non-fatal mapping errors and their handling (fatal predecessor/input/gate failures are handled by `_preconditions`/`_postconditions` + `INTERPRETER.md` § `_on_error`):

| Error Category                         | Behavior                                        |
| -------------------------------------- | ----------------------------------------------- |
| Unrecognized dyno type                 | Reject formation, add warning, continue         |
| Empty Procfile (no process types)      | Reject app formations, add warning, continue    |
| Unrecognized Postgres/Redis/Kafka plan | Defer to specialist gate, add warning, continue |
| Unrecognized availability preference   | Default to `multi-az` + RDS + warning, continue |
| Add-on not in Fast-Path Table          | Specialist gate (deferred), continue            |
| Partial match on Fast-Path Table       | Specialist gate (NOT a match), continue         |

A no-services-and-no-deferred outcome is an unrecoverable error and a failing handoff gate halts per the gate protocol (`INTERPRETER.md` § `_on_error`); do not patch artifacts to force a pass.
