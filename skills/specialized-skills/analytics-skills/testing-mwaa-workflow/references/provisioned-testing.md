# Provisioned MWAA Testing

Trigger and monitor a run on MWAA Provisioned (Python DAG). Every call here is
a single, aws-shaped `aws mwaa invoke-rest-api` invocation that proxies the
Airflow REST API through one AWS API call. No `create-web-login-token`, no curl:
`invoke-rest-api` reaches private (VPC-only) web servers.

`invoke-rest-api` returns `{"RestApiStatusCode": <int>, "RestApiResponse": {...}}`.
Read the run/DAG state from `RestApiResponse`.

**CLI vs SDK difference for `Body`**: the CLI `--body` flag accepts a JSON
string (`'{"key": "value"}'`). The boto3 SDK `Body` parameter accepts a
Python dict (`{"key": "value"}`) — do NOT wrap it in `json.dumps()`. Passing
a string produces the same generic `RestApiClientException` (empty message) as
other failures, with no indication the cause is serialization. All examples
below use CLI syntax; when calling via SDK, pass the equivalent dict.

## Readiness (before the first trigger)

Confirm the DAG is present and import-error-free:

```bash
aws mwaa invoke-rest-api --name <env> --path /dags --method GET \
  --query-parameters '{"dag_id_pattern":"<dag_id>"}'
```

`RestApiResponse.dags[]` lists parsed DAGs. `dag_id_pattern` bounds the response
to the target so it is found even on an environment with more than 100 DAGs (an
unfiltered `/dags` returns only the first 100 by default); it is a substring
match, so exact-match `<dag_id>` in `dags[]` (and if the pattern itself matches
more than 100 DAGs, add `"limit":"100","offset":"0"` and loop `offset` until
`total_entries`). The target `dag_id` must be present
with `has_import_errors: false`, plus a **version-aware ready check** via the
`/dags` collection endpoint (the per-DAG endpoint `/dags/<dag_id>` can return
stale values due to response caching):

- **AF2 (REST API v1):** require `is_active: true`.
- **AF3 (REST API v2):** the `is_active` field **does not exist** in the v2
  `/dags[]` schema — never wait on it (a naive check reads it as absent/false
  forever and the readiness gate never passes). Require `is_stale: false`
  instead.

A DAG that is parsed but not yet ready (AF2 `is_active: false`, AF3
`is_stale: true`) can reject trigger POST requests with an opaque
`RestApiClientException` (empty error message). This readiness lag is typically
1-5 minutes after the file first appears in S3.

Absent after the readiness window, `has_import_errors: true`, or still not
ready after that window (the environment's scan interval + 30s, default 300s
when unset, per SKILL.md Step 1; AF2 `is_active` never true / AF3 `is_stale`
never false) — hand to debugging-mwaa-workflow to split S3-sync lag from an
import error (it reads the DAGProcessing log group). Do not trigger a DAG that
is absent, has import errors, or is not ready.

## Trigger

**Airflow 3.x (REST API v2):**

```bash
aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
  --method POST --body '{"dag_run_id": "<explicit-id>", "logical_date": "<unique-ISO8601-UTC>"}'
```

`<explicit-id>` is a unique string you choose (e.g., `smoke_test__2026-08-11T01-00-00`).
Constraints: must not contain `/`; max 250 chars; must be unique per
(dag_id, logical_date) pair.

**Airflow 2.x (REST API v1):**

```bash
aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
  --method POST --body '{"dag_run_id": "<explicit-id>", "conf": {}}'
```

`<explicit-id>` follows the same constraints as above. AF2 does not require
`logical_date` and accepts `conf` directly.

`invoke-rest-api` auto-routes to v1 or v2 based on the environment's Airflow
version — callers do not specify a version prefix in the path. The body format
differs: AF3 requires `logical_date` (ISO 8601 UTC) and does not accept `conf`
at the top level; AF2 does not require `logical_date` and accepts `conf`
directly. Sending the wrong format produces a generic `RestApiClientException`
with no descriptive message.

Capture the `dag_run_id` so the poll can find this exact run.

**Unpause before triggering.** A manual run POSTed against a *paused* DAG is
accepted (the run is created in `queued`) but the scheduler does not execute it
while the DAG is paused, on Airflow 2.x and 3.x alike. It sits `queued` with
`start_date: null` and looks like a stuck trigger. Unpause first
(`PATCH /dags/<dag_id>` with `{"is_paused": false}`), then trigger. The
freshness gate's paused case (step 4 below) does this unpause and decides
whether to adopt the run it creates or to trigger.

**Prefer a definitely-past `logical_date`.** Manually triggered runs are
processed regardless of `logical_date`, but using a timestamp in the past
(e.g., 5 minutes ago) avoids two practical issues: (1) if prior runs of the
same DAG are still retrying, the new run may be blocked by `max_active_runs`
and appear stuck — a past timestamp makes it obvious the issue is concurrency,
not scheduling; (2) if the DAG templates on `{{ ds }}`, a past timestamp on the
same calendar day keeps data paths aligned with seeded test data.

On a **retest**, vary both `dag_run_id` and `logical_date`. Airflow enforces a
unique `(dag_id, logical_date)`; reusing a prior value makes the POST a silent
no-op — a generic `RestApiClientException` with no run created, indistinguishable
at a glance from a transient error. If the DAG templates on `{{ ds }}` (or other
date-derived paths), keep the same calendar date and vary only the time-of-day
so those paths still resolve to the staged test data.

Before re-triggering, confirm the prior run is terminal (see the poll below). A
task in retry-backoff still occupies a `max_active_runs` slot, so a new run
sits `queued` behind it rather than starting — a stall that looks like a
trigger failure but is the concurrency cap.

## Before POSTing a manual trigger

When a paused DAG is unpaused during testing (common in delegated mode — the
DAG was just deployed paused), and `catchup=False` with an eligible interval
already past, the scheduler creates a `scheduled__` run immediately. A DAG
created unpaused (`core.dags_are_paused_at_creation=False` or
`is_paused_upon_creation=False`) gets the same run within seconds of its first
parse. A prior run may therefore be the scheduler's run of the file you just
deployed, the scheduler's run of a *previous* file, or a leftover from an
earlier test.

**Apply the freshness gate** (delegated and standalone mode alike) before
adopting any prior run. The reference time is the DAG file's **deploy time**,
not `last_parsed_time` (which advances on every re-parse even when the file is
unchanged):

1. **Resolve the deploy time** — the S3 `LastModified` of the DAG file object.
   Read `SourceBucketArn` and `DagS3Path` from `get-environment`, then
   head-object the file (in delegated mode the calling skill names the
   file):

   ```bash
   aws mwaa get-environment --name <env> \
     --query 'Environment.{Bucket:SourceBucketArn,Path:DagS3Path}'
   aws s3api head-object --bucket <source-bucket> --key <DagS3Path>/<file.py> \
     --query 'LastModified'
   ```

   `SourceBucketArn` is `arn:aws:s3:::<source-bucket>`; use the bare bucket name
   for `--bucket`.

   If the deploy time cannot be read — `head-object` returns `AccessDenied`, or
   the DAG file key is unknown (standalone mode with no hand-off) — do
   **not** fall back to `last_parsed_time`. First ask the user for the DAG file
   key (so `head-object` can run) or the file's deploy time directly. If neither
   is available, tell the user freshness cannot be verified, treat **every**
   prior run as stale, and apply the scheduled-DAG rules in step 4: a terminal
   prior run, trigger fresh (under the Step 2 confirmation); a non-terminal
   (`queued`/`running`) prior run, do not trigger silently — ask the user to
   start a fresh run now (it runs alongside the in-flight run and can collide on
   downstream resources) or wait for the in-flight run to finish and then
   trigger fresh.

2. **Fetch the most recent run:**

   ```bash
   aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
     --method GET --query-parameters '{"order_by": "-start_date", "limit": "1"}'
   ```

   Read its `start_date` and `state` from `RestApiResponse.dag_runs[0]`.

3. **Read whether the DAG has a schedule** from the `/dags` collection response
   the readiness check already fetched. `timetable_description` is the primary
   signal and is present on both majors: a value of
   `"Never, external triggers only"` means no schedule. The per-major field
   below is **absent (key omitted) or null** when there is no schedule and
   carries the schedule when there is one — read it as confirmation, and never
   require an explicit null (the live `/dags` response omits the key entirely
   for an unscheduled DAG):
   - **AF2 (v1):** no schedule when `schedule_interval` is absent or null. When
     scheduled it is an object, e.g.
     `{"__type": "CronExpression", "value": "@hourly"}`.
   - **AF3 (v2):** no schedule when `timetable_summary` is absent or null. When
     scheduled it is a cron string, e.g. `"0 * * * *"`.

4. **Decide by pause state, then by schedule.** `is_paused` comes from the same
   `/dags` response.

   - **Paused.** No run can start until you unpause, so you choose the run
     that tests the new file. Poll the `/dags` collection until
     `last_parsed_time` is after `LastModified`, within the Step 1 readiness
     window. From that response read the next run time (AF2:
     `next_dagrun_create_after`; AF3: `next_dagrun_run_after`), which the DAG
     processor recomputes on every parse, paused or not. Note the most recent
     run, unpause (`PATCH /dags/<dag_id>` with `{"is_paused": false}`), and:
     - **Next run time at or before the unpause** (a scheduled DAG whose latest
       interval is due): the scheduler creates that run within seconds. Poll
       `dagRuns` for a new `run_type` `scheduled` run that was not there
       before the unpause, adopt it, and poll it in Step 3. Do not POST a
       trigger, which would run the DAG twice against the same downstream
       resources. If no such run appears within the readiness window, the
       scheduler is not creating runs: go to Step 4 (diagnosis) rather than
       triggering.
     - **Next run time null** (no schedule) **or in the future:** no run is
       coming now. POST the manual trigger.
     - **The parse never came within the window:** unpause anyway and apply
       the unpaused cases below.
   - **Unpaused, no schedule.** A run whose `start_date >= LastModified` is
     fresh: adopt it — non-terminal (`queued`/`running`), skip the POST and poll
     it in Step 3; terminal `success`, report it (Step 6); terminal `failed`, go
     to Step 4 (diagnosis). A run with `start_date < LastModified` is stale:
     trigger fresh. If that stale run is still running, handle it as the
     scheduled non-terminal case below.
   - **Unpaused, scheduled.** Treat any scheduler-created or earlier run as
     stale, even one with `start_date >= LastModified`: a scheduled run that
     fires right after the upload can still have executed the previous file,
     because the new file reaches the scheduler and workers only after MWAA's
     S3 sync and the next parse. If the stale run is terminal, trigger fresh as
     normal. If it is non-terminal (`queued`/`running`), **do not** trigger
     silently — ask the user to either (a) start a fresh run now, which runs
     alongside the in-flight run and can collide on downstream resources, or
     (b) wait for the in-flight run to finish first. In delegated mode the
     caller's approval to test does not cover this choice; ask. If they choose
     to wait, poll the in-flight run to a terminal state (it is not the test
     result — do not report it as one), then trigger fresh.

The gate decides on deploy time and the DAG's schedule, never on the code a run
executed: no MWAA or Airflow API exposes a run's source. On Airflow 3.2.1 a
code-only change keeps the same DAG version and overwrites that version's stored
source in place; on Airflow 2.x `/dagSources` returns only the current file.

## Poll to terminal

**Task instances without a `state` field** (or with `state: null`) mean the
scheduler has not yet processed them. This is normal immediately after
triggering — wait for at least one poll cycle (scheduler heartbeat is
5-30 seconds). If they remain stateless after 60 seconds, the likely causes
are: the run is behind a `max_active_runs` concurrency cap (prior runs still
retrying), or the scheduler is overloaded. Check for other active runs of the
same DAG before concluding the trigger failed.

Poll the `dagRuns` collection:

```bash
aws mwaa invoke-rest-api --name <env> --path /dags/<dag_id>/dagRuns \
  --method GET --query-parameters '{"order_by": "-start_date", "limit": "5"}'
```

Scan `RestApiResponse.dag_runs[]` for the entry whose `dag_run_id` equals the
captured id and read its `state` — a scheduler-created or concurrent run can
otherwise be the newest by `start_date` and mask the target run. Terminal
states: `success`, `failed`.
`queued`/`running` mean keep polling.

## Fallback

A `RestApiServerException` that persists after retries, or a timeout, falls
back to the Scheduler and DAGProcessing CloudWatch log groups for run/task
state, exactly as debugging-mwaa-workflow documents. A `RestApiClientException`
is a 4xx from Airflow, so read its `RestApiStatusCode` first (404 wrong
`dag_run_id`, 401/403 role). Prefer `invoke-rest-api`; use logs only when it errors.
