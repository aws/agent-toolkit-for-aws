# MWAA Serverless YAML Schema Reference

<!-- Engine versions (Airflow, providers-amazon, Python) come from the AWS doc
     fetched in B3 step 0. This file covers YAML structure and validation rules. -->

## Source of truth (verify at runtime)

The authoritative, current sets are the AWS docs; fetch them at runtime. The
tables below are a snapshot to verify against, not the final word:

- DAG/task parameters: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/supported-airflow-parameters.html
- Template/Jinja parameters: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/supported-jinja-parameters.html
- Operators: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/operators.html

## Supported DAG-Level Parameters

| Parameter | Validation Rule | Default |
|-----------|----------------|---------|
| dag_id | Non-empty string | -- |
| schedule | Cron expression, or `null` (unscheduled) | -- |
| start_date | Date string (YYYY-MM-DD) | -- |
| end_date | After or equal to start_date | -- |

`schedule` must be a cron expression or `null` (unscheduled, manual-trigger only) — no Datasets/Assets.
<!-- Limits verified against: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/supported-airflow-parameters.html -->

## Unsupported DAG-Level Parameters (ignored)

description, catchup, dagrun_timeout, tags, access_control,
on_failure_callback, on_success_callback, sla_miss_callback,
is_paused_upon_creation, max_active_runs, depends_on_past,
email_on_failure, email_on_retry, max_consecutive_failed_dag_runs.

NOTE: `description` in the YAML body is silently ignored. Pass workflow
descriptions via `--description` on `create-workflow`/`update-workflow`.

## Supported Task-Level Parameters

| Parameter | Validation Rule | Default |
|-----------|----------------|---------|
| task_id | Valid string | -- |
| retries | 0 to 3 | 1 |
| retry_delay | 0 to 300 seconds | 300s |
| execution_timeout | Max 3600 seconds | 3600s |

> These ranges are the values verified against the AWS supported-airflow-parameters
> doc; confirm them at runtime, as service parameter constraints can change.
<!-- Limits verified against: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/supported-airflow-parameters.html -->

## Unsupported Task-Level Parameters (ignored)

deferrable, on_failure_callback, on_success_callback, on_retry_callback,
on_execute_callback, on_skipped_callback, trigger_rule, outlets, inlets,
retry_exponential_backoff, max_retry_delay, pool, pool_slots, queue,
priority_weight, executor, do_xcom_push, multiple_outputs, start_date,
end_date, weight_rule, owner, email.

## Timedelta Format (REQUIRED)

```yaml
# WRONG - causes ValidationException
execution_timeout: 900

# CORRECT
execution_timeout:
  __type__: datetime.timedelta
  seconds: 900
```

Same format for `retry_delay`.

## AWS Base Operator Attributes

| Parameter | MWAA Provisioned | MWAA Serverless |
|-----------|-----------------|-----------------|
| aws_conn_id | Supported | Controlled by service (omit) |
| verify | Supported | Not supported |
| botocore_config | Supported | Not supported |
| region_name | Supported | Omit — inherited from environment |

## Task Dependencies

```yaml
task_b:
  operator: ...
  dependencies: [task_a]

# Multiple upstream:
task_c:
  operator: ...
  dependencies: [task_a, task_b]
```

Tasks without `dependencies` run in parallel.

## Operators (common cases; full authoritative list: operators.html at runtime)

Verify any specific operator against the operators doc linked above at runtime;
the supported set evolves.

**Supported (high-signal):** `PythonOperator` and `BashOperator` for custom code
(see "Custom Code (Python/Bash)" below); plus AWS provider operators across
Storage (S3), Catalog (Glue), Analytics (Athena / Glue jobs / Redshift Data /
EMR / QuickSight), ML (SageMaker, Bedrock), Compute (Lambda / Batch / ECS), and
Application Integration (SNS / SQS / Step Functions / MwaaServerless).

**Not supported (verify at runtime — the supported set evolves):** `BranchPythonOperator`, the `@task` decorator,
branching, `SubDagOperator`, `S3ToRedshiftOperator`, `MwaaTriggerDagRunOperator`.

## Custom Code (Python/Bash)

MWAA Serverless runs custom Python/Bash natively:

- `PythonOperator` — `airflow.providers.standard.operators.python.PythonOperator`
  (Airflow 3 form) or `airflow.operators.python.PythonOperator`. Requires
  `python_callable` as `module_name.function_name`.
- `BashOperator` — `airflow.providers.standard.operators.bash.BashOperator`
  or `airflow.operators.bash.BashOperator`. Requires `bash_command`.

Code ships via the `--code` S3 package. See
[serverless-code-packaging.md](serverless-code-packaging.md) for packaging,
pre-installed packages, and limits.
