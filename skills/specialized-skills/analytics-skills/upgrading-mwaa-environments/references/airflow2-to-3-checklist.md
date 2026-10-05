# Migration Checklist — Grep Patterns Beyond Ruff AIR Rules

> Applies only when a version jump crosses the 2.x-to-3.x boundary (`crosses_major`). Not used for within-2.x or within-3.x upgrades.

Patterns that require manual grep/search because Ruff AIR30x rules do not cover them.

## 1. Direct metadata DB access

Search for: `provide_session`, `create_session`, `@provide_session`, `from airflow.settings import Session`, `from airflow.settings import engine`, `session.query(`, `engine.connect(`

**Availability changes across the major boundary (surface this to the user).**
On AF2, DAG tasks can open a session against the environment metadata DB. On
AF3, MWAA no longer exposes the metadata DB to worker tasks, so any DAG that
opens a metadata-DB session **works on AF2 and stops functioning on AF3**. Warn
the user explicitly: these DAGs must be redesigned before the cross-major version jump,
or dropped. This applies regardless of which upgrade approach you choose.

Fix depends on what the code queries:

- **Airflow metadata tables** (DagRun, TaskInstance, Variable, Pool, etc.):
  Redesign to the Airflow REST API — either call the environment **webserver**
  REST API in-VPC (web login token), or use `aws mwaa invoke-rest-api`. Note
  `invoke-rest-api` has a **low call-rate limit**, so batch/paginate and avoid
  per-row calls. For `airflow db` CLI invocations in BashOperator, see section 16 for the
  MWAA CLI endpoint workaround.
- **Non-Airflow tables** (custom application data stored in the metadata DB):
  Migrate the query to a dedicated data store (RDS, DynamoDB) via a separate
  Airflow connection. MWAA does not expose the metadata DB for arbitrary SQL
  in AF3.

## 2. Legacy imports

Search for: `from airflow.contrib`, `from airflow.operators.` (without `.providers`), `from airflow.hooks.` (without `.providers`)
Fix: Map each to the equivalent `apache-airflow-providers-*` import path.

## 3. Removed/renamed DAG arguments

Search for: `schedule_interval=`, `timetable=`, `days_ago(`, `fail_stop=`, `concurrency=` (DAG constructor), `sla=`, `sla_miss_callback`, `task_concurrency=`
Fix: `schedule_interval`/`timetable` -> `schedule=`. `days_ago` -> `pendulum.today("UTC").add(days=-N)`. `fail_stop` -> `fail_fast`. `concurrency` -> `max_active_tasks`. `sla`/`sla_miss_callback` -> removed; use CloudWatch alarms. `task_concurrency` -> `max_active_tis_per_dag`.

## 4. Deprecated context keys

Search for: `execution_date`, `prev_ds`, `next_ds`, `yesterday_ds`, `tomorrow_ds`, `templates_dict`
Fix: `execution_date` -> `context["dag_run"].logical_date`. `tomorrow_ds`/`yesterday_ds` -> `macros.ds_add(ds, 1)`/`macros.ds_add(ds, -1)`. `prev_ds`/`next_ds` -> `prev_start_date_success` or timetable API. `templates_dict` -> `context["params"]`.

## 5. XCom pickling

Search for: `ENABLE_XCOM_PICKLING`, `.xcom_pull(` without `task_ids=`
Fix: Use JSON-serializable data or a custom XCom backend.

## 6. Datasets to Assets

Search for: `airflow.datasets`, `triggering_dataset_events`, `DatasetOrTimeSchedule`, `on_dataset_created`, `on_dataset_changed`, `outlet_events["`, `inlet_events["`
Fix: `airflow.datasets` -> `airflow.sdk.Asset`. `triggering_dataset_events` -> `triggering_asset_events`. `DatasetOrTimeSchedule` -> `AssetOrTimeSchedule`. `on_dataset_created`/`on_dataset_changed` -> `on_asset_created`/`on_asset_changed`. Use `Asset(name=...)` objects as keys.

## 7. Removed operators

Search for: `SubDagOperator`, `SimpleHttpOperator`, `DagParam`, `DummyOperator`
Fix: `SubDagOperator` -> TaskGroups. `SimpleHttpOperator` -> `HttpOperator` (providers-http). `DagParam` -> `Param`. `DummyOperator` -> `EmptyOperator` (providers-standard).

## 8. Email changes

Search for: `airflow.operators.email.EmailOperator`, `airflow.utils.email`
Fix: Use `apache-airflow-providers-smtp` with `SmtpNotifier`.

## 9. REST API v1

Search for: `/api/v1`, `auth=(` (basic auth patterns), `execution_date` in API params
Fix: Update to `/api/v2` with bearer tokens. Replace `execution_date` with `logical_date`. Endpoint renames: `/api/v1/datasets` -> `/api/v2/assets`, `/api/v1/roles` -> the FAB auth-manager API `/auth/fab/v1/roles` (roles/users/permissions moved out of the core API into the `apache-airflow-providers-fab` provider). The FAB endpoint is NOT reachable via `aws mwaa invoke-rest-api` (which only proxies the core `/api/v2` API) — callers must use web-server session auth (`create-web-login-token` -> session cookie).

## 10. File paths and shared utility imports

Search for: `import common`, `from common`, `import utils`, `from utils` (bare imports), `sys.path.append`, `sys.path.insert`
Fix: Use fully qualified imports (`from dags.common.utils import helper`). Anchor paths with `__file__` or `AIRFLOW_HOME`.

## 11. FAB-based plugins

Search for: `appbuilder_views`, `appbuilder_menu_items`, `flask_blueprints`, `AirflowPlugin`
Fix: FAB plugins need manual migration; recommend a separate PR. MWAA continues using FAB for auth on Airflow 3.

## 12. Configuration file changes

Search for: `AIRFLOW__CORE__SQL_ALCHEMY`, `AIRFLOW__CORE__REMOTE_LOGGING`, `AIRFLOW__CORE__BASE_LOG_FOLDER`, `AIRFLOW__CORE__DAG_CONCURRENCY`, `AIRFLOW__SCHEDULER__DEACTIVATE_STALE_DAGS_INTERVAL`, `AIRFLOW__WEBSERVER__BASE_URL`, `AIRFLOW__KUBERNETES__`
Fix: Update env var section/key names per config-moves in quick-reference.

## 13. Policy rename

Search for: `def policy(` in `airflow_local_settings.py`
Fix: Rename function to `task_policy`.

## 14. Callback and behavior changes

Search for: `on_success_callback` (no longer fires on skip), `trigger_rule="dummy"`, `TriggerRule.DUMMY`, `trigger_rule="none_failed_or_skipped"`, `expanded_ti_count`, `external_trigger`, `test_mode`
Fix: Use `on_skipped_callback` for skip handling. `TriggerRule.DUMMY` -> `TriggerRule.ALWAYS`. `trigger_rule="none_failed_or_skipped"` -> `TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS`. `expanded_ti_count` -> REST API for mapped TIs. `external_trigger` -> `dag_run.run_type`. Remove `test_mode` reliance.

## 15. TaskFlow `_TaskDecorator.output` removal

Search for: `.output` preceded by a `@task`-decorated function name (e.g., `my_task.output`, `create_cluster.output`)
Ruff AIR rules do NOT detect this pattern.

In AF2, `@task`-decorated functions expose a `.output` property on the decorator
object that resolves to an XCom reference. In AF3, `_TaskDecorator.output` is
removed entirely — accessing it raises `AttributeError`.

Fix: Replace `<decorator_name>.output` with the variable holding the decorated
function's call result. The call result is already an XCom-backed reference in
both AF2 and AF3.

```python
# BEFORE (AF2 pattern — fails on AF3)
@task
def create_cluster(subnet_id):
    ...
    return cluster_id

create_cluster(subnet_id)
next_task = SomeOperator(cluster_id=create_cluster.output)

# AFTER (works on both AF2 and AF3)
@task
def create_cluster(subnet_id):
    ...
    return cluster_id

result = create_cluster(subnet_id)
next_task = SomeOperator(cluster_id=result)
```

**Ruff `--unsafe-fixes` can INTRODUCE this pattern.** `ruff --fix
--unsafe-fixes` (used in the upgrade skill's Phase 5) rewrites some `xcom_pull`
Jinja templates (e.g. `"{{ task_instance.xcom_pull(task_ids='t') }}"`) into
`t.output` — the exact AF3-invalid form shown above — and then does NOT re-flag
it. So the original code can be clean of `.output` while the *fixed* code is
not. Always re-run this section's grep on the **fixed** output after any
`--unsafe-fixes` pass, not just on the original DAGs.

## 16. Airflow CLI access from worker tasks

Search for: any `airflow` CLI invocation inside a BashOperator or `@task`
shell-out — most commonly `airflow db clean`, `airflow db check`, or other
`airflow db` subcommands.

### What breaks and why

On AF2, a BashOperator can invoke `airflow db clean ...` directly because the
worker process has the metadata DB connection string configured. On AF3 MWAA,
the standalone `airflow` CLI crashes on worker initialization with
`sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL` — the metadata
DB URL is not exposed to the worker environment.

This affects ALL standalone `airflow` CLI invocations from BashOperator or
`@task` shell-outs, not just `db` commands. Any DAG that shells out to the
`airflow` binary will fail on AF3 workers.

### Redesign path: MWAA CLI endpoint

The MWAA CLI endpoint (webserver-side, accessed via `create-cli-token` + HTTP
POST) still supports certain `db` subcommands. Not all subcommands are
permitted — the endpoint explicitly blocks some (e.g., `db migrate`, `db
reset`). The agent must verify each command before committing to this path.

Steps to convert:

1. Run `cheat-sheet` via the MWAA CLI endpoint on the target environment to
   discover available commands and their exact syntax for that Airflow version.
   Do not assume command renames — verify names against `cheat-sheet` output.
2. Test the specific command the DAG needs via the CLI endpoint. Use
   `--dry-run` where available. Note: MWAA CLI requires `-y` for any command
   that prompts for confirmation (the endpoint does not support interactive
   prompts). If the endpoint returns "sub command not allowed", this command
   cannot use the CLI endpoint path — fall back to REST API or drop the DAG.
3. Convert the BashOperator DAG to a Python task that calls `boto3`
   `mwaa.create_cli_token()`, then HTTP POSTs the command to
   `https://{webserver_hostname}/aws_mwaa/cli`. Parse the base64-encoded
   stdout/stderr from the JSON response.
4. If the command is blocked at the endpoint and no REST API equivalent exists,
   warn the user that this DAG must be dropped or redesigned outside MWAA.
