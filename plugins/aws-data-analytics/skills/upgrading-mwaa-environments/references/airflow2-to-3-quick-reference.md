# Migration Quick Reference

> Applies only when a version jump crosses the 2.x-to-3.x boundary (`crosses_major`). Not used for within-2.x or within-3.x upgrades.

Lookup tables for Phase 5 code fixes. For detection patterns (what to grep
for), see [airflow2-to-3-checklist.md](airflow2-to-3-checklist.md).

## Key Import Changes

| Airflow 2.x | Airflow 3 |
|---|---|
| `airflow.operators.dummy_operator.DummyOperator` | `airflow.providers.standard.operators.empty.EmptyOperator` |
| `airflow.operators.bash.BashOperator` | `airflow.providers.standard.operators.bash.BashOperator` |
| `airflow.operators.python.PythonOperator` | `airflow.providers.standard.operators.python.PythonOperator` |
| `airflow.operators.email.EmailOperator` | `airflow.providers.smtp.operators.smtp.SmtpOperator` |
| `airflow.sensors.external_task.ExternalTaskSensor` | `airflow.providers.standard.sensors.external_task.ExternalTaskSensor` |
| `airflow.operators.subdag.SubDagOperator` | Removed. Use `TaskGroup`. |
| `airflow.decorators.dag` | `airflow.sdk.dag` |
| `airflow.decorators.task` | `airflow.sdk.task` |
| `airflow.datasets.Dataset` | `airflow.sdk.Asset` |
| `airflow.contrib.*` | Removed. Use corresponding `airflow.providers.*` package. |

## Context Key Replacements

| Removed Key | Replacement |
|---|---|
| `execution_date` | `context["dag_run"].logical_date` |
| `tomorrow_ds` | `macros.ds_add(ds, 1)` |
| `yesterday_ds` | `macros.ds_add(ds, -1)` |
| `prev_ds` / `next_ds` | `prev_start_date_success` or timetable API |
| `triggering_dataset_events` | `triggering_asset_events` |
| `templates_dict` | `context["params"]` |

`logical_date` may be `None` for Asset-triggered runs. Guard with `context["dag_run"].logical_date`.

## Config Section Moves

| Old Section | New Section | Options |
|---|---|---|
| `[core]` | `[database]` | `sql_alchemy_conn`, `sql_alchemy_pool_size`, `sql_alchemy_pool_recycle`, `max_db_retries` |
| `[core]` | `[logging]` | `base_log_folder`, `remote_logging`, `remote_log_conn_id`, `logging_level`, `log_format` |

## Config Renames

| Old | New |
|---|---|
| `[scheduler]deactivate_stale_dags_interval` | `[scheduler]parsing_cleanup_interval` |
| `[scheduler]max_threads` | `[scheduler]parsing_processes` |
| `[webserver]web_server_host` | `[api]host` |
| `[webserver]session_lifetime_days` | `[webserver]session_lifetime_minutes` |
| `[webserver]update_fab_perms` | `[fab]update_fab_perms` |
| `[api]auth_backend` | `[api]auth_backends` |
| `[core]dag_concurrency` | `[core]max_active_tasks_per_dag` |
| `[kubernetes]` section | `[kubernetes_executor]` section |

## Default Behavior Changes

| Setting | Airflow 2 Default | Airflow 3 Default |
|---|---|---|
| `schedule` (DAG) | `timedelta(days=1)` | `None` (unscheduled) |
| `catchup` | `True` | `False` |
| `on_success_callback` | Fires on skip | Does NOT fire on skip (use `on_skipped_callback`) |
| `.airflowignore` syntax | regexp | glob (set `DAG_IGNORE_FILE_SYNTAX=regexp` to keep old) |

## REST API Endpoint Renames

| Old (v1) | New (v2) |
|---|---|
| `/api/v1/datasets` | `/api/v2/assets` |
| `/api/v1/datasets/{uri}` | `/api/v2/assets/{uri}` |
| `/api/v1/datasets/events` | `/api/v2/assets/events` |
| `/api/v1/roles` | `/auth/fab/v1/roles` † |
| `/api/v1/permissions` | `/auth/fab/v1/permissions` † |

> † `/auth/fab/v1/*` (roles, permissions) is the FAB auth-manager API, **not** the core API — unlike the `/api/v2/*` rows above, these are **not** reachable via `aws mwaa invoke-rest-api`; callers must use web-server session auth (`create-web-login-token` -> session cookie). See checklist item 9 (REST API v1).

## REST API Field Renames

| Old Field | New Field |
|---|---|
| `dataset_triggered` | `asset_triggered` |
| `dataset_expression` | `asset_expression` |
| `concurrency` (DAGDetail) | `max_active_tasks` |
| `schedule_interval` | `timetable_summary` |

## Metadata DB Access

See checklist item 1 in
[airflow2-to-3-checklist.md](airflow2-to-3-checklist.md) for detection
patterns and fix strategies (in-task Airflow REST API vs. CLI vs. external
data store).
