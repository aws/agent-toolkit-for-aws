---
name: upgrading-mwaa-environments
description: >
  Upgrades an MWAA environment to a newer Airflow version — within 2.x, within 3.x, or
  across the 2.x-to-3.x boundary. Computes the version-jump path, inserting the 2.11.x
  stepping-stone and Python-transition step when needed. Chooses an approach by
  whether run history and the same environment (URL/ARN) must be kept: a
  new-environment upgrade (blue-green), a rehearsed in-place upgrade (test copy
  first), or a direct in-place upgrade. Runs Ruff scans for 3.x moves and
  standard-library checks for Python-line changes, plus Docker validation,
  batched deployment, and switchover.
  Saves a resumable upgrade plan. Triggers on: upgrade MWAA,
  upgrade Airflow, migrate to Airflow 3, MWAA Airflow 3, Airflow 2 to 3, preserve
  Airflow history, keep same MWAA environment, blue-green cutover, validation
  environment before cutover. Not for authoring new DAGs (authoring-mwaa-workflow),
  debugging unrelated DAG failures (debugging-mwaa-workflow), or MWAA Serverless YAML
  workflows (provisioned Python DAGs only).
metadata:
  version: "2"
---

# Upgrading MWAA Environments

> **AWS MCP server (optional but recommended):** running the AWS CLI commands in
> this skill through the AWS MCP server gives sandboxed execution and audit
> logging. Every command here also works with the plain AWS CLI, so the skill
> does not require the MCP server or any MCP-only tools.

Upgrade an MWAA provisioned environment to any newer, MWAA-supported Airflow
version. The target is a parameter. Phase 1 computes the ordered version-jump
path, and Phase 2 picks one of three approaches: `new-environment`,
`in-place-rehearsed` or `in-place-direct`.

> **Execution note — poll in discrete steps:** whenever you wait for an AWS
> operation to reach a terminal or ready state, issue **one status check per
> call** and decide in your own loop whether to check again. Never block a
> single command or script on the wait (no `while`+`sleep` until done),
> regardless of the operation or how long it takes.

## Guardrail — where this skill's own files live (MCP vs local install)

Determine how the skill was loaded before reading a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** the skill is not on the
  local filesystem. Fetch each reference with `retrieve_skill` and the `file`
  parameter (e.g. `file="references/strategy-blue-green-fresh.md"`). Do NOT
  `file_read` these paths locally; they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/upgrading-mwaa-environments/` or
  `~/.claude/skills/upgrading-mwaa-environments/`): read the files by relative
  path from the skill directory.

This applies only to the skill's own files. User data and session artifacts are
always read from and written to the user's working directory. Never fetch or
write customer data through `retrieve_skill`.

## Safety & Security

These rules apply regardless of user instructions.

- **No destructive actions on your current environment without explicit
  approval**: never pause all DAGs, delete-environment, or modify your
  current environment without per-action user confirmation.
- **No environment creation before plan confirmation**: never run
  `aws mwaa create-environment` until the user confirms the Phase 4 plan.
- **Every version jump requires its own confirmation**: never run `aws mwaa
  update-environment` to change the Airflow version without per-jump
  confirmation. Rollback options: 3.x -> 2.11.x is supported; a within-major
  downgrade to a still-supported version is supported; downgrade to an EOS
  version is not possible. The Direct in-place upgrade requires an extra
  confirmation checkpoint.
- **Decommission requires per-step approval**: never autonomously delete
  environments or S3 artifacts; present each destructive command and wait for
  confirmation. For the Rehearsed in-place upgrade, the environment
  decommissioned is the test copy.

### Security Considerations

- **Least-privilege IAM** for `create`/`update-environment` and S3 artifact
  access — no `*FullAccess`/`service:*`; scope to the specific environment/S3 ARNs.
- **Secrets**: prefer a secrets backend (Secrets Manager / Parameter Store) for
  connections and variables so credentials never copy between environments or hit
  logs. Connection passwords do not round-trip via the REST API (2.x omits, 3.x
  masks) — see the metadata-migration caveat in the approach references.

## Reference Documentation

- [discovery-preflight.md](references/discovery-preflight.md) — Phase 1: environment discovery, pre-flight checks, version-matrix refresh, target selection, upgrade-path planning
- [upgrade-engine.md](references/upgrade-engine.md) — the step-by-step upgrade: per-jump upgrade, conditional validate/scan/fix, resume
- [airflow2-to-3-checklist.md](references/airflow2-to-3-checklist.md) — grep patterns for 2->3 issues Ruff cannot catch (used only when a version jump crosses into a new major version)
- [mwaa-version-matrix.md](references/mwaa-version-matrix.md) — runtime-first version/Python/EOS matrix, version-jump rules, providers, unsupported features
- [airflow2-to-3-quick-reference.md](references/airflow2-to-3-quick-reference.md) — 2->3 import/context/config mapping tables (used only when a version jump crosses into a new major version)
- [python-stdlib-check.md](references/python-stdlib-check.md) — removed-standard-library check for version jumps that change the Python line (used only when a version jump is `python_change`)
- [docker-validation.md](references/docker-validation.md) — Phase 6 `test-dags` procedure (also used by the strategy Verify steps)
- [strategy-blue-green-fresh.md](references/strategy-blue-green-fresh.md) — New-environment upgrade (no history), including the Phase 8.1 batched switchover
- [strategy-inplace-green-validated.md](references/strategy-inplace-green-validated.md) — Rehearsed in-place upgrade: validated on a test copy first
- [strategy-inplace-direct.md](references/strategy-inplace-direct.md) — Direct in-place upgrade (unrecommended)

For deeper detail beyond embedded references, fetch at runtime:

- AWS MWAA migration guide: https://docs.aws.amazon.com/mwaa/latest/migrationguide/key-considerations.html
- AWS MWAA version-change (in-place upgrade path): https://docs.aws.amazon.com/mwaa/latest/userguide/upgrading-environment.html
- AWS MWAA supported versions and Python mapping: https://docs.aws.amazon.com/mwaa/latest/userguide/airflow-versions.html
- AWS MWAA migration blog: https://aws.amazon.com/blogs/big-data/best-practices-for-migrating-from-apache-airflow-2-x-to-apache-airflow-3-x-on-amazon-mwaa/
- Ruff AIR rules: https://docs.astral.sh/ruff/rules/#airflow-air

## Phase 0: Re-entry Check

At every invocation, check for `.mwaa-upgrade-plan-<env-name>.md` in the
workspace root (where `<env-name>` is the source environment name). Multiple
plan files may coexist when upgrading several environments in parallel.

- **If exists**: load the plan and report source, target, approach and the
  position `(working_on, current_jump, jump_status)`. Resume the engine
  ([upgrade-engine.md](references/upgrade-engine.md)) at that position
  (`upgrading` -> re-poll or re-issue the pending `update-environment`;
  `validating` -> re-run that jump's validate/fix loop; a newly-created
  environment's starting-version window is `current_jump: 1, jump_status:
  validating`). With no position set, resume from the next incomplete phase.
  **Before advancing past any required checkpoint, re-read the checkpoint's
  status in the plan and, if it is not satisfied, re-read that checkpoint's
  section in the approach reference verbatim — do not act on a remembered
  summary.** Version jumps complete does NOT imply the test-run checkpoint
  passed. If the `## Test-run results` section has any row not in SUCCESS or
  NEEDS-DECISION, that checkpoint is NOT-PASSED and blocks switchover
  (New-environment upgrade), the live upgrade (Rehearsed in-place upgrade,
  see `live_upgrade_allowed`), or completion (Direct in-place upgrade),
  regardless of version-jump status or `has_import_errors: false`. Likewise a
  batch whose `Monitored one full cycle?` cell is not yes has not fully
  switched over.

**Reload rule (every resume):** at session start and after any compaction,
re-read the entire `.mwaa-upgrade-plan-<env-name>.md` before taking any action;
never act on a remembered or summarized version. This generalizes the
remembered-summary rule above from required checkpoints to the whole plan.

**Plan Reconciliation (run before resuming any work):** check the plan's
self-consistency invariants in
[plan-materialization.md](references/plan-materialization.md). On ANY
violation, do NOT trust the plan: establish ground truth with read-only
`aws mwaa get-environment`, `/dags`, and the health path (`/health` on Airflow
2.x, `/monitor/health` on 3.x), repair the plan to match reality, and record it
in `Last updated`. If reality is ambiguous, ask the user. A stale `PASSED`
checkpoint otherwise triggers a destructive next action: switchover + delete
your current environment (New-environment upgrade), the irreversible live
upgrade (Rehearsed in-place upgrade), or premature completion (Direct in-place
upgrade).

- **If absent**: Proceed to Phase 1.

## Phase 1: Discover + Plan Path + Pre-flight

Fetch and follow
[references/discovery-preflight.md](references/discovery-preflight.md). It runs
environment discovery, pre-flight safety checks, version-matrix refresh, target
selection, and upgrade-path planning (detection only; version jumps execute
in Phase 7). Record every output it names into the plan now, because a
compaction before Phase 4 would otherwise lose it. That includes the
environment-scoped permission entries found for the new or test environment,
and per version jump `from`/`to`/`python_from`/`python_to`/`python_change`/
`crosses_major`, with the latest-2.11.x stepping-stone version and
Python-transition step inserted only when the source is not already 2.11.x.

## Phase 2: Choose the Upgrade Approach

One question decides the safest approach; whether you keep the same environment
(its URL and ARN) follows from it and is not a separate choice.

**Do you need to keep your run history** — the record of past DAG runs and task
instances in the Airflow UI?

- **No, a clean slate is fine** → **New-environment upgrade** (slug
  `new-environment`). Build a new environment on the target version and switch
  over to it. It gets a new URL and ARN and no run history; your current
  environment keeps running untouched until you switch, so rolling back is
  just "don't switch."
- **Yes, keep it** → **Rehearsed in-place upgrade** (slug `in-place-rehearsed`).
  Upgrade your existing environment in place (same URL and ARN, history kept),
  after rehearsing the whole upgrade on a temporary test copy. Use the Direct
  in-place upgrade (no test copy) only if the user explicitly declines the
  rehearsal.

This skill does not combine a new URL and ARN with preserved run history.

| Approach | History | URL/ARN | Your current environment during the upgrade | New/test environment created at | Recommended |
|---|---|---|---|---|---|
| New-environment upgrade | Discarded | New | Runs until switchover | the first version jump's target | Yes |
| Rehearsed in-place upgrade | Preserved (snapshot) | Same | Rehearsed on a test copy, then upgraded | the first version jump's target | Yes |
| Direct in-place upgrade | Preserved (snapshot) | Same | Upgraded directly | none | No |

The Direct in-place upgrade is unrecommended and requires an extra
confirmation checkpoint.

**Guardrail**: if the user picks the Rehearsed or Direct in-place upgrade and
the environment has more than 50 DAGs or complex DAGs were detected in
Phase 3, warn and recommend the New-environment upgrade instead. Do not block.

Record the chosen approach's slug (`new-environment` / `in-place-rehearsed` /
`in-place-direct`) in the plan. The position (`working_on`, `current_jump`,
`jump_status`) is initially unset.

## Phase 3: Assess Compatibility

1. **Compatibility scan (conditional on a cross-major version jump):** If any
   version jump in the plan is `crosses_major`, run Ruff with AIR rules as a
   required checkpoint:

   ```
   ruff check --preview --select AIR .
   ```

   Report findings grouped by rule code. Ruff AIR rules cover 2-to-3
   (AIR301/302/303/311/312) and 3.1 (AIR321, preview) API changes; they do NOT
   detect APIs removed between 2.x minor versions, nor 3.2-specific changes.
   Phase 6 Docker import validation in the target image covers that gap: a
   removed API fails as an import error there. If NO version jump is
   `crosses_major` (a within-major upgrade), the AIR scan is informational
   only; rely on Phase 6 instead.

   **AIR311 vs AIR301 severity:** AIR311 flags imports that moved to
   `airflow.sdk` (e.g., `airflow.datasets.Dataset` -> `airflow.sdk.Asset`).
   Fix every AIR311 hit: on the same version the change is behavior-neutral
   (most old paths are shims that resolve to the same object), and it prevents
   a break on a later 3.x upgrade, because individual shims are removed in
   later 3.x releases (for example `airflow.datasets` in 3.2). An AIR311 hit
   blocks the jump only if the old import fails on the target version; confirm
   that with the Phase 6 Docker parse. AIR301 hits (removed APIs) always block.
   The fixed code (`from airflow.sdk import ...`) is AF3-only and cannot be
   deployed until after the cross-major version jump completes — see the
   two-phase deployment note in each approach reference.

   **Patterns Ruff does NOT catch:** The manual checklist
   ([airflow2-to-3-checklist.md](references/airflow2-to-3-checklist.md))
   includes patterns invisible to Ruff, notably standalone Airflow CLI in
   BashOperator (section 16).
   Always run the manual scan even when Ruff reports zero findings.
1a. **Python standard-library check (conditional on `python_change`):** If
   any version jump in the plan is `python_change`, run the check in
   [python-stdlib-check.md](references/python-stdlib-check.md) for each such
   jump's `python_from` → `python_to`. This is independent of
   `crosses_major`: it runs for within-2.x jumps such as 2.10.x → 2.11.x
   (Python 3.11 → 3.12), and it does not run when no jump changes the Python
   line. Scan the DAGs, shared utilities, and the contents of `plugins.zip`.
   A clean Ruff result does not clear this check, because Ruff AIR rules do
   not cover the standard library. Record the result as `python-stdlib` in the
   plan (Phase 4). A check that could not run is `INCOMPLETE`, never clean.
2. Run manual scan using patterns from [airflow2-to-3-checklist.md](references/airflow2-to-3-checklist.md).
   **Surface a metadata-DB warning (every approach, cross-major only):** DAGs
   using metadata-DB access work on AF2 but break on AF3. ORM-access DAGs
   (checklist section 1) must be redesigned to the REST API or dropped.
   CLI-access DAGs (`airflow db ...`, checklist section 16) move to the MWAA
   CLI endpoint (preferred; verify the command on the target via
   `cheat-sheet`), the REST API, or are dropped. Record each affected DAG and
   its category in the plan (Phase 4).
3. Check requirements.txt against the target version's constraints from [mwaa-version-matrix.md](references/mwaa-version-matrix.md).
4. **Secrets backend detection**: Check for a `secrets.backend` config override. With Secrets Manager or Parameter Store, variables and connections are external and need no migration. **If NO secrets backend is configured, surface this to the user at plan time:** connection passwords will NOT migrate via the REST API (2.x omits them; 3.x returns `***`), and on a 3.x source variables with sensitive keys and sensitive fields in connection `extra` are masked too. The user must move these to a secrets backend or complete them out of band on the target, and variable values and connection `extra` transit CLI args and the audit log during migration. Details are in the metadata-migration caveat of the approach reference. Record this in the plan (Phase 4).
5. **Plugin inventory**: If PluginsS3Path is set, list contents. Flag FAB/web-view plugins needing special attention.
5a. **External-resource collision warning** (New-environment and Rehearsed upgrades): DAGs that write to fixed paths or create or start fixed-name external resources (Glue jobs, EMR applications, S3 keys, tables) can collide between environments during test runs and the switchover drain, because the new environment or test copy uses the same connections and variables (for example Glue `ConcurrentRunsExceededException`). List these DAGs, record the warning in the plan (Phase 4), and recommend per-environment names (for example derived from `AIRFLOW_ENV_NAME`). Do not rewrite DAGs without the user's approval. To limit the overlap, DAGs on the new environment or test copy stay paused except during their own test run, and are paused again when it finishes.
6. Classify each DAG by upgrade difficulty: Simple, Moderate, Complex.
7. Group DAGs into batches (shared utilities in batch 0, simple first).

## Phase 4: Generate Upgrade Plan

Write `.mwaa-upgrade-plan-<env-name>.md` to the workspace root with the
contents listed in [plan-materialization.md](references/plan-materialization.md)
`## Plan contents`.

Record the ordered upgrade path as a `## Upgrade Path` table:

| Jump | From → To | Python change | New major version | Status |
|---|---|---|---|---|
| 1 | <jump.from> → <jump.to> | <python_from> → <python_to> (e.g. `3.11 → 3.12`) or `no` | yes/no | pending |

For the Rehearsed in-place upgrade (two environments — the test copy, then
your current environment), give the upgrade-path table separate `Test copy
status` and `Your current environment status` columns; mark the
current-environment jumps `IRREVERSIBLE`.

### Write out every checkpoint and record-section into the plan (mandatory)

Before presenting the plan, follow
[plan-materialization.md](references/plan-materialization.md) and generate every
section it specifies, conforming to its `## Plan format contract` and
`## Self-consistency invariants`. Any step that exists only as prose in an
approach reference, not as a discrete PENDING item in the plan, WILL be skipped
after compaction. A parse-clean signal (`has_import_errors: false`) does NOT
satisfy the test-run checkpoint and must never be recorded as "validated" or
"complete".

Present the plan to the user for confirmation before proceeding.

## Phase 5: Fix Code

1. **Batch 0 (shared utilities):** Fix shared modules first. Apply patterns from [airflow2-to-3-quick-reference.md](references/airflow2-to-3-quick-reference.md).
2. **Per batch (1..N):**
   a. Run Ruff auto-fix: `ruff check --preview --select AIR --fix --unsafe-fixes --unfixable AIR201 <files>`
      (AIR201 hits are reported, not auto-fixed; see checklist section 15).
      When a fix renames a symbol (e.g. `Dataset` -> `Asset`), Ruff leaves the old import; delete
      the old-path imports left unused (`ruff check --select F401 <files>` lists them).
   b. Fix remaining issues per DAG using [airflow2-to-3-quick-reference.md](references/airflow2-to-3-quick-reference.md).
   c. Re-run Ruff to verify zero AIR violations.
   d. **Re-scan the FIXED files (cross-major only)** with the checklist
      section 16 grep, not just the originals, so edits made while fixing are
      covered. Fix hits and re-run Ruff.
   e. Save progress (see plan-materialization.md `## Saving progress`): mark
      each DAG `DONE` and update `Last updated` before starting the next batch.
3. **Python-line fixes (only when a version jump is `python_change` and Phase 3
   step 1a recorded `python-stdlib` hits):** **5-PY.1** replace each removed
   standard-library usage using the replacement table in
   [python-stdlib-check.md](references/python-stdlib-check.md); **5-PY.2**
   re-run the check on the fixed files and mark each hit `DONE`. These
   replacements also run on the source Python, so, unlike AF3 fixes, they
   SHOULD be deployed BEFORE the `python_change` jump: to your current
   environment before an in-place jump, and into the DAG path of a new
   environment or test copy created at a version on the new Python line.
   Deploying to your current environment needs the user's confirmation.

## Phase 6: Local Validation via Docker (Recommended; Strongly Recommended for Python-line Changes and Cross-Major)

Validates the fixed code against the target version with the `test-dags`
command in `aws/amazon-mwaa-docker-images`. If the repo has no image for the
target version, skip Docker validation (log the reason in the plan) and rely on
the engine's live validation in Phase 7.

**Cross-major version jumps:** When any version jump is `crosses_major`,
Docker validation is strongly recommended. Ruff AIR rules miss several
runtime-breaking patterns (e.g., shim modules removed in the target 3.x
release, such as `airflow.datasets` in 3.2). Docker import validation catches these before live
deployment, avoiding iterative fix-deploy-fail cycles on the remote environment.
If Docker is skipped for a cross-major upgrade, log the skip reason AND warn
that undetected runtime errors are likely.

**Python-line changes:** When any version jump is `python_change`, Docker
validation is also strongly recommended. The standard-library check (Phase 3
step 1a) reads code statically, so it cannot see dynamic imports, method calls
it has no name for, or failures that only happen at runtime. For each
`python_change` jump, validate the DAG set actually deployed at that jump (the
Python-line fixes from Phase 5 step 3, plus any AF3 fixes only if that jump is
after the cross-major jump) in that jump's `to` image.

**If Docker is skipped:** Docker is not required, but log the reason in the
plan and warn the user that APIs removed between minor versions (which Ruff
does not cover), provider changes in the target image, and removed-stdlib
usage the Phase 3 check missed will show up only as import errors on the live
environment after the jump.

Follow [docker-validation.md](references/docker-validation.md) for each image
row in the plan (the target, each `python_change` jump's `to`, and `jump_1.to`
for the strategy Verify step). Never record an image `DONE` unless its check
passed.

## Phase 7: Deploy

Dispatch to the chosen approach's reference. Each runs the step-by-step
upgrade ([upgrade-engine.md](references/upgrade-engine.md)).

- **New-environment upgrade**: Follow [strategy-blue-green-fresh.md](references/strategy-blue-green-fresh.md)
- **Rehearsed in-place upgrade**: Follow [strategy-inplace-green-validated.md](references/strategy-inplace-green-validated.md)
- **Direct in-place upgrade (unrecommended)**: Follow [strategy-inplace-direct.md](references/strategy-inplace-direct.md)

Throughout Phase 7, save progress as described in
[plan-materialization.md](references/plan-materialization.md): after each
step, sub-step, version jump, checkpoint, batch, and per-DAG status - and
before the next action - save the change (status token + durable facts +
`Last updated` + `## Where we are`) to the plan.

**DAG test-run validation (REQUIRED for every approach):** after the engine's
parse validation passes, invoke **skill** `testing-mwaa-workflow` for each DAG
or batch to confirm execution succeeds at the target version; on failure,
invoke **skill** `debugging-mwaa-workflow`. Do NOT trigger DAG runs manually
via the REST API (`POST /dags/{id}/dagRuns`) or poll run states inline; the
testing skill owns triggering, polling, classification and the fix loop. Do
NOT proceed to the live upgrade (Rehearsed in-place upgrade), switchover
(New-environment upgrade), or completion (Direct in-place upgrade) until this
checkpoint passes: New-environment Step 4-checkpoint, Rehearsed Step
1-checkpoint, Direct Step 4. Record results in the plan's `## Test-run
results` section. Parse-only validation does not prove artifacts run.

## Phase 8: Switchover + Decommission

Applies to the New-environment and Rehearsed in-place upgrades; the Direct
in-place upgrade completes at Phase 7. New-environment upgrade: switch over,
then decommission your current environment. Rehearsed in-place upgrade: skip
switchover and decommission the TEST COPY; never delete your current
environment.

1. **Batched switchover** (New-environment upgrade only; explicit approval
   per batch): follow `## Phase 8.1: Batched switchover` in
   [strategy-blue-green-fresh.md](references/strategy-blue-green-fresh.md).
   It covers the pre-switchover restore summary, pause -> drain -> unpause ->
   monitor per batch (8.1(a)-(d), with the rollback), and the 8.1a
   `scheduler.catchup_by_default` question after the final batch.

2. **Stability period**: user-defined monitoring window after the final batch
   (recommend 24h or one full cycle of the longest-interval DAG). Watch the
   built-in CloudWatch metrics dashboard and **Create recommended alarms**,
   prioritizing scheduler heartbeat and oldest queued task age
   (https://docs.aws.amazon.com/mwaa/latest/userguide/monitoring-dashboard.html).
   For the New-environment upgrade your current environment stays paused, not
   deleted; for the Rehearsed in-place upgrade it is live and monitored.
3. **Decommission** (explicit approval per step):
   - New-environment upgrade: delete your current environment —
     `aws mwaa delete-environment --name <current-env>`; archive its S3
     artifacts (optional).
   - Rehearsed in-place upgrade: delete the test copy —
     `aws mwaa delete-environment --name <test-copy>`.
   Then **clean up environment-scoped permission entries** for the retired
   environment, only after its `delete-environment` has completed (the 8.1(d)
   rollback and the stability period need them until then). New-environment
   upgrade: remove your old environment's entries recorded at pre-flight.
   Rehearsed in-place upgrade: remove the test copy's entries added at
   pre-flight. Re-read the current role, trust and KMS policies, re-run the
   shared-resource check, then remove only recorded entries marked
   `exclusive` (never the remaining environment's, and never one another
   environment uses), and show the diff for per-change approval. See discovery-preflight.md Step 2.3.
4. **Read-only option** (New-environment upgrade): Offer to keep your current
   environment paused for an extended period for historical UI access before
   final deletion. If the user takes it, the permission cleanup above waits
   until that final deletion.
5. Save progress: mark upgrade complete (status `DONE`), set `Where we are`
   `phase: complete`, and update `Last updated`.
