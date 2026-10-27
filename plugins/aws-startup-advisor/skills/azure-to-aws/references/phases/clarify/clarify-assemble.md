---
_assemble: assemble-preferences
_of_phase: clarify
_reads:
  - global (fragment contribution)
  - compute (fragment contribution)
  - database (fragment contribution)
  - licensing (fragment contribution)
  - identity (fragment contribution)
  - ai (fragment contribution, when ai-workload-profile.json exists)
_produces:
  - preferences.json
_knowledge:
  - { file: references/shared/schema-preferences.md }
  - { file: references/shared/schema-discover-ai.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
---

# Clarify — Assemble Preferences

> **Assembler unit.** The single creator of `preferences.json` and the owner of its
> final contract. See `clarify.md` for how it is composed into the phase.

**Schema reference**: `references/shared/schema-preferences.md`.

## This unit owns the conversation

Fragments compute rows. **The assembler is the only thing that talks to the user**, and it
runs three gates in order. See `clarify.md` § Step: Run the phase for why.

### Gate 1 — The assumption sheet (mandatory)

Present **every** DETECTED and PROPOSED row, from all fragments, as one sheet — batched at
**five rows at a time**. Each row shows: what it is, the disposition, the value or default,
and the **consequence line** the fragment supplied.

```
Migration assumptions — confirm or correct

  1. Target region          DETECTED   eu-west-1
     Mapped from westeurope. All AWS resources deploy here.
  2. Compute target         PROPOSED   Elastic Beanstalk
     Closest to App Service; AWS manages deployment, scaling and patching.
     Choose Fargate for direct container control.
  3. Plan asp-contoso-web   PROPOSED   keep 5 apps together
     Mirrors what you pay for today. Splitting multiplies the compute line by 5.
  4. CPU architecture       DETECTED   x86_64
     Forced by vm-contoso-reporting (Windows). Graviton is not available for it.
  5. Human identity         PROPOSED   fresh IAM Identity Center
     Simplest path, and leaves no dependency on Azure after cutover.

Reply with a row number to change it, or "looks right" to accept all.
```

**Accept "use the defaults for the rest" at any point** and record the documented defaults
for the remainder — the phase completes either way. A wizard the user cannot escape is an
interrogation.

### Fast-path mode (entered from `clarify.md` § Step 0.5 only)

When Clarify entered via the fast-path offer, the three gates collapse into one exchange.
Nothing about the _rows_ changes — every fragment has run and every row has a disposition —
only the order and the gating:

1. **Ask the ESSENTIAL rows first, in one batch, with their context lines.** On an eligible
   estate these are at most: `design_constraints.compliance` (Q-A1c, always) and
   `baseline.azure_monthly_spend` (Q-A5, only when no billing source was discovered). No
   other ESSENTIAL row can fire, because Discover's eligibility rule excludes every estate
   feature that would make one fire (and `data.db_cutover` is PROPOSED-and-deferred, not
   ESSENTIAL — see Q-D2). If one does, the inventory and the verdict disagree — stop, say
   so, and fall back to the full flow.
2. **Apply every DETECTED and PROPOSED row's documented value** without presenting a sheet.
   Record each PROPOSED row's key in `metadata.questions_defaulted[]` — other than rows
   carrying `deferred_to_generate: true`, which are listed in
   `metadata.deferred_to_generate[]` instead (below); DETECTED rows are not "defaulted" —
   they were read from the estate. Array rows use index notation —
   `app_service_plans[0].isolation_split`, `clusters[1].pattern_id` — so one dotted
   lookup resolves the entry (the Estimate block labels the row from the plan's
   `name_expression` or the `cluster_id`, not from the key). Rows marked
   `deferred_to_generate` go **only** in `metadata.deferred_to_generate[]`, never in
   `questions_defaulted[]` — the two lists are disjoint, so a deferred row renders once in
   the Estimate block and Step 3b has one entry to clear.
3. **Say one sentence, then proceed** — do not present the defaults here:

   > "Thanks — I've applied [N] documented defaults (compute target, DB availability, plan
   > grouping, …). You'll see each one, with what it decides and what it costs, right next
   > to the estimate, and you can change any of them there."

   The defaults are rendered by `estimate-assemble.md` § Step 2 as the **"Assumptions
   behind this number"** block, _after_ the user has a number to judge them against. A
   default is only worth correcting once its consequence is visible in dollars; showing the
   list before the estimate is the gate this mode exists to remove.
4. Write `preferences.json` with `metadata.clarify_mode: "fast_path"`. Everything else in
   this file — `clarify_status`, the Validation Checklist, the handoff gate — applies,
   read in **fast-path mode**: where a check or a `clarify.md` postcondition says a row
   was "asked", "shown", or "user-confirmed", the fast path satisfies it when the row
   carries its documented default, is listed in `metadata.questions_defaulted[]`, and is
   disclosed at `estimate-assemble.md` § Step 2. The wizard meaning is unchanged; the
   fast path is not a relaxed gate but a second way to pass it, and a fast-path run that
   lacks the list entry still fails.

Corrections (made at the Estimate gate directly, or through the workshop sidebar —
`workshop-refresh.md` § 3) remove the row's key from `questions_defaulted[]`, write the
user's value, and add a `"source": "user_corrected"` sibling on the row (disposition stays
`PROPOSED`, per assembly rule 2), so Design's rationale can say "you chose this" rather than
"we assumed this". A deferred row corrected at the gate takes the Step 3b confirmation write
instead (`estimate-assemble.md` § Step 2).

The App Service Plan isolation row (Q-C2) deserves one explicit word: it stays PROPOSED with
its documented default (no split) on the fast path, as on the full sheet, and it **must**
appear in the Estimate-side assumptions block with its cost consequence whenever a plan hosts
more than one app. `SKILL.md` names plan isolation as a reason Clarify cannot be skipped; the
fast path honours that by always surfacing the default next to the number it moves, not by
asking a question the full flow also defaults.

**Show N/A rows too**, compactly, at the end of the sheet. _"Licensing — N/A, no Windows or
SQL found"_ tells the user the estate was checked. Silence does not, and the report
distinguishes the two.

### Gate 2 — The essential questions

Only after the sheet is confirmed. Ask each ESSENTIAL row directly, batched, **with the
context its fragment supplied** — an essential question without its context is unanswerable:

> _Your `pg-contoso-store` is `ZoneRedundant` with a standby in zone 2 today. We will not
> assume you want to keep paying for that, and we will not assume you want to give it up._

An ESSENTIAL row has no default **on purpose**, and the phase does not complete until every
one is answered. Do not invent a default to get past the gate; do not treat silence as an
answer.

### Gate 3 — The recap

Echo back what was recorded, ESSENTIAL rows first, then anything the user corrected. This is
the last point before Design commits, and it is cheap relative to re-running four phases.

## Assembly rules

0. Write the top-level `metadata` block: `clarify_mode` (`"fast_path"` | `"wizard"`),
   `fast_path_eligible` (copied from the inventory verdict so the report can show both the
   verdict and the choice), `questions_defaulted[]` (every PROPOSED row that took its
   documented value without being shown as a question, other than rows carrying
   `deferred_to_generate: true` — on the wizard path that is the rows the user confirmed on
   the sheet or waved through with "use the defaults for the rest"; array rows under their
   index key, e.g. `app_service_plans[0].isolation_split`),
   and `deferred_to_generate[]` (every row carrying `deferred_to_generate: true` — today
   only `data.db_cutover` when a relational database is present; `[]` otherwise). The two
   lists are **disjoint**: a deferred row is never also listed in `questions_defaulted[]`.
   A deferred row is **not** asked in this phase on either path; it is confirmed at the
   Decision gate's [C] (`estimate-assemble.md` § Step 3b) before Generate loads.
1. Merge every fragment's rows into one `preferences.json`.
2. Every row carries `disposition`, `value`, and `default`. A row the user never answered
   keeps its documented default and **stays PROPOSED** — never silently promote a default to
   a user decision. Design's rationale prints "you chose this" differently from "we assumed
   this", and that distinction is only available if it is recorded here.
3. Record `licensing` as N/A **explicitly** when the gate did not fire, with the reason. An
   absent key and a considered N/A are different facts.
4. Carry the user's confirmed or corrected cluster `pattern_id` values forward, so Design
   consumes a validated pattern rather than re-deriving one.
5. **Never copy a secret out of the inventory.** The inventory holds app-setting NAMES only,
   and preferences has no reason to hold even those.

## `clarify_status` — the phase's own verdict

**REQUIRED at the top level of `preferences.json`.** Exactly one of:

| Value                  | Means                                                                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COMPLETE`             | Every row the user was shown is recorded, and no `ESSENTIAL` row has `value: null`. The phase may emit `HANDOFF_OK`                                                 |
| `BLOCKED_ON_ESSENTIAL` | At least one `ESSENTIAL` row was shown and left unanswered. The phase emits `GATE_FAIL`, and every blocking row carries `unanswered: true` and `blocks_phase: true` |

`ESSENTIAL` + `value: null` **is** the completion gate (decision 13.5b) — an essential row
has no default on purpose, and this field is where that determination is written down. A run
that reaches `HANDOFF_OK` with a null essential value has invented consent, and the artifact
is perfectly well-formed either way, which is exactly why the verdict must be explicit rather
than left for a reader to infer.

**A conflicting answer does NOT block.** If the user selects an option a `hard_blockers` row
suppresses — MGN against an Azure Edition Windows image, say — record the answer **as given**,
add a sibling `conflict` key stating what suppresses it and why, and put the blocker in
`licensing.blockers[]` with `severity: "blocker"`. Status stays `COMPLETE`: the customer
answered, and the blocker is a **prerequisite**, not a competing preference. Silently
rewriting their answer and faking a gate failure both hide a real decision they need to make.

## Validation Checklist

- [ ] `clarify_status` is set to `COMPLETE` or `BLOCKED_ON_ESSENTIAL`, and it agrees with whether any `ESSENTIAL` row has `value: null`.
- [ ] `metadata.clarify_mode` is `fast_path` or `wizard`; when `fast_path`, the inventory's `metadata.clarify_fast_path.eligible` was `true` and `metadata.questions_defaulted[]` lists every PROPOSED row that was not asked, other than rows carrying `deferred_to_generate: true` (listed in `metadata.deferred_to_generate[]`).
- [ ] `metadata.deferred_to_generate[]` is present and lists exactly the rows carrying `deferred_to_generate: true`; each such row has a non-null `default`, a `default_basis`, a `size_coverage` (`complete` | `partial` | `unknown` — the unknown-size fallback is a documented default, not a gap), and does not appear in `questions_defaulted[]`.
- [ ] `questions_defaulted[]` and `deferred_to_generate[]` share no key, and every `questions_defaulted[]` key (index notation for array rows) resolves to a PROPOSED row whose `value` equals its `default` and carries no `source`.

- [ ] `global.target_region` is set.
- [ ] `design_constraints.cpu_architecture` is set, with `x86_64` recorded as the default.
- [ ] `identity` is set (Category J always fires).
- [ ] `licensing` is either answered or explicitly N/A **with a reason**.
- [ ] **No row has `disposition: "ESSENTIAL"` and `value: null`.** That combination is the
      gate: an essential question was shown and not answered, and the phase must not complete.
- [ ] Every row whose `value` came from its default still reads `PROPOSED`, not `DETECTED`.
- [ ] Every App Service Plan hosting more than one app has an isolation answer — on the
      wizard path the user's answer or the default of no split confirmed on the sheet; on the
      fast path the recorded default of no split **and** an
      `app_service_plans[n].isolation_split` entry in `metadata.questions_defaulted[]`, so
      `estimate-assemble.md` § Step 2 discloses it.
- [ ] Every cluster carrying a `pattern_id` has a confirmed value — on the wizard path
      user-confirmed or corrected on the sheet; on the fast path the detected pattern as its
      documented default, and (when the row is PROPOSED) a `clusters[n].pattern_id` entry in
      `metadata.questions_defaulted[]`.
- [ ] Every fragment that did **not** fire has its section written as `N/A` with a reason —
      not omitted.
- [ ] No secret values were copied out of the inventory into preferences.

## Status — build step 5 (infra categories)

Owns the three gates and the checklist. Reads five fragments: global, compute, database,
licensing (conditional), identity.

| Lands in | What                                                                                                           |
| -------- | -------------------------------------------------------------------------------------------------------------- |
| step 4   | the cluster pattern-confirmation section, once `patterns.md` exists to produce a `pattern_id` worth confirming |
| done     | `clarify-ai.md` (wired, build step 3); the standalone `clarify-ai-only.md` route is deferred (§19.9c)          |
