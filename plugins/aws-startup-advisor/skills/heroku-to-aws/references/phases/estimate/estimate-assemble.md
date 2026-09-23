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

[A] Done for now — I have what I need to decide
[B] Explore what-ifs — reprice scenarios side by side (~1 min each): region,
    single-AZ database, compute target, Graviton
[C] Generate Terraform and migration scripts
```

Omit option **B** if the workshop sidebar is already `"completed"` from the
offer above (do not re-offer the same choice twice in one turn) — present only
**[A] Done for now** and **[C] Generate Terraform and migration scripts** in
that case.

**Choice handling:**

- **A** → Then:
  1. **Render the decision pack:** load
     `references/shared/report-decision-core.md` and render it in **decision**
     mode — write `$MIGRATION_DIR/decision-report.html` and
     `$MIGRATION_DIR/DECISION.md` per that file's decision-mode rules (no
     appendices, no Terraform, CTA footer). Validate with
     `python3 "$PLUGIN_ROOT/scripts/validate-heroku-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR"`
     (absolute paths — cwd must not be load-bearing; `--migration-dir` is required
     so the decision-mode pre-execution check — `.phase-status.json`'s
     `phases.generate` must be `"pending"` or absent for THIS cycle, not raw
     `terraform/` / `generation-*.json` absence; see `report-decision-core.md` —
     actually runs) and fix failures before presenting.
  2. Set `run_mode: "decide"` and `current_phase: "complete"` in
     `.phase-status.json` (`phases.generate` **stays** `"pending"` — this
     combination means "decision complete, execution available on request";
     see `references/vendored/state/phase-status.schema.json`).
  3. Continue with the Feedback sidebar per `SKILL.md`. Close with:
     "Your decision report is saved at `decision-report.html` (plus a
     Slack-friendly `DECISION.md`). If you decide to migrate, say 'generate
     the Terraform and migration scripts' — everything is saved and I'll pick
     up from here."
- **B** → Load `references/phases/workshop/workshop.md`. Keep
  `current_phase: estimate`; set `phases.workshop` → `"in_progress"`. On
  workshop exit, **return to this gate** (options A and C; the workshop's
  active scenario carries into either) — do not advance to Generate directly.
- **C** → Set `run_mode: "decide_and_execute"` and `current_phase` →
  `"generate"`. Continue with the Feedback/Generate sidebars in `SKILL.md`.

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

- **A** → Set `run_mode: "decide_and_execute"` and `current_phase` →
  `"generate"` **before** loading `generate.md`. Continue to Generate.
- **B** → Leave state unchanged; end the turn.
