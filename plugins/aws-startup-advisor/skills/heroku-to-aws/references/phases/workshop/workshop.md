---
_phase: workshop
_title: "What-If Workshop (Optional)"
_kind: sidebar
_requires_phase: estimate
_gates: generate
_trigger:
  {
    _when: "user opts in post-Estimate (estimate-assemble offer [A], or says what if / reprice / workshop mode / compare scenarios)",
  }
_input:
  - heroku-resource-inventory.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
_knowledge:
  - { file: references/shared/schema-workshop-scenarios.md }
_fragments:
  - _id: sheet
    _trigger: { _always: true }
    _file: phases/workshop/workshop-sheet.md
  - _id: refresh
    _trigger: { _when: "user chose Apply & reprice" }
    _file: phases/workshop/workshop-refresh.md
  - _id: compare
    _trigger: { _when: "user chose Compare scenarios OR after a successful refresh" }
    _file: phases/workshop/workshop-compare.md
_assemble:
  _file: phases/workshop/workshop-assemble.md
_produces:
  - scenarios/index.json
_interactive: true
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_file_exists:
      [
        heroku-resource-inventory.json,
        preferences.json,
        aws-design.json,
        estimation-infra.json,
      ]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: scenarios/index.json
    _on_failure: _warn_and_skip
---

# Phase: What-If Workshop (Sidebar)

> **Sidebar** (`_kind: sidebar`), not a backbone step — same class as
> `feedback`. Entered only when its `_trigger` fires; has **no** `_advances_to`;
> never becomes `current_phase`. Returns control to the Estimate→Generate flow.
> Contract: `references/shared/schema-workshop-scenarios.md`.

**Execute ALL steps in order. Do not skip or deviate.**

## Entry

1. Preconditions above must pass. Do **not** re-run Discover / live CLI / Terraform parse.
2. **Stale Generate/decide guard (mandatory, single authoritative point —
   runs before any other Entry step or Loop branch).** This condition covers
   EVERY re-entry path into workshop (Apply & reprice, Compare scenarios, or
   exiting workshop without ever entering `workshop-refresh.md`) — do not
   rely on a narrower guard inside `workshop-refresh.md` alone; by the time
   that file's own "Stale Generate guard" step runs, this step has already
   reset `phases.generate`, so a second `== "completed"` check there can
   never fire again.

   Fires when ANY of: `phases.generate` (or later) is `"completed"`;
   `phases.generate` is `"in_progress"` (an interrupted Generate);
   `current_phase == "generate"` with `run_mode` set (choice C was taken —
   `phases.generate` may still be `"pending"` here if Generate was never
   actually entered, which is why this condition is written on
   `current_phase`, not `phases.generate`); `current_phase == "complete"`
   with `run_mode` set (a resolved decide/decide_and_execute state). Step 3
   below normalizes `current_phase`/`run_mode` for every one of these four
   conditions, not only the last.

   On fire: apply Estimate `_re_entry_guard` confirm → set every phase
   downstream of Estimate back to `"pending"` in `.phase-status.json`
   (`reset_downstream_to_pending`).

   **Do NOT delete anything Generate wrote.** An earlier version of this
   guard deleted a named subset of Generate's output files (`baseline.tf`,
   `variables.tf`, etc.) on the theory that only those exact filenames are
   "purely generated." That is false: `generate-terraform.md` tells users to
   fill in `terraform.tfvars`, and per its Step 11 header/opt-out
   instructions users are told to hand-edit `baseline.tf` (replace
   placeholder contact emails) and `variables.tf` (comment out blocks to
   decline the security baseline) — both keep their generated filename after
   being customer-edited. `_contributes:` frontmatter identifies each
   fragment's ORIGINAL output path, not whether that path's CURRENT contents
   are still disposable; there is no reliable way to tell "still exactly as
   generated" apart from "customer-edited since" from the filename alone, so
   no filename-based deletion list can be made safe. `terraform/` and every
   other Generate-produced path (`generation-*.json`, `MIGRATION_GUIDE.md`,
   `README.md`, `migration-report.html`, `report-validation-status.json`)
   are left completely untouched by this guard — Design/Estimate get
   overwritten by the reprice, but the previous execution pack these files
   represent is never modified, deleted, or archived by workshop re-entry.

   Reaching the Decision gate afterward with a stale execution pack still on
   disk is fine: `validate-heroku-migration-report.py --mode decision`
   determines "pre-execution" from `.phase-status.json`'s own
   `phases.generate` value (reset to `"pending"` by this guard above), not
   from whether `terraform/`/`generation-*.json` happen to exist on disk —
   see that validator's decision-mode check. A prior cycle's execution pack
   legitimately coexisting with a fresh decision is the expected, supported
   state; it is what lets the user compare the new decision against files
   they may still be relying on, and it is exactly what the next accepted
   Generate run will overwrite in its own course.

   If the user does NOT confirm the guard (declines the re-entry), **stop**
   here — do not patch preferences or re-run Design/Estimate; the existing
   execution pack and decide/execute state are left untouched either way.
3. **Normalize `current_phase`/`run_mode` on ANY accepted re-entry
   (mandatory).** This step runs whenever step 2 fired and the user
   confirmed — it is the same re-entry event, not a separately-triggered one.
   An earlier version of this step only fired when `current_phase ==
   "complete"`, which covers the terminal decide-complete resume
   (`run_mode: "decide"`, `phases.generate: "pending"`) but NOT the three
   `current_phase: "generate"` states step 2 also detects as stale (choice C
   taken, with `phases.generate` `"pending"`, `"in_progress"`, or
   `"completed"`). Scoping the reset to one named `current_phase` value while
   the guard above fires on four different conditions left three of those
   four states with a normalized `phases.generate` but a STALE
   `current_phase`/`run_mode` — a session resumed after workshop exit would
   then select Generate again (per `SKILL.md` § "Gate-presented resume",
   which requires `run_mode` absent to detect an unresolved gate) instead of
   reaching the still-unresolved Decision gate.

   Whenever step 2's guard fired and was confirmed, ALSO reset
   `current_phase` to `"estimate"` and clear `run_mode` (read-merge-write,
   remove the key rather than setting it to null) **before** step 4 — for
   every one of step 2's four trigger conditions, not only the
   `current_phase == "complete"` case. This returns the run to the pre-gate
   state the workshop expects in every accepted-re-entry state, not just the
   terminal one.
4. Set `phases.workshop` to `"in_progress"` (do not change `current_phase`
   further — sidebars never own it). Prefer leaving `current_phase` at
   `estimate` until the user exits workshop back to the Decision gate (see
   `estimate-assemble.md` § "Post-Estimate: Decision Gate" and
   `workshop-assemble.md`).

## Loop

1. If `scenarios/index.json` missing → `workshop-refresh.md` § Baseline capture.
2. `workshop-sheet.md` — present knobs + actions.
3. Branch:
   - **Apply & reprice** → `workshop-refresh.md` (inner Design/Estimate) →
     `workshop-compare.md`
   - **Compare scenarios** → `workshop-compare.md`
   - **Exit workshop** → `workshop-assemble.md` (resolve sidebar) → returns to
     the **Decision gate** in `estimate-assemble.md` (never directly to
     Generate — see `workshop-assemble.md`)
   - **Exit to full Clarify** → danger; Clarify re-entry only on explicit confirm

## Hard rules

| Rule                  | Behavior                                                       |
| --------------------- | -------------------------------------------------------------- |
| Inventory frozen      | Never write inventory or `capture/`                            |
| Inner Design/Estimate | Artifact rewrite only — see `workshop-refresh.md` § Inner runs |
| Max 5 scenarios       | Warn + name eviction before delete                             |
| Working tree = active | prefs / design / estimation match active scenario              |
| No Generate in loop   | Mark stale via re-entry; user confirms                         |

These rules restate the canonical contract in
`references/vendored/workshop/workshop-invariants.md` (vendored from
`skills/shared/workshop/workshop-invariants.md`, kept byte-identical by
`shared:sync`). When this table and that file disagree, the invariants
file wins — fix this table.

## Decline without entering

When Estimate offer **[B] Proceed to the decision** is chosen, do not enter
this phase's fragments — mark `phases.workshop` `"completed"` (resolved/
declined) per sidebar semantics in `INTERPRETER.md`, then present the
**Decision gate** (`estimate-assemble.md` § "Post-Estimate: Decision Gate").
`current_phase` stays `"estimate"` — the gate, not this decline path, sets the
next state from the user's A/C choice.
