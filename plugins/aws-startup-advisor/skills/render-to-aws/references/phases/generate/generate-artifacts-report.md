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
`delta_monthly_usd`, `recommendation`, `pricing_source`, `accuracy_confidence`,
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
| `aws_monthly_balanced` | `projected_costs.aws_monthly_balanced` — the capacity-preserving scenario; matches the generated Terraform | plugin-root |
| `aws_monthly_optimized`| `projected_costs.aws_monthly_optimized` — the right-sized scenario          | plugin-root  |
| `aws_monthly_premium`  | `projected_costs.aws_monthly_premium` (optional; required when the value exists) | plugin-root |
| `delta`                | `delta_monthly_usd` — right-sized minus capacity-preserving, e.g. `-$62`   | render-local |

Example: `<td data-cost-key="aws_monthly_balanced">$358</td>` and
`<td data-cost-key="current_monthly">$123</td>`. Monthly figures render as **whole dollars**
rounded half-to-even (358.5 → `$358`, 296.5 → `$296`, 123.45 → `$123`); cents fail the
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

Any mapping / service / headline count the report states MUST equal
`generation-warnings.json` → `accounting.accounted_count`, which equals the number of
`aws-design.json` mappings (every mapping is classified exactly once). State the split in
`appendix-accounting` so the reader sees how the design resolved rather than a bare number:
**"N design rows · G generated · C consumed topology · D deferred · U unsupported"** where
N = `design_count`, G = `generated_count`, C = `consumed_topology_count`, D =
`deferred_count`, U = `unsupported_count`, and N = G + C + D + U. The
`<section id="appendix-accounting">` element carries `data-accounted-count="N"`. The
`exec-services` headline count, the Terraform `migration_summary` count, and the ledger must
all agree. Deferred and unsupported rows are still rows the customer must plan for — never
present them as generated.

## Step 3.75: Stable appendix lettering (REQUIRED — validator-enforced)

The letter is part of the heading and TOC label; it does not shift when a conditional section
is absent:

| Section ID              | Visible heading prefix                               |
| ----------------------- | ---------------------------------------------------- |
| `appendix-services`     | Appendix A — Service Recommendations                 |
| `appendix-accounting`   | Appendix A.1 — Generation Accounting                 |
| `appendix-costs`        | Appendix B — Cost Estimates                          |
| `appendix-optimization` | Appendix B.1 — Savings Plans and Reserved Instances  |
| `appendix-steps`        | Appendix C — Migration Steps and Rollback            |
| `appendix-ai`           | Appendix D — AI Migration                            |
| `appendix-artifacts`    | Appendix E — Generated Artifacts Catalog             |
| `appendix-config`       | Appendix F — Your Configuration                      |
| `appendix-security`     | Appendix G — Security Capabilities                   |
| `appendix-security-gap` | Appendix H — Security Gap Analysis                   |
| `appendix-assumptions`  | Appendix I — Assumptions, Exclusions, and Validation |
| `appendix-glossary`     | Appendix J — Glossary                                |

Absent conditional sections keep their letters: a Render run has no `appendix-ai` (the AI
track is deferred) and still uses Appendix E for artifacts, never renumbering it to D.
`appendix-accounting` is render-specific and takes `A.1` so the shared letters A–J do not
shift. Required here: A, A.1, B, C, E, I, J. `appendix-optimization` (B.1) only when
`optimization_opportunities[]` is non-empty. The plugin-root validator checks both `<h2>` and
TOC labels.

## Step 3.8: Appendix build instructions

Everything each appendix needs is specified here, from the artifacts this skill writes — no
other skill has to be installed. Keep the lettering from Step 3.75.

### Appendix A — Service Recommendations (`appendix-services`, REQUIRED)

One row per `aws-design.json` mapping (at least two rows): Render resource, kind, selected
AWS service, disposition, and **How we chose this** from the mapping confidence (Standard
pairing / Tailored to your setup / Estimated from billing only). Rows the ledger classified
as consumed topology, deferred, or unsupported say so in the disposition column.

### Appendix A.1 — Generation Accounting (`appendix-accounting`, REQUIRED)

The Step 3.5 split sentence, `data-accounted-count`, and one row per source resource from
`accounting.source_resource_ids` with its classification and target file(s) or reason.

### Appendix B — Cost Estimates (`appendix-costs`, REQUIRED)

At least three body rows: every line of `scenarios.capacity_preserving.lines` and
`scenarios.right_sized.lines` with its monthly amount and `pricing_source` basis, the two
scenario totals (`known_cost_monthly_usd`), and `unpriced_line_ids` per scenario. When
`is_floor` is true, label that total a **known-cost floor** and name the unpriced lines;
when false, say no unpriced lines remain. Whole dollars throughout.

### Appendix C — Migration Steps and Rollback (`appendix-steps`, REQUIRED)

Numbered phases, each an `<h3>Phase N — …</h3>` block (at least two), in `MIGRATION_GUIDE.md`
order, each naming what moves and the script the operator runs: `scripts/promote-image.sh`
(build-once ECR digest promotion), `scripts/migrate-postgres.sh` (PostgreSQL stages),
`scripts/migrate-disk.sh` (EFS pre-copy and final delta). State that every script is dry-run
by default and that nothing was executed during Generate. Close with a **rollback table**
(Track | Trigger | Action | Recovery objective) built from the runbook's rollback section:
Render source retained, DNS and traffic restored last, writer fencing lifted. No week or
hour durations.

### Appendix E — Generated Artifacts Catalog (`appendix-artifacts`, REQUIRED)

Every file in the pack: `terraform/*.tf`, `MIGRATION_GUIDE.md`, `README.md`, each script
under `scripts/`, `generation-warnings.json`, `validation-report.json`, with one line on
what each is for. Deferred work appears here only as "not generated".

### Appendix I — Assumptions, Exclusions, and Validation (`appendix-assumptions`, REQUIRED)

**Pricing confidence table:** source, status, accuracy band — from `pricing_source`
(`status`, `message`, `services_by_source`, `services_with_missing_fallback`) and
`accuracy_confidence`.

**Exclusions list** — one line each, every one that applies: human labor
(`migration_cost_considerations.human_labor_monthly_usd` is null); unpriced or
partially priced lines (`unpriced_line_ids`, `services_with_missing_fallback`); the Workflow
semantics limited to the proven set (task order, retry with backoff, per-attempt timeout,
task-token callback, retained logging and alarms, Map fan-out or compensation when declared)
and never Render execution parity; the deferred AI track; `terraform apply` prohibited until
provider-backed validation passes.

**Validation limitations:** from `validation-report.json` when the main window has already
written one for this run (`status`, `policy_status`, a `passed_degraded_offline` provider
outage); otherwise state that validation runs after the worker returns and its result lives
in `validation-report.json`.

### Appendix J — Glossary (`appendix-glossary`, REQUIRED)

`<table class="glossary-table">` with `Term` / `Meaning` headers and at least three rows
(e.g. ECR digest promotion, writer quiescence, known-cost floor, Express mode).

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

The worker writes the candidate as `migration-report.html` but does not validate it. In the
main window run both commands with absolute paths — the plugin-root structural gate first,
the render-only pass second:

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
