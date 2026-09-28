---
_fragment: sheet
_of_phase: workshop
---

# Workshop — Assumption Sheet

> **Fragment unit.** See `workshop.md` for how it is composed into the sidebar.

Presents the current assumptions as an editable sheet and collects the user's
changes. It writes no artifact of its own — the scenario snapshot is the refresh
fragment's job, and the index is the assembler's — which is why it declares no
`_contributes`.

Knobs: region, HA posture, compute target, cost-optimization appetite, CPU
architecture. Each row shows the current value and where it came from (a Clarify
answer, a detected fact, or a skill default), so the user can see what they are
overriding.

## Step 1: Read current knobs

From `$MIGRATION_DIR/preferences.json`:

| Knob              | Path                                         | Allowed values                                                     |
| ----------------- | -------------------------------------------- | ------------------------------------------------------------------ |
| Target region     | `global.target_region.value`                 | Valid AWS region code                                              |
| HA posture        | `data.availability.value`                    | `single-az`, `multi-az`, `multi-az-ha`, `multi-region`             |
| Compute target    | `design_constraints.compute_target.value`    | `elastic_beanstalk`, `ecs-fargate`, `eks` — omit row if key absent |
| Cost optimization | `design_constraints.cost_optimization.value` | `conservative`, `balanced`, `aggressive`                           |
| CPU architecture  | `design_constraints.cpu_architecture.value`  | `x86_64`, `graviton` — omit row if key absent                      |

When patching wrapper objects, preserve `chosen_by`, `prompt`, and
`design_consequence` (set `chosen_by` to `"user"` on edit). Prefer the catalog
prompts from `schema-preferences.md` / the canonical question files under
`references/vendored/clarify/` when present on the wrappers — do not invent
placeholder prompts.

### Graviton default note (CPU architecture row)

This skill defaults `cpu_architecture` to `x86_64`, not Graviton (see SKILL.md §
Philosophy) — Azure fleets carry Windows and .NET routinely, and Graviton
compatibility is the exception here rather than the rule. When presenting the
CPU architecture row:

- If `design_constraints.cpu_architecture.forced_by` is set (a Windows VM or
  App Service Plan forced `x86_64`), show that row as **not editable** — name
  the forcing resource and do not offer Graviton as an option for it. Forced
  rows do not participate in the what-if sheet the way PROPOSED rows do.
- Otherwise present both options, with the row's current value (whatever
  Clarify recorded — DETECTED, PROPOSED, or user-corrected) as the starting
  point, and the ~15–20% hourly savings figure as the incentive to switch.
- **Do not silently imply Graviton is safe estate-wide** just because one
  service is eligible — a mixed estate needs the same per-service caveat GCP's
  sheet gives, worded for Azure's forcing conditions (Windows, .NET Framework,
  GPU/CUDA workloads, RDS SQL Server) instead of GCP's `graviton_profile[]`
  risk-signal tiers.

## Step 2: Present

Lead with:

> **What-if workshop** — discovery is frozen. Edit assumptions to reprice.
> Generate/Terraform will be marked stale if you continue after Generate already ran.

Show knob → current value. Invite confirm-or-change per row.

**Region / pricing honesty:**

> Region repricing uses the us-east-1 pricing cache; regional deltas are noted
> qualitatively.

Actions (exactly one):

- **[A] Apply & reprice**
- **[B] Compare scenarios**
- **[C] Done — back to the decision gate** (choose "done for now" or "generate scripts" there)
- **[D] Exit to full Clarify** (danger — confirm first)

## Step 3: Validate (Apply only)

1. Region is a non-empty AWS region code.
2. HA posture is one of the allowed values.
3. Compute target / cpu_architecture values are recognized when present.
4. A forced `cpu_architecture` row (`forced_by` set) cannot be overridden to
   Graviton through the sheet — reject the edit and re-show the row with its
   forcing reason, the same way Clarify itself would.
5. Do not invent VM-cutover or licensing knobs on this sheet — those are
   one-time migration-runbook decisions from Clarify, not cost-shaping knobs
   this sidebar reprices.

On failure: re-present the sheet — do not run Design.
