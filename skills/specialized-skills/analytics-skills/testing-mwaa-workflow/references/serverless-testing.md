# Serverless MWAA Testing

Trigger and monitor a run on MWAA Serverless (YAML workflow). The entire surface
is the `aws mwaa-serverless` API — no Airflow web UI, no REST API, no CLI token.

## Readiness (before the first trigger)

```bash
aws mwaa-serverless get-workflow --workflow-arn <arn>
```

Requires `--workflow-arn` (not `--name`). `WorkflowStatus: READY` means the
workflow is deployable and runnable. The YAML definition was validated
synchronously at CreateWorkflow/UpdateWorkflow, so a separate parse wait is
unnecessary; a non-READY status (CREATING, UPDATING, FAILED) means not ready —
for FAILED, hand to debugging-mwaa-workflow.

## Trigger

```bash
aws mwaa-serverless start-workflow-run --workflow-arn <arn>
```

Capture `RunId` from the response so the poll targets this exact run.

## Poll to terminal

```bash
aws mwaa-serverless get-workflow-run --workflow-arn <arn> --run-id <RunId>
```

Read `RunDetail.RunState`. Terminal states: `SUCCESS`, `FAILED`, `TIMEOUT`,
`STOPPED`. `STARTING`/`QUEUED`/`RUNNING`/`STOPPING` mean keep polling
(`STOPPING` transitions to `STOPPED`). Only `SUCCESS` is a pass.

JMESPath for scripted polling: `--query "RunDetail.RunState" --output text`.

On a non-SUCCESS terminal state, hand the workflow ARN and RunId to
debugging-mwaa-workflow, which reads `RunDetail.ErrorMessage` to split a
definition/parse error (empty `TaskInstances`) from a task-execution failure
(populated `TaskInstances`).
