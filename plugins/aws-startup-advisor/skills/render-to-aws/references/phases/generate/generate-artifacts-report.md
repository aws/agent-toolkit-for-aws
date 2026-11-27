---
_fragment: artifacts-report
_of_phase: generate
_contributes:
  - migration-report.html
  - generation-warnings.json
---

# Generate — Stakeholder Report

> **Fragment unit.** See `generate.md` for how it is composed into the phase.

The customer-facing report. **It leads with the architecture rationale** — what Render
resources were found, what each becomes on AWS, and why — and keeps the per-resource
accounting in an appendix. This fragment also writes `generation-warnings.json`, the ledger
the report's accounting is checked against.

**Execute the steps in order.** This fragment runs in the file-only `rw` worker: it reads
the artifacts on disk and writes HTML and JSON. It never runs a script. Do not use recalled
values.

## Inputs

Read from `$MIGRATION_DIR/`: `aws-design.json` (`mappings[]` with `source_resource_id`,
`aws_service`, `disposition`, `confidence`, `aws_config.ecs_mode` / `ecs_mode_reason`,
`ai_track`), `estimation-infra.json` (`current_costs`, `projected_costs`, `scenarios`,
`rightsizing_delta`, `recommendation`, `pricing_source`, `accuracy_confidence`,
`complexity_tier`, `migration_cost_considerations`, `optimization_opportunities`),
`preferences.json` (every question with its disposition), `render-resource-inventory.json`
(resource kinds), the generated ledger from the infra and docs fragments, and the generated
pack itself (`terraform/`, `scripts/`, `MIGRATION_GUIDE.md`, `README.md`).

**Load `references/shared/report-decision-core.md` and render it in full mode.** That file loads the vendored canonical core (`references/vendored/report/report-decision-core.md`) first and then supplies this skill's parameters and add-ons; together they are the single source of truth for every executive-summary section (Decision Summary through "What
this assessment rests on"), the render-specific required sections, the readability contract,
and the exclusion list. Do not restate or paraphrase its rules here. If that file is missing,
emit `GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing` and
stop — a report that silently degrades to unstructured HTML is worse than one that fails
loudly, because the phase still reports success and the customer still receives the file.

## Step 0: Validate Artifacts (Read Only — REQUIRED before any HTML is written)

The JSON artifacts this report is rendered from must pass the plugin's artifact validator
**before** any report content is built. A report built on an artifact that fails its own
contract inherits the defect and hides it.

**This fragment runs in the file-only `rw` worker, which cannot run `python3`.** The check
is therefore owned by the caller: `generate.md` § "Main-window artifact pre-check" runs it in
the MAIN window, before the worker is dispatched, as:

```bash
python3 "$PLUGIN_ROOT/scripts/validate-artifacts.py" \
  --run-dir "$MIGRATION_DIR" \
  --skill render-to-aws
```

and dispatches this fragment only on exit `0` (`PASS`). On exit `1` (`FAIL`) the caller
surfaces every `ERROR` line to the user, emits
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=artifact_contract`, names the
phase that owns the failing artifact so the user can re-run it, does **NOT** patch any artifact
to pass validation, and does **NOT** dispatch the worker — so `migration-report.html` is never
written. Any other exit code means the validator did not run (e.g. `python3` unavailable):
the caller tells the user the pre-report check was skipped and never records it as a pass.

Inside this fragment, Step 0 is a precondition, not a command: if you are executing this
file, the caller's check passed or was reported as skipped. Do not attempt to run the
validator from the worker; never write the report when the caller reports the check as
failed.

## Step 1: Lead with the architecture (REQUIRED)

After `decision-summary`, the TOC, `exec-share`, and `exec-services`, the report OPENS its
argument with `exec-architecture`: build-once ECR image promotion by digest, private ingress
(ALB or CloudFront in front, services in private subnets), managed PostgreSQL on RDS and
Valkey on ElastiCache, EFS for persistent disks, Step Functions for a supported Workflow,
and tagged, isolated per-environment stacks. For **every** ECS on Fargate mapping state
whether it is **Express or standard** and quote its `aws_config.ecs_mode_reason`. Name the
deferred AI surface plainly so the report does not overclaim.

The per-resource accounting table goes in `appendix-accounting`, not the body; `exec-targets`
(Step 3) carries the mapping rows the reader needs.

## Step 2: Cost anchors (REQUIRED — validator-enforced)

Present the Premium / Balanced / Optimized table from `estimation-infra.json` with the
render scenario semantics in `report-decision-core.md` Section 3, and **surface, not hide**
`is_floor: true` or non-empty `unpriced_line_ids` (say the total is a known-cost floor and
why), the baseline provenance (`current_costs.source`), and the accuracy band.

Wrap each figure inside `<section id="exec-costs">` with a `data-cost-key` attribute so the
validators can confirm the rendered dollars match the estimate:

| `data-cost-key`        | Value                                                                      | Checked by   |
| ---------------------- | -------------------------------------------------------------------------- | ------------ |
| `current_monthly`      | `current_costs.render_monthly`, or the literal text `unavailable` when `current_costs.source` is `unavailable` | plugin-root (dollars) / render-local (literal) |
| `aws_monthly_balanced` | `projected_costs.aws_monthly_balanced` — the right-sized design; matches the generated Terraform | plugin-root |
| `aws_monthly_optimized`| `projected_costs.aws_monthly_optimized` — Balanced minus the commitment discount on eligible lines | plugin-root  |
| `aws_monthly_premium`  | `projected_costs.aws_monthly_premium` (optional; required when the value exists) | plugin-root |
| `delta`                | `rightsizing_delta.monthly` — like-for-like minus Balanced, on the like-for-like comparison row, e.g. `+$52` | render-local |

Example: `<td data-cost-key="aws_monthly_balanced">$306</td>` and
`<td data-cost-key="current_monthly">$123</td>`. Monthly figures render as **whole dollars**
rounded half-to-even (306.5 → `$306`, 243.6 → `$244`, 123.45 → `$123`); cents fail the
currency gate. The attribute is not reader-visible text. Each anchor must sit on a rendered
element inside `exec-costs` itself — not in an HTML comment, and not merely somewhere else in
the document (a decision-summary hero metric does not satisfy this rule). **A missing
required anchor is a validator FAIL, not a skip.** Only untagged illustrative figures remain
unchecked. State that human labor is excluded.

## Step 3: Render domain sections

Each section below is required by `report-decision-core.md` § "Render-specific required
sections", which also lists the exact phrases the render-local validator looks for.

- **`exec-targets`** — one `<tr data-source-resource-id="…" data-aws-service="…">` per
  `aws-design.json` mapping, attributes copied exactly, the AWS service in the row's visible
  text, with disposition and the "How we chose this" phrase from the mapping confidence.
- **`migration-data`**, **`migration-storage`**, **`migration-deployment`** — the PostgreSQL
  (Database Migration Service or `pg_dump`) and Key Value procedure with writer quiescence,
  integrity checks and source retention; the EFS pre-copy/delta transfer for `/var/data` with
  ownership, permissions and integrity checks; the ECR digest promotion with the serving
  deploy identity, auto-deploy state and rollback lineage. Walk the order
  `MIGRATION_GUIDE.md` lays out so report and runbook agree.
- **`cutover`**, **`rollback`**, **`verification`** — DNS TTL, certificate readiness, traffic
  shift and writer quiescence; rollback triggers, writer fencing, DNS restore and the retained
  Render source (`cutover.source_retention` from `preferences.json`); endpoint, database,
  cache, disk, worker/cron and Workflow checks.
- **`deferred-surfaces`** — the exact `deferred_shared_ai_engine` warning paragraph and every
  `conditional_workflow_generation_unsupported` warning from Step 3.9, each stating plainly
  that nothing was generated for it.
- **`exec-timeline`** — the stage order of `MIGRATION_GUIDE.md` (prerequisites → build and
  deployment → PostgreSQL → Key Value → persistent disk → deployment and service cutover →
  DNS and traffic → verification), the binding driver first, no week or hour figures.
- **`exec-risks`** — a table (Risk · Impact · Likelihood · Mitigation) from
  `recommendation.migrate_if`, the ledger warnings, the deferred AI track, and defaulted
  preferences with cutover or cost impact. Never empty.
- **`exec-assumptions`** — after `exec-risks`, per `report-decision-core.md` Section 8.

## Step 3.5: Accounting split (REQUIRED)

The accounting-split rule is the skeleton's (§ Accounting split); the render values are the
⟨accounting_*⟩ rows of the parameter table in Step 3.75. The
`<section id="appendix-accounting">` element carries `data-accounted-count="N"`, and the
`exec-services` headline count, the Terraform `migration_summary` count, and the ledger must
all agree.

## Step 3.75: Appendix block (REQUIRED — skeleton-driven, validator-enforced)

**Load `references/vendored/report/report-appendix-skeleton.md` and build the appendix block
from it.** That file is the single source of truth for the stable appendix lettering (A–J plus
the dotted A.1 slot; letters never shift when a conditional section is absent — a Render run
has no `appendix-ai` and still uses Appendix E for artifacts), the appendix divider, and the
purpose, trigger, data sources, table shapes and content rules of Appendices A, B, B.1, C, E,
I and J. Everything each appendix needs is specified there and in the parameter table below,
from the artifacts this skill writes — no other skill has to be installed. Do not restate or
paraphrase its rules here. If the file is missing, emit
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing` and stop.

### Parameters

| Parameter                                                                        | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ⟨source_cloud⟩                                                                   | Render                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ⟨report_mode⟩                                                                    | `full` (render has no AI-only path — the AI track is deferred)                                                                                                                                                                                                                                                                                                                                                                                             |
| ⟨precheck_owner⟩ / ⟨precheck_skill_flag⟩                                         | Caller-owned: `generate.md` § "Main-window artifact pre-check" runs `validate-artifacts.py` in the main window (Step 0 above) / `--skill render-to-aws`                                                                                                                                                                                                                                                                                                     |
| ⟨appendices_rendered⟩                                                            | Required: A, A.1 (render add-on, "Appendix A.1 — Generation Accounting"), B, C, E, I, J. Conditional: B.1 only when `optimization_opportunities[]` is non-empty. Declared omissions: D — AI track deferred to `bedrock-migration-assessment` (Step 3.9 `deferred_shared_ai_engine`); F, G, H — the render content follow-up PR adds them; preferences dispositions and the generated baseline are not yet rendered as appendices (see Declared exceptions). |
| ⟨appendix_header_text⟩                                                           | "Appendix: Detailed Migration Analysis"                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ⟨footer_text⟩                                                                    | "Generated by Render to AWS Migration Advisor — draft for review; verify figures against source JSON artifacts before executive sign-off." (Step 4)                                                                                                                                                                                                                                                                                                         |
| ⟨extra_anchors⟩                                                                  | `delta` (render-local, `rightsizing_delta.monthly`) and the `current_monthly` literal `unavailable` when `current_costs.source` is `unavailable` (Step 2)                                                                                                                                                                                                                                                                                                           |
| ⟨accounting_ledger_field⟩                                                        | `generation-warnings.json` → `accounting.accounted_count`, which equals the number of `aws-design.json` mappings (every mapping is classified exactly once)                                                                                                                                                                                                                                                                                                 |
| ⟨accounting_split_sentence⟩                                                      | **"N design rows · G generated · C consumed topology · D deferred · U unsupported"** where N = `design_count`, G = `generated_count`, C = `consumed_topology_count`, D = `deferred_count`, U = `unsupported_count`, and N = G + C + D + U                                                                                                                                                                                                                      |
| ⟨accounting_location⟩                                                            | `appendix-accounting` (Appendix A.1 below), whose `<section>` carries `data-accounted-count="N"`                                                                                                                                                                                                                                                                                                                                                            |
| ⟨validator_invocation⟩                                                           | The two-command block in Step 5 (plugin-root validator with `--estimation-infra`, `--aws-design`, `--migration-dir`; then the render-local validator)                                                                                                                                                                                                                                                                                                       |
| ⟨design_mapping_source⟩                                                          | `aws-design.json` → `mappings[]` (`source_resource_id`, kind, `aws_service`, `disposition`, `confidence`)                                                                                                                                                                                                                                                                                                                                                   |
| ⟨how_we_chose_vocabulary_ref⟩                                                    | the mapping's `confidence` in `aws-design.json` (`deterministic` / `inferred` / `billing_inferred`) — same value as the render decision-core layer                                                                                                                                                                                                                                                                                                          |
| ⟨service_row_extras⟩                                                             | A disposition column: rows the ledger classified as consumed topology, deferred, or unsupported say so there                                                                                                                                                                                                                                                                                                                                                |
| ⟨cost_breakdown_source⟩                                                          | Every line of `scenarios.like_for_like.lines`, `scenarios.balanced.lines` and `scenarios.optimized.lines` with its monthly amount and `pricing_source` basis, the Premium uplift, the Optimized commitment arithmetic, and the four totals (`known_cost_monthly_usd`) — tier fields per decision core ⟨tier_semantics⟩                                                                                                                                                              |
| ⟨mandatory_breakdown_rows⟩                                                       | none beyond the canonical                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ⟨baseline_breakdown⟩                                                             | n/a — `current_costs.render_monthly` is a single figure with a `source`                                                                                                                                                                                                                                                                                                                                                                                     |
| ⟨floor_fields⟩                                                                   | `is_floor` and `unpriced_line_ids` per scenario; when `is_floor` is true, label that total a **known-cost floor** and name the unpriced lines; when false, say no unpriced lines remain                                                                                                                                                                                                                                                                      |
| ⟨extra_cost_columns⟩                                                             | none                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨optimization_sources⟩ / ⟨ri_sp_eligibility_ref⟩                                 | Infra only (`estimation-infra.json`; no AI estimate exists in this skill) / `references/vendored/estimate/ri-sp-eligibility.md`                                                                                                                                                                                                                                                                                                                             |
| ⟨phase_order_source⟩                                                             | `MIGRATION_GUIDE.md` order                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ⟨scripts_list⟩                                                                   | `scripts/promote-image.sh` (build-once ECR digest promotion), `scripts/migrate-postgres.sh` (PostgreSQL stages), `scripts/migrate-disk.sh` (EFS pre-copy and final delta)                                                                                                                                                                                                                                                                                  |
| ⟨cutover_strategy_fields⟩                                                        | `cutover.source_retention` from `preferences.json`                                                                                                                                                                                                                                                                                                                                                                                                         |
| ⟨rollback_source⟩ / ⟨rollback_rows⟩                                              | The runbook's rollback section (`MIGRATION_GUIDE.md`) / Render source retained, DNS and traffic restored last, writer fencing lifted                                                                                                                                                                                                                                                                                                                        |
| ⟨ai_appendix_spec⟩                                                               | Declared omission — the AI track is deferred to `bedrock-migration-assessment`; no `appendix-ai` is ever rendered                                                                                                                                                                                                                                                                                                                                           |
| ⟨pack_extras⟩                                                                    | `generation-warnings.json`, `validation-report.json`                                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨data_artifacts⟩                                                                 | `preferences.json`, `render-resource-inventory.json`, `estimation-infra.json`, `aws-design.json`; `ai-workload-profile.json` when present                                                                                                                                                                                                                                                                                                                   |
| ⟨preferences_groups⟩ / ⟨preferences_schema_ref⟩ / ⟨critical_default_caveats⟩     | n/a — Appendix F is a declared omission in this PR (render content follow-up)                                                                                                                                                                                                                                                                                                                                                                               |
| ⟨baseline_controls_table⟩ / ⟨security_equivalent_label⟩ / ⟨security_extra_columns⟩ / ⟨budget_limit_formula⟩ / ⟨compliance_field⟩ / ⟨cost_guardrail_rows⟩ / ⟨opt_out_procedure⟩ | n/a — Appendix G is a declared omission in this PR (render content follow-up)                                                                                                                                                                                                                                                                                                                                                                |
| ⟨gap_source_names⟩ / ⟨gap_extra_rows⟩ / ⟨observability_note_field⟩               | n/a — Appendix H is a declared omission in this PR (render content follow-up)                                                                                                                                                                                                                                                                                                                                                                               |
| ⟨pricing_source_fields⟩                                                          | `pricing_source` (`status`, `message`, `services_by_source`, `services_with_missing_fallback`) and `accuracy_confidence`                                                                                                                                                                                                                                                                                                                                    |
| ⟨exclusion_extras⟩                                                               | Human labor (`migration_cost_considerations.human_labor_monthly_usd` is null); unpriced or partially priced lines (`unpriced_line_ids`, `services_with_missing_fallback`); the Workflow semantics limited to the proven set (task order, retry with backoff, per-attempt timeout, task-token callback, retained logging and alarms, Map fan-out or compensation when declared) and never Render execution parity; the deferred AI track; `terraform apply` prohibited until provider-backed validation passes |
| ⟨rightsizing_limitations⟩                                                        | `rightsizing_delta.what_would_change_this` plus any line held at like-for-like by a sizing table (the Valkey node)                                                                                                                                                                                                                                                                                                                                                                         |
| ⟨terraform_validation_rule⟩                                                      | From `validation-report.json` when the main window has already written one for this run (`status`, `policy_status`, a `passed_degraded_offline` provider outage); otherwise state that validation runs after the worker returns and its result lives in `validation-report.json`                                                                                                                                                                             |
| ⟨warnings_sources⟩                                                               | `generation-warnings.json` (Step 3.9) — the ledger warnings the report already states in `deferred-surfaces`                                                                                                                                                                                                                                                                                                                                                |
| ⟨glossary_examples⟩                                                              | ECR digest promotion, writer quiescence, known-cost floor, Express mode                                                                                                                                                                                                                                                                                                                                                                                     |

### Declared exceptions

render-to-aws passes no `--profile`; the validator's default `full` set (A, B, C, E) is met.
Divergence from the skeleton's optional appendices is declared here, pending the render
content follow-up PR:

- `appendix-ai` (D) — never rendered: the AI track is deferred to `bedrock-migration-assessment`.
- `appendix-config` (F) — not rendered yet, although `preferences.json` exists; the follow-up adds it.
- `appendix-security` (G) — not rendered yet, although `generate-artifacts-baseline.md` emits the baseline; the follow-up adds it.
- `appendix-security-gap` (H) — not rendered yet; the follow-up adds it.
- `appendix-optimization` (B.1) — conditional per the skeleton; absent when there are no opportunities.

Add-on: `appendix-accounting` (A.1) below, checked by the render-local validator.

### Appendix A.1 — Generation Accounting (`appendix-accounting`, REQUIRED)

The Step 3.5 split sentence, `data-accounted-count`, and one row per source resource from
`accounting.source_resource_ids` with its classification and target file(s) or reason.

## Step 3.9: `generation-warnings.json`

Write `generation-warnings.json` against `references/shared/schema-generation-warnings.json`. Every design mapping occurs exactly once in `generated`, `consumed_topology`, `deferred`, or `unsupported`; counts and canonical byte-sorted IDs reconcile. Emit:

- `deferred_shared_ai_engine` whenever the design AI track has that exact status. The warning states that `ai-workload-profile.json` conforms to the shared #415 contract and that, after Discover, this run starts `bedrock-migration-assessment` on that profile. That assessment designs the Bedrock target and estimates its cost, then stops before generate. No AI target, cost, model, adapter, or Terraform may appear in this skill's artifacts.
- `conditional_workflow_generation_unsupported` only for a Workflow classified `unsupported` by `generate-infra-workflow.md`, with its ledger `detail` as the reason. The selected design still appears in the report, while the report plainly states that its Terraform was not generated and lists the manual validation needed. A Workflow classified `generated` is shown as generated; the report lists only the semantics the contract tests prove (task order, retry with backoff, per-attempt timeout, task-token callback, retained logging and alarms, and Map fan-out or compensation when declared) and never claims Render execution parity.
- `unpriced_cost_floor` when either estimate scenario has unpriced lines.
- `eb_platform_branch_retired` for each Elastic Beanstalk service whose `compute.runtime_version` names no listed platform branch (retired, or never offered), so `generate-infra-compute.md` named the nearest listed branch of that family instead; the report names the declared version, the branch chosen, and whether the declared branch was retired or never offered. `eb_platform_version_undeclared` for each Elastic Beanstalk service whose `compute.runtime_version` is `null`; the report names the branch chosen and says the version must be pinned before cutover.
- `ecs_express_public_subnet_placement` for each Express service placed in public subnets, and `ecs_express_not_selected_rolling_release` for each service the Generate rules in `generate-artifacts-infra.md` name. The report states for every Fargate mapping whether it is Express or standard and its `ecs_mode_reason`.

## Step 4: Draft-for-review footer (REQUIRED)

Every report carries a footer stating it is a `draft for review`, generated from the
migration artifacts, and that figures are estimates to validate before decisions. The
report must not contain captured secrets, environment values, email/account/workspace/
project/environment IDs, repository URLs, or local paths. It is a draft for review, not a
deployment-success claim.

> **Plan-share links are GATED OFF** (landing page not live). Do NOT emit a share link.

## Step 5: Validate the rendered report (REQUIRED — mandatory gate)

The validation shape is the skeleton's (§ Validate the rendered report): the worker writes the
candidate as `migration-report.html` but does not validate it. In the main window run both
commands with absolute paths — the plugin-root structural gate first, the render-only pass
second:

```bash
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --estimation-infra "$MIGRATION_DIR/estimation-infra.json" \
  --aws-design "$MIGRATION_DIR/aws-design.json" \
  --migration-dir "$MIGRATION_DIR"
uv run --project "$SKILL_BASE/scripts" --frozen python \
  "$SKILL_BASE/scripts/validate-render-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" --migration-dir "$MIGRATION_DIR"
```

Both must print `REPORT_OK` and exit 0; that is the only pass. The plugin-root validator is
stdlib-only and owns structure, readability, accessibility, and the shared cost anchors; the
render-local validator owns the render-specific sections, target rows, accounting, ledger,
`delta`, and exclusions. On `REPORT_FAIL` / exit 1 from either, atomically rename the
candidate to `migration-report.incomplete.html`, preserve every diagnostic line for the user,
and block completion. Exit 2 from either also blocks completion.

If `uv` or the frozen environment is unavailable, stage 7 is recorded as `failed` (`checks.report.status: failed`, top-level `status: failed`) with evidence naming the missing `uv` or frozen environment, the incomplete-HTML rename still applies, completion stays blocked, and the preflight warning plus the rerun command are shown. A missing `python3` for the plugin-root validator is recorded the same way, with evidence naming `python3`. There is no validation skip; stages 1 to 6 are unaffected.

Do not ask the user to install Vale, Pa11y, axe, or Chromium, and do not skip validation
because such tooling is absent — it is never required.
