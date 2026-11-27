# The step-by-step upgrade (version-by-version)

The core upgrade-and-validate procedure every approach uses. It works on one
environment at a time: the new environment (New-environment upgrade), the
test copy then your current environment (Rehearsed in-place upgrade), or
your current environment (Direct in-place upgrade). Walks an ordered upgrade
path; version numbers are never hardcoded.

## Inputs (supplied by the calling approach)

- **Environment name** — the environment this engine mutates.
- **Upgrade path** — ordered version jumps from the plan, each with `from`,
  `to`, `python_from`, `python_to`, `python_change`, `crosses_major`.
- **Starting condition**:
  - **newly created** (validate at the starting version, then upgrade
    through the remaining version jumps) — the environment was created by
    the approach at version jump 1's `to`.
  - **upgraded in place** (upgrade through every version jump, starting at
    the first) — the environment currently sits at version jump 1's `from`.

## Per-version-jump confirmation

Every `aws mwaa update-environment` (every version jump) requires its own
explicit user confirmation. State rollback options at each in-place version
jump: downgrade from 3.x to 2.11.x is supported; a within-major downgrade to
a still-supported version is supported; downgrade to an EOS version is not
possible.

**Python-line gate (before presenting any `python_change` jump):** if
`jump_j` is `python_change`, do not present
`update-environment --airflow-version <jump_j.to>` until the plan shows no
`python-stdlib` hit still `PENDING` (5-PY.1 / 5-PY.2 `DONE` and the fixes
deployed, 5-PY.3) and the standard-library check is not `INCOMPLETE` unless
the user acknowledged it (5-PY.0 `DONE`). If the gate fails, stop and report
which items are open. Docker validation is not part of this gate. For a
newly created environment, version jump 1 has no `update-environment` (the
environment is created at `jump_1.to`). If jump 1 is `python_change`, apply
the gate before deploying DAGs to it, checking 5-PY.1, 5-PY.2 and 5-PY.0 only.
That deploy is what completes 5-PY.3.

## Validate / fix loop (run after an env reaches a version V)

1. Deploy the current DAG set to the environment; wait for parsing.
1a. Unpause DAGs ONLY on an environment that is serving production: your
   current environment in the Direct in-place upgrade, and your current
   environment after its in-place jump in the Rehearsed in-place upgrade
   (starting condition: upgraded in place). On the new environment
   (New-environment upgrade) and the test copy (Rehearsed in-place upgrade),
   skip this step and leave DAGs paused after deploy: they share connections
   and variables with your current environment, so unpaused schedules there
   run every DAG twice. If `/dags` shows a DAG there with `is_paused: false`
   (it was created unpaused through `core.dags_are_paused_at_creation=False`
   or `is_paused_upon_creation=False`), pause it with the same PATCH and
   `{"is_paused":true}`. The testing skill unpauses each DAG only for its test
   run, and Phase 8.1(c) is the first real unpause on the new environment.
   On a production environment, newly synced DAGs register as paused by
   default on MWAA, so unpause each DAG in the deployed set that was unpaused
   before the upgrade (the `Original pause state` recorded at discovery).
   Leave DAGs that were paused then paused, and list them for the user:

   ```
   aws mwaa invoke-rest-api --name <env> --method PATCH \
     --path /dags/<dag_id> --body '{"is_paused":false}'
   sleep 0.2
   ```

   (`invoke-rest-api` has a 10-second timeout and a 6 MB response cap
   ([docs](https://docs.aws.amazon.com/mwaa/latest/userguide/access-mwaa-apache-airflow-rest-api.html));
   it is also throttled per environment, so the sleep spaces calls out — prefer
   exponential backoff on a throttling error over assuming a fixed rate.)
2. Check `has_import_errors` is false for all DAGs
   (`invoke-rest-api --path /dags`).
3. **Pre-cross fixes** when the NEXT version jump crosses into a new major
   version (this version is the required stepping-stone before the crossing):
   run the Ruff AIR scan (`ruff check --preview --select AIR .`) and the manual
   checklist greps, and fix using
   [airflow2-to-3-quick-reference.md](airflow2-to-3-quick-reference.md) and
   [airflow2-to-3-checklist.md](airflow2-to-3-checklist.md). Re-deploy until
   Ruff and the checklist are clean and imports are clean.
4. **Python-line re-validation:** if the just-reached version jump was
   flagged `python_change` (it crossed a Python-line boundary, e.g. 3.11 to
   3.12), run a dedicated requirements re-validation against the new
   Python-line constraints file and flag compiled-dependency conflicts
   before continuing. This is the generalized reason the intermediate step
   exists (to move Python safely and isolate compiled-dependency risk); it
   applies whether or not the version jump also crosses a major version.
   A `ModuleNotFoundError` (or `ImportError` / `AttributeError`) for a
   standard-library module or name after this jump means the Phase 3 step 1a
   check missed it. Fix it the same way (Phase 5 step 3 replacements), redeploy
   via step 1, and record it under the plan's `python-stdlib` findings with
   the note "found after the jump".

Do not search CloudWatch logs for `DeprecationWarning` /
`RemovedInAirflow{N}Warning` as a check: warnings raised by DAG code do not
reach those logs, so hits there are platform noise and no hits is not
evidence of clean code. Deprecation warnings are advisory; removed APIs show
up as import errors (step 2).

## Steps

### Newly created

- **Validate at the starting version (version jump 1's `to`):** set
  `current_jump: 1`, `jump_status: validating`, then run the validate /
  fix loop (so a resume during this window is unambiguous). If
  there is no version jump 2, version jump 1's `to` is the target — validate
  and go to Finish.
- **For each remaining version jump j = 2..N:** set requirements to
  `jump_j.to`'s constraint URL (apply provider changes from the quick
  reference if `crosses_major`); **pause all DAGs** before upgrading to
  prevent the scheduler from firing runs during the transition:

  **AF3 (bulk):**

  ```
  aws mwaa invoke-rest-api --name <env> --method PATCH \
    --path /dags --query-parameters '{"dag_id_pattern":"~"}' \
    --body '{"is_paused":true}'
  ```

  `"~"` is Airflow's shorthand regex for "match all DAGs".

  **AF2 (per-DAG loop, paginated):**

  ```
  # /dags returns up to 100 DAGs per call (default limit) — page through ALL of
  # them so every DAG is paused, not just the first 100 (see discovery-preflight.md)
  offset=0
  while :; do
    dag_ids=$(aws mwaa invoke-rest-api --name <env> --method GET \
      --path /dags --query-parameters "{\"limit\":\"100\",\"offset\":\"$offset\"}" \
      --query 'RestApiResponse.dags[].dag_id' --output text)
    [ -z "$dag_ids" ] && break
    n=0
    for dag_id in $dag_ids; do   # dag_ids are space-free identifiers
      aws mwaa invoke-rest-api --name <env> --method PATCH \
        --path "/dags/$dag_id" --body '{"is_paused":true}'
      sleep 0.2  # invoke-rest-api is throttled per environment
      n=$((n + 1))
    done
    [ "$n" -lt 100 ] && break
    offset=$((offset + 100))
  done
  ```

  Set plan `jump_status: upgrading`; apply the Python-line gate above if
  `jump_j` is `python_change`; present
  `update-environment --airflow-version <jump_j.to>` for confirmation; execute;
  poll to AVAILABLE (report every 5 minutes; stop on UPDATE_FAILED/UNAVAILABLE);
  set `jump_status: validating`; run the validate / fix loop
  (step 1a leaves DAGs paused here, because a newly created environment is
  the new environment or the test copy); mark the version jump complete and save progress (version
  jump Status, `## Where we are`, `Last updated`) BEFORE presenting the next
  version jump; advance `current_jump`.

### Upgraded in place

- **For each version jump j = 1..N:** set requirements to `jump_j.to`'s
  constraint URL (provider changes if `crosses_major`); **pause all DAGs**
  before upgrading to prevent the scheduler from firing runs during the
  transition:

  **AF3 (bulk):**

  ```
  aws mwaa invoke-rest-api --name <env> --method PATCH \
    --path /dags --query-parameters '{"dag_id_pattern":"~"}' \
    --body '{"is_paused":true}'
  ```

  `"~"` is Airflow's shorthand regex for "match all DAGs".

  **AF2 (per-DAG loop, paginated):**

  ```
  # /dags returns up to 100 DAGs per call (default limit) — page through ALL of
  # them so every DAG is paused, not just the first 100 (see discovery-preflight.md)
  offset=0
  while :; do
    dag_ids=$(aws mwaa invoke-rest-api --name <env> --method GET \
      --path /dags --query-parameters "{\"limit\":\"100\",\"offset\":\"$offset\"}" \
      --query 'RestApiResponse.dags[].dag_id' --output text)
    [ -z "$dag_ids" ] && break
    n=0
    for dag_id in $dag_ids; do   # dag_ids are space-free identifiers
      aws mwaa invoke-rest-api --name <env> --method PATCH \
        --path "/dags/$dag_id" --body '{"is_paused":true}'
      sleep 0.2  # invoke-rest-api is throttled per environment
      n=$((n + 1))
    done
    [ "$n" -lt 100 ] && break
    offset=$((offset + 100))
  done
  ```

  Set `jump_status: upgrading`; apply the Python-line gate above if `jump_j`
  is `python_change`; present
  `update-environment --airflow-version <jump_j.to>` for confirmation; execute;
  poll to AVAILABLE; set `jump_status: validating`; run the validate /
  fix loop (which unpauses DAGs in step 1a after validation; run the
  pre-cross fixes when version jump j+1 is `crosses_major`); mark the version jump
  complete and save progress (version jump Status, `## Where we are`, `Last
  updated`) BEFORE presenting the next version jump; advance `current_jump`.

Example in-place command (values from the current version jump, never
hardcoded):

```
aws mwaa update-environment --name <env> \
  --airflow-version <jump.to> \
  --requirements-s3-path <requirements-path-for-jump.to>
```

Poll:

```
aws mwaa get-environment --name <env> --query "Environment.Status"
```

### Finish (after the last version jump)

- Verify health:

  ```
  aws mwaa invoke-rest-api --name <env> --method GET --path /monitor/health  # Airflow 3.x
  aws mwaa invoke-rest-api --name <env> --method GET --path /health          # Airflow 2.x
  ```

  Expected: metadatabase=healthy, scheduler=healthy.
- Confirm `has_import_errors` is false for every DAG.
- On failure, hand off to `debugging-mwaa-workflow` with context
  ("upgrade to `<target>` on `<env>`; DAGs `<list>` have import errors"), then
  re-verify.
- Return control to the calling approach. The engine's scope is parse
  validation (health + no import errors). Approaches that use the new
  environment or the test copy for validation (New-environment upgrade,
  Rehearsed in-place upgrade) are responsible for invoking execution
  validation (`testing-mwaa-workflow`) as a required checkpoint before
  proceeding to the live upgrade or switchover. Parse success alone does
  not prove artifacts will execute correctly at the target version.

## Re-entry

The engine writes `working_on` (the environment), `current_jump` (integer
index into the upgrade path), and `jump_status` (`upgrading` while an update
is in flight, `validating` during the post-update loop). Phase 0 resumes at
that environment + version jump + status. Each write happens before the next
action, per saving progress in
[plan-materialization.md](plan-materialization.md), so the recorded position
never trails reality by more than one in-flight action. For the Rehearsed
in-place upgrade (two environments), `working_on` selects the test copy from
your current environment.
