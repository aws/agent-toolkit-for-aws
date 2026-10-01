---
name: testing-mwaa-workflow
description: >
  Tests Amazon MWAA workflow execution end-to-end: trigger a run and monitor it
  to completion for Provisioned (Python DAG, via Airflow REST API) and Serverless
  (YAML workflow, via StartWorkflowRun). Verifies the artifact is deployed and
  parse-ready, triggers with confirmation, polls to terminal state, and on failure
  delegates diagnosis to debugging-mwaa-workflow and artifact/redeploy fixes to
  authoring-mwaa-workflow, then retests up to a capped number of attempts.
  Triggers on: test my DAG, test my workflow, run my DAG, trigger a test run,
  does my DAG work, smoke-test the pipeline, verify my workflow runs, execute my
  DAG to check it. Not applicable to writing or deploying a new workflow (handled by authoring-mwaa-workflow), or for diagnosing why a run failed or root-causing an
  error (handled by debugging-mwaa-workflow).
metadata:
  version: "1"
---

# Testing MWAA Workflows

> **AWS MCP server (optional but recommended):** running the AWS CLI commands in
> this skill through the AWS MCP server gives sandboxed execution and audit
> logging. Every command here also works with the plain AWS CLI, so the skill
> does not require the MCP server or any MCP-only tools.

Test Amazon MWAA workflow execution end-to-end: trigger a run, poll it to a
terminal state, and on failure drive a capped debug -> fix -> retest loop. This
skill triggers and reads state only; it delegates every diagnosis to
debugging-mwaa-workflow and every mutation (artifact edit, redeploy, environment
create/update) to authoring-mwaa-workflow. Routes by flavor, then runs one
shared spine.

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
  `file="references/provisioned-testing.md"`) and read the returned content. Do
  NOT `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/testing-mwaa-workflow/` or
  `~/.claude/skills/testing-mwaa-workflow/`): Read the files from the local
  skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## Step 0: Detect Flavor, Mode, and Complexity

### Flavor (reuse debugging's logic)

1. An environment name resolvable via `aws mwaa get-environment` -> **Provisioned**.
2. A `workflow/...` ARN or any `aws mwaa-serverless` context -> **Serverless**.
3. Neither signal -> ask: **MWAA Provisioned (Python DAG)** or **MWAA Serverless
   (YAML workflow)**?

### Invocation mode

- **Standalone** — the user points at an existing, already-deployed target.
- **Delegated** — authoring-mwaa-workflow deployed and handed over the resolved
  target (env name + `dag_id`, or workflow ARN). Its "deploy and test now?"
  approval satisfies the first trigger confirmation only.

### Complexity

- **Simple** — target already deployed and known-ready -> skip to Step 2.
- **Standard** — just deployed, readiness unknown -> full spine.
- **Complex** — retest inside an active fix loop.

## Step 1: Readiness Check (before the first trigger)

Confirm the artifact is deployed and parse-ready. Do not trigger blind. This step
is MANDATORY even when you plan to adopt an existing run — the readiness data
(`last_parsed_time`, `is_active`, `has_import_errors`) feeds the freshness gate
in Step 2.

- **Provisioned:** confirm `dag_id` present with `has_import_errors: false`,
  then apply the version-aware ready check via the `/dags` collection endpoint.
  Determine the poll window from the environment's configured scan interval:
  check `get-environment` -> `AirflowConfigurationOptions` for
  `scheduler.dag_dir_list_interval` (AF2) or `dag_processor.refresh_interval` (AF3).
  If unset, default to 300s. Poll up to that interval + 30s at 15s intervals
  (the per-DAG endpoint can lag). On **AF2 (REST API v1)** require
  `is_active: true`. On **AF3 (REST API v2)** the `is_active` field does not
  exist — require `is_stale: false` instead and never wait on `is_active` (it
  reads as absent/false forever). A DAG that is parsed but not yet ready will
  reject trigger attempts with an opaque `RestApiClientException`. Not ready in
  time -> hand to debugging-mwaa-workflow.
- **Serverless:** confirm `WorkflowStatus` is `READY` (via `get-workflow
  --workflow-arn`). Not ready -> hand to debugging-mwaa-workflow.

This readiness window is separate from the Step 3 run timeout. See
[references/provisioned-testing.md](references/provisioned-testing.md) and
[references/serverless-testing.md](references/serverless-testing.md) for exact
commands.

## Step 2: Confirm, then Trigger (safety gate)

State the resolved target and classify its environment. Unless you are certain
it is a development/test environment (name or tags clearly indicate dev/test),
treat it as production: emit a prod warning and require explicit user
confirmation before triggering. If the target is confirmed production (name or
tags contain `prod`, `prd`, or `production`, or the user says so), require
explicit approval at **every** state-changing step — each trigger, re-trigger,
and clear/rerun — not just once. For a target you are certain is dev/test,
require explicit user confirmation before the **first** trigger and each
re-trigger.

This gate is already satisfied when the user has given explicit approval for
the action: in delegated mode the authoring "deploy and test now?" approval
covers the first trigger, and an explicit pre-authorization to trigger a
specific run counts as that confirmation — do not re-ask when approval has
already been given.

Before triggering, check for scheduler-created runs (see provisioned-testing
reference). Apply the **freshness gate** before adopting any prior run:

- **Delegated mode:** always trigger fresh. Prior runs predate the deployment
  by definition — do not adopt regardless of state.
- **Standalone mode:** compare `run.start_date` against `dag.last_parsed_time`
  read from the `/dags` collection response the Step 1 readiness check already
  fetches (the collection returns `last_parsed_time` per DAG in both v1 and v2 —
  no per-DAG call needed). If `start_date < last_parsed_time`, the run tested a
  prior artifact version — treat as stale, trigger fresh. Only adopt runs where
  `start_date >= last_parsed_time`.

For fresh, non-stale runs that pass the gate: if a run already exists for the
target interval, adopt it instead of POSTing. Monitor through Step 3.

On a **retest**, all run identifiers must be fresh (Provisioned: both
`dag_run_id` and `logical_date`; Serverless: new `start-workflow-run` call).
Before re-triggering, confirm every prior run is terminal — a still-running
prior run can block the new one from starting.

See references for exact trigger commands and retest hygiene.

## Step 3: Poll to Terminal

Poll the triggered run until it reaches a terminal state. See references for
exact poll commands and error fallbacks.

**Timeout handling:**

- **Provisioned with `dagrun_timeout` set:** if elapsed time exceeds
  `dagrun_timeout` and the run is still not terminal, treat as failure -> Step 4.
  (`dagrun_timeout` is a DAG-level Airflow parameter and does not apply to MWAA
  Serverless.)
- **Serverless:** poll until the service returns a terminal state — no caller
  ceiling is needed, because the MWAA Serverless service enforces its own run
  cap and surfaces it as the `TIMEOUT` terminal state.
- **Provisioned without `dagrun_timeout`:** there is no DAG- or service-level
  deadline, so agree a **maximum wait** with the user before polling (they know
  the DAG's expected runtime; default to 1h if they have no preference). Poll
  until terminal OR the maximum wait elapses. On reaching the cap, stop polling
  and report — do not silently mark it failed, and do not keep polling
  unbounded:
  > Run `<run-id>` has not reached a terminal state within the agreed
  > `<max-wait>`. It may still be running — I have not failed it. Choose:
  > (a) extend the wait, (b) inspect logs / the Airflow UI, or (c) treat this
  > test as inconclusive.

**Poll interval scales with elapsed time:**

| Elapsed time | Poll interval |
|--------------|---------------|
| <= 5 min | 15s |
| > 5-15 min | 30s |
| > 15-30 min | 60s |
| > 30-60 min | 2 min |
| > 60 min | 5 min |

**Pass = terminal SUCCESS only**; no output-data inspection. On pass -> Step 6.

## Step 4: On Failure, Delegate to Debugging

Hand the run identifiers to debugging-mwaa-workflow. It returns its standard
structure (Root Cause / Impact / Immediate Fix / Prevention / Commands). Do not
re-diagnose here.

## Step 5: Classify Fixes and Loop

**5a. Classify each action item** debugging returns into one bucket:

| Bucket | Examples | Handling |
|--------|----------|----------|
| ARTIFACT | wrong operator param, missing import, bad YAML schema/timedelta, wrong task wiring, Serverless code-package fix (missing dep / wrong-platform wheel / bad zip layout) | Delegate to authoring-mwaa-workflow: regenerate the compliant artifact (and rebuild/redeploy the `--code` package for Serverless), then redeploy. Auto-continue. |
| ENVIRONMENT | requirements.txt dependency, plugins.zip, env config / worker sizing | Delegate to authoring's deploy path (owns env mutation + its own approval). Auto-continue after that gate. |
| HUMAN-GATED | new IAM permission, VPC/networking, missing data asset, quota increase | Cannot be auto-applied. Present exact commands, pause the loop, wait for the user to confirm resolution before any retest. |

Testing never mutates directly.

**5b. Re-test.** After an auto-fixable bucket is applied and redeployed, loop
back to Step 1 (redeploy triggers a fresh S3-sync/parse) -> Step 2 (re-confirm)
-> Step 3. Apply Step 2's re-trigger hygiene: fresh `dag_run_id` **and**
`logical_date`, and confirm the prior run is terminal (not just still
retry-backing-off) before the new trigger.

**5c. Mixed action items in one cycle (parallel).** Kick off the auto-fixable
fixes (regenerate + redeploy via authoring) and present the human-gated items at
the same time; do not fully serialize. Two guardrails: (1) gate the retest on
**both** completing — do not re-trigger until auto-fixes are redeployed **and**
the user confirms the human-gated items; (2) if an auto-fix depends on a
human-gated item (the regenerated artifact references a resource/permission the
user must create first), sequence them instead of parallelizing.

**5d. Loop cap and stop conditions.** The cap counts **attempts without
progress**, not raw attempts — default 3 (override "retry up to N"). Define
**progress** as either: a task that failed before now reaches SUCCESS (the
pipeline advanced), or debugging reports a different root cause than the prior
attempt. An attempt that makes progress resets the counter — a multi-task
pipeline that clears one blocker per run is advancing, and a hard raw-count cap
would abandon it mid-repair. Stop and summarize when any of: (1) run reaches
SUCCESS -> Step 6 pass; (2) the no-progress counter hits the cap; (3) a
HUMAN-GATED item -> pause for the user. Two consecutive runs with the **same**
root cause count as one no-progress increment each — that is the counter
advancing, not a separate rule.

## Step 6: Report

```
Test Result: PASS | FAIL | STOPPED (<reason>)
Target: <env-name + dag_id | workflow ARN>  [PROD WARNING if applicable]
Attempts: <n>/<cap>
Run History:
  Attempt 1: <run_id> -> <state> (<duration>) [-> root cause if failed]
Fixes Applied: <artifact/env fixes auto-applied via authoring, per attempt> | none
Outstanding Action Items: <human-gated items, exact commands> | none
Next Step: <re-invoke to retest after resolving | passed, nothing needed>
```

PASS requires terminal SUCCESS. STOPPED covers cap-reached / no-progress /
human-gated-pause, each named explicitly.

## Gotchas

- A freshly deployed artifact is not immediately runnable — it must sync from S3
  and parse (Provisioned) or was validated at create/update (Serverless). Step 1
  is mandatory before the first trigger unless complexity is Simple.
- This skill never edits an artifact, changes requirements, or creates/updates
  an environment. Those are authoring-mwaa-workflow's job and carry its approval
  gates. Testing only triggers (confirmed) and reads state.
- Pass is run-state SUCCESS only. Output-data correctness is out of scope.

## Troubleshooting

| Symptom | Cause | Action |
|---------|-------|--------|
| DAG absent from `GET /dags` | S3-sync lag or import error | Hand to debugging-mwaa-workflow before triggering |
| `--path` rejected / truncated | Path over 64 chars (https://docs.aws.amazon.com/cli/latest/reference/mwaa/invoke-rest-api.html) | Poll the collection path with `--query-parameters` |
| `RestApiClientException` on poll | Web server unreachable | Fall back to DAGProcessing/Scheduler log groups |
| `RestApiClientException` on dagRuns POST (empty message) | DAG not ready — AF2: `is_active=false` (activation incomplete); AF3: `is_stale=true` (`is_active` does not exist in v2) | Poll `/dags` collection until ready (AF2 `is_active=true` / AF3 `is_stale=false`); do not retry the trigger blind |
| Manual run created but stuck in `queued`, never starts (AF3) | DAG is paused — AF3 does not execute manual runs while paused (AF2 does) | Unpause (`PATCH /dags/<dag_id>` `{"is_paused": false}`) then trigger; common right after an upgrade where DAGs are deployed paused |
| Serverless `get-workflow` not READY | Still creating/updating or failed | Wait for READY; if FAILED, hand to debugging |
| Same failure two attempts running | Fix not addressing root cause | Stop at no-progress; summarize; do not burn the cap |

## References

- [references/provisioned-testing.md](references/provisioned-testing.md) — exact invoke-rest-api commands (readiness, trigger, poll), 64-char path limit, retest hygiene, log fallback
- [references/serverless-testing.md](references/serverless-testing.md) — exact mwaa-serverless commands (get-workflow, start-workflow-run, get-workflow-run), terminal states

## Security Considerations

- **Triggers real runs** (state-changing): every trigger and re-trigger requires
  explicit confirmation; prod-named targets get a warning first.
- **No autonomous mutation**: the skill never edits artifacts, requirements, or
  environments and never changes IAM — those are delegated to authoring (with
  its own gates). Human-gated fixes pause the loop for user action.
- **No secret exposure**: run and log inspection must not surface credentials or
  connection strings into output.
