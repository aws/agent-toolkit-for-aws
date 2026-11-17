---
_fragment: artifacts-infra-workflow
_of_phase: generate
_contributes:
  - { file: terraform/workflow.tf, _when: "a Render Workflow is classified supported" }
---

# Generate Workflow infrastructure

Emit `terraform/workflow.tf` for a Render Workflow only when every semantic it needs is in the supported rubric below. The rubric is executable in `tests/render_workflow_asl.py` and proven by `tests/test_render_workflow_contracts.py`. Generate never claims Render execution parity: the tests prove the Step Functions definition matches the declared source semantics, not that Render and AWS behave identically at runtime.

## Where semantics come from

Discovery captures Workflow metadata, versions, tasks, runs, and attempts. It does not capture task code, retry settings, timeouts, or the task graph. Generate therefore reads semantics only from the Design `aws_config` of the `render.workflow` and `render.workflow_task` mappings (see `design-refs/workflows.md`) and never infers or defaults them. A key that is absent is not assumed.

## Classification is all or nothing per Workflow

Classify a Workflow and every task it owns (`task_order` plus any `compensation_task`) together. If every row passes the rubric, record them `generated` with target file `terraform/workflow.tf`. If any check fails, record the Workflow and all its tasks `unsupported` with empty `target_files`, emit one `conditional_workflow_generation_unsupported` warning whose `subject` is the Workflow ID and whose `detail` is the first failed reason (`<key>: <explanation>`), and emit no partial or approximate Terraform. A task owned by no supported Workflow is `unsupported` with `task_orphan`. A Workflow that is not `unsupported` produces no warning.

## Supported semantics

Only the orchestrator `AWS Step Functions Standard` is generated. Task targets are `AWS Lambda` and `ECS on Fargate task`.

| Semantic | Declared by (`aws_config`) | Step Functions mapping | Contract test |
| --- | --- | --- | --- |
| Task sequence | Workflow `task_order`, at least one unique mapped task | `StartAt` is the first task state, `Next` follows `task_order`, the last state has `End` | `test_sequence_chain_matches_task_order` |
| Lambda task | task `aws_service` is `AWS Lambda` | `arn:aws:states:::lambda:invoke`, `Payload.$` is the state input, `OutputPath` is `$.Payload` | `test_lambda_task_integration_and_packaging` |
| ECS Fargate task | task `aws_service` is `ECS on Fargate task` | `arn:aws:states:::ecs:runTask.sync`, `LaunchType` `FARGATE`, private subnets, the worker security group, no public IP. The state input (the item inside a Map) reaches the container as the `STEP_INPUT` environment variable through `Overrides.ContainerOverrides` and `States.JsonToString($)`, within the 8192-character `RunTask` overrides limit. `runTask.sync` returns the task description, not container output, so `ResultPath` is `null`: the input passes through to the next state, a Map fan-in array holds the items, and the container returns no data to the Workflow | `test_ecs_task_integration_and_iam`, `test_every_supported_ecs_state_receives_input` |
| Per-attempt timeout | exactly one of `timeout_seconds` or `timeout_minutes`, 30 to 86400 seconds, at most 900 for Lambda | `TimeoutSeconds` on the Task state, equal Lambda `timeout` | `test_timeout_matches_source_and_lambda_bound` |
| Retry with backoff | task `retry` with `max_retries` (at least 1), `wait_duration_ms` (whole seconds), `backoff_scaling` (at least 1.0) | `Retry` with `MaxAttempts` = `max_retries`, `IntervalSeconds` = `wait_duration_ms / 1000`, `BackoffRate` = `backoff_scaling`, `ErrorEquals` `States.TaskFailed` and `States.Timeout` | `test_retry_mapping_exact_and_absent_means_unsupported` |
| Fan-out and fan-in | task `fan_out` with `max_concurrency` 1 to 40 | Inline `Map`, `ItemsPath` `$.items`, `MaxConcurrency` as declared, no tolerated-failure fields, so any item failure fails the Map and the result array is the fan-in | `test_fan_out_fan_in_map_structure` |
| Failure catch with compensation | task `compensation_task` naming a mapped task outside `task_order` | `Catch` on `States.ALL` with `ResultPath` `$.error` routes to `Compensate_<state>`, which runs the compensation task and then a `Fail` state `CompensatedFailure`, so a compensated run still ends failed. No `compensation_task` means no `Catch` | `test_catch_routes_to_compensation_then_fail` |
| Callback by task token | Workflow `callbacks` true (every Lambda task in `task_order` waits for a token) with `callback_timeout_seconds` at least every task timeout | Lambda `invoke.waitForTaskToken`, `TaskToken.$` is `$$.Task.Token`, state `TimeoutSeconds` is the callback timeout, `Retry` on `States.TaskFailed` only so a timed-out token wait is never re-issued | `test_callback_uses_task_token_and_timeout` |
| Retained history and observability | Workflow `history` is `auditable` | `type` `STANDARD`, execution logging `ALL` without execution data, log retention from a validated variable, optional X-Ray, alarms on failed, timed-out, and aborted executions | `test_standard_logging_retention_and_alarms` |
| Least-privilege IAM | derived | see IAM below | `test_iam_scope_is_exact` |

## Unsupported semantics

Each unsupported condition returns its reason key as the start of the warning `detail`.

| Reason key | Condition |
| --- | --- |
| `orchestrator_unsupported` | Orchestrator is Lambda durable functions or Step Functions Express; only Standard has contract tests |
| `history_not_auditable` | `history` is not `auditable` |
| `task_target_unsupported` | A task targets AWS Batch or anything other than Lambda or ECS Fargate task |
| `branching_unsupported`, `dynamic_graph_unsupported` | `branching` or `dynamic_graph` is truthy; the graph lives in customer code and is not captured |
| `approvals_unsupported` | `approvals` is truthy; approval identity and UX are not provable from the source |
| `trigger_unsupported`, `schedule_unsupported` | `trigger` or `schedule` is truthy; Render starts runs through its API or SDK and no Step Functions starter is tested |
| `idempotency_key_unsupported`, `concurrency_unsupported`, `cancellation_unsupported` | `idempotency_key`, `concurrency`, or `cancellation` is truthy; Step Functions has no matching execution-level control |
| `task_order_missing`, `task_order_unmapped_task` | `task_order` is absent, empty, has duplicates, or names an ID that is not a mapped `render.workflow_task` |
| `timeout_missing`, `timeout_invalid`, `timeout_out_of_bounds`, `lambda_timeout_over_900` | Timeout absent, ambiguous, outside 30 to 86400 seconds, or over 900 seconds for Lambda; Render's default is not assumed |
| `retry_missing`, `retry_invalid` | `retry` is absent (Render applies an undocumented default retry when omitted) or has fields other than the three declared, a zero retry count, sub-second or fractional-second waits, or `backoff_scaling` below 1.0 |
| `fan_out_invalid` | `fan_out` is not exactly `max_concurrency` between 1 and 40 |
| `compensation_invalid` | `compensation_task` is unmapped, inside `task_order`, uses `fan_out`, or has its own `compensation_task` |
| `callbacks_invalid`, `callback_timeout_missing`, `callback_timeout_without_callbacks`, `callback_timeout_below_task_timeout` | `callbacks` is not boolean, or `callback_timeout_seconds` is absent, present without callbacks, or below a task timeout |
| `callback_ecs_unsupported`, `callback_fan_out_unsupported` | A callback on an ECS task, or combined with Map fan-out, has no contract test |
| `task_shared` | A task is owned by more than one Workflow |
| `task_orphan` | A task is not in any supported Workflow |
| `workflow_unsupported` | The row belongs to a Workflow that failed another check |
| `source_record_not_importable` | `render.workflow_version`, `render.task_run`, and `render.task_attempt` are source evidence with no importable AWS equivalent; Render run history is not migrated |

Unknown `aws_config` keys are ignored. Payloads over 256 KiB, Render execution timing, and Render platform-side retries are not tested and never claimed.

## `terraform/workflow.tf`

Emit one file with no values taken from the capture.

- Variables: `workflow_log_retention_days` (default is the resolved Clarify answer `observability.log_retention`, 30 days when unanswered; validated against CloudWatch retention values), `workflow_tracing_enabled` (default false), `workflow_alarm_actions` (default empty). Each task adds typed, validated variables with no default: for Lambda `<task>_package_path`, `<task>_runtime`, `<task>_handler`, `<task>_memory_mb`; for ECS `<task>_image` (immutable ECR digest), `<task>_cpu`, `<task>_memory_mb`. Render compute plans are not converted.
- Definition: `aws_sfn_state_machine` with `type = "STANDARD"` and `definition = jsonencode(...)` of the ASL above. Function, task definition, subnet, and security group values are Terraform references, never literals. State names are the task source ID with non-alphanumerics mapped to `_`.
- Lambda packaging: `aws_lambda_function` with `filename` and `source_code_hash = filebase64sha256(...)` from the owner's package variable. Emit no source code, inline archive, or `archive_file`. Each function gets its own log group and a role that can only write that log group.
- ECS tasks: one `aws_ecs_task_definition` per task. It references the compute-owned `aws_ecs_cluster.main`, execution role `aws_iam_role.ecs_execution` and task role `aws_iam_role.ecs_task` (set as `task_role_arn`), plus `aws_subnet.private` and `aws_security_group.worker` from the network fragment. Declare none of them here. They exist only when `compute.tf` is generated, so a stack whose only ECS use is a Workflow task needs the compute fragment to run too (a dependency on the compute trigger in `generate.md`, which this fragment does not edit). Each task gets its own log group (retention from `workflow_log_retention_days`) and an `awslogs` `logConfiguration` on the container with that group, the `var.aws_region` region and a stream prefix. Do not add public IPs.
- Logging: a log group named under `/aws/vendedlogs/states/`, `logging_configuration` level `ALL` with `include_execution_data = false`, retention from `workflow_log_retention_days`. Step Functions keeps Standard execution history for 90 days independent of this log group.
- Tracing: `tracing_configuration` follows `workflow_tracing_enabled`; X-Ray permissions are added only while it is true.
- Alarms: `aws_cloudwatch_metric_alarm` on `ExecutionsFailed`, `ExecutionsTimedOut`, and `ExecutionsAborted` with `alarm_actions = var.workflow_alarm_actions`.
- No dead-letter queue: Step Functions invokes tasks synchronously, so no asynchronous delivery exists to drop. Failed executions surface through the alarms.
- Tags: `SourceResourceId` with the Render source ID.

## IAM

The state machine role has two inline policies.

- `<workflow>_tasks` is a literal `jsonencode` policy scanned by the policy validator. It allows `lambda:InvokeFunction` only on the declared function ARNs, and for ECS tasks `ecs:RunTask` only on the declared task definition ARNs, `iam:PassRole` only on `aws_iam_role.ecs_execution` and `aws_iam_role.ecs_task`, the two roles every task definition passes, with `iam:PassedToService` `ecs-tasks.amazonaws.com`, and `events:PutTargets`, `events:PutRule`, `events:DescribeRule` only on the `StepFunctionsGetEventsForECSTaskRule` managed rule.
- `<workflow>_service` is an `aws_iam_policy_document` holding the actions AWS documents as requiring `Resource` `*`: log delivery, X-Ray (inside a dynamic statement tied to `workflow_tracing_enabled`), and `ecs:StopTask` and `ecs:DescribeTasks` (Step Functions can only stop tasks it started). Nothing else uses `*`.

Do not grant `states:SendTaskSuccess`, `states:SendTaskFailure`, or `states:SendTaskHeartbeat`; AWS has no resource-level scoping for them. The migration guide tells the owner to grant them to the callback sender. Do not grant `states:StartExecution`; the caller that replaces Render's run API owns it.

## Ledger and report

For a supported Workflow, `generation-warnings.json` lists the Workflow and each owned task under `generated` with `target_files` `["terraform/workflow.tf"]` and states that Render execution parity is not claimed. For any other Workflow follow the classification rule above. The report and `MIGRATION_GUIDE.md` follow `generate-artifacts-report.md` and `generate-artifacts-docs.md`.
