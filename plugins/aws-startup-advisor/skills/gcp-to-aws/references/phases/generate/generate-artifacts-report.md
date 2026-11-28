# Generate Phase: HTML Migration Report

> Loaded by generate.md AFTER generate-artifacts-docs.md completes.

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Generate a single self-contained HTML report (`migration-report.html`) combining an executive summary with detailed appendix. The HTML file uses inline CSS — no external dependencies required. Users can open it in any browser and use "Print to PDF" if a PDF is needed.

**Output:**

- `migration-report.html` — Self-contained HTML report with executive summary and detailed appendix

**Non-blocking:** If report generation fails after `VALIDATE_OK` (HTML build error only), log a warning and continue. Validation `GATE_FAIL` is **not** a silent skip — always surface to the user. Do NOT fail the Generate phase for report issues.

## Step 0: Validate Artifacts (Read Only)

Load and execute `shared/validate-artifacts.md` **before** building report content.

- Run all **required** checks (field presence only — do not rewrite artifact prose).
- On any `GATE_FAIL`: output failure lines to the user, **do NOT write** `migration-report.html`, **do NOT patch artifacts**, return to parent `generate.md`.
- On `VALIDATE_OK`: proceed to Step 1.

## Prerequisites

At least one of these must exist in `$MIGRATION_DIR/`:

- Design artifact: `aws-design.json`, `aws-design-ai.json`, or `aws-design-billing.json`
- Estimation artifact: `estimation-infra.json`, `estimation-ai.json`, or `estimation-billing.json`
- Generation plan: `generation-infra.json`, `generation-ai.json`, or `generation-billing.json`

If **none** exist: skip report generation. Output: "Skipping HTML report — no migration artifacts found."

## Data Sources

Gather data from all available artifacts. Each section below notes which artifact provides the data.

| Data Point                                     | Primary Source                                                                                                                                          | Fallback                                             |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| GCP services detected                          | `aws-design.json` clusters[].resources[]                                                                                                                | `aws-design-billing.json` services[]                 |
| AWS service mappings                           | `aws-design.json` resources[].aws_service                                                                                                               | `aws-design-billing.json` services[].aws_service     |
| Rationale per service                          | `aws-design.json` resources[].rationale                                                                                                                 | `aws-design-billing.json` services[].rationale       |
| Current GCP monthly cost                       | `estimation-infra.json` current_costs.gcp_monthly                                                                                                       | `estimation-billing.json`                            |
| Projected AWS monthly cost                     | `estimation-infra.json` projected_costs.aws_monthly_balanced                                                                                            | `estimation-billing.json`                            |
| Cost breakdown per service                     | `estimation-infra.json` projected_costs.breakdown                                                                                                       | `estimation-billing.json`                            |
| Cost tiers (premium/balanced/optimized)        | `estimation-infra.json` cost_comparison                                                                                                                 | —                                                    |
| Optimization opportunities                     | `estimation-infra.json` optimization_opportunities                                                                                                      | —                                                    |
| Migration shape (approach + duration drivers)  | `generation-infra.json` migration_plan.duration_drivers                                                                                                 | `generation-billing.json`                            |
| Top risks                                      | `generation-infra.json` risk_assessment                                                                                                                 | `generation-billing.json`                            |
| Human expertise flags                          | Design artifact resources[].human_expertise_required                                                                                                    | —                                                    |
| AI model mappings                              | `aws-design-ai.json`                                                                                                                                    | —                                                    |
| AI cost estimates                              | `estimation-ai.json`                                                                                                                                    | —                                                    |
| Migration decision / recommendation            | `estimation-infra.json` → `recommendation`                                                                                                              | `financial_summary.recommendation` (string fallback) |
| Complexity and path shape                      | `migration-preview.json` → `complexity_signal`, `duration_hint` (legacy `timeline_hint` accepted, week values only with the uncalibrated label)         | —                                                    |
| Key decisions ahead                            | `migration-preview.json` → `key_decisions_ahead`                                                                                                        | —                                                    |
| User configuration choices                     | `preferences.json` (read `.value` from wrapped fields)                                                                                                  | —                                                    |
| AI capabilities and integration                | `ai-workload-profile.json` → `models[]`, `integration`, `agentic_profile`                                                                               | —                                                    |
| Deferred services                              | Design artifact `resources[].aws_service == "Deferred — specialist engagement"`                                                                         | —                                                    |
| Observability cost callout                     | `estimation-infra.json` → `projected_costs.breakdown` (array: `service` contains "Observability"; object: key contains `observability` or `cloudwatch`) | —                                                    |
| **Combined AWS monthly run rate (infra + AI)** | Sum `estimation-infra.json` Balanced + `estimation-ai.json` → `cost_comparison.projected_bedrock_monthly` (or `recommended_model.monthly_cost`)         | —                                                    |
| **Security baseline component costs**          | `estimation-infra.json` → `projected_costs.breakdown.security_baseline.components` (GuardDuty, cloudtrail_s3, etc.)                                     | Static ranges in Appendix G when JSON absent         |
| **Terraform validation status**                | `validation-report.json` → `status`, `provider_version`                                                                                                 | —                                                    |
| **Pricing confidence / staleness**             | `estimation-infra.json` → `pricing_source`, `accuracy_confidence`                                                                                       | `estimation-ai.json` accuracy fields                 |
| **AI optimization opportunities**              | `estimation-ai.json` → `optimization_opportunities`, `optimized_projection`                                                                             | —                                                    |
| **What-if workshop scenarios**                 | `scenarios/index.json` + each `scenarios/scenario-NNN.json` manifest (`estimation_summary`, `preferences_subset`, optional `graviton_note`)             | — (omit section when workshop unused)                |

## Step 1: Build Executive Summary Section

**Load `references/shared/report-decision-core.md` and render it in `full` mode.** That file loads the vendored canonical core (`references/vendored/report/report-decision-core.md`) first and then supplies this skill's parameters and add-ons; together they are the single source of truth for every executive-summary section (Decision Summary through "What this assessment rests on") — verdict typography, baseline-quality/not-comparable rules, Activate wording, and readability conventions all live there. Do not restate or paraphrase its rules here.

Full-mode notes:

- `generation-infra.json` and `terraform/` exist on this path — use them where the core's sections prefer them (migration shape from `migration_plan.duration_drivers`, cluster order in the architecture diagram).
- **Replace, never patch:** if `decision-report.html` exists from a prior Decide run, leave it untouched and render `migration-report.html` fresh from the artifacts. Do not splice or extend the decision report's HTML. Note in the Generated Artifacts Catalog that the full report supersedes the decision report.

## Step 2: Build Detailed Appendix

**Load `references/vendored/report/report-appendix-skeleton.md` and build the appendix block from it.** That file is the single source of truth for the shared appendix build — the stable lettering, the appendix divider, the purpose, trigger, data sources, table shapes and content rules of Appendices A, B, B.1, C, E, F, G, H, I and J, and the post-write appendix self-check. Do not restate or paraphrase its rules here. If the file is missing, emit `GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing` and stop.

### Parameters

The skeleton's `⟨parameter⟩` values for this skill. The GCP-specific content the skeleton points at (Appendix B sizing columns, Appendix D, the Appendix F critical-default caveats, the Appendix G control rows, the Appendix I known limitations) follows under the GCP add-on headings below.

| Parameter                                                                        | Value                                                                                                                                                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ⟨source_cloud⟩                                                                   | GCP                                                                                                                                                                                                                                                                                                                                                                                        |
| ⟨report_mode⟩                                                                    | `full`                                                                                                                                                                                                                                                                                                                                                                                     |
| ⟨precheck_owner⟩ / ⟨precheck_skill_flag⟩                                         | In-fragment: Step 0 above loads `shared/validate-artifacts.md` / n/a (no `--skill` flag; the fragment runs the checks itself)                                                                                                                                                                                                                                                              |
| ⟨appendices_rendered⟩                                                            | A, B, C, E, I, J required; B.1 conditional (`optimization_opportunities[]` non-empty); D conditional (AI artifacts exist); F conditional (`preferences.json` exists); G conditional (infra track ran, `baseline.tf` emitted); H conditional (infra track ran). No declared omissions.                                                                                                        |
| ⟨appendix_header_text⟩                                                           | "Appendix: Detailed Migration Analysis"                                                                                                                                                                                                                                                                                                                                                    |
| ⟨footer_text⟩                                                                    | "Generated by GCP to AWS Migration Advisor — draft for review; verify figures against source JSON artifacts before executive sign-off." (Step 3 HTML structure)                                                                                                                                                                                                                             |
| ⟨extra_anchors⟩                                                                  | none — the decision core's `aws_monthly_balanced` / `current_monthly` (Step 4 item 15)                                                                                                                                                                                                                                                                                                     |
| ⟨accounting_ledger_field⟩ / ⟨accounting_split_sentence⟩ / ⟨accounting_location⟩  | n/a — gcp-to-aws writes no generation ledger; the PRIMARY-services headline rule in `references/shared/report-decision-core.md` § 1 governs counts                                                                                                                                                                                                                                         |
| ⟨validator_invocation⟩                                                           | The command block in Step 4 (`--estimation-infra`, `--estimation-ai`, `--aws-design`, `--migration-dir`; no `--profile`)                                                                                                                                                                                                                                                                  |
| ⟨design_mapping_source⟩                                                          | `aws-design.json` `clusters[].resources[]`; fallback `aws-design-billing.json` `services[]`                                                                                                                                                                                                                                                                                                 |
| ⟨how_we_chose_vocabulary_ref⟩                                                    | `design-refs/fast-path.md` → User-facing vocabulary                                                                                                                                                                                                                                                                                                                                        |
| ⟨service_row_extras⟩                                                             | If the mapping was **Tailored to your setup** (`inferred`) and `rubric_applied` is present: list the 6 criteria evaluations (appendix detail — optional in executive summary)                                                                                                                                                                                                              |
| ⟨cost_breakdown_source⟩                                                          | `estimation-infra.json` `projected_costs.breakdown`                                                                                                                                                                                                                                                                                                                                        |
| ⟨mandatory_breakdown_rows⟩                                                       | compute, database, storage, networking; **security_baseline** (`mid` cost AND component sub-rows from `components`, e.g. GuardDuty, cloudtrail_s3, budgets); **observability** (`mid` and `note` — GCP free-tier comparison); supporting (Secrets Manager, ECR, etc.)                                                                                                                      |
| ⟨baseline_breakdown⟩                                                             | `current_costs.breakdown` — compute/database/storage/networking/other vs infra total                                                                                                                                                                                                                                                                                                       |
| ⟨floor_fields⟩                                                                   | n/a — the GCP estimate carries no `is_floor` / unpriced-line fields                                                                                                                                                                                                                                                                                                                        |
| ⟨extra_cost_columns⟩                                                             | "Sizing basis" — see GCP add-on § Appendix Section B below                                                                                                                                                                                                                                                                                                                                 |
| ⟨optimization_sources⟩ / ⟨ri_sp_eligibility_ref⟩                                 | Infra (`estimation-infra.json`) + AI (`estimation-ai.json`, `available` sequencing from the `optimization_opportunities[]` rows bedrock-migration-assessment writes) / `references/shared/ri-sp-eligibility.md`                                                                                                                                                                                                                                 |
| ⟨phase_order_source⟩                                                             | The generation plan's `migration_plan` stages (`generation-infra.json`, fallback `generation-billing.json`)                                                                                                                                                                                                                                                                                 |
| ⟨scripts_list⟩                                                                   | The `scripts/` the run emitted, in plan order                                                                                                                                                                                                                                                                                                                                              |
| ⟨cutover_strategy_fields⟩                                                        | n/a — the GCP preferences record no cutover-strategy field; the plan's phase descriptions carry the strategy                                                                                                                                                                                                                                                                              |
| ⟨rollback_source⟩ / ⟨rollback_rows⟩                                              | The generation plan's rollback triggers and steps / one row per track the plan names                                                                                                                                                                                                                                                                                                      |
| ⟨ai_appendix_spec⟩                                                               | GCP add-on § Appendix Section D below                                                                                                                                                                                                                                                                                                                                                      |
| ⟨pack_extras⟩                                                                    | `ai-migration/` adapter files when the AI track ran — see the conditional AI artifacts table in the GCP add-on § Appendix Section E below                                                                                                                                                                                                                                                  |
| ⟨data_artifacts⟩                                                                 | The data-artifacts table in the GCP add-on § Appendix Section E below (`preferences.json`, `ai-workload-profile.json`, `gcp-resource-inventory.json`, `estimation-infra.json`, `aws-design.json`)                                                                                                                                                                                       |
| ⟨preferences_groups⟩                                                             | `design_constraints`, `ai_constraints`, and `startup_constraints` (when present)                                                                                                                                                                                                                                                                                                           |
| ⟨preferences_schema_ref⟩                                                         | `references/shared/schema-preferences.md`                                                                                                                                                                                                                                                                                                                                                  |
| ⟨critical_default_caveats⟩                                                       | GCP add-on § Appendix Section F below (Q2 / Q3 / Q6 / Q11)                                                                                                                                                                                                                                                                                                                                 |
| ⟨baseline_controls_table⟩                                                        | The eight-row table in the GCP add-on § Appendix Section G below                                                                                                                                                                                                                                                                                                                           |
| ⟨security_equivalent_label⟩ / ⟨security_extra_columns⟩                           | "GCP equivalent" / "Threat mitigated"                                                                                                                                                                                                                                                                                                                                                      |
| ⟨budget_limit_formula⟩                                                           | n/a — the GCP `baseline.tf` budget alert is listed as a control row; this spec states no formula                                                                                                                                                                                                                                                                                           |
| ⟨compliance_field⟩                                                               | `preferences.json` → `design_constraints.compliance.value`                                                                                                                                                                                                                                                                                                                                 |
| ⟨cost_guardrail_rows⟩                                                            | The two-row guardrails table in the GCP add-on § Appendix Section G below                                                                                                                                                                                                                                                                                                                 |
| ⟨opt_out_procedure⟩                                                              | Run `terraform apply` on `baseline.tf`. To skip: delete `baseline.tf` before applying. See `terraform/README.md` for details.                                                                                                                                                                                                                                                              |
| ⟨gap_source_names⟩                                                               | firewall rules → security groups; service accounts → IAM roles; Cloud Audit Logs → CloudTrail; SCC optional → GuardDuty in baseline.tf; public GCS → S3 (if public GCS/S3 detected in design); GCP larger free tier vs CloudWatch always-free tier (e.g. 50 GB GCP logging vs 5 GB CloudWatch always-free)                                                                                   |
| ⟨gap_extra_rows⟩ / ⟨observability_note_field⟩                                    | none / `note`                                                                                                                                                                                                                                                                                                                                                                              |
| ⟨pricing_source_fields⟩                                                          | `estimation-infra.json` → `pricing_source`, `accuracy_confidence`; fallback `estimation-ai.json` accuracy fields                                                                                                                                                                                                                                                                           |
| ⟨exclusion_extras⟩                                                               | GCP egress when `migration_cost_considerations.billing_data_available === false`                                                                                                                                                                                                                                                                                                           |
| ⟨rightsizing_limitations⟩                                                        | GCP add-on § Appendix Section I below ((i) / (ii) / (iii))                                                                                                                                                                                                                                                                                                                                 |
| ⟨terraform_validation_rule⟩                                                      | GCP add-on § Appendix Section I below (`validation-report.json` when present)                                                                                                                                                                                                                                                                                                              |
| ⟨warnings_sources⟩                                                               | Design warnings, including the Elastic Beanstalk platform-branch warning — GCP add-on § Appendix Section I below                                                                                                                                                                                                                                                                           |
| ⟨glossary_examples⟩                                                              | monthly run rate, DMS, OAI, RTO, CUD, SCC, IMDSv2, P95, RAG (Step 3 readability rule 4)                                                                                                                                                                                                                                                                                                    |

### Declared exceptions

None. gcp-to-aws follows the skeleton's default appendix set with no `--profile`.

**GCP add-ons.** The sections below carry the GCP-specific content the parameter table points at; each keeps its canonical letter.

### Appendix Section B — GCP columns and sizing basis

**Per-service cost breakdown table** with columns: Service Category, AWS Service, Monthly Cost (Balanced), Sizing basis, Calculation/Notes.

**Sizing basis column:** from the breakdown entry's `sizing_basis` (`estimate-infra.md` Part 2D): `Measured (30-day p95)` for an EC2 or RDS row whose mapping has `sizing_provenance: "measured"`, with the like-for-like size and `like_for_like_monthly` in a `<small>`; `Declared` with the mapping's `declared_reason` in a `<small>` (`insufficient data`, `memory unavailable`, `idle`, `group member`, `user exempt`, `conservative`) for the rest; `—` for rows that carry no instance size (S3, SQS, networking). When `projected_costs.sizing_bands` is present, add one line under the table: "Like-for-like **$L**/mo vs right-sized **$R**/mo (N resources measured; basis)" from `like_for_like_monthly`, `right_sized_monthly`, `measured_resources` and `basis`, no recomputation.

### Appendix Section D — AI Migration (conditional)

**Only include if `aws-design-ai.json` or `estimation-ai.json` exists.**

**D.1 — AI Stack Detected:**

Pull from `ai-workload-profile.json` when present:

| Aspect              | Detected                                                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------------------------- |
| AI source           | `summary.ai_source`                                                                                        |
| Models              | `models[].model_id` — comma-separated list                                                                 |
| Capabilities in use | `integration.capabilities_summary` — keys where value is `true`                                            |
| Integration pattern | `integration.pattern`                                                                                      |
| Gateway/router      | `integration.gateway_type` or "None (direct SDK)"                                                          |
| Frameworks          | `integration.frameworks` or "None"                                                                         |
| Agentic             | If `agentic_profile` exists: "Yes — [framework], [orchestration_pattern], [agent_count] agents"; else "No" |

**D.2 — Why Bedrock (conditional):**

Show this section when `aws-design-ai.json` → `ai_architecture.honest_assessment` contains ANY of: `"recommend_stay"`, `"weak_migrate"`, or `"moderate_migrate"` where any model's Bedrock price exceeds the source provider price.

> **Why migrate to Bedrock when [source] may be cheaper per token?**
>
> - **Single-vendor billing:** One AWS bill instead of separate provider invoices
> - **VPC-private inference:** Model calls stay in your VPC — no data over public internet
> - **IAM access control:** No API keys to rotate; permissions follow your AWS IAM model
> - **Model evaluation:** A/B test models with Bedrock's built-in evaluation framework
> - **Guardrails:** Content filtering and PII detection at the platform level
> - **Commitment pricing:** Provisioned Throughput for predictable costs at scale — no-commit, 1-month, or 6-month terms (not a 1-year/3-year Reserved Instance or Savings Plan; distinct product, distinct terms), worth evaluating only once traffic is sustained and predictable, not at migration time
>
> These benefits matter most when: you handle sensitive data, need AI call audit trails, or want to consolidate vendors.

**D.3 — Model Mappings:**

- Model mappings (GCP model to AWS Bedrock model)
- AI cost estimates

**D.4 — Migration approach:**

- Migration approach (adapter pattern, A/B testing)

**D.5 — Post-migration AI cost optimization (conditional):**

**Only include if `generation-ai.json` exists in `$MIGRATION_DIR/` (AI track ran).**

Not all of these require waiting until migration is validated and stable — figures below are AWS's own published numbers where available (the `optimization_opportunities[]` rows of `estimation-ai.json`, which bedrock-migration-assessment writes, are the source of truth for these; do not restate different figures here):

| Optimization               | Estimated savings                                                                        | When to apply                                                                                               | Prerequisite                                                                                                                                                                      |
| -------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prompt caching             | Up to 90% on cached input tokens (AWS-published), workload- and cache-hit-rate dependent | Available Day 1 — when prompts have long repeated context                                                   | Minimum ~1K–4K tokens cacheable prefix; per-model minimums and TTL apply                                                                                                          |
| Multi-model tiered routing | 60–87% (plugin estimate)                                                                 | Available Day 1 (design-time choice) — high/very-high volume, `tiered_strategy` in design                   | Same model family available in 2+ cost tiers at design time                                                                                                                       |
| Intelligent Prompt Routing | Up to 30% (AWS-published ceiling)                                                        | After 2+ weeks of production traffic (plugin recommendation, not an AWS-imposed minimum — see caveat below) | Same model family in multiple tiers (default: Anthropic or Meta Llama; other models via configurable routers) — **does not apply to a Gemini-only or OpenAI-only Bedrock design** |
| Model distillation         | Up to ~75%                                                                               | After 30+ days of stable, high-volume production                                                            | Stable prompts, evaluation dataset, sufficient call volume                                                                                                                        |

**Intelligent Prompt Routing vs. Multi-model tiered routing are two distinct mechanisms, not the same lever under two names:** Intelligent Prompt Routing is Bedrock's own automatic per-request router (AWS product feature, "up to 30%" is AWS's published ceiling — but the "wait 2+ weeks" guidance is this plugin's own caution, not an AWS requirement); Multi-model tiered routing is this plugin's design-time pattern of manually splitting traffic across model tiers ("60-87%" is this plugin's own estimate for that pattern, not an AWS-published figure). Do not merge these into one row.

**Not all of these are "post-migration" in the same sense.** Prompt caching and Multi-model tiered routing are usable immediately — do not gate them behind a stability period or present them only as a "Month 2-3" item; a founder reading this section should see they can adopt these on day one. Intelligent Prompt Routing (needs 2+ weeks of production traffic to validate routing quality) and Model distillation (needs 30+ days of stable, high-volume production) are the two levers that genuinely require waiting — surface only those two as a "Month 2-3+" roadmap item. Do not block migration on any of these.

**Prompt caching caveat:** Caching only helps for long, repeated context windows, and the "up to 90%" figure is a ceiling — actual savings depend on cache hit rate and how much of the prompt is cacheable. Evaluate actual prompt patterns before assuming savings.

**Full detail:** Open `ai-workload-profile.json` in this directory.

Source: `ai-workload-profile.json`, `aws-design-ai.json`, `estimation-ai.json`

### Appendix Section E — GCP data and AI artifact tables

**Data artifacts (for detailed review):**

| Artifact                      | Contents                                                   |
| ----------------------------- | ---------------------------------------------------------- |
| `preferences.json`            | All migration configuration choices and their sources      |
| `ai-workload-profile.json`    | Full AI model inventory, capabilities, evidence            |
| `gcp-resource-inventory.json` | Complete GCP resource inventory with classifications       |
| `estimation-infra.json`       | Detailed cost model, recommendation, per-service breakdown |
| `aws-design.json`             | Full architecture design with rationale per service        |

**AI migration artifacts (conditional — only list if they exist on disk):**

| Artifact                                                    | Description                                                                       |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `ai-migration/STARTUP_PROGRAMS.md` or `STARTUP_PROGRAMS.md` | AWS Activate credit tiers, application URLs, eligibility guidance                 |
| `ai-migration/setup_bedrock.sh`                             | Bedrock model access setup, plus the Bedrock budget and cost anomaly monitor (dry run unless `--execute`) |
| `ai-migration/test_comparison.py`                           | A/B comparison harness for source vs Bedrock quality                              |

### Appendix Section F — Your Configuration (`appendix-config`, conditional)

**All five skeleton columns are required here, including Source signal:** GCP
constraint objects carry a `source` field (`terraform:…`, `default:Q16`), so the
column the skeleton marks optional is rendered on every row for this skill.

**Critical-default caveats (required when present):** For a defaulted constraint
whose question ID appears in `metadata.questions_defaulted`, render the matching
caveat below. The unknown/missing-spend and unknown-compliance rules also apply
regardless of `chosen_by` or question metadata:

- `compliance` (Q2): render a warning callout: _"⚠ Compliance was not explicitly confirmed. The security baseline assumes no regulatory requirements. If SOC 2, PCI, HIPAA, or FedRAMP applies, re-run Clarify or manually add controls."_ **Also fire this callout whenever `compliance.value` contains `"unknown"`** (regardless of `chosen_by` — covers both "I don't know" answers and defaulted runs). `"unknown"` never triggers the Section 4 compliance-controls note or any compliance-specific architecture.
- `gcp_monthly_spend` (Q3): when its value is `"unknown"` or the key is absent,
  render: _"GCP spend is unconfirmed. No spend band has been assumed. The report
  shows AWS costs; a full cost comparison is unavailable until a confirmed
  source baseline is provided."_ Show this for explicit user answers as well
  as skipped/defaulted questions. A separately calculated inventory estimate
  remains labelled as incomplete standing charges, not confirmed spend.
- `availability` (Q6): render a warning callout: _"⚠ Database availability was assumed (Multi-AZ) — the user never confirmed it. This assumption roughly doubles the database line vs single-AZ. Confirm the availability requirement (or compare a single-AZ scenario in the what-if workshop) before treating the database estimate as final."_

Place these callouts at the top of Appendix F, before the table, so they're immediately visible.

The same missing-baseline rule applies to `cloud_run_monthly_spend` (Q11):
unknown never means zero or `$100–$500`. Preserve `"unknown"` in the configuration
table. When `current_costs.source` is `"unavailable"` or its amount is null,
render source cost, savings, percentage changes, and ROI comparisons as
**Unavailable**, not `$0`, and do not manufacture a budget to fill metric cards.
Use the estimate's baseline source and caveat consistently in the executive
summary and cost appendix.

### Appendix Section G — Security Capabilities

Control rows for the skeleton's Appendix G table (⟨baseline_controls_table⟩):

| Control                | What it does for you                                                                | Threat mitigated                      | GCP equivalent                             | Monthly cost |
| ---------------------- | ----------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------ | ------------ |
| GuardDuty              | Detects compromised credentials, crypto mining, unusual API patterns within minutes | Credential theft, resource hijacking  | Security Command Center (paid Premium)     | ~$2–25/mo    |
| CloudTrail             | Immutable audit log of every API call — who did what, when                          | Unauthorized changes, compliance gaps | Cloud Audit Logs (free for admin activity) | ~$0.50–3/mo  |
| IMDSv2 enforcement     | Blocks SSRF attacks from stealing instance/container credentials                    | Server-side request forgery           | N/A (GCP uses different metadata model)    | $0           |
| Access Analyzer        | Alerts when IAM policies or S3 buckets become publicly accessible                   | Accidental public exposure            | IAM Recommender (partial)                  | $0           |
| EBS default encryption | All storage volumes encrypted at rest by default                                    | Data exposure from stolen disks       | Default encryption (GCP default)           | $0           |
| Budget alerts          | Email when spend exceeds threshold                                                  | Bill shock from runaway resources     | GCP Budgets (free)                         | $0           |
| S3 Block Public Access | Account-wide prevention of any bucket being made public                             | Accidental data leaks                 | Uniform bucket-level access (opt-in)       | $0           |
| IAM password policy    | 14-char min, rotation, complexity for console users                                 | Weak password compromise              | Cloud Identity policies                    | $0           |

**Compliance-conditional (only when SOC 2/PCI/HIPAA/FedRAMP declared in preferences):**

| Control             | What it adds                                           | Compliance gap covered             | Monthly cost |
| ------------------- | ------------------------------------------------------ | ---------------------------------- | ------------ |
| AWS Config          | Continuous recording of resource configuration changes | Change audit trail for SOC 2 / PCI | ~$2–10/mo    |
| Security Hub + FSBP | Automated security checks against AWS best practices   | Baseline posture scoring           | ~$1–15/mo    |

**Cost guardrails (when `$MIGRATION_DIR/ai-migration/setup_bedrock.sh` exists and contains the step `== 6. Bedrock budget and cost anomaly monitor`):**

bedrock-migration-assessment's Generate writes both controls into that script, and they exist only after the user runs it with `--execute`; say so under the table.

| Control                         | What it does for you                                                    | Threat mitigated                                   | GCP equivalent                                 | Monthly cost |
| ------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------- | ------------ |
| Bedrock budget (1.5× projected) | Monthly budget at the script's `BUDGET_USD` default (1.5× the projected AI cost, at least $10); emails at 80% actual and 100% forecast when run with `--alert-email` | Runaway token spend from buggy retry loops         | GCP Budgets (free, but no per-service scoping) | $0           |
| Cost anomaly detection          | Daily email for a spend anomaly whose impact is 50% or more of expected spend, when run with `--alert-email` (~24h data lag) | Gradual cost creep, unexpected model-price changes | None (no GCP per-service anomaly equivalent)   | $0           |

Read the budget row from the script's variable lines, `BUDGET_USD="${BUDGET_USD:-<amount>}"` and `BUDGET_SERVICES="${BUDGET_SERVICES:-<services>}"`. When either default is empty, the script creates no budget: replace the budget row's "What it does for you" with "no budget until you export `BUDGET_USD`" (empty amount) or "no budget until you export `BUDGET_SERVICES` with the service names Cost Explorer shows" (empty services), and quote the matching line from `ai-migration/README.md`. Keep the anomaly row. Never add an Inference profiles row: the script creates no inference profile.

**What the baseline does NOT cover:** the canonical list (skeleton § Appendix G).

Source: static content + `preferences.json` compliance values

### Appendix Section I — Known limitations (GCP right-sizing)

**Exclusions list:** the canonical items (skeleton § Appendix I) plus the GCP-specific lines below.

- GCP egress when `migration_cost_considerations.billing_data_available === false`
- Utilization-based right-sizing (**Known limitations**, one line per affected resource, each naming the action that would unlock measured sizing), three-way on the inventory's `utilization` objects (`coverage` is derived from CPU only, so a numeric `memory`, `disk_bytes_used` or `connections` block can exist beside `coverage: no_data`; a metric block is numeric when it has `p95` rather than `status`):
  - (i) at least one resource carries `utilization` whose `coverage` is not `no_data` (live discovery with Cloud Monitoring): list every EC2 / RDS mapping that is not fully measured, grouped by reason —
    `coverage: "insufficient"` ("N of M hourly samples; re-run discovery after the VM has 30 days of history"); `declared_reason: "memory_unavailable"` ("install the Ops Agent on these N VMs and re-run discovery"); `burst: true` ("sized onto a burstable `t4g`/`t3` from sustained hourly means — validate with a load test; Unlimited-mode charges are not priced", or, when it stayed declared, why); `idle: true` ("decommission candidate, kept at declared size — confirm before migrating"); `declared_reason: "skipped_group_member"` ("managed-instance-group member — right-size the group template, follow-up"); `declared_reason: "user_exempt"` ("kept at declared size at your request"); `declared_reason: "conservative"` (one line for all: "cost-optimization appetite Conservative — change it in Clarify to right-size"); `sizing_note: "memory_bound"` ("memory p95 keeps it at like-for-like; CPU alone would allow smaller"); `sizing_note: "memory_saturated"` ("Cloud SQL memory reads saturated (page cache); the declared class is the floor, not evidence of need"); `sizing_note: "burstable_baseline_exceeded"` ("sustained load exceeds every burstable baseline at or below like-for-like; expect throttling or move to a fixed family"). Add one line that IOPS were not measured for right-sized RDS storage (`storage.basis: "measured"`), and one line per `rds_proxy: true` database ("RDS Proxy recommended for N: connections p95 exceeds the class limit — not priced in this estimate and not in the generated Terraform; add it by hand or raise `max_connections` in a parameter group").
  - (ii) every `utilization.coverage` is `no_data` but at least one resource has a numeric `memory`, `disk_bytes_used` or `connections` block: state that partial 30-day utilization was captured (name the metrics that have numeric blocks, and that CPU coverage is unavailable), so every EC2 / RDS mapping stays at its declared / like-for-like size; re-run discovery once the VMs have 30 days of CPU history to unlock measured sizing.
  - (iii) no resource carries `utilization`, or no `utilization` object anywhere has a numeric block (the Monitoring API was disabled or every monitoring row was skipped): one line states that right-sizing requires live discovery with Cloud Monitoring read access, so a Terraform-only user knows what they are missing and how to get it.

**Terraform validation:** from `validation-report.json` when present (`status`, provider version).

Source: estimation artifacts, `validation-report.json`, design warnings. A design warning about an Elastic Beanstalk platform branch (a service whose language version had a retired branch) is listed by service with the source version and the branch selected.

## Step 3: Generate HTML

### Pre-Write Sanity Check (mandatory)

Immediately before writing the file, **re-read from disk**:

1. `estimation-infra.json` → `recommendation.path_label` present OR Step 1 fallback documented.
2. `migration-preview.json` → `complexity_signal` present (if file exists).
3. Assembled HTML string contains `<section id="decision-summary">`.

If any check fails: emit `GATE_FAIL | phase=generate | field=<path> | reason=missing`, do **not** write the file, return to parent.

Write the complete HTML to `$MIGRATION_DIR/migration-report.html`.

### HTML Structure (required section IDs)

The output MUST include these `id` attributes (content from Steps 1–2; gates check **presence only**):

| Section ID              | Content                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------ |
| `decision-summary`      | Section 0 — Migration Decision Summary                                                           |
| `exec-services`         | Primary services summary                                                                         |
| `exec-costs`            | Cost comparison headline / tier table                                                            |
| `exec-optimization`     | Cost Optimization (SP / RI) — required when `optimization_opportunities[]` is non-empty          |
| `exec-timeline`         | Migration shape (stages + drivers)                                                               |
| `exec-risks`            | Top risks                                                                                        |
| `appendix-services`     | Appendix A                                                                                       |
| `appendix-costs`        | Appendix B                                                                                       |
| `appendix-optimization` | Savings Plans / RI opportunity table — required when `optimization_opportunities[]` is non-empty |
| `appendix-steps`        | Appendix C                                                                                       |
| `appendix-artifacts`    | Appendix E                                                                                       |

Conditional IDs (include when their trigger applies): `exec-share`, `exec-tco`, `exec-architecture`, `exec-security-teaser`, `exec-optimization`, `what-if-scenarios`, `appendix-ai`, `appendix-config`, `appendix-security`, `appendix-security-gap`, `appendix-assumptions`, `appendix-optimization`, `appendix-glossary`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GCP to AWS Migration Assessment</title>
  <style>
    /* All CSS inline — see CSS specification below */
  </style>
</head>
<body>
  <div class="report">
    <h1>GCP to AWS Migration Assessment</h1>
    <p class="subtitle"><!-- project · run id · date --></p>
    <div class="executive-summary">
      <section id="decision-summary"><!-- verdict + hero metrics FIRST — the thesis before any menu --></section>
      <nav class="toc" id="toc" aria-label="Table of contents"><!-- AFTER the decision summary, never before --></nav>
      <!-- <section id="exec-share"> when a monthly estimate exists -->
      <section id="exec-services"><!-- Primary services --></section>
      <section id="exec-costs"><!-- Cost headline --></section>
      <!-- <section id="exec-optimization"> when optimization_opportunities[] is non-empty -->
      <!-- <section id="what-if-scenarios"> when scenarios/index.json has ≥2 entries -->
      <section id="exec-timeline"><!-- Timeline --></section>
      <section id="exec-risks"><!-- Top risks --></section>
    </div>
    <div class="appendix">
      <section id="appendix-services"><!-- Appendix A --></section>
      <section id="appendix-costs"><!-- Appendix B --></section>
      <!-- <section id="appendix-optimization"> when optimization_opportunities[] is non-empty -->
      <section id="appendix-steps"><!-- Appendix C --></section>
      <!-- <section id="appendix-ai"> when AI artifacts exist -->
      <section id="appendix-artifacts"><!-- Appendix E --></section>
      <!-- <section id="appendix-config"> when preferences.json exists -->
      <!-- <section id="appendix-security"> Appendix G -->
      <section id="appendix-glossary"><!-- Final appendix: terms used in this report --></section>
    </div>
    <footer>
      Generated by GCP to AWS Migration Advisor — draft for review; verify figures against source JSON artifacts before executive sign-off.
    </footer>
  </div>
</body>
</html>
```

### CSS Specification

The inline CSS is a **readability contract**, not a loose example. Full and
decision reports MUST use the same shell and selectors so visual quality does
not drift between phases. The validator checks the required selectors and
layout properties. Keep the report self-contained: no external fonts,
stylesheets, scripts, or images.

**Layout:**

- `:root`: define reusable semantic colors for page background, surface,
  text, muted text, border, AWS navy, link blue, success, warning, and danger.
- `*`: `box-sizing: border-box`
- `body`: system font stack; margin `0`; color `#1f2328`; background
  `#f6f8fa`; line-height `1.55`; font-size `15px`
- `.report`: max-width `1040px`; margin `0 auto`; padding
  `2rem 1.5rem 4rem`
- `section`: white surface, `1px` border, `8px` radius, padding
  `1.25rem 1.5rem`, margin-bottom `1rem`, and `scroll-margin-top: 1rem`.
  Every executive and appendix section is therefore a distinct card instead
  of prose floating on a white page.
- `.executive-summary` and `.appendix`: use normal document flow; never nest
  `<section>` elements.
- `.appendix-header`: dark AWS-navy visual divider before the detailed
  appendix. It is a `<div>`, not a `<section>`, so section validation remains
  unambiguous.

**Typography:**

The sizes below form a deliberate five-step scale (~1.25 ratio on a `15px`
base): **2rem** display (verdict headline, hero metric values) → **1.85rem**
page title → **1.3rem** section headings → **1.05rem** subheadings →
**0.88rem** table/data text → **0.78rem** captions and labels. When adding a
new element, pick the nearest step — do not invent in-between sizes; a report
whose type sits on a scale reads as designed, one with ad-hoc sizes reads as
assembled.

- `h1`: font-size `1.85rem`; margin-bottom `0.25rem`; border-bottom
  `3px solid #ff9900`; padding-bottom `0.5rem`
- `h2`: font-size `1.3rem`; margin-top `0`; border-bottom `1px solid` the
  border color; padding-bottom `0.45rem`
- `h3`: font-size `1.05rem`; margin-top `1.1rem`; color `#424a53`
- `p`, `ul`, and `ol` inside cards: compact vertical rhythm; default bottom
  margin no larger than `0.8rem`
- `.subtitle` and secondary labels: muted color, smaller type
- `.verdict-headline`: large (`2rem`) typography-first statement with a
  visible accent; meaning must still be carried by its words, not color
- `.verdict`: positive recommendation callout with pale green background,
  green border, and stronger left border. Use it only for go/migrate outcomes;
  stay/defer recommendations use the warning/neutral callout treatment.
- `.share-card`: pale blue or neutral surface, `1px` border, stronger left
  border, `0.95rem` body type, and no controls. It holds the copy-ready
  `exec-share` paragraph; the words carry all meaning.
- links: visible blue with underline on hover and a high-contrast
  `:focus-visible` outline for keyboard readers
- **Contrast floor (WCAG AA):** every text/background pair — including muted
  captions, badge text on tinted backgrounds, and callout text — meets
  **4.5:1** (3:1 for large display text). The current palette passes; this
  line makes it a requirement, not a coincidence. Never trade contrast for a
  softer look.
- **Interaction discipline:** interactive elements (links, `<summary>`,
  `.toplink`) get `cursor: pointer` and a `150–300ms` CSS transition on
  hover/focus color changes — no snapping. **Entrance, scroll-triggered, and
  ambient animations are banned:** they read as AI-generated in a document,
  do nothing in print, and this is a report, not a landing page.

**Tables:**

- `table`: width `100%`; border-collapse collapse; margin
  `0.75rem 0 1rem`; background white; font-size `0.88rem`
- `th`, `td`: **horizontal rules only** — `border: 0; border-bottom: 1px solid` the border color; `0.45rem 0.65rem` padding, left/top alignment. Never add vertical cell borders: grid + zebra + hover is three redundant separation cues (data-ink)
- `thead th`: heavier bottom border (`2px`) to anchor the header row
- `th`: subtle gray background and semibold text (do not use a large dark
  header block for every table)
- `td.num, th.num`: `text-align: right; font-variant-numeric: tabular-nums` — apply `class="num"` to **every numeric column** (currency, hours, weeks, percentages) and its header so magnitudes align for scanning; label/prose columns stay left-aligned
- alternating body rows use a subtle background; hover must not be the only
  way to distinguish rows
- on viewports below `700px`, tables become horizontally scrollable rather
  than shrinking text to an unreadable size

**Cards (for executive summary metrics):**

- `.metrics`: CSS grid using
  `repeat(auto-fit, minmax(180px, 1fr))`, gap `0.75rem`, margin `0.85rem 0`
- `.metric`: white or subtly tinted surface, `1px` border, `8px` radius,
  padding `0.85rem 1rem`; never use inline-block cards with uneven wrapping
- `.metric strong`: block, `1.45rem`, compact line-height
- `.metric span`: muted `0.78rem` uppercase label with slight letter spacing
- `.metric small`: block, muted supporting context
- Put the decision's 3–5 most useful numbers in this grid: combined AWS
  monthly run rate (or the single-track estimate), timeline, per-track costs,
  effort. Do not duplicate the same number merely to fill a card.
- `.metric-hero`: white background, `2px` accent border (e.g. `#0d7377`),
  value ~`1.9rem` — the one or two **primary** decision metrics (run rate,
  timeline) render first with this treatment; the reader should not have to
  rank the numbers themselves.
- **Activate credits are never a metric card** — a credit offer is a
  call-to-action with a link, not a measurement; rendering it in the grid
  gives it false equivalence with the run rate. It renders as the 💡 callout
  (see the Activate callout rules in `report-decision-core.md`), with the
  clickable apply link (`https://aws.amazon.com/startups/credits/`) inside.
- `.chip-warn`: inline pill (pale yellow background, amber border, small bold
  text) for per-metric caveats — e.g. "⚠ not comparable" on the GCP baseline
  card (see the not-comparable rendering rule in `report-decision-core.md`).
- When a supported comparable baseline produces a savings value, apply the
  green `.savings` class to the numeric value. Use `.increase` for a supported
  increase. Never color absolute costs or non-comparable deltas as savings.

**Cost comparison highlight:**

- `.savings`, `.cost-savings`: green and semibold/bold for supported savings
- `.increase`, `.cost-increase`: red and semibold/bold for supported increases

**Warning callout (for human_expertise_required):**

- `.callout`: shared padding, radius, margin, and readable font size
- `.callout-warning`, `.callout-info`, `.callout-ok`: distinct pale
  backgrounds plus borders. Use an icon or explicit label as well as color.

**Confidence badges (visible text = user-facing vocabulary, not JSON):**

- `.badge`: display inline-block; padding 2px 8px; border-radius 12px; font-size 0.75rem; font-weight 600
- `.badge-deterministic`: background #e6f4ea; color #137333 — label **Standard pairing**
- `.badge-inferred`: background #fef7e0; color #b05a00 — label **Tailored to your setup**
- `.badge-billing`: background #fce8e6; color #c5221f — label **Estimated from billing only**

**Risk badges (Top Risks table):**

- `.badge-impact-critical`: background #fce8e6; color #c5221f
- `.badge-impact-high`: background #fef7e0; color #b05a00
- `.badge-like-low`: background #f1f3f4; color #545b64
- `.badge-like-medium`: background #fef7e0; color #b05a00

**Navigation aids:**

- `nav.toc` carries `id="toc"`
- `h2 .toplink`: float right; small, muted, no underline — every section `<h2>` ends with `<a class="toplink" href="#toc">↑ contents</a>`; hidden in `@media print`
- `details.reading-guide`: muted collapsible for how-to-read explanations that would otherwise sit between the reader and the data (see Content Rules)

**Verdict metadata (Section 0):**

- Do not define or render `.badge-verdict-*` pills. The verdict is the
  `.verdict-headline`; execution shape and complexity are plain-text
  `.verdict-meta`. This keeps the information hierarchy semantic and avoids
  relying on color.

**Print styles:**

- `@media (max-width: 700px)`: reduce report/card padding, force the metric
  grid to one column, make the TOC one column, and allow tables/diagrams to
  scroll horizontally
- `@media print`: white page background, compact report padding, preserve card
  borders, avoid breaks inside metric cards/callouts/table rows, and start the
  appendix on a new page. Do not apply `break-inside: avoid` to entire long
  sections because that creates large blank areas in printed reports.

**Footer:**

- `footer`: margin-top 3rem; padding-top 1rem; border-top 1px solid #e8e8e8; text-align center; color #687078; font-size 0.8rem

### Content Rules

1. **All data must come from artifacts** — do not invent numbers or services. If an artifact field is missing, omit that section.
2. **Currency formatting**: Monthly figures as whole dollars with thousands separators (`$1,415`, `$118`). Use cents only where sub-dollar precision is meaningful (`$1.50`, `$0.40`). Be consistent within the report — do not mix `$118.00` and `$118`.
3. **Percentage formatting**: Include `+` or `-` prefix. Use green styling for savings, red for increases.
4. **No external resources**: No CDN links, no external fonts, no images. Everything inline.
5. **Valid HTML5**: Output must be valid, well-formed HTML5.

### Readability Conventions (enforced by `validate-migration-report.py`)

These move from "example in the fixture" to enforced gate. See `references/shared/validate-migration-report.md` and `fixtures/migration-report-reference.html`.

**Governing principle — structure is information, not decoration.** Every structural device in the report (numbering, labels, badges, dividers, ordering) must encode something true about the content: numbers only for real sequences, badges only for real classifications, position only for real priority (the verdict before the menu, heroes before supporting metrics). When adding a new device, ask what fact it encodes; if the answer is "it looks organized," leave it out. The rules below are applications of this principle.

1. **No numbered headings.** Rendered `<h2>`/`<h3>` headings use plain titles ("Estimated AWS Monthly Run Rate"), never `Section N — …`. The "Section N" labels used elsewhere in _this spec_ are authoring references only and must not appear in output. The table of contents carries structure: executive sections in an ordered `<ol>`, appendices in a separate lettered list (avoids "11. Appendix A" double-numbering). The validator fails on a literal `Section 0` or any `<hN>Section N — …` heading. **Genuine sequences keep their numbers.** This ban targets _decorative_ heading labels only. Real sequences — the migration cluster order, phased timeline weeks, migration phases, and rollback steps — MUST stay ordered (`<ol>` or a numbered table column) because the order carries information the reader needs. Do not flatten them to bullets to satisfy this rule.
2. **No internal scoring trace.** Per-cluster mapping rationale goes in a collapsible `<details class="why">` ("Why this mapping?") block — never a bare `Rubric:` line. The validator fails on a literal `Rubric:` in the body.
3. **Security teaser up top, full detail in the appendix.** `exec-security-teaser` carries a 2–3 line summary that links down to `appendix-security` (full control table) and `appendix-security-gap`. Do not render the full control table in the executive flow.
4. **Expand acronyms** on first use and include a dedicated final
   `<section id="appendix-glossary">` glossary appendix (monthly run rate, DMS,
   OAI, RTO, CUD, SCC, IMDSv2, P95, RAG) — the audience is startup founders,
   not AWS specialists. Include only terms that appear in the report, plus the
   monthly-run-rate definition. Render the glossary
   as a bordered two-column `<table class="glossary-table">` with `Term` and
   `Meaning` headers, one distinct cell per term and definition, a caption,
   and `scope="col"` headers. Do not render it as a `<dl>` or loose paragraphs.
   Define monthly run rate as recurring modeled cloud-service charges and
   explicitly distinguish it from total cost of ownership.
5. **Accessible tables and diagrams.** Every table has a `<caption>` and `scope="col"` on header cells. The architecture diagram is wrapped in `<figure role="img" aria-label="…">` with a `<figcaption>` text alternative.
6. **State the verdict.** The decision summary includes a one-sentence recommendation banner (e.g. "Recommendation: Migrate in dependency order — estimated AWS run rate $497/mo, BigQuery deferred") in addition to the typography-first verdict headline and plain-text metadata.
7. **Reader vocabulary in the executive flow.** Artifact filenames (`estimation-infra.json`) and Terraform resource IDs (`aws_guardduty_detector.baseline`) are internal build vocabulary. Use them only in the technical appendices (`appendix-services`, `appendix-costs`, `appendix-optimization`, `appendix-security`, `appendix-artifacts`, etc.). In the executive flow (`decision-summary`, `exec-tco`, `exec-costs`, `exec-optimization`, `exec-services`, `exec-architecture`, `exec-security-teaser`, `what-if-scenarios`, `exec-timeline`, `exec-risks`), name things by what the reader controls — "the generated security baseline", "the infrastructure cost estimate", "workshop scenario comparison" — not by the file or resource that produced them. Rewrite tooling-availability notes (e.g. "AWS MCP Server not invoked") to reader-facing impact, or drop them. The validator fails on a `*.json` artifact filename or an `aws_<resource>.<name>` Terraform ID inside any `exec-*`, `what-if-scenarios`, or `decision-summary` section.
8. **One name per concept.** Use a single consistent label for each recommended choice across the whole report. The recommended Bedrock model and the chosen cost tier keep the same name in the verdict, tables, and appendices (always "Claude Sonnet 5 (recommended)", always "Balanced"). Do not alternate "recommended / selected target / design target / projected" for the same item — one label is how the reader keeps their bearings.
9. **Ordered action lists.** In `decision-summary`, `Key decisions ahead` and `Next steps` MUST use `<ol class="compact">`, not `<ul>`. The validator fails when either heading is followed by a bullet list. `Migrate if` / `Stay entirely if` remain unordered lists.
10. **Data first, explanation adjacent.** Never make the reader wade through a how-to-read paragraph or callout to reach the table it explains. Render the data first; put reading guidance in a `<details class="reading-guide">` immediately **after** the table (e.g. "How to read the three cost tiers"). Mandatory caveats that must not be collapsible (the not-comparable rule, baseline-quality labels) attach to the figure they qualify — a `.chip-warn` pill on the metric card plus one line in its `<small>` — rather than a standalone paragraph above the section's data.
11. **Numeric columns aligned.** Every table column whose cells are currency, hours, weeks, or percentages carries `class="num"` on its `<td>`s and header (right-aligned, tabular figures). Mixed cells (a number plus a qualifying `<small>`) still count as numeric.
12. **Corrections and derivations go in disclosures.** When a figure was corrected or derived (e.g. a tier-rule effort estimate replaced by a bottom-up range), the report states the **corrected value plus one clause** in the visible flow and puts the how-we-got-here narrative in a `<details class="why">` ("Why this is lower than the automatic estimate"). Internal classification history is machinery, not decision input — same principle as rule 2.
13. **No vague intensifiers.** Quantify instead of amplifying: never `very`, `significantly`, `extremely`, or `vastly` in report prose. "Significantly cheaper" becomes "-32% ($497/mo lower)". If a figure can't be quantified, state the range from the artifact or omit the claim. The validator fails on these words in the rendered body.
14. **Unambiguous dates.** All dates use ISO format `YYYY-MM-DD` (generation date, pricing last-updated, ECD-style targets). Never slash formats (`07/24/2026` reads differently in different locales). The validator fails on `N/N/YYYY` slash dates in the body.
15. **Color is never the only signal.** Verdict, complexity, and confidence badges already carry text labels — keep it that way for any new status element. Cost deltas keep the `+`/`-` prefix and a word ("savings" / "increase") alongside the green/red styling, so the report reads correctly when printed in black-and-white or by a color-blind reader.
16. **Active voice for actions.** Migration steps and next steps name the actor: "You run the cutover script", "Terraform creates the security baseline", "Your AWS account team reviews the BigQuery path" — never "the hosts will be migrated" with no owner.
17. **Denominators with progress metrics.** Any percentage describing coverage or progress states its base: "6 of 8 services (75%)", not "75% of services". Cost percentages keep their baseline visible in the same table row.
18. **Copy-ready leadership brief.** When a monthly estimate exists, render
    `exec-share` after the TOC using only decision-summary facts. It contains
    one standalone paragraph, no buttons or JavaScript, no new calculations,
    and no stronger certainty than the underlying estimate.
19. **Rounded monthly figures (enforces rule 2).** A monthly-scale dollar
    figure (whole-dollar part `$2` or higher) never renders with cents —
    round to the nearest whole dollar. Cents remain only on genuinely
    sub-dollar precision (`$1.50`, `$0.40`) or a per-unit rate (`$0.018/hr`,
    `$21.18` per 1-/6-month commitment unit-hour). The validator fails on a
    `$X.YY` figure `>= $2.00` with no adjacent rate suffix — this is the
    regression class where raw unrounded arithmetic (`$25,684.89/mo`) reaches
    the reader and overflows fixed-width metric cards.

> **Section IDs are stable anchors, not placement hints.** Some `appendix-*` IDs render in the executive flow on purpose (notably `appendix-assumptions`). Do not rename IDs to match position — the validator and TOC key on them.

## Step 4: Self-Check and Post-Write Validation

After generating the HTML file, verify:

1. **Required section IDs**: Each required ID appears **exactly once** on `<section id="...">` (not on `<div>` or other elements). See validator script.
2. **TOC integrity**: Every `<nav class="toc">` link `href="#id"` resolves to a `<section id="id">`; all required sections are linked.
3. **Combined AWS monthly run rate**: When **both**
   `estimation-infra.json` and `estimation-ai.json` exist, exactly one
   `exec-tco` section (legacy ID) with the summed AWS recurring service
   estimate. Never label it TCO. Sum the GCP side only when every source
   baseline is comparable; otherwise show "Not comparable."
4. **Data accuracy**: Cost figures in HTML match the estimation artifact values exactly — **manual / agent self-check**; the automated validator does not verify numerics (see `validate-migration-report.md` scope).
5. **Decision summary**: Migration Decision Summary present when estimation or preview artifacts exist; uses `recommendation.path_label` when block present, plus a one-sentence recommendation banner
6. **Human expertise flags**: Warning callouts appear for all services with `human_expertise_required: true`
7. **Valid HTML**: Opening and closing tags match, no broken table structures
8. **No placeholders**: No `[placeholder]` or `TODO` text in the report output
9. **Footer disclaimer**: Footer contains "draft for review"
10. **Readability**: No literal `Rubric:` and no numbered headings (`Section 0`, `Section 1b`, `<hN>Section N — …`); security teaser up top with full table in the appendix; tables have `<caption>`/`scope`; acronyms expanded; one-sentence recommendation banner in decision summary
11. **Reader vocabulary**: No artifact filenames (`*.json`) or Terraform resource IDs (`aws_*.*`) inside `decision-summary` / `exec-*` sections — those names live only in the technical appendices.
12. **Consistent labels**: The recommended model and the chosen cost tier use one consistent name across verdict, tables, and appendices (no "recommended / selected / design target" drift for the same item).
13. **Ordered next steps**: `Key decisions ahead` and `Next steps` in `decision-summary` use `<ol>`, not `<ul>`.
14. **Style conventions**: No vague intensifiers (`very`, `significantly`, `extremely`, `vastly`) in body prose; all dates are `YYYY-MM-DD`; no status conveyed by color alone; action steps use active voice with a named actor; progress percentages show their denominator.
15. **Cost-figure anchors (machine-checkable).** Wrap the recommended AWS monthly
    figure and the current-spend comparator in `exec-costs` with a `data-cost-key`
    attribute so the validator can confirm the rendered dollars match the estimate:
    - Projected AWS monthly (Balanced): `data-cost-key="aws_monthly_balanced"` on the
      element containing that dollar figure (value = `projected_costs.aws_monthly_balanced`).
    - Current GCP monthly: `data-cost-key="current_monthly"` (value = `current_costs.gcp_monthly`).
    - Optional per-tier: `data-cost-key="aws_monthly_premium"` / `"aws_monthly_optimized"`.

    Example: `<span data-cost-key="aws_monthly_balanced">$112/mo</span>`. The attribute
    is not reader-visible text, so it does not violate rule 7 (reader vocabulary). The
    validator asserts the rendered dollars equal the JSON for every anchor present.
    **The anchor must sit inside `<section id="exec-costs">` on a rendered element —
    not inside an HTML comment, and not merely present anywhere else in the document
    (e.g. a decision-summary hero metric does not satisfy this rule even if its own
    figure is correct — `exec-costs` is the section a validator holds to the estimate).**
    **The two required anchors above (`aws_monthly_balanced` and `current_monthly`) are
    mandatory whenever their JSON value exists and `exec-costs` is rendered — a missing
    required anchor is a validator FAIL, not a skip.** Only _untagged illustrative_
    numbers (and the optional per-tier figures when absent) are skipped.
16. **Whole-dollar monthly figures**: No monthly-scale dollar figure
    (`$2.00` or higher) renders with cents unless it is a per-unit/hourly
    rate — see rule 19 above.

17. **Appendix self-check**: skeleton § Post-write appendix self-check (appendix depth, security baseline surfaced, conditional sections, `appendix-config` provenance columns, glossary last, Cost Optimization placement).

**Run automated validator (mandatory when HTML was written):**

Load `shared/validate-migration-report.md`. Resolve script from plugin root: `$PLUGIN_ROOT/scripts/validate-migration-report.py`.

The validator is **stdlib Python only**. Do **not** ask the user to install Vale,
Pa11y, axe, Lighthouse, Chromium, or any other prose/accessibility tooling. Do
**not** skip validation because those tools are missing — they are never required.

`REPORT_OK` is not a substitute for this file or for
`references/shared/report-decision-core.md`. Load the decision core and render
it in **full** mode before writing HTML. The validator then rejects a report
that has the right section IDs but omits the decision-core content those
artifacts require: the verdict headline, hero metrics, the per-track line, the
conditions checklist, "What would flip this", the specialist-engagement
callout, the architecture section when the design has clusters, the
assumptions panel after risks, a risk table, and the what-if column set
(Region, HA, Compute, Arch) when two or more scenarios exist. A report written
only to satisfy an older structural gate will fail.

```bash
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --estimation-infra "$MIGRATION_DIR/estimation-infra.json" \
  --estimation-ai "$MIGRATION_DIR/estimation-ai.json" \
  --aws-design "$MIGRATION_DIR/aws-design.json" \
  --migration-dir "$MIGRATION_DIR"
```

Pass `--estimation-infra` / `--estimation-ai` / `--aws-design` only when those files exist in `$MIGRATION_DIR`. Use `--no-readability` only for non-customer test fixtures — not for normal Generate runs.

- On `REPORT_OK`: proceed to Step 5.
- On `REPORT_FAIL`: **rename** to `migration-report.incomplete.html` (default; do not delete), emit all failure lines to the user, and report to parent: "Report generation incomplete — re-run report step or expand appendix per fixtures/migration-report-reference.html". Do **not** claim a complete report was delivered or present a stub/numbered/jargon report as complete.

## Step 5: Open Report in Browser

After writing the HTML file, open it in the user's default browser so they can view it immediately.

Run: `open "$MIGRATION_DIR/migration-report.html"` (macOS) or `xdg-open "$MIGRATION_DIR/migration-report.html"` (Linux).

If the open command fails, fall back to presenting the full file path to the user:

```
Migration report ready — open in your browser:
file://$MIGRATION_DIR/migration-report.html
```

## Completion

Report to the parent orchestrator. **Do NOT update `.phase-status.json`** — the parent `generate.md` handles phase completion.

Output:

```
Migration report saved to $MIGRATION_DIR/migration-report.html

Report sections:
- Executive Summary: Section 0 Migration Decision Summary, [services count] primary services, [cost comparison], [timeline]
- Appendix A: Service Recommendations
- Appendix B: Cost Estimates
- Appendix C: Migration Steps
- [Appendix D: AI Migration — if applicable]
- Appendix E: Artifacts Catalog
- [Appendix F: Your Configuration — if preferences.json exists]
- Appendix G: Security Capabilities
- [Appendix H: Security Gap Analysis — when infra track ran]
- [Appendix I: Assumptions & Validation — always recommended]
- Appendix J: Glossary
```
