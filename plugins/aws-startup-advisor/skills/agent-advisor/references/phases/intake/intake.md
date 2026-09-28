---
_phase: intake
_title: "Intake — Entry Point + Background"
_init: true
_input: workspace
_assemble:
  _file: phases/intake/intake-assemble.md
_produces:
  - .phase-status.json
_advances_to: discover
_postconditions:
  - _check_file_exists: .phase-status.json
    _on_failure: _halt_and_inform
  - _validate_json: .phase-status.json
    _on_failure: _halt_and_inform
  - _assert: "the .phase-status.json written by Step 5 has entry_point and audience set, intake = completed, and all later phases set to pending or skipped per the entry point"
    _on_failure: _halt_and_inform
---

# Phase: Intake — Entry Point + Background

## Step 1 — Create the run directory

Generate a run id from the current time as `MMDD-HHMM`. Create the run directory under the
**user's current working directory** (run `pwd` and anchor to it) — NOT the plugin install tree.
So: `<cwd>/.agent-advisor/<run_id>/`, plus `<cwd>/.agent-advisor/.gitignore` containing `*` (so
run state is never committed). All later `$RUN_DIR` references point here.

## Step 1.5 — Temporal signal recognition

If the opening message carries a Temporal signal (mentions Temporal, Temporal Cloud,
Temporal workers, `temporalio` / `go.temporal.io` / `@temporalio` / `temporal-sdk`),
acknowledge it in one line and record the signal in `$RUN_DIR/context-notes.md`. A Temporal
migration routes into the normal flow with `migrate` as the entry point (pre-select it in
Q1 when intent is explicit, still confirmable).

**No-code path seeding:** when the Temporal signal fires AND the user does not provide a code
path (no directory offered in Step 4), additionally SEED declared temporal units in
`$RUN_DIR/context-notes.md`: one `temporal_worker_poll` unit (`source: "declared"`,
`trigger: "temporal"`) plus a temporal context stub
`{ "detected": true, "server": "unknown", "source": "declared" }`, and note that Activity
classes will be established by interview in Clarify.

Continue to Step 2.

## Step 2 — Ask two questions with AskUserQuestion

Ask BOTH in one AskUserQuestion call (two questions):

**Q1 — Starting point** (header "Starting point"):

- Build from scratch — I have an idea, no code → `build_scratch`
- Deploy existing code — I have working agent code → `build_deploy`
- Migrate — I have agents running elsewhere → `migrate`
- Add capabilities — already on AWS, want to add services → `add_capabilities`

**Q2 — Your background** (header "Background"):

- Technical (engineer/developer) → `technical`
- Business-leaning (founder/PM/non-technical) → `business`
- Mixed team → `business` (start in business language, add technical detail on request)

## Step 3 — Handle add_capabilities

If Q1 == add_capabilities: this is a self-contained branch of THIS skill. Set `entry_point =
add_capabilities` in `.phase-status.json` (Step 5), then load
`references/phases/add-capabilities/add-capabilities.md` and follow it. Do NOT continue into Discover / Clarify /
Design — the branch runs its own 5-step flow and ends by writing
`capabilities-recommendation.md`. (Per the state table, the `add_capabilities` row routes here
directly after intake.)

## Step 4 — Open context prompt

Ask (plain text): "What can you tell me about your agent — and is it one workload, or
several (e.g. an interactive agent plus a batch job)? If several, do they interact? How
is each one triggered (user request, event/queue, cron/schedule)? Any files or existing
code to share? (Optional — say 'skip' to move on.)" Capture any framework/model/infra
hints into `$RUN_DIR/context-notes.md`. If the user names several workloads, record a
draft `units` list in context-notes.md (one line per unit: proposed kebab-case id,
`workload_class` guess from the closed vocabulary defined in
`references/phases/discover/discover.md` — `agent_session` | `batch` | `light_io` |
`service` — `trigger` guess from the closed vocabulary (`request` | `event` | `schedule` |
`temporal` | `unknown`), and interaction). Single-workload answers record nothing extra
(collapse invariant — no new question turn either way; this rides the existing question).

**Exception — a Temporal signal ALWAYS records a draft, even for a single workload.** If the
answers mention Temporal (workers, task queues, Activities, Workflows, `*.tmprl.cloud`), record a
draft `units` list regardless of unit count, and it MUST include a `temporal_worker_poll` unit
plus a line per Activity-execution class the user describes. Do not collapse a Temporal workload
to "nothing extra" — the polling tier and the Activity classes are what Clarify's Temporal
interview and scope gate need; losing them silently drops Tier 1 polling and the orchestration
decision.

For `build_deploy` / `migrate`, **explicitly ask for the code path** ("Where's your agent code?
A directory path lets me detect your framework/model and skip questions."). Discover runs only
if a path is given; if the user declines a path, note it and set `discover = skipped` in Step 5.

## Step 5 — Write state

Write `$RUN_DIR/.phase-status.json` with `entry_point`, `audience` (from Q2), `intake` =
completed. Set `discover` = pending if entry point is build_deploy/migrate AND the user
offered a code path, else `skipped`. Set all later phases (`clarify`, `model-recommend`,
`confirm`, `design`, `estimate`, `generate`) to pending.

## Step 2 amendment — target maturity

Ask **Q3 — Target maturity** in the same AskUserQuestion call unless a valid run seed supplies `target_maturity`: Prototype → `prototype`; Private beta → `private_beta`; Production → `production`. Persist the selected value as top-level `target_maturity` in `.phase-status.json`. Do not infer this value from a runtime or a successful deployment.
