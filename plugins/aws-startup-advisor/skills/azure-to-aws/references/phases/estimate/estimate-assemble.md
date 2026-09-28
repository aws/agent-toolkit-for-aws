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

[A] That's what I needed for now — stop here with the design and the estimate
[B] Explore what-if scenarios (region, HA, compute target, architecture) before deciding
[C] Generate the migration artifacts — Terraform, migration scripts, and docs
```

Rules for the pack itself:

- **Every dollar figure is labeled an estimate** — "Est. $X/mo", never a bare
  figure that reads as exact.
- **When either total is a floor, the "Not priced" line is REQUIRED**, and both
  totals render as "$X or more". Omitting it turns an honest floor into a quiet
  understatement.
- **When the right-sizing delta is `$0`**, replace that clause with the reason
  rather than printing "saves $0" — e.g. "no utilization data, so right-sizing
  reflects declared waste only". A bare `$0` reads as a broken calculation.
- **At most one data-justified scenario hint.** When a material assumption was
  defaulted rather than confirmed — most often `data.availability`, where
  Multi-AZ roughly doubles the database line — append: "Suggestion: we assumed
  [assumption]; pricing a [alternative] scenario would bound that before you
  commit."

---

## Step 3: Handle the choice, and write `run_mode`

`run_mode` is a top-level key in `.phase-status.json`, defined in the vendored
`state/phase-status.schema.json`. It is **already** in that schema, so this needs
no shared schema change.

| Choice                   | `run_mode`             | `current_phase`    | `phases.workshop`        | Then                                                                                                                                                                                           |
| ------------------------ | ---------------------- | ------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A** — done for now     | `"decide"`             | `"complete"`       | `"completed"` (declined) | **Write `DECISION.md` (Step 3a below)**, then close out. `phases.generate` **stays** `"pending"`: that combination means "decision complete, execution available on request"                   |
| **B** — what-if workshop | `"decide"`             | stays `"estimate"` | `"in_progress"`          | Enter the `workshop` sidebar. **Re-present this gate when the sidebar resolves** (options A and C; the active scenario carries into either). Never advance to Generate from inside the sidebar |
| **C** — generate         | `"decide_and_execute"` | `"generate"`       | `"completed"` (declined) | Continue to Generate                                                                                                                                                                           |

Use the read-merge-write Phase Status Update Protocol, and set `phases.estimate`
to `"completed"` in the same write.

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
