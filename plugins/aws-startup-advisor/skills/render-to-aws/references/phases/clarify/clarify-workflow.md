---
_fragment: workflow
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify Workflow requirements

For each Workflow, resolve whether orchestration is code-centric checkpointing or separately modeled state; total and per-step duration; waits; branching and fan-out/fan-in; callbacks; approvals; audit/history; compensation; broad AWS service coordination; volume and delivery guarantees; retries; idempotency keys; concurrency; trigger/schedule; state retention; and failure/cancellation behavior.

For every task class, independently resolve runtime/package, duration, memory/CPU, container requirement, VPC/filesystem access, queue behavior, array-job or GPU/specialized-compute needs, side effects, retries, and idempotency. These facts must select exactly one task target: Lambda, ECS/Fargate task, or AWS Batch.

Do not infer live Render parity from documented source or an unexecuted fixture. Missing orchestration or task eliminators return to Clarify. Conditional unsupported artifact generation does not permit Design to defer the Workflow decision.
## Structured Workflow answers
Resolve these rows after the prose questions above. The `Consumer` column names the Generate rubric that reads the structured key, which fails closed when a required key is missing. All rows use topic `workflow`. The `Resource` column says which inventory resource owns the answer.

| `question_id` | Resource | Topic | Ask when | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- | --- | --- |
| `workflow.orchestration_shape` | each Workflow | `workflow` | the inventory contains a Workflow | none. Unresolved until the user says whether the flow is code-centric checkpointing or separately modeled state. | Workflow orchestrator | Design workflow orchestrator selector. |
| `workflow.task_duration` | each Workflow task | `workflow` | the inventory contains a Workflow task | none. Unresolved until the user gives the longest run time. | Workflow task target | Design per-task target selector. |
| `workflow.task_order` | each Workflow | `workflow` | the Workflow has more than one task | none. Unresolved until the user gives the task order as `task_order`. | Generated state machine order (`task_order`) | `generate-infra-workflow.md` |
| `workflow.callback_wait` | each Workflow | `workflow` | the Workflow waits for a callback or approval | none. Unresolved until the user gives the wait limit; recorded as `callbacks` and `callback_timeout_seconds`. | Callback timeout on the task token state | `generate-infra-workflow.md` |
| `workflow.timeout` | each Workflow | `workflow` | always, for each Workflow | none. Unresolved until the user gives a total time limit; recorded as `timeout_seconds` or `timeout_minutes`. | Workflow execution timeout | `generate-infra-workflow.md` |
| `workflow.task_retry` | each Workflow task | `workflow` | the inventory contains a Workflow task | none. Unresolved until the user gives `max_retries`, `wait_duration_ms` and `backoff_scaling`, or states that the task is not retried. | Task retry policy (`retry`) | `generate-infra-workflow.md` |
| `workflow.fan_out_concurrency` | each Workflow | `workflow` | the Workflow fans out over a list or runs tasks in parallel | none. Unresolved until the user gives `fan_out.max_concurrency`. | Parallel task limit (`fan_out.max_concurrency`) | `generate-infra-workflow.md` |
| `workflow.compensation` | each Workflow | `workflow` | a task has side effects that must be undone on failure | none. Unresolved until the user names the `compensation_task` or says none exists. | Compensation task (`compensation_task`) | `generate-infra-workflow.md` |
| `workflow.history` | each Workflow | `workflow` | always, for each Workflow | none. Unresolved until the user says whether execution history must be kept and for how long (`history`). | Execution history and logging (`history`) | `generate-infra-workflow.md` |

When no Workflow task exists, mark the task rows `not_applicable` with that fact as evidence.
