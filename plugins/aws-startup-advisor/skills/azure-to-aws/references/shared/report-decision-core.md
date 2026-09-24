# Report Decision Core (shared renderer spec)

The executive-summary sections below are the **decision core** — the single
source of truth for verdict, cost, timeline, risk, and assumption rendering.
Two consumers load this file; the content rules are identical in both:

| Mode         | Loaded by                                 | Output                                                                                            |
| ------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **decision** | `estimate.md` Decision gate, choice **A** | Standalone `decision-report.html` + `DECISION.md` — decision core only, no appendices, CTA footer |
| **full**     | `generate-artifacts-report.md` Step 1     | The executive-summary block of `migration-report.html`, followed by the appendices                |

**Never patch one output into the other.** When Execute runs after a Decide
run, `migration-report.html` is rendered **fresh from the artifacts** — do not
extend, edit, or splice `decision-report.html`. All data needed for either
output lives in the JSON artifacts.

## Decision-mode specifics

- **Artifacts available:** discovery + `preferences.json` + `aws-design*.json` + `estimation-*.json` (+ `migration-preview.json`, `scenarios/` when present). `generation-*.json` and `terraform/` do NOT exist. Sections that prefer Generate artifacts carry an inline **_Decision mode:_** override next to the full-mode rule (decision-summary item 4, Sections 2b, 3 footnote, 4, 6, 7) — **those inline overrides are the authoritative decision-mode law**; when a section has no override, its rule applies unchanged in both modes.
- **HTML shell:** same `<head>` (charset, viewport, inline CSS) and CSS specification as the full report (see `generate-artifacts-report.md` Step 3), title "Azure to AWS Migration Assessment — Decision Report". Body contains ONLY the `executive-summary` div with the exec sections and TOC (TOC links only to sections present; `nav.toc` carries `id="toc"` and every section `<h2>` ends with the `↑ contents` toplink per the nav-aids CSS spec). Opening order follows the hero-is-the-thesis rule: `decision-summary` first, TOC after it. Required section IDs in decision mode: `decision-summary`, `exec-assumptions`, `exec-services`, `exec-costs`, `exec-timeline`, `exec-risks` (+ conditional `exec-share`, `exec-tco`, `exec-architecture`, `exec-security-teaser`, `exec-optimization`, `what-if-scenarios` per their triggers).
- **CTA footer (required, after the last section):** `<section id="decision-cta">` — "**Ready to execute?** Say \"generate the Terraform and migration scripts\" and I'll produce the full execution pack (Terraform, migration scripts, rollback runbook, fill-in checklist) from this same analysis." Plus one line: "This decision report was generated without execution artifacts; the full migration report replaces it if you proceed."
- **`DECISION.md` (required twin):** same content as the HTML, as plain Markdown (Slack/GitHub-friendly): verdict headline, cost table, migrate-if/stay-if lists, timeline band, top risks, assumptions, CTA line. No HTML tags.
- **Validation:** run `scripts/validate-migration-report.py $MIGRATION_DIR/decision-report.html --mode decision [--estimation-infra ...] [--estimation-ai ...] [--aws-design ...]` and fix failures before presenting. Pass the estimation (and design) files when they exist so the Cost Optimization gate can fire.
- **Cost-figure anchor (machine-checkable, decision mode too):** the
  `data-cost-key="aws_monthly_balanced"` anchor required by
  `generate-artifacts-report.md` Step 2 applies here unchanged — wrap the Balanced dollar
  figure inside `exec-costs` in it whenever `projected_costs.aws_monthly_balanced` exists.
  A missing anchor is a validator FAIL, not a skip, and passing `--estimation-infra` is
  what makes the gate fire.
- All content rules below apply unchanged: baseline-quality badge + not-comparable rule, cost labeling ("Est."), readability (no artifact filenames in exec sections, no "Section N" headings, ordered action lists), Activate wording rules.

---

The executive summary is the first thing visible when opening the report. Design it to fit approximately 1–2 printed pages.

### Executive Summary Content

**Header:** "Azure to AWS Migration Assessment" with subtitle "Executive Summary" and generation date.

**Table of contents (required — placed AFTER the decision summary, never before it):** Linked `<nav class="toc">` listing all executive sections and appendix sections present in this report. **Every `href="#section-id"` MUST match a `<section id="section-id">` on the page exactly** (same string, including hyphens). Omit TOC links only for sections not rendered.

**The hero is the thesis (opening order):** the reader's first screenful is the decision, not navigation. Page order: title line → `decision-summary` (verdict headline + hero metrics) → TOC → remaining sections. An 18-link menu between the title and the verdict makes the reader scroll past chrome to learn the answer; the document's thesis — "Go, with conditions · $X/mo · phased, long pole: database cutover" — must be visible before any menu.

**Target length:** approximately 2–4 printed pages for executive summary. _Full mode only:_ **Do NOT truncate appendices** to fit page count — appendices may be long.

**Anti-stub rule (mandatory; the appendix clauses apply in full mode only):** every rendered section MUST carry real artifact data as HTML tables and prose. **Forbidden:** sections that only say "see `estimation-infra.json`" or list JSON filenames without numeric costs, service mappings, or migration phases. Reference fixture: `migrate/plugins/migration-to-aws/fixtures/migration-report-reference.html`.

**Section 0 — Migration Decision Summary (REQUIRED):**

Pull from `estimation-infra.json` → `recommendation` block. Fallback chain if `recommendation` is absent:

1. `estimation-infra.json` → `financial_summary.recommendation` (string) — use as `path_label`; synthesize `migrate_if` / `stay_if` from Part 7 prose defaults in `estimate-infra.md`
2. `migration-preview.json` — show complexity + timeline only; label: "Full recommendation requires Estimate phase — run Phase 4"

Content when `recommendation` block exists:

1. **Verdict (typography-first — the verdict is the thesis of this section):** When `recommendation.outcome` exists (v2 artifacts), render `outcome_label` as the section's **headline statement** in large display type (e.g. `<p class="verdict-headline">Go, with conditions</p>`), followed by one labeled metadata line in body type: "Execution shape: [path_label] · Complexity: [complexity_signal]". The hierarchy encodes the real relationship — the decision is the headline; how and how-hard are attributes of it. Do **not** render the verdict as a row of colored pill badges: structure should carry the information, and meaning must never depend on color alone (a muted color accent on the headline is fine; the words carry the verdict). When `outcome` is absent (pre-extension artifacts), the same treatment applies with `path_label` as the headline. When `conditional_go`: render `conditions[]` as a short checklist directly under the metadata line. When `defer_for_evidence`: lead with what IS established ("AWS can host this stack; AWS-side estimate $X–$Y/mo" + the designed-slice mapping), then the named missing evidence and how to obtain it — do not show a savings headline as if the decision were made, and do not present defer as "no answer."
   1a. **Recommendation callout (required):** Render the one-sentence
   recommendation narrative directly below the headline/meta as
   `<div class="verdict">…</div>`. For `go`, `conditional_go`, and
   migrate-path legacy outcomes, use the green positive callout treatment
   defined by the shared CSS. For `stay` or `defer_for_evidence`, use the
   warning/neutral variant instead — never use green to imply approval. The
   explicit recommendation words remain required; color is only a scanning
   aid.
   1a. **Per-track disposition line (required when `recommendation.track_outcomes` exists):** one line under the verdict metadata, plain names, one clause per track — e.g. "By track: Compute + database: **go**. AI text: **go**. AI image: **conditional** — keeps the current provider via the adapter until the quality eval passes; does not gate the rest. Analytics: **deferred** — specialist track, parallel." Render the track note verbatim. **Never render a track-scoped condition as a whole-stack stay reason**: the Stay-if list holds only entries the artifact scoped to the whole stack; track-prefixed conditions render in the conditions checklist and the track line. Omit silently for single-track or pre-extension artifacts.
   1b. **Confidence pointer:** one line under the verdict block — `Confidence: [confidence] — full basis in <a href="#exec-assumptions">What This Assessment Rests On</a>.` The full assumptions panel lives at the **end** of the executive summary (see Section 8 below), not here.
2. **Complexity:** from `migration-preview.json` → `complexity_signal` ("Simple", "Moderate", "Complex") — colored badge
3. **Cost headline:** from `estimation-infra.json` → `cost_comparison.option_b_balanced` vs Azure baseline,. Do NOT use `migration-preview.json` → `cost_preview` when estimation artifact exists (preview is superseded). If only preview exists **and** `cost_preview.quote_suppressed` is true: do **not** render a dollar headline or "Early estimate (±30%)" — render "AWS monthly cost withheld at Discover — authored Terraform sizes exceed preview defaults. Run Estimate after Clarify." If only preview exists and the quote was **not** suppressed: show labeled "Early estimate (±30%) — full analysis not yet run."
4. **Timeline:** week counts are never rendered in either mode — the plugin has no calibrated duration data (`shared/migration-complexity.md` § Provenance). _Full mode:_ approach + the binding duration driver from `generation-infra.json` → `migration_plan.duration_drivers[]` (e.g. "Phased, in dependency order — long pole: database cutover"). _Decision mode:_ `migration-preview.json` → `duration_hint` (path-shape phrasing) when present, else the tier's driver summary from `shared/migration-complexity.md`; label it "**if you execute**". **Legacy artifacts:** when an old artifact carries `total_weeks` or `timeline_hint` week ranges, render only with the visible label "Legacy planning heuristic (uncalibrated): N weeks" — never bare. In neither mode use `recommendation.next_steps` as timeline — those are action items, not duration.
5. **Migrate if / Stay entirely if:** from `recommendation.migrate_if` and `recommendation.stay_if`. Render as two compact lists. The customer-facing second heading is **"Stay entirely if"** so a track-scoped hold (for example, keeping image generation on the current provider) cannot be mistaken for a recommendation to abandon the whole migration. The `stay_if` list contains whole-stack reasons only. For Synapse/Data Factory deferred analytics: **do not** frame specialist engagement as a reason to stay on Azure unless the user must cut over analytics in the **same window** as app infra. Prefer migrate-if bullets that mention parallel specialist planning. When track-scoped caveats exist, add one muted sentence after the lists explaining which track can remain on the source platform without blocking the rest.
6. **Key decisions ahead:** from `migration-preview.json` → `key_decisions_ahead` — **ordered list** (`<ol class="compact">`), not bullets. Each item is one concrete decision the reader must make next.
   6b. **What would flip this (v2 artifacts):** from `recommendation.would_flip_if[]` when present — short unordered list immediately after Migrate if / Stay entirely if. Skip silently when absent.
7. **Next steps (optional):** from `recommendation.next_steps` — **ordered list** (`<ol class="compact">`) of actionable steps separate from timeline. Numbered sequence implies priority order; keep `Migrate if` / `Stay entirely if` as unordered lists. When generated artifacts contain fill-in placeholders, the FIRST next step MUST state execution readiness: "Fill in the [N] account-specific values (emails, account ID, image URI — checklist in MIGRATION_GUIDE.md) — nothing can be applied until then." The report is the decision document; this line is the bridge from decision to execution.

**Section 0b — Share With Your CFO (`exec-share`, REQUIRED when any estimation artifact contains a monthly source or AWS estimate):**

Render immediately after the TOC. This is a copy-ready, one-paragraph decision
brief derived only from values already shown in the decision summary:

- verdict and confidence;
- estimated AWS monthly run rate (combined when comparable, otherwise the
  available track estimate with its scope);
- source baseline only when it is comparable, otherwise say that actual source
  billing must be confirmed;
- migration shape and binding duration driver;
- at most three conditions or evidence gaps.

Use `<div class="share-card"><p>…</p></div>` with exactly one substantive
paragraph (at least 20 words) and a short lead-in ("The one-paragraph version,
ready to forward:"). Do not add JavaScript, a copy button, editable controls,
or new calculations. The paragraph must stand alone when pasted into email or
a planning document. Label every modeled amount as estimated and preserve the
same comparability caveats as the cost section. In decision mode, omit
Generate-only facts. Add `exec-share` to the TOC only when rendered.

**Deferred services flag:** If ANY resource in the design artifact has `aws_service == "Deferred — specialist engagement"`, add a prominent callout:

> ⚠️ **Specialist engagement required:** [service name] does not have an automated AWS mapping from this plugin. Engage your AWS account team and/or a data analytics migration partner to evaluate the best AWS analytics path. This does **not** block phased migration of other services; exclude [service name] from the combined estimated AWS monthly run rate until the target architecture is defined.

**Startup credits callout (decision summary / verdict):**

| `startup_program_status.value` | Verdict / metric copy                                                                                                                                                                                                                                |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eligible_founders`            | May state "Eligible for up to $5K AWS Activate Founders credits" and link `STARTUP_PROGRAMS.md`                                                                                                                                                      |
| `eligible_portfolio`           | May state Portfolio credits (up to $200K) and Org ID requirement                                                                                                                                                                                     |
| `has_credits`                  | Note existing credits; no "apply for" language                                                                                                                                                                                                       |
| `unknown`                      | **Neutral only:** e.g. "Review AWS Activate tiers in `STARTUP_PROGRAMS.md` — funding stage not confirmed in Clarify." **Do not** write "Eligible Founders tier", "your status: eligible_*", or dollar amounts tied to a specific tier in the verdict |

**Sidebar callout box:** Show the 💡 Activate callout when `startup_program_status.value` is **not** `unknown`, **or** when `unknown` but you use the neutral wording above (optional). When `unknown`, do **not** imply a confirmed tier. **The Activate item is ALWAYS this callout, never a metric card** — it is a call-to-action with a link, not a measurement, and rendering it in the metric grid gives it false equivalence with the run-rate and timeline figures. The clickable apply link goes inside the callout.

**Metric hierarchy (when the decision summary renders a metric grid):** the reader should not have to rank the numbers themselves. The one or two **primary** decision metrics — the combined (or single-track) AWS run rate, and the migration shape (approach + binding driver, e.g. "Phased · long pole: database cutover") — render first with `.metric-hero` treatment (larger value, accent border). Supporting metrics (per-track costs, savings percentages) follow as standard cards, max ~5 total. Never render a week count or effort-hours as a metric card.

Do **not** infer Activate tier from `azure_monthly_spend` or `ai_monthly_spend` in the report or `estimation-*.json` ROI bullets.

**Apply link (required):** Whenever the report or `STARTUP_PROGRAMS.md` mentions AWS Activate credits, include at least one clickable link to the official apply page: `<a href="https://aws.amazon.com/startups/credits/">AWS Activate credits</a>` (HTML report) or `[AWS Activate credits](https://aws.amazon.com/startups/credits/)` (Markdown). Place it in the decision-summary verdict, a callout, and/or the Next steps ordered list — not only in the appendix artifact catalog. When an Activate metric card is rendered, put the clickable apply link **inside that card** so the action remains attached to the benefit.

_Full mode only:_ after Generate, run `scripts/validate-startup-program-artifacts.py --migration-dir $MIGRATION_DIR`. (Decision mode: the Activate wording rules above still apply to the rendered content; the script runs when the Generate artifacts it checks exist.)

Source: estimation artifact `recommendation`, `migration-preview.json`, design artifact

- Source: estimation artifact

**Section 1b — Estimated AWS Monthly Run Rate (`exec-tco`, REQUIRED when both `estimation-infra.json` AND `estimation-ai.json` exist):**

`exec-tco` is a legacy structural ID retained for validator compatibility; the
customer-facing heading MUST NOT say "TCO" or "Total Cost of Ownership." This
assessment models recurring cloud-service charges, not staffing, operations,
support, migration labor, or other ownership costs.

Show the combined estimated AWS monthly cloud-service run rate **excluding**
deferred services (e.g. Synapse / Data Factory):

| Row            | Azure                                                      | AWS Balanced                                | Notes                                                              |
| -------------- | ---------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------ |
| Infrastructure | `current_costs.azure_monthly`                              | `projected_costs.aws_monthly_balanced`      | From infra estimate                                                |
| AI / ML        | `current_costs.azure_monthly_ai_spend` or AI band midpoint | `cost_comparison.projected_bedrock_monthly` | From AI estimate                                                   |
| **Combined**   | sum only when all source baselines are comparable          | sum                                         | No overall Δ/% if any source baseline is partial or not comparable |

If `estimation-ai.json` → `optimized_projection` exists, footnote the optimized AI path separately.
Add one sentence: "This is an estimated cloud-service run rate, not total cost
of ownership." When the infrastructure baseline is inventory-derived or
standing-charges-only, show "Not comparable" in the combined Azure cell and
never sum it with a user-stated AI midpoint.

**Azure addition (AI-bundled total):** when the user stated a single Azure monthly total that bundles AI/Cognitive spend (Azure OpenAI, Document Intelligence, etc.) — because `estimation-ai.json` is reported as a separate artifact from `estimation-infra.json` — do **not** place that bundled total beside the AWS infrastructure figure as if comparable, and do **not** render a savings %. Show it with the `⚠ not comparable` chip and one line: "your stated Azure total includes AI spend, which is estimated separately here; compare against the combined infra + AI run rate, not infrastructure alone."

If `estimation-ai.json` → `optimization_opportunities` contains a
`provisioned_throughput` entry, add one footnote: "Provisioned Throughput
(a Bedrock-specific commitment option) uses no-commit, 1-month, or 6-month
terms — not the 1-year/3-year Reserved Instance or Savings Plan terms shown
elsewhere in this report." This is the first place a reader sees the combined
run rate — do not rely on the full report's appendix alone to make this
distinction.

Source: `estimation-infra.json`, `estimation-ai.json`

**Section 1 — Current Stack Overview:**

- Count of PRIMARY Azure services detected (from design artifact — filter to primary classification only; exclude secondary/supporting resources like default VPC firewalls)
- List each PRIMARY Azure service with its type (e.g., "App Service (compute)", "Azure SQL Flexible Server (database)")
- Source: design artifact (filtered)

**Section 2 — Recommended AWS Architecture:**

- Table with columns: Azure Service, AWS Service, **How we chose this**
- **How we chose this** values: use `design-refs/fast-path.md` → **User-facing vocabulary** — **Standard pairing** (`deterministic`), **Tailored to your setup** (`inferred`), **Estimated from billing only** (`billing_inferred`). Show the **bold phrase** in the table; JSON value optional in a tooltip or footnote for technical readers only.
- One row per mapped service
- If any service has `human_expertise_required: true`, mark it with a warning indicator and footnote: "Specialist guidance recommended — contact your AWS account team"
- Source: design artifact

**Section 2b — Architecture diagram (`exec-architecture`, REQUIRED when `aws-design.json` clusters exist):**

ASCII or structured diagram showing: users → ALB → compute → database/storage/AI; security baseline box; deferred services called out.

_Full mode:_ include **migration cluster order** from `generation-infra.json` → `migration_plan.cluster_order`. Source: `aws-design.json`, `generation-infra.json`.

_Decision mode:_ render the diagram from `aws-design.json` clusters only — **omit cluster order** (`generation-infra.json` does not exist yet). Source: `aws-design.json`.

**Section 3 — Cost Comparison:**

- Side-by-side display: Current Azure Monthly vs Estimated AWS Monthly (**Balanced** tier — the default scenario for comparing to Azure)
- **Baseline-quality badge (required):** label the Azure figure using `current_costs.source` and the display-label table in `estimate-infra.md` Part 1 — "Measured from your Azure billing (±5%)" / "Estimated from resource configs (±20–30%, standing charges only)" / "Your stated spend band from Clarify" / "Your stated figure (unverified)". **Never** place an inventory-only Azure figure beside a user spend band without the explicit not-comparable line from `estimate-infra.md` Part 1 — they measure different things. **Azure addition:** when `current_costs.source` is `baseline_not_invoiced` (the Azure baseline came from a rung other than a Cost Management export — see `estimate-infra.md` Part 1), label the figure "Azure baseline not invoiced — derived from resource configuration, not billing" and treat it as **not comparable** to a user-stated spend band (apply the not-comparable rendering below).
- Percent change (savings or increase)
- Render supported savings values with the green `.savings` class and supported
  increases with `.increase`. Never color a percentage as savings when the Azure
  and AWS baselines are not comparable; use an absolute estimated-cost card
  plus the not-comparable note instead.
- **Cost labeling rule:** All dollar figures in cost tables and metrics MUST be labeled as estimated monthly costs. Use column headers like "Est. Monthly AWS" or "Estimated Monthly" — never present figures as exact amounts.
- **Not-comparable rendering:** the mandatory not-comparable warning is NOT collapsible and does not sit as a paragraph between the heading and the numbers — attach it to the Azure figure itself: a `.chip-warn` pill ("⚠ not comparable") on the metric card plus the one-line explanation in its `<small>` (what the figure measures, what the stated band measures, "do not read a savings %").
- **How to read cost tiers (required when infra estimation with three tiers exists; rendered as a `<details class="reading-guide">` immediately AFTER the tier table — data first, explanation adjacent):** The three AWS monthly figures are **estimated monthly costs** for the **same** mapped architecture (same services in `aws-design.json`), not three different generated Terraform stacks. **Order = highest → middle → lowest** monthly estimate in this model. Use **Balanced** as the **primary** row vs Azure; **Premium** and **Optimized** are **bounds** (higher HA / newer skew vs cost-optimization skew). When `terraform/` is present, it implements **one** infrastructure baseline aligned with the **Balanced** cost scenario (see `terraform/README.md` and `migration_summary` output).
- If 3 tiers available: show **Premium**, **Balanced**, and **Optimized** with **short subtitles** (second line or subtext under each label), plus a **"vs Balanced, for this stack" column** from `projected_costs.scenario_deltas` when present — the itemized differences are the decision content (a reader must be able to answer "what would I buy at Premium / give up at Optimized?" from the table alone). Architectural deltas carry their consequence verbatim from the artifact (e.g. "Drops NAT Gateway — tasks move to public subnets or VPC endpoints; posture change, not just savings"); commitment-based savings name the commitment. Balanced's cell is "— anchor; matches generated Terraform" (full mode) or "— anchor" (decision mode). When `scenario_deltas` is absent (pre-extension artifacts), omit the column — do not invent deltas. Do NOT expand the generic tier definitions to compensate; the reading-guide `<details>` already covers same-architecture semantics:
  - **Premium** — _Highest resilience / highest monthly estimate in this model_
  - **Balanced** — _Default scenario; compare Azure to this row first_
  - **Optimized** — _Lower monthly estimate; reservations, Spot, or storage trade-offs assumed_
- **Footnote (required):** _All figures are estimated monthly costs based on AWS pricing data at time of analysis._ Then, _full mode:_ _Only one Terraform configuration is generated (Balanced-aligned baseline). Premium and Optimized are what-if cost models in `estimation-infra.json` — adjust IaC yourself if you want those postures in production._ _Decision mode:_ _If you generate the execution pack, its Terraform will align with the Balanced scenario; Premium and Optimized are what-if cost models._
- **Only include "Azure data transfer egress (est.)" when the infra estimation artifact has `migration_cost_considerations.billing_data_available === true`.** Never present human one-time migration costs. If `false` or only non-infra estimates exist, footnote: "Azure data transfer egress estimates require billing data and the infra estimate path."
- If observability entry exists in `projected_costs.breakdown` (tolerant lookup: array where `service` contains "Observability" OR object where key contains `observability` or `cloudwatch`) AND the entry's `note` field mentions Azure free tiers:

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
applies is `references/vendored/estimate/ri-sp-eligibility.md`.

**Section 4 — Security & Cost Guardrails (teaser — full table in Appendix G):**

Show top controls as a compact teaser:

| Control                        | What it does for you                                               | Monthly cost                         |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------ |
| GuardDuty                      | Detects compromised credentials and crypto mining within minutes   | ~$2–25/mo                            |
| CloudTrail                     | Immutable audit log of every API call — required for SOC 2         | ~$0.50–3/mo                          |
| Budget alerts                  | Email when spend exceeds threshold — catches runaway resources     | $0                                   |
| Bedrock cost anomaly detection | Alerts within ~24h if AI spend spikes unexpectedly (AI track only) | $0 (Cost Explorer anomaly detection) |

The fourth row is **conditional** — only render when `$MIGRATION_DIR/ai-migration/bedrock_monitoring.tf` exists on disk. Do NOT render based on `generation-ai.json` alone.

_Full mode:_ > See Appendix G for full security and cost guardrails table with Azure equivalents.

_Decision mode:_ > The full control-by-control table is included if you generate the execution pack.

If `preferences.json` contains compliance values (`soc2`, `pci`, `hipaa`, `fedramp`):

> **Compliance note:** Your declared compliance requirement ([standard]) triggers additional controls (AWS Config + Security Hub) at ~$3–25/mo. _(Full mode: append "See Appendix G.")_

**Do NOT include step-by-step enablement** — that belongs in `terraform/README.md` and `MIGRATION_GUIDE.md`.

Source: static content + `preferences.json` compliance values

**Section 5 — Operational Changes (conditional rows only):**

Only render rows for service types PRESENT in the design artifact. Do not show rows for services not in the migration.

| Azure Service                | AWS Service                 | What stays the same                               | What's new                                                                                                        |
| ---------------------------- | --------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| App Service / Container Apps | Elastic Beanstalk / Fargate | Managed web/containers, auto-scaling, pay-per-use | One App Service Plan maps to one Elastic Beanstalk env (fan-in preserved); ALB for HTTP routing; ECR replaces ACR |
| Azure SQL / Flexible Server  | RDS / Aurora                | Managed DB, automated backups, PITR               | Parameter groups replace server parameters; Security Groups replace firewall rules                                |
| Blob Storage                 | S3                          | Object storage, lifecycle policies, versioning    | Bucket policies replace RBAC/SAS; CloudFront needed for public CDN                                                |
| Azure OpenAI                 | Bedrock                     | Managed API, pay-per-token                        | IAM-based access (no API keys); SDKs differ (Azure OpenAI SDK path maps to the Bedrock/OpenAI adapter)            |

**Conditional rendering:** Check design artifact for each `azure_type` / `aws_service` pair. Only include rows where the Azure source type exists in the design. If a service category has no match, skip that row entirely.

Source: static template filtered by design artifact service types

**Section 6 — Timeline:**

- _Full mode:_ migration approach (phased/fast-track/conservative), the ordered
  stage sequence (no week column — order is the information), `duration_drivers[]`
  with the binding driver first, and the operational time policies (watch
  periods, observation windows — these are policy, keep them). **No
  implementation-effort hours** — uncalibrated staffing-shaped numbers get
  pasted into budgets; if a legacy artifact carries hour fields, drop them
  (do not render even with a label). When infrastructure was classified Large
  solely because AI coexists, treat that as an invalid stale classification
  and re-run complexity sizing before rendering. Source: generation plan.
- _Decision mode:_ the same rules as decision-summary item 4 (`duration_hint` path-shape, else tier driver summary, labeled "if you execute"; legacy week values only with the "Legacy planning heuristic (uncalibrated)" label), plus the migration approach from `recommendation.path_label`. **Omit engineering effort hours** — they don't exist before Generate and are never estimated. Source: `migration-preview.json` / complexity drivers / estimation artifact.

**Section 7 — Top Risks:**

- Up to 3 highest-severity risks
- Table columns: Risk · **Impact** · **Likelihood** · Mitigation — impact and likelihood are separate badge columns (`.badge-impact-critical` / `.badge-impact-high`, `.badge-like-low` / `.badge-like-medium`), never combined into one prose string like "Critical impact (low probability)" — a risk matrix is scanned, not read
- _Full mode source:_ generation plan `risk_assessment` (preferred).
- _Decision mode source_ (in order; **never leave `exec-risks` empty** when any of these exist): (1) risk/condition items in `estimation-infra.json` → `recommendation` (`conditions[]`, `would_flip_if[]`); (2) deferred-specialist rows from the design artifact (e.g. Synapse/Data Factory excluded from totals); (3) material `chosen_by: "default"` assumptions with cost or HA impact from `preferences.json` (e.g. availability defaulted — "~2x database cost swing; confirm before cutover sizing"). Invent nothing beyond these artifacts.

**Section 8 — What this assessment rests on (`exec-assumptions`, REQUIRED):**

> Rendered heading is a plain title — e.g. `<h2>What This Assessment Rests On</h2>` with `<section id="exec-assumptions">`. Never render a literal "Section 8" heading (validator readability rule).

Placed at the **end of the executive summary** — after Top Risks, immediately before the appendices — where assumption and validation sections conventionally sit in a migration report. The decision summary links here via the confidence pointer (item 1b). Three parts, all read from existing artifacts — invent nothing:

1. **Assumptions applied by default** — table of every constraint in `preferences.json` with `chosen_by: "default"`: Setting (plain name), Assumed value, and the constraint's `design_consequence` verbatim. When no constraint was defaulted, render one line: "All inputs were confirmed by you or extracted from your Terraform/billing — nothing was assumed."
2. **Confidence** — one line from `recommendation.confidence` with a plain-language gloss: high — "inputs measured or confirmed"; medium — "some material inputs assumed"; low — "key inputs missing or stale". When v2 `decision_basis` exists, render its three lists (measured / assumed / unknown) as compact columns instead of the single line.
3. **Pricing provenance** — from the estimation artifact: `pricing_source` + cache date + `accuracy_confidence` band, matching the wording the Estimate chat summary already uses (e.g. "Estimates based on cached AWS pricing (2026-03-07), accuracy ±5–10%").

TOC: link `#exec-assumptions` in the executive list. The anti-stub rule applies: this section must render actual settings and consequences, never "see preferences.json".

Source: `preferences.json`, `estimation-infra.json` (falls back to `estimation-ai.json` accuracy fields for AI-only runs)
