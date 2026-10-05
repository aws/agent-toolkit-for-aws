---
name: upgrading-mwaa-environments
description: >
  Upgrades an MWAA environment to a newer Airflow version — within 2.x, within 3.x, or
  across the 2.x-to-3.x boundary. Computes the version-jump path, inserting the 2.11.x
  stepping-stone and Python-transition step when needed. Chooses an approach by
  whether run history and the same environment (URL/ARN) must be kept: a
  new-environment upgrade (blue-green), a rehearsed in-place upgrade validated on a
  test copy, or a direct in-place upgrade. Runs Ruff scanning and deprecation-warning
  log scans for 3.x moves, plus Docker validation, batched deployment, and switchover.
  Saves a resumable upgrade plan for multi-session work. Triggers on: upgrade MWAA,
  upgrade Airflow, migrate to Airflow 3, MWAA Airflow 3, Airflow 2 to 3, preserve
  Airflow history, keep same MWAA environment, blue-green cutover, validation
  environment before cutover. Not for authoring new DAGs (authoring-mwaa-workflow),
  debugging unrelated DAG failures (debugging-mwaa-workflow), or MWAA Serverless YAML
  workflows (provisioned Python DAGs only).
metadata:
  version: "1"
---

# Upgrading MWAA Environments

> **AWS MCP server (optional but recommended):** running the AWS CLI commands in
> this skill through the AWS MCP server gives sandboxed execution and audit
> logging. Every command here also works with the plain AWS CLI, so the skill
> does not require the MCP server or any MCP-only tools.

Upgrade an MWAA provisioned environment to any newer, MWAA-supported Airflow
version: within 2.x, within 3.x, or across the 2.x-to-3.x boundary. The target
is a parameter. A path planner computes an ordered version-jump list from
(source, target); the latest 2.11.x stepping-stone version and a Python-line
transition step are inserted only when the path requires them. A deployment
approach is selected by whether historical run data must be preserved and
whether the same environment (its URL/ARN) must be kept: a new-environment upgrade
(`new-environment`), a rehearsed in-place upgrade validated on a test copy
first (`in-place-rehearsed`), or a direct in-place upgrade (`in-place-direct`).

> **Execution note — poll in discrete steps:** whenever you wait for an AWS
> operation to reach a terminal or ready state, issue **one status check per
> call** and decide in your own loop whether to check again. Never block a
> single command or script on the wait (no `while`+`sleep` until done),
> regardless of the operation or how long it takes.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference via
  `retrieve_skill` with the `file` parameter (e.g.
  `file="references/strategy-blue-green-fresh.md"`) and read the returned
  content. Do NOT `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/upgrading-mwaa-environments/` or
  `~/.claude/skills/upgrading-mwaa-environments/`): Read the files from the
  local skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

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
- [strategy-blue-green-fresh.md](references/strategy-blue-green-fresh.md) — New-environment upgrade (no history)
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

- **If exists**: Load the plan, report source, target, chosen approach, and
  the position `(working_on, current_jump, jump_status)`. Resume the engine
  ([upgrade-engine.md](references/upgrade-engine.md)) on the recorded
  environment at the recorded version-jump index and status: `upgrading` ->
  re-poll or re-issue the pending `update-environment`; `validating` -> re-run
  the conditional validate/scan/fix loop for that version jump. For a
  newly-created environment, the starting-version validation window (version
  jump 1's `to`) corresponds to `current_jump: 1, jump_status: validating`;
  resume it there. If no position is set, resume from the next incomplete
  phase.
  **Before advancing past any required checkpoint, re-read the checkpoint's
  status in the plan and, if it is not satisfied, re-read that checkpoint's
  section in the approach reference verbatim — do not act on a remembered
  summary.** Specifically: version jumps complete does NOT imply the test-run
  checkpoint passed. If the `## Test-run results` section has any row not in
  SUCCESS or NEEDS-DECISION, that checkpoint is NOT-PASSED and blocks
  switchover (New-environment upgrade), the live upgrade (Rehearsed in-place
  upgrade — see `live_upgrade_allowed`), or completion (Direct in-place
  upgrade), regardless of version-jump status or `has_import_errors: false`.
  Likewise a batch whose `Monitored one full cycle?` cell is not yes has not
  fully switched over.

**Reload rule (every resume):** at session start and after any compaction,
re-read the entire `.mwaa-upgrade-plan-<env-name>.md` before taking any action;
never act on a remembered or summarized version. This generalizes the
remembered-summary rule above from required checkpoints to the whole plan.

**Plan Reconciliation (run before resuming any work):** verify the plan's
self-consistency invariants (full list in
[plan-materialization.md](references/plan-materialization.md)): a checkpoint
marked `PASSED` requires all its prerequisite Checklist items `DONE`/`SKIP`;
`Where we are.test_run_checkpoint` must equal the Test-run results table (any
`PENDING` row -> `NOT-PASSED`); `current_jump`/`jump_status` must match the
Upgrade Path Status; for the Rehearsed in-place upgrade, `live_upgrade_allowed`
must equal the test-run checkpoint. On ANY violation, do NOT trust the plan -
establish ground truth with read-only `aws mwaa get-environment`, `/dags`, and
`/health`, repair the plan to match reality, and record it in `Last updated`.
If reality is ambiguous, ask the user. A stale `PASSED` checkpoint otherwise
triggers a destructive next action: switchover + delete your current
environment (New-environment upgrade), the irreversible live upgrade
(Rehearsed in-place upgrade), or premature completion (Direct in-place
upgrade).

- **If absent**: Proceed to Phase 1.

## Phase 1: Discover + Plan Path + Pre-flight

Fetch and follow
[references/discovery-preflight.md](references/discovery-preflight.md). It runs
environment discovery, pre-flight safety checks, version-matrix refresh, target
selection, and upgrade-path planning (detection only — version jumps execute
in Phase 7). Record every output into the plan now, because Phase 4 is what
turns it into the durable plan file, and a compaction before Phase 4 would
otherwise lose it:

- discovered environment facts (Airflow version, S3 artifact paths + object
  versions, KmsKey, config options, DAG list, shared utilities);
- the new-environment / test-copy S3 layout (New-environment upgrade,
  Rehearsed in-place upgrade);
- pre-flight results (S3 versioning, target constraints, KMS key-policy reuse);
- the selected target version;
- the ordered upgrade path — per version jump
  `from`/`to`/`python_change`/`crosses_major`, with the latest-2.11.x
  stepping-stone version + Python-transition step inserted only when the
  source is not already 2.11.x.

## Phase 2: Choose the Upgrade Approach

One question decides the safest approach; whether you keep the same environment
(its URL and ARN) follows from it and is not a separate choice.

**Do you need to keep your run history** — the record of past DAG runs and task
instances in the Airflow UI?

- **No, a clean slate is fine** → **New-environment upgrade** (slug
  `new-environment`). Build a brand-new environment on the target version and
  switch over to it. It gets a new URL and starts with no run history; your
  current environment keeps running untouched until you switch, so rolling back
  is just "don't switch."
- **Yes, keep it** → **Rehearsed in-place upgrade** (slug `in-place-rehearsed`).
  Upgrade your existing environment in place — same URL, full history kept. First
  rehearse the whole upgrade on a temporary test copy to catch problems safely.
  Use the Direct in-place upgrade (no test copy) only if the user explicitly
  declines the rehearsal.

Whether you keep the same environment (its URL and ARN) is a consequence, not
an input: keeping your run history means upgrading your current environment in
place (same URL and ARN), while the New-environment upgrade necessarily creates
a new environment. This skill does not combine a new environment (a new URL and
ARN) with preserved run history — if the user needs a new URL and ARN, run
history is not carried over (New-environment upgrade).

| Approach | History | URL/ARN | Your current environment during the upgrade | New/test environment created at | Recommended |
|---|---|---|---|---|---|
| New-environment upgrade | Discarded | New | Runs until switchover | the first version jump's target | Yes |
| Rehearsed in-place upgrade | Preserved (snapshot) | Same | Rehearsed on a test copy, then upgraded | the first version jump's target | Yes |
| Direct in-place upgrade | Preserved (snapshot) | Same | Upgraded directly | none | No |

The New-environment upgrade and the Rehearsed in-place upgrade are both
recommended; the user chooses by need. The Direct in-place upgrade is
unrecommended and requires an extra confirmation checkpoint.

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
   The pre-cross deprecation-warning scan in the engine covers the
   2.x-internal gap. If NO version jump is `crosses_major` (a within-major
   upgrade), the AIR scan is informational only; rely on the engine's generic
   `DeprecationWarning` scan instead.

   **Version-aware severity for AIR311 (import path moves):** AIR311 flags
   imports that moved to `airflow.sdk` (e.g., `airflow.datasets.Dataset` ->
   `airflow.sdk.Asset`). Severity depends on the target version:
   - **Target 3.0.x or 3.1.x:** soft deprecation — compatibility shims exist,
     old imports still work. Fix recommended but not blocking.
   - **Target 3.2.1+:** hard blocker — shim modules are fully removed
     (`ModuleNotFoundError` at parse time). Must fix before deploying to target.

   Always classify AIR311 as "must fix" when the target is 3.2.1+. The fixed
   code (`from airflow.sdk import ...`) is AF3-only and cannot be deployed
   until after the cross-major version jump completes — see the two-phase
   deployment note in each approach reference.

   **Patterns Ruff does NOT catch:** The manual checklist
   ([airflow2-to-3-checklist.md](references/airflow2-to-3-checklist.md))
   includes patterns invisible to Ruff, notably `_TaskDecorator.output`
   (section 15) and standalone Airflow CLI in BashOperator (section 16).
   Always run the manual scan even when Ruff reports zero findings.
2. Run manual scan using patterns from [airflow2-to-3-checklist.md](references/airflow2-to-3-checklist.md).
   **Surface a metadata-DB warning (every approach, cross-major only):** DAGs
   using metadata-DB access work on AF2 but break on AF3. Two categories:
   - **ORM-access DAGs** (`settings.Session()`, `provide_session` — checklist
     section 1): must be redesigned to the REST API (webserver in-VPC, or
     `invoke-rest-api` with its low rate limit) or dropped.
   - **CLI-access DAGs** (`airflow db ...` in BashOperator — checklist section
     16): redesign to the MWAA CLI endpoint (preferred, simpler) or REST API
     or drop. The agent must verify command availability on the target version
     via `cheat-sheet` before committing to this path.
   Record each affected DAG and its category in the plan (Phase 4).
3. Check requirements.txt against the target version's constraints from [mwaa-version-matrix.md](references/mwaa-version-matrix.md).
4. **Secrets backend detection**: Check for `secrets.backend` config override in environment configuration. If using Secrets Manager or Parameter Store, note that variables/connections are external and do not need migration. **If NO secrets backend is configured, surface this to the user at plan time:** connection passwords will NOT migrate via the REST API (2.x omits, 3.x masks), so password-bearing connections must be moved to a secrets backend or have their passwords re-entered out of band on the target — and variable values / connection `extra` transit `--body`/CLI args and the audit log during migration. Record this in the plan (Phase 4).
5. **Plugin inventory**: If PluginsS3Path is set, list contents. Flag FAB/web-view plugins needing special attention.
6. Classify each DAG by upgrade difficulty: Simple, Moderate, Complex.
7. Group DAGs into batches (shared utilities in batch 0, simple first).

## Phase 4: Generate Upgrade Plan

Write `.mwaa-upgrade-plan-<env-name>.md` to workspace root (where
`<env-name>` is the source environment name discovered in Phase 1). Include:

- Environment details (source name, source version, region) plus the target
  version and the full upgrade-path table
- Chosen approach — its slug (`new-environment` / `in-place-rehearsed` /
  `in-place-direct`)
- Pre-flight results (S3 versioning, constraints, upgrade-path status)
- Docker validation status (pending)
- Secrets backend detection results
- Requirements changes needed
- **Cross-major only** — metadata-DB-access findings (Phase 3 step 2): each DAG
  using metadata-DB access, categorized as ORM-access (redesign to REST API or
  drop) or CLI-access (redesign to MWAA CLI endpoint, or REST API, or drop);
  plus a PENDING post-fix re-scan checkpoint (Phase 5 step 2d). Omit when no
  version jump is `crosses_major`.
- Approach-specific fields: New-environment upgrade — new environment name,
  new-environment S3 paths; Rehearsed in-place upgrade — test-copy env name,
  test-copy S3 paths; Direct in-place upgrade — none (in-place, no new/test
  environment)
- Batch table with per-DAG status

Record the ordered upgrade path as a `## Upgrade Path` table:

| Jump | From → To | Python change | New major version | Status |
|---|---|---|---|---|
| 1 | <jump.from> → <jump.to> | yes/no | yes/no | pending |

For the Rehearsed in-place upgrade (two environments — the test copy, then
your current environment), give the upgrade-path table separate `Test copy
status` and `Your current environment status` columns; mark the
current-environment jumps `IRREVERSIBLE`.

### Write out every checkpoint and record-section into the plan (mandatory)

Before presenting the plan, follow
[plan-materialization.md](references/plan-materialization.md) and generate every
section it specifies, conforming to its `## Plan format contract` (fixed status
vocabulary, `Last updated` line, `## Where we are` keys) and satisfying its
`## Self-consistency invariants`: the `## Checklist`, every per-approach
required checkpoint as its own PENDING entry, the pre-seeded `## Test-run
results` and `## Switchover progress` (New-environment upgrade) tables, the
`## Where we are` block, the parse-clean-vs-test-run-verified status
vocabulary (`LOADED` vs `VERIFIED`), and the approach-specific sub-step
decomposition rules. The plan is the durable, resumable source of truth: any
step that exists only as prose in a approach reference — not as a discrete
PENDING item here — WILL be skipped after compaction. Generate these sections
BEFORE presenting the plan; a parse-clean signal (`has_import_errors: false`)
does NOT satisfy the test-run checkpoint and must never be recorded as
"validated" or "complete".

Present the plan to the user for confirmation before proceeding.

## Phase 5: Fix Code

1. **Batch 0 (shared utilities):** Fix shared modules first. Apply patterns from [airflow2-to-3-quick-reference.md](references/airflow2-to-3-quick-reference.md).
2. **Per batch (1..N):**
   a. Run Ruff auto-fix: `ruff check --preview --select AIR --fix --unsafe-fixes <files>`
   b. Fix remaining issues per DAG using [airflow2-to-3-quick-reference.md](references/airflow2-to-3-quick-reference.md).
   c. Re-run Ruff to verify zero AIR violations.
   d. **Re-scan the FIXED files (cross-major only)** with the checklist
      section 15/16 greps — not just the originals. `--unsafe-fixes` can rewrite
      `xcom_pull` templates into `<task>.output` (AF3-invalid) without re-flagging
      it; this runtime break otherwise surfaces only at live parse. Fix hits and
      re-run Ruff.
   e. Save progress (see plan-materialization.md `## Saving progress`): mark
      each DAG `DONE` and update `Last updated` before starting the next batch.

## Phase 6: Local Validation via Docker (Recommended; Strongly Recommended for Cross-Major)

Uses `aws/amazon-mwaa-docker-images` to validate fixed code against the target
version. This repo only provides images for Airflow 2.9.2 and newer. If the
target version is below 2.9.2, skip Docker validation (log skip reason in the
plan) and rely on the engine's live validation in Phase 7 instead.

**Cross-major version jumps:** When any version jump is `crosses_major`,
Docker validation is strongly recommended. Ruff AIR rules miss several
runtime-breaking patterns (e.g., `_TaskDecorator.output` removal, fully-removed
shim modules in 3.2.1+). Docker import validation catches these before live
deployment, avoiding iterative fix-deploy-fail cycles on the remote environment.
If Docker is skipped for a cross-major upgrade, log the skip reason AND warn
that undetected runtime errors are likely.

1. Check Docker availability: `docker --version`. If unavailable, user declines, or target < 2.9.2, log skip in plan with warning and proceed to Phase 7.
2. Pull the target-version image (resolve the exact tag at runtime from the repo README).
3. **Validate requirements.txt**: Mount into container, run install validation. If failures: report conflicts, suggest fixes, loop until passing or user skips.
4. **Validate plugins.zip** (if present): Mount and run import validation.
5. **Validate DAG imports**: Mount fixed DAGs, run parsing. If errors: return to Phase 5 for affected files, then re-validate.
6. Save progress: mark Docker validation `DONE` or `SKIP` (with reason) and update
   `Last updated`.

## Phase 7: Deploy

Dispatch to the approach-specific reference based on the plan's chosen
approach. Each approach runs the step-by-step upgrade
([upgrade-engine.md](references/upgrade-engine.md)) on the new environment
(New-environment upgrade), the test copy then your current environment
(Rehearsed in-place upgrade), or your current environment (Direct in-place
upgrade).

- **New-environment upgrade**: Follow [strategy-blue-green-fresh.md](references/strategy-blue-green-fresh.md)
- **Rehearsed in-place upgrade**: Follow [strategy-inplace-green-validated.md](references/strategy-inplace-green-validated.md)
- **Direct in-place upgrade (unrecommended)**: Follow [strategy-inplace-direct.md](references/strategy-inplace-direct.md)

Throughout Phase 7, save progress as described in
[plan-materialization.md](references/plan-materialization.md): after each
step, sub-step, version jump, checkpoint, batch, and per-DAG status - and
before the next action - save the change (status token + durable facts +
`Last updated` + `## Where we are`) to the plan.

**DAG test-run validation (REQUIRED for every approach):** After the
engine's parse validation passes, invoke **skill** `testing-mwaa-workflow` for
each DAG or batch of DAGs to confirm execution succeeds at the target version.
On failure, invoke **skill** `debugging-mwaa-workflow` for root-cause analysis.
Do NOT trigger DAG runs manually via the REST API (`POST /dags/{id}/dagRuns`)
or poll run states inline — the testing skill owns triggering, polling,
classification (SUCCESS vs NEEDS-DECISION), and the fix loop. This is a
required checkpoint — do NOT proceed to the live upgrade (Rehearsed in-place
upgrade), switchover (New-environment upgrade), or completion (Direct in-place
upgrade) until test-run validation passes. Parse-only validation (no import
errors) does not prove artifacts will run correctly. Each approach reference
defines this as an explicit, numbered required checkpoint that must be
satisfied before the next phase: New-environment upgrade Step 4-checkpoint,
Rehearsed in-place upgrade Step 1-checkpoint, Direct in-place upgrade Step 4.
The checkpoint requires recording results in a `## Test-run results` section
of the plan. The upgrade skill orchestrates this loop and does not perform
test/debug logic inline.

## Phase 8: Switchover + Decommission

Applies to approaches that create a new/test environment (New-environment
upgrade, Rehearsed in-place upgrade). The Direct in-place upgrade completes at
Phase 7 (no new/test environment).

- **New-environment upgrade**: switch over from your current environment to
  the new environment, then decommission your current environment.
- **Rehearsed in-place upgrade**: the test copy was a rehearsal; your current
  environment is the live upgraded environment. Skip switchover; decommission
  the TEST COPY. Do not delete your current environment.

1. **Batched switchover** (New-environment upgrade only; explicit approval
   per batch): For each batch (matching the same batch grouping from Phase 7):
   a. Pause the batch's DAGs on your current environment (space calls with a
      short sleep; `invoke-rest-api` has a 10-second timeout / 6 MB response
      cap
      ([docs](https://docs.aws.amazon.com/mwaa/latest/userguide/access-mwaa-apache-airflow-rest-api.html))
      and is throttled per environment, so use backoff rather than a fixed rate):

      ```
      aws mwaa invoke-rest-api --name <current-env> --method PATCH \
        --path /dags/<dag_id> --body '{"is_paused":true}'
      sleep 0.2
      ```

   b. Drain: wait for in-flight runs of those DAGs to complete on your current
      environment. Poll `dag_runs` for `state=running`. If a run remains
      in-flight after 10 minutes and its active task is a sensor or deferred
      operator (check task_instances for `state=deferred` or
      `state=sensing`), proceed with unpausing on the new environment. The
      paused DAG on your current environment will not produce new runs; the
      in-flight run will complete or timeout independently. It cannot
      conflict with the new environment because the new environment starts
      fresh with no prior dag_runs for that execution_date.
   c. Unpause the same DAGs on the new environment (same 0.2s throttle):

      ```
      aws mwaa invoke-rest-api --name <new-env> --method PATCH \
        --path /dags/<dag_id> --body '{"is_paused":false}'
      sleep 0.2
      ```

   d. Monitor the batch on the new environment for one full schedule cycle
      before proceeding to the next batch. On failure, re-enable the batch on
      your current environment (rollback) and investigate.

   Per-DAG pause/unpause above uses `--path /dags/<dag_id>`, subject to the
   64-char `--path` limit; for an over-length `dag_id` use the Airflow CLI
   fallback (`aws mwaa create-cli-token` -> `airflow dags pause|unpause`) noted
   in [upgrade-engine.md](references/upgrade-engine.md).

   For small environments (fewer than 10 DAGs or all-simple classification),
   offer an all-at-once switchover as an alternative if the user prefers speed.

2. **Stability period**: User-defined monitoring window after the final batch
   completes (recommend: 24h or one full cycle of the longest-interval DAG).
   Watch the environment's health on its built-in CloudWatch metrics dashboard
   and the **Create recommended alarms** action, which stay current; scheduler
   liveness (e.g. Scheduler heartbeat) and queue backlog (e.g. Oldest queued
   task age) are the core post-switchover indicators to prioritize
   (https://docs.aws.amazon.com/mwaa/latest/userguide/monitoring-dashboard.html).
   For the New-environment upgrade, your current environment remains paused,
   not deleted. For the Rehearsed in-place upgrade, your current environment
   is live and monitored.
3. **Decommission** (explicit approval per step):
   - New-environment upgrade: delete your current environment —
     `aws mwaa delete-environment --name <current-env>`; archive its S3
     artifacts (optional).
   - Rehearsed in-place upgrade: delete the test copy —
     `aws mwaa delete-environment --name <test-copy>`.
4. **Read-only option** (New-environment upgrade): Offer to keep your current
   environment paused for an extended period for historical UI access before
   final deletion.
5. Save progress: mark upgrade complete (status `DONE`), set `Where we are`
   `phase: complete`, and update `Last updated`.
