# Serverless MWAA Diagnostics

Data sources for MWAA Serverless (YAML workflow) failure investigation.
Serverless has NO Airflow web UI, NO REST API, and NO CLI token. The entire
diagnostic surface is the `aws mwaa-serverless` API plus one CloudWatch log
group. All investigation operations are read-only; the remediation commands
at the end change state and are for the user to run.

## Run state and the three failure classes

1. `aws mwaa-serverless list-workflow-runs --workflow-arn <arn>` lists runs
   with `Status` (STARTING, QUEUED, RUNNING, SUCCESS, FAILED, TIMEOUT,
   STOPPING, STOPPED).
2. `aws mwaa-serverless get-workflow-run --workflow-arn <arn> --run-id <id>`
   returns `RunDetail`. The `RunDetail.ErrorMessage` field splits three failure
   classes:
   - **Definition/parse error** — `ErrorMessage` holds a parser message (for
     example `expected token ',', got 'create_test_table'`) and
     `TaskInstances` is empty. The workflow YAML never ran. Fix the definition.
   - **Task-execution failure** — `ErrorMessage` is `Workflow execution
     failed` and `TaskInstances` is populated. Drill into the failed task.
   - **Code-package failure** — the run fails to start task execution because
     the service could not extract the `--code` package or the package holds a
     corrupt Python environment. `ErrorMessage` references code extraction and
     `TaskInstances` may be empty. Fix the package (see the failure catalog's
     serverless custom-code section), not the YAML.

   Task-execution failures now include arbitrary Python exceptions
   (`PythonOperator`) and non-zero exits (`BashOperator`), not just AWS
   operator API errors — read the task log for the real traceback.
   `get-workflow` returns `Code` (`S3Location`) and `CodeSnapshottedAt`; use
   them to confirm which code version ran.

## Task logs

For a task-execution failure, resolve the log stream per task:

```bash
aws mwaa-serverless list-task-instances --workflow-arn <arn> --run-id <id> \
  --query 'TaskInstances[].TaskInstanceId' --output text \
| xargs -n 1 -I {} aws mwaa-serverless get-task-instance \
  --workflow-arn <arn> --run-id <id> --task-instance-id {} \
  --query '{Status: Status, StartedAt: StartedAt, LogStream: LogStream}'
```

`get-task-instance` returns a `LogStream` path. Read that stream in CloudWatch.

## CloudWatch log group

The default log group is `/aws/mwaa-serverless/{workflow-id}/` (the workflow-id
is the suffix in the workflow ARN). If the user supplied a custom log group at
workflow creation, this default is wrong: call `aws mwaa-serverless
get-workflow --workflow-arn <arn>` and read `LoggingConfiguration` to get the
actual log group name in use.

## Remediation (present to user; do not execute)

Serverless has no clear/rerun of a past run. Options:

- Re-trigger: `aws mwaa-serverless start-workflow-run --workflow-arn <arn>`.
- Fix-and-redeploy: correct the YAML and update the workflow (use
  authoring-mwaa-workflow to regenerate a compliant YAML).
