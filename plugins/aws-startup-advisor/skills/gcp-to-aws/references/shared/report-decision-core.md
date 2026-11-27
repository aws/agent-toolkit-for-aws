# Report Decision Core — GCP layer

## Load order

1. **Load `references/vendored/report/report-decision-core.md` first.** That vendored copy is the canonical, cloud-agnostic decision core — the section model and stable IDs per mode, the decision-mode contract, verdict typography and metric hierarchy, cost labeling and the `data-cost-key` anchors, readability, CSS and accessibility, the draft footer. It lives inside this skill; read no other skill's file.
2. **Then apply this file.** It supplies the values the canonical writes as `⟨parameter⟩`, GCP's Operational Changes rows, and the GCP-only add-ons. Nothing here overrides a canonical rule; where this file is silent, the canonical rule applies unchanged. Where the canonical and `$PLUGIN_ROOT/scripts/validate-migration-report.py` disagree, the validator wins.

Other files in this skill cite the decision core by its legacy section numbers. They map to the canonical headings as: Section 0 = Decision summary · 0b = Share With Your CFO · 1 = Current Stack Overview · 1b = Estimated AWS Monthly Run Rate (`exec-tco`) · 2 = Recommended AWS Architecture · 2b = Architecture diagram · 3 = Cost Comparison · 3b = What-if scenarios · 3c = Cost Optimization · 4 = Security & Cost Guardrails · 5 = Operational Changes · 6 = Timeline · 7 = Top Risks · 8 = What this assessment rests on.

## Parameters

| Parameter                                                  | GCP value                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ⟨source_cloud⟩                                             | GCP                                                                                                                                                                                                                                                                                                                                                                                            |
| ⟨modes_used⟩ / ⟨loaders⟩                                   | `decision` — `estimate.md` Decision gate, choice **A** (standalone `decision-report.html` + `DECISION.md`). `full` — `generate-artifacts-report.md` Step 1 (the executive-summary block of `migration-report.html`; its Step 3 holds the CSS specification both modes share). No `ai_only` mode in this skill.                                                                                 |
| ⟨required_ids⟩                                             | The validator's default per-mode sets — no `--profile`.                                                                                                                                                                                                                                                                                                                                        |
| ⟨current_monthly_path⟩                                     | `current_costs.gcp_monthly` — the validator resolves `data-cost-key="current_monthly"` from this key. Legacy artifacts compare `comparison.aws_balanced_monthly_usd` vs `comparison.gcp_monthly_usd`.                                                                                                                                                                                           |
| ⟨ai_spend_key⟩                                             | `current_costs.gcp_monthly_ai_spend`                                                                                                                                                                                                                                                                                                                                                           |
| ⟨baseline_label_table⟩                                     | `current_costs.source` → the display-label table in `estimate-infra.md` Part 1: "Measured from your GCP billing (±5%)" / "Estimated from resource configs (±20–30%, standing charges only)" / "Your stated spend band from Clarify" / "Your stated figure (unverified)". The explicit not-comparable line is defined there too.                                                                |
| ⟨service_mapping_table⟩                                    | § Service mapping table below                                                                                                                                                                                                                                                                                                                                                                  |
| ⟨activate_status_path⟩ / ⟨activate_copy⟩                   | `preferences.json` → `startup_constraints.startup_program_status.value`; copy per status in § Activate copy below                                                                                                                                                                                                                                                                              |
| ⟨decision_cta_text⟩ / ⟨decision_md_extras⟩                 | § Decision CTA below; `DECISION.md` has no extra parts beyond the canonical list                                                                                                                                                                                                                                                                                                                |
| ⟨validator_invocation⟩                                     | § Validator invocation below                                                                                                                                                                                                                                                                                                                                                                   |
| ⟨tier_subtitles⟩ / ⟨tier_semantics⟩                        | Canonical default subtitles. Key mapping only: Premium `projected_costs.aws_monthly_premium` / `cost_comparison.option_a_premium`; Balanced `projected_costs.aws_monthly_balanced` / `cost_comparison.option_b_balanced` (the Terraform-aligned, right-sized figure); Optimized `projected_costs.aws_monthly_optimized` / `cost_comparison.option_c_optimized`; itemized differences in `projected_costs.scenario_deltas.premium` / `.optimized`; derivation notes in `_premium_basis` / `_optimized_basis`. The definitions are the canonical's. |
| ⟨complexity_source⟩                                        | `migration-preview.json` → `complexity_signal` ("Simple", "Moderate", "Complex")                                                                                                                                                                                                                                                                                                               |
| ⟨confidence_source⟩                                        | `recommendation.confidence`                                                                                                                                                                                                                                                                                                                                                                    |
| ⟨key_decisions_source⟩                                     | `migration-preview.json` → `key_decisions_ahead`                                                                                                                                                                                                                                                                                                                                               |
| ⟨duration_driver_source⟩ / ⟨stage_sequence_source⟩         | _Decision mode:_ `migration-preview.json` → `duration_hint` (path-shape phrasing) when present, else the tier's driver summary from `shared/migration-complexity.md` (§ Provenance is why no duration is calibrated). _Full mode:_ `generation-infra.json` → `migration_plan.duration_drivers[]` and the generation plan's ordered stages.                                                       |
| ⟨defaulted_constraint_fields⟩ / ⟨extracted_from_wording⟩   | `preferences.json` constraints with `chosen_by: "default"` and their `design_consequence`; "extracted from your Terraform/billing"                                                                                                                                                                                                                                                              |
| ⟨provenance_fields⟩                                        | `estimation-infra.json` → `pricing_source`, cache date, `accuracy_confidence` band                                                                                                                                                                                                                                                                                                             |
| ⟨fallback_chain⟩                                           | (1) `financial_summary.recommendation` as `path_label`, with `migrate_if` / `stay_if` synthesized from Part 7 prose defaults in `estimate-infra.md`; (2) `migration-preview.json` — complexity + timeline shape only, labeled "Full recommendation requires Estimate phase — run Phase 4"                                                                                                       |
| ⟨stack_overview_filter⟩                                    | PRIMARY classification only — exclude secondary/supporting resources such as default VPC firewalls; name each as e.g. "Cloud Run (compute)", "Cloud SQL (database)"                                                                                                                                                                                                                             |
| ⟨how_we_chose_vocabulary_ref⟩                              | `design-refs/fast-path.md` → **User-facing vocabulary**                                                                                                                                                                                                                                                                                                                                        |
| ⟨ri_sp_eligibility_ref⟩                                    | `references/shared/ri-sp-eligibility.md`                                                                                                                                                                                                                                                                                                                                                       |
| ⟨reference_fixture⟩                                        | `fixtures/migration-report-reference.html`                                                                                                                                                                                                                                                                                                                                                     |
| ⟨deferred_analytics_example⟩                               | BigQuery                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨spend_fields⟩                                             | `gcp_monthly_spend`, `ai_monthly_spend`                                                                                                                                                                                                                                                                                                                                                        |
| ⟨risk_sources⟩                                             | The three canonical decision-mode sources only; the deferred-specialist example is BigQuery excluded from totals                                                                                                                                                                                                                                                                               |
| ⟨fill_in_checklist_name⟩                                   | "checklist in MIGRATION_GUIDE.md"                                                                                                                                                                                                                                                                                                                                                              |

### Activate copy

| `startup_program_status.value` | Verdict / metric copy                                                                                                                                                                                                                                |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eligible_founders`            | May state "Eligible for up to $5K AWS Activate Founders credits" and link `STARTUP_PROGRAMS.md`                                                                                                                                                      |
| `eligible_portfolio`           | May state Portfolio credits (up to $200K) and Org ID requirement                                                                                                                                                                                     |
| `has_credits`                  | Note existing credits; no "apply for" language                                                                                                                                                                                                       |
| `unknown`                      | **Neutral only:** e.g. "Review AWS Activate tiers in `STARTUP_PROGRAMS.md` — funding stage not confirmed in Clarify." **Do not** write "Eligible Founders tier", "your status: eligible_*", or dollar amounts tied to a specific tier in the verdict |

Show the 💡 callout when the status is **not** `unknown`, or when `unknown` with the neutral wording (optional). The callout, apply-link, never-a-metric-card, and no-tier-inference rules are canonical (§ Deferred services and startup credits).

### Decision CTA

`<section id="decision-cta">` — "**Ready to execute?** Say \"generate the Terraform and migration scripts\" and I'll produce the full execution pack (Terraform, migration scripts, rollback runbook, fill-in checklist) from this same analysis." Plus the canonical fixed line: "This decision report was generated without execution artifacts; the full migration report replaces it if you proceed."

### Validator invocation

Default contract, no `--profile`. Decision mode:

```sh
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR" [--estimation-infra …] [--estimation-ai …] [--aws-design …]
```

Full mode: the same command against `$MIGRATION_DIR/migration-report.html` with `--mode full`, as documented in `shared/validate-migration-report.md` (exit-code table, fixture-bleed detection). Pass the estimation and design files when they exist so the cost-anchor, share, security-teaser, and Cost Optimization gates fire; `--migration-dir` is required on every real run. `REPORT_OK` from this one validator is the gate — this skill has no add-on validator for the report.

## Service mapping table

_Full mode:_ include **migration cluster order** from `generation-infra.json` → `migration_plan.cluster_order`. Source: `aws-design.json`, `generation-infra.json`.

_Decision mode:_ render the diagram from `aws-design.json` clusters only — **omit cluster order** (`generation-infra.json` does not exist yet). Source: `aws-design.json`.

**Section 3 — Cost Comparison:**

- Side-by-side display: Current GCP Monthly vs Estimated AWS Monthly (**Balanced** tier — the default scenario for comparing to GCP)
- **Baseline-quality badge (required):** label the GCP figure using `current_costs.source` and the display-label table in `estimate-infra.md` Part 1 — "Measured from your GCP billing (±5%)" / "Estimated from resource configs (±20–30%, standing charges only)" / "Your stated spend band from Clarify" / "Your stated figure (unverified)". **Never** place an inventory-only GCP figure beside a user spend band without the explicit not-comparable line from `estimate-infra.md` Part 1 — they measure different things.
- Percent change (savings or increase)
- Render supported savings values with the green `.savings` class and supported
  increases with `.increase`. Never color a percentage as savings when the GCP
  and AWS baselines are not comparable; use an absolute estimated-cost card
  plus the not-comparable note instead.
- **Cost labeling rule:** All dollar figures in cost tables and metrics MUST be labeled as estimated monthly costs. Use column headers like "Est. Monthly AWS" or "Estimated Monthly" — never present figures as exact amounts.
- **Cost-figure anchors (machine-checkable, both modes).** Wrap the Balanced AWS
  monthly figure and the current GCP monthly figure inside `exec-costs` with a
  `data-cost-key` attribute, so `validate-migration-report.py` can confirm the
  rendered dollars match the estimate: `data-cost-key="aws_monthly_balanced"` on
  the element holding the Balanced dollar figure (value =
  `projected_costs.aws_monthly_balanced`), and `data-cost-key="current_monthly"`
  on the element holding the GCP figure (value = `current_costs.gcp_monthly`).
  Optional per-tier: `data-cost-key="aws_monthly_premium"` /
  `"aws_monthly_optimized"`. Example:
  `<strong data-cost-key="aws_monthly_balanced">$155</strong>`. The attribute is
  not reader-visible text. **Both required anchors are mandatory whenever their
  JSON value exists and `exec-costs` is rendered — in decision mode as well as
  full mode** — a missing required anchor is a validator FAIL, not a skip. The
  anchor must sit inside `exec-costs` itself; a figure repeated elsewhere in the
  decision summary (e.g. a hero metric) does not satisfy this rule.
- **Not-comparable rendering:** the mandatory not-comparable warning is NOT collapsible and does not sit as a paragraph between the heading and the numbers — attach it to the GCP figure itself: a `.chip-warn` pill ("⚠ not comparable") on the metric card plus the one-line explanation in its `<small>` (what the figure measures, what the stated band measures, "do not read a savings %").
- **How to read cost tiers (required when infra estimation with three tiers exists; rendered as a `<details class="reading-guide">` immediately AFTER the tier table — data first, explanation adjacent):** The three AWS monthly figures are **estimated monthly costs** for the **same** mapped architecture (same services in `aws-design.json`), not three different generated Terraform stacks. **Order = highest → middle → lowest** monthly estimate in this model. Use **Balanced** as the **primary** row vs GCP; **Premium** and **Optimized** are **bounds** (higher HA / newer skew vs cost-optimization skew). When `terraform/` is present, it implements **one** infrastructure baseline aligned with the **Balanced** cost scenario (see `terraform/README.md` and `migration_summary` output).
- If 3 tiers available: show **Premium**, **Balanced**, and **Optimized** with **short subtitles** (second line or subtext under each label), plus a **"vs Balanced, for this stack" column** from `projected_costs.scenario_deltas` when present — the itemized differences are the decision content (a reader must be able to answer "what would I buy at Premium / give up at Optimized?" from the table alone). Architectural deltas carry their consequence verbatim from the artifact (e.g. "Drops NAT Gateway — tasks move to public subnets or VPC endpoints; posture change, not just savings"); commitment-based savings name the commitment. Balanced's cell is "— anchor; matches generated Terraform" (full mode) or "— anchor" (decision mode). When `scenario_deltas` is absent (pre-extension artifacts), omit the column — do not invent deltas. Do NOT expand the generic tier definitions to compensate; the reading-guide `<details>` already covers same-architecture semantics:
  - **Premium** — _Highest resilience / highest monthly estimate in this model_
  - **Balanced** — _Default scenario; compare GCP to this row first_
  - **Optimized** — _Lower monthly estimate; reservations, Spot, or storage trade-offs assumed_
- **Footnote (required):** _All figures are estimated monthly costs based on AWS pricing data at time of analysis._ Then, _full mode:_ _Only one Terraform configuration is generated (Balanced-aligned baseline). Premium and Optimized are what-if cost models in `estimation-infra.json` — adjust IaC yourself if you want those postures in production._ _Decision mode:_ _If you generate the execution pack, its Terraform will align with the Balanced scenario; Premium and Optimized are what-if cost models._
- **Only include "GCP data transfer egress (est.)" when the infra estimation artifact has `migration_cost_considerations.billing_data_available === true`.** Never present human one-time migration costs. If `false` or only non-infra estimates exist, footnote: "GCP data transfer egress estimates require billing data and the infra estimate path."
- If observability entry exists in `projected_costs.breakdown` (tolerant lookup: array where `service` contains "Observability" OR object where key contains `observability` or `cloudwatch`) AND the entry's `note` field mentions GCP free tiers:

> **Observability cost note:** [Pull the `note` field verbatim]

- Source: estimation artifact

**Section 3b — What-if scenarios (`what-if-scenarios`, OPTIONAL):**

Render **only when** `$MIGRATION_DIR/scenarios/index.json` exists and
`scenarios[]` has **≥ 2** entries (baseline + at least one workshop variant).
Omit entirely when workshop was declined or never entered.

1. Load `scenarios/index.json`. For each entry (baseline first, then by
   `created_at`), read the manifest at `entry.manifest`.
2. HTML table matching `workshop-compare.md` columns:

| Scenario | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity |
| -------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- |

Resolve knobs from each scenario's preferences copy (or
`preferences_subset` / `estimation_summary` on the manifest): Region ←
`design_constraints.target_region.value`; HA ←
`design_constraints.availability.value`; Compute ←
`design_constraints.kubernetes.value` when present; Arch ←
`design_constraints.cpu_architecture.value`. Costs and complexity ←
`estimation_summary`.
3. Mark the active row (`scenario_id == index.active_scenario_id`) with
`class="active-scenario"` or an "(active)" label.
4. Under the table: active vs baseline knob deltas (plain language); any
`graviton_note` / `region_note`;
remind that discovery inventory is frozen
and generated Terraform matches the **active** scenario only.
`estimation_summary.calculator_url` is always `null` — render no "open in AWS
Pricing Calculator" link.
5. TOC: link `#what-if-scenarios` only when rendered. Place this section in the
executive flow immediately after `exec-costs` (before security teaser /
timeline). When `exec-optimization` is also rendered, place it after
`exec-costs` and before `what-if-scenarios`.

**Section 3c — Cost Optimization (`exec-optimization`, REQUIRED when any
`estimation-*.json` has a non-empty `optimization_opportunities[]`):**

This is a **standalone executive section**. A table buried only under
Appendix B / `appendix-costs` does **not** satisfy the gate — that is how
Savings Plans and Reserved Instances were dropped from generated reports.

Place immediately after `exec-costs` (and before `what-if-scenarios` /
`exec-architecture` / security teaser). Add `#exec-optimization` to the TOC
when rendered.

Render two things:

1. **Posture comparison table** (Balanced on-demand vs applicable commitments
   vs Optimized as a floor). Columns such as: Posture, Est. monthly, vs
   Balanced, What you commit to. Savings Plans and Reserved Instances are
   incremental to the **Balanced on-demand** baseline. **Do not** add those
   savings on top of the Optimized tier — Optimized already embeds
   illustrative reservation / Spot assumptions. State that caveat in the
   section when Optimized is shown. Database Savings Plans and RDS Reserved
   Instances are mutually exclusive on the same database workload.
2. **Which commitment fits** — a short list from the opportunity rows
   (Compute Savings Plans, Database Savings Plans, Reserved Instances /
   reserved capacity / reserved nodes, plus non-commitment rows such as
   Fargate Spot or S3 Intelligent-Tiering when present).

_Full mode:_ the line-level opportunity table (Optimization, Target,
Monthly savings / Est. savings, Commitment, Effort) lives in a dedicated
`<section id="appendix-optimization">` immediately after `appendix-costs`.
`exec-optimization` links down to it. Do not leave that table as an `<h3>`
inside `appendix-costs`.

_Decision mode:_ there are no appendices. Include the opportunity-table
columns in `exec-optimization` itself (or a compact version of the same
rows). Do **not** emit `appendix-optimization`.

Source: `estimation-infra.json` / `estimation-ai.json` →
`optimization_opportunities`. Eligibility of which commitment product
applies is `references/shared/ri-sp-eligibility.md`.

**Section 4 — Security & Cost Guardrails (teaser — full table in Appendix G):**

Show top controls as a compact teaser:

| Control                        | What it does for you                                               | Monthly cost                         |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------ |
| GuardDuty                      | Detects compromised credentials and crypto mining within minutes   | ~$2–25/mo                            |
| CloudTrail                     | Immutable audit log of every API call — required for SOC 2         | ~$0.50–3/mo                          |
| Budget alerts                  | Email when spend exceeds threshold — catches runaway resources     | $0                                   |
| Bedrock cost anomaly detection | Alerts within ~24h if AI spend spikes unexpectedly (AI track only) | $0 (Cost Explorer anomaly detection) |

The fourth row is **conditional** — only render when `$MIGRATION_DIR/ai-migration/setup_bedrock.sh` exists on disk and contains the step `== 6. Bedrock budget and cost anomaly monitor`. Do NOT render based on `generation-ai.json` alone.

_Full mode:_ > See Appendix G for full security and cost guardrails table with GCP equivalents.

_Decision mode:_ > The full control-by-control table is included if you generate the execution pack.

If `preferences.json` contains compliance values (`soc2`, `pci`, `hipaa`, `fedramp`):

> **Compliance note:** Your declared compliance requirement ([standard]) triggers additional controls (AWS Config + Security Hub) at ~$3–25/mo. _(Full mode: append "See Appendix G.")_

**Do NOT include step-by-step enablement** — that belongs in `terraform/README.md` and `MIGRATION_GUIDE.md`.

Source: static content + `preferences.json` compliance values

**Section 5 — Operational Changes (conditional rows only):**

Only render rows for service types PRESENT in the design artifact. Do not show rows for services not in the migration.

| GCP Service        | AWS Service | What stays the same                                 | What's new                                                                           |
| ------------------ | ----------- | --------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Cloud Run          | Fargate     | Fully managed containers, auto-scaling, pay-per-use | Task definitions replace service.yaml; ALB for HTTP routing; ECR replaces GCR        |
| Cloud SQL          | RDS/Aurora  | Managed DB, automated backups, PITR                 | Parameter groups replace database flags; Security Groups replace authorized networks |
| Cloud Storage      | S3          | Object storage, lifecycle policies, versioning      | Bucket policies replace IAM conditions; CloudFront needed for public CDN             |
| Vertex AI / Gemini | Bedrock     | Managed API, pay-per-token                          | IAM-based access (no API keys); SDKs differ                                          |

## GCP add-ons

Declared add-ons on top of the canonical contract — rules that exist only because the source cloud is GCP.

- **BigQuery next step (Decision summary, under the deferred-services callout):** when the deferred service is BigQuery, render the bq-assess `.callout-info` box directly under the canonical ⚠ specialist-engagement callout, per `references/shared/bq-assess-next-step.md` → Report callout. Never block or delay the report on it. In the Recommended AWS Architecture table, end BigQuery's specialist footnote with: "and see the BigQuery next step above." The `exec-tco` deferred-services exclusion names BigQuery as its example.
- **Startup-program artifact check:** _Full mode only:_ after Generate, run `scripts/validate-startup-program-artifacts.py --migration-dir $MIGRATION_DIR`. (Decision mode: the Activate wording rules above still apply to the rendered content; the script runs when the Generate artifacts it checks exist.)
- **AI-stale complexity (Timeline, full mode):** when infrastructure was classified Large solely because AI coexists, treat that as an invalid stale classification and re-run complexity sizing before rendering the timeline.
- **What-if columns (What-if scenarios):** the comparison table's columns are the ones `references/phases/workshop/workshop-compare.md` defines; keep the two in step when either changes.

## Declared exceptions

None. gcp-to-aws follows the default contract: the validator's default required-ID sets in `decision` and `full` mode, no `--profile`, every canonical section rendered under its canonical trigger. Any future shape divergence must be declared here and in `SKILL_PROFILES` of the shared validator, never silently.
