# Phase 5: Generate Migration Artifacts (Orchestrator)

## Telemetry boundary

Load `references/vendored/telemetry/PROTOCOL.md` from the GCP skill root, including
when this phase is executed inline by another skill. In `cli` mode, reconcile
after each persisted `.phase-status.json` update and before waiting, returning,
or advancing, including the final completion write. In `hook` mode, leave
reporting to the configured hooks.

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

**Compliance-estimate staleness guard.** When `estimation-infra.json` exists, read
`preferences.json` → `design_constraints.compliance.value` (absent / `none` / `unknown` →
treat as no gating framework declared) and check whether it contains any of `soc2`, `pci`,
`hipaa`, `fedramp` — the same gating set `generate-artifacts-infra.md` uses to decide whether
`baseline.tf` emits the Config + Security Hub compliance controls. If it does,
`estimation-infra.json` → `projected_costs.breakdown` MUST already contain a
`security_baseline_compliance` entry (added whenever Estimate ran with the compliance answer
correctly read). If that entry is **missing** — a run whose Estimate saw an empty/absent
compliance value even though Clarify recorded a gating framework, most likely because
Estimate ran before the `design_constraints.compliance.value` reader fix — the budget and
report totals downstream would **understate**: Generate would still correctly emit the
compliance controls in `baseline.tf` (it reads the same field, already correct), but their
cost would be silently absent from `aws_budgets_budget.limit_amount` and every report cost
table. **STOP.** Emit `GATE_FAIL | phase=generate | field=estimation-infra.json.projected_costs.breakdown.security_baseline_compliance | reason=stale_downstream`.
Tell the user: "Your declared compliance requirement ([frameworks]) will add AWS Config and
Security Hub controls to the generated Terraform, but the cost estimate on file was computed
before that requirement was applied — it's missing that line item, so your budget and report
totals would understate the real cost. Re-run Phase 4 (Estimate) to refresh it, then come
back to Generate." **Do NOT** patch `estimation-infra.json` to add the missing entry, and do
NOT proceed to Stage 1 — per `shared/handoff-gates.md`'s re-entry protocol, this is a
user-confirmed re-run, not a silent repair. If the user confirms, set `phases.estimate` (and
`phases.generate`, if not already `"pending"`) back to `"pending"` before re-running Estimate.

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

After writing `migration-report.html`, run `shared/validate-migration-report.md` (automated script). `REPORT_OK` means the decision-core content checks passed, not that the section IDs alone were present — the HTML must still have been rendered from `references/shared/report-decision-core.md`. Branch on the shell exit code per that doc's table — `0` (`REPORT_OK`), `1` (`REPORT_FAIL`: remove or rename incomplete HTML and warn the user — do not present a stub report as complete), or anything else (validator did not run, e.g. `python3` missing — tell the user validation was skipped, do not treat it as pass or fail).

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

**Write the web-handoff summary (fail-open):** run
`python3 "$PLUGIN_ROOT/scripts/emit-plan-json.py" --migration-dir "$MIGRATION_DIR" --plugin-json "$PLUGIN_ROOT/.claude-plugin/plugin.json"`
(absolute paths — cwd must not be load-bearing). It reads the estimate artifacts and writes `$MIGRATION_DIR/plan.json`, the uploadable handoff file, printing `PLAN_OK | …` or `PLAN_SKIP | reason=…`. This is an optional enhancement, never a gate: on any skip or error the migration is still complete — continue without it and do not surface the script output to the user. When it printed `PLAN_OK`, present the web-handoff block described after the Output section below.

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

**Web-handoff — only when the writer above printed `PLAN_OK`** (if it printed `PLAN_SKIP`, omit this whole block; there is no file to upload). Do three things, in order:

- **(a)** In the `✓ Produced` list in the Summary above, add exactly one entry as **plain text** — that list renders inside a code block, where Markdown links do not work, so do not link it here (the clickable link is the What's next call-to-action below): `plan.json — upload to AWS Startups Migrate to see if you qualify for AWS credits`. Keep every existing entry on its own line; do not merge, collapse, or re-wrap them.
- **(b)** Then show the user their `plan.json`. The `.migration` folder is hidden by default
  on macOS and Linux, so open the file's location for them instead of leaving them
  to find it. Run the command for the user's OS once, as an ordinary command — the
  agent's own permission prompt is the user's choice, so do not ask separately
  first:

  - macOS: `open -R "$MIGRATION_DIR/plan.json"` — opens Finder with the file
    selected, even inside the hidden folder.
  - Windows: `MSYS_NO_PATHCONV=1 explorer.exe /select,"<absolute Windows path to plan.json>"`
    — the prefix stops Git Bash from rewriting `/select,` as a path (drop it in
    PowerShell or cmd). In Git Bash, get the Windows path with
    `cygpath -w "$MIGRATION_DIR/plan.json"`. `explorer.exe` exits non-zero even
    when it succeeds, so treat it as opened unless it prints an error.
  - Linux: `xdg-open "$MIGRATION_DIR"` — opens the folder (it cannot select the
    file).

  Then show exactly ONE of the two messages below, as plain text (not in a code
  block). Do not reword them — this copy is owned by the web experience.

  If the folder opened:

  > **The folder is open with your plan.json selected.**

  On Linux, where the file cannot be selected, show **The folder with your
  plan.json is open.** instead.

  If the command failed, was not available, or the user declined it, show this
  as its own message, separate from the phase summary, and do not add any other
  explanation of why it did not open. Replace `<absolute path to plan.json>`
  with the real absolute path:

  > The folder did not open. The open command is blocked in your permissions.
  >
  > Your plan.json is saved at:
  > `<absolute path to plan.json>`
  >
  > The .migration folder is hidden by default on macOS. In Finder, press Command + Shift + Period (.) to show it.

  On Linux, use this last line instead: "The .migration folder is hidden by
  default on Linux. In your file manager, press Ctrl + H to show it." On Windows,
  the folder is not hidden, so omit the last line.

  Adjust only the first line: if the migration report also failed to open, start
  with "The report and the folder did not open." instead; keep "The open command
  is blocked in your permissions." only when a permission rule blocked it, and
  drop that sentence when the user declined or the command failed for another
  reason.

- **(c)** Then append the What's next block below, verbatim, replacing `<run_id>` in the link with the run's `run_id` (from `.phase-status.json`), lowercased if it is a UUID so the `run=` value matches the plan's `runId`. It MUST begin with the "💬 What's next" heading. The call-to-action must be a Markdown link so it renders as clickable text with no bare URL. Do not reword it — this copy is owned by the web experience:

> **💬 What's next**
>
> - **Refine your plan**
>   Tell me what to change. For example: "use Fargate instead," "make it multi-region," or "reduce the cost."
> - **See your AWS credits**
>   Sign in or create an account on AWS Startups Migrate, then upload plan.json to see the AWS migration credits you qualify for.
>
> [Go to AWS Startups Migrate →](https://startups.aws.com/startups/en-US/migrate/credits?source=plugin&run=<run_id>)
>
> After you upload, you also get:
>
> - Interactive plan dashboard
> - Monthly cost estimate
> - Migration paths: AI agent, AWS expert, or AWS Partner

Ship note: this reaches customers only after the import page and the ImportPlan API are both live in production.

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._
