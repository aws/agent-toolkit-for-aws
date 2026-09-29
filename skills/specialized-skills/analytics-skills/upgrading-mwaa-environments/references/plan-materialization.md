# Writing and Resuming the Upgrade Plan (Phase 4)

How to turn the chosen approach reference into a durable, resumable plan file,
and how to keep that file correct across the whole upgrade lifecycle: create it
(Phase 4), maintain it during execution (Phases 5-8), and reconcile it on resume
(Phase 0). These sections are what survives context compaction and what Phase 0
resumes from.

## Write out every checkpoint and record-section into the plan (mandatory)

The plan is the durable, resumable source of truth: Phase 0 resumes from it,
and it is what survives context compaction. Any step that exists only as prose
in a approach reference — not as a discrete, tracked item in this plan — WILL
be skipped after compaction. A parse-clean signal (`has_import_errors: false`)
does NOT satisfy the test-run checkpoint and must never be recorded in a way
that reads as "validated" or "complete". Generate these sections BEFORE
presenting the plan for confirmation; do not defer their creation to execution
time.

**Compaction-survival rule for skill delegations:** When a step requires
invoking another skill (e.g., `testing-mwaa-workflow`, `debugging-mwaa-workflow`,
`authoring-mwaa-workflow`), the text you write for that step MUST include the
word "skill" and name that skill explicitly. After compaction, the original
approach reference text is gone — the plan file is the only artifact the agent
reads on re-entry. A step that says "Test-run checkpoint [PENDING]" will be
ad-hoc'd with manual REST API calls; a step that says "invoke skill
testing-mwaa-workflow (delegated mode) and not manual DAG run triggers
[PENDING]" will trigger the correct skill invocation. This applies to every
step that delegates to a skill, not just the test-run checkpoint.

Open the chosen approach reference now and enumerate (a) every numbered step,
(b) every step marked REQUIRED or flagged as a checkpoint, and (c) every `##`
record-section it names. Write each into the plan as a discrete PENDING,
trackable item. At minimum the generated plan MUST contain:

- A `## Checklist` section mirroring the chosen reference's numbered steps
  plus Phase 8, each with a status field. Flag every action that needs
  confirmation (deploy to your current environment, create-environment, each
  version jump, switchover, decommission) and every step labeled REQUIRED.
  **Multi-action steps must be decomposed** — see the approach-specific
  sub-step rules below.
- Every required checkpoint from the reference as its own PENDING entry. By
  approach: New-environment upgrade — Step 4-checkpoint (test-run the new
  environment); Rehearsed in-place upgrade — Step 1-checkpoint (test-run the
  test copy; a hard prerequisite for the live upgrade), Step 3 re-check your
  current environment (REQUIRED); Direct in-place upgrade — Step 1 extra
  confirmation checkpoint, Step 4 test-run your current environment.
- A pre-seeded `## Test-run results` section, with one row per deployed DAG in
  state `PENDING` (columns: DAG ID, run_id, State, Duration, Notes) and a
  header stating it is REQUIRED and must be all-SUCCESS or NEEDS-DECISION
  before switchover (New-environment upgrade) / before the live upgrade
  (Rehearsed in-place upgrade) / before marking complete (Direct in-place
  upgrade).
- The test-run checkpoint step in the Checklist MUST use this exact wording
  pattern (the location named varies by approach):
  - New-environment upgrade: `Test-run checkpoint: run DAGs on the new environment — invoke skill testing-mwaa-workflow (delegated mode) and not manual DAG run triggers [PENDING, REQUIRED CHECKPOINT]`
  - Rehearsed in-place upgrade: `Test-run checkpoint: run DAGs on the test copy — invoke skill testing-mwaa-workflow (delegated mode) and not manual DAG run triggers [PENDING, REQUIRED CHECKPOINT]`
  - Direct in-place upgrade: `Test-run checkpoint: run DAGs on your current environment — invoke skill testing-mwaa-workflow (delegated mode) and not manual DAG run triggers [PENDING, REQUIRED CHECKPOINT]`

  The word "skill" and the "not manual DAG run triggers" clause are not
  decorative — they are the re-entry instruction that survives compaction.
  Without them, a resuming agent will ad-hoc trigger-and-poll via the REST
  API instead of invoking the structured testing skill.
- For the New-environment upgrade, a `## Switchover progress` table
  pre-seeded with one row per batch and columns: Batch, Current environment
  paused, New environment unpaused, `Monitored one full cycle?`, Advanced. The
  plan must not advance a batch until its `Monitored one full cycle?` cell is
  yes. **The Rehearsed in-place upgrade has no switchover** — omit this table
  for it; use the batch table's per-DAG status for test-copy deployment
  tracking instead.
- A `## Where we are` block: `working_on`, `current_jump`, `jump_status`,
  `phase` (which of the skill's Phases 0–8 the upgrade is in),
  `test_run_checkpoint` (`NOT-PASSED` / `PASSED`). For the Rehearsed
  in-place upgrade, add `live_upgrade_allowed` — `yes` / `no` (`yes` only
  after the test-run checkpoint is `PASSED`) so a resuming agent cannot start
  the irreversible live upgrade on parse-only evidence.
- Phase 8 broken into discrete tracked items: `8.1: Batched switchover
  [PENDING]` (New-environment upgrade only), `8.2: Stability period
  [PENDING]`, `8.3: Decommission [PENDING, NEEDS CONFIRMATION]`. Do not track
  Phase 8 as a single line.

The batch table's status vocabulary MUST distinguish parse-clean from
test-run-verified. Use `LOADED` (uploaded, parses, zero import errors) as
distinct from `VERIFIED`; `LOADED` is never a completion state. For
multi-jump New-environment upgrade paths, add a `Deploy Phase` column
(`A: original` or `B: fixed`) to distinguish starting-version original DAGs
from post-target AF3-fixed DAGs — deploying Phase B code before the target
version jump completes causes `ModuleNotFoundError`.

## Approach-specific sub-step decomposition rules

Many numbered steps are multi-action procedures. If context compacts
mid-step, the plan must record which sub-actions completed. The Checklist
MUST decompose these steps into individually-tracked sub-items:

**New-environment upgrade:**

- Step 1 (create the new environment): track as `1a: create-environment` +
  `1b: poll AVAILABLE`. Do not proceed to Step 2 until status = AVAILABLE.
- Step 2 (Migrate Operational Metadata): track per-category: `Variables:
  [PENDING/SKIP/DONE]`, `Connections: [PENDING/SKIP/DONE]`, `Pools:
  [PENDING/SKIP/DONE]`. Pre-populate SKIP for categories handled by a secrets
  backend (detected in Phase 3 Step 4).
- Step 4 (Deploy Fixed DAGs): for multi-jump paths, split into `4A: Deploy
  original DAGs (starting-version validation)` and `4B: Deploy fixed DAGs
  (post-target)`. The batch table must record which deployment phase each DAG
  is in. AF3-only imports (`from airflow.sdk`) MUST NOT be deployed until the
  target version jump completes.

**Rehearsed in-place upgrade:**

- Step 1b (Migrate Operational Config): track as a discrete item with
  per-category status (same as the New-environment upgrade's Step 2). If
  skipped, the test run on the test copy fails with misleading "connection
  not found" errors unrelated to the version upgrade.
- Step 3 (Re-check your current environment): treat as REQUIRED. After the
  irreversible live upgrade, do not proceed to Step 5 (mark complete) without
  confirming your current environment is healthy (scheduler heartbeat
  advancing, no import errors).

**Direct in-place upgrade:** no additional decomposition required beyond the
existing Phase 4 mandate (Steps 1 and 4 are already individually tracked).

## Phase 5 decomposition (cross-major only)

When any version jump crosses into a new major version, Phase 5 (Fix Code)
must be written into the plan as individually-tracked sub-items in the
Checklist. The re-scan step is the critical one — `--unsafe-fixes` can
introduce runtime-breaking patterns (notably `_TaskDecorator.output`) that
are invisible to Ruff but cause `AttributeError` at parse time on the target
version. If context compacts before the re-scan runs, the plan must still
instruct the agent to perform it.

Write Phase 5 into the plan as:

```
- [ ] Phase 5: Fix Code (cross-major) [PENDING]
  - 5.0: Redesign metadata-DB-access DAGs (if any flagged in Phase 3):
    ORM-access DAGs to REST API; CLI-access DAGs to MWAA CLI endpoint
    (run `cheat-sheet` on target env to confirm command availability) [PENDING]
  - 5.1-N: Fix batch 1..N DAGs (Ruff --fix --unsafe-fixes + manual) [PENDING per batch]
  - 5.FINAL: Re-scan ALL fixed files for .output on @task refs + airflow db CLI
    (sections 15/16). MUST run AFTER all --unsafe-fixes and manual edits are
    complete. Grep patterns: `\.output` adjacent to @task-decorated function
    names, `airflow db` or `airflow CLI` in BashOperator strings. Any hits
    require a fix-and-re-verify cycle before proceeding to Phase 6/7. [PENDING]
```

The `5.FINAL` step is a required checkpoint: do not proceed to deployment
(Phase 7/8) until the re-scan is recorded as DONE with zero hits. Its
ordering constraint ("AFTER all --unsafe-fixes") must appear in the plan
text — without it, a resuming agent may run the re-scan before applying
fixes, get a clean result, and then introduce the very patterns the re-scan
was meant to catch.

## Plan format contract

The plan is parsed by the agent itself on resume, so its structure must be
predictable. Every plan MUST follow this contract.

- **Status vocabulary (fixed, no synonyms):** `PENDING`, `DONE`, `SKIP`,
  `DROPPED`, `LOADED` (uploaded + parses; not yet test-run), `VERIFIED` (test run
  passed), `NEEDS-DECISION` (blocked on an external/infra dependency or a user
  call), and for checkpoints `PASSED` / `NOT-PASSED`. Do not invent other status
  words (no "in progress", "partial", "done-ish").
- **`Last updated` line:** the first line after the plan title MUST be
  `Last updated: <UTC ISO-8601 timestamp> - <one-line what-changed>`, rewritten
  each time progress is saved. It is the freshness signal a resuming agent
  reads first.
- **`## Where we are` keys (fixed):** `working_on`, `current_jump`, `jump_status`,
  `phase` (which of the skill's Phases 0–8 the upgrade is in),
  `test_run_checkpoint` (`PASSED` / `NOT-PASSED`), and for the Rehearsed
  in-place upgrade `live_upgrade_allowed` — `yes` / `no` (`yes` only after the
  test-run checkpoint is `PASSED`).

## Saving progress (maintain the plan during execution)

After completing any tracked item - a step, sub-step, version jump,
checkpoint, batch, or per-DAG status - and BEFORE issuing the next action or
command, save that change to the plan file. Never batch plan updates. Saving
progress means updating three things together:

1. the item's status token (from the fixed vocabulary above);
2. any newly-discovered durable facts - run_ids, environment ARNs, S3 object
   versions, NEEDS-DECISION reasons, and decisions - recorded in the relevant
   table or section, not just held in context;
3. the `Last updated` line and the `## Where we are` block.

Recording durable facts (not only status flips) is what prevents detail - not
just progress - from being lost when context compacts. "Before the next
action" is what keeps multi-action steps (e.g. the rehearsal's
create/migrate/version-jump/deploy sub-steps) from drifting behind reality.

**Never write secret values into the plan.** The plan is a durable on-disk
artifact. Record connection/variable migration as status tokens only
(`PENDING`/`SKIP`/`DONE`); never store passwords, connection strings, variable
values, or connection `extra` contents in it. Reference secrets by key/name only.

## Self-consistency invariants

These invariants MUST always hold. A violation means the plan is mid-drift and
Plan Reconciliation (below) must run before any further action. They are written
against the plan's roles so they hold for every approach; the "test-run
checkpoint" is whichever checkpoint the chosen approach defines - the
New-environment upgrade's Step 4-checkpoint, the Rehearsed in-place upgrade's
Step 1-checkpoint, or the Direct in-place upgrade's Step 4.

| # | Invariant | Applies to |
|---|---|---|
| 1 | A checkpoint marked `PASSED` requires all its prerequisite `## Checklist` items to be `DONE` or `SKIP`. | New-environment upgrade, Rehearsed in-place upgrade, Direct in-place upgrade |
| 2 | `## Where we are`.test_run_checkpoint equals the aggregate of the `## Test-run results` table - any `PENDING` row means `NOT-PASSED`. | New-environment upgrade, Rehearsed in-place upgrade, Direct in-place upgrade |
| 3 | Every DAG the batch table shows deployed has a row in the `## Test-run results` table. | New-environment upgrade, Rehearsed in-place upgrade, Direct in-place upgrade |
| 4 | `current_jump` / `jump_status` match the Upgrade Path table's per-jump Status (for the Rehearsed in-place upgrade, whichever of the test-copy/current-environment columns applies to where you are). | New-environment upgrade, Rehearsed in-place upgrade, Direct in-place upgrade |
| 5 | No switchover batch is `Advanced` unless its `Monitored one full cycle?` cell is `yes`. | New-environment upgrade |
| 6 | `live_upgrade_allowed` is present and is `yes` only when `test_run_checkpoint` is `PASSED` (otherwise `no`). | Rehearsed in-place upgrade |

## Plan reconciliation on resume

At session start and after any compaction, re-read the entire plan file before
taking any action; never act on a remembered or summarized version. Then, before
resuming work, run this reconciliation:

1. Check every invariant above.
2. If all hold, resume at `## Where we are`.
3. If any invariant is violated, do NOT trust the plan to resolve itself -
   establish ground truth with read-only AWS calls:
   - `aws mwaa get-environment --name <env>` - does the env exist, at what
     version/status?
   - `aws mwaa invoke-rest-api --name <env> --method GET --path /dags`
     (paginate: loop `offset` by 100 until `total_entries`, per
     discovery-preflight.md Step 1.4) - are the DAGs deployed, and is
     `has_import_errors` false?
   - `aws mwaa invoke-rest-api --name <env> --method GET --path /health` -
     metadatabase/scheduler healthy, heartbeat advancing?
4. Repair the plan to match observed reality (correct the drifted
   statuses/checkpoint), and record what was repaired in the `Last updated`
   line.
5. If reality is genuinely ambiguous, surface it to the user - never guess.

A stale `PASSED` test-run checkpoint invites a different destructive next
action per approach; reconciliation guards each:

| Approach | Stale checkpoint would trigger next | Danger |
|---|---|---|
| New-environment upgrade | switchover batch + `delete-environment` on your current environment | destroys the live fallback |
| Rehearsed in-place upgrade | irreversible live upgrade on your current environment | upgrades your current environment on false evidence |
| Direct in-place upgrade | mark migration complete | declares success unvalidated |
