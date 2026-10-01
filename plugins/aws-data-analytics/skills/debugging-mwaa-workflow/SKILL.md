---
name: debugging-mwaa-workflow
description: >
  Diagnoses and root-causes Amazon MWAA workflow failures across Provisioned
  (Python DAG) and Serverless (YAML workflow) environments. Provisioned uses
  aws mwaa invoke-rest-api, CloudWatch log groups, and get-environment;
  Serverless uses aws mwaa-serverless API (GetWorkflowRun, ListWorkflowRuns,
  GetTaskInstance) and CloudWatch logs. Covers failed runs and tasks, DAGs
  not appearing, import errors, worker OOM, IAM denials, and dependency drift.
  Triggers on: DAG failed, task failed, workflow run failed, MWAA error, debug
  my DAG, why did my workflow fail, DAG not showing up, MWAA import error,
  requirements failing, worker crashed, serverless run failed.
  Not applicable to authoring workflows (handled by authoring-mwaa-workflow), running or
  smoke-testing a workflow (handled by testing-mwaa-workflow), or CI-CD deploy failures.
metadata:
  version: "1"
---

# Debugging MWAA Workflows

> **AWS MCP server (optional but recommended):** running the AWS CLI commands in
> this skill through the AWS MCP server gives sandboxed execution and audit
> logging. Every command here also works with the plain AWS CLI, so the skill
> does not require the MCP server or any MCP-only tools.

Diagnose and root-cause Amazon MWAA workflow failures, then report root cause,
impact, and recommended remediation. Routes by flavor, then runs a shared
4-step diagnostic spine.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference via
  `retrieve_skill` with the `file` parameter (e.g.
  `file="references/failure-catalog.md"`) and read the returned content. Do NOT
  `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/debugging-mwaa-workflow/` or
  `~/.claude/skills/debugging-mwaa-workflow/`): Read the files from the local
  skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## Step 0: Detect Flavor and Scope the Failure

### Detect flavor

1. An environment name resolvable via `aws mwaa get-environment` means the
   environment is **Provisioned**.
2. A `workflow/...` ARN or any `aws mwaa-serverless` context means the
   environment is **Serverless**. A bare run identifier does NOT indicate
   flavor — Provisioned DAG runs also have run ids.
3. If neither signal is present, ask: is the target **MWAA Provisioned (Python
   DAG)** or **MWAA Serverless (YAML workflow)**?

### Route by complexity

- **Simple** — a single named task or run failed with a clear exception. Jump
  to Step 2 for that task.
- **Standard** — a run failed and the cause is unknown. Run the full Step 1 to
  Step 4 sweep.
- **Complex** — intermittent or environment-wide (multiple DAGs, "worked
  yesterday", nothing appearing). Run the full sweep with emphasis on Step 3.

## Step 1: Identify the Failure

**Provisioned:** list failed DAG runs and task instances via
`aws mwaa invoke-rest-api` (paths `/dags/{id}/dagRuns` and
`/dags/{id}/dagRuns/{run_id}/taskInstances`). If `invoke-rest-api` errors
(`RestApiClientException`), fall back to the Scheduler and DAGProcessing log
groups. Get version and config from `aws mwaa get-environment`. See
[references/provisioned-diagnostics.md](references/provisioned-diagnostics.md).

**Serverless:** `aws mwaa-serverless list-workflow-runs`, then
`get-workflow-run`. Read `RunDetail.ErrorMessage` — an empty `TaskInstances`
with a parser message is a definition error; `Workflow execution failed` with
populated `TaskInstances` is a task-execution failure. See
[references/serverless-diagnostics.md](references/serverless-diagnostics.md).

## Step 2: Get Error Details and Categorize

Pull the real exception past boilerplate:

**Provisioned:** read the Task log group first, then Worker/Scheduler/
DAGProcessing as the symptom directs.

**Serverless:** `list-task-instances` then `get-task-instance` to get each
task's `LogStream`, then read that stream in CloudWatch.

Then categorize in priority order — `infra`, then `drift`, then `code-data` —
using [references/failure-catalog.md](references/failure-catalog.md). The
category determines the Step 3 checks.

## Step 3: Check Context (Why It Happened)

Run the context checks for the matched category from
[references/failure-catalog.md](references/failure-catalog.md). Do not stop at
the surface exception: a SIGKILL is an OOM story, a fresh import error on
unchanged code is a drift story, a sensor timeout is an upstream-health story.

## Step 4: Provide Actionable Output

Report in this exact structure:

```
Root Cause: <one-line diagnosis with the evidence that proves it>
Impact: <what failed, which runs, blast radius>
Immediate Fix: <the smallest change that unblocks>
Prevention: <the change that stops recurrence>
Commands: <exact read-only commands run, plus remediation commands for the user to run>
```

Run only read-only operations. Present state-mutating remediation
(clear/rerun/backfill for Provisioned; start-workflow-run or fix-and-redeploy
for Serverless) as commands for the user to run, with the impact stated. Never
execute them autonomously (production safety).

For the fix-and-redeploy path, use `authoring-mwaa-workflow` to regenerate a
compliant artifact.

## Gotchas

- Serverless has no Airflow web UI, no REST API, and no CLI token. Do not
  attempt `create-web-login-token`, `invoke-rest-api`, or any Airflow REST
  path for Serverless.
- For Provisioned, always use `aws mwaa invoke-rest-api` (not
  `create-web-login-token` + curl). `invoke-rest-api` reaches VPC-only web
  servers without network access.
- `GetWorkflowRun.RunDetail.ErrorMessage` distinguishes a definition error
  (empty `TaskInstances`) from a task-execution failure (`Workflow execution
  failed`, populated `TaskInstances`). Read it before pulling task logs.
- The Serverless log group defaults to `/aws/mwaa-serverless/{workflow-id}/`
  but can be a custom group; confirm via `get-workflow` `LoggingConfiguration`
  before assuming the path.
- A DAG not appearing has several causes — an import/parse error, the scheduler
  scan interval (`scheduler.dag_dir_list_interval`, or `dag_processor.refresh_interval`
  on Airflow 3.x) not yet elapsed, a `dag_id` collision, or S3-sync delay — and
  is rarely a broken DAG. Check `GET /importErrors` and `GET /dags/{dag_id}` via
  invoke-rest-api (and the DAGProcessing logs); see the failure catalog's
  "DAG not appearing in the UI" checklist before concluding the code is wrong.
- A worker SIGKILL is an OOM signal. Recommend moving work to Glue/EMR/Lambda;
  scaling workers alone does not fix per-task memory pressure.
- MWAA re-resolves dependencies on environment update, so an unchanged DAG can
  start failing on import with no code change. Treat no-code-change import
  failures as drift.
- Serverless `PythonOperator`/`BashOperator` tasks run custom code from a
  `--code` package. A run that fails to extract the package or hits
  `ModuleNotFoundError` is a packaging problem (wrong-platform wheel, missing
  dep, bad layout), not a YAML definition error. See the failure catalog's
  serverless custom-code section.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `RestApiClientException` (Provisioned) | Mis-scoped execution role or service error | Fall back to Scheduler/DAGProcessing log groups |
| `ResourceNotFoundException` on get-workflow-run | Wrong workflow ARN or run id | Re-list with list-workflow-runs |
| Task log stream empty (Serverless) | Wrong log group assumed | Read `LoggingConfiguration` from get-workflow |
| No task logs but run FAILED | Definition/parse error | Read `RunDetail.ErrorMessage`; fix the YAML |

## References

- [references/provisioned-diagnostics.md](references/provisioned-diagnostics.md) — Provisioned data sources and read-only commands
- [references/serverless-diagnostics.md](references/serverless-diagnostics.md) — Serverless API, log group, failure classes
- [references/failure-catalog.md](references/failure-catalog.md) — category-keyed context checks and remediation

## Security Considerations

- **Read-only by default**: diagnosis uses only read/list/describe calls.
  Remediation (clear/rerun/backfill, IAM or key-policy changes) is presented as
  commands for the user to run, never executed autonomously.
- **Least-privilege IAM**: when an `AccessDenied` is a genuine permission gap,
  recommend the minimal `Action`/`Resource` from the error — never a wildcard;
  distinguish it from a nonexistent-resource typo (do not broaden IAM then).
- **Cross-account**: KMS key-policy / assume-role changes are human-gated and
  coordinated with the resource owner.
- **No secret exposure**: do not surface credentials or connection strings from
  logs or API responses in the diagnosis output.
