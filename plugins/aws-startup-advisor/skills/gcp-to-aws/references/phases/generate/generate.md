# Phase 5: Generate Migration Artifacts (Orchestrator)

> **CONSENT GUARD (check before Step 1):** This phase runs only by explicit
> opt-in. If `.phase-status.json` → `run_mode` is not `"decide_and_execute"`:
> when this turn's user message is an explicit Execute request ("generate the
> Terraform", "create the migration scripts", gate choice C), set
> `run_mode: "decide_and_execute"` (read-merge-write) and proceed; otherwise
> STOP — do not generate anything — and re-present the Decision gate (or the
> decide-complete resume offer) from `estimate.md` / `SKILL.md`.

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

The Generate phase has **2 mandatory stages** that run sequentially:

1. **Stage 1: Migration Planning** — Produces execution plans (JSON) from estimation + design artifacts
2. **Stage 2: Artifact Generation** — Produces deployable code (Terraform, scripts, adapters, docs) from plans + designs

Both stages must complete for the phase to succeed.

## Prerequisites

1. Read `$MIGRATION_DIR/.phase-status.json`. If missing, invalid, or `phases.clarify` is not exactly `"completed"`: **STOP**. Output: "Phase 2 (Clarify) not completed or phase state is missing/invalid. Complete Clarify before Generate."
2. Read `$MIGRATION_DIR/preferences.json`. If missing: **STOP**. Output: "Phase 2 (Clarify) not completed. Run Phase 2 first."

Check which estimation artifacts exist in `$MIGRATION_DIR/`:

- `estimation-infra.json` (infrastructure estimation)
- `estimation-ai.json` (AI workload estimation)
- `estimation-billing.json` (billing-only estimation)

If **none** of these estimation artifacts exist: **STOP**. Output: "No estimation artifacts found. Run Phase 4 (Estimate) first."

## Stage 1: Migration Planning

**Dirty-state tracking**: Before producing any Stage 1 outputs, set `dirty_state` in `.phase-status.json`:

```json
"dirty_state": {
  "phase": "generate",
  "stage": "stage_1_planning",
  "started_at": "<ISO 8601 UTC>",
  "partial_outputs": [],
  "missing_outputs": ["generation-infra.json", "generation-ai.json", "generation-billing.json"]
}
```

Trim `missing_outputs` to only the artifacts expected for the active routes. Update `partial_outputs` and `missing_outputs` after each sub-file completes.

Route based on which estimation artifacts exist. Multiple paths can run independently.

### Infrastructure Migration Plan

IF `estimation-infra.json` exists:

> Load `generate-infra.md`

Produces: `generation-infra.json`

### AI Migration Plan

IF `estimation-ai.json` exists:

> Load `generate-ai.md`

Produces: `generation-ai.json`

### Billing-Only Migration Plan

IF `estimation-billing.json` exists:

> Load `generate-billing.md`

Produces: `generation-billing.json`

## Stage 2: Artifact Generation

**MUST proceed only after Stage 1 completes.** Route based on generation plans + design artifacts.

**Dirty-state tracking**: Before producing any Stage 2 outputs, update `dirty_state` in `.phase-status.json`:

```json
"dirty_state": {
  "phase": "generate",
  "stage": "stage_2_artifacts",
  "started_at": "<ISO 8601 UTC>",
  "partial_outputs": ["generation-infra.json"],
  "missing_outputs": ["terraform/", "scripts/", "MIGRATION_GUIDE.md", "README.md"]
}
```

Carry forward `partial_outputs` from Stage 1. Trim `missing_outputs` to only the artifacts expected for the active routes plus mandatory docs. Update after each sub-file completes.

### Infrastructure Artifacts

IF `generation-infra.json` AND `aws-design.json` exist:

> Load `generate-artifacts-infra.md`

Produces: `terraform/` directory

After generate-artifacts-infra.md completes (terraform files generated),
load `generate-artifacts-scripts.md` to generate migration scripts.

Produces: `scripts/` directory

### AI Artifacts

IF `generation-ai.json` AND `aws-design-ai.json` exist:

> Load `generate-artifacts-ai.md`

Produces: `ai-migration/` directory

### Billing Skeleton Artifacts

IF `generation-billing.json` AND `aws-design-billing.json` exist:

> Load `generate-artifacts-billing.md`

Produces: `terraform/skeleton.tf` (with TODO markers)

### Documentation (ALWAYS runs after artifact generation)

AFTER all above artifact generation sub-files complete:

> Load `generate-artifacts-docs.md`

Produces: `MIGRATION_GUIDE.md`, `README.md`

### HTML Report (ALWAYS runs last, after documentation)

AFTER generate-artifacts-docs.md completes:

> Load `generate-artifacts-report.md`

Produces: `migration-report.html`

**Validation gate:** Report generation runs `shared/validate-artifacts.md` first. If validation emits `GATE_FAIL`: log the failure to the user, **do not write** `migration-report.html`, and continue to Phase Completion (report is optional output; validation failure is not a silent skip). Do **NOT** patch artifacts to pass validation.

After writing `migration-report.html`, run `shared/validate-migration-report.md` (automated script). Branch on the shell exit code per that doc's table — `0` (`REPORT_OK`), `1` (`REPORT_FAIL`: remove or rename incomplete HTML and warn the user — do not present a stub report as complete), or anything else (validator did not run, e.g. `python3` missing — tell the user validation was skipped, do not treat it as pass or fail).

## Phase Completion

Load `shared/handoff-gates.md`. **Re-read from disk** before checking.

Verify both stages are complete:

1. **Stage 1 route gates (fail closed)**:
   - If `estimation-infra.json` exists -> require `generation-infra.json`
   - If `estimation-ai.json` exists -> require `generation-ai.json`
   - If `estimation-billing.json` exists -> require `generation-billing.json`
2. **Stage 2 route gates (fail closed)**:
   - If infra artifact route is active (`generation-infra.json` AND `aws-design.json`) -> require `terraform/`, `scripts/`, and `validation-report.json` (with `status` in `{passed, passed_degraded_offline, skipped_user_continue}` AND `policy_status` == `POLICY_OK`, unless the user chose skip/abort on a policy failure)
   - If AI artifact route is active (`generation-ai.json` AND `aws-design-ai.json`) -> require `ai-migration/`
   - If billing artifact route is active (`generation-billing.json` AND `aws-design-billing.json`) -> require `terraform/skeleton.tf`
3. **Documentation gate (always)**:
   - Require `MIGRATION_GUIDE.md` and `README.md`
4. If any active route is missing expected outputs: Emit `GATE_FAIL | phase=generate | field=<artifact> | reason=missing`. **Do NOT modify artifacts.** STOP — do not mark phase complete.

**On PASS:** Emit `HANDOFF_OK | phase=generate | artifacts=<key files verified>`.

After `HANDOFF_OK`, use the Phase Status Update Protocol (read-merge-write) to update `.phase-status.json` — **in the same turn** as the summary below:

- Set `phases.generate` to `"completed"`
- Set `current_phase` to `"complete"`

## Summary

**Use structured completion reporting** in the shape below. Present final summary to user:

```
Phase 5 (Generate) complete.

✓ Produced:
  - generation-infra.json: [X]-week migration plan
  - terraform/: [N] files (list key files)
  - scripts/: [N] files
  - MIGRATION_GUIDE.md: [N] sections
  - README.md: artifact catalog + quick start
  - migration-report.html: executive summary
  - migration-report.pdf: PDF version [or "skipped — no converter available"]

⊘ Skipped (not applicable):
  - [artifact]: [reason]

⚠ Skipped (non-blocking failure):
  - migration-report.html: [failure reason]  ← only if report generation failed
```

After the structured block, include:

1. **Plans generated** — List all `generation-*.json` files produced
2. **Artifacts generated** — List all directories and files created (terraform/, scripts/, ai-migration/, MIGRATION_GUIDE.md, README.md). Include `migration-report.html` only if it exists.
3. **Validation status** — If `$MIGRATION_DIR/validation-report.json` exists, report its `status` field (`passed`, `passed_degraded_offline`, or `skipped_user_continue`). If `status == "passed_degraded_offline"`, add: "Provider registry was unreachable; `terraform validate` was skipped. Re-run `terraform init && terraform validate` from a network-connected shell to complete validation." Also report `policy_status` (`POLICY_OK`/`POLICY_FAIL`) — the tf-best-practices policy gate runs regardless of the offline path and must report `POLICY_OK` before infra Generate completes (see `generate-artifacts-infra.md` Step 6).
4. **Key timelines** — Highlight migration timeline from the generation plans
5. **Key risks** — Highlight top risks from the generation plans
6. **TODO markers** — Note any TODO markers in generated artifacts that require manual attention
7. **Next steps** — Recommend reviewing generated artifacts, customizing TODO sections, and beginning migration execution

Output to user:

- If `migration-report.html` exists: "Phase 5 of 6 complete (Generate). All required phases of the GCP-to-AWS migration analysis are complete. Your migration report is ready at $MIGRATION_DIR/migration-report.html. Optional: Phase 6 (Feedback)."
- If `migration-report.html` is missing: "Phase 5 of 6 complete (Generate). All required phases of the GCP-to-AWS migration analysis are complete. Markdown documentation is available at $MIGRATION_DIR/MIGRATION_GUIDE.md and $MIGRATION_DIR/README.md. (HTML report generation is optional and non-blocking.) Optional: Phase 6 (Feedback)."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._
