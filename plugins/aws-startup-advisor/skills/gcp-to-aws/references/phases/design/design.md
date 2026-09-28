# Phase 3: Design AWS Architecture (Orchestrator)

**Execute ALL steps in order. Do not skip or optimize.**

## Prerequisites

1. Read `$MIGRATION_DIR/.phase-status.json`. If missing, invalid, or `phases.clarify` is not exactly `"completed"`: **STOP**. Output: "Phase 2 (Clarify) not completed or phase state is missing/invalid. Run `references/phases/clarify/clarify.md` until Clarify finishes and `.phase-status.json` shows `phases.clarify`: `completed`."
2. Read `$MIGRATION_DIR/preferences.json`. If missing: **STOP**. Output: "Phase 2 (Clarify) not completed. Run Phase 2 first."

Check which discovery artifacts exist in `$MIGRATION_DIR/`:

- `gcp-resource-inventory.json` (IaC discovery ran)
- `gcp-resource-clusters.json` (IaC discovery ran)
- `billing-profile.json` (billing discovery ran)
- `ai-workload-profile.json` (AI workloads detected)

If **none** of these artifacts exist: **STOP**. Output: "No discovery artifacts found. Run Phase 1 (Discover) first."

## Routing Rules

### Infrastructure Design (IaC-based)

IF `gcp-resource-inventory.json` AND `gcp-resource-clusters.json` both exist:

→ Load `design-infra.md`

Produces: `aws-design.json`

### Billing-Only Design (fallback)

IF `billing-profile.json` exists AND `gcp-resource-inventory.json` does **NOT** exist:

→ Load `design-billing.md`

Produces: `aws-design-billing.json`

### AI Workload Design

IF `ai-workload-profile.json` exists:

→ Load `design-ai.md`

Produces: `aws-design-ai.json`

### Mutual Exclusion

- **design-infra** and **design-billing** never both run (billing-only is the fallback when no IaC exists).
- **design-ai** runs independently of either design-infra or design-billing (no shared state). Run it after the infra/billing design completes.

## Phase Completion

Before marking Design complete, enforce route output gates (fail closed):

1. Determine which design routes ran:
   - IaC route: `gcp-resource-inventory.json` AND `gcp-resource-clusters.json` exist
   - Billing-only route: `billing-profile.json` exists AND `gcp-resource-inventory.json` does NOT exist
   - AI route: `ai-workload-profile.json` exists
2. Require at least one route to be active. If none active: STOP.
3. For each active route, require its expected artifact:
   - IaC route -> `aws-design.json`
   - Billing-only route -> `aws-design-billing.json`
   - AI route -> `aws-design-ai.json`
4. If any active route is missing its expected output: STOP and output: "Design route [name] did not produce required artifact(s). Re-run the failed sub-design before completing Phase 3."

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** each active route artifact before checking.

**Re-entry guard:** If `estimation-infra.json` (or sibling estimate artifacts) exists and `phases.estimate` is `"completed"`: STOP unless the user explicitly confirms re-running Design. Emit `GATE_FAIL | phase=design | field=estimation-infra.json | reason=stale_downstream`.

**On any route gate FAIL:** Emit `GATE_FAIL | phase=design | field=<artifact> | reason=missing`. **Do NOT modify artifacts to pass the gate.** **Do NOT update `.phase-status.json`.**

**On PASS:** Emit `HANDOFF_OK | phase=design | artifacts=<comma-separated active design files>`.

### Inner workshop reprice — skip state transition

When Design is invoked from `workshop-refresh.md` (inner reprice): rewrite the
active design artifact(s) (`aws-design.json` and siblings as applicable), then
**return to the workshop loop**. Do **not** emit `HANDOFF_OK`, do **not** set
`phases.design` to `"in_progress"` or re-stamp `"completed"`, do **not** change
`current_phase`, and do **not** treat Estimate as stale for a Generate reset
unless the user is already past Generate (see workshop-refresh stale-Generate
guard). Leave `phases.design` and `phases.estimate` as `"completed"` and
`current_phase` at `"estimate"` while `phases.workshop` is `"in_progress"`.

### Design summary card (outer runs only — before the phase-status update)

After outer-run `HANDOFF_OK`, present a compact card built from the design artifact(s) so the user sees what Design decided before costs arrive. Chat only — not a file:

```
### Your AWS architecture at a glance

| GCP service | AWS target | How we chose this |
| ----------- | ---------- | ----------------- |
| [top 3-5 PRIMARY mappings] | [aws_service] | [Standard pairing / Tailored to your setup / Estimated from billing only] |

[If any resource is "Deferred — specialist engagement":]
Deferred (specialist engagement): [service names] — excluded from automated design and estimated AWS monthly run rate.

What Estimate answers next: your GCP baseline vs estimated AWS monthly cost
(three scenarios), per-service breakdown, and the migrate/stay recommendation.
```

Use the user-facing vocabulary from `design-refs/fast-path.md` for "How we chose this" (**Standard pairing** / **Tailored to your setup** / **Estimated from billing only**) — never raw `deterministic`/`inferred` enum values. Cap the table at 5 rows ("+ N more in the design artifact"). Skip this card entirely on inner workshop reprices.

After the card, use the Phase Status Update Protocol
(read-merge-write) to update `.phase-status.json` — **in the same turn** as the
output message below:

- Set `phases.design` to `"completed"`
- Set `current_phase` to `"estimate"`

Output to user: "Phase 3 of 6 complete (Design). AWS architecture designed. Remaining: Estimate → Generate (+ optional Feedback). Next artifact: estimation-infra.json (and estimation-ai.json for AI workloads). Proceeding to Phase 4: Estimate Costs."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._

## Reference Files

Sub-design files may reference rubrics in `design-refs/`:

- `design-refs/index.md` — GCP type → rubric file lookup
- `design-refs/fast-path.md` — Direct (table) mappings vs rubric path; **User-facing vocabulary** for presenting `confidence` to users (**Standard pairing** / **Tailored to your setup** / **Estimated from billing only**)
- `design-refs/compute.md` — Compute service rubric
- `design-refs/elastic-beanstalk.md` — Elastic Beanstalk reference (App Engine, managed platform)
- `design-refs/database.md` — Database service rubric
- `design-refs/storage.md` — Storage service rubric
- `design-refs/networking.md` — Networking service rubric
- `design-refs/messaging.md` — Messaging service rubric
- `design-refs/ai.md` — AI/ML service rubric

## Scope Boundary

**This phase covers architecture mapping ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Cost calculations or pricing estimates
- Execution timelines or migration schedules
- Terraform or IaC code generation
- Risk assessments or rollback procedures
- Team staffing or resource allocation

**Your ONLY job: Map GCP resources to AWS services. Nothing else.**
