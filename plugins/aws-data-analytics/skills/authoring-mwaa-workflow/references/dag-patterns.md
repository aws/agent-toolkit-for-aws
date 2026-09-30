# DAG Patterns Reference

## Package Availability

MWAA pre-installs only Airflow core, the Amazon provider package, and their
transitive dependencies. Do not assume any other Python package (pandas,
pyarrow, numpy, scikit-learn, etc.) is available at task runtime. If DAG code
needs a package not in the base image:

- Add it to `requirements.txt` (installed at environment startup). Pin every
  package to an exact version and install against the Apache Airflow constraints
  file that matches the environment's Airflow and Python version
  (`--constraint "https://raw.githubusercontent.com/apache/airflow/constraints-<AIRFLOW_VERSION>/constraints-<PY_VERSION>.txt"`,
  with the exact URL fetched at runtime). Unpinned or unconstrained requirements
  are the most common cause of a failed environment update — a transitive
  dependency resolves to a version incompatible with the pinned Airflow.
- Or delegate the work to a managed service (Glue for Spark/pandas, SageMaker
  for ML, Lambda for lightweight transforms) that has its own runtime.

A `ModuleNotFoundError` at task execution (not at parse time) means the import
is inside a task callable and the package is not installed. The fix is
requirements.txt or delegation — not inlining the install in the DAG.

## Timeout Chain

```
sensor.timeout <= dagrun_timeout
service_timeout <= dagrun_timeout
execution_timeout = safety net per non-deferred window (15min typical)
dagrun_timeout >= sum(service timeouts) + retry buffer
```

For deferrable operators, execution_timeout resets on each deferred-to-active
cycle. It need not exceed the service timeout.

## Retry Categories

| Category | retries | retry_delay | Notes |
|----------|---------|-------------|-------|
| Sensor | 0 | -- | Has own timeout |
| API call | 3 | 5min | Short, transient failures |
| Compute job (expensive) | 1 | 5min | Costly reruns; minimize |
| Compute job (cheap idempotent) | 2 | 5min | Safe to retry |
| DQ gate | 2 | 5min | AirflowFailException non-retryable |
| Teardown | 2 | 5min | trigger_rule=all_done |

Always: `retry_exponential_backoff=True`, `max_retry_delay=timedelta(minutes=30)`.

## Failure Callback Template

```python
def notify_failure(context):
    import json
    import boto3
    from datetime import datetime, timezone

    task_instance = context["task_instance"]
    dag_id = context["dag"].dag_id
    task_id = task_instance.task_id
    start_date = task_instance.start_date
    end_date = task_instance.end_date or datetime.now(timezone.utc)
    exception = context.get("exception", "")

    message = {
        "dag_id": dag_id,
        "task_id": task_id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        # Publish only the exception TYPE (carries no secret) + the log_url;
        # never the message/traceback/args, which can carry secrets or PII
        # (CWE-532). Authorized viewers get full detail via log_url.
        "error_type": type(exception).__name__ if exception else "",
        "log_url": task_instance.log_url,
    }

    sns = boto3.client("sns", region_name=REGION)
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"Airflow task failed: {dag_id}.{task_id}",
        Message=json.dumps(message, indent=2),
    )
```

> **Security:** enable server-side encryption (SSE) on the SNS topic, restrict
> `Publish` to the execution role, and confirm `SNS_TOPIC_ARN` is an expected
> in-account recipient — the callback sends operational metadata off the
> environment.

## Waiting for AWS Resource State Changes

**Exhaust Airflow-native constructs before writing custom wait code.** An
operator or sensor that owns the wait is almost always preferable to a
hand-written boto3 poll — it frees the worker slot and encodes the polling and
error handling for you. Work down this ladder and stop at the first rung that
applies:

1. **Deferrable operator.** If a deferrable operator exists for the action, use
   it with `deferrable=True` (e.g., `EmrServerlessStartJobOperator(deferrable=True)`).
   It hands the wait to the triggerer, freeing the worker slot for the whole
   wait and resuming on the completion event.
2. **Submit + deferrable sensor.** If no single operator both submits and waits,
   submit with a non-blocking operator (e.g., `wait_for_completion=False`) and
   wait with a **deferrable sensor** (`deferrable=True`). Deferrable support is
   per-sensor and per-provider-version — verify it for the specific sensor.
   Some AWS sensors are NOT deferrable (e.g. `AthenaSensor`,
   `EmrServerlessJobSensor`); for those, use the deferrable *operator* form
   instead (`AthenaOperator(deferrable=True)`,
   `EmrServerlessStartJobOperator(deferrable=True)`). If no deferrable path
   exists, a sensor in `mode="reschedule"` still frees the worker slot between
   pokes (no triggerer needed, but it only resumes on a fixed interval).
3. **Bounded in-task poll loop.** Only when no operator or sensor fits and you
   must wait inside a `@task` with boto3. Do not assume
   `client.get_waiter("<state>")` exists — not every service/operation ships a
   waiter, and a missing one raises `ValueError: Waiter does not exist` at
   runtime. Verify waiter availability in the boto3 docs for your runtime's
   botocore version before using `get_waiter`; otherwise use a bounded loop:

```python
for _ in range(max_attempts):
    response = client.get_<resource>(<id>=resource_id)
    state = response["<resource>"]["state"]
    if state == target_state:
        break
    if state in terminal_failure_states:
        raise RuntimeError(f"Resource reached {state}")
    time.sleep(delay_seconds)
else:
    raise RuntimeError(f"Resource did not reach {target_state}")
```

Deferrable operators and sensors require a running triggerer; MWAA runs a
managed triggerer on all MWAA-supported Airflow versions, so the
deferrable rungs work out of the box on both Airflow 2 and 3. The
`mode="reschedule"` fallback needs no triggerer. See A6 rule 5 in
authoring-provisioned-dag.md for the submit + `@task` sensor split.

## start_date

Use a fixed, timezone-aware datetime from stdlib. Never use `days_ago()` (deprecated
in 2.8, removed in 3.x) or naive datetimes (rejected in 3.x). **Always pair a fixed
past `start_date` with `catchup=False`**: on Airflow 2.x `catchup` defaults to True,
so a scheduled DAG with a past `start_date` backfills every missed interval in one
burst the moment it is unpaused. AF3 defaults `catchup=False`, but set it explicitly
so the DAG behaves the same on both.

```python
from datetime import datetime, timezone

with DAG(
    dag_id="example",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    schedule="<mm> <h> * * *",  # off-peak cron DERIVED from dag_id (A6 rule 15): mm 1-59, h 1-6 UTC — recompute per DAG, never a fixed literal or @preset
    catchup=False,  # REQUIRED with a fixed past start_date — avoids a backfill storm
):
    ...
```

Do not use `pendulum.datetime(...)` — it adds a top-level dependency on pendulum's
API which changed between v2 and v3. Stdlib `timezone.utc` works on all
MWAA-supported Python versions (3.10+) and all Airflow versions (2.x and 3.x).

## Idempotency

- Job names with `"{{ ds_nodash }}"` suffixes for date uniqueness.

## Cross-DAG Triggering

Event-driven coupling. The object type and its in-task event key differ by
Airflow major, so gate the example by the target Airflow version (per A3
"verify APIs exist in the Airflow version"):

```python
# Airflow 2.4-2.x (Datasets):
from airflow.datasets import Dataset
DATASET = Dataset("s3://bucket/prefix/")
# Producer: outlets=[DATASET] on final task
# Consumer: schedule=[DATASET]
# In-task events: context["triggering_dataset_events"]

# Airflow 3.x (Assets replace Datasets):
from airflow.sdk import Asset
ASSET = Asset("s3://bucket/prefix/")
# Producer: outlets=[ASSET] on final task
# Consumer: schedule=[ASSET]
# In-task events: context["triggering_asset_events"]
```

Cross-environment: `MwaaTriggerDagRunOperator` if support available in Airflow version in use.
