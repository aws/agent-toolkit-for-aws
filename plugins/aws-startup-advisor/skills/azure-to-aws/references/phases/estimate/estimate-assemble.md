---
_assemble: assemble-estimation
_of_phase: estimate
_reads:
  - infra (fragment contribution)
  - ai (fragment contribution, when ai-workload-profile.json exists)
_produces:
  - estimation-infra.json
  - estimation-ai.json
  - DECISION.md
_knowledge:
  - { file: references/vendored/estimate/estimation-infra.schema.json }
  - { file: references/vendored/state/phase-status.schema.json }
  - { file: references/vendored/workshop/workshop-invariants.md }
---

# Estimate — Assemble Estimation and Present the Decision Gate

> **Assembler unit.** The single creator of `estimation-infra.json`. It also owns
> the post-Estimate decision gate and is the **only** unit that writes
> `run_mode`. See `estimate.md` for how it is composed into the phase.

---

## Step 1: Assemble the artifact

1. Merge the cost-engine contribution into `estimation-infra.json` per
   `references/vendored/estimate/estimation-infra.schema.json`. That schema has
   no `additionalProperties: false`, so the azure-specific keys the cost engine
   emits — `licensing_delta`, `reservation_substitutions`, the `lift` /
   `right_sized` split, `pricing_source.services_by_source.partial[]` — are legal
   without a shared schema change. Do not make one.
2. **Both totals must be present.** `projected_costs` carries a 1:1 lift total
   AND a right-sized total, and `cost_comparison.rightsizing_delta` states the
   difference between them. One total alone is an incomplete artifact, not a
   shorter one.
3. **Reconcile each total against its own lines.** Every total equals the
   arithmetic sum of its per-service costs, excluding every line that carries an
   `exclusion_reason`. A total that does not reconcile is a gate failure — never
   a rounding note, and never adjusted so the gate passes.
4. **Verify** `complexity_tier` and `complexity_inputs` are present and
   consistent with `references/vendored/estimate/complexity-tiers.json`. The cost
   engine classifies (its Part 7); this step only checks that it did, and that a
   floor total did not quietly pull the tier down.
5. **Propagate the floor flag.** If any line carries an `exclusion_reason`, both
   totals carry `is_floor: true`, and every presentation of either number in the
   next step says so. A floor presented as a total is the most misleading single
   thing this phase can emit.

---

## Step 2: Present the decision gate

Generate is **opt-in**. The decision is the product; the execution artifacts are
not. The verdict already exists in `recommendation` — present it, then let the
user choose what happens next.

Present the pack, one line each, values read from the artifact:

```
Phase 4 of 7 complete (Estimate). Remaining: Generate (+ optional Workshop, Feedback).

### Decision pack ready

- Verdict: [recommendation.outcome_label]
- Est. AWS monthly, right-sized: $[X]  ·  1:1 lift: $[Y]  ·  right-sizing saves $[Y-X]
- Your Azure baseline: [figure, with its rung label — or "not established"]
- Not priced: [services carrying an exclusion_reason, with the reason, or omit the line]
- Timeline if you execute: ~[N-M] weeks ([complexity_tier])
- Deferred to specialists: [deferred[] entries, or omit the line]

#### Assumptions behind this number

| Assumed | Value | What it decides / what changing it does |
| --- | --- | --- |
| Compute target | Elastic Beanstalk | closest to App Service; "Fargate" for direct container control |
| Plan asp-contoso-web | keep 3 apps together | mirrors today's bill; splitting multiplies the compute line by 3 |
| DB availability | single-AZ | no HA on your Flexible Server today; "multi-AZ" adds a standby (~2x the DB line) |
| DB cutover | dump/restore (64 GiB) | confirmed before Generate — DMS adds instance hours and a replication phase |
| CPU architecture | x86_64 | "Graviton" reprices compute ~20% lower where supported |

Say a row name to change it — I'll re-run Design and Estimate and show this pack again.

[A] That's what I needed for now — stop here with the design and the estimate
[B] Explore what-if scenarios (region, HA, compute target, architecture) before deciding
[C] Generate the migration artifacts — Terraform, migration scripts, and docs
```

**The "Assumptions behind this number" block** is built from `preferences.json`:
one row per key in `metadata.questions_defaulted[]`, plus one per key in
`metadata.deferred_to_generate[]` (labelled "confirmed before Generate"). The two lists
are disjoint (`clarify-assemble.md` § Assembly rule 0), so no row renders twice. An
array-row key such as `app_service_plans[0].isolation_split` resolves to that element of
the array; label the row from the plan's `name_expression` (or the `cluster_id` for
`clusters[n].pattern_id`), not from the key. Each row shows the applied value and the
consequence line its Clarify fragment supplied. Omit the block only when both arrays
are empty. This is where the assumption sheet lives when Clarify ran in fast-path mode
— the user judges a default against the dollars it moves, not before they have a
number — and on the wizard path it shows the rows the user waved through with "use the
defaults for the rest". Always include the App Service Plan isolation row when a plan
hosts more than one app.

**Handling a correction from this block:**

- If the row is a workshop knob (region, availability, compute target, CPU
  architecture), route it through option **B** — the sidebar reprices those side by
  side and applies the same provenance update as the direct route
  (`workshop-refresh.md` § 3: the user's value, `"source": "user_corrected"`, key
  removed from `metadata.questions_defaulted[]`) **before** it snapshots the scenario,
  so this block never re-lists the explicit choice as an assumption when the gate is
  re-presented.
- If the row carries `deferred_to_generate: true` (today `data.db_cutover`, the row
  labelled "confirmed before Generate"), the correction **is** the confirmation Step 3b
  would otherwise collect. Do not write `"source": "user_corrected"`; apply Step 3b's
  write rule in full instead — `value`, `"source": "user_confirmed_at_generate"`,
  `deferred_to_generate: false`, key removed from **both** `metadata` lists. Leaving
  the flag `true` makes `estimate-infra.md` § Part 4 label the user's answer "assumed;
  confirmed before Generate" and makes Step 3b ask it again. Then continue with the
  next bullet's re-run and reconciliation.
- Otherwise: write the user's value to the row (keep `disposition: PROPOSED`, add
  `"source": "user_corrected"`, remove the key from `metadata.questions_defaulted[]`),
  mark `phases.design` and `phases.estimate` pending via the Phase Status Update
  Protocol, re-run Design → Estimate, then — when `scenarios/index.json` exists — run
  § Scenario reconciliation below, and re-present this gate. Never hand-edit
  `aws-design.json` or `estimation-infra.json` to reflect the change.

Rules for the pack itself:

- **Every dollar figure is labeled an estimate** — "Est. $X/mo", never a bare
  figure that reads as exact.
- **When either total is a floor, the "Not priced" line is REQUIRED**, and both
  totals render as "$X or more". Omitting it turns an honest floor into a quiet
  understatement.
- **When the right-sizing delta is `$0`**, replace that clause with the reason
  rather than printing "saves $0" — e.g. "no utilization data, so right-sizing
  reflects declared waste only". A bare `$0` reads as a broken calculation.
- **At most one data-justified scenario hint, and only when the assumptions block
  is absent.** When a material assumption was defaulted rather than confirmed —
  most often `data.availability`, where Multi-AZ roughly doubles the database
  line — and both `metadata.questions_defaulted[]` and
  `metadata.deferred_to_generate[]` are empty (so no block rendered), append:
  "Suggestion: we assumed [assumption]; pricing a [alternative] scenario
  would bound that before you commit." When the block is present it already
  carries that row with its consequence; do not say it twice.

---

## Step 3: Handle the choice, and write `run_mode`

`run_mode` is a top-level key in `.phase-status.json`, defined in the vendored
`state/phase-status.schema.json`. It is **already** in that schema, so this needs
no shared schema change.

| Choice                   | `run_mode`             | `current_phase`    | `phases.workshop`        | Then                                                                                                                                                                                           |
| ------------------------ | ---------------------- | ------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A** — done for now     | `"decide"`             | `"complete"`       | `"completed"` (declined) | **Write `DECISION.md` (Step 3a below)**, then close out. `phases.generate` **stays** `"pending"`: that combination means "decision complete, execution available on request"                   |
| **B** — what-if workshop | `"decide"`             | stays `"estimate"` | `"in_progress"`          | Enter the `workshop` sidebar. **Re-present this gate when the sidebar resolves** (options A and C; the active scenario carries into either). Never advance to Generate from inside the sidebar |
| **C** — generate         | `"decide_and_execute"` | `"generate"`       | `"completed"` (declined) | **Run Step 3b first** (confirm deferred execution choices), then continue to Generate                                                                                                           |

Use the read-merge-write Phase Status Update Protocol, and set `phases.estimate`
to `"completed"` in the same write.

### Step 3b — On option C, confirm the deferred execution choices before Generate loads

`preferences.json` → `metadata.deferred_to_generate[]` lists the rows Clarify
defaulted because nothing before Generate consumes them (today: `data.db_cutover`;
see `clarify-database.md` § Q-D2). They are **asked for real here**, one batch,
each with the fragment's original options and the context that makes it
answerable — the extracted database size for `db_cutover`. The prompt follows the
row's `size_coverage`:

**`size_coverage: "complete"`** — the measured size is the context:

> "Before I write the runbook, one execution choice I defaulted earlier:
>
> **Database cutover** — your largest database is 64 GiB, so I assumed
> dump-and-restore (a scheduled outage proportional to size).
> [A] AWS DMS with continuous replication — near-zero downtime, more setup, needs logical replication on the source
> [B] Dump and restore during a maintenance window — simpler, downtime proportional to database size (current assumption)"

**`size_coverage: "unknown"`** — say why the size is missing (from `default_basis`),
and offer to take the size first:

> "**Database cutover** — I couldn't read your database's size ([reason from
> `default_basis`, e.g. the storage enrichment call was skipped]), so I assumed
> dump-and-restore for `<server name>`. Roughly how large is it? Under 100 GiB,
> dump-and-restore is the simpler path; above it, DMS.
> [A] AWS DMS with continuous replication — near-zero downtime, more setup, needs logical replication on the source
> [B] Dump and restore during a maintenance window — simpler, downtime proportional to database size (current assumption)
> [C] Tell me the size first and I'll recommend"

**`size_coverage: "partial"`** — name the unmeasured server(s) and say the rule may
flip: "your largest _measured_ database is 64 GiB, but `<server>` has no recorded
size — if it is above 100 GiB the recommendation flips to DMS." Offer the same [C].

When the user states a size, write it on the row as `user_stated_size_gib: <n>` —
leave `largest_relational_db_gib` and `size_coverage` as Clarify wrote them, because
they record what Discover measured — then recommend per the 100 GiB rule (inclusive
on the dump-and-restore side) and take [A] or [B]. Never rewrite the measured fields
to make the row look complete.

**Write rule — clear every piece of deferral state in one preference update:**

1. `value` ← the answer; `"source": "user_confirmed_at_generate"`; disposition stays
   `PROPOSED`.
2. `deferred_to_generate: false` — explicit, not deleted. `estimate-infra.md` § Part 4
   reads this row flag to choose its label; leaving it `true` makes the confirmed
   answer print as "assumed".
3. Remove the key from `metadata.deferred_to_generate[]` **and** from
   `metadata.questions_defaulted[]`. The lists are disjoint from this PR on, so the
   second removal is a no-op on a fresh file; it is kept so a `preferences.json`
   written before the lists were disjoint is also cleaned and Step 2 cannot re-list
   the confirmed answer.
4. Keep `default`, `default_basis`, `largest_relational_db_gib`, and `size_coverage`
   as the audit trail of what was assumed and why.

Only then write `run_mode: "decide_and_execute"`.

**Reprice the migration-cost line, whether or not the answer changed.** Re-run
`estimate-infra.md` § Part 4 Migration cost considerations — the Migration-service
cost row — against the confirmed value. Because the row flag is now `false` and
`source` is `user_confirmed_at_generate`, the line is labelled "confirmed at the
Decision gate", never "assumed; confirmed before Generate". A changed answer
(`dump_restore` → `dms`) adds DMS instance hours — note the delta in one line; an
unchanged answer changes no dollars but the label still flips. Do not re-present the
whole pack, and do not re-run Part 7 — that is the complexity tier, which this answer
does not move. When `scenarios/index.json` exists, run § Scenario reconciliation below
after **every** Step 3b write, changed answer or not — the write rule and the Part 4
label have changed the working `preferences.json` and `estimation-infra.json` either
way, and `workshop-invariants.md` § 4 is about the working tree matching the active
snapshot, not about whether a dollar figure moved.

Generate's `_preconditions` must find `metadata.deferred_to_generate` empty and no
row still carrying `deferred_to_generate: true` — an unconfirmed deferred row is the
one way a runbook can be written against an answer the user never gave.

This step is skipped when `metadata.deferred_to_generate[]` is empty or absent (an
estate with no relational database, a `preferences.json` written before this field
existed, or a deferred row the user already corrected from the Step 2 assumptions
block — that correction applied this step's write rule and emptied the list).

### Scenario reconciliation after a gate-side preference write

**Trigger:** a direct correction from the Step 2 assumptions block that re-ran Design
→ Estimate, or **any** Step 3b write (changed answer or not) — **and**
`scenarios/index.json` exists (a workshop has saved scenarios). Skip when it does not.

**Why:** `workshop-invariants.md` § 4 — the working preference/design/estimate
artifacts must always match `index.active_scenario_id`. The sidebar
(`workshop-refresh.md` § 6) is otherwise the only writer of `scenarios/<id>.*`, so a
gate-side write that re-prices the working tree leaves the active snapshot and its
`estimation_summary` describing a design Generate will not build, and the report's
what-if table reads those stale manifests. An unchanged Step 3b answer moves no
dollars but still rewrites the row's provenance and the Part 4 label, so the active
snapshot differs from the working tree until this runs; the procedure is idempotent,
so running it for a provenance-only write costs nothing.

**Procedure — update the active scenario in place, mark the rest stale when the
estimate moved:**

1. Read `index.active_scenario_id` (call it `<active>`).
2. After Design/Estimate (or the Part 4 reprice) have written the working tree,
   overwrite `scenarios/<active>.preferences.json`, `scenarios/<active>.aws-design.json`,
   and `scenarios/<active>.estimation-infra.json` from the working-tree artifacts.
3. Rewrite the active manifest `scenarios/<active>.json`: `estimation_summary` (the
   three tiers, `complexity_tier`, `pricing_source`, `recommendation_outcome`) from the
   new `estimation-infra.json`; recompute `preferences_subset` against the baseline
   snapshot; set `corrected_at_gate: "<dotted row key>"`; append
   `(corrected at decision gate: <row>)` to `label`.
4. **When the write changed the estimate** (the active manifest's `estimation_summary`
   differs from the one step 3 just wrote), on **every other** manifest (the baseline
   included when it is not active) set `stale: true` and `stale_reason: "<row> changed
   at the decision gate after this scenario was priced"`. Do not delete, re-price, or
   re-id them — a new scenario id here would trip the five-scenario cap outside the
   sidebar. When the write changed only provenance (an unchanged Step 3b answer), skip
   this step: the other scenarios' numbers are still right, and their snapshot copies
   carrying the pre-confirmation row is accepted drift — the sidebar's next Apply
   snapshots a fresh id from the working tree anyway.
5. Leave `inventory_fingerprint`, `active_scenario_id`, and
   `.phase-status.json.phases.workshop` unchanged.
6. Say one line: "Updated scenario `<active>`; `<n>` other scenario(s) marked stale —
   reprice in the workshop to refresh them." Omit the second clause when step 4 was
   skipped.

`workshop-compare.md` and the report's what-if table render the `stale` marker. A
stale scenario stays stale — the sidebar snapshots a fresh id on its next Apply
(`workshop-refresh.md` § 6) rather than rewriting a priced one, so the marker is the
honest record that the old row was priced before the correction.

### Step 3a — On option A, write `DECISION.md` (the Assess-complete handoff marker)

Option A is a completed Assess: the customer has a design and a costed decision but no
execution artifacts. Write `$MIGRATION_DIR/DECISION.md` — a plain-Markdown decision report
(Slack/GitHub-friendly, **no HTML tags**) built from the artifacts that exist now
(`preferences.json`, `aws-design.json` and/or `aws-design-ai.json`, `estimation-infra.json`
and/or `estimation-ai.json`). This is the standardized "assessment is done, here is the
decision" marker that a downstream AI-rewrite path reads — it pairs with the
`run_mode: "decide"` + `current_phase: "complete"` tuple so any consumer can recognise an
Assess-complete azure run the same way it recognises a gcp one.

Content (match gcp-to-aws's `DECISION.md` twin — same shape, Azure wording):

1. **Verdict headline** — the recommendation in one line (migrate / migrate-with-conditions /
   stay), from `estimation-*.json` `recommendation`.
2. **Cost table** — current Azure monthly vs projected AWS monthly (1:1 lift and right-sized),
   with the floor/credibility caveats carried verbatim from the estimate; for an AI-only run,
   the Bedrock projection and the source-vs-target comparison from `estimation-ai.json`.
3. **Migrate-if / Stay-if** — the conditions under which the recommendation holds.
4. **Timeline band** — `~[N–M] weeks` from the complexity tier, or omit when no tier signal.
5. **Top risks** — the most material assumptions/exclusions (availability downgrade, unpriced
   lines, licensing, the RDS Multi-AZ overstatement, etc.).
6. **Assumptions** — the defaulted-not-confirmed rows that shaped the numbers.
7. **CTA line** — "Ready to execute? Say 'generate the Terraform and migration artifacts' and
   I'll produce the full execution pack from this same analysis." Plus: "This decision report
   was written without execution artifacts; the full migration report replaces it if you
   proceed."

> **The full HTML `decision-report.html` twin is deferred** — it needs gcp's shared
> `report-decision-core.md` renderer vendored into azure (a consumer-contract file, the same
> class as `pricing-cache.md`; see plan §19.13). `DECISION.md` is the load-bearing handoff
> marker and stands alone as plain Markdown; the HTML report is a presentation upgrade, not
> the handoff signal.

### Why C writes `run_mode` before Generate loads

Write `run_mode: "decide_and_execute"` **before** `generate.md` loads, not after
it finishes. A session that dies mid-Generate then resumes as an Execute run
rather than re-asking a question the user already answered. Writing it afterwards
means a crash silently discards consent that was actually given.

### An absent `run_mode` is NOT consent

An absent `run_mode` means the question has not been put to the user yet. It is
not a default and it is not a "no". Do not infer consent from silence, from a
completed Estimate, or from the user having asked for an estimate in the first
place.

**This rule has no mechanical teeth.** `generate.md` expresses it as an
`_assert`, and per `INTERPRETER.md` the DSL binds `_assert` prose but never
evaluates it — so the same model that might skip the gate is the one certifying
it was not skipped. The safeguard here is the procedure, not a validator. That is
a reason to be more careful, not less.

### On A, do not nag

Option A is a complete, successful run, not an abandoned one: the customer got a
design and a costed decision. Close with where the artifacts are and how to
resume — "if you decide to migrate, say 'generate the Terraform and migration
scripts' and I'll pick up from here" — and stop there.

---

## Step 4: Postconditions

Evaluate the `_postconditions` declared in `estimate.md`. On all-pass emit
`HANDOFF_OK | phase=estimate | artifacts=estimation-infra.json`. On any failure
emit `GATE_FAIL | phase=estimate | field=<path> | reason=<reason>` and stop.

**Do not modify the artifact to make a gate pass, and do not update
`.phase-status.json` on a failure.** Report which check failed and what would fix
it.

### Inner workshop reprice — skip the transition

When Estimate is re-run from `workshop-refresh.md` as an inner reprice: write the
artifact, present a brief summary, and **return to the workshop loop**. Do not
emit `HANDOFF_OK`, do not touch `.phase-status.json`, and do not present the
decision gate. The gate belongs to the outer run; re-presenting it inside the
sidebar is how a scenario comparison turns into an accidental commitment.
