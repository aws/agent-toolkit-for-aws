---
_fragment: report
_of_phase: generate
_contributes:
  - migration-report.html
---

# Generate — Stakeholder HTML Report (Heroku)

> Thin shareable HTML for SAs / founders. Not a full GCP/Vercel assessment
> clone — decision + costs + optional what-if scenarios, then point at
> `MIGRATION_GUIDE.md` for procedure. Runs **after** docs so the guide exists
> when the report links to it.
>
> **This file is the single source of truth for `decision-summary` /
> `decision-basis` / `exec-costs` / `what-if-scenarios` content rules.**
> `references/shared/report-decision-core.md` (loaded by the Decision gate,
> `estimate-assemble.md` choice A) reuses these same rules to render
> `decision-report.html` — it does not restate them. If you change a section's
> content rule here, it applies to both outputs.

**Execute ALL steps in order. Do not skip.**

---

## Inputs

| Artifact                                                                                                                       | Use                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `estimation-infra.json`                                                                                                        | Recommendation path, three cost tiers, complexity, `optimization_opportunities[]`                                                                                               |
| `aws-design.json`                                                                                                              | Short service count / primary compute target                                                                                                                                    |
| `preferences.json`                                                                                                             | Region, HA, arch (active scenario = working tree)                                                                                                                               |
| `scenarios/index.json` + manifests **+ each scenario's `scenarios/scenario-NNN.preferences.json` / `.aws-design.json` copies** | What-if table when ≥2 scenarios — manifests carry the cost tiers/complexity; the per-scenario Region/HA/Compute/Arch columns come from the scenario's preferences/design copies |
| `MIGRATION_GUIDE.md`                                                                                                           | Must already exist (docs fragment ran first)                                                                                                                                    |

---

## Step 1: Gather figures

From `estimation-infra.json`:

- `recommendation.path_label` (or `financial_summary.recommendation`)
- `recommendation.outcome` / `outcome_label` / `conditions[]` / `decision_basis` /
  `would_flip_if[]` when present (v2 decision fields from Estimate Part 8 — tolerate
  absence on pre-extension artifacts and fall back to `path_label`)
- `recommendation.confidence` when present
- `projected_costs.aws_monthly_premium` / `_balanced` / `_optimized`
- `complexity_tier`
- `pricing_source.status` (for a one-line pricing confidence note)

From design + preferences: region, primary compute (EB / Fargate / EKS),
service count.

---

## Step 2: Write `migration-report.html`

Write a **self-contained** HTML file to `$MIGRATION_DIR/migration-report.html`
(inline CSS only). Required section IDs:

| Section ID          | Content                                                                                                                                                                                                                                                                                      |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `decision-summary`  | Typography-first verdict (see below), cost one-liner, next action                                                                                                                                                                                                                            |
| `exec-costs`        | Heroku-vs-AWS side-by-side when a Heroku baseline exists (`current_costs.source != "unavailable"`); otherwise the AWS three-tier table with a one-line note that no Heroku baseline was available. Estimated monthly; Balanced primary                                                       |
| `cost-optimization` | Reserved Instance / Savings Plan opportunities table, or the explicit no-eligible-commitment statement — see below. Always present, never omitted                                                                                                                                            |
| `next-steps`        | Ordered list pointing to `MIGRATION_GUIDE.md` phases (not a procedure dump). Include one bullet noting the Terraform ships with `baseline.tf` (account security baseline — GuardDuty, CloudTrail, budget alerts) and that three contact emails must be set in tfvars before `terraform plan` |

### `decision-summary` content (REQUIRED)

1. **Verdict (typography-first — the thesis of this section):** When
   `recommendation.outcome` exists, render `outcome_label` as the section's
   **headline** in large display type (e.g.
   `<p class="verdict-headline">Go, with conditions</p>`), then one body-type
   metadata line: `Execution shape: [path_label] · Complexity: [complexity_tier]`.
   Do **not** render the verdict as a row of colored pill badges — structure
   carries the information; meaning must never depend on color alone (a muted
   accent on the headline is fine; the words carry the verdict). When `outcome`
   is absent (pre-extension artifacts), use `path_label` as the headline the
   same way.
   - `conditional_go`: render `conditions[]` as a short checklist under the
     metadata line.
   - `defer_for_evidence`: lead with what IS established ("AWS can host this
     stack; AWS-side estimate $X–$Y/mo"), then the named missing evidence and
     how to obtain it — never present defer as "no answer," and do not show a
     savings headline as if the decision were made.
   - `stay`: headline is the stay label; do not imply a migrate path.
2. **Confidence pointer (when `confidence` or `decision_basis` exists):** one
   line under the verdict — `Confidence: [confidence] — full basis in
   <a href="#decision-basis">What This Assessment Rests On</a>.`
3. **Cost one-liner** — Balanced AWS monthly vs Heroku baseline when available
   (estimated monthly), else AWS Balanced alone.
4. **What would flip this (v2):** from `recommendation.would_flip_if[]` when
   present — short unordered list. Skip silently when absent.
5. **One-sentence next action** — the single most useful next step for the
   reader (Generate artifacts, confirm a condition, or gather named evidence).

### `decision-basis` (end of summary, when v2 fields exist)

When `recommendation.decision_basis` is present, render
`<section id="decision-basis">` **after** `decision-summary` and **before**
`exec-costs` (or immediately before `next-steps` if you keep costs first —
either order is fine as long as the confidence pointer's href resolves):

- Heading: `What This Assessment Rests On` (plain title — never "Section N").
- Three compact columns/lists from `decision_basis`: **Measured** / **Assumed** /
  **Unknown**. Invent nothing — copy the arrays as written.
- One-line pricing provenance from `pricing_source` + accuracy band.

Omit the section when `decision_basis` is absent (pre-extension artifacts).

### `cost-optimization` (REQUIRED — always render, never omit)

Render `<section id="cost-optimization">` after `exec-costs` (before
`what-if-scenarios` when present, otherwise before `next-steps`). Source:
`estimation-infra.json` → `optimization_opportunities[]`, per the eligibility
rules and three-state model in
`references/vendored/estimate/ri-sp-eligibility.md`.

- **When `optimization_opportunities` is non-empty:** render a table with
  columns Optimization, Target Services, Monthly Savings, Commitment, Effort.
  Below the table, one line: "Activate credits don't cover RI/Savings Plan
  upfront costs — they apply only to the ongoing discounted hourly rate."
- **When `optimization_opportunities` is empty:** do not omit the section or
  leave it blank. Render one sentence: "No 1-year/3-year commitment product
  applies to this architecture." When Bedrock is part of the design, add:
  "Bedrock inference has a separate mechanism (Provisioned Throughput, 1- or
  6-month commitment), evaluated separately from Reserved Instances/Savings
  Plans."

Heading: `Cost Optimization Opportunities` (plain title — never "Section N").

### Conditional — `what-if-scenarios`

When `scenarios/index.json` exists and `scenarios[]` has **≥ 2** entries,
render `<section id="what-if-scenarios">` **after** `exec-costs` and **before**
`next-steps`:

Render, in order:

- Table columns (must stay in sync with `workshop-compare.md`'s table):

| Scenario | Region | HA | Compute | Arch | Premium $/mo | Balanced $/mo | Optimized $/mo | Complexity |
| -------- | ------ | -- | ------- | ---- | ------------ | ------------- | -------------- | ---------- |

- Mark the active row (`index.active_scenario_id`).
- `estimation_summary.calculator_url` is always `null`; no calculator link is rendered.
- Under the table: active vs baseline knob deltas; any `region_note`; remind
  inventory is frozen and Terraform matches the **active** scenario only.

Omit the section when workshop was declined or never entered.

### TOC + footer

- `<nav class="toc">` with links to every section present.
- Footer must include: `draft for review` and instruct readers to verify figures
  before sign-off.
- Title: `Heroku to AWS Migration Assessment`.
- Cost labeling: every dollar figure is an **estimated monthly** cost.
- Reader vocabulary: no `*.json` filenames or `aws_*.` resource IDs in
  `decision-summary` / `exec-costs` / `what-if-scenarios` (name things the
  reader controls).

### Minimal CSS

Use a short inline stylesheet: readable body font, `.report` max-width ~900px,
tables with borders, `.active-scenario` or bold active row,
`.verdict-headline` (large display type for the outcome — **not** a colored
pill badge row), `.toc` list. Keep visual noise low — this is a one-pager for
stakeholders, not a design system.

### Skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Heroku to AWS Migration Assessment</title>
  <style>/* inline */</style>
</head>
<body>
  <div class="report">
    <nav class="toc">…</nav>
    <section id="decision-summary">…</section>
    <!-- <section id="decision-basis"> when recommendation.decision_basis exists -->
    <section id="exec-costs">…</section>
    <section id="cost-optimization">…</section>
    <!-- <section id="what-if-scenarios"> when ≥2 scenarios -->
    <section id="next-steps">…</section>
    <footer>Generated by Heroku to AWS Migration Advisor — draft for review; verify figures before executive sign-off.</footer>
  </div>
</body>
</html>
```

---

## Step 3: Soft gate

Before returning:

1. File exists and is non-empty.
2. Contains `decision-summary`, `exec-costs`, `cost-optimization`, `next-steps`, and `draft for review`.
3. When `recommendation.outcome` exists: `decision-summary` contains the
   `outcome_label` text (or a `verdict-headline` element) — not a row of colored
   pill badges as the sole verdict carrier.
4. When `recommendation.decision_basis` exists: contains `decision-basis`.
5. If `scenarios/index.json` has ≥2 scenarios, contains `what-if-scenarios`.
6. `cost-optimization` is non-empty — either the table or the explicit
   no-eligible-commitment sentence, never a blank section.

On failure: fix and rewrite — do **not** leave a stub. Report generation is
part of Generate for heroku-to-aws (stakeholder deliverable), but a report
failure should not delete Terraform/docs; repair the HTML and continue.

Optional (non-blocking): if
`$PLUGIN_ROOT/scripts/validate-heroku-migration-report.py` exists, run:

```
python3 scripts/validate-heroku-migration-report.py \
  "$MIGRATION_DIR/migration-report.html" --mode full --migration-dir "$MIGRATION_DIR"
```

Exit 0 (`REPORT_OK`) → continue. Non-zero (`REPORT_FAIL | ...`) → repair the
named section(s) and re-run once; if it still fails, keep the best HTML, record
the failure line in `generation-warnings.json`, and continue (never a
generation halt).

---

## Scope Boundary

**This fragment writes `migration-report.html` ONLY.**

FORBIDDEN:

- Re-running Design / Estimate / workshop
- Duplicating the full `MIGRATION_GUIDE.md` procedure into HTML
- Inventing cost figures not present in `estimation-infra.json` / scenario
  manifests
