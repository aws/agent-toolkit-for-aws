---
_fragment: artifacts-report
_of_phase: generate
_contributes:
  - migration-report.html
---

# Generate — Stakeholder Report

> **Fragment unit.** See `generate.md` for how it is composed into the phase.

The customer-facing report. **It leads with the cluster-level architecture rationale** —
what workloads were found, what each becomes, and why — and moves the per-resource
mapping table to an appendix. This is the visible payoff of the holistic goal and the
part a customer actually reads; a 40-row table as the headline buries the argument.

**Execute the steps in order.**

## Inputs

Read from `$MIGRATION_DIR/`: `aws-design.json` (`clusters[]` with `pattern_status` /
`target_architecture` / `rationale`, `services[]`, `deferred[]`, `warnings[]`),
`estimation-infra.json` (cost comparison, tiers, reservations, `is_floor`),
`azure-resource-inventory.json` (drift + reservation signals), `preferences.json`,
and `scenarios/index.json` if it exists (workshop what-ifs).

**Load `references/shared/report-decision-core.md` and render it in `full` mode.** That file loads the vendored canonical core (`references/vendored/report/report-decision-core.md`) first and then supplies this skill's parameters and add-ons; together they are the single source of truth for every executive-summary section (Decision Summary through "What
this assessment rests on") — verdict typography, the required section IDs, baseline-quality and
not-comparable rules, Activate wording, and the CSS readability contract all live there. Do not
restate or paraphrase its rules here.

There is no hand-rolled fallback. If that file is missing, emit
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing` and stop — a
report that silently degrades to unstructured HTML is worse than one that fails loudly, because
the phase still reports success and the customer still receives the file.

## Step 0: Validate Artifacts (Read Only — REQUIRED before any HTML is written)

The JSON artifacts this report is rendered from must pass the plugin's artifact validator
**before** any report content is built. A report built on an artifact that fails its own
contract inherits the defect and hides it.

**This fragment runs in the file-only `rw` worker, which cannot run `python3`.** The check
is therefore owned by the caller: `generate.md` § "Step: Run the phase" runs it in the MAIN
window, before the worker is dispatched (step 2 there), as:

```bash
python3 "$PLUGIN_ROOT/scripts/validate-artifacts.py" \
  --run-dir "$MIGRATION_DIR" \
  --skill azure-to-aws
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

## AI-only report path (REQUIRED when there is no infrastructure track)

An app-code-only / AI-workload repo produces the AI artifacts but **no infra track** —
`aws-design.json`, `estimation-infra.json`, and `terraform/` do not exist, only
`ai-workload-profile.json`, `aws-design-ai.json`, `estimation-ai.json`,
`generation-ai.json`, and `ai-migration/`. `migration-report.html` is **still a required
`_produces` artifact on this path** — never skip it. A completed Generate with no report
is the silent-degradation failure this fragment exists to prevent.

When `aws-design.json` and `estimation-infra.json` are BOTH absent but the AI artifacts
exist, render `migration-report.html` in **AI-only mode**: still load
`references/shared/report-decision-core.md` for the decision-core section rules
(verdict typography, `exec-assumptions`, `exec-risks`, Activate wording, the CSS
readability contract), but source every figure from the AI artifacts and OMIT the infra
executive/appendix sections (`exec-services`, `exec-costs`, `appendix-costs`,
`appendix-services`, `appendix-steps`) that no infra track can populate. Required sections
on this path: `decision-summary`, `exec-assumptions`, `exec-risks`, `appendix-ai`,
`appendix-artifacts`, `appendix-config`, `appendix-glossary`. Render:

- **`decision-summary`** — the verdict from `estimation-ai.json` -> `recommendation`
  (e.g. already-on-Bedrock -> `go`, model_change:false), the AI monthly run rate from
  `cost_comparison` (labeled estimated, with the accuracy band), and the residual Azure
  coupling as the real migration work (e.g. retarget Azure AI Search -> OpenSearch
  Serverless / Bedrock Knowledge Bases; re-embed at the target dimension).
- **`exec-optimization`** (REQUIRED when `estimation-ai.json` -> `optimization_opportunities`
  is non-empty, e.g. a `provisioned_throughput` entry) — the same standalone-section rule
  as the full report; a buried table does not satisfy it.
- **`appendix-ai`** — the model migration table from `aws-design-ai.json` (each
  `models_to_migrate` with model_change / migration_path), the feature-flag rollback
  (`AI_PROVIDER`), and the vector-store re-index note.
- **`appendix-artifacts`** — the `ai-migration/` catalog (setup, adapter/mantle, comparison
  test, `bedrock_monitoring.tf`) and `STARTUP_PROGRAMS.md`.
- **`appendix-config`** — the `preferences.json` values and every `chosen_by: "default"`
  assumption (token volume, compliance-unknown, region) with its consequence.

Step 3.5's infra resource-count rule does not apply (no `aws-design.json` services); the
AI accounting lives in `appendix-ai`. Step 5 validates this report with `--mode ai_only`.

## Step 1: Lead with cluster-level rationale (REQUIRED — `_assert`)

The report OPENS with the workload story, one block per `clusters[]` entry:

- the workload (its primary + members, in plain language),
- its `target_architecture` and the cluster `rationale` — what it becomes and why,
- for an `unclassified` cluster or `pattern_status: catalog_absent`, say so plainly so
  the report does not overclaim architectural insight it does not have.

The per-resource mapping table (azure_type → aws_service, confidence) goes in an
**appendix**, not the body. The phase `_assert` fails if the table leads.

## Step 2: Cost section

Present the Premium / Balanced / Optimized comparison from `estimation-infra.json`, and
**surface, not hide**:

- `is_floor: true` and any unpriced lines — say the total is a floor and why.
- Reserved-instance baselines, and that a `$0` consumption line was substituted with an
  RI-equivalent rate (never presented as free).
- The baseline provenance (user-stated bracket vs invoice) and the accuracy band.

**Cost-figure anchors (machine-checkable, REQUIRED).** Wrap the Balanced AWS monthly figure
and the current Azure monthly figure inside `<section id="exec-costs">` with a
`data-cost-key` attribute, so `validate-migration-report.py` can confirm the rendered
dollars match the estimate: `data-cost-key="aws_monthly_balanced"` on the element holding
the Balanced dollar figure (value = `projected_costs.aws_monthly_balanced`), and
`data-cost-key="current_monthly"` on the element holding the Azure figure (value =
`current_costs.azure_monthly` — the validator resolves the `current_monthly` anchor from
that key for this skill). Optional per-tier: `data-cost-key="aws_monthly_premium"` /
`"aws_monthly_optimized"`. Example:
`<strong data-cost-key="aws_monthly_balanced">Est. $155/mo</strong>` and
`<span data-cost-key="current_monthly">$4,200/mo</span>`. The attribute is not
reader-visible text. Each anchor must sit on a rendered element inside `exec-costs` itself —
not in an HTML comment, and not merely somewhere else in the document (a decision-summary
hero metric does not satisfy this rule). **Both anchors are mandatory whenever their JSON
value exists and `exec-costs` is rendered — a missing required anchor is a validator FAIL,
not a skip.** Only untagged illustrative figures remain unchecked.

## Step 3: Surface the rest

- **Drift** between declared IaC and running state (when a live/RDfA source ran).
- **Deferred** specialist items, each named with its recommendation.
- **Availability downgrades** — where a zone-redundant source maps to single-AZ.
- The **what-if comparison** when `scenarios/index.json` has ≥ 2 scenarios (REQUIRED by
  the phase `_assert` in that case).

## Step 3.5: Resource count (REQUIRED)

Any **mapping / plan / service / headline** count the report states — the headline "N
services", a per-section subtotal, or the appendix mapping table's row count — MUST equal
`generation-warnings.json.accounted`: the accounted headline = generated services (each
plan-fold counted ONCE via its parent) + `deferred[]`. `skipped[]` entries (config sources,
observability, plan-folded children) are still recorded in `generation-warnings.json` for
completeness but are **EXCLUDED from the accounted headline** — a folded or config-only
resource is not a distinct billed service, and counting it double-counts against its parent.
Do **not** count only the emitted `.tf` resources, and do **not** count `services[]` alone —
a deferred resource is still a resource the customer must plan for. This mirrors the
PRIMARY-services headline rule in gcp-to-aws `report-decision-core.md` § 1 (secondaries
excluded). The report-body mapping count, the Terraform `migration_summary` count
(`generate-artifacts-infra.md` Step 4), and `generation-warnings.json.accounted` must all
agree.

**Surface the split in the report body (REQUIRED).** State the three figures side by side so
the reader sees raw estate vs. plan rather than a bare number that appears to disagree with
the discovery count: **"N discovered · M mapped services · A accounted (M + D deferred)"** —
where N = `total_resources` (raw discovered), M = generated primary services, D = `deferred[]`,
and A = `accounted` (= M + D).

**Exception — the discovery/"discovered" count is its own figure.** A statement about what
was _discovered_ — "Discovery identified N resources", "N resources discovered", the raw
Azure estate size — references `azure-resource-inventory.json` `total_resources` (the RAW
discovered count), NOT `accounted`. `total_resources` legitimately exceeds `accounted`
(the accounted set excludes resources that were never mapped/planned — e.g. free/zero-cost
or non-migratable items), so forcing the discovery label to equal `accounted` understates
what was actually found. Keep the two distinct: the discovery figure = `total_resources`;
every mapping/plan/service/headline figure = `accounted` (with the three-way agreement
above). This mirrors gcp-to-aws `report-decision-core.md` where the discovered/current
count is a separate figure from the mapping count.

## Step 3.75: Stable appendix lettering (REQUIRED — authoring rule; the validator checks section IDs, not letters)

Use the same stable customer-visible appendix labels as the full-report contract. The letter is
part of the heading and TOC label; it does not shift when a conditional section is absent:

| Section ID              | Visible heading prefix                               |
| ----------------------- | ---------------------------------------------------- |
| `appendix-services`     | Appendix A — Service Recommendations                 |
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

Render `appendix-artifacts` before `appendix-config`. Conditional sections keep their reserved
letters when absent — for example, an infra-only report still uses Appendix E for artifacts,
never renumbering it to D. The plugin-root report validator checks the section IDs, not the letters, so the letters are an authoring rule.

## Step 3.8: Appendix build instructions — C, G, H, I

Appendices A, B, B.1, D, E, F and J are populated by Steps 1–3 and the shared
`report-decision-core.md` rules. The four sections below have no other build instruction in
this skill; everything they need is specified here, from the artifacts this skill writes —
no other skill has to be installed. Keep the lettering from Step 3.75.

### Appendix C — Migration Steps and Rollback (`appendix-steps`, REQUIRED)

Numbered migration phases, each as an `<h3>Phase N — …</h3>` block (the validator requires
at least two, counting whichever is larger: these headings or the section's table rows),
carrying:

- Phase name and what moves — walk the cutover sequence `MIGRATION_GUIDE.md` lays out in
  dependency-tier order (`generate-artifacts-docs.md` Step 1 item 3), so the report and the
  runbook agree on the order. Name the clusters from `aws-design.json` → `clusters[]` that
  move in each phase.
- The scripts the operator runs in that phase, by name and in order:
  `scripts/01-validate-prerequisites.sh` (always first), `scripts/02-migrate-data.sh` when the
  design has a database, `scripts/03-migrate-containers.sh` when it has an Azure Container
  Registry, `scripts/04-migrate-secrets.sh` when it has a Key Vault, and
  `scripts/05-validate-migration.sh` (always last). State that every script is dry-run by
  default and that nothing was executed during Generate.
- The cutover strategy each phase depends on, from `preferences.json`: `data.db_cutover`
  (`dump_restore` — freeze, dump, restore, verify; or `dms` — DMS replication then a switch)
  and `design_constraints.vm_cutover` (`mgn` or re-platform). Name a prerequisite blocker
  verbatim when `preferences.json` records one (e.g. a `vm_cutover.conflict` such as
  `azure_edition_windows_server`, which must be cleared before MGN can replicate).
- Dependencies and the verification that gates the next phase (the Verification section per
  service in `MIGRATION_GUIDE.md`).
- Deferred items from `aws-design.json` → `deferred[]`, each named with its recommendation,
  so a deferral the runbook carries is not silent in the report.

Do not quote week or hour durations — the plugin has none that are calibrated. Communicate
time as stage order plus duration drivers.

**Rollback procedure** — a table (Track | Trigger | Action | Recovery objective) built from
the runbook's rollback notes: keep the Azure resource running until verification passes; DNS
and traffic cutover last; for `dump_restore`, rollback before the switch is lifting the write
freeze on Azure; for `dms`, it is stopping the task and lifting the freeze; for `mgn`, the
Azure VM stays up until the rollback window closes. Add an AI track row (feature-flag
rollback to the current provider) when `ai-migration/` exists.

Source: `MIGRATION_GUIDE.md`, `preferences.json`, `aws-design.json` (`clusters[]`,
`deferred[]`), `generation-warnings.json` (`deferred[]`, `skipped[]`), the `scripts/` the run
emitted.

### Appendix G — Security Capabilities (`appendix-security`)

Full security-baseline capability table. The executive flow carries only a teaser
(`exec-security-teaser`); this appendix is the complete picture. One row per always-on
control `terraform/baseline.tf` emits (`generate-artifacts-infra.md` Step 1.5), with the
Terraform resource name in a `class="mono"` cell:

| Control                       | Terraform resource                                | What it does for you                                                              | Azure equivalent                                        | Monthly cost   |
| ----------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------- | -------------- |
| Alternate contacts            | `aws_account_alternate_contact.*`                 | Billing, operations and security notices reach a named owner                      | Subscription service-admin and billing contacts         | $0             |
| IAM password policy           | `aws_iam_account_password_policy.baseline`        | 14-char minimum, reuse prevention, complexity for console users                   | Entra ID password protection                            | $0             |
| S3 account public-access block | `aws_s3_account_public_access_block.baseline`    | Account-wide prevention of any bucket being made public                           | Storage account `allowBlobPublicAccess = false`         | $0             |
| EBS default encryption        | `aws_ebs_encryption_by_default.baseline`          | Every volume encrypted at rest by default                                         | Managed-disk server-side encryption (platform default)  | $0             |
| IAM Access Analyzer           | `aws_accessanalyzer_analyzer.baseline`            | Alerts when IAM policies or buckets grant external access                         | Entra Permissions Management / Defender CSPM (partial)  | $0             |
| IMDSv2 required               | `aws_ec2_instance_metadata_defaults.baseline`     | Blocks SSRF from stealing instance credentials                                    | None (Azure IMDS has no token mode to enforce)          | $0             |
| CloudTrail + S3 log bucket    | `aws_cloudtrail.baseline`                         | Immutable audit log of every API call                                             | Activity Log + Log Analytics export                     | ~$0.50–3/mo    |
| AWS Budget                    | `aws_budgets_budget.monthly_spend`                | Alerts before spend passes the limit `baseline.tf` computed                       | Cost Management budgets                                 | $0             |
| GuardDuty                     | `aws_guardduty_detector.baseline`                 | Detects compromised credentials, crypto mining, unusual API patterns              | Microsoft Defender for Cloud (paid plans)               | ~$2–25/mo      |

State the budget limit `baseline.tf` wrote (`max(50, ceil(aws_monthly_balanced × 1.2))`) and
say plainly that the Estimate does **not** roll CloudTrail storage, GuardDuty, Config or
Security Hub into `aws_monthly_balanced` — the cost column is an indicative list-price range,
not a line of the estimate.

**Compliance-conditional** (only when `preferences.json` →
`design_constraints.compliance.value` contains `soc2`, `pci`, `hipaa` or `fedramp`): add rows
for `aws_config_configuration_recorder.baseline` (continuous configuration recording; Azure
equivalent Azure Policy + change tracking) and `aws_securityhub_account.baseline` (automated
checks against AWS best practices; Azure equivalent Defender for Cloud regulatory
compliance). When the compliance list is empty or `["unknown"]`, say the add-on was not
generated and what would trigger it.

**Cost guardrails** (when `$MIGRATION_DIR/ai-migration/bedrock_monitoring.tf` exists): the
Bedrock budget and cost-anomaly rows, with Azure Cost Management budgets / Azure OpenAI
quota as the equivalents. Add an **Inference profiles (tagged)** row only when the generated
file contains an enabled `aws_bedrock_inference_profile` resource and its output.

**What the baseline does NOT cover (you still need):**

- SOC 2: Qualified auditor, formal policies, employee training, vendor management
- HIPAA: BAA with AWS, qualified HIPAA auditor, data handling policies
- PCI: QSA assessment, network segmentation validation, pen testing
- FedRAMP: Agency-level NIST 800-53 controls, ATO process

**To enable / opt out:** `terraform apply` on `baseline.tf`; opting out is the three-step
procedure in `generate-artifacts-infra.md` Step 1.5 § "Opting out of the baseline" (the
Remote State section must survive). Point at `terraform/README.md`.

Source: `terraform/baseline.tf` as emitted, `preferences.json` compliance values,
`estimation-infra.json` → `projected_costs.aws_monthly_balanced` (budget limit).

### Appendix H — Security Gap Analysis (`appendix-security-gap`, REQUIRED when infra track ran)

Table: Capability | Azure (detected) | AWS (generated) | Gap / action. Minimum rows:

- Network perimeter (network security groups and VNet subnets → VPC security groups and
  subnets; count the `Microsoft.Network/*` entries in `azure-resource-inventory.json`)
- Identity & access (Entra ID, managed identities and RBAC role assignments → IAM roles and
  scoped policies; name the `preferences.json` → `identity.value` choice, e.g. a fresh IAM
  Identity Center rather than Entra federation)
- Audit logging (Azure Activity Log → CloudTrail in `baseline.tf`)
- Threat detection (Microsoft Defender for Cloud, if enabled → GuardDuty in `baseline.tf`)
- Secrets management (Key Vault → Secrets Manager; state whether `aws_config.kms_added` /
  `acm_added` is true for the `Microsoft.KeyVault/vaults` service in `aws-design.json`)
- Public data exposure (storage accounts with public blob access or an `allUsers`-style
  grant in the inventory → S3 account-level public-access block)
- Bastion / operator access (Azure Bastion → Systems Manager Session Manager, no instance)
  when `Microsoft.Network/bastionHosts` is in the inventory
- Observability cost shift (Azure Monitor / Log Analytics ingestion allowance vs CloudWatch
  always-free tier; pull the gap text from the `estimation-infra.json` observability line's
  `basis`, which states the assumed GB/mo — never say CloudWatch has no free tier)

Source: `aws-design.json` (`services[]` with `azure_type`, `aws_service`, `aws_config`),
`azure-resource-inventory.json`, `terraform/baseline.tf`, `estimation-infra.json`
observability line. The Gap/action column compares the two postures and names the action
(net-new control, mapped 1:1, review in production), not a bare "different".

### Appendix I — Assumptions, Exclusions, and Validation (`appendix-assumptions`, REQUIRED)

**Pricing confidence table:** domain, source, accuracy band, last updated — from
`estimation-infra.json` → `pricing_source` (`status`, `cache_last_updated`, `cache_region`,
`target_region`, `region_mismatch_note`) and `accuracy_confidence`. When
`pricing_source.region_mismatch` is true, say which region the rates are from and which the
design targets. Add an AI row from `estimation-ai.json` when it exists.

**Exclusions list** — one line each, every one that applies:

- Deferred services (`aws-design.json` → `deferred[]`, each with its `recommendation`; note
  when the deferred resource is cost-bearing on Azure today, per the Estimate's
  `deferred_bears_azure_cost` warning)
- Unpriced and partially priced lines (`pricing_source.services_with_missing_fallback`,
  `services_by_source.partial`, and the Estimate's `pricing_unavailable`, `pricing_partial`,
  `quantity_unavailable` warnings) — say the totals are floors when `is_floor` is true
- Windows licensing when `licensing_delta.fired` is true and `monthly_delta` is null
  (`licensing_cost_absent`) — name the vCPU count carried without a licence cost
- Azure egress and the other `migration_cost_considerations.categories[]` whose `monthly` is
  null, each with its `basis`
- Professional services / dual-run period (not modeled —
  `migration_cost_considerations.no_labor_costs`)
- Unexpired Azure reservations or savings plans (named, not quantified)
- Utilization-based right-sizing (**Known limitations**): read
  `cost_comparison.rightsizing_delta`. When `basis` is `none` — no RDfA report and no
  `az monitor` metrics were discovered — one line states that the delta is $0 because every
  SKU was mapped like-for-like, and that right-sizing needs an RDfA export or 14+ days of
  Azure Monitor P95 metrics in Discover. List each `declared_waste_found[]` entry (e.g. an
  idle App Service Plan carried as `idle: true`) as its own line. When utilization data was
  present (`basis` is `utilization` or `both`), list every EC2 / RDS mapping in
  `aws-design.json` whose `sizing_provenance` is not `measured`, grouped by reason: no
  `measured_utilization` on the source resource (the RDfA export or Azure Monitor window did
  not cover it); `sizing_provenance: "user_stated"` (kept at the size you asked for);
  `sizing_provenance: "model_prior"` (no `knowledge/` row covered the SKU, so the size is an
  inference, not a measurement). One line per group, naming the resources, so the reader
  knows which figures a later metrics capture would move.

**Terraform validation:** do NOT read `validation-report.json` and do NOT state a status,
policy verdict or provider version here. The main window writes that file in
`generate.md` § "Step: Run the phase" step 5, after this report is written, so a read now
returns nothing on a first run and the previous attempt's verdict on a re-run. Say that
Terraform fmt / init / validate and the `tf-best-practices` policy gate run after the report
is generated, and point the reader to `validation-report.json` (on an AI-only run its
`terraform_dir` is `ai-migration`) for the result of this run.

**Design and generation warnings:** `aws-design.json` → `warnings[]` (e.g. an
`availability_downgrade_from_source` finding where a ZoneRedundant source maps to single-AZ)
and `generation-warnings.json` → `skipped[]` with their reasons, so a resource that produced
no Terraform is accounted for in writing.

Source: `estimation-infra.json`, `aws-design.json`, `generation-warnings.json`,
`preferences.json`.

## Step 4: Draft-for-review footer (REQUIRED — `_assert`)

Every report carries a footer stating it is a draft for review, generated from the
migration plan, and that figures are estimates to validate before decisions.

> **Plan-share links are GATED OFF** (landing page not live). Do NOT emit a share link.

## Step 5: Validate the rendered report (REQUIRED — mandatory gate)

The prose above is not self-enforcing. Render the report from
`references/shared/report-decision-core.md` in **full** mode (or AI-only mode
when there is no infra track) before you write HTML. `REPORT_OK` is not a
substitute for that file: the shared validator rejects a report that has the
right section IDs but omits decision-core content the artifacts require
(verdict headline, hero metrics, per-track line, conditions, "What would flip
this", the specialist-engagement callout, the architecture section when the
design has clusters, assumptions after risks, a risk table, and the what-if
columns Region / HA / Compute / Arch when two or more scenarios exist).

Run the plugin's report validator, which is source-cloud-agnostic and already
present at plugin root — resolve it the same way the `tf-best-practices` policy
checker is resolved:

```bash
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --estimation-infra "$MIGRATION_DIR/estimation-infra.json" \
  --estimation-ai "$MIGRATION_DIR/estimation-ai.json" \
  --aws-design "$MIGRATION_DIR/aws-design.json" \
  --migration-dir "$MIGRATION_DIR"
```

Pass `--estimation-infra` / `--estimation-ai` / `--aws-design` only when those files exist in `$MIGRATION_DIR` (absolute paths — cwd must not be load-bearing). The validator does not read `aws-design.json` from `--migration-dir`; the architecture-section and specialist-callout checks fire only when `--aws-design` is passed, so omitting it on an infra run leaves those omissions undetected.

**AI-only path:** when there is no infra track (no `estimation-infra.json`), add `--mode ai_only` so the validator requires the AI-only section set (`decision-summary`, `exec-assumptions`, `exec-risks`, `appendix-ai`, `appendix-artifacts`, `appendix-config`, `appendix-glossary`) instead of the infra sections. Pass `--estimation-ai "$MIGRATION_DIR/estimation-ai.json"`; there is no `aws-design.json` on this path, so `--aws-design` is omitted.

Branch on the exit code, exactly as gcp-to-aws's `generate.md` does:

- `0` (`REPORT_OK`) — proceed.
- `1` (`REPORT_FAIL`) — **rename** the file to `migration-report.incomplete.html` (do not
  delete), emit every failure line to the user, and report incompleteness to the parent. Do NOT
  present a stub as a complete report.
- any other code — the validator did not run (e.g. `python3` unavailable). Tell the user
  validation was skipped; never record it as a pass.

The validator is stdlib-only. Do not ask the user to install Vale, Pa11y, axe, or Chromium, and
do not skip validation because such tooling is absent — it is never required.

## Status — implemented (build step: Generate)

Implemented, mirroring gcp-to-aws's `generate-artifacts-report.md` but honoring azure's
holistic contract: cluster-level rationale leads, per-resource table is an appendix,
cost floor / reservations / drift / deferrals / availability-downgrades / what-if all
surfaced, draft-for-review footer present.
