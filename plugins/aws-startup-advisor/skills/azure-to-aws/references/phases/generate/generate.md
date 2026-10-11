---
_phase: generate
_title: "Generate Migration Artifacts"
_requires_phase: estimate
_input:
  - preferences.json
  - { file: aws-design.json, _when: "run has an infra track" }
  - { file: estimation-infra.json, _when: "run has an infra track" }
  - { file: azure-resource-inventory.json, _when: "run has an infra track" }
  - { file: aws-design-ai.json, _when: "run has an AI track" }
  - { file: estimation-ai.json, _when: "run has an AI track" }
_fragments:
  - _id: artifacts-infra
    _trigger: { _when: "run has an infra track (aws-design.json + estimation-infra.json exist)" }
    _file: phases/generate/generate-artifacts-infra.md
  - _id: artifacts-docs
    _trigger: { _when: "run has an infra track (MIGRATION_GUIDE.md/terraform docs apply)" }
    _file: phases/generate/generate-artifacts-docs.md
  - _id: artifacts-report
    _trigger: { _always: true }
    _file: phases/generate/generate-artifacts-report.md
  - _id: artifacts-ai
    _trigger: { _when: "aws-design-ai.json exists in $MIGRATION_DIR AND run_mode is decide_and_execute" }
    _file: phases/generate/generate-artifacts-ai.md
_assemble:
  _file: phases/generate/generate-assemble.md
_produces:
  - migration-report.html
  - generation-warnings.json
  - validation-report.json
  - README.md
  - { file: terraform/main.tf, _when: "run has an infra track" }
  - { file: terraform/baseline.tf, _when: "run has an infra track" }
  - { file: terraform/variables.tf, _when: "run has an infra track" }
  - { file: terraform/outputs.tf, _when: "run has an infra track" }
  - { file: terraform/.gitignore, _when: "run has an infra track" }
  - { file: terraform/terraform.tfvars.example, _when: "run has an infra track" }
  - { file: MIGRATION_GUIDE.md, _when: "run has an infra track" }
  - { file: generation-ai.json, _when: "run has an AI track and run_mode is decide_and_execute" }
_advances_to: complete
_interactive: false
_exec:
  _agent: rw
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_phase_completed: workshop
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _assert: "preferences.json exists and validates. WHEN the run has an infra track (azure-resource-inventory.json was produced at Discover): aws-design.json, estimation-infra.json, and azure-resource-inventory.json also exist and validate as JSON — an aws-design.json whose services[] is empty because every resource was deferred or skipped is still an infra track and takes the baseline-only path (core files + baseline.tf). WHEN the run is AI-only / app-code-only (no azure-resource-inventory.json — the app-code-only Discover/Clarify-ai-only/Design-ai/Estimate-ai track): those infra artifacts are ABSENT and instead ai-workload-profile.json, aws-design-ai.json, and estimation-ai.json exist and validate. A run with NEITHER an infra design nor an AI design is unrecoverable."
    _on_failure: _unrecoverable
  - _assert: "run_mode in .phase-status.json is 'decide_and_execute' — the user chose Execute at the post-Estimate decision gate, accepted the decide-complete resume offer, or explicitly asked for Terraform/migration scripts this turn. An absent run_mode is NOT consent."
    _on_failure: _halt_and_inform
  - _assert: "preferences.json metadata.deferred_to_generate is absent or an empty array, and no preferences.json row carries deferred_to_generate: true — every execution-only row Clarify defaulted (data.db_cutover) was confirmed at the Decision gate's Step 3b (estimate-assemble.md), which sets the row flag to false and removes the key from both metadata lists. A non-empty array or a row still flagged true means a runbook is about to be written against an answer the user never gave; return to Step 3b."
    _on_failure: _halt_and_inform
_postconditions:
  - _assert: "the always-produced artifacts exist and (where JSON) validate: migration-report.html, generation-warnings.json, validation-report.json, README.md. WHEN the run has an infra track: terraform/main.tf, terraform/baseline.tf, terraform/variables.tf, terraform/outputs.tf, terraform/.gitignore, terraform/terraform.tfvars.example, and MIGRATION_GUIDE.md also exist. baseline.tf is required even when aws-design.json has no infrastructure clusters. WHEN the run is AI-only (no aws-design.json / estimation-infra.json): there is no terraform/ directory and no MIGRATION_GUIDE.md; instead generation-ai.json exists and validates and an ai-migration/ directory was produced. migration-report.html is required on BOTH paths — a completed Generate with no report is a gate failure."
    _on_failure: _halt_and_inform
  - _validate_json: [generation-warnings.json, validation-report.json]
    _on_failure: _halt_and_inform
  - _assert: "validation-report.json (written by the MAIN-WINDOW validation step, not the rw worker) has status in {passed, passed_degraded_offline, skipped_user_continue} AND policy_status == POLICY_OK. On an AI-only run its terraform_dir is ai-migration (the Bedrock monitoring stack is the only generated Terraform) and the tf-best-practices policy gate still runs against it — unless the user chose skip/abort on a policy failure, in which case status may be policy_failed / policy_status POLICY_FAIL and the phase completes only by that explicit user choice. The tf-best-practices policy gate runs regardless of the offline path, so policy_status is never masked by passed_degraded_offline."
    _on_failure: _halt_and_inform
  - _assert: "WHEN the run has an infra track: terraform/main.tf has a valid provider configuration; terraform/variables.tf declares aws_region plus operations_email, billing_email, and security_email with no defaults; terraform/baseline.tf exists and contains aws_cloudtrail, aws_guardduty_detector, and aws_budgets_budget (and aws_config / aws_securityhub only when design_constraints.compliance names soc2, pci, hipaa, or fedramp). A domain .tf file beyond the core files is required only when a service was generated; a design with no infrastructure clusters still passes on the core files plus baseline.tf. MIGRATION_GUIDE.md has Prerequisites and Verification sections. WHEN AI-only: vacuously satisfied (no terraform/ or MIGRATION_GUIDE.md on this path). README.md lists the generated artifacts on every path."
    _on_failure: _halt_and_inform
  - _assert: "migration-report.html ALWAYS exists (it is a required _produces artifact on every path — an infra/mixed run and an AI-only app-code run alike; a completed Generate with no report is a gate failure, never a silent skip). It was rendered from references/shared/report-decision-core.md and PASSES $PLUGIN_ROOT/scripts/validate-migration-report.py (REPORT_OK, exit 0), which enforces required section IDs, TOC integrity, the CSS readability contract, accessibility, and the decision-core content checks (verdict headline, hero metrics, flip conditions, specialist callout, architecture section, what-if columns) when the artifacts contain that data. REPORT_OK does not replace rendering references/shared/report-decision-core.md. Infra/mixed runs render full mode (validated default mode); an AI-only run (no aws-design.json / estimation-infra.json) renders AI-only mode and is validated with --mode ai_only --estimation-ai estimation-ai.json. A REPORT_FAIL leaves migration-report.incomplete.html and blocks completion. Additionally, for a run with an infra track: the report leads with cluster-level architecture rationale, the per-resource mapping table appears only in an appendix, and a draft-for-review footer is present"
    _on_failure: _halt_and_inform
  - _assert: "if scenarios/index.json has at least 2 scenarios, migration-report.html includes the what-if comparison"
    _on_failure: _halt_and_inform
  - _assert: "every designed service is accounted for — generated, or listed in generation-warnings.json"
    _on_failure: _halt_and_inform
  - _assert: "no placeholder {{VARIABLE}} tokens remain in any .tf file; those belong in variables.tf as var.* references"
    _on_failure: _halt_and_inform
  - _assert: "no secret VALUE from the inventory appears in any generated artifact; secrets are emitted as Secrets Manager references"
    _on_failure: _halt_and_inform
  - _assert: "WHEN aws-design-ai.json exists AND run_mode is decide_and_execute: generation-ai.json exists and validates, its rollback_plan.mechanism is 'feature_flag' with flag_name 'AI_PROVIDER' and default_value 'azure_openai'; an ai-migration/ directory was produced (setup_bedrock.sh, test_comparison.py, bedrock_monitoring.tf on every path; migrate_to_mantle.sh for the mantle path OR provider_adapter.* for the direct/gpt-oss path, not both); and no proprietary openai.gpt-* model ID is paired with a converse/bedrock-runtime path. When aws-design-ai.json is absent this is vacuously satisfied"
    _on_failure: _halt_and_inform
_forbids_files:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
---

# Phase 5: Generate Migration Artifacts

## Orientation

Emit the Terraform, the scripts, the docs, and the report. This phase runs under
`_exec: { _agent: rw }` with `_interactive: false` — the work is bulky, file-only,
and self-contained, so it runs in an isolated sub-agent while the gates, the state
transition, and the `HANDOFF_OK` stay in the main window.

**The Terraform validation, the `tf-best-practices` policy gate, and the
`validation-report.json` write also stay in the main window** — the dispatched `rw`
worker emits `terraform/` only; it cannot invoke skills or run `terraform`/`python`.
This mirrors gcp-to-aws's `generate.md`, which owns validation inline in its own main
window and passes only the terraform DIR to the skill (the caller owns the report). See
§ "Step: Run the phase" step 4.

## Generate is opt-in, and the check has no mechanical teeth

The `run_mode` precondition above is an `_assert`. **CI binds `_assert` bodies but
never evaluates them** — the string is checked for being a non-empty value in the
right list, and nothing more. So the consent rule depends entirely on the interpreter
honoring the prose. A future reader should not assume this is enforced.

The DSL has no vocabulary for an opt-in phase, and inventing one for a single case
would be worse than this: the alternative is a mechanical check that the state file
carries a specific value, which the grammar does not have a check kind for.
`estimate-assemble.md` owns writing `run_mode`, and it writes
`decide_and_execute` **before** this phase loads, so a session that dies mid-Generate
resumes as an Execute run.

The `_check_phase_completed: workshop` precondition is the other half of the ordering:
the `workshop` sidebar declares `_gates: generate`, and a declined sidebar counts as
resolved.

## Sequencing

Emit in tier order — network, identity, and secrets first, then data, then compute,
then edge. That is the same tiering the clusters carry, which is why the tiering
replaced topological depth: Generate's sequencing is what the ordering is _for_.

## Status — implemented (build step: Generate)

The three artifact fragments and the assembler are wired AND their emitters are
implemented: `generate-artifacts-infra.md` emits Terraform, `generate-artifacts-docs.md`
the docs, `generate-artifacts-report.md` the stakeholder report (rendered from
`references/shared/report-decision-core.md`, full mode, validated by
`scripts/validate-migration-report.py`), and `generate-artifacts-ai.md` the AI-migration
pack when an AI design exists. The phase runs infra, AI-only (app-code-only), or both —
`_produces` and the pre/postconditions are conditional on which track exists. Read each
fragment's own `## Status`, not this line, for its emitter detail.

## Step: Run the phase

Steps 2–3 are the phase's WORK and are dispatched to the file-only `rw` worker. Step 4
and step 5 run in the MAIN window — the worker cannot invoke skills or run
`terraform`/`python`.

1. Verify the entry gate, including `run_mode`.
2. Run each fragment whose `_trigger` holds. (worker)
3. Run `generate-assemble.md`. (worker — emits `terraform/`, the docs, the report, and
   `generation-warnings.json`; it does NOT validate or write `validation-report.json`.)
4. **Validate the generated Terraform and write the validation report — MAIN WINDOW,
   after the worker returns and before `_postconditions`.** This MUST run in the main
   window because the `rw` worker cannot invoke skills or run `terraform`/`python`. This
   phase is the **caller** of the `tf-best-practices` validation protocol, exactly as
   gcp-to-aws's `generate.md` owns validation inline in its main window:
   - Invoke the `tf-best-practices` skill for the post-writing validation context, passing
     `$MIGRATION_DIR/terraform` — the DIR only (the caller owns the report, just as gcp
     passes only the terraform DIR to the skill). Treat it as a black box: run the
     fmt/init/validate stages where available, and the zero-dependency policy checker,
     which **runs regardless of the offline path** (a provider-registry outage skips
     `terraform validate` but never the policy gate).
   - Apply fix-and-retry to the reported `violations[]` sites (budget 3), then run the
     retry/skip/abort prompt.
   - WRITE the single canonical report at `$MIGRATION_DIR/validation-report.json` — the two
     segments joined by a single `/` (slash-joined). Merge the skill's policy verdict into
     THAT file as `policy_status` (+ `policy_violations` on failure), recorded independently
     of the fmt/init/validate outcome so a policy failure is never masked by
     `passed_degraded_offline`. **Never** write a separate `policy-verdict.json`, and never
     pin the skill's raw verdict path as the report.
   - An unresolved `POLICY_FAIL` the user does not `skip`/`abort` sets `status: policy_failed`
     and blocks completion (the `_postconditions` `_assert`).
5. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK` and advance to
   `complete`; on any failure emit `GATE_FAIL` and stop.

**Write the web-handoff summary (fail-open), only after `HANDOFF_OK`:** run
`python3 "$PLUGIN_ROOT/scripts/emit-plan-json.py" --migration-dir "$MIGRATION_DIR" --plugin-json "$PLUGIN_ROOT/.claude-plugin/plugin.json"`
(absolute paths — cwd must not be load-bearing). It reads the estimate artifacts and
writes `$MIGRATION_DIR/plan.json`, the uploadable handoff file, printing `PLAN_OK | …`
or `PLAN_SKIP | reason=…`. This is an optional enhancement, never a gate: on any skip
or error the migration is still complete — continue without it and do not surface the
script output to the user.

**Web-handoff — only when the writer above printed `PLAN_OK`** (if it printed `PLAN_SKIP`, omit this whole block; there is no file to upload). Do three things, in order:

- **(a)** In the completion summary, add exactly one plain-text entry (no link — the clickable link is the What's next call-to-action below): `plan.json — upload to AWS Startups Migrate to see if you qualify for AWS credits`.
- **(b)** Then show the user their `plan.json`. The `.migration` folder is hidden by default
  on macOS and Linux, so open the file's location for them instead of leaving them to
  find it. Run the command for the user's OS once, as an ordinary command — the agent's
  own permission prompt is the user's choice, so do not ask separately first:

  - macOS: `open -R "$MIGRATION_DIR/plan.json"` — opens Finder with the file selected,
    even inside the hidden folder.
  - Windows: `MSYS_NO_PATHCONV=1 explorer.exe /select,"<absolute Windows path to plan.json>"`
    — the prefix stops Git Bash from rewriting `/select,` as a path (drop it in
    PowerShell or cmd). In Git Bash, get the Windows path with
    `cygpath -w "$MIGRATION_DIR/plan.json"`. `explorer.exe` exits non-zero even when it
    succeeds, so treat it as opened unless it prints an error.
  - Linux: `xdg-open "$MIGRATION_DIR"` — opens the folder (it cannot select the file).

  Then show exactly ONE of the two messages below, as plain text (not in a code block).
  Do not reword them — this copy is owned by the web experience.

  If the folder opened:

  > **The folder is open with your plan.json selected.**

  On Linux, where the file cannot be selected, show **The folder with your plan.json
  is open.** instead.

  If the command failed, was not available, or the user declined it, show this as its
  own message, separate from the phase summary, and do not add any other explanation
  of why it did not open. Replace `<absolute path to plan.json>` with the real absolute
  path:

  > The folder did not open. The open command is blocked in your permissions.
  >
  > Your plan.json is saved at:
  > `<absolute path to plan.json>`
  >
  > The .migration folder is hidden by default on macOS. In Finder, press Command + Shift + Period (.) to show it.

  On Linux, use this last line instead: "The .migration folder is hidden by default on
  Linux. In your file manager, press Ctrl + H to show it." On Windows, the folder is
  not hidden, so omit the last line. Keep "The open command is blocked in your
  permissions." only when a permission rule blocked it, and drop that sentence when the
  user declined or the command failed for another reason.

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
