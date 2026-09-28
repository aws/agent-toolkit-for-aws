---
_assemble: assemble-generation
_of_phase: generate
_reads:
  - terraform (fragment contribution)
  - docs (fragment contribution)
  - report (fragment contribution)
  - eks-generate (fragment contribution, when EKS in design)
_produces:
  - generation-warnings.json
  - validation-report.json
---

# Generate — Validate and Assemble

> **Assembler unit.** Runs after the generation fragments (`generate-terraform.md`,
> `generate-docs.md`, `generate-report.md`, and `generate-eks.md` when EKS is in
> the design) have written their artifacts. It runs the cross-artifact validation
> (every-service-generated-or-warned, reference integrity, no `{{VAR}}` leak) and
> emits the handoff signal, then updates `.phase-status.json` in Step 4. The
> report validator itself runs later, in the main-window "Finish Generate" step
> (this assembler is dispatched and has no shell). It owns the phase's final
> artifact-level contract.

---

## Step 3: Validate Complete Artifact Set

The full generated artifact set (core terraform files + MIGRATION_GUIDE.md +
README.md + migration-report.html + generation-warnings.json) is gate-checked by
this phase's `_postconditions` (see the Completion Handoff Gate below). This
assembler adds the cross-artifact checks that span multiple fragment outputs:

**Cross-reference checks:**

- Every service in `aws-design.json.services[]` is either generated in Terraform OR listed in `generation-warnings.json`
- If any service has `aws_service: "EKS"` → `terraform/eks.tf` must exist AND `kubernetes/` directory must contain at least one Deployment manifest
- If any service has `aws_service: "Elastic Beanstalk"` → `terraform/beanstalk.tf` must exist, plus the selected EB deploy artifact (`.github/workflows/deploy-eb.yml` for `github_actions`, `terraform/pipeline.tf` for `codepipeline`, none for `manual`)
- `README.md` references all files that actually exist
- `MIGRATION_GUIDE.md` data migration sections match design content (no empty sections)

**Authoritative Terraform policy check (after all Terraform producers):**

1. Invoke the `tf-best-practices` skill at its post-writing (Part 2) touchpoint
   against `$MIGRATION_DIR/terraform`, writing the checker output to the temporary
   `$MIGRATION_DIR/validation-report.policy.json` sidecar. This assembler runs
   after `eks-generate`, so the scan covers `eks.tf` and every other final `.tf`
   file. The scoped shell runs only that checker (`python3`/`uvx`), never `git`,
   network calls, or arbitrary commands.
2. On `POLICY_FAIL`, apply the `fix_hint`s to the named `.tf` sites and rerun the
   checker, up to the shared budget of three attempts.
3. Write `$MIGRATION_DIR/validation-report.json` in the v2 envelope from
   `$PLUGIN_ROOT/skills/tf-best-practices/references/terraform-validation.md`, preserving
   `status: "passed_degraded_offline"` and `offline_fallback_used: true` because
   this path does not run `terraform fmt/init/validate`. Merge the sidecar's
   `policy_status` into `policy_status` and its `violations[]` into
   `policy_violations[]`; never invent `POLICY_OK`.
4. Delete `validation-report.policy.json` after the merge. If no shell is
   available, write `policy_status: "not_run"` so `_postconditions` fails closed.

---

## Completion Handoff Gate (Fail Closed)

The completion checks are declared in this phase's `_postconditions` frontmatter and
enforced per `INTERPRETER.md` § Gate protocol: re-read the generated artifacts from
disk, run the mechanical checks (`_check_file_exists` for the core terraform files
including `baseline.tf` + MIGRATION_GUIDE.md + README.md + migration-report.html)
and the `_assert` judgment checks (valid provider / aws_region variable, a domain
.tf beyond core, security-baseline resource inventory + compliance-conditional
section + contact email variables, guide sections, report sections, conditional
Postgres/ Redis migration scripts, conditional EKS terraform + kubernetes
manifests, every service accounted for, no `{{VARIABLE}}` placeholders), then emit
`GATE_FAIL` (STOP) or
`HANDOFF_OK | phase=generate | artifacts=terraform/,MIGRATION_GUIDE.md,README.md,migration-report.html,validation-report.json`.

The report validator (**required, blocking**) runs in the **main window**, not here — this
assembler is dispatched to the shell-less `rw` worker along with the fragments (`INTERPRETER.md`
§ `_exec`), so it cannot run `python3`. `generate.md`'s "Finish Generate in the main window
(report validation)" step runs
`validate-heroku-migration-report.py` over `migration-report.html` **after this assembler
returns and before** the read-only `_postconditions` gate; on `REPORT_OK` it stamps
`report-validation-status.json` (the durable result the gate asserts), and on `REPORT_FAIL` it
emits `GATE_FAIL` and pastes the validator's `errors[]`. Per `INTERPRETER.md` § `_postconditions`,
the gate does **not** edit the HTML, artifacts, or state — it halts. Recovery is a hand-edit of
`migration-report.html` from the pasted errors + a direct re-run of the validator and re-stamp (or
a maintainer re-running Generate for a clean rebuild), not this assembler repairing the report.

The Terraform **policy gate** is not optional, and it is enforced by `generate.md`
`_postconditions` — a **read-only** gate the interpreter runs in the **main window**
(`INTERPRETER.md` § `_exec` step 4). The policy checker run, the budget-3 `.tf`
fix-and-retry loop, and the verdict write all happen **before** this gate in this
assembler, after every Terraform-producing fragment has finished. This is where
`terraform/` may be edited. By the time the gate runs, the retry budget is already
spent and `validation-report.json` covers the final Terraform directory. The gate only does
`_validate_json` + assert `policy_status == "POLICY_OK"`. If `validation-report.json` is
missing/invalid or its `policy_status` is `"POLICY_FAIL"` (or `not_run`), the gate emits
`GATE_FAIL`. Per `INTERPRETER.md` § `_postconditions`, this assembler does **not** modify
`.tf` files or the verdict after the read-only gate begins, and it does not advance on
failure — it halts and surfaces the residual violations.

Targeted recovery is: (1) human-edit the named `.tf` sites; (2) rerun the checker
against `$MIGRATION_DIR/terraform` with `--json
$MIGRATION_DIR/validation-report.policy.json`; (3) merge the sidecar's
`policy_status` and `violations[]` into the canonical v2 report's `policy_status`
and `policy_violations[]` without replacing its `$schema` envelope; (4) delete the
sidecar; and (5) rerun the read-only Generate `_postconditions`. Do **not**
redispatch Generate: it re-authors `terraform/` and would wipe manual fixes.

---

## Step 4: Update Phase Status and Hand Off

Only after `HANDOFF_OK`, apply the phase-status update protocol (`INTERPRETER.md` § The interpreter loop) — mark `phases.generate` completed and advance per `_advances_to` (the `complete` terminal) — in the **same turn** as the output message below.

Output to user:

```
Phase 5 of 6 complete (Generate). Optional remaining: Feedback.

Artifacts produced:
• terraform/ — [N] Terraform files for AWS infrastructure (includes baseline.tf, the account security baseline — MIGRATION_GUIDE.md Phase 1 covers its contact variables and how to opt out)
• MIGRATION_GUIDE.md — Step-by-step migration procedure
• README.md — Artifact listing and quick start
• migration-report.html — Stakeholder summary (costs + what-if scenarios when present)
• scripts/ — Database migration scripts
[• generation-warnings.json — N service(s) require manual setup]   (show this line only when warnings is non-empty; the file is always written)

Migration planning is complete. All artifacts are in $MIGRATION_DIR/.
Share migration-report.html with stakeholders; use MIGRATION_GUIDE.md for cutover.
```

After this output, SKILL.md handles the post-Generate share prompt and feedback finalization.

---

## Output Files

This phase's artifacts are declared in `_produces` (the terraform floor + MIGRATION_GUIDE.md + README.md + generation-warnings.json; `.phase-status.json` is updated per Step 4). Conditional outputs (`scripts/migrate-postgres.sh` when Postgres in design, `scripts/migrate-redis.sh` when Redis in design) are governed by the docs fragment's Step 0/Step 3; `generation-warnings.json` is always written (empty `warnings` array when nothing was skipped).

---

## Error Handling

Non-fatal generation errors and their handling (fatal predecessor/input/gate failures are handled by `_preconditions`/`_postconditions` + `INTERPRETER.md` § `_on_error`):

| Error Category                       | Behavior                                  |
| ------------------------------------ | ----------------------------------------- |
| Terraform generation partial failure | Log to generation-warnings.json, continue |
| Documentation generation failure     | GATE_FAIL at the completion gate          |
| Handoff gate check fails             | Halt pipeline, surface diagnostic         |
