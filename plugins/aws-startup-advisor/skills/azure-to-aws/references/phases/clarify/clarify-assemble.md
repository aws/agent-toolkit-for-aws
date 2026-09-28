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

- [ ] `global.target_region` is set.
- [ ] `design_constraints.cpu_architecture` is set, with `x86_64` recorded as the default.
- [ ] `identity` is set (Category J always fires).
- [ ] `licensing` is either answered or explicitly N/A **with a reason**.
- [ ] **No row has `disposition: "ESSENTIAL"` and `value: null`.** That combination is the
      gate: an essential question was shown and not answered, and the phase must not complete.
- [ ] Every row whose `value` came from its default still reads `PROPOSED`, not `DETECTED`.
- [ ] Every App Service Plan hosting more than one app has an isolation answer, or the
      recorded default of no split.
- [ ] Every cluster carrying a `pattern_id` has a user-confirmed value.
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
