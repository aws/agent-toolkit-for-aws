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
`preferences.json` (every question with its disposition, plus `global`), `render-resource-inventory.json`
(resource kinds), `scenarios/index.json` when present (the workshop index with its inline
scenario manifests), the generated ledger from the infra and docs fragments, and the generated
pack itself (`terraform/`, `scripts/`, `MIGRATION_GUIDE.md`, `README.md`) — in particular
`terraform/baseline.tf` (the account baseline controls, the budget limit, the remote-state
block) and `terraform/monitoring.tf` (alarms and the alerts topic).

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
| `aws_monthly_optimized`| `projected_costs.aws_monthly_optimized` — Balanced minus the commitment discount on eligible lines; exactly one anchor in `exec-costs` | plugin-root (dollars) / render-local (presence) |
| `aws_monthly_premium`  | `projected_costs.aws_monthly_premium` (required, exactly one anchor in `exec-costs`, whenever the value exists) | plugin-root (dollars) / render-local (presence) |
| `like_for_like_monthly`| `scenarios.like_for_like.known_cost_monthly_usd` — the like-for-like comparison figure (a comparison, never a tier); exactly one anchor in `exec-costs`, on the like-for-like comparison row's "Monthly (USD)" cell | render-local (dollars, whole-dollar half-to-even; `COST_LIKE_FOR_LIKE_MONTHLY_MISSING` / `_MISMATCH` / `_SOURCE_INVALID`) |
| `delta`                | `rightsizing_delta.monthly` — like-for-like minus Balanced, on the like-for-like comparison row, e.g. `+$45` | render-local |

Example: `<td data-cost-key="aws_monthly_balanced">$314</td>` and
`<td data-cost-key="current_monthly">$123</td>`. Monthly figures render as **whole dollars**
rounded half-to-even (313.5 → `$314`, 277.8 → `$278`, 358.5 → `$358`, 123.45 → `$123`); cents fail the
currency gate. The attribute is not reader-visible text. Each anchor must sit on a rendered
element inside `exec-costs` itself — not in an HTML comment, and not merely somewhere else in
the document (a decision-summary hero metric does not satisfy this rule). **A missing
required anchor is a validator FAIL, not a skip.** Only untagged illustrative figures remain
unchecked. State that human labor is excluded.

## Step 2.5: Executive sections after the cost table

Immediately after `exec-costs`, and before `exec-timeline`, render these sections in this
order, each only when its trigger holds and each linked from the TOC when rendered. Their
rules are the decision core's (§ Cost Optimization, § What-if scenarios, § Security & Cost
Guardrails); this step names the render sources. None of them may name an artifact filename
or a Terraform resource address — control names and figures only.

1. **`exec-optimization` — Cost Optimization.** Trigger: `optimization_opportunities[]` is
   non-empty. Posture table with the rows Balanced on-demand (the anchor), Balanced plus the
   Compute Savings Plan (percent-only — the vendored range — until a 30–90 day AWS usage
   baseline exists; quote the mid-point dollar figure only as what Optimized prices), Balanced
   plus the Database Savings Plan (a dollar figure only when a line passes the Generation 7+ gate;
   when every recorded class is pre-Generation-7, the row says no saving is claimed, names the
   ineligible classes and that a Generation 7+ class would qualify, and shows no dollar amount or
   purchase recommendation), and Optimized as the floor (the commitment rows that have eligible
   lines, at their mid-point rate, each line's discount rounded to whole dollars). State in the section that the Savings Plan
   rows are **incremental to Balanced and not additive to Optimized**, because Optimized already
   includes the commitment rows that have eligible lines. Then the "Which commitment fits" list from the opportunity
   rows (the eligible `aws_service` values per bucket; a bucket with no eligible line says so and recommends nothing; RDS Reserved Instances are mutually
   exclusive with the Database Savings Plan on the same database; no Spot or storage-class row
   unless the estimate emits one). Link down to Appendix B.1. Sources: `optimization_opportunities[]`,
   `scenarios.optimized.commitment`, `projected_costs`.
   **Appendix B.1 credits caveat.** Once, directly below the B.1 opportunities table and scoped to
   the commitment rows, state: promotional or AWS Activate credits do not cover the upfront cost of
   Reserved Instances or Savings Plans (Partial or All Upfront) and apply only to the ongoing
   discounted rate. Do not repeat it elsewhere and do not make a wider credits claim.
2. **`what-if-scenarios` — What-if Scenarios.** Trigger: `scenarios/index.json` lists two or
   more scenarios. Columns Scenario · Region · HA · Compute · Arch · Premium $/mo · Balanced $/mo
   · Optimized $/mo · Complexity. Knob columns resolve from `preferences.json` → `global`
   (Region ← `aws_region`, HA ← `availability`, Compute ← `management_model` — this skill has
   no Kubernetes knob, so Compute names the ECS model — Arch ← `cpu_architecture`), each
   overlaid by the scenario's `preferences_subset`; costs and complexity ← the manifest's
   `estimation_summary`, rounded to whole dollars. Manifests are inline in the index (no
   `manifest` path). The active row (`active_scenario_id`) carries `class="active-scenario"`
   and an "(active)" label. Under the table: the knob delta of each variant against the
   baseline in plain words, any `region_note`, and the reminder that the discovery inventory is
   frozen and the generated Terraform matches the active scenario only. `calculator_url` is
   always null — render no calculator link.
3. **`exec-security-teaser` — Security and Cost Guardrails (render add-on).** Trigger:
   `terraform/baseline.tf` was emitted (always, for this skill). The canonical trigger
   (`projected_costs.breakdown.security_baseline`) never exists in this skill's estimate, so the
   section is a declared add-on, not the canonical rule. Three rows — GuardDuty, CloudTrail,
   Budget alerts — with the decision core's indicative ranges (~$2–25/mo, ~$0.50–3/mo, $0) and
   the actual budget `limit_amount` written to `baseline.tf`; say plainly that none of them is a
   line of the estimate; one sentence from `global.compliance` (the AWS Config + Security Hub
   add-on was or was not generated); "See Appendix G".

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

## Step 3.75: Appendix block (REQUIRED — skeleton-driven; the validator checks section IDs, the letters are an authoring rule pinned by the contract test)

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
| ⟨appendices_rendered⟩                                                            | Required: A, A.1 (render add-on, "Appendix A.1 — Generation Accounting"), B, C, E, I, J. Conditional: B.1 when `optimization_opportunities[]` is non-empty (always true once the estimate finds a commitment-eligible line); F when `preferences.json` exists (always after Clarify); G when `terraform/baseline.tf` was emitted (always — `generate-artifacts-baseline.md` emits it on every run); H always — the Render security posture it compares against is declared by this spec (⟨gap_source_names⟩), not read from an inventory file. Declared omission: D — AI track deferred to `bedrock-migration-assessment` (Step 3.9 `deferred_shared_ai_engine`). |
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
| ⟨preferences_groups⟩                                                             | Every object of `preferences.json` → `questions[]` (iterate all; never a subset), one row each: Question / assumption ← `decision_changed` (the decision the question changes) with the `question_id` in a `class="mono"` span (the artifact carries no `prompt` text — legacy-fallback clause of the skeleton); Your choice ← `value` (arrays expanded, `null` → "not applicable"); Source ← `disposition` + `provenance` → "User answer" / "Default applied (`default_rule`)" / "Not applicable (discovered)"; Design consequence ← `consequence`. Sort: answered, then not-applicable (discovered), then defaulted. Defaulted rows carry `class="assumption"`. Then a second table, "Global settings", one row per key of `preferences.json` → `global` (`aws_region`, `availability`, `compliance`, `cost_posture`, `cpu_architecture`, `management_model`), Source "Clarify global answer", consequence from the clarify question that key resolves. No `source` signal column exists in this skill's artifact. |
| ⟨preferences_schema_ref⟩                                                         | `references/shared/schema-preferences.md` (the field contract) and the `question_id` rows of the Clarify fragments (`references/phases/clarify/clarify-*.md`), which supply the question wording the artifact does not carry                                                                                                                                                                                                                                   |
| ⟨critical_default_caveats⟩                                                       | Callouts at the top of Appendix F for: defaulted `cost.budget_guardrail` (the artifact's consequence is "recommends no AWS Budgets alert"; state that the baseline still creates a budget at `max(50, ceil(aws_monthly_balanced × 1.2))` so the two agree); defaulted `cutover.source_retention` (the rollback window and the double-run period); `global.compliance` when it is `["none"]` or `["unknown"]` (no AWS Config + Security Hub add-on, no regulated-data controls); `global.availability` (the multi-AZ posture the estimate priced) |
| ⟨baseline_controls_table⟩                                                        | One row per always-on control group of `generate-artifacts-baseline.md` § baseline.tf (alternate contacts, password policy, S3 account public-access block, EBS default encryption, IAM Access Analyzer, IMDSv2 defaults, CloudTrail with its log bucket, the monthly budget, GuardDuty) plus one row for the Remote State block and one summary row for `terraform/monitoring.tf` (alerts topic and alarms). The CloudTrail row's Render equivalent is Render's Pro-plan workspace audit logs of team actions (90-day retention, CSV or API export), not "no audit log", and its action column says CloudTrail adds a per-API-call trail of the AWS account; the monthly budget row's Render equivalent is "Render billing page" with no claim about the absence of spend alerts. Each row's Terraform cell lists **every** `resource "<type>" "<name>"` address of the generated `baseline.tf` it covers, written `<type>.<name>` — the render-local validator checks that every address of the file appears in the section. Cost cells for controls without a shared indicative range read "—" with a one-line footnote |
| ⟨security_equivalent_label⟩ / ⟨security_extra_columns⟩                           | "Render equivalent" / Threat mitigated, Terraform resource (`class="mono"`)                                                                                                                                                                                                                                                                                                                                                                                 |
| ⟨budget_limit_formula⟩                                                           | The `cost.budget_guardrail` number when the user gave one, else `max(50, ceil(aws_monthly_balanced × 1.2))` — print the formula with the estimate value and the `limit_amount` written to `baseline.tf` (e.g. `max(50, ceil(313.5 × 1.2)) = 377`), and the 50 / 80 / 100 % notification thresholds                                                                                                                                                              |
| ⟨compliance_field⟩                                                               | `preferences.json` → `global.compliance` (array; `["none"]` means no compliance-conditional rows — say the add-on was not generated and what would trigger it)                                                                                                                                                                                                                                                                                              |
| ⟨cost_guardrail_rows⟩                                                            | none — this skill never generates `ai-migration/` (the AI track is deferred), so no Bedrock budget or anomaly row exists                                                                                                                                                                                                                                                                                                                                    |
| ⟨opt_out_procedure⟩                                                              | Per `generate-artifacts-baseline.md` § Opting out: delete the block from the `Account Baseline` marker through its `End Account Baseline` marker and remove the `billing_email` / `security_email` tfvars rows; keep the shared declarations above it and the Remote State block; the result must pass `terraform validate`. Point at `terraform/README.md`                                                                                                   |
| ⟨gap_source_names⟩                                                               | The Render posture this skill compares against, named from the design and preferences kinds (no inventory security fields exist): private services on the Render-managed network; team members, deploy hooks and API keys; service logs plus workspace audit logs of team actions on Pro plans and higher (Render docs, https://render.com/docs/audit-logs, read 2026-11-27: at least 90 days retained, each export spans at most 90 days, CSV or API export), which are not a trail of every API call your services make — never write that Render has no audit log; no intrusion or threat detector; public static sites by design; plan-based log retention; environment groups for secrets; Render-managed TLS certificates; dashboard and shell operator access                                                              |
| ⟨gap_extra_rows⟩                                                                 | Secrets management (environment group → Secrets Manager + Parameter Store), TLS and certificates (Render-managed TLS → ACM with external DNS), Operator access (dashboard/shell → IAM Identity Center and the CI OIDC role)                                                                                                                                                                                                                                      |
| ⟨observability_note_field⟩                                                       | none — render's estimate lines carry no note field. The observability row cites the environment line's amount (the CloudWatch Logs, Metrics and Alarms line) and the `observability.log_retention` preference, and says the estimate prices CloudWatch above the always-free tier without claiming CloudWatch has no free tier                                                                                                                              |
| ⟨pricing_source_fields⟩                                                          | `pricing_source` (`status`, `message`, `services_by_source`, `services_with_missing_fallback`), `accuracy_confidence`, `current_costs.source` / `baseline_note`, and `timestamp`. Appendix I renders them as a table with columns Domain / source · Status · Accuracy / confidence · Dated: one row per `services_by_source` bucket (cached, estimated, fallback), one for the Render baseline (`current_costs.source`), one for `services_with_missing_fallback`. The accuracy cell carries the artifact's prose confidence and the per-line `confidence` counts — no numeric band exists in the artifact; the Dated cell carries the estimate `timestamp` date and the baseline-note date, never the rate cache's own date |
| ⟨exclusion_extras⟩                                                               | Human labor (`migration_cost_considerations.human_labor_monthly_usd` is null); unpriced or partially priced lines (`unpriced_line_ids`, `services_with_missing_fallback`); the Workflow semantics limited to the proven set (task order, retry with backoff, per-attempt timeout, task-token callback, retained logging and alarms, Map fan-out or compensation when declared) and never Render execution parity; the deferred AI track; `terraform apply` prohibited until provider-backed validation passes |
| ⟨rightsizing_limitations⟩                                                        | `rightsizing_delta.what_would_change_this` plus any line held at like-for-like by a sizing table (the Valkey node) or by absent sizing evidence (a Workflow or Lambda line whose design mapping records no size or `sizing_provenance`)                                                                                                                                                                                                                                                                                                                                                                         |
| ⟨terraform_validation_rule⟩                                                      | From `validation-report.json` when the main window has already written one for this run (`status`, `policy_status`, a `passed_degraded_offline` provider outage); otherwise state that validation runs after the worker returns and its result lives in `validation-report.json`                                                                                                                                                                             |
| ⟨warnings_sources⟩                                                               | `generation-warnings.json` (Step 3.9) — the ledger warnings the report already states in `deferred-surfaces`                                                                                                                                                                                                                                                                                                                                                |
| ⟨glossary_examples⟩                                                              | ECR digest promotion, writer quiescence, known-cost floor, Express mode                                                                                                                                                                                                                                                                                                                                                                                     |

### Declared exceptions

render-to-aws passes no `--profile`; the validator's default `full` set (A, B, C, E) is met,
and every conditional appendix whose trigger holds is rendered. The one declared omission:

- `appendix-ai` (D) — never rendered: the AI track is deferred to `bedrock-migration-assessment`.

Render add-ons, declared here and in `references/shared/report-decision-core.md` § Render add-ons:

- `exec-security-teaser` renders on the trigger "`terraform/baseline.tf` emitted", not on the
  canonical `projected_costs.breakdown.security_baseline` entry, which this skill's estimate
  never writes (estate-wide costs attach to design mappings).
- Appendix H's Render-side posture is declared by ⟨gap_source_names⟩ above; no inventory
  security fields are read.
- `scenarios/index.json` carries its scenario manifests inline (no `manifest` path field), and
  the what-if Compute column resolves from `global.management_model` (no Kubernetes knob).
- `appendix-accounting` (A.1) below, checked by the render-local validator.

### Fixture layout

The checked-in golden lives at `fixtures/expected/generated/migration-report.html` with its
artifacts one level up (`fixtures/expected/estimation-infra.json`, `aws-design.json`,
`preferences.json`, `scenarios/index.json`). When validating that fixture, **both** validators
take `--migration-dir fixtures/expected` (not `fixtures/expected/generated`), so the shared
validator sees `scenarios/index.json` and enforces the what-if gate. Real runs (Step 5) pass
`$MIGRATION_DIR`, where the report and its artifacts share one directory.

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
