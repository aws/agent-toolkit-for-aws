---
_phase: generate
_title: "Generate Migration Artifacts"
_requires_phase: estimate
_input:
  - aws-design.json
  - estimation-infra.json
  - preferences.json
  - heroku-resource-inventory.json
_fragments:
  - _id: terraform
    _trigger: { _always: true }
    _file: phases/generate/generate-terraform.md
  - _id: docs
    _trigger: { _always: true }
    _file: phases/generate/generate-docs.md
  - _id: report
    _trigger: { _always: true }
    _file: phases/generate/generate-report.md
  - _id: eks-generate
    _trigger: { _when: "aws-design.json has an eks_cluster entry OR a service with aws_service == 'EKS'" }
    _file: phases/generate/generate-eks.md
_assemble:
  _file: phases/generate/generate-assemble.md
_produces:
  - terraform/main.tf
  - terraform/baseline.tf
  - terraform/variables.tf
  - terraform/outputs.tf
  - terraform/security.tf
  - terraform/.gitignore
  - terraform/terraform.tfvars.example
  - MIGRATION_GUIDE.md
  - README.md
  - migration-report.html
  - generation-warnings.json
  - validation-report.json
_advances_to: complete
_interactive: false
_exec:
  _agent: rwx
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [aws-design.json, estimation-infra.json, preferences.json, heroku-resource-inventory.json]
    _on_failure: _unrecoverable
  - _validate_json: [aws-design.json, estimation-infra.json, preferences.json, heroku-resource-inventory.json]
    _on_failure: _unrecoverable
  - _assert: "preferences.json metadata.questions_deferred_to_generate is absent or an empty array — every Generate-time question Clarify defaulted (Q4 maintenance window, Q6c DB migration method, Q12d EB deploy method) was asked at the Decision gate's 'Confirm execution choices' step (estimate-assemble.md). A non-empty array means MIGRATION_GUIDE.md / Terraform is about to be written against an answer the user never gave; return to that step."
    _on_failure: _halt_and_inform
_postconditions:
  - _check_file_exists: [terraform/main.tf, terraform/baseline.tf, terraform/variables.tf, terraform/outputs.tf, terraform/security.tf, terraform/.gitignore, terraform/terraform.tfvars.example, MIGRATION_GUIDE.md, README.md, migration-report.html, generation-warnings.json, validation-report.json]
    _on_failure: _halt_and_inform
  - _assert: "terraform/main.tf has valid provider configuration; terraform/variables.tf declares at least an aws_region variable"
    _on_failure: _halt_and_inform
  - _assert: "terraform/baseline.tf contains a locals block with cloudtrail_retention_days set to a positive integer, plus aws_account_alternate_contact resources for each of operations, billing, and security, aws_iam_account_password_policy, aws_s3_account_public_access_block, aws_ebs_encryption_by_default, aws_accessanalyzer_analyzer, aws_ec2_instance_metadata_defaults, aws_cloudtrail with its log bucket, aws_budgets_budget, and aws_guardduty_detector"
    _on_failure: _halt_and_inform
  - _assert: "terraform/baseline.tf has the Compliance-Conditional section (aws_config_* recorder/delivery/status, aws_securityhub_account, FSBP standards subscription) exactly when the normalized preferences compliance array contains soc2, pci, hipaa, or fedramp; a PCI DSS standards subscription exists only when it contains pci; no NIST 800-53 standards subscription exists regardless of compliance values"
    _on_failure: _halt_and_inform
  - _assert: "terraform/variables.tf declares operations_email, billing_email, and security_email with no defaults and placeholder-rejecting validation blocks, and terraform/terraform.tfvars.example lists all three with TODO placeholders"
    _on_failure: _halt_and_inform
  - _validate_json: [validation-report.json]
    _on_failure: _halt_and_inform
  - _assert: "validation-report.json has $schema 'validation-report/v2' and its policy_status is 'POLICY_OK' (produced by the assembler after every Terraform-producing fragment, including conditional eks-generate, completed; a not_run placeholder is never accepted). POLICY_FAIL or not_run fails closed. TRUST BOUNDARY: this gate reads the worker-written verdict and trusts its provenance claim (the worker MUST NOT invent POLICY_OK — see generate-assemble.md); it does NOT independently re-run the checker to re-derive the result. This is the same trust level as every other _postconditions _assert here (each reads what the worker wrote). This gate is READ-ONLY: do not run the checker, edit .tf, or edit the verdict here."
    _on_failure: _halt_and_inform
  - _assert: "at least one domain .tf file exists beyond the core files"
    _on_failure: _halt_and_inform
  - _assert: "MIGRATION_GUIDE.md has Prerequisites, Verification, Cutover, and Rollback sections, in that order, with Decommission after Rollback; the Rollback section names a DNS-revert action (when terraform/dns.tf exists: one that persists cutover_weight in terraform.tfvars, never a one-command -var override; otherwise: setting each hostname back to its Heroku DNS target at the current provider). When Postgres is in the design, the Rollback section states where the primary database is after the Phase 2 database handoff, never instructs dropping that database as a disposable copy, and gives a database failback that stops every writer (Heroku maintenance plus every process type scaled to 0 and Scheduler disabled, with the formation recorded for restore; Fargate via writers_quiesced in terraform.tfvars, which is emitted whether or not dns.tf exists, so a later apply stays at 0; Elastic Beanstalk via the Auto Scaling group, never MinSize 0, and later applies do not apply aws_elastic_beanstalk_environment; EKS by writing replicas 0 into kubernetes/*-deployment.yaml from the migration directory and applying it), confirms no application session is active, resets the Heroku public schema, restores with pg_restore --exit-on-error, restores the recorded formation and checks web readiness before maintenance:off, and stops if that restore fails. When Elastic Beanstalk is in the design the failback DNS move is aws route53 change-resource-record-sets, and a saved plan that changes aws_elastic_beanstalk_environment is not applied. When Postgres is not in the design, the Rollback section contains no pg_dump, pg_restore, or migrate-postgres.sh command. README.md lists the artifacts"
    _on_failure: _halt_and_inform
  - _assert: "if preferences.json data.dns_strategy (the field Clarify Q10 writes; there is no global.dns_strategy) is 'route53' and at least one heroku-resource-inventory.json resource_type 'domain' resource belongs to a heroku_app whose web formation is an Elastic Beanstalk or Fargate service in aws-design.json, then terraform/dns.tf exists and declares hosted_zone_ids (map, one zone per hostname), heroku_dns_targets, heroku_apex_ips, and cutover_weight variables, a per-hostname local.aws_targets map (no shared scalar target), weighted apex_heroku/apex_aws records, and an aws_acm_certificate_validation resource, and no terraform file declares var.acm_certificate_arn; otherwise — including every EKS design and every domain whose app has no EB/Fargate web service — terraform/dns.tf does not exist and such domains are listed in generation-warnings.json"
    _on_failure: _halt_and_inform
  - _assert: "migration-report.html has decision-summary, exec-costs, cost-optimization, next-steps, and draft-for-review footer; if scenarios/index.json has ≥2 scenarios, also what-if-scenarios"
    _on_failure: _halt_and_inform
  - _assert: "report-validation-status.json exists and its report_status is 'REPORT_OK', stamped by the main-window 'Finish Generate' report-validation step (described below, run BEFORE this gate); a REPORT_FAIL, a missing/not_run stamp (validator could not run), or a missing file blocks completion. This gate is READ-ONLY: do not run the validator or edit the report/stamp here."
    _on_failure: _halt_and_inform
  - _assert: "if Postgres is in the design, scripts/migrate-postgres.sh exists; if Redis is in the design, scripts/migrate-redis.sh exists"
    _on_failure: _halt_and_inform
  - _assert: "if EKS is in the design, terraform/eks.tf exists WITH cluster + node group resources, AND a kubernetes/ directory has namespace + deployment manifests"
    _on_failure: _halt_and_inform
  - _assert: "if Elastic Beanstalk is in the design, terraform/beanstalk.tf exists; if preferences.design_constraints.eb_deploy_method.value is github_actions or absent, .github/workflows/deploy-eb.yml exists; if codepipeline, terraform/pipeline.tf exists; if manual, no automated deploy artifact is required"
    _on_failure: _halt_and_inform
  - _assert: "for every Elastic Beanstalk web service, terraform/variables.tf declares required per-app eb_application_port_<app>_web and eb_health_check_path_<app>_web string variables with no defaults and basic validation, and terraform/beanstalk.tf passes them unchanged to that app's PORT and HealthCheckPath settings; non-web Elastic Beanstalk services do not require these web-only variables"
    _on_failure: _halt_and_inform
  - _assert: "every designed service is accounted for (generated or listed in generation-warnings.json)"
    _on_failure: _halt_and_inform
  - _assert: "no placeholder {{VARIABLE}} tokens remain in Terraform .tf files (those belong in variables.tf as var.* references)"
    _on_failure: _halt_and_inform
_forbids_files:
  - heroku-resource-inventory.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
---

# Phase 5: Generate Migration Artifacts

> **CONSENT GUARD (check before anything else):** This phase runs only by explicit
> opt-in (the decision is the product; execution artifacts are opt-in). If
> `.phase-status.json` → `run_mode` is not `"decide_and_execute"`: when this turn's
> user message is an explicit Execute request ("generate the Terraform", "create the
> migration scripts", or Decision-gate choice C), set `run_mode: "decide_and_execute"`
> (read-merge-write) and proceed; otherwise STOP — do not generate anything — and
> re-present the Decision gate (or the decide-complete resume offer) from
> `estimate-assemble.md` / `SKILL.md`.

## Orientation

Transform the design + estimate into migration artifacts in `$MIGRATION_DIR/`: a
`terraform/` directory, `MIGRATION_GUIDE.md`, `README.md`, `migration-report.html`
(stakeholder summary + optional what-if scenarios), database migration scripts,
`generation-warnings.json`, and `validation-report.json` (the Terraform
policy-gate verdict the assembler produces after all fragments — it runs the
tf-best-practices policy checker against the final `terraform/` directory, and
the read-only completion gate then reads that verdict).
Terraform for each Elastic Beanstalk web service
is intentionally incomplete until the customer supplies that app's required
application port and health check path. Non-web Elastic Beanstalk services do not
require those web-only inputs. This is the multi-artifact phase.

Composed of the terraform + docs + report fragments + an EKS-generate fragment + one
cross-artifact validator assembler (declared in the frontmatter
`_fragments`/`_assemble`); the interpreter runs each fragment whose `_trigger` is
true, then the assembler. The `eks-generate` fragment is an ALTERNATIVE compute
path — it fires only when the design has an `eks_cluster` (its `_when` trigger),
emitting `eks.tf` + `kubernetes/` manifests. Templates are output skeletons
(`templates/generate/...`); the fragments are the routing algorithm. Read each unit
file for its own contract; the assembler owns the cross-artifact completion gate.

---

## Scope Boundary

**This phase covers artifact generation ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Re-designing or changing AWS service selections (Phase 3 decisions are final)
- Re-estimating costs (Phase 4 estimates are final)
- Asking the user additional clarification questions (Phase 2 is done)
- Discovering new Heroku resources (Phase 1 is done)
- Feedback collection (Phase 6 handles this)

**Your ONLY job: Transform the design into migration artifacts. Nothing else** — with two
exceptions. Running the tf-best-practices policy checker against the generated `terraform/` and
applying its `fix_hint`s is part of _producing_ the artifacts: the assembler does this after all
Terraform-producing fragments (Generate is dispatched at `_exec._agent: rwx`, which grants exactly
the scoped shell the checker needs — nothing else). Running the report validator over
`migration-report.html` is a separate, main-window exception: the dispatched worker's shell is
scoped to the policy checker only (it cannot run the report validator), so that check is part of
_finishing_ the artifacts and happens in the "Finish Generate" step below, after the worker
returns. Design/estimate decisions stay final.

---

## Finish Generate in the main window (report validation) — BEFORE the gate

This is **leftover Generate work**, not a gate check: the dispatched `_exec._agent: rw` worker
that assembled the report has no shell (`INTERPRETER.md` § capability tiers — `rw` excludes Bash),
so it could not run the report validator. The interpreter finishes that work in the MAIN window
(the only place with a shell), **after the worker returns and before running `_postconditions`**.

1. Run the report validator (**required, blocking**):

   ```
   python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" \
     "$MIGRATION_DIR/migration-report.html" --migration-dir "$MIGRATION_DIR"
   ```

2. `REPORT_OK` → **stamp the durable result** so the gate reads an artifact, not conversation
   memory: write `$MIGRATION_DIR/report-validation-status.json` as
   `{"report_status": "REPORT_OK"}`, then continue to the gate. `REPORT_FAIL` → write
   `{"report_status": "REPORT_FAIL", "errors": [ … ]}` and **emit `GATE_FAIL`, pasting the
   validator's `errors[]` verbatim** so the user knows exactly what failed (missing scope id,
   empty `cost-optimization`, a banned `badge-verdict-*` pill class, a `<th>` without `scope`,
   missing `<html lang>`, etc.). This step does **not** edit the HTML.

3. If the validator cannot run at all (no shell on the host), do **not** write
   `report_status: "REPORT_OK"` — leave the stamp absent (or `not_run`) so the gate fails closed.

Then the `_postconditions` gate runs (read-only): the section-id `_assert` plus the
`report-validation-status.json` `_assert` above. The gate runs no validator and edits nothing (per
`INTERPRETER.md` § `_postconditions`, a gate never mutates artifacts to pass).

**Recovery on `GATE_FAIL`:** fix the report from the pasted `errors[]` — either hand-edit
`migration-report.html`, re-run the validator directly, and re-stamp `report-validation-status.json`
on `REPORT_OK`; or a maintainer re-runs Generate for a clean rebuild. Do **not** rely on "just
re-run Generate" as the fix path in prose: re-dispatch re-authors the report under the shell-less
worker, so the pasted error list is what makes the next attempt actionable.

`report-validation-status.json` is a temp status sidecar (like the policy sidecar) — not a
`_produces` artifact; it exists only to carry the validator result across the worker→gate boundary.
