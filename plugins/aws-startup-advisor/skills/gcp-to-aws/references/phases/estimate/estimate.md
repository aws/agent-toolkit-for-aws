# Phase 4: Estimate AWS Costs (Orchestrator)

**Execute ALL steps in order. Do not skip or optimize.**

## Step 0: Pricing Mode Selection

Before running any sub-estimate file, determine the pricing source.

### Step 0a: Load Pricing Cache

Read `shared/pricing-cache.md`. Check the `Last updated` date in the header:

- If <= 90 days old: **Cached prices are the primary source.** No MCP calls needed for services listed in the cache. Proceed to Step 1.
- If > 90 days old: Cache is stale. There is no live pricing lookup to fall back to — keep using the cached rates, widen the stated accuracy band, and surface the staleness warning in Step 0b.

### Step 0b: Surface Status to User (ALWAYS run)

**Before any sub-estimate file runs**, display the pricing mode to the user so they know what to expect:

- **If cache ≤ 90 days**: "Pricing source: cached (updated [date], ±5-25% accuracy). No live pricing API required."
- **If cache > 90 days**: "⚠️ Pricing source: stale cache only (updated [date]). Proceeding with cached pricing; accuracy may be ±15-25% for AI models."
- **If a required service is NOT in cache**: "⚠️ Some services not in pricing cache. Those services will show `pricing_source: unavailable` in the estimate."

This prevents silent failures — the user sees the pricing constraint upfront, not after 5 minutes of estimation work.

### Pricing Hierarchy

Each sub-estimate file uses this lookup order per service:

1. **`shared/pricing-cache.md`** (primary) — Cached prices (±5-25% accuracy). Set `pricing_source: "cached"`. Used first because it requires zero API calls and covers most common services.
2. **Unavailable** — If a service is NOT in the cache, set `pricing_source: "unavailable"` for that service. Add the service to `services_with_missing_fallback` and display a warning to the user: "Pricing unavailable for [service] — not in cache. Exclude from totals or provide a manual estimate."

**`pricing_source` values summary:**

| Value           | Meaning                                    |
| --------------- | ------------------------------------------ |
| `"cached"`      | Found in pricing-cache.md (normal path)    |
| `"unavailable"` | Not in cache; service excluded from totals |

If cache is > 90 days old:

- Add warning: "Cached pricing data is >90 days old; accuracy may be significantly degraded"
- **Display to user**: Add visible warning with staleness notice

## Step 1: Prerequisites

1. Read `$MIGRATION_DIR/.phase-status.json`. If missing, invalid, or `phases.clarify` is not exactly `"completed"`: **STOP**. Output: "Phase 2 (Clarify) not completed or phase state is missing/invalid. Complete Clarify before Estimate."
2. Read `$MIGRATION_DIR/preferences.json`. If missing: **STOP**. Output: "Phase 2 (Clarify) not completed. Run Phase 2 first."

Check which design artifacts exist in `$MIGRATION_DIR/`:

- `aws-design.json` (infrastructure design from IaC)
- `aws-design-ai.json` (AI workload design)
- `aws-design-billing.json` (billing-only design)

If **none** of these artifacts exist: **STOP**. Output: "No design artifacts found. Run Phase 3 (Design) first."

## Step 2: Routing Rules

### Infrastructure Estimate

IF `aws-design.json` exists:

> Load `estimate-infra.md`

Produces: `estimation-infra.json`

### Billing-Only Estimate

IF `aws-design-billing.json` exists AND `aws-design.json` does **NOT** exist:

> Load `estimate-billing.md`

Produces: `estimation-billing.json`

### AI Estimate

IF `aws-design-ai.json` exists:

> Load `estimate-ai.md`

Produces: `estimation-ai.json`

### Mutual Exclusion

- **estimate-infra** and **estimate-billing** never both run (billing-only is the fallback when no IaC exists).
- **estimate-ai** runs independently of either estimate-infra or estimate-billing (no shared state). Run it after the infra/billing estimate completes.

## Phase Completion

Before marking Estimate complete, enforce route output gates (fail closed):

1. Determine which estimate routes ran:
   - Infra route: `aws-design.json` exists
   - Billing-only route: `aws-design-billing.json` exists AND `aws-design.json` does NOT exist
   - AI route: `aws-design-ai.json` exists
2. Require at least one route to be active. If none active: STOP.
3. For each active route, require its expected artifact:
   - Infra route -> `estimation-infra.json`
   - Billing-only route -> `estimation-billing.json`
   - AI route -> `estimation-ai.json`
4. If any active route is missing its expected output: STOP and output: "Estimate route [name] did not produce required artifact(s). Re-run the failed sub-estimate before completing Phase 4."

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** each active estimate artifact before checking.

**Re-entry guard:** If `generation-infra.json` (or sibling generation artifacts) exists and `phases.generate` is not `"pending"`: STOP unless the user explicitly confirms re-running Estimate. Emit `GATE_FAIL | phase=estimate | field=generation-infra.json | reason=stale_downstream`.

**Infra route additional checks** (when `estimation-infra.json` exists):

- `recommendation.path` ∈ `{migrate_optimized, migrate_phased, stay}`
- `recommendation.path_label` is non-empty
- `recommendation.migrate_if` and `recommendation.stay_if` are non-empty arrays

**On any FAIL:** Emit `GATE_FAIL | phase=estimate | field=<path> | reason=missing`. **Do NOT modify artifacts to pass the gate.** **Do NOT update `.phase-status.json`.** Tell the user to re-run `estimate-infra.md` Part 7 (recommendation block).

**On PASS:** Emit `HANDOFF_OK | phase=estimate | artifacts=<comma-separated active estimate files>`.

### Inner workshop reprice — skip state transition

When Estimate is invoked from `workshop-refresh.md` (inner reprice): write the
estimate artifact(s), present a brief summary, then **return to the workshop
loop**. Do **not** emit `HANDOFF_OK`, do **not** update `.phase-status.json`, do
**not** offer the what-if workshop below.

### Outer Estimate — Decision gate

After outer-run `HANDOFF_OK`, use the Phase Status Update Protocol
(read-merge-write) — **in the same turn** as the summary:

1. Set `phases.estimate` to `"completed"`
2. Ensure `phases.workshop` exists (seed `"pending"` if missing)
3. **Do not** set `current_phase` to `"generate"` — Generate is opt-in from
   here on. Leave `current_phase` at `"estimate"` and present the Decision
   gate below.

### Post-Estimate: Decision Gate

**The decision is the product; execution artifacts are opt-in.** The verdict
(`recommendation.outcome` / `path`) already exists in the estimate artifacts —
present it and let the user choose what happens next. Never advance to
Generate without an explicit choice of option C (or an explicit later request
for Terraform/scripts).

Present (values from the active estimate artifacts; one line each):

```
Phase 4 of 6 complete (Estimate). Remaining: Generate (+ optional Feedback).

### Decision pack ready

- Verdict: [outcome_label when recommendation.outcome exists; else path_label]
- AWS estimate (Balanced): $[X]/mo · Your GCP baseline: [figure with its
  baseline-quality label from estimate-infra.md Part 1 — apply the
  not-comparable rule when the sources measure different things]
- Timeline if you execute: ~[N–M] weeks ([complexity tier], from
  shared/migration-complexity.md — omit this line when no tier signal exists)
- Deferred to specialists: [BigQuery / other deferred rows, or omit line]

[A] Done for now — I have what I need to decide
[B] Explore what-ifs — reprice scenarios side by side (~1 min each): region,
    single-AZ database, EKS vs Fargate, Graviton
[C] Generate Terraform and migration scripts
```

**Data-justified scenario hint (add one line when applicable):** if a material
assumption was defaulted rather than confirmed — most commonly `availability`
(Multi-AZ, ~2x database cost) — append: "Suggestion: we assumed [assumption];
comparing a [alternative] scenario would bound that assumption before you
commit." Suggest at most one.

**Choice handling:**

- **A** → Mark `phases.workshop` → `"completed"` (declined). Then:
  1. **Render the decision pack:** load `references/shared/report-decision-core.md`
     and render it in **decision** mode — write
     `$MIGRATION_DIR/decision-report.html` and `$MIGRATION_DIR/DECISION.md`
     per that file's decision-mode rules (no appendices, no Terraform, CTA
     footer). Validate with
     `python3 "$PLUGIN_ROOT/scripts/validate-migration-report.py" "$MIGRATION_DIR/decision-report.html" --mode decision --migration-dir "$MIGRATION_DIR"`
     and pass `--estimation-infra` / `--estimation-ai` / `--aws-design` when
     those files exist so the Cost Optimization gate can fire
     (absolute paths — cwd must not be load-bearing) and fix failures before
     presenting. `--migration-dir` is required on a real run: it is how the
     validator finds `scenarios/index.json`, so the what-if column check
     (Region, HA, Compute, Arch, the three tiers, Complexity) fires when
     Workshop produced two or more scenarios before the user chose A.
  2. Set `run_mode: "decide"` and `current_phase: "complete"` in
     `.phase-status.json` (`phases.generate` **stays** `"pending"` — this
     combination means "decision complete, execution available on request";
     see `schema-phase-status.md`).
  3. **Write the web-handoff summary (fail-open):** run
     `python3 "$PLUGIN_ROOT/scripts/emit-plan-json.py" --migration-dir "$MIGRATION_DIR" --plugin-json "$PLUGIN_ROOT/.claude-plugin/plugin.json"`
     (absolute paths — cwd must not be load-bearing). It reads the estimate
     artifacts and writes `$MIGRATION_DIR/plan.json`, the uploadable handoff
     file, printing `PLAN_OK | …` or `PLAN_SKIP | reason=…`. This is an optional
     enhancement, never a gate: on any skip or error the decision is still
     complete — continue without it and do not surface the script output to the
     user.
  4. Run the post-gate feedback checkpoint per `SKILL.md`. Step 3 has already
     run, so you know its `PLAN_OK`/`PLAN_SKIP` status — author the close **once**
     with that knowledge, never as a two-pass edit of an already-shown message:
     - If step 3 printed `PLAN_SKIP` (no `plan.json`), close with:
       "Your decision report is saved at `decision-report.html` (plus a
       Slack-friendly `DECISION.md`). If you decide to migrate, say 'generate
       the Terraform and migration scripts' — everything is saved and I'll pick
       up from here."
     - If step 3 printed `PLAN_OK`, close with that same sentence and also name
       `plan.json` in it, with **AWS Startups Migrate** as a Markdown link (the
       close is prose, so a link renders here, unlike the fenced Generate
       produced-list). Substitute the run's `run_id` (from `.phase-status.json`),
       lowercased if it is a UUID — e.g. "Your decision report is saved at
       `decision-report.html` (plus a Slack-friendly `DECISION.md`), and your
       uploadable plan at `plan.json` — upload it to
       [AWS Startups Migrate](https://startups.aws.com/startups/en-US/migrate/credits?source=plugin&run=<run_id>)
       for up to $1,500 in credits. If you decide to migrate, say 'generate the
       Terraform and migration scripts' — everything is saved and I'll pick up
       from here." The `plan.json` filename appears in EXACTLY ONE place — this
       close — and NEVER in the What's next block below.
  5. **Web-handoff — only when step 3 printed `PLAN_OK`** (if it printed
     `PLAN_SKIP`, omit this whole block; there is no file to upload). Append the
     What's next block below, verbatim, replacing `<run_id>` in the link with the
     run's `run_id` (from `.phase-status.json`), lowercased if it is a UUID so the
     `run=` value matches the plan's `runId`. It MUST begin with the "💬 What's
     next" heading — do NOT add a `plan.json` line (or any file line) above or
     inside it. The call-to-action must be a Markdown link so it renders as
     clickable text with no bare URL. Do not reword it — this copy is owned by the
     web experience:

     > **💬 What's next**
     >
     > - **Refine your plan**
     >   Tell me what to change. For example: "use Fargate instead," "make it multi-region," or "reduce the cost."
     > - **Claim your credits**
     >   When you're happy with your plan, upload it below to apply for up to $1,500 in AWS migration credits.
     >
     > [🎉 Get up to $1,500 in AWS migration credits →](https://startups.aws.com/startups/en-US/migrate/credits?source=plugin&run=<run_id>)
     >
     > Upload your plan to AWS Startups Migrate to see what you qualify for and unlock:
     >
     > - Interactive plan dashboard
     > - Monthly cost estimate
     > - Migration paths: AI Agent, AWS Expert, or AWS Partner
     > - Up to $1,500 in AWS migration credits

     Ship note: this reaches customers only after the import page and the
     ImportPlan API are both live in production.
- **B** → Load `references/phases/workshop/workshop.md`. Keep
  `current_phase: estimate`; set `phases.workshop` → `"in_progress"`. On
  workshop exit, **return to this gate** (options A and C; the workshop's
  active scenario carries into either) — do not advance to Generate directly.
- **C** → Mark `phases.workshop` → `"completed"` (declined). Set
  `run_mode: "decide_and_execute"` and `current_phase` → `"generate"`. Then
  run the post-gate feedback checkpoint per `SKILL.md` and continue to
  Generate.

For AI-only / billing-only runs (no infra inventory), present the gate without
option B and set `phases.workshop` → `"completed"`. Prefix the presented gate
with the same breadcrumb line: "Phase 4 of 6 complete (Estimate). Remaining:
Generate (+ optional Feedback)."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._

## Reference Files

- `shared/pricing-cache.md` — Cached AWS + source provider pricing (±5-25%, primary source)

## Scope Boundary

**This phase covers financial analysis ONLY.**

**Cost labeling rule (applies to ALL sub-estimate files):** All dollar figures presented to the user in chat summaries, report tables, and metric boxes MUST be labeled as "estimated monthly costs" or prefixed with "Est." — never present raw dollar amounts as if they are exact. This includes the Present Summary output, migration report content, and any user-facing cost references.

FORBIDDEN — Do NOT include ANY of:

- Changes to architecture mappings from the Design phase
- Execution timelines or migration schedules — **exception:** the Decision gate's one-line timeline band (`~N–M weeks`, tier from `shared/migration-complexity.md`) is allowed; full schedules, week-by-week plans, and runbooks remain Generate-only
- Terraform or IaC code generation
- Detailed migration procedures or runbooks
- Team staffing or resource allocation

**Your ONLY job: Show the financial picture of moving to AWS. Nothing else.**
