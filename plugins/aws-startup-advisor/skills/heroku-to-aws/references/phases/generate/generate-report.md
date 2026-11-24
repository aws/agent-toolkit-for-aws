---
_fragment: report
_of_phase: generate
_contributes:
  - migration-report.html
---

# Generate — Stakeholder HTML Report (Heroku)

> Stakeholder HTML that uses the same visual shell as the GCP migration
> assessment (page background, section cards, metric grid, verdict callout,
> appendix divider, focus and print styles). The Heroku report stays shorter:
> decision, costs, developer workflow, what-if scenarios, and five appendices
> the Heroku artifacts can fill. It adds the copy-ready CFO brief and the
> complexity-tier planning band, because both are already in the estimate.
> It does not include the GCP AI appendix, security-gap analysis, or glossary.
> Cutover procedure stays in `MIGRATION_GUIDE.md`. Runs **after** docs so the
> guide exists when the report links to it.
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
| `decision-summary`  | Typography-first verdict (see below), cost one-liner, next action                                                                                                                                                                                                                            |
| `exec-costs`        | Heroku-vs-AWS side-by-side when a Heroku baseline exists (`current_costs.source != "unavailable"`); otherwise the AWS three-tier table with a one-line note that no Heroku baseline was available. Estimated monthly; Balanced primary. **When `current_costs.baseline_note` is present (any derived — not invoiced — source, including the Postgres Advanced per-pool formula), render it as a visible caveat line directly beside the Heroku current-monthly figure — never only in the accuracy band.** This is mandatory, not conditional on which derived source produced the note. **When `cost_comparison.comparison_status == "incomplete_unmatched_services"`, render the same mandatory caveat-beside-the-figure treatment, naming `cost_comparison.unmatched_deferred_services` and `unmatched_deferred_cost` directly beside the savings/difference figure — never present that dollar delta as decision-grade savings without it.** **When `aws-design.json` `metadata.postgres_followers_collapsed[]` is non-empty, add one line under the database rows listing each collapsed follower and what serves it (`served_by`: `rds_read_replica` → "RDS read replica of `{leader_resource_id}`", `aurora_reader` → "Aurora reader of `{leader_resource_id}`"), so the reader sees why the AWS database count is lower than the Heroku add-on count; skip silently when empty or absent.** This file is the single source of truth for `exec-costs` content rules, so `report-decision-core.md`'s reuse of these rules picks this up automatically. |
| `cost-optimization` | Reserved Instance / Savings Plan opportunities table, or the explicit no-eligible-commitment statement — see below. Always present, never omitted                                                                                                                                            |
| `developer-workflow` | Always render — in both report modes (`report-decision-core.md` renders it in `decision-report.html` / `DECISION.md` too, with its pre-execution wording override). Heading "Developer workflow: what stays, what changes, what you build". One line stating the Q5c answer. Then the table defined in § `developer-workflow` below. Then the closing paragraph(s) defined there. Reader vocabulary only — no file names or resource IDs |
| `exec-share`        | Always render, in both modes, immediately after the table of contents. The copy-ready CFO brief defined below. No new arithmetic |
| `exec-timeline`     | Always render, in both modes, after `developer-workflow` and before `what-if-scenarios` (or before `next-steps` / `decision-cta` when there is no what-if section). The planning band defined below |
| `shared-data-stores` | **Conditional** — only when the inventory has `shared_data_stores.cohorts` with at least one entry. One table: Cohort / Apps (count) / Shared stores (count) / App names. One sentence above it: apps in a cohort read the same database, cache or Kafka cluster and cannot be cut over strictly one at a time without cross-cloud access to that store; sequence them as a group or plan the interim connectivity. No ordering, no recommendation of which cohort goes first |
| `next-steps`        | Ordered list pointing to `MIGRATION_GUIDE.md` phases (not a procedure dump). Include one bullet noting the Terraform ships with `baseline.tf` (account security baseline — GuardDuty, CloudTrail, budget alerts) and that three contact emails must be set in tfvars before `terraform plan`. Unless `startup_program_status` is `has_credits`, include one item: apply for [AWS Activate credits](https://aws.amazon.com/startups/credits/) before `terraform apply` — credits do not apply retroactively |

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
   - **Estate line (when `metadata.apps_by_environment_tier` exists):** one line
     directly under the cost one-liner — `N apps, of which M are production by name or
     pipeline stage`, where `N` is the sum of all tier counts and `M` is the `prod`
     count. This is the only rule for this line; the estate-workbook change reads the
     same field and quotes the same sentence. Skip silently when the tier map is absent
     (Terraform-only discovery).
4. **What would flip this (v2):** from `recommendation.would_flip_if[]` when
   present — short unordered list. Skip silently when absent.
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
7. **AWS Activate credits callout (always, both modes):** the 💡
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
- the migration shape (`path_label`)
- at most three conditions or evidence gaps

Label every amount as estimated. Preserve the same comparability caveats as
`exec-costs`. In decision mode, omit Generate-only facts.

### `exec-timeline` (always render, both modes)

Render `<section id="exec-timeline">` after `developer-workflow`. Heading:
`Timeline`.

- Shape: `recommendation.path_label`.
- Planning band from `complexity_tier`, copied from the Estimate timeline
  table. Do not invent a different range:
  - `small`: 2–6 weeks
  - `medium`: 6–12 weeks
  - `large`: 12–18 weeks
- The words "planning band" are visible beside that range. The band is the
  complexity-tier planning range, not a staffed schedule and not a commitment.
- When preferences name a maintenance window, one line with the day and hour.
  Skip when absent.
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
  `decision-summary` / `exec-share` / `exec-timeline` / `exec-costs` /
  `what-if-scenarios` (name things the reader controls).

### Visual shell

Both `migration-report.html` and `decision-report.html` include the stylesheet
below. Copy it as written.

`validate-heroku-migration-report.py` does not require every declaration in
that block. It fails when a `<style>` block is missing any of these, and only
these:

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
`thead th` rules, and `tr.active-scenario` are part of the stylesheet to copy.
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

After `next-steps`, render `<div class="appendix">` preceded by
`<div class="appendix-header">Appendix</div>`. Decision mode omits this block
(`report-decision-core.md`). Each appendix is a `<section>` with a plain
heading. Copy figures and choices from the artifacts. Do not invent rows.

| Section ID | Content |
| --- | --- |
| `appendix-services` | One row per `aws-design.json` `services[]` entry: Heroku app, source, AWS service, and the size the reader controls (instance class, task size, count). |
| `appendix-costs` | Estimate line items when the breakdown has them. Otherwise the Heroku baseline and the three AWS tiers, as estimated monthly whole dollars, plus the pricing-source caveat. |
| `appendix-config` | Choices from `preferences.json`: region, availability, maintenance window, compute default and any formation override, Elastic Beanstalk deploy method, database HA, migration method, DNS. Columns: Choice, Your answer, What it changes. |
| `appendix-security` | The account baseline Generate emits, as a table with columns Control, Setting, What it does, and Threat mitigated. Rows: alternate contacts (an incident reaches someone who can act); password policy, 14 characters, reuse 24, maximum age 90 days (weak console passwords); S3 public-access block (accidental public buckets); default EBS encryption (data exposure from a stolen volume); Access Analyzer (a policy or bucket becomes public); IMDSv2 (credential theft through server-side request forgery); CloudTrail at the generated retention (who changed what); the monthly budget and its alert thresholds (bill shock); GuardDuty (credential theft and resource hijacking). Say that the three contact emails must be set before `terraform plan`, and that removing `baseline.tf` plus those three variables opts out. When the normalized compliance list contains soc2, pci, hipaa, or fedramp, add AWS Config (a record of configuration change) and Security Hub with FSBP (baseline posture checks), each with the same two meaning columns. Do not add those rows when compliance is none. Do not add a monthly-cost column or a Heroku-equivalent column. |
| `appendix-assumptions` | `recommendation.decision_basis` measured, assumed, and unknown lists when present, copied as written, plus one pricing-provenance line. |

Do not emit `appendix-ai`, `appendix-security-gap`, `appendix-steps`,
`appendix-glossary`, or `exec-tco`. The cutover procedure stays in
`MIGRATION_GUIDE.md`.

### Table & figure accessibility (REQUIRED — the blocking validator enforces these)

- **Every `<th>` must declare `scope="col"` or `scope="row"`.** The report's tables
  (`exec-costs`, `cost-optimization` when opportunities exist, `what-if-scenarios`) are
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
    <section id="developer-workflow">…</section>
    <section id="exec-timeline">…</section>
    <!-- <section id="what-if-scenarios"> when ≥2 scenarios -->
    <section id="next-steps">…</section>
    <div class="appendix-header">Appendix</div>
    <div class="appendix">
      <section id="appendix-services">…</section>
      <section id="appendix-costs">…</section>
      <section id="appendix-config">…</section>
      <section id="appendix-security">…</section>
      <section id="appendix-assumptions">…</section>
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
2. Contains `decision-summary`, `exec-share`, `exec-timeline`, `exec-costs`, `cost-optimization`, `next-steps`, the five appendix sections, the visual-shell selectors (including `.share-card`), and `draft for review`. The security appendix table has What it does and Threat mitigated columns.
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

```
python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" \
  "$MIGRATION_DIR/migration-report.html" --mode full --migration-dir "$MIGRATION_DIR"
```

`REPORT_OK` means the validator's decision-core checks passed. It is not a substitute for the content
rules in this file: when `recommendation.would_flip_if` is non-empty the
summary must include a "What would flip this" list whose items render every
entry (the heading over an empty or partial list fails; content inside
`<template>` or comments does not count; the label may be a heading over the
list or lead its first item, `<li>What would flip this: …</li>`), and when two or more scenarios
exist the what-if table must include Region, HA, Compute, Arch, and Complexity.
A report written only to satisfy the section-ID list will fail.

`REPORT_OK` → the report gate passes. `REPORT_FAIL` → the main-window step emits `GATE_FAIL` **and
pastes the validator's `errors[]` verbatim**; the gate does not edit the HTML itself. The pasted
errors are what make recovery actionable — a bare "re-run Generate" is not a fix, since re-dispatch
re-authors the report under this shell-less worker. On `REPORT_OK` the finish step stamps
`report-validation-status.json` (the durable result the read-only gate asserts). Recovery is a
hand-edit of the report from those errors + a direct validator re-run and re-stamp (or a maintainer
re-running Generate for a clean rebuild).
The validator enforces the required sections, the `draft for review` footer, the typography-first
verdict rules, the populated "What would flip this" list when `would_flip_if` is present, the what-if
column set when two or more scenarios exist, non-empty `cost-optimization`, and the
a11y subset the report emits (`<th scope>`, `<figure>` labels).

---

## Scope Boundary

**This fragment writes `migration-report.html` ONLY.**

FORBIDDEN:

- Re-running Design / Estimate / workshop
- Duplicating the full `MIGRATION_GUIDE.md` procedure into HTML
- Inventing cost figures not present in `estimation-infra.json` / scenario
  manifests
