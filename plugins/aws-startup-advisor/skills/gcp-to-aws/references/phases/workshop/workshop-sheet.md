# Workshop — Assumption Sheet (GCP)

> Confirm-first sheet (same UX as Clarify's Assumption-Sheet Wizard, but **post-
> Estimate** and limited to cost-shaping knobs). Not a full Clarify re-interview.

## Step 1: Read current knobs

From `$MIGRATION_DIR/preferences.json`:

| Knob                 | Path                                        | Allowed values                                                      |
| -------------------- | ------------------------------------------- | ------------------------------------------------------------------- |
| Target region        | `design_constraints.target_region.value`    | Valid AWS region code                                               |
| Availability         | `design_constraints.availability.value`     | `single-az`, `multi-az`, `multi-az-ha`, `multi-region`              |
| Kubernetes / compute | `design_constraints.kubernetes.value`       | `eks-managed`, `eks-or-ecs`, `ecs-fargate` — omit row if key absent |
| CPU architecture     | `design_constraints.cpu_architecture.value` | `graviton`, `x86`, `mixed` — omit row if key absent                 |

When patching wrapper objects, preserve `chosen_by`, `prompt`, and
`design_consequence` (set `chosen_by` to `"user"` on edit). Prefer the catalog
prompts from `schema-preferences.md` / Q11b text from `clarify-compute.md` when
present on the wrappers — do not invent placeholder prompts.

### Graviton evidence (CPU architecture row)

Read `graviton_profile[]` from discovery artifacts (`gcp-resource-inventory.json`
and/or `ai-workload-profile.json` / merged discover outputs — wherever Discover
wrote the array). Count entries whose `tier` is `incompatible`, `conditional`,
or `unknown` (risk-signal tiers per `clarify-compute.md` Q11b).

When presenting the CPU architecture row:

- If any risk-signal tiers exist, **always** show a one-line caveat under the
  row, e.g.:
  > 2 entries are Graviton-incompatible / conditional — choosing `graviton`
  > applies where `tier: ready`; incompatible entries stay x86 (same semantics
  > as Clarify Q11b "all eligible"). Prefer `mixed` for an explicit split.
- Do **not** silently imply 100% Graviton savings when risk signals exist.
- SA may still pick `graviton` / `x86` / `mixed`; the caveat travels into the
  scenario label/note on Apply (see `workshop-refresh.md`).

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
2. Availability is one of the allowed values.
3. Kubernetes / cpu_architecture values are recognized when present.
4. Do not invent BigQuery warehouse targets or agentic migration_approach fields.

On failure: re-present the sheet — do not Design.
