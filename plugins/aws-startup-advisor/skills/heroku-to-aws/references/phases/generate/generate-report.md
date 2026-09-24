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

**Cost-figure anchor (machine-checkable).** In `exec-costs`, wrap the recommended AWS
monthly (Balanced) dollar figure in a `data-cost-key="aws_monthly_balanced"` attribute so
the validator can confirm it matches `estimation-infra.json` `projected_costs.aws_monthly_balanced`
— e.g. `<span data-cost-key="aws_monthly_balanced">$112/mo</span>`. The attribute is not
reader-visible text. The validator asserts the rendered dollars equal the JSON for every
anchor present. **The `aws_monthly_balanced` anchor is mandatory whenever that JSON value
exists and `exec-costs` is rendered — a missing anchor is a validator FAIL, not a skip.**
Only untagged _illustrative_ numbers are skipped.

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
- **Whole-dollar monthly figures (blocking).** Render every monthly-scale dollar
  figure ($2 or more) as a **whole dollar** — `$112/mo`,` $25,684/mo` — never with
  cents (`$112.34/mo`fails the report validator's currency gate and blocks
  Generate). Cents are allowed only for genuinely sub-dollar precision (` $1.50`,
  `$0.40`) or an explicit per-unit rate (` $0.018/hr`, `$5.00/mo per policy`). Round
  the`projected_costs.*`tiers and the Heroku baseline to the nearest dollar when
  you write them into`exec-costs`, the cost one-liner, and the what-if table.
- Reader vocabulary: no `*.json` filenames or `aws_*.` resource IDs in
  `decision-summary` / `exec-costs` / `what-if-scenarios` (name things the
  reader controls).

### Minimal CSS

Use a short inline stylesheet: readable body font, `.report` max-width ~900px,
tables with borders, `.active-scenario` or bold active row,
`.verdict-headline` (large display type for the outcome — **not** a colored
pill badge row), `.toc` list. Keep visual noise low — this is a one-pager for
stakeholders, not a design system.

### Table & figure accessibility (REQUIRED — the blocking validator enforces these)

- **Every `<th>` must declare `scope="col"` or `scope="row"`.** The report's tables
  (`exec-costs`, `cost-optimization` when opportunities exist, `what-if-scenarios`) are
  column-headed, so emit `<th scope="col">…</th>` for each header cell.
- **If you emit a `<figure>`, it must carry a non-empty `aria-label` and a `<figcaption>`.**
  The one-pager normally has no figures; this only applies if you add one.
- `<html>` carries `lang="en"` (the skeleton already does).

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
    <section id="exec-costs">
      <!-- every <th> declares scope; copy this header pattern for cost-optimization + what-if too -->
      <table>
        <thead><tr><th scope="col">Service</th><th scope="col">Heroku</th><th scope="col">AWS (Balanced)</th></tr></thead>
        <tbody>…
          <tr><td>Total</td><td>…</td><td><span data-cost-key="aws_monthly_balanced">$NNN/mo</span></td></tr>
        </tbody>
      </table>
    </section>
    <section id="cost-optimization">…</section>
    <!-- <section id="what-if-scenarios"> when ≥2 scenarios -->
    <section id="next-steps">…</section>
    <footer>Generated by Heroku to AWS Migration Advisor — draft for review; verify figures before executive sign-off.</footer>
  </div>
</body>
</html>
```

---

## Step 3: Self-check (in-fragment) + blocking validation (main window)

**In-fragment self-check (this fragment, no shell).** Before returning, confirm the HTML you
wrote satisfies the contract, and if not, **fix and rewrite it here** (this is the one place
the report is edited — a stub is never acceptable):

1. File exists and is non-empty.
2. Contains `decision-summary`, `exec-costs`, `cost-optimization`, `next-steps`, and `draft for review`.
3. `decision-summary` must **not contain** any `badge-verdict-*` class; when
   `recommendation.outcome` exists it must render a `verdict-headline` element.
4. When `recommendation.decision_basis` exists: contains `decision-basis`.
5. If `scenarios/index.json` has ≥2 scenarios, contains `what-if-scenarios`.
6. `cost-optimization` is non-empty — the table or the explicit no-eligible-commitment
   sentence, never a blank section. If you wrote the sentence, it renders as visible
   text (not only inside a comment/`<template>`) and reads verbatim once entities decode.
7. Every `<th>` declares `scope="col"`/`"row"`; any `<figure>` has `aria-label` + `<figcaption>`.
8. **No monthly-scale dollar figure renders with cents.** Scan every `$` figure: any
   monthly total $2 or more must be whole-dollar (`$112/mo`, not` $112.34/mo`) — the
   validator's currency gate is blocking. Round any cents you find on a monthly figure
   before returning. (Cents are fine only on sub-$2 amounts or explicit per-unit rates.)
9. When `projected_costs.aws_monthly_balanced` is present, `exec-costs` wraps that
   figure in `<span data-cost-key="aws_monthly_balanced">$NNN/mo</span>` (the
   validator FAILs on a missing anchor — it is how the rendered figure is confirmed
   against the estimate). The attribute is not reader-visible text.

A report failure must not delete the Terraform/docs — repair the HTML in this fragment. Fixing
the report is **only** done here, before control returns; the completion gate never edits it.

**Blocking validation runs in the MAIN window, not here.** This fragment runs in a dispatched
`_exec._agent: rw` worker with no shell (`INTERPRETER.md` § capability tiers), so it cannot run
the validator. The interpreter runs it in `generate.md`'s **"Finish Generate in the main window
(report validation)"** step — which executes **after** this worker returns and **before** the
read-only `_postconditions` gate (per `INTERPRETER.md` § `_exec` step 4, gates are never
dispatched):

```
python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" --mode full --migration-dir "$MIGRATION_DIR"
```

`REPORT_OK` → the report gate passes. `REPORT_FAIL` → the main-window step emits `GATE_FAIL` **and
pastes the validator's `errors[]` verbatim**; the gate does not edit the HTML itself. The pasted
errors are what make recovery actionable — a bare "re-run Generate" is not a fix, since re-dispatch
re-authors the report under this shell-less worker. On `REPORT_OK` the finish step stamps
`report-validation-status.json` (the durable result the read-only gate asserts). Recovery is a
hand-edit of the report from those errors + a direct validator re-run and re-stamp (or a maintainer
re-running Generate for a clean rebuild).
The validator enforces the required sections, the `draft for review` footer, the typography-first
verdict rules, non-empty `cost-optimization`, and the a11y subset the report emits (`<th scope>`,
`<figure>` labels).

---

## Scope Boundary

**This fragment writes `migration-report.html` ONLY.**

FORBIDDEN:

- Re-running Design / Estimate / workshop
- Duplicating the full `MIGRATION_GUIDE.md` procedure into HTML
- Inventing cost figures not present in `estimation-infra.json` / scenario
  manifests
