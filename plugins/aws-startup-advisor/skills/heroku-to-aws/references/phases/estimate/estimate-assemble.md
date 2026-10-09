---
_assemble: assemble-estimation
_of_phase: estimate
_reads:
  - cost-engine (fragment contribution)
_produces:
  - estimation-infra.json
---

# Estimate — Assemble and Validate estimation-infra.json

> **Assembler unit.** Runs after the cost-engine fragment (`estimate-cost-engine.md`)
> has computed the full financial picture. It assembles the final
> `estimation-infra.json`, enforces the completion handoff gate (including the
> Property-16 total invariant + every-service-priced check), updates
> `.phase-status.json`, and presents the summary. It owns the artifact-level
> contract for this phase.

---

## Output: Write `estimation-infra.json`

Assemble the full artifact conforming to `references/vendored/estimate/estimation-infra.schema.json`
(that schema is the field contract — do not re-enumerate it here). Each section is the
corresponding output the cost-engine fragment computed: `pricing_source` +
`current_costs` (Part 1), `projected_costs` (Parts 2/2B), `cost_comparison` (Part 3),
`migration_cost_considerations` (Part 4), `roi_analysis` (Part 5),
`optimization_opportunities` (Part 6), `complexity_tier` + `complexity_inputs`
(Part 7), and `recommendation` (Part 8).

The assembler additionally DERIVES the `financial_summary` roll-up (not produced by
any single cost-engine Part; the schema leaves its shape open):

```json
{
  "financial_summary": {
    "current_heroku_monthly": "<N or null>",
    "projected_aws_balanced_monthly": "<N>",
    "projected_aws_optimized_monthly": "<N>",
    "monthly_savings_balanced": "<heroku - balanced, negative = AWS more expensive>",
    "monthly_savings_optimized": "<heroku - optimized>",
    "annual_savings_optimized": "<× 12>",
    "recommendation": "<summary sentence>"
  }
}
```

Sign convention: savings = Heroku minus AWS (positive = you save by migrating).
This is deliberately the OPPOSITE sign of
`roi_analysis.recurring_savings.monthly_difference_*` (difference = AWS minus
Heroku) — same fact, savings-vs-difference framing. When presenting either,
always label the direction in words; never print a bare signed value.

Also attach optional workshop metadata when present (does not affect Property-16):

```json
{
  "workshop": {
    "scenario_id": "<preferences.workshop.active_scenario_id or null>",
    "region_note": "<from cost-engine, or null>"
  }
}
```

Write to `$MIGRATION_DIR/estimation-infra.json`.

---

## Completion Handoff Gate (Fail Closed)

The completion checks are declared in this phase's `_postconditions` frontmatter
and enforced per `INTERPRETER.md` § Gate protocol: **re-read `estimation-infra.json`
from disk**, run the mechanical checks (`_check_file_exists` / `_validate_json`) and
the `_assert` judgment checks (recommendation shape, the Property-16 total-invariant,
every-service-priced, complexity tier), then emit `GATE_FAIL` (do NOT patch artifacts;
STOP) or `HANDOFF_OK | phase=estimate | artifacts=estimation-infra.json`.

One check needs this fragment's context: `estimation-infra.json` must also pass
`references/vendored/estimate/estimation-infra.schema.json` validation (the schema shape) — verify that as part
of the `_validate_json` postcondition.

### Inner workshop reprice — skip this gate's state transition

When invoked from `workshop-refresh.md` (inner reprice): write
`estimation-infra.json`, optionally soft-check Property-16, present a brief
summary, then **return to the workshop loop**. Do **not** emit `HANDOFF_OK`, do
**not** update `.phase-status.json`, do **not** offer the what-if workshop below.

---

## Present Summary

After writing `estimation-infra.json`, present a concise summary to the user:

1. **Pricing source and accuracy** — State cache age and accuracy range
2. **Heroku baseline vs AWS projected** (balanced tier) — one-line comparison (if a baseline was determined, labeled with its source; include the derived-baseline caveat when the source is not billing data)
3. **Three-tier table**: Premium, Balanced, Optimized with monthly totals
   - Premium: _Highest resilience / highest monthly estimate_
   - Balanced: _Default scenario; compare Heroku to this first_
   - Optimized: _Lower estimate; reservations / Spot trade-offs assumed_
   - One-line note: Three figures are pricing scenarios for the same architecture (not three Terraform stacks). Generated Terraform aligns with Balanced.
4. **Per-service cost breakdown** (balanced tier, 1 line per service)
5. **Migration complexity**: tier + timeline range
6. **Monthly and annual savings** (or increase) vs Heroku per tier (if a baseline was determined)
7. **Cost optimization:** if `optimization_opportunities` is non-empty, list the top 2-3 with savings potential. If it is empty (per the vendored eligibility matrix, nothing in this design is RI/SP-eligible), say so in one line instead of skipping the line entirely: "No 1-year/3-year commitment product applies to this architecture." Either way, when any commitment product is mentioned, add: "Note: Activate credits don't cover RI/Savings Plan upfront costs."
8. **Recommendation**: lead with `outcome_label` (or `path_label` when `outcome` is absent). List `conditions[]` when `conditional_go`. Close with 1–3 `would_flip_if[]` bullets when present. Keep `path_label` as the execution-shape line under the verdict.

Keep under 25 lines. The user can ask for details or re-read `estimation-infra.json`.

---

## Phase status after outer Estimate (deferred Generate advance)

After outer-run `HANDOFF_OK` (not an inner workshop reprice):

1. Mark `phases.estimate` → `"completed"`.
2. Ensure `phases.workshop` exists (seed `"pending"` if the key is missing).
3. **Do not** set `current_phase` to `"generate"` yet — leave `current_phase` at
   `"estimate"` until the workshop sidebar is resolved (entered then exited, or
   declined) **and** the Decision gate below has been answered. This matches
   sidebar semantics: workshop never owns `current_phase`, and mid-workshop
   fixtures correctly stay on `estimate`.
4. Offer the what-if workshop below. On exit or decline, present the Decision
   gate (below) — do **not** fall through to Generate directly.

---

## Post-Estimate: What-If Workshop Offer

After outer-run `HANDOFF_OK`, the summary above, and the deferred phase-status
update — offer:

```
Phase 4 of 6 complete (Estimate). Remaining: Generate (+ optional Feedback).
Before you decide, want to see how the numbers move if you change something?
I can reprice scenarios side by side in about a minute each, without
re-running discovery — for example: a different AWS region, single-AZ
database for staging, a different compute target, or ARM-based (Graviton)
instances.

[A] Enter what-if workshop
[B] Proceed to the decision
```

**Data-justified scenario hint (add one line when applicable):** if a material assumption was defaulted or tier-derived rather than confirmed — most commonly `database_ha` — append: "Suggestion: we assumed [assumption]; comparing a [alternative] scenario would bound it before you commit." Suggest at most one.

- **A** → Load `references/phases/workshop/workshop.md` (sidebar) and follow it
  (baseline capture if `scenarios/` missing, then the sheet). Keep
  `current_phase: estimate`; set `phases.workshop` → `"in_progress"`. On
  workshop exit, **return to the Decision gate below** (do not advance to
  Generate directly) — the workshop's active scenario carries into it.
- **B** → Mark `phases.workshop` → `"completed"` (resolved/declined — no
  `scenarios/` required). Proceed to the Decision gate below.

On first workshop entry after this Estimate, `workshop-refresh.md` baseline
capture snapshots the current artifacts as `scenario-001` before any edits.

---

## Post-Estimate: Decision Gate

**The decision is the product; execution artifacts are opt-in.** The verdict
(`recommendation.outcome` / `path`) already exists in `estimation-infra.json` —
present it and let the user choose what happens next. Never advance to
Generate without an explicit choice of option C (or an explicit later request
for Terraform/scripts).

Reached only after the what-if workshop offer above has been resolved
(entered-and-exited, or declined) — never presented while `phases.workshop`
is `"pending"` or `"in_progress"`.

Present (values from `estimation-infra.json`; one line each):

```
Phase 4 of 6 complete (Estimate). Remaining: Generate (+ optional Feedback).

### Decision pack ready

- Verdict: [outcome_label when recommendation.outcome exists; else path_label]
- AWS estimate (Balanced): $[X]/mo · Your Heroku baseline: [figure, or "not
  established" when current_costs.source is unavailable]
- Timeline if you execute: ~[N–M] weeks ([complexity_tier], from
  references/vendored/estimate/complexity-tiers.json)

#### Assumptions behind this number

| Assumed | Value | What it decides / what changing it does |
| --- | --- | --- |
| Migration approach | full cutover | one downtime event; "data-first" moves the DB first and keeps Heroku running longer (adds dual-run cost) |
| Database HA | multi-AZ (matches your availability answer; your standard-0 plan has no follower today) | "single-AZ" matches the current plan and roughly halves the RDS line |
| Cost posture | balanced | "aggressive" minimizes cost and accepts tighter margins; "conservative" matches current capacity and prioritizes stability |
| Container registry | ECR | — |
| DB migration method | pg_dump/restore (~2 GB) | confirmed before Generate — DMS for larger databases shortens the outage |
| Maintenance window | flexible | confirmed before Generate — no cost effect |

Say a row name to change it — I'll re-run Design and Estimate and show this pack again.

[A] Done for now — I have what I need to decide
[B] Explore what-ifs — reprice scenarios side by side (~1 min each): region,
    single-AZ database, compute target, Graviton
[C] Generate Terraform and migration scripts
```

Omit option **B** if the workshop sidebar is already `"completed"` from the
offer above (do not re-offer the same choice twice in one turn) — present only
**[A] Done for now** and **[C] Generate Terraform and migration scripts** in
that case.

**The "Assumptions behind this number" block** is built from `preferences.json`:
one row per question ID in `metadata.questions_defaulted` (the field's applied
value and the consequence from the Clarify catalog / Assumption Sheet), plus one
per ID in `metadata.questions_deferred_to_generate` (labelled "confirmed before
Generate"). Omit the block only when both arrays are empty. This is where the
Assumption Sheet lives when Clarify ran in fast-path mode — the user judges a
default against the dollars it moves, not before they have a number — and on the
full flow it shows the rows waved through with "use defaults for the rest".
Extracted (Detected) values are not listed here; they were read from Heroku, not
assumed.

**Handling a correction from this block:**

- If the row is a **workshop knob** — any field whose path is listed in
  `workshop-sheet.md` § Step 1 (`global.target_region`, `global.availability`,
  `data.database_ha`, `data.redis_ha`, `design_constraints.compute_target.default`,
  `operational.cost_optimization`, `workshop.cpu_architecture`) — route it
  through option **B** — the sidebar already reprices those side by side, and
  `workshop-refresh.md` § 6.4 records knob diffs in each scenario's
  `preferences_subset`, so a knob must never be changed outside it. Database HA
  and cost posture rows in the block above are knobs. The option **B** label
  names only the common ones; the full set is the sheet's. This route applies
  **whether or not option B was displayed**: when the gate omitted **B** because
  the sidebar was already `"completed"` from the offer, a knob row named here
  still enters the workshop exactly as choice **B** below does — load
  `references/phases/workshop/workshop.md`, keep `current_phase: estimate`, set
  `phases.workshop` → `"in_progress"` (its Entry runs the stale-Generate guard
  on every re-entry, so a completed sidebar is a legal starting state) — and
  returns to this gate on exit. Never write the knob into `preferences.json`
  from this gate as a workaround for a missing option. The workshop records
  the provenance the correction implies: `workshop-refresh.md` § 3 sets
  `sources.<QID>` to `"user"` and moves the ID out of
  `metadata.questions_defaulted` / `metadata.questions_skipped_extracted`
  for every knob the sheet changed, before its inner Estimate and before the
  scenario snapshot — so a corrected knob does not reappear in the block
  above as an assumption, and the saved active scenario carries the same
  provenance as the working tree. Scenarios the user did not change keep
  their own saved provenance.
- Otherwise, the correction is a late answer to a Clarify question and runs
  the **same question contract** the interview would have run — a field-only
  write is not enough:
  1. **Interpret through the catalog.** Look up the question in
     `clarify-interview.md` § Question Catalog. Validate the value against its
     **Valid options** (reject and re-prompt on mismatch, as interview Step 3c
     does). Write **every** field the matching **Interpret** line sets, and run
     any follow-up it requires before moving on — e.g. "data-first" on Q6b
     (`migration_approach: "interim_cutover_data_first"`) MUST ask the target
     exit date, validate it as a future ISO 8601 date, and set
     `target_exit_date`, `interim_cutover: true`, and `ktlo_warning`; the
     reverse correction (data-first → full cutover) sets `interim_cutover:
     false` and removes `target_exit_date` / `ktlo_warning` (schema rule 4:
     only non-null keys are written).
     Generate selects interim procedures from `migration_approach` alone, so a
     data-first answer with no exit date is never a valid state.
  2. **Record provenance.** Set `sources.<QID>` to `"user"` and move the ID to
     `metadata.questions_asked` from whichever index lists it —
     `metadata.questions_defaulted` for a defaulted row, or
     `metadata.questions_deferred_to_generate` for a Generate-time row (Q4,
     Q6c, Q12d) answered early from this block. Remove only that ID: the other
     still-unanswered deferred IDs stay listed and are still asked at **[C]**
     ("Confirm execution choices" below asks whatever remains and skips when
     the array is empty). Q12d's Interpret line already wrote
     `eb_deploy_method.chosen_by: "user"` in step 1. An ID left in the
     deferred array with `sources.<QID>` = `"user"` fails the checklist in
     step 3, so this move is what lets the correction reprice. Set
     `metadata.timestamp` to now.
  3. **Re-run the Clarify gate.** Run `clarify-assemble.md` § Validation
     Checklist on the updated `preferences.json` (re-read from disk) and stop on
     any failure — do not reprice an artifact Clarify would have rejected.
     Artifact-only: `phases.clarify` stays `"completed"`, no `HANDOFF_OK` is
     emitted, no phase breadcrumb is printed.
  4. **Reprice.** Mark `phases.design` and `phases.estimate` pending via the
     Phase Status Update Protocol and re-run Design → Estimate. Never hand-edit
     `aws-design.json` or `estimation-infra.json`. Do not re-present the gate
     yet — continue to step 5 first, so the gate (and any report the user asks
     for from it) never reads a working tree that a saved scenario contradicts.
  5. **Rebase the scenario store (when `scenarios/index.json` exists).** This
     gate is also reached after a workshop has saved scenarios, and
     `references/vendored/workshop/workshop-invariants.md` § 4 requires the
     working tree to equal
     `index.active_scenario_id`. A non-knob correction changes the **base** every
     scenario shares (`workshop-refresh.md` § 3 changes only knobs and their
     own provenance entries, so scenarios differ only by their
     `preferences_subset` knobs) — it is not a new scenario. Only non-knob
     fields reach this step: a `workshop-sheet.md` § Step 1 path was routed to
     option **B** above and must not be rebased here, or saved preferences
     would disagree with their manifest's `preferences_subset`. Rebase the
     store in place rather than
     leaving it split across two bases:
     - For the **active** scenario: overwrite its three copies
       (`scenarios/{id}.preferences.json` / `.aws-design.json` /
       `.estimation-infra.json`) with the new working-tree artifacts.
     - For **every other** scenario (baseline first): apply the same non-knob
       field change(s) and the step 2 provenance/index updates to its saved
       preferences copy, swap that copy into the
       working tree, run inner Design → Estimate per `workshop-refresh.md`
       § Inner runs (artifact-only), and copy the three working-tree artifacts
       back into that scenario's copies. After the last one, restore the working
       tree from the active scenario's three copies.
     - For each rebased manifest, recompute `preferences_fingerprint` and
       `aws_design_fingerprint` and rewrite `estimation_summary` from its new
       `estimation-infra.json` copy; leave `scenario_id`, `label`, `created_at`,
       `source`, and `preferences_subset` unchanged (knob-only diffs are
       unaffected by a non-knob field). Do not allocate a new scenario or change
       `active_scenario_id`.
     - Say so in one line: "Repricing [N] saved what-if scenario(s) with this
       change too, so the comparison stays like-for-like." The main report and
       its what-if comparison row then read the same active estimate.
  6. **Re-present this gate** (after step 5, or straight after step 4 when no
     `scenarios/index.json` exists).

**Confirm execution choices (option C only, before `run_mode` is written):**
`metadata.questions_deferred_to_generate` lists the questions Clarify defaulted
because only Generate reads them — Q4 maintenance window, Q6c DB migration
method (when Postgres is present), Q12d EB deploy method (when the compute plan
includes EB). Ask them now, in one batch, using each question's catalog text from
`clarify-interview.md` with its context (the DB size estimate and its source on
Q6c). Write each answer to its field, set `sources.<field>` to `"user"`
(`chosen_by: "user"` on `eb_deploy_method`), move the IDs to
`metadata.questions_asked`, empty `metadata.questions_deferred_to_generate`, and
only then set `run_mode`. Skip this step when the array is empty or absent.
`generate.md` must not load while it is non-empty — that is the one way a
runbook gets written against an answer the user never gave.

**Choice handling:**

- **A** → Then:
  1. **Render the decision pack:** load
     `references/shared/report-decision-core.md` and render it in **decision**
     mode — write `$MIGRATION_DIR/decision-report.html` and
     `$MIGRATION_DIR/DECISION.md` per that file's decision-mode rules (no
     appendices, no Terraform, CTA footer). Validate with
     `python3 "<SKILL_BASE>/scripts/validate-heroku-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR"`
     (absolute paths — cwd must not be load-bearing; `--migration-dir` is required
     so the decision-mode pre-execution check — `.phase-status.json`'s
     `phases.generate` must be `"pending"` or absent for THIS cycle, not raw
     `terraform/` / `generation-*.json` absence; see `report-decision-core.md` —
     actually runs) and fix failures before presenting.
  2. Set `run_mode: "decide"` and `current_phase: "complete"` in
     `.phase-status.json` (`phases.generate` **stays** `"pending"` — this
     combination means "decision complete, execution available on request";
     see `references/vendored/state/phase-status.schema.json`).
  3. **Write the web-handoff summary (fail-open):** run
     `python3 "<SKILL_BASE>/scripts/emit-plan-json.py" --migration-dir "$MIGRATION_DIR" --plugin-json "$PLUGIN_ROOT/.claude-plugin/plugin.json"`
     (absolute paths — cwd must not be load-bearing). It reads the estimate
     artifacts and writes `$MIGRATION_DIR/plan.json`, the uploadable handoff
     file, printing `PLAN_OK | …` or `PLAN_SKIP | reason=…`. This is an optional
     enhancement, never a gate: on any skip or error the decision is still
     complete — continue without it and do not surface the script output to the
     user.
  4. Continue with the Feedback sidebar per `SKILL.md`. Step 3 has already run,
     so you know its `PLAN_OK`/`PLAN_SKIP` status — author the close **once** with
     that knowledge, never as a two-pass edit of an already-shown message:
     - If step 3 printed `PLAN_SKIP` (no `plan.json`), close with:
       "Your decision report is saved at `decision-report.html` (plus a
       Slack-friendly `DECISION.md`). If you decide to migrate, say 'generate
       the Terraform and migration scripts' — everything is saved and I'll pick
       up from here."
     - If step 3 printed `PLAN_OK`, close with that same sentence and also name
       `plan.json` in it as plain text, with no link (the What's next block
       below carries the only link) — e.g. "Your decision report is saved at
       `decision-report.html` (plus a Slack-friendly `DECISION.md`), and your
       uploadable plan at `plan.json` — upload it to AWS Startups Migrate
       to see if you qualify for AWS credits. If you decide to migrate, say 'generate the
       Terraform and migration scripts' — everything is saved and I'll pick up
       from here."
  5. **Web-handoff — only when step 3 printed `PLAN_OK`** (if it printed
     `PLAN_SKIP`, omit this whole step; there is no file to upload).

     **Show the user their `plan.json`.** The `.migration` folder is hidden by default
     on macOS and Linux, so open the file's location for them instead of leaving them
     to find it. Run the command for the user's OS once, as an ordinary command — the
     agent's own permission prompt is the user's choice, so do not ask separately
     first:

     - macOS: `open -R "$MIGRATION_DIR/plan.json"` — opens Finder with the file
       selected, even inside the hidden folder.
     - Windows: `MSYS_NO_PATHCONV=1 explorer.exe /select,"<absolute Windows path to plan.json>"`
       — the prefix stops Git Bash from rewriting `/select,` as a path (drop it in
       PowerShell or cmd). In Git Bash, get the Windows path with
       `cygpath -w "$MIGRATION_DIR/plan.json"`. `explorer.exe` exits non-zero even
       when it succeeds, so treat it as opened unless it prints an error.
     - Linux: `xdg-open "$MIGRATION_DIR"` — opens the folder (it cannot select the
       file).

     Then show exactly ONE of the two messages below, as plain text (not in a code
     block). Do not reword them — this copy is owned by the web experience.

     If the folder opened:

     > **The folder is open with your plan.json selected.**

     On Linux, where the file cannot be selected, show **The folder with your
     plan.json is open.** instead.

     If the command failed, was not available, or the user declined it, show this
     as its own message, separate from the phase summary, and do not add any other
     explanation of why it did not open. Replace `<absolute path to plan.json>`
     with the real absolute path:

     > The folder did not open. The open command is blocked in your permissions.
     >
     > Your plan.json is saved at:
     > `<absolute path to plan.json>`
     >
     > The .migration folder is hidden by default on macOS. In Finder, press Command + Shift + Period (.) to show it.

     On Linux, use this last line instead: "The .migration folder is hidden by
     default on Linux. In your file manager, press Ctrl + H to show it." On Windows,
     the folder is not hidden, so omit the last line.

     Adjust only the first line: if the migration report also failed to open, start
     with "The report and the folder did not open." instead; keep "The open command
     is blocked in your permissions." only when a permission rule blocked it, and
     drop that sentence when the user declined or the command failed for another
     reason.

     Then append the What's next block below, verbatim, replacing `<run_id>` in the link with the
     run's `run_id` (from `.phase-status.json`), lowercased if it is a UUID so the
     `run=` value matches the plan's `runId`. It MUST begin with the "💬 What's
     next" heading. The call-to-action must be a Markdown link so it renders as
     clickable text with no bare URL. Do not reword it — this copy is owned by the
     web experience:

     > **💬 What's next**
     >
     > - **Refine your plan**
     >   Tell me what to change. For example: "use Fargate instead," "make it multi-region," or "reduce the cost."
     > - **See your AWS credits**
     >   Sign in or create an account on AWS Startups Migrate, then upload plan.json to see the AWS migration credits you qualify for.
     >
     > [Go to AWS Startups Migrate →](https://startups.aws.com/startups/en-US/migrate/credits?source=plugin&run=<run_id>)
     >
     > After you upload, you also get:
     >
     > - Interactive plan dashboard
     > - Monthly cost estimate
     > - Migration paths: AI agent, AWS expert, or AWS Partner

     Ship note: this reaches customers only after the import page and the
     ImportPlan API are both live in production. This `plan.json` import handoff
     is separate from the base64url plan-share link gated off in
     `SKILL.md`/`feedback-collect.md`.
- **B** → Load `references/phases/workshop/workshop.md`. Keep
  `current_phase: estimate`; set `phases.workshop` → `"in_progress"`. On
  workshop exit, **return to this gate** (options A and C; the workshop's
  active scenario carries into either) — do not advance to Generate directly.
- **C** → **Run "Confirm execution choices" above first.** Then set
  `run_mode: "decide_and_execute"` and `current_phase` → `"generate"`. Continue
  with the Feedback/Generate sidebars in `SKILL.md`.

### Decide-complete resume

If a warm start finds `current_phase == "complete"` AND `run_mode == "decide"`
AND `phases.generate == "pending"`: this is the decide-complete terminal state,
not an incomplete run. Do **not** re-run Estimate. Offer:

```
Your last session ended with a decision (see decision-report.html /
DECISION.md). Want to generate the Terraform and migration scripts now?

[A] Yes, generate now
[B] No, I'm still deciding
```

- **A** → **Run "Confirm execution choices" (§ Post-Estimate: Decision Gate)
  first** if `metadata.questions_deferred_to_generate` is non-empty. Then set
  `run_mode: "decide_and_execute"` and `current_phase` → `"generate"` **before**
  loading `generate.md`. Continue to Generate.
- **B** → Leave state unchanged; end the turn.
