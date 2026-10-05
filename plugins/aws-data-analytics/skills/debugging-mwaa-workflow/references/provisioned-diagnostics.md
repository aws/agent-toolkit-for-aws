# Provisioned MWAA Diagnostics

Data sources for MWAA Provisioned (Python DAG) failure investigation. All
investigation operations are read-only; the remediation commands at the end
change state and are for the user to run.

## Environment facts (always start here)

- `aws mwaa get-environment --name <env>` returns Airflow version, environment
  class, `LoggingConfiguration` (which CloudWatch log groups are enabled and at
  what level), `AirflowConfigurationOptions`, `MinWorkers`/`MaxWorkers`,
  execution role ARN, and S3 `SourceBucketArn` / `DagS3Path` /
  `RequirementsS3Path` / `PluginsS3Path`.
- `aws mwaa list-environments` resolves the environment name when the user is
  vague.

## CloudWatch component log groups (primary log source)

MWAA delegates all logging to CloudWatch. The Airflow REST API task-instance
logs endpoint (`/taskInstances/{id}/{try}/logs`) is unreliable — it may return
empty content or an error. Always fetch task log content directly from
CloudWatch using `aws logs filter-log-events` with the Task log group and a
filter pattern matching the task ID or DAG run ID.

`LoggingConfiguration` in `get-environment` gives the exact log group ARNs.
Component-to-symptom mapping:

| Component | Log group suffix | Read when |
|-----------|------------------|-----------|
| DAGProcessing | `-DAGProcessing` | DAG not appearing, import errors |
| Scheduler | `-Scheduler` | run never started, scheduling gaps |
| Task | `-Task` | a task failed; the real exception is here |
| Worker | `-Worker` | SIGKILL/OOM, task stuck, autoscaling |
| WebServer | `-WebServer` | UI 5xx, login failures |

Read logs with `aws logs filter-log-events --log-group-name <name>
--start-time <ms>` or the CloudWatch Logs MCP tool if available.

## Airflow REST API via invoke-rest-api (run and task state)

All Airflow REST API calls use `aws mwaa invoke-rest-api` — a single AWS API
call that proxies the request through the MWAA control plane. No
`create-web-login-token`, no curl, no session exchange. `invoke-rest-api`
reaches private (VPC-only) web servers that are otherwise inaccessible.

`invoke-rest-api` returns `{"RestApiStatusCode": <int>, "RestApiResponse": {...}}`.
Read the run/task state from `RestApiResponse`.

### List failed DAG runs

```bash
aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
  --method GET --query-parameters '{"order_by": "-start_date", "limit": "5"}'
```

Read `RestApiResponse.dag_runs[].state`. Filter for `failed`.

### Get task instances for a failed run

Use the collection endpoint and pass the run in query parameters — the
`--path` is capped at 64 characters (MWAA `InvokeRestApi`), and the per-run
path below often exceeds it:

```bash
aws mwaa invoke-rest-api --name <env> \
  --path /dags/<dag_id>/taskInstances --method GET \
  --query-parameters '{"dag_run_id":"<run_id>","limit":"100","offset":"0"}'
```

The per-run path is shorter to read but embeds `<run_id>` in the path, so
`/dags/<dag_id>/dagRuns/<run_id>/taskInstances` frequently exceeds the 64-char
limit and is rejected with an opaque `RestApiClientException`; use it only when
the fully-substituted path stays under 64 characters:

```bash
aws mwaa invoke-rest-api --name <env> \
  --path /dags/<dag_id>/dagRuns/<run_id>/taskInstances --method GET
```

Read `RestApiResponse.task_instances[].state`. Failed tasks carry the exception
in their Task log group (see above). **Both forms paginate** (Airflow REST
default `limit` 100): a run using dynamic task mapping (`.expand()`) can have
more than 100 task instances, so re-issue with `offset` incremented by 100
until you have read `total_entries` — otherwise failed mapped tasks beyond the
first 100 are missed.

### Check DAG registration / parse state (a DAG not appearing)

```bash
# Import/parse errors across all files (traceback + filename); paginated
# (default limit 100) — loop offset until total_entries when a shared module
# breaks many files
aws mwaa invoke-rest-api --name <env> --path /importErrors --method GET \
  --query-parameters '{"limit":"100","offset":"0"}'

# Registration state of one DAG: last_parsed_time, fileloc, is_active (2.x) / is_stale (3.x)
aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id> --method GET
```

Read `RestApiResponse`. A file listed under `/importErrors` failed to parse —
fix the code and it re-registers on the next scan. If `GET /dags/<dag_id>`
returns 404 the DAG has not registered yet: wait one
`scheduler.dag_dir_list_interval` (Airflow 2.x) /
`dag_processor.refresh_interval` (Airflow 3.x) scan cycle, or check for a
duplicate `dag_id`. `last_parsed_time` and `fileloc` (both 2.x and 3.x) confirm
it parsed and which file won a `dag_id` collision; read `is_active` on Airflow
2.x, or `is_stale` (inverted) on Airflow 3.x, and `has_import_errors` for a
parse failure.

### Fallback

A `RestApiClientException` (rare — possible on a mis-scoped execution role)
means `invoke-rest-api` cannot reach the web server. Fall back to the Scheduler
and DAGProcessing CloudWatch log groups for run/task state.

## Remediation commands (present to user; do not execute)

- Clear and rerun a task:

  ```bash
  aws mwaa invoke-rest-api --name <env> \
    --path /dags/<dag_id>/clearTaskInstances --method POST \
    --body '{"dry_run": false, "task_ids": ["<task_id>"], "dag_run_id": "<run_id>"}'
  ```

- Trigger a new run (body differs by Airflow major):

  ```bash
  # Airflow 3.x (REST v2): logical_date, NO top-level conf
  aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
    --method POST --body '{"dag_run_id": "<explicit-id>", "logical_date": "<unique-ISO8601-UTC>"}'
  # Airflow 2.x (REST v1): conf accepted, logical_date not required
  aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
    --method POST --body '{"dag_run_id": "<explicit-id>", "conf": {}}'
  ```

- Backfill: run `airflow dags backfill` through the MWAA CLI token endpoint
  (`aws mwaa create-cli-token`).

These change environment state. Present the exact command and its impact; let
the user run it (production safety).
