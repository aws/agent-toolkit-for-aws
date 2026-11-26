# Report Decision Core (Render to AWS Migration Assessment)

The executive-summary sections below are the **decision core** — the single
source of truth for verdict, cost, timeline, risk, and assumption rendering in
`migration-report.html`. This skill has no Decision gate and writes no
`decision-report.html`: after Estimate, `estimate-assemble.md` offers
**Done for now** or **Generate**, and the report is rendered only by Generate
(`generate-artifacts-report.md` Step 1). **Only full mode exists.** Every rule
in this file applies unchanged; there is no decision-mode override to consult.

The report is rendered **fresh from the artifacts** on every Generate run. All
data it needs lives in the JSON artifacts under `$MIGRATION_DIR`; recalled
values from the chat transcript are never a source.

This file is self-contained. It carries the reference wording for the rules the
plugin-root validator enforces, so a render-only install reads no file from any
other migration skill.

---

The executive summary is the first thing visible when opening the report. Design it to fit approximately 1–2 printed pages.

## Executive Summary Content

**Header:** "Render to AWS Migration Assessment" with subtitle "Executive Summary" and generation date (ISO 8601, e.g. 2026-10-21).

**Table of contents (required — placed AFTER the decision summary, never before it):** Linked `<nav class="toc" aria-label="Table of contents">` listing all executive sections, the migration-execution sections, and the appendix sections present in this report. **Every `href="#section-id"` MUST match a `<section id="section-id">` on the page exactly** (same string, including hyphens), and every rendered section is linked. `nav.toc` carries `id="toc"` so each section `<h2>` can end with a `↑ contents` toplink. Omit TOC links only for sections not rendered.

**The hero is the thesis (opening order):** the reader's first screenful is the decision, not navigation. Page order: title line → `decision-summary` (verdict headline + hero metrics) → TOC → remaining sections. A long link menu between the title and the verdict makes the reader scroll past chrome to learn the answer; the document's thesis — "Migrate, phased · Est. $X/mo · long pole: PostgreSQL cutover" — must be visible before any menu.

**Target length:** approximately 2–4 printed pages for the executive summary. **Do NOT truncate appendices** to fit page count — appendices may be long.

**Anti-stub rule (mandatory):** every rendered section MUST carry real artifact data as HTML tables and prose. **Forbidden:** sections that only say "see the estimate" or list JSON filenames without numeric costs, service mappings, or migration phases. Artifact filenames (`*.json`) and Terraform resource IDs (`aws_x.y`) never appear inside `decision-summary` or any `exec-*` section; appendices and `deferred-surfaces` may name them. Reference fixture for the HTML shell and CSS: `$PLUGIN_ROOT/fixtures/migration-report-reference.html` (copy its structure, never its dollar figures).

**Section 0 — Migration Decision Summary (`decision-summary`, REQUIRED):**

Pull from `estimation-infra.json` → `recommendation` block (`path`, `migrate_if`, `stay_if`). Fallback if `recommendation` is absent: `financial_summary.recommendation` (string) as the path label, with migrate-if / stay-if synthesized from the Estimate prose defaults in `estimate-infra.md`.

Content when `recommendation` exists:

1. **Verdict (typography-first — the verdict is the thesis of this section):** render the recommendation path as the section's **headline statement** in large display type (e.g. `<p class="verdict-headline">Migrate, phased</p>` for `migrate_phased`), followed by one labeled metadata line in body type: "Execution shape: [path] · Complexity: [complexity_tier]". The hierarchy encodes the real relationship — the decision is the headline; how and how-hard are attributes of it. Do **not** render the verdict as a row of colored pill badges: structure carries the information, and meaning never depends on color alone (a muted color accent on the headline is fine; the words carry the verdict).
   1a. **Recommendation callout (required):** Render the one-sentence recommendation narrative directly below the headline/meta as `<div class="verdict">…</div>`. For a migrate path use the green positive callout treatment defined by the shared CSS. For a stay or defer path use the warning/neutral variant instead — never use green to imply approval. The explicit recommendation words remain required; color is only a scanning aid.
   1b. **Confidence pointer:** one line under the verdict block — `Confidence: [accuracy_confidence gloss] — full basis in <a href="#exec-assumptions">What This Assessment Rests On</a>.` The full assumptions panel lives at the **end** of the executive summary (Section 8 below), not here.
2. **Complexity:** from `estimation-infra.json` → `complexity_tier` — plain badge text.
3. **Cost headline:** Est. AWS monthly for the **Balanced** scenario (`projected_costs.aws_monthly_balanced`) beside the current Render baseline (`current_costs.render_monthly`, or the literal text `unavailable` when `current_costs.source` is `unavailable`). Label every figure "Est." and whole dollars (see Section 3).
4. **Timeline:** week counts are never rendered — the plugin has no calibrated duration data. Render the approach plus the binding duration driver (e.g. "Phased, in dependency order — long pole: PostgreSQL cutover"), taken from the stage order `MIGRATION_GUIDE.md` lays out. Never use `recommendation.next_steps` as a timeline — those are action items, not duration.
5. **Migrate if / Stay entirely if:** from `recommendation.migrate_if` and `recommendation.stay_if`. Render as two compact lists. The customer-facing second heading is **"Stay entirely if"** so a deferred track (the AI workload, an unsupported Workflow) cannot be mistaken for a recommendation to abandon the whole migration. When `stay_if` is empty, render one line saying no whole-stack stay condition was identified — never an empty list.
6. **Key decisions ahead:** **ordered list** (`<ol class="compact">`), not bullets, built from the defaulted `preferences.json` answers with a design consequence and from `migrate_if`. Each item is one concrete decision the reader must make next.
7. **Next steps (optional):** **ordered list** (`<ol class="compact">`) of actionable steps separate from timeline. Numbered sequence implies priority order; keep `Migrate if` / `Stay entirely if` as unordered lists. When generated artifacts contain fill-in placeholders, the FIRST next step MUST state execution readiness: "Fill in the [N] account-specific values (checklist in the migration guide) — nothing can be applied until then." The report is the decision document; this line is the bridge from decision to execution.

**Section 0b — Share With Your CFO (`exec-share`, REQUIRED when `estimation-infra.json` contains a monthly source figure or an AWS estimate):**

Render immediately after the TOC. This is a copy-ready, one-paragraph decision
brief derived only from values already shown in the decision summary:

- verdict and confidence;
- estimated AWS monthly run rate for the Balanced scenario;
- source baseline only when it is comparable, otherwise say that actual Render
  billing must be confirmed;
- migration shape and binding duration driver;
- at most three conditions or evidence gaps.

Use `<div class="share-card"><p>…</p></div>` with exactly one substantive
paragraph (at least 20 words) and a short lead-in ("The one-paragraph version,
ready to forward:"). Do not add JavaScript, a copy button, editable controls,
or new calculations. The paragraph must stand alone when pasted into email or
a planning document. Label every modeled amount as estimated and preserve the
same comparability caveats as the cost section. Add `exec-share` to the TOC
only when rendered.

**Deferred AI flag:** when `estimation-infra.json` → `ai_track.status` (or the design's AI track) is `deferred_shared_ai_engine`, add a callout under the verdict stating that the AI workload is assessed separately by `bedrock-migration-assessment` and carries no target, cost, model, adapter, or Terraform in this report. This does **not** block the phased migration of the infrastructure.

**Startup credits:** this skill collects no `startup_program_status` in Clarify and writes no `STARTUP_PROGRAMS.md`, so the report renders no AWS Activate callout and makes no credits claim.

**Metric hierarchy (when the decision summary renders a metric grid):** the reader should not have to rank the numbers themselves. The one or two **primary** decision metrics — the Balanced AWS run rate, and the migration shape (approach + binding driver, e.g. "Phased · long pole: PostgreSQL cutover") — render first with `.metric-hero` treatment (larger value, accent border). Supporting metrics (Optimized scenario, savings) follow as standard cards, max ~5 total. Never render a week count or effort-hours as a metric card.

Source: `estimation-infra.json` (`recommendation`, `complexity_tier`, `accuracy_confidence`, `ai_track`), `preferences.json`, `aws-design.json`

**Section 1b — Estimated AWS Monthly Run Rate (`exec-tco`, REQUIRED only when both an infrastructure estimate AND a separate AI estimate exist):**

This skill never writes an AI estimate (the AI track is `deferred_shared_ai_engine`), so `exec-tco` is not rendered. If a future run carries both estimates, `exec-tco` is a legacy structural ID retained for validator compatibility; the customer-facing heading MUST NOT say "TCO" or "Total Cost of Ownership", the combined row sums only comparable baselines, and one sentence states "This is an estimated cloud-service run rate, not total cost of ownership."

**Section 1 — Current Stack Overview (`exec-services`, REQUIRED):**

- Count of Render resources in the design (one per `aws-design.json` mapping — the same count as `appendix-accounting`)
- List each resource with its Render kind: web service, private service, background worker, cron job, PostgreSQL, Key Value, persistent disk, static site, custom domain, build source, environment group, project, environment, Workflow, Workflow task
- Source: `aws-design.json` mappings, `render-resource-inventory.json` kinds

**Section 2 — Recommended AWS Architecture (`exec-targets`, REQUIRED):**

- Table with columns: Render resource, Kind, AWS service, Disposition, **How we chose this**
- **How we chose this** values from the mapping's confidence: **Standard pairing** (`deterministic`), **Tailored to your setup** (`inferred`), **Estimated from billing only** (`billing_inferred`). Show the **bold phrase**; the JSON value is optional in a footnote for technical readers only.
- One row per `aws-design.json` mapping. Each row is `<tr data-source-resource-id="…" data-aws-service="…">` carrying the exact mapping values; the row's visible text names the AWS service. The render-local validator compares the row set to the design exactly.
- For every ECS on Fargate mapping, state whether it is **Express or standard** and quote `aws_config.ecs_mode_reason`.
- Source: `aws-design.json`

**Section 2b — Architecture (`exec-architecture`, REQUIRED in this skill):**

The plugin-root validator requires `exec-architecture` only when the design has clusters; this skill requires it always (render-local validator). Prose or a structured diagram covering, in plain language: build-once ECR image promotion by digest, private ingress (ALB/CloudFront in front, services in private subnets unless the design placed an Express service in public subnets), managed PostgreSQL (RDS) and Valkey (ElastiCache), EFS for persistent disks, Step Functions for a supported Workflow, and tagged, isolated per-environment stacks. Name the deferred AI surface. Required phrases (render-local validator): `build-once` (or `build once`), `private`, `managed`.

Source: `aws-design.json`, `render-resource-clusters.json`

**Section 3 — Cost Comparison (`exec-costs`, REQUIRED):**

- Side-by-side display: Current Render Monthly vs Estimated AWS Monthly (**Balanced** scenario — the default scenario for comparing to Render)
- **Baseline-quality badge (required):** label the Render figure using `current_costs.source` — `billing`: "Measured from your Render billing (±5%)"; `inventory`: "Estimated from resource configs (±20–30%, standing charges only)"; `user_stated`: "Your stated figure (unverified)"; `unavailable`: render the literal text `unavailable` in the current-spend cell and say actual Render billing must be confirmed. **Never** place an inventory-only Render figure beside a user-stated band without an explicit not-comparable line — they measure different things.
- **Render scenario semantics (required):** the three AWS monthly figures are **estimated monthly costs** for the **same** mapped architecture, not three generated Terraform stacks. **Balanced = the capacity-preserving scenario** (`scenarios.capacity_preserving`, `projected_costs.aws_monthly_balanced`) — it matches the generated Terraform. **Optimized = the right-sized scenario** (`scenarios.right_sized`, `projected_costs.aws_monthly_optimized`). **Premium = the estimate's upper bound** (`projected_costs.aws_monthly_premium`). `delta_monthly_usd` = right-sized minus capacity-preserving, shown in the Optimized row's "vs Balanced" cell as a render-local `delta` anchor (negative means the right-sized scenario is cheaper).
- **Cost-figure anchors (machine-checkable, REQUIRED):** inside `exec-costs`, `data-cost-key="current_monthly"` on the element holding the Render figure (value `current_costs.render_monthly`), `data-cost-key="aws_monthly_balanced"` (value `projected_costs.aws_monthly_balanced`), `data-cost-key="aws_monthly_optimized"` (value `projected_costs.aws_monthly_optimized`; exactly one anchor), `data-cost-key="aws_monthly_premium"` (value `projected_costs.aws_monthly_premium`; exactly one anchor, required whenever that value exists, which the estimate schema always carries), and the render-local `data-cost-key="delta"` (value `delta_monthly_usd`, rendered as `-$62` or `$-62`). Each anchor sits on a rendered element inside `exec-costs` itself — not in an HTML comment, and not only in a decision-summary hero metric. A missing required anchor is a validator FAIL, not a skip.
- **Whole dollars:** every monthly figure renders as whole dollars rounded half-to-even (358.5 → `$358`, 296.5 → `$296`, 123.45 → `$123`, 394.35 → `$394`). Cents fail the currency gate.
- Percent change (savings or increase). Render supported savings with the green `.savings` class and increases with `.increase`. Never color a percentage as savings when the Render and AWS baselines are not comparable; use an absolute estimated-cost card plus the not-comparable note instead.
- **Cost labeling rule:** All dollar figures in cost tables and metrics MUST be labeled as estimated monthly costs. Use column headers like "Est. Monthly AWS" or "Estimated Monthly" — never present figures as exact amounts.
- **Not-comparable rendering:** the mandatory not-comparable warning is NOT collapsible and does not sit as a paragraph between the heading and the numbers — attach it to the Render figure itself: a `.chip-warn` pill ("⚠ not comparable") plus the one-line explanation in its `<small>`.
- **How to read cost tiers (required; rendered as a `<details class="reading-guide">` immediately AFTER the tier table — data first, explanation adjacent):** Premium → Balanced → Optimized is highest → middle → lowest. Balanced is the **primary** row vs Render; Premium and Optimized are **bounds**. `terraform/` implements **one** infrastructure baseline aligned with the Balanced (capacity-preserving) scenario.
- Tier table rows with **short subtitles**:
  - **Premium** — _Upper bound of this estimate_
  - **Balanced** — _Capacity-preserving scenario; the generated Terraform baseline; compare Render to this row first_
  - **Optimized** — _Right-sized scenario; lower monthly estimate_
- **Footnote (required):** _All figures are estimated monthly costs based on AWS pricing data at time of analysis. Only one Terraform configuration is generated (Balanced-aligned, capacity-preserving baseline). Premium and Optimized are what-if cost models — adjust IaC yourself if you want those postures in production._ State that human labor is excluded (`migration_cost_considerations.human_labor_monthly_usd` is null).
- When either scenario has `is_floor: true` or non-empty `unpriced_line_ids`, say the total is a **known-cost floor** and name the unpriced lines.
- Source: `estimation-infra.json`

**Section 3b — What-if scenarios (`what-if-scenarios`, OPTIONAL):**

Render **only when** `$MIGRATION_DIR/scenarios/index.json` exists and lists ≥ 2 scenarios (baseline + at least one workshop variant). Omit entirely when the workshop was declined or never entered. Columns: Scenario, Region, HA, Compute, Arch, Premium $/mo, Balanced $/mo, Optimized $/mo, Complexity; mark the active row; place it immediately after `exec-costs`; link `#what-if-scenarios` only when rendered.

**Section 3c — Cost Optimization (`exec-optimization`, REQUIRED when `estimation-infra.json` → `optimization_opportunities[]` is non-empty):**

A **standalone executive section** immediately after `exec-costs` (before `what-if-scenarios` / `exec-timeline`); a table buried in an appendix does not satisfy it. Render a posture comparison (Balanced on-demand vs applicable commitments vs Optimized as a floor; Savings Plans and Reserved Instances are incremental to Balanced, never added on top of Optimized, which already embeds reservation or Spot assumptions) and a short "which commitment fits" list. The line-level opportunity table lives in `<section id="appendix-optimization">` (Appendix B.1) immediately after `appendix-costs`; `exec-optimization` links down to it. Omit both when the array is empty.

**Section 6 — Timeline (`exec-timeline`, REQUIRED):**

Migration approach (phased/fast-track/conservative), the ordered stage sequence from `MIGRATION_GUIDE.md` (prerequisites → build and deployment → PostgreSQL → Key Value → persistent disk → deployment and service cutover → DNS and traffic → verification; no week column — order is the information), the binding duration driver first, and the operational time policies (watch periods, observation windows — these are policy, keep them). **No implementation-effort hours** and **no week counts** — uncalibrated staffing-shaped numbers get pasted into budgets. Source: `MIGRATION_GUIDE.md`, `estimation-infra.json` → `complexity_tier`.

**Section 7 — Top Risks (`exec-risks`, REQUIRED, rendered as a `<table>`):**

- Up to 3–5 highest-severity risks, **never empty**
- Table columns: Risk · **Impact** · **Likelihood** · Mitigation — impact and likelihood are separate badge columns (`.badge-impact-critical` / `.badge-impact-high`, `.badge-like-low` / `.badge-like-medium`), never combined into one prose string like "Critical impact (low probability)" — a risk matrix is scanned, not read
- Sources, in order: (1) `recommendation.migrate_if` conditions; (2) `generation-warnings.json` warnings (`ecs_express_not_selected_rolling_release`, `conditional_workflow_generation_unsupported`, `unpriced_cost_floor`, `eb_platform_*`); (3) the deferred AI track; (4) material defaulted `preferences.json` answers with cost, cutover, or HA impact (e.g. `cutover.source_retention` defaulted). Invent nothing beyond these artifacts.

**Section 8 — What this assessment rests on (`exec-assumptions`, REQUIRED):**

> Rendered heading is a plain title — e.g. `<h2>What This Assessment Rests On</h2>` with `<section id="exec-assumptions">`. Never render a literal "Section 8" heading (validator readability rule).

Placed at the **end of the executive summary** — after Top Risks, immediately before the migration-execution sections — where assumption and validation sections conventionally sit in a migration report. The decision summary links here via the confidence pointer (item 1b). Three parts, all read from existing artifacts — invent nothing:

1. **Assumptions applied by default** — table of every `preferences.json` question with disposition `defaulted`: Setting (plain name), Assumed value, and the consequence for the design. When nothing was defaulted, render one line: "All inputs were confirmed by you or extracted from your Blueprint/billing — nothing was assumed."
2. **Confidence** — one line from `accuracy_confidence` with a plain-language gloss: high — "inputs measured or confirmed"; medium — "some material inputs assumed"; low — "key inputs missing or stale".
3. **Pricing provenance** — from `estimation-infra.json` → `pricing_source` (`status`, `message`, `services_by_source`) and `accuracy_confidence`, matching the wording the Estimate chat summary already uses (e.g. "AWS rates use the reviewed us-east-1 cache; Render baseline is user stated").

TOC: link `#exec-assumptions` in the executive list. The anti-stub rule applies: this section must render actual settings and consequences, never "see preferences".

Source: `preferences.json`, `estimation-infra.json`

## Readability rules (validator-enforced)

- No intensifiers: never write "very", "significantly", "extremely", or "vastly".
- No "Section N" headings and no "Rubric:" labels in rendered text.
- Dates in ISO 8601 only.
- Every `<table>` has a `<caption>`; every `<th>` carries `scope="col"` or `scope="row"`. Images have non-empty `alt`; figures have an `aria-label` and `<figcaption>`. Do not use color as the only status carrier.
- Appendix headings and TOC labels carry their stable letters (`generate-artifacts-report.md` Step 3.75) and the appendix block opens with `<div class="appendix-header">`.
- The footer says `draft for review` and tells the reader to validate estimates before decisions.

## Render-specific required sections

The plugin-root validator requires `decision-summary`, `exec-assumptions`, `exec-services`, `exec-costs`, `exec-timeline`, `exec-risks`, `appendix-services`, `appendix-costs`, `appendix-steps`, `appendix-artifacts`, plus `exec-share` and `appendix-glossary` under their triggers. This skill additionally requires each section below exactly once, non-empty, and linked from the TOC (render-local validator codes `SECTION_<ID>_MISSING` / `_DUPLICATE` / `_EMPTY`, `TOC_RENDER_SECTION_MISSING`). The phrases in `code` are the terms the render-local validator looks for in each section's rendered text (case-insensitive; one alternative per group suffices).

1. `exec-architecture` — Section 2b above. Terms: `build-once` or `build once`; `private`; `managed`.
2. `exec-targets` — Section 2 above: one `<tr data-source-resource-id data-aws-service>` row per design mapping with the service in visible text (`TARGET_MAPPING_MISMATCH`, `TARGET_VISIBLE_TEXT_MISMATCH`, `TARGET_ROW_ATTRIBUTES_INCOMPLETE`).
3. `migration-data` — PostgreSQL full-load/CDC procedure, Key Value transition, writer quiescence, integrity checks, and source retention. Terms: `postgres`; `Database Migration Service` or `pg_dump`; `quiesc`; `integrity`; `source retention`.
4. `migration-storage` — EFS pre-copy/delta transfer for `/var/data`, ownership/permissions/locking checks, quiescence, integrity, and rollback. Terms: `efs`; `/var/data`; `pre-copy`; `delta`; `ownership`; `permissions`; `integrity`.
5. `migration-deployment` — build-once ECR digest promotion, serving-deploy identity, auto-deploy state, immutable rollout, and rollback lineage. Terms: `ecr`; `digest`; `serving deploy`; `auto-deploy`; `rollback`.
6. `cutover` — prerequisites, certificate readiness, DNS TTL, writer quiescence, traffic shift, and acceptance checks. Terms: `dns`; `ttl`; `certificate`; `traffic`; `writer quiescence`.
7. `rollback` — rollback triggers, writer fencing, DNS/traffic restoration, target cleanup limits, and retained Render source. Terms: `source retention`; `render`; `restore`; `dns`; `writer`.
8. `verification` — concrete endpoint, database, cache, disk, worker/cron, and Workflow checks. Terms: `endpoint`; `database`; `cache`; `disk`; `workflow`.
9. `deferred-surfaces` — the exact `deferred_shared_ai_engine` warning paragraph and every `conditional_workflow_generation_unsupported` warning. Deferred work is never represented as generated (`AI_DEFERRED_STATE_MISSING`, `AI_DEFERRED_WARNING_UNEXPECTED`, `WORKFLOW_LIMIT_MISSING`).
10. `appendix-accounting` — heading "Appendix A.1 — Generation Accounting" (the `.1` keeps the shared letters A–J from shifting): design/generated/consumed-topology/deferred/unsupported counts and all source rows. The section carries `data-accounted-count` equal to `generation-warnings.json` → `accounting.accounted_count` (`REPORT_ACCOUNTED_COUNT_MISMATCH`).

Cost checks owned by the render-local validator: `delta` (`COST_DELTA_MISSING` / `COST_DELTA_SOURCE_INVALID` / `COST_DELTA_MISMATCH`); the unavailable-baseline literal (`COST_CURRENT_MONTHLY_MISSING` / `COST_CURRENT_MONTHLY_UNAVAILABLE_TEXT_MISMATCH`); anchor presence, exactly one inside `exec-costs`, for `aws_monthly_optimized` and `aws_monthly_premium` (`COST_AWS_MONTHLY_OPTIMIZED_MISSING` / `COST_AWS_MONTHLY_PREMIUM_MISSING`); and the projected/scenario equalities `projected_costs.aws_monthly_balanced` = `scenarios.capacity_preserving.known_cost_monthly_usd` and `projected_costs.aws_monthly_optimized` = `scenarios.right_sized.known_cost_monthly_usd` (`COST_AWS_MONTHLY_BALANCED_SCENARIO_MISMATCH` / `COST_AWS_MONTHLY_OPTIMIZED_SCENARIO_MISMATCH`). The dollar values of `current_monthly`, `aws_monthly_balanced`, `aws_monthly_optimized`, and `aws_monthly_premium` are asserted by the plugin-root validator.

## Cross-artifact truth

The render-local validator compares rendered targets to every `aws-design.json` mapping and accounting to `generation-warnings.json`; the plugin-root validator compares cost anchors to `estimation-infra.json`. The generation ledger classifies every design source exactly once as generated, consumed topology, deferred, or conditionally unsupported. AI is represented only by the exact deferred state; Workflow Terraform is represented only when its semantics are supported and validated.

The report is a customer artifact. It never contains source secrets, environment values, personal data, repository URLs, account/workspace/project/environment IDs, or local paths (`PRIVACY_EMAIL`, `PRIVACY_RENDER_API_KEY`, `PRIVACY_AWS_ACCESS_KEY`, `PRIVACY_PRIVATE_KEY`, `PRIVACY_LOCAL_PATH`).

## Validation

Two validators gate the report, both run in the main window with absolute paths (`generate-artifacts-report.md` Step 5):

- `$PLUGIN_ROOT/scripts/validate-migration-report.py` is the structure/content gate: required section IDs and order, the CSS shell, verdict and metric-hero markup, the risk table, assumptions after risks, appendix depth and lettering, readability, accessibility, the glossary, and the shared cost anchors. This file carries the reference wording for its rules (copied here, so no file from another migration skill is read).
- `$SKILL_BASE/scripts/validate-render-migration-report.py` is the render-only pass: the sections, terms, target rows, accounting, ledger reconciliation, the render-local cost checks above (`delta` anchor, unavailable-baseline literal, optimized/premium anchor presence, projected/scenario equality), and exclusions.

Both must print `REPORT_OK`. A report that fails either is renamed `migration-report.incomplete.html`; it remains available for diagnosis but MUST NOT satisfy Generate `_produces` or completion. There is no skip-and-complete path.
