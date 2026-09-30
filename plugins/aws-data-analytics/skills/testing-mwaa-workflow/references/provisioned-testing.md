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

**Unpause before triggering (AF3 behavior change).** On Airflow 3.x, a manual
run POSTed against a *paused* DAG is accepted (the run is created in `queued`)
but the scheduler does not execute it while the DAG is paused — it sits
`queued` indefinitely and looks like a stuck trigger. Airflow 2.x runs manual
triggers regardless of pause state; AF3 does not. Unpause first
(`PATCH /dags/<dag_id>` with `{"is_paused": false}`), then trigger. This is
common right after an upgrade, where DAGs are deployed paused.

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

## Existing runs after unpause

When a paused DAG is unpaused during testing (common in delegated mode — the
DAG was just deployed paused), and `catchup=False` with an eligible interval
already past, the scheduler creates a `scheduled__` run immediately. This
consumes the next eligible `logical_date`.

Before POSTing a manual trigger:

1. GET `/dags/<dag_id>/dagRuns` with `{"order_by": "-start_date", "limit": "1"}`.
2. **Apply the freshness gate** — a prior run may have tested a previous
   version of the artifact:
   - **Delegated mode:** the artifact was just rewritten and redeployed.
     Any prior run by definition tested the previous file. Skip adoption
     and trigger fresh regardless of state.
   - **Standalone mode:** compare `run.start_date` against
     `dag.last_parsed_time` read from the `/dags` collection readiness
     response (the ready check already fetches it; the collection returns
     `last_parsed_time` per DAG, so there is no need to re-query the per-DAG
     endpoint). If `start_date < last_parsed_time`, the run predates the
     current artifact — treat as stale, trigger fresh.
3. If a **fresh** run exists (passes the gate):
   - Non-terminal (`queued`/`running`) — adopt it: skip the POST, proceed
     directly to poll (Step 3) using the scheduler's `dag_run_id`.
   - Terminal `success` — the DAG already passed; report it (Step 6).
   - Terminal `failed` — the DAG already failed; proceed to Step 4 (diagnosis).
4. If no fresh runs exist — POST the manual trigger as normal.

This check is cheap (one GET) and prevents the silent-failure scenario where
the POST returns `RestApiClientException` because the `logical_date` is
already taken — indistinguishable from a transient error without this context.

## Poll to terminal

**Task instances without a `state` field** (or with `state: null`) mean the
scheduler has not yet processed them. This is normal immediately after
triggering — wait for at least one poll cycle (scheduler heartbeat is
5-30 seconds). If they remain stateless after 60 seconds, the likely causes
are: the run is behind a `max_active_runs` concurrency cap (prior runs still
retrying), or the scheduler is overloaded. Check for other active runs of the
same DAG before concluding the trigger failed.

Mind the 64-character `--path` limit: a per-run path
(`/dags/<dag_id>/dagRuns/<url-encoded-run-id>`) can exceed it. Poll the short
collection path with query parameters instead:

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

A `RestApiClientException` or timeout (rare with `invoke-rest-api`, possible on
a mis-scoped execution role) falls back to the Scheduler and DAGProcessing
CloudWatch log groups for run/task state, exactly as debugging-mwaa-workflow
documents. Prefer `invoke-rest-api`; use logs only when it errors.
