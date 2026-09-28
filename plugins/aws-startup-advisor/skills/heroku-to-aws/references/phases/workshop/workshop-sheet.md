---
_fragment: sheet
_of_phase: workshop
---

# Workshop — Assumption Sheet

> Confirm-first sheet (GCP assumption-sheet UX). Not a full Clarify re-interview.
> Non-listed preferences stay frozen.

## Step 1: Read current knobs

From `$MIGRATION_DIR/preferences.json`:

| Knob              | Path                                        | Allowed values                                                                                |
| ----------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Target region     | `global.target_region`                      | Valid AWS region code                                                                         |
| Availability      | `global.availability`                       | `single-az`, `multi-az`, `multi-az-ha`, `multi-region` (as used by Clarify)                   |
| Database HA       | `data.database_ha`                          | Same family; omit row if key absent (no Postgres)                                             |
| Redis HA          | `data.redis_ha`                             | As Clarify; omit row if key absent                                                            |
| Compute target    | `design_constraints.compute_target.default` | `elastic_beanstalk`, `ecs-fargate`, `eks-managed`, `eks-or-ecs` — keep existing `overrides[]` |
| Cost optimization | `operational.cost_optimization`             | `conservative`, `balanced`, `aggressive`                                                      |
| CPU architecture  | `workshop.cpu_architecture`                 | `x86_64` (default if missing), `arm64`                                                        |

## Step 2: Present the sheet

Lead with:

> **What-if workshop** — discovery is frozen. Edit assumptions to reprice.
> Generate/Terraform will be marked stale if you continue after Generate already ran.

Show a compact table of knob → current value. Invite edits (confirm-or-change per
row). Do not re-ask DNS, VPC, migration method, Fir intent, or other Clarify
fields here.

**Region / pricing honesty (always show under the table):**

> Region repricing uses the us-east-1 pricing cache (see any `region_note` on the
> estimate for qualitative regional notes). Arch, HA, and compute knobs reprice from
> cache/design tables.

Actions (exactly one):

- **[A] Apply & reprice** — patch knobs and refresh Design + Estimate
- **[B] Compare scenarios** — show side-by-side without changing knobs
- **[C] Exit to Generate** — leave workshop with the active scenario
- **[D] Exit to full Clarify** — danger path; confirm before Clarify re-entry

## Step 3: Validate edits (Apply path only)

Before refresh:

1. `global.target_region` is a non-empty AWS region code.
2. `global.availability` is one of the allowed values.
3. If `data.database_ha` / `data.redis_ha` present, values are recognized.
4. `design_constraints.compute_target.default` is one of the four compute targets.
5. `workshop.cpu_architecture` is `x86_64` or `arm64`.
6. Do not strip `compute_target.overrides[]` unless the user explicitly cleared them.

On validation failure: show the error, re-present the sheet — do not Design.
