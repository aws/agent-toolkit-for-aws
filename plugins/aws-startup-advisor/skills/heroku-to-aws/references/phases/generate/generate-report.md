---
_fragment: report
_of_phase: generate
_contributes:
  - migration-report.html
---

# Generate — Stakeholder HTML Report (Heroku)

> Stakeholder HTML that uses the same visual shell as the GCP migration
> assessment (page background, section cards, metric grid, verdict callout,
> appendix divider, focus and print styles). The Heroku report follows the
> shared decision core and appendix skeleton: decision, current stack, costs,
> cost optimization, developer workflow, timeline, what-if scenarios, top
> risks, what the assessment rests on, and Appendices A, B, B.1, E, F, G, I
> and J. It adds the copy-ready CFO brief, because the figures it restates
> are already in the estimate. It does not include the GCP AI appendix or the
> security-gap analysis (a PaaS source has no security posture to compare).
> Cutover procedure stays in `MIGRATION_GUIDE.md`. Runs **after** docs so the
> guide exists when the report links to it.
>
> **This file is the single source of truth for `decision-summary` /
> `exec-services` / `exec-costs` / `exec-optimization` / `what-if-scenarios` /
> `exec-risks` / `exec-assumptions` content rules.**
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
| `preferences.json`                                                                                                             | Region, HA, arch (active scenario = working tree); `global.startup_program_status` for the Activate credits callout                                                                                                                               |
| `scenarios/index.json` + manifests **+ each scenario's `scenarios/scenario-NNN.preferences.json` / `.aws-design.json` copies** | What-if table when ≥2 scenarios — manifests carry the cost tiers/complexity; the per-scenario Region/HA/Compute/Arch columns come from the scenario's preferences/design copies |
| `MIGRATION_GUIDE.md`                                                                                                           | Must already exist (docs fragment ran first)                                                                                                                                    |
| `heroku-resource-inventory.json`                                                                                               | `metadata.apps_by_stack_status` / `metadata.eol_stack_apps` for the end-of-life stack line (tolerate absence on older inventories)                                               |

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
- `current_costs.accuracy` and `current_costs.baseline_note` — required
  whenever `current_costs.source != "unavailable"`; `baseline_note` carries a
  derived baseline's approximation caveat (e.g. the full-month assumption on a
  Postgres Advanced per-pool estimate) and MUST be rendered, not just gathered
  — see `exec-costs` below.
- `cost_comparison.comparison_status` / `unmatched_deferred_cost` /
  `unmatched_deferred_services` — when `comparison_status ==
  "incomplete_unmatched_services"`, these MUST be rendered as a caveat beside
  the savings/difference figure, not just gathered — see `exec-costs` below.

From design + preferences: region, primary compute (EB / Fargate / EKS),
service count, `global.dx_priority`, and `design_constraints.compute_target.recommendation.scale_note`
when present. For the `developer-workflow` status rules: the resolved compute target
per app (`compute_target.default` plus matching `overrides[]`, as Design resolved it —
read it from `aws-design.json`'s per-formation `aws_service`, not from
`recommendation.value`) and `design_constraints.eb_deploy_method.value`
(`github_actions` when absent and EB is present).

From the inventory, for the `developer-workflow` section: apps by stack
(`container` vs buildpack stacks), count of `pipeline` resources and of apps that
appear in any `stages[]`, whether any pipeline has `review_apps_enabled: true`, total
`config_var_keys` across `config` resources, count of `release` process types, and the
number of non-data-store add-ons that are mapped vs deferred in `aws-design.json`.
For the Scheduler row specifically: the scheduler-family add-ons (`addon_service`
normalizing to `heroku scheduler`, `scheduler` or `advanced scheduler`) split into those
whose `resource_id` appears as a `source_resource_id` in `aws-design.json` `services[]`
(mapped to EventBridge Scheduler) and those whose `resource_id` appears in `deferred[]`
(no replacement selected). Both counts are inputs to the row's status — on this
branch `advanced-scheduler` has no fast-path row or alias, so Design defers it.

From the inventory: `shared_data_stores.cohorts` (for the conditional
`shared-data-stores` section) and `metadata.apps_by_environment_tier` (one line in
`decision-summary` **only when the field is present**: "N apps, of which M are
production by name or pipeline stage", where `N` is the sum of all tier counts and `M`
is the `prod` count. When the field is absent, omit the line and never derive the counts
here).

From `estimation-infra.json` `current_costs.rightsizing_candidates[]` (present when any
Postgres database holds 25% or less of its plan's storage and a smaller same-family plan
fits twice its data — the Clarify Q6d Right-sizing rule): render a **Right-size before
you move** table inside `exec-costs`, below the Heroku-vs-AWS table — top ten by saving,
columns Database (`heroku_app` plus the add-on `resource_id`, so two databases on one app
stay distinct) / Role (`unknown` when discovery wrote no `pg_role`) / Plan / Plan storage /
Data / Used % / Fitting plan / Saving per month, then one line with the total
`rightsizing_monthly_saving_usd` and the sentences: "This is a Heroku-side saving available
today, before any migration; it is not counted in the AWS figure. Fitting plan is chosen
by storage only; a plan sized for memory, connections or query load may be correct as it
is." When `database_sizing_basis` is `measured`, add: "AWS targets for the databases
confirmed in Clarify Q6d are sized from measured data."

From `estimation-infra.json` `current_costs.contract` (present only when the user
supplied a Heroku order form in Clarify): render a **Contract reconciliation** table
inside `exec-costs`, below the Heroku-vs-AWS table — rows per contract category
(dynos, add-on credits, support, Private Spaces, Connect rows, other) with Contract
$/mo, Discovered $/mo, Gap, and the `gap_explanation`. Follow it with this sentence,
verbatim in substance: "The contract comparison overstates savings: the contract
includes support, credits and committed headroom that discovery cannot see, while
the AWS figure leaves out any add-ons marked Deferred, AWS Support and data
transfer. Use the discovered like-for-like figure for a scope-matched comparison and
treat both as floors on AWS cost." Never present "contract minus AWS" as the
headline saving.

From `estimation-infra.json` `cost_comparison.like_for_like_comparison` (present whenever
any add-on was Deferred): render it as its own row block in `exec-costs`, directly under
the full-baseline comparison — "Scope-matched: Heroku $X/mo (excludes $D/mo of add-ons
with no AWS mapping yet) vs AWS Balanced $Y/mo → $Z/mo {more|less} on AWS ({P}%)". Keep
the full-baseline row and its caveat above it. Wrap the like-for-like Heroku figure in
`data-cost-key="heroku_monthly_like_for_like"` so the validator can cross-check it (the
validator requires that anchor inside `exec-costs` whenever `like_for_like_comparison`
exists, and fails the report when its rendered dollars differ from
`cost_comparison.heroku_monthly_like_for_like`). Two variants of that line:

- `like_for_like_comparison.difference_pct` absent/null (`heroku_monthly_like_for_like`
  is $0; `pct_note` present): render "(percentage not applicable)" in place of "({P}%)".
  Keep the dollar `$Z/mo`.
- `like_for_like_comparison.attribution == "incomplete"`: the label is "Scope-matched
  (provisional — N deferred add-on(s) could not be attributed and remain in the Heroku
  figure: `<names from unattributed_deferred_services>`)" instead of "Scope-matched", and
  the block must not say "decision-grade" or "both sides exclude" — the named add-ons are
  still only on the Heroku side. Only `attribution == "complete"` may be labelled
  decision-grade.

These rules apply in both report modes (`report-decision-core.md` reuses this section).
From `heroku-resource-inventory.json` (when present — older inventories omit
these keys; treat absence as no finding):

- `metadata.apps_by_stack_status` (`eol` / `deprecated` / `supported` /
  `container` / `unknown` counts)
- `metadata.eol_stack_apps` (sorted app names on end-of-life stacks)

From `heroku-resource-inventory.json` and `aws-design.json` metadata (both optional — tolerate absence):

- `heroku-resource-inventory.json` `metadata.apps_by_environment_tier` (Discover assemble
  rule 5a) — the per-tier app counts; when present, `decision-summary` quotes the
  production share (see below) instead of recounting apps.
- `aws-design.json` `metadata.postgres_followers_collapsed[]` (Design 2B-F) — Heroku
  followers served by a read replica / Aurora reader of their leader rather than a
  separate database; when non-empty, `exec-costs` lists them (see below) so the reader
  can see why the AWS database count is lower than the Heroku add-on count.

---

## Step 2: Write `migration-report.html`

Write a **self-contained** HTML file to `$MIGRATION_DIR/migration-report.html`
(inline CSS only). Required section IDs:

| Section ID          | Content                                                                                                                                                                                                                                                                                      |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `decision-summary`  | Typography-first verdict (see below), cost one-liner rendered as a `.metrics` grid whose Balanced card carries `class="metric metric-hero"` (e.g. `<div class="metrics"><div class="metric metric-hero"><strong>AWS estimate (Balanced)</strong><br>Est. $210/mo</div><div class="metric">…Heroku baseline…</div></div>` — the shared validator fails a summary with no `metric-hero`), next action. Placed **before** `<nav class="toc">` in both modes |
| `exec-costs`        | Heroku-vs-AWS side-by-side when a Heroku baseline exists (`current_costs.source != "unavailable"`); otherwise the AWS three-tier table with a one-line note that no Heroku baseline was available. Estimated monthly; Balanced primary. **When `current_costs.baseline_note` is present (any derived — not invoiced — source, including the Postgres Advanced per-pool formula), render it as a visible caveat line directly beside the Heroku current-monthly figure — never only in the accuracy band.** This is mandatory, not conditional on which derived source produced the note. **When `cost_comparison.comparison_status == "incomplete_unmatched_services"`, render the same mandatory caveat-beside-the-figure treatment, naming `cost_comparison.unmatched_deferred_services` and `unmatched_deferred_cost` directly beside the savings/difference figure — never present that dollar delta as decision-grade savings without it.** **When `aws-design.json` `metadata.postgres_followers_collapsed[]` is non-empty, add one line under the database rows listing each collapsed follower and what serves it (`served_by`: `rds_read_replica` → "RDS read replica of `{leader_resource_id}`", `aurora_reader` → "Aurora reader of `{leader_resource_id}`"), so the reader sees why the AWS database count is lower than the Heroku add-on count; skip silently when empty or absent.** This file is the single source of truth for `exec-costs` content rules, so `report-decision-core.md`'s reuse of these rules picks this up automatically. |
| `exec-services`     | Always render, in both modes, after `exec-share` and before `exec-costs`. Heading `Current Stack Overview`. One count line (`services.length` from the design) and one table row per `services[]` entry — see § `exec-services` below |
| `exec-optimization` | Full mode: always render after `exec-costs` — the posture comparison, the not-additive caveat and "Which commitment fits", or the explicit no-eligible-commitment sentence when `optimization_opportunities[]` is empty. Decision mode: render only when `optimization_opportunities[]` is non-empty (the default trigger). See § `exec-optimization` below |
| `developer-workflow` | Always render — in both report modes (`report-decision-core.md` renders it in `decision-report.html` / `DECISION.md` too, with its pre-execution wording override); the shared validator's heroku profile requires it in both modes. Heading "Developer workflow: what stays, what changes, what you build". One line stating the Q5c answer. Then the table defined in § `developer-workflow` below. Then the closing paragraph(s) defined there. Reader vocabulary only — no file names or resource IDs |
| `exec-share`        | Always render, in both modes, immediately after the table of contents. The copy-ready CFO brief defined below. No new arithmetic |
| `exec-timeline`     | Always render, in both modes, after `developer-workflow` and before `what-if-scenarios` (or before `exec-risks` when there is no what-if section). The migration shape, stage order and duration drivers defined below — no week, month or hour figure |
| `exec-risks`        | Always render, in both modes, after `exec-timeline` / `what-if-scenarios`. Heading `Top Risks`. One table, columns Risk · Impact · Likelihood · Mitigation — see § `exec-risks` below. Never empty |
| `exec-assumptions`  | Always render, in both modes, immediately after `exec-risks` — the last executive section (the shared validator fails it placed before `exec-risks`). Heading `What This Assessment Rests On`. Three parts — see § `exec-assumptions` below |
| `shared-data-stores` | **Conditional** — only when the inventory has `shared_data_stores.cohorts` with at least one entry. One table: Cohort / Apps (count) / Shared stores (count) / App names. One sentence above it: apps in a cohort read the same database, cache or Kafka cluster and cannot be cut over strictly one at a time without cross-cloud access to that store; sequence them as a group or plan the interim connectivity. No ordering, no recommendation of which cohort goes first |

**Cost-figure anchors (machine-checkable).** In `exec-costs`, wrap the recommended AWS
monthly (Balanced) dollar figure in a `data-cost-key="aws_monthly_balanced"` attribute so
the shared validator can confirm it matches `estimation-infra.json`
`projected_costs.aws_monthly_balanced` — e.g.
`<span data-cost-key="aws_monthly_balanced">$112/mo</span>`. When the estimate carries
`cost_comparison.heroku_monthly_baseline`, wrap the rendered Heroku baseline figure in
`exec-costs` in `data-cost-key="current_monthly"` the same way — the shared validator
resolves `current_monthly` from that key for this skill. The attributes are not
reader-visible text. The validator asserts the rendered dollars equal the JSON for every
anchor present. **Both anchors are mandatory whenever their JSON value exists and
`exec-costs` is rendered — a missing anchor is a validator FAIL, not a skip.** Only untagged
_illustrative_ numbers are skipped. (The scope-matched `heroku_monthly_like_for_like`
anchor in Step 1 is checked by the heroku add-on validator.)

### `decision-summary` content (REQUIRED)

1. **Verdict (typography-first — the thesis of this section):** When
   `recommendation.outcome` exists, render `outcome_label` as the section's
   **headline** in large display type (e.g.
   `<p class="verdict-headline">Go, with conditions</p>`), then one body-type
   metadata line: `Execution shape: [migration shape] · Complexity: [complexity_tier]`.
   The migration shape comes from `preferences.json` `global.migration_approach`,
   never from `path_label` (which names the pricing scenario, not a shape):
   `full_cutover` (or absent) → `Full cutover: one migration window`;
   `interim_cutover_data_first` → `Data-first: interim cutover`. The `Migration
   shape` metric card, the "Timeline if you execute" line and the `exec-share`
   paragraph use the same derived shape.
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
   1a. **Recommendation callout (required, both modes):** one sentence stating
   the recommendation (the path, the migration shape and the governing
   condition) in `<div class="verdict">…</div>` directly below the metadata
   line — the green callout for `go` / `conditional_go` / migrate-path legacy
   outcomes, the neutral variant for `stay` or `defer_for_evidence`. The shared
   validator requires the exact `verdict` class token inside `decision-summary`
   (`verdict-headline` does not satisfy it). `DECISION.md` carries the same
   sentence as a `Recommendation:` paragraph under its `Execution shape` line.
2. **Confidence pointer (always):** one line under the verdict —
   `Confidence: [confidence] — full basis in
   <a href="#exec-assumptions">What This Assessment Rests On</a>.` Use
   `recommendation.confidence` when present; otherwise `medium` when any
   `preferences.json` `sources.<QID>` is `default`, else `high` (the same rule
   `exec-assumptions` part 2 applies).
3. **Cost one-liner** — Balanced AWS monthly vs Heroku baseline when available
   (estimated monthly), else AWS Balanced alone.
   - **Estate line (when `metadata.apps_by_environment_tier` exists):** one line
     directly under the cost one-liner — `N apps, of which M are production by name or
     pipeline stage`, where `N` is the sum of all tier counts and `M` is the `prod`
     count. This is the only rule for this line; the estate-workbook change reads the
     same field and quotes the same sentence. Skip silently when the tier map is absent
     (Terraform-only discovery).
4. **Migrate if / Stay entirely if:** from `recommendation.migrate_if` and
   `recommendation.stay_if`, rendered as `<h3>Migrate if</h3><ul class="compact">`
   and `<h3>Stay entirely if</h3><ul class="compact">`, one `<li>` per entry,
   placed before "What would flip this". The second heading is exactly
   **"Stay entirely if"** — the shared validator fails a bare "Stay if" heading
   and requires exactly one "Stay entirely if" heading when `stay_if` is
   non-empty. Omit a list whose array is absent or empty.
   4a. **What would flip this (v2):** from `recommendation.would_flip_if[]` when
   present — short unordered list rendering every entry. Skip silently when absent.
   - **End-of-life stacks (conditional):** when
     `metadata.apps_by_stack_status.eol > 0`, add one line stating that N apps
     run on Heroku stacks that have reached end-of-life and no longer receive
     operating-system security patches on Heroku, then list
     `metadata.eol_stack_apps` (all names when ≤ 10; otherwise the first 10
     followed by "and N more"). Skip silently when the key is absent or zero.
5. **One-sentence next action** — the single most useful next step for the
   reader (Generate artifacts, confirm a condition, or gather named evidence).
6. **Developer workflow pointer (when `global.dx_priority == "critical"`):** one
   line — `Developer workflow was rated critical; see
   <a href="#developer-workflow">Developer workflow</a> for what stays, what changes
   and what must be built.`
7. **Next steps (full mode only):** `<h3>Next steps</h3><ol class="compact">`
   after "What would flip this" — the shared validator fails this heading over a
   `<ul>`. Items, in this order: (1) "Set the three contact emails
   (`operations_email`, `billing_email`, `security_email`) in `terraform.tfvars`
   before `terraform plan` — checklist in MIGRATION_GUIDE.md — nothing can be
   applied until then."; (2) follow the MIGRATION_GUIDE.md phases in order
   (point at the guide, never paste the procedure); (3) the Terraform ships with
   `baseline.tf` (account security baseline — GuardDuty, CloudTrail, budget
   alerts); (4) unless `startup_program_status` is `has_credits`: apply for
   [AWS Activate credits](https://aws.amazon.com/startups/credits/) before
   `terraform apply` — credits do not apply retroactively. Decision mode renders
   no Next steps list; `decision-cta` is its terminal section and the
   one-sentence next action (item 5) stays.
8. **AWS Activate credits callout (always, both modes):** the 💡
   `<div class="callout callout-info">` defined in
   `references/shared/report-decision-core.md` § Startup credits callout, placed after
   the cost one-liner. Wording follows `preferences.json`
   `global.startup_program_status`: `eligible_founders` → Founders (up to $5,000);
   `eligible_portfolio` → Portfolio (up to $200,000, Org ID from your investor);
   `has_credits` → credits already on the account, no "apply for"; `unknown`/absent
   → neutral both-tiers wording with no confirmed tier. Always include the
   clickable apply link `https://aws.amazon.com/startups/credits/` inside the
   callout (the validator fails a summary that names Activate without it). Never a
   metric card; never infer the tier from spend. Unless `has_credits`, say credits
   are not retroactive — apply before `terraform apply`.

### `exec-services` (always render, both modes)

Render `<section id="exec-services">` after `exec-share` and before
`exec-costs`. Heading: `Current Stack Overview` (plain title — never "Section N").

- One count line: "{N} Heroku resources on {A} app(s) were mapped to AWS
  targets", where `N` is `aws-design.json` `services.length` and `A` the number
  of distinct `heroku_app` values. Then "No add-on is deferred." or "{D}
  add-on(s) have no AWS mapping selected yet" from `deferred[]`.
- One table (caption, `scope="col"` headers), columns **Heroku app / Heroku
  primitive / AWS target**, one row per `services[]` entry: `heroku_app`; the
  primitive named from `source_resource_id` with its type in parentheses (a
  `:web` / `:worker` formation → "web formation (compute)"; a Postgres add-on →
  "Heroku Postgres add-on (database)"; Redis → "(cache)"; Kafka → "(streaming)");
  `aws_service` plus the size the reader controls from `aws_config` (instance
  type or class, Multi-AZ, instance range, storage).
- One line per `deferred[]` entry under the table: "{resource}: no AWS mapping
  selected" — never fold a deferred add-on into the mapped rows.
- Reader vocabulary only: no artifact filenames or Terraform resource IDs.

### `exec-assumptions` (always render, both modes — last executive section)

Render `<section id="exec-assumptions">` **immediately after** `exec-risks`
(the shared validator fails `exec-assumptions` placed before `exec-risks`) and
before `decision-cta` (decision mode) or the appendix divider (full mode). The
`decision-summary` confidence pointer links here. Heading: `What This
Assessment Rests On` (plain title — never "Section N"). Three parts, all read
from the artifacts — invent nothing:

1. **Assumptions applied by default.** A table (caption, scoped headers),
   columns **Setting / Assumed value / Design consequence**, one row per
   question whose `preferences.json` `sources.<QID>` is `"default"` (the
   `defaults_applied[]` IDs). Setting is the plain name and Design consequence
   the catalog text from the ⟨preferences_groups⟩ row table under § Appendices
   (keyed by field). Flag the three Generate-time questions (Q4, Q6c, Q12d) with
   "asked for real at Generate" while they are listed in
   `metadata.questions_deferred_to_generate`. `compute_target.chosen_by ==
   "system_recommended"` is derived, not defaulted — it does not get a row.
   When no `sources` entry is `default`, render one line instead: "All inputs
   were confirmed by you or extracted from your Heroku inventory — nothing was
   assumed."
2. **Confidence.** When `recommendation.decision_basis` exists, render its
   three arrays as compact **Measured** / **Assumed** / **Unknown** columns,
   copied as written. Otherwise one line: `Confidence: [confidence] — [gloss]`,
   where confidence is `recommendation.confidence` when present, else `medium`
   when any `sources` entry is `default`, else `high`; gloss: high — "inputs
   measured or confirmed"; medium — "some material inputs assumed" (name them);
   low — "key inputs missing or stale". Say which inputs were confirmed by you
   and which were extracted from your Heroku inventory.
3. **Pricing provenance.** One line from `pricing_source.status` (+
   `pricing_source.message` when it names a cache or region) and
   `accuracy_confidence`, matching the Estimate chat summary — e.g. "Estimates
   based on cached AWS pricing (us-east-1 cache), accuracy ±5–10%."

The anti-stub rule applies: render the settings and consequences themselves,
never "see the preferences file".

### `exec-share` (always render, both modes)

Render `<section id="exec-share">` immediately after `<nav class="toc">`.
Heading: `Share with your CFO`. Lead-in sentence, outside the card: "The
one-paragraph version, ready to forward:". Then exactly one
`<div class="share-card"><p>…</p></div>`. The card holds one paragraph of at
least 20 words. No button, script, input, or second paragraph. No new
arithmetic — restate figures already shown in the decision summary.

The paragraph must still make sense pasted into an email. Use only:

- the verdict and confidence
- the estimated AWS Balanced monthly figure
- the Heroku baseline when a comparable baseline exists; otherwise say the Heroku bill is not established
- the migration shape (derived from `preferences.json` `global.migration_approach`
  per `decision-summary` item 1 — never `path_label`)
- at most three conditions or evidence gaps

Label every amount as estimated. Preserve the same comparability caveats as
`exec-costs`. In decision mode, omit Generate-only facts.

### `exec-timeline` (always render, both modes)

Render `<section id="exec-timeline">` after `developer-workflow`. Heading:
`Timeline`.

- Shape: `preferences.json` `global.migration_approach` (Clarify Q6b), rendered
  as in `decision-summary` item 1 — `full_cutover` (or absent) → `Full cutover:
  one migration window`; `interim_cutover_data_first` → `Data-first: interim
  cutover`. Never `recommendation.path_label`: that names the pricing scenario
  ("Migrate with Optimized pricing scenario"), not a shape. This is the
  ⟨duration_driver_source⟩ / ⟨stage_sequence_source⟩ the heroku layer of
  `report-decision-core.md` points at.
- Stage order, as a short ordered list derived from the same field:
  `full_cutover` → provision the AWS environment, migrate the database inside
  the migration window, cut over every app in that same window;
  `interim_cutover_data_first` → provision, migrate the database first (interim
  cutover, with the bounded Heroku-to-RDS access), then containerize and cut
  over compute by `global.target_exit_date`.
- Duration drivers, named only from the artifacts: `complexity_tier` as a word
  (small / medium / large), `complexity_inputs.service_count` and
  `deferred_count`, database HA and the migration method from preferences, and
  the maintenance window (one line with the day and hour) when preferences name
  one. Skip any driver that is absent.
- **No week, month or hour figure anywhere in the report.** Durations are
  uncalibrated; the shared validator's readability gate fails a bare "N–M weeks"
  and an "N–M hours" range. Say this is not a staffed schedule and not a
  commitment.
- One line pointing at `MIGRATION_GUIDE.md` for the procedure. Do not paste
  cutover or rollback steps into this section.
- Do not invent a duration driver the artifacts do not name.

### `developer-workflow` (always render)

The customer's developers will judge the migration by their daily workflow, not by
the architecture diagram. Say plainly what maps, what is generated, what they must
build, and what has no equivalent. One table, one row per Heroku primitive, columns
**Heroku today / On AWS / Status / Your estate**. Status is exactly one of four words:
**Covered** (an AWS feature or a generated artifact does this; the command differs),
**Generated** (this migration emits it per app), **Build** (not generated; the platform
team writes it once and reuses it), **No equivalent**. A status describes what this
migration **actually emits for the selected target**, never what the stack or the
`recommendation.value` implies — when the estate mixes targets, give one status per
target group ("**Generated** for the {n} Beanstalk apps; **Build** for the {m} Fargate
apps") rather than the most favourable one. Likewise a status that depends on what
Design mapped is **computed from `aws-design.json`'s `services[]` and `deferred[]`
entries, never asserted** — a row never says "Covered — mapped" while any of its
source add-ons sits in `deferred[]`.

**Status rules for the target- and design-dependent rows** (resolved target per app
from `aws-design.json`, deploy method from `eb_deploy_method.value`, `github_actions`
when absent; mapped/deferred counts from `aws-design.json` as gathered in Step 1):

| Row                | Resolved target / design state                     | Status                                                                                                                                                                                                                 |
| ------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Push to deploy     | EB + `github_actions`, or EB + `codepipeline` for an app that does not resolve to CNB | **Generated** — the generated workflow (or CodePipeline) builds and deploys per app |
| Push to deploy     | EB + `codepipeline`, app resolves to CNB (`app_containerization_method == "cnb_heroku_builder"`) | **Build** — CodePipeline is unsupported for CNB apps (it cannot run `pack build`), so no pipeline is generated for them; use the `github_actions` workflow, or write the pipeline yourself |
| Push to deploy     | EB + `manual`                                      | **Build** — no CI is generated; the guide documents a CLI deploy                                                                                                                                                       |
| Push to deploy     | Fargate or EKS (any method)                        | **Build** — no push-to-deploy workflow is generated for container services; the team writes the image build + deploy pipeline                                                                                           |
| Push to deploy     | any target, buildpack app with `app_containerization_method == "dockerfile"` | add "**Build** — a Dockerfile per buildpack app" as a separate clause for those apps only; a CNB app (the default) needs no Dockerfile, because `pack build` with the Heroku builder produces the image, so never add the clause for it |
| Config vars        | EB                                                 | **Covered** — one `environmentsecrets` binding per sensitive key is generated; you import the values                                                                                                                   |
| Config vars        | Fargate                                            | **Build** — the generated task definition carries no environment/secrets bindings; you export the values, import them to Secrets Manager / Parameter Store, and wire each key into the task definition yourselves (the migration guide's Fargate config-var section is the procedure; in the rendered row say "the migration guide", not the file name) |
| Config vars        | EKS                                                | **Build** — the generated Kubernetes Deployments carry `PORT` plus `DATABASE_URL` and `REDIS_URL` `secretKeyRef` bindings only (reading a per-app Kubernetes Secret that is not generated); you create that Secret from the exported values and add an env entry per remaining key to each Deployment (the migration guide's EKS section shows the `kubectl create secret` and `secretKeyRef` steps). There is no task definition for EKS apps and the Fargate config-var procedure does not apply to them — never point EKS apps at it |
| One-off commands   | EB / Fargate (ECS)                                 | **Covered** — ECS Exec or `eb ssh`; one-off tasks as a run-task call |
| One-off commands   | EKS                                                | **Covered** — `kubectl exec` into a running pod, or `kubectl run` / a Kubernetes Job for a one-off task; there are no ECS services or Beanstalk environments for EKS apps, so never give them ECS Exec, `eb ssh` or run-task |
| Log tailing        | EB / Fargate (ECS)                                 | **Covered** — CloudWatch Logs live tail |
| Log tailing        | EKS                                                | **Covered** — `kubectl logs -f` against the pods. CloudWatch live tail is **Build**: `generate-eks.md` configures no application-log forwarding (no Fluent Bit and no CloudWatch Observability add-on), so you install one and then tail the log group |
| Scheduler add-ons  | every scheduler-family add-on in `services[]`      | **Covered** — mapped to EventBridge Scheduler; disclose that no Terraform is emitted for the schedules themselves (Generate records them in its unsupported-resource warnings), so each job is recreated as a schedule by you                                                                                   |
| Scheduler add-ons  | one or more scheduler-family add-ons in `deferred[]` | **Build** for those — "{S_deferred} scheduler add-on(s) deferred — replacement selection pending"; when others are mapped, render both statuses with their counts ("**Covered** for {S_mapped}; **Build** for {S_deferred}")                                                                              |

| Heroku today                              | On AWS                                                                                      | Status                                                                            | Your estate (from the inventory)                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `git push heroku main` + buildpacks       | CI builds a container image and deploys it                                                  | Per the status rules above: **Generated** only for Beanstalk apps with a generated deploy method; **Build** for Fargate/EKS apps and manual Beanstalk; plus **Build** (a Dockerfile per app) only for buildpack apps whose `app_containerization_method` is `dockerfile`; **Build** for EB apps on CodePipeline that resolve to CNB | "{N} buildpack apps, {M} already containerized; {n} on Beanstalk, {m} on Fargate/EKS" |
| Pipelines and promote                     | Environments per stage with the same image promoted between them, approval-gated            | Per target: **Generated** for EB apps with a generated `github_actions` deploy (an approval-gated `promote.yml`, which promotes the staging version in a promote pair or redeploys a chosen version); **Build** for Fargate/EKS apps, manual or CodePipeline EB apps, and the pipelines themselves (stages, environments) | "{P} pipelines covering {A} apps" |
| Review apps                               | An ephemeral environment per pull request, torn down on merge                               | **Build** (or buy — see below)                                                    | "enabled on {R} pipelines" or "not enabled"                          |
| Config vars                               | Parameter Store / Secrets Manager, injected at deploy; `config:set` becomes one CLI call      | Per the status rules above: **Covered** for Beanstalk apps (bindings generated, values by you); **Build** for Fargate apps (values imported and task-definition bindings written by you); **Build** for EKS apps (database/cache bindings generated, Kubernetes Secret and the remaining keys' env entries written by you) | "{K} config var keys across {N} apps"                                |
| `heroku run` / one-off dynos              | Per target: ECS Exec or `eb ssh`, run-task for one-off tasks (Beanstalk/Fargate); `kubectl exec`, `kubectl run` or a Kubernetes Job (EKS) | Per the status rules above: **Covered** — different command for the target | —                                                                    |
| `heroku logs --tail`                      | Per target: CloudWatch Logs live tail (Beanstalk/Fargate); `kubectl logs -f` (EKS)           | Per the status rules above: **Covered** for Beanstalk/Fargate apps; **Covered** for EKS apps via `kubectl logs -f`, with CloudWatch tailing **Build** (log forwarding such as Fluent Bit or the CloudWatch Observability add-on is additional setup) | —                                                                    |
| Release phase                             | A pre-deploy job in the workflow that runs before traffic shifts                             | **Build**                                                                         | "{L} release process types"                                          |
| Scheduler add-ons                         | EventBridge Scheduler                                                                       | Per the status rules above, computed from `aws-design.json`: **Covered** for the mapped add-ons (schedules recreated by you); **Build** for any in `deferred[]` ("{S_deferred} scheduler add-on(s) deferred — replacement selection pending") | "{S_mapped} scheduler add-ons mapped, {S_deferred} deferred"         |
| `ps:scale`                                | Autoscaling policy or one CLI call                                                          | **Covered**                                                                       | —                                                                    |
| Add-on marketplace                        | Each add-on becomes an AWS service or a retained SaaS, wired by Terraform                   | **No equivalent** to the marketplace itself                                       | "{X} add-ons mapped, {Y} deferred for manual selection"              |

Fill the last column from the inventory and design counts gathered in Step 1; write
"—" where there is nothing to count. Do not invent rows. Do not soften "Build" into
"Covered" because a how-to exists in `MIGRATION_GUIDE.md`.

**Closing paragraph (always):** "The rows marked Build are a platform layer your team
owns: a deploy pipeline for Fargate, EKS and manual-deploy apps, a promote step for every
app that gets no generated `promote.yml`, release steps, review-app automation, and a thin command wrapper. It is weeks of platform work, not months, and it is the same for
every app." When `compute_target.recommendation.scale_note` exists and
`compute_target.default` is `"ecs-fargate"`, add: "Compute was recommended as shared
ECS clusters rather than one Beanstalk environment per process type ({scale_note}) so
that day-to-day operation stays at least as simple as Heroku." When the note exists but
`default` is `"elastic_beanstalk"` (the user took the EB override), add instead:
"Shared ECS clusters were recommended ({scale_note}); you chose one Beanstalk
environment per process type, so the Build rows above repeat per environment."

**Build-vs-buy paragraph (when `dx_priority` is `critical`, or more than 40
formations):** "Two shapes for that layer: build it yourselves on the generated
scaffolding (lowest cost, you own it, needs platform-engineering time), or run a
platform product on your AWS account that provides Heroku-style push-to-deploy,
pipelines and review apps from day one (products in this space include Flightcontrol,
Porter and Coherence; another vendor, another contract, faster start). The AWS cost
below is the same either way; the difference is people and time." Name the products
plainly, make no recommendation between them, and never present a product's price.

### `exec-optimization` (full mode: always render; decision mode: when opportunities exist)

Render `<section id="exec-optimization">` immediately after `exec-costs`
(before `developer-workflow`; `what-if-scenarios`, when present, follows
`exec-timeline`). Heading: `Cost Optimization` (plain title — never "Section
N"). Source: `estimation-infra.json` → `optimization_opportunities[]`, per the
eligibility rules and three-state model in
`references/vendored/estimate/ri-sp-eligibility.md`. In full mode the section
is a heroku add-on: always rendered, never omitted. In decision mode it follows
the default trigger — render it only when `optimization_opportunities[]` is
non-empty, and add it to the TOC when rendered.

- **When `optimization_opportunities` is non-empty**, render in order:
  1. A **posture comparison table** (caption, scoped headers), columns
     Posture / Est. monthly / vs Balanced / What you commit to, rows: Balanced
     on-demand (`aws_monthly_balanced`, "—", "nothing — pay as you go"); one row
     per commitment opportunity ("Balanced with {opportunity}",
     `aws_monthly_balanced − savings_monthly`, "−${savings_monthly}/mo",
     `commitment`); Optimized (`aws_monthly_optimized`, the difference to
     Balanced, "every eligible commitment at its mid-point rate"). Every figure
     is an estimated monthly whole dollar.
  2. One sentence, mandatory whenever the word "Optimized" appears in the
     section: "Savings Plan savings are incremental to the Balanced on-demand
     figure and are **not additive** to the Optimized tier — Optimized already
     includes them at the mid-point rate." (The shared validator fails an
     `exec-optimization` that mentions Optimized without a not-additive /
     already-includes phrase, and one that never mentions Balanced.)
  3. **Which commitment fits** — a short list, one item per opportunity:
     `opportunity` → `target_services` → `commitment`, `implementation_effort`,
     and `prerequisite` when present (a Compute Savings Plan is recommended in
     percent only until a 30–90 day AWS usage baseline exists — `ri-sp-eligibility.md`
     caveat 1). Database Savings Plans and RDS Reserved Instances are mutually
     exclusive on the same database workload. A Database Savings Plan is
     recommended only when the design's RDS instance class is Generation 7 or
     newer, per the `generation_gate` in
     `references/vendored/estimate/commitment-discount-ranges.json`; for a
     pre-Generation-7 class (for example db.t4g) the item and its posture row
     state that the class is ineligible, attach no dollar saving, and name a
     qualifying class (db.m7g or db.r7g).
  4. Full mode: one line linking down to the line-level table — "Line-level
     opportunities:" followed by `<a href="#appendix-optimization">Appendix B.1 —
     Savings Plans and Reserved Instances</a>`. Decision mode: there is no appendix, so
     render the opportunity table itself here (columns Optimization / Target /
     Monthly savings / Commitment / Effort, one row per opportunity) under the
     list, and never emit `appendix-optimization`.
- **When `optimization_opportunities` is empty (full mode):** do not omit the
  section or leave it blank. Render one sentence, as visible text: "No
  1-year/3-year commitment product applies to this architecture." When Bedrock
  is part of the design, add: "Bedrock inference has a separate mechanism
  (Provisioned Throughput, 1- or 6-month commitment), evaluated separately from
  Reserved Instances/Savings Plans."

**Appendix B.1 — `appendix-optimization` (full mode, always render).** Render
`<section id="appendix-optimization">` immediately after `appendix-costs`,
heading `Appendix B.1 — Savings Plans and Reserved Instances`. When
`optimization_opportunities[]` is non-empty: one table (caption, scoped
headers), columns **Optimization / Target / Monthly savings / Commitment /
Effort**, one row per opportunity — `opportunity` / `target_services` joined
with ", " / `savings_monthly` as an estimated monthly whole dollar (fall back
to `savings_percent` when `savings_monthly` is absent) / `commitment` /
`implementation_effort`. The Optimization cell carries the product name as
written ("Compute Savings Plans", "Database Savings Plans", "Reserved
Instances") — the shared validator looks for a Savings Plan / Reserved Instance
data row in this table, not in a heading or caveat. A Database Savings Plans row
carries a dollar saving only for a Generation 7+ RDS instance class (the
`generation_gate` in `references/vendored/estimate/commitment-discount-ranges.json`);
for a pre-Generation-7 class the estimate records `savings_monthly: null` and
the Monthly savings cell says the class is ineligible and names a qualifying
class (db.m7g or db.r7g) instead of a figure. Below the table, once:
"Activate credits don't cover RI/Savings Plan upfront costs — they apply only
to the ongoing discounted hourly rate." When the array is empty, render the
same no-eligible-commitment sentence as `exec-optimization` instead of a table.
Both sections carry the sentence in that case; neither is ever blank.

### `exec-risks` (always render, both modes)

Render `<section id="exec-risks">` after `exec-timeline` (after
`what-if-scenarios` when present) and immediately before `exec-assumptions`.
Heading: `Top Risks` (plain title — never "Section N"). One table (caption,
scoped headers) — the shared validator fails a bullet list — with columns
**Risk / Impact / Likelihood / Mitigation**. Impact and Likelihood are separate
one-word cells (Critical / High / Medium; High / Medium / Low), optionally
wrapped in `.badge-impact-*` / `.badge-like-*` spans; never a combined phrase
such as "high impact (low probability)". Up to five rows, highest severity
first. Sources, in this order — invent nothing beyond them:

1. `recommendation.conditions[]` and `would_flip_if[]` — one row each (the
   condition or flip as the risk; the mitigation is what confirms it).
2. `aws-design.json` `deferred[]` — one row per deferred add-on ("no AWS
   mapping selected; its cost and cutover step are not in this estimate").
3. `preferences.json` entries whose `sources.<QID>` is `"default"` on a cost-
   or HA-bearing question: Q3 availability, Q6 database HA, Q12c compute
   target, Q4 maintenance window, Q6c migration method — one row each, naming
   the assumed value and what confirming it changes.
4. Full mode only: `generation-warnings.json` `warnings[]` — one row per
   warning that names an unsupported or skipped resource.

Never leave the section empty: a run with no conditions, no deferred add-ons,
no cost-bearing defaults and no warnings still renders one row for the pricing
band (`accuracy_confidence`) — "the estimate may move within ±N%; mitigation:
re-run Estimate against live pricing before committing". Reader vocabulary
only: no artifact filenames or Terraform resource IDs in this section.

### Conditional — `what-if-scenarios`

When `scenarios/index.json` exists and `scenarios[]` has **≥ 2** entries,
render `<section id="what-if-scenarios">` **after** `exec-timeline` and
**before** `exec-risks`:

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
  `decision-summary` / `exec-share` / `exec-services` / `exec-costs` /
  `exec-optimization` / `exec-timeline` / `what-if-scenarios` / `exec-risks`
  (name things the reader controls).

### Visual shell

Both `migration-report.html` and `decision-report.html` include the stylesheet
below. Copy it as written.

The validators do not require every declaration in that block. The shared
validator (`$PLUGIN_ROOT/scripts/validate-migration-report.py --profile heroku`)
fails when a `<style>` block is missing any of these, and the heroku add-on
checks the `.share-card` rule; nothing else in the block is gated:

- `body` `background` is `#f6f8fa` or a `var(...)`. Another hex value, or `rgb()`, fails. The error says "body must use a contrasting page background".
- `.report` or `.container` sets `max-width`
- `section` sets `background`, `border`, and `border-radius`
- `.metrics` is `display: grid` with `grid-template-columns`
- `.metric` sets `border` and `border-radius`
- `.verdict` sets `background` and `border`
- `.savings` sets `color`
- `.share-card` sets `border`
- `.appendix-header` is defined
- a `:focus-visible` rule
- `@media (max-width: 700px)`
- `@media print`

`h1`, `.verdict-headline`, `.metric-hero`, `.increase`, the `table` / `th, td` /
`thead th` rules, `tr.active-scenario`, `.compact`, the `.badge-impact-*` /
`.badge-like-*` risk badges, `.glossary-table` and `.assumption-default` are
part of the stylesheet to copy.
The checker does not fail a report that omits them. Other colors and spacing
inside the checked rules may be refined. The page background may not.

```css
body { margin: 0; background: #f6f8fa; color: #1f2328; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 15px; line-height: 1.55; }
.report { max-width: 1040px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }
h1 { font-size: 1.85rem; margin-bottom: 0.25rem; border-bottom: 3px solid #ff9900; padding-bottom: 0.5rem; }
.verdict-headline { font-size: 2rem; line-height: 1.15; margin: 0 0 0.35rem; }
section { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 1.25rem 1.5rem; margin-bottom: 1rem; scroll-margin-top: 1rem; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin: 0.85rem 0; }
.metric { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 0.85rem 1rem; }
.metric-hero { border: 2px solid #0d7377; }
.verdict { background: #e6f4ea; border: 1px solid #137333; border-left: 4px solid #137333; padding: 0.75rem 1rem; }
.savings { color: #137333; font-weight: 650; }
.increase { color: #c5221f; font-weight: 650; }
.share-card { background: #f0f6fc; border: 1px solid #d0d7de; border-left: 4px solid #0969da; padding: 0.85rem 1rem; }
.callout { padding: 0.85rem 1rem; border-radius: 6px; margin: 0.85rem 0; font-size: 0.95rem; }
.callout-info { background: #eef5ff; border: 1px solid #0969da; border-left: 4px solid #0969da; }
.appendix-header { background: #232f3e; color: #fff; padding: 1rem 1.5rem; margin: 2rem 0 1rem; }
.compact { margin: 0.25rem 0 0.75rem; padding-left: 1.25rem; }
.badge-impact-critical, .badge-impact-high { color: #c5221f; font-weight: 650; }
.badge-like-low, .badge-like-medium { color: #57606a; font-weight: 650; }
.glossary-table td:first-child { font-weight: 650; white-space: nowrap; }
.assumption-default td:first-child { font-weight: 650; }
a:focus-visible { outline: 2px solid #0969da; outline-offset: 2px; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0 1rem; font-size: 0.88rem; }
th, td { border: 0; border-bottom: 1px solid #d0d7de; padding: 0.45rem 0.65rem; text-align: left; vertical-align: top; }
thead th { border-bottom: 2px solid #d0d7de; }
tr.active-scenario { font-weight: 650; }
@media (max-width: 700px) { .report { padding: 1rem; } .metrics { grid-template-columns: 1fr; } }
@media print { body { background: #fff; } .appendix { break-before: page; } }
```

Put the verdict headline in large display type. Do not render it as a colored
pill. A go outcome may sit in `.verdict`. A conditional or stay outcome uses a
pale warning callout so the color is not the only signal. The Balanced monthly
figure is a `.metric-hero` inside `.metrics`, next to the Heroku baseline when
one exists and the complexity tier. Mark a supported savings delta with
`.savings` and a supported increase with `.increase`, and keep the `+` or `-`
in the text.

### Appendices (full report only)

After `exec-assumptions`, render `<div class="appendix">` preceded by
`<div class="appendix-header">Appendix</div>`. Decision mode omits this block
(`report-decision-core.md`). Copy figures and choices from the artifacts. Do
not invent rows.

**Load `references/vendored/report/report-appendix-skeleton.md` and build the
appendix block from it.** That file is the single source of truth for the
shared appendix build (lettering, divider, the purpose, trigger, data sources,
table shapes and content rules of Appendices A, B, B.1, E, F, G, I and J as
this skill renders them). Do not restate or paraphrase its rules here. If the
file is missing, emit
`GATE_FAIL | phase=generate | fragment=artifacts-report | reason=renderer_missing`
and stop. The Heroku report omits three appendices a PaaS source cannot fill —
the profile `SKILL_PROFILES["heroku"]` in the shared validator, passed as
`--profile heroku` — and every omission is declared below. Headings and TOC
labels carry the skeleton's letters: `Appendix A — Service Recommendations`,
`Appendix B — Cost Estimates`, `Appendix B.1 — Savings Plans and Reserved
Instances`, `Appendix E — Generated Artifacts Catalog`, `Appendix F — Your
Configuration`, `Appendix G — Security Capabilities`, `Appendix I —
Assumptions, Exclusions, and Validation`, `Appendix J — Glossary`. C, D and H
are absent and their letters stay reserved.

Do not emit `appendix-ai`, `appendix-security-gap`, `appendix-steps`, or
`exec-tco`. The cutover procedure stays in `MIGRATION_GUIDE.md`.

#### Parameters

| Parameter                                                                        | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ⟨source_cloud⟩                                                                   | Heroku                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ⟨report_mode⟩                                                                    | `full` (decision mode renders no appendix block; heroku has no AI-only path)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ⟨precheck_owner⟩ / ⟨precheck_skill_flag⟩                                         | n/a — no artifact pre-check runs before the report; `generate.md`'s `_assert`s gate the phase / n/a                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ⟨appendices_rendered⟩                                                            | Required under `SKILL_PROFILES["heroku"]`: A (`appendix-services`), B (`appendix-costs`), B.1 (`appendix-optimization`, always rendered — the no-eligible-commitment sentence when there are no opportunities), E (`appendix-artifacts`), F (`appendix-config`), G (`appendix-security`), I (`appendix-assumptions`), J (`appendix-glossary`). Declared omissions (Declared exceptions below): C, D, H. Lettered headings and TOC labels as the skeleton writes them.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ⟨appendix_header_text⟩                                                           | "Appendix"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ⟨footer_text⟩                                                                    | "Generated by Heroku to AWS Migration Advisor — draft for review; verify figures before executive sign-off." (Skeleton HTML below)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ⟨extra_anchors⟩                                                                  | `heroku_monthly_like_for_like` (scope-matched block, checked by the heroku add-on validator)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ⟨accounting_ledger_field⟩ / ⟨accounting_split_sentence⟩ / ⟨accounting_location⟩  | n/a — heroku-to-aws writes no generation ledger; the service count comes from `aws-design.json` `services[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ⟨validator_invocation⟩                                                           | The two-command block in Step 3 (shared validator with `--profile heroku`, `--estimation-infra`, `--migration-dir`; then `validate-heroku-migration-report.py`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨design_mapping_source⟩                                                          | `aws-design.json` `services[]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ⟨how_we_chose_vocabulary_ref⟩                                                    | n/a — the design rows carry no confidence vocabulary; targets are explained in `exec-services`, `developer-workflow` and `appendix-services`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨service_row_extras⟩                                                             | One row per `services[]` entry: Heroku app, source, AWS service, and the size the reader controls (instance class, task size, count)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ⟨cost_breakdown_source⟩                                                          | `estimation-infra.json` `projected_costs.breakdown` line items when the breakdown has them. Otherwise the Heroku baseline and the three AWS tiers, as estimated monthly whole dollars, plus the pricing-source caveat.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ⟨mandatory_breakdown_rows⟩ / ⟨baseline_breakdown⟩ / ⟨floor_fields⟩ / ⟨extra_cost_columns⟩ | none beyond the canonical / n/a (`cost_comparison.heroku_monthly_baseline` is a single figure with `baseline_note`) / n/a (no floor fields in the Heroku estimate) / none                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ⟨optimization_sources⟩ / ⟨ri_sp_eligibility_ref⟩                                 | Infra only (`estimation-infra.json` → `optimization_opportunities[]`; item shape per `estimate-cost-engine.md` Part 6: `opportunity`, `type`, `target_services[]`, `savings_percent`, `savings_monthly`, `commitment`, `implementation_effort`, `prerequisite`) / `references/vendored/estimate/ri-sp-eligibility.md`. Rendered as `exec-optimization` (posture + which commitment fits) and Appendix B.1 `appendix-optimization` (line-level table) — both always present in full mode                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ⟨phase_order_source⟩ / ⟨scripts_list⟩ / ⟨cutover_strategy_fields⟩ / ⟨rollback_source⟩ / ⟨rollback_rows⟩ | n/a — `appendix-steps` is a declared omission (cutover procedure stays in `MIGRATION_GUIDE.md`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ⟨ai_appendix_spec⟩                                                               | Declared omission — heroku-to-aws has no AI track                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ⟨pack_extras⟩ / ⟨data_artifacts⟩                                                 | Appendix E lists what exists at render time, one line each: `terraform/` (core files `main.tf`, `variables.tf`, `outputs.tf`, `security.tf`, `.gitignore`, `terraform.tfvars.example` plus `baseline.tf`; conditional `pipeline.tf`, `eks.tf`, `ecr.tf`, `dns.tf` when present), `MIGRATION_GUIDE.md`, `README.md`, every `scripts/*.sh` present (`migrate-postgres.sh`, `migrate-redis.sh`), every `.github/workflows/*.yml` present (`deploy-eb.yml`, `promote.yml`), `kubernetes/` when present, and `generation-warnings.json`; then one line "Written after this report by the completion step: `validation-report.json`, `heroku-estate.xlsx`, `plan.json` (when their writers succeed)"; then "This report supersedes `decision-report.html`" when that file exists in the migration directory / Data artifacts table (Artifact · Contents): `preferences.json` (your Clarify answers and their provenance), `heroku-resource-inventory.json` (the discovered Heroku estate), `aws-design.json` (the AWS mapping per resource), `estimation-infra.json` (the three cost tiers and the recommendation)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ⟨preferences_groups⟩                                                             | Columns **Question / Your choice / Source / Design consequence** (the shared validator requires a question-or-assumption, choice, source and consequence header and at least two rows). One row per field below that is present in `preferences.json`, sorted user → extracted → default → derived; a default row is flagged (`class="assumption-default"`). Source from `sources.<QID>`: `user` → "User answer"; `extracted` → "Extracted from your Heroku inventory"; `default` → "Default applied"; `design_constraints.compute_target.chosen_by == "system_recommended"` → "Derived (recommended from the inventory)". Heroku constraints carry no per-field `prompt` / `design_consequence`, so the skeleton's legacy fallback applies: take the Question and Design consequence from this row catalog (keyed by field), never leave a cell empty. Row catalog (field · Q-ID · Question · Design consequence): `global.target_region` · Q1 · Which AWS region should your infrastructure be deployed to? · Every resource is created in this region; pricing is this region's. `global.compliance` · Q2 · Do you need to meet any compliance frameworks? · HIPAA → BAA-eligible services only; PCI → encryption at rest and in transit; SOC 2 → audit logging; none → no extra controls beyond the baseline. `global.availability` · Q3 · What availability level does your production workload need? · single-az / multi-az → RDS PostgreSQL; multi-az-ha / multi-region → Aurora; applies to every data service. `global.maintenance_window` · Q4 · When should AWS perform maintenance operations? · Sets the RDS and Beanstalk maintenance window; flexible leaves AWS defaults. `global.environment_naming` · Q5 · What should the primary environment be called in AWS resource naming and tags? · Becomes the Terraform `environment` variable (the environment segment of resource names and the `Environment` tag) and the guide's environment name; never changes the architecture or the estimate. `global.dx_priority` · Q5c · How important is keeping the Heroku developer workflow? · Changes what the report says must still be built; critical adds the build-vs-buy choice; never changes the Terraform. `data.database_ha` · Q6 · What high-availability configuration do you want for PostgreSQL on AWS? · single-az / multi-az → RDS (Multi-AZ when multi-az); multi-az-ha → Aurora. `global.migration_approach` · Q6b · How do you want to phase the migration? · data-first adds the interim database exposure section and a platform-risk callout to the guide. `data.migration_method` · Q6c · How would you like to migrate your PostgreSQL data to AWS? · Selects the data migration procedure in the guide; DMS adds the CDC limitation warning. `data.redis_ha` · Q7 (when present) · Do you want Redis replicated across AZs? · Replication group with a standby versus a single node. `data.dns_strategy` · Q10 · How do you want to manage DNS for your migrated services? · route53 generates `dns.tf` with weighted cutover records; external leaves DNS with your provider. `operational.containerization_status` · Q12b · Is your application already containerized? · buildpack_only / partial add the Containerization Prerequisites section and fire Q12f. `operational.containerization_method` · Q12f · How should buildpack apps get a container image? · cnb_heroku_builder → `pack build` with the Heroku builder, ECR repositories, no Dockerfile; dockerfile → `docker build` per app. `operational.container_registry` · Q12 · Where should container images be stored for your containerized workloads? · ecr → images are published to one ECR repository per Cloud Native Buildpacks app (`ecr.tf`), which that build path requires (the only option when Q12f is cnb_heroku_builder); external → no `ecr.tf` and no ECR login step, images are pulled from your registry. `design_constraints.compute_target` · Q12c · Which compute target should formations use? · Resolves each formation to Elastic Beanstalk, Fargate or EKS; one extra row per `overrides[]` entry naming the formation. `design_constraints.eb_deploy_method` · Q12d (when present) · How do you want to deploy code changes to Elastic Beanstalk? · github_actions generates the deploy and promote workflows; codepipeline generates `pipeline.tf`; manual generates no CI. `operational.log_retention_days` · Q13 · How long should application logs be retained? · CloudWatch Logs retention (mapped to the nearest Beanstalk-accepted value). `operational.alerting` · Q14 · How do you want to handle alerting and on-call notifications? · Recorded for your operations runbook; the generated Terraform emits no application alarms or on-call wiring for this answer (the account baseline's budget notifications are separate; see Appendix G), so the choice never moves the estimate. `operational.cost_optimization` · Q15 · How aggressively should we optimize for cost vs. operational safety? · Right-sizing margin applied to the Balanced tier. `global.startup_program_status` · Q17 · Have you applied for AWS Activate credits? · Drives only the credits callout wording; never moves the estimate.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ⟨preferences_schema_ref⟩ / ⟨critical_default_caveats⟩                            | `references/phases/clarify/clarify-interview.md` § Question Catalog (question text and Design impact per Q-ID; the row catalog above is its report-facing summary) / one `<div class="callout callout-info">` above the table for each of these when its `sources.<QID>` is `default`: Q2 compliance ("Compliance was not confirmed — no framework-specific controls were added; confirm before go-live"), Q3 availability ("Availability was defaulted to Multi-AZ — roughly a 2x database cost swing either way; confirm before cutover sizing"), Q17 startup-program status ("Funding stage not confirmed — the Activate guidance is neutral; answer Q17 to see the tier that applies"). None when none of the three is defaulted                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ⟨baseline_controls_table⟩ / ⟨security_extra_columns⟩                             | The account baseline Generate emits, as a table with columns Control, Setting, What it does, and Threat mitigated. Rows: alternate contacts (an incident reaches someone who can act); password policy, 14 characters, reuse 24, maximum age 90 days (weak console passwords); S3 public-access block (accidental public buckets); default EBS encryption (data exposure from a stolen volume); Access Analyzer (a policy or bucket becomes public); IMDSv2 (credential theft through server-side request forgery); CloudTrail at the generated retention (who changed what); the monthly budget and its alert thresholds (bill shock); GuardDuty (credential theft and resource hijacking). Say that the three contact emails must be set before `terraform plan`. Do not add a monthly-cost column or a Heroku-equivalent column (declared exception — column vocabulary). |
| ⟨security_equivalent_label⟩ / ⟨budget_limit_formula⟩ / ⟨cost_guardrail_rows⟩     | n/a — no Heroku-equivalent column (declared exception) / n/a — the budget row names its alert thresholds, not a formula / n/a — no AI track, no `bedrock_monitoring.tf`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ⟨compliance_field⟩                                                               | The normalized compliance list: when it contains soc2, pci, hipaa, or fedramp, add AWS Config (a record of configuration change) and Security Hub with FSBP (baseline posture checks), each with the same two meaning columns. Do not add those rows when compliance is none.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ⟨opt_out_procedure⟩                                                              | Removing `baseline.tf` plus those three contact variables opts out                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ⟨gap_source_names⟩ / ⟨gap_extra_rows⟩ / ⟨observability_note_field⟩               | n/a — `appendix-security-gap` is a declared omission (no source-cloud security posture to gap-compare on a PaaS)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ⟨pricing_source_fields⟩ / ⟨rightsizing_limitations⟩                              | `recommendation.decision_basis` measured, assumed, and unknown lists when present, copied as written, plus one pricing-provenance line from `pricing_source.status` (prose-only declared exception — the `decision_basis` lists in place of the pricing-confidence table; when the estimate has no `decision_basis`, the pricing-provenance line plus the `accuracy_confidence` band) / n/a — covered by the `decision_basis` lists                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ⟨exclusion_extras⟩ / ⟨terraform_validation_rule⟩ / ⟨warnings_sources⟩           | none / n/a — this fragment runs before `validation-report.json` exists and states no Terraform status / `generation-warnings.json` `warnings[]` and `aws-design.json` `warnings[]`, listed one line each under Appendix I ("none" when both are empty); the same warnings feed `exec-risks` source (4)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ⟨glossary_examples⟩                                                              | Estimated monthly run rate (what the AWS resources are expected to cost per month at list price, before credits; say it is "not the full ownership cost: staffing, tooling and operating labor are not priced" — the literal phrases "total cost of ownership" and "TCO" are banned anywhere in the report body by the shared validator's READABILITY rule), Balanced / Premium / Optimized (the three pricing tiers: right-sized on-demand; the same design with every resilience uplift; Balanced with every eligible commitment at its mid-point rate), Savings Plan, Multi-AZ, Elastic Beanstalk, Cloud Native Buildpacks, GuardDuty. At least three rows; `<table class="glossary-table">` with Term / Meaning headers, a caption and `scope="col"`; the final section of the report                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

#### Declared exceptions

Every entry mirrors `SKILL_PROFILES["heroku"]` in
`$PLUGIN_ROOT/scripts/validate-migration-report.py` (reason text copied from the
validator), plus the prose-only declarations the validator does not encode:

- `appendix-steps` (C) — not required: cutover procedure stays in MIGRATION_GUIDE.md.
- `appendix-ai` (D) — not required: heroku-to-aws has no AI track.
- `appendix-security-gap` (H) — not required: no source-cloud security posture to gap-compare on a PaaS.
- The profile's `skip` map is empty: the glossary, "Stay entirely if", optimization-section and `appendix-config` column checks all run under `--profile heroku`.
- `appendix-security` columns — Control · Setting · What it does · Threat mitigated, no cost or Heroku-equivalent column (the heroku add-on validator checks "What it does" / "Threat mitigated"; prose-only).
- `appendix-assumptions` — `decision_basis` lists instead of the pricing-confidence table (prose-only).
- `appendix-artifacts` (E) lists the pack at render time; `validation-report.json`, `heroku-estate.xlsx` and `plan.json` are named as written after this report (prose-only timing note).

### Table & figure accessibility (REQUIRED — the shared validator enforces these)

- **Exactly one `<h1>`** — the skeleton's report title. Section headings are `<h2>`.
- **Every `<table>` has a `<caption>`** stating what the table shows.
- **Every `<th>` must declare `scope="col"` or `scope="row"`.** The report's tables
  (`exec-services`, `exec-costs`, `exec-optimization`, `developer-workflow`,
  `what-if-scenarios`, `exec-risks`, `exec-assumptions`, every appendix table) are
  column-headed, so emit `<th scope="col">…</th>` for each header cell.
- **If you emit a `<figure>`, it must carry a non-empty `aria-label` and a `<figcaption>`.**
  This report normally has no figures; this only applies if you add one.
- `<html>` carries `lang="en"` (the skeleton already does).

### Skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Heroku to AWS Migration Assessment</title>
  <style>/* visual shell from the section above */</style>
</head>
<body>
  <div class="report">
    <h1>Heroku to AWS Migration Assessment</h1>
    <section id="decision-summary">…</section>
    <nav class="toc">…</nav>
    <section id="exec-share">…</section>
    <section id="exec-services">…</section>
    <section id="exec-costs">
      <!-- every <th> declares scope; copy this header pattern for every other table too -->
      <table>
        <caption>Estimated monthly AWS cost by tier</caption>
        <thead><tr><th scope="col">Tier</th><th scope="col">Est. Monthly AWS</th></tr></thead>
        <tbody>…
          <tr><td>Balanced</td><td><span data-cost-key="aws_monthly_balanced">$NNN/mo</span></td></tr>
        </tbody>
      </table>
    </section>
    <section id="exec-optimization">…</section>
    <section id="developer-workflow">…</section>
    <section id="exec-timeline">…</section>
    <!-- <section id="what-if-scenarios"> when ≥2 scenarios -->
    <section id="exec-risks">…</section>
    <section id="exec-assumptions">…</section>
    <div class="appendix-header">Appendix</div>
    <div class="appendix">
      <section id="appendix-services"><h2>Appendix A — Service Recommendations</h2>…</section>
      <section id="appendix-costs"><h2>Appendix B — Cost Estimates</h2>…</section>
      <section id="appendix-optimization"><h2>Appendix B.1 — Savings Plans and Reserved Instances</h2>…</section>
      <section id="appendix-artifacts"><h2>Appendix E — Generated Artifacts Catalog</h2>…</section>
      <section id="appendix-config"><h2>Appendix F — Your Configuration</h2>…</section>
      <section id="appendix-security"><h2>Appendix G — Security Capabilities</h2>…</section>
      <section id="appendix-assumptions"><h2>Appendix I — Assumptions, Exclusions, and Validation</h2>…</section>
      <section id="appendix-glossary"><h2>Appendix J — Glossary</h2>…</section>
    </div>
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
2. Contains `decision-summary` (before the TOC, with the "Migrate if" / "Stay entirely if" lists and the `<h3>Next steps</h3><ol class="compact">`), `exec-share`, `exec-services`, `exec-costs`, `exec-optimization`, `developer-workflow`, `exec-timeline`, `exec-risks`, `exec-assumptions` (in that order, `exec-assumptions` last), the eight appendix sections A, B, B.1, E, F, G, I, J with their lettered headings, a TOC link to each of them, the visual-shell selectors (including `.share-card`), one `<h1>`, and `draft for review`. The security appendix table has What it does and Threat mitigated columns; the configuration appendix has Question / Your choice / Source / Design consequence columns and at least two rows; the glossary is a `glossary-table` with at least three rows. No week, month or hour figure appears anywhere.
3. `decision-summary` must **not contain** any `badge-verdict-*` class; when
   `recommendation.outcome` exists it must render a `verdict-headline` element.
4. `exec-assumptions` renders the defaults table (or the nothing-assumed line), the confidence line (or the `decision_basis` columns when the estimate declares them) and the pricing-provenance line; the confidence pointer in `decision-summary` links to `#exec-assumptions`. `exec-risks` has at least one table row.
5. If `scenarios/index.json` has ≥2 scenarios, contains `what-if-scenarios`.
6. `exec-optimization` and `appendix-optimization` are non-empty — the posture table
   plus the not-additive sentence and the B.1 opportunity table, or the explicit
   no-eligible-commitment sentence in both, never a blank section. If you wrote the
   sentence, it renders as visible text (not only inside a comment/`<template>`) and
   reads verbatim once entities decode.
7. Every `<th>` declares `scope="col"`/`"row"`; every `<table>` has a `<caption>`; any `<figure>` has `aria-label` + `<figcaption>`.
8. **No monthly-scale dollar figure renders with cents.** Scan every `$` figure: any
   monthly total $2 or more must be whole-dollar (`$112/mo`, not` $112.34/mo`) — the
   validator's currency gate is blocking. Round any cents you find on a monthly figure
   before returning. (Cents are fine only on sub-$2 amounts or explicit per-unit rates.)
9. When `projected_costs.aws_monthly_balanced` is present, `exec-costs` wraps that
   figure in `<span data-cost-key="aws_monthly_balanced">$NNN/mo</span>` (the
   validator FAILs on a missing anchor — it is how the rendered figure is confirmed
   against the estimate). The attribute is not reader-visible text. When
   `cost_comparison.heroku_monthly_baseline` is present, the rendered Heroku baseline in
   `exec-costs` is wrapped in `<span data-cost-key="current_monthly">$NNN/mo</span>` the
   same way.
10. If `cost_comparison.comparison_status == 'incomplete_unmatched_services'`,
    confirm the unmatched-service caveat is visible text next to the
    Heroku-vs-AWS figure, not only inside `baseline_note`.
11. `decision-summary` contains the 💡 Activate credits callout (`.callout-info`) with a
    clickable `https://aws.amazon.com/startups/credits/` link, worded for
    `global.startup_program_status` — tier and dollar amount only for `eligible_founders`
    / `eligible_portfolio`, no "apply for" wording for `has_credits`, neutral for `unknown`.

A report failure must not delete the Terraform/docs — repair the HTML in this fragment. Fixing
the report is **only** done here, before control returns; the completion gate never edits it.

**Blocking validation runs in the MAIN window, not here.** This fragment runs in a dispatched
`_exec._agent: rw` worker with no shell (`INTERPRETER.md` § capability tiers), so it cannot run
the validator. The interpreter runs it in `generate.md`'s **"Finish Generate in the main window
(report validation)"** step — which executes **after** this worker returns and **before** the
read-only `_postconditions` gate (per `INTERPRETER.md` § `_exec` step 4, gates are never
dispatched):

```bash
python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --profile heroku \
  --estimation-infra "$MIGRATION_DIR/estimation-infra.json" \
  --migration-dir "$MIGRATION_DIR"
python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" \
  --migration-dir "$MIGRATION_DIR"
```

Both commands must print `REPORT_OK` and exit 0. Either `REPORT_FAIL` blocks; a validator that
does not run (non-0/1 exit, missing `python3`, missing
`$PLUGIN_ROOT/scripts/validate-migration-report.py`) is not a pass. There is no skip path.

`REPORT_OK` from both means the structure and decision-core checks passed. It is not a substitute
for the content rules in this file or for the appendix skeleton
(`references/vendored/report/report-appendix-skeleton.md` § Validate the rendered report): when
`recommendation.would_flip_if` is non-empty the summary must include a "What would flip this"
list whose items render every entry (the heading over an empty or partial list fails; content
inside `<template>` or comments does not count; the label may be a heading over the list or
lead its first item, `<li>What would flip this: …</li>`), and when two or more scenarios exist
the what-if table must include Scenario, Region, HA, Compute, Arch, Complexity and the three
tier columns. A report written only to satisfy the section-ID list will fail.

`REPORT_OK` → the report gate passes. `REPORT_FAIL` → the main-window step emits `GATE_FAIL` **and
pastes the validator's `errors[]` verbatim**; the gate does not edit the HTML itself. The pasted
errors are what make recovery actionable — a bare "re-run Generate" is not a fix, since re-dispatch
re-authors the report under this shell-less worker. On `REPORT_OK` the finish step stamps
`report-validation-status.json` (the durable result the read-only gate asserts). Recovery is a
hand-edit of the report from those errors + a direct validator re-run and re-stamp (or a maintainer
re-running Generate for a clean rebuild).
**What each validator enforces.** The shared validator
(`$PLUGIN_ROOT/scripts/validate-migration-report.py --profile heroku`) enforces the
required section IDs for this skill in each mode (full: `decision-summary`, `exec-share`,
`exec-services`, `exec-costs`, `exec-optimization`, `developer-workflow`, `exec-timeline`,
`exec-risks`, `exec-assumptions` and the eight appendices A, B, B.1, E, F, G, I, J; decision:
`decision-summary`, `exec-share`, `exec-services`, `exec-costs`, `developer-workflow`,
`exec-timeline`, `exec-risks`, `exec-assumptions`, `decision-cta`), the TOC
(present, no broken links, every required section linked), `decision-summary` before the TOC,
no rendered `appendix-*` in decision mode, the visual-shell stylesheet rules listed above,
accessibility (`<html lang>`, exactly one `<h1>`, `<th scope>`, a `<caption>` on every table,
`<figure>` labels), whole-dollar monthly currency, the readability rules (no bare week or hour
ranges, no "TCO", no "Section N" headings, no vague intensifiers, ISO dates), reader vocabulary
in the exec sections (no `*.json` or `aws_*.` tokens), the typography-first verdict rules (no
`badge-verdict-*` pills; `verdict-headline` when `recommendation.outcome` exists), the
`metric-hero` card, the populated "What would flip this" list, exactly one "Stay entirely if"
heading when `stay_if` is non-empty, the "Next steps" heading over an ordered list, the
`exec-risks` table placed before `exec-assumptions`, the `exec-optimization` Balanced /
not-additive wording and the Savings Plan row in the B.1 table when opportunities exist, the
`appendix-config` Question / Your choice / Source / Design consequence columns, the
`glossary-table` with at least three rows, the exec-share brief (one `.share-card` paragraph of
at least 20 words, no controls), the Activate apply link, the what-if column set when two or
more scenarios exist, appendix content-depth floors, the `draft for review` footer, and the
`aws_monthly_balanced` / `current_monthly` cost anchors. The heroku add-on
(`<SKILL_BASE>/scripts/validate-heroku-migration-report.py`) enforces the heroku-only rules:
no `decision-cta` in full mode, no `.appendix-header` in decision mode, no retired section ID
in either mode (`next-steps`, `cost-optimization`, `decision-basis` each fail with a message
naming the replacement: the `decision-summary` Next steps list / `decision-cta`,
`exec-optimization` plus `appendix-optimization`, `exec-assumptions`), the `.share-card`
border rule, the `heroku_monthly_like_for_like` anchor and its source-consistency check, the
Activate status rules driven by `preferences.json`, in full mode a populated table row or the
exact no-eligible-commitment sentence in each of `exec-optimization` and
`appendix-optimization` (when present), the security-appendix "What it does" / "Threat
mitigated" columns, `exec-assumptions` ("What This Assessment Rests On") when the estimate
declares `recommendation.decision_basis`, and the decision-mode `.phase-status.json`
pre-execution check.

---

## Scope Boundary

**This fragment writes `migration-report.html` ONLY.**

FORBIDDEN:

- Re-running Design / Estimate / workshop
- Duplicating the full `MIGRATION_GUIDE.md` procedure into HTML
- Inventing cost figures not present in `estimation-infra.json` / scenario
  manifests
