---
_phase: workshop
_title: "What-If Workshop (Optional)"
_kind: sidebar
_requires_phase: estimate
_gates: generate
_trigger:
  {
    _when: "user opts in post-Estimate (estimate-assemble offer [B], or says what if / reprice / workshop mode / compare scenarios)",
  }
_input:
  - azure-resource-inventory.json
  - preferences.json
  - aws-design.json
  - estimation-infra.json
_knowledge:
  - { file: references/shared/schema-workshop-scenarios.md }
  - { file: references/vendored/workshop/workshop-invariants.md }
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
        azure-resource-inventory.json,
        preferences.json,
        aws-design.json,
        estimation-infra.json,
      ]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: scenarios/index.json
    _on_failure: _warn_and_skip
  - _validate_json: scenarios/index.json
    _on_failure: _warn_and_skip
---

# Sidebar: What-If Workshop

## Orientation

Change an assumption, reprice, and compare — without re-running Discover. This is a
**sidebar**: off-backbone, entered only by its `_trigger`, and it returns control
rather than advancing. It never appears as `current_phase`.

`_gates: generate` means Generate must not start while this sidebar is unresolved.
Resolution includes a decline — a declined sidebar is still `"completed"`, because
`_gates` holds ordering, never participation. Whether the user actually engaged is a
separate signal, carried by whether `scenarios/index.json` exists.

The cross-skill invariants for the workshop live in
`references/vendored/workshop/workshop-invariants.md` and win on any disagreement
with the unit files here.

Knobs on the sheet: region, HA, compute target, cost optimization, CPU architecture.
**The architecture default is `x86_64`** here, matching the skill default rather than
the repo-wide Graviton default — see SKILL.md § Philosophy.

## Status — build step 6

Implemented. The knob set (region, HA posture, compute target, cost
optimization, CPU architecture), the Apply & reprice mechanics, the
comparison table, and the sidebar-resolve handoff back to the decision gate
are ported from `gcp-to-aws`'s equivalent, adapted to this skill's knobs and
its Premium/Balanced/Optimized scenario schema — see each fragment's own
Status note for what changed versus GCP's version.

## Step: Run the sidebar

1. Present the sheet (`workshop-sheet.md`).
2. On Apply & reprice, run `workshop-refresh.md`: patch preferences → re-run Design →
   re-run Estimate → snapshot the result as a scenario.
3. On Compare, or after a successful refresh, run `workshop-compare.md`.
4. Run `workshop-assemble.md` to resolve the sidebar and return control.
