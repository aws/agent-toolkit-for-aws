# Authoring — Path B: YAML Workflow (MWAA Serverless)

Detailed steps for the Serverless / YAML path. The agent is routed here from the authoring-mwaa-workflow SKILL.md "Step 0: Route to Path"; it does not need the Provisioned (Path A) reference.

## Path B: YAML Workflow (MWAA Serverless)

See [yaml-schema.md](yaml-schema.md) for format and constraints.

### B1. Gather Context

1. **Resource identifiers** — look up via AWS tools. No placeholders.
2. **Schedule** — NEVER use `@daily`/`@hourly` (or any `@`-preset) unless the
   user explicitly asks for that exact expression. If the user has no
   preference, derive a spread off-peak cron from the `dag_id` (minute 1-59,
   hour 1-6 UTC; see B4 rule 11) — never at the top of the hour, and do not
   reuse a single fixed time across workflows.

Airflow version is fixed by MWAA Serverless engine version (not user-chosen).

### B2. Validate Operators

1. Check operator is in the MWAA Serverless supported operators allowlist.
   See [yaml-schema.md](yaml-schema.md). `PythonOperator` and
   `BashOperator` ARE supported — prefer them for inline custom logic. Reach
   for another target only when the work does not fit the worker (1 vCPU /
   3 GiB, 60-min task cap, no internet by default; confirm current worker limits
   from the AWS MWAA Serverless docs at runtime): use
   `LambdaInvokeFunctionOperator` when the user references an existing Lambda;
   offload heavy or long-running compute to Glue or EMR; give a task that needs
   internet a `NetworkConfiguration` VPC.
2. Look up operator parameters for the correct provider version.
3. Remove all unsupported task-level params: `deferrable`, `trigger_rule`,
   `outlets`, `on_failure_callback`, `retry_exponential_backoff`,
   `max_retry_delay`, `pool`, `queue`, etc.
4. If any task uses `PythonOperator`/`BashOperator`, do **B3 Custom Code &
   Dependencies** before writing.

### B3. Custom Code & Dependencies (only if using Python/Bash)

0. **Stdlib fast-path:** if all imports in the callable/script are Python
   stdlib or builtins (e.g., `time`, `json`, `os`, `math`), skip the AWS doc
   fetch — no third-party dependencies exist. Go directly to step 1 (write the
   callable) then step 4 (packaging). Otherwise, fetch the authoritative
   runtime reference:
   https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/operators-python-bash-detail.html
   Extract: current pre-installed package list, Python version, and worker
   constraints. This is the source of truth — local references summarize but
   may lag.
1. Write the callable/script the task runs. `python_callable` is referenced as
   `module_name.function_name`; the module is a `.py` file at the root of the
   code package.
2. Determine third-party dependencies. Check each against the pre-installed
   package list from the AWS doc fetched in step 0. Do NOT bundle a
   pre-installed package — the pre-installed version wins and shadows a bundled
   copy; warn the user if they need a different version. Skip if stdlib
   fast-path applies.
3. State the runtime constraints: dependencies must be `manylinux2014_x86_64`
   wheels matching the Python version from the AWS doc (verify the platform tag and version against the step-0 doc if the runtime architecture changes); tasks have no internet
   by default (a package needing runtime network access requires a
   `NetworkConfiguration` VPC). Skip if stdlib fast-path applies.
4. Packaging and deployment happen in the Deploy phase via `--code`; see
   [serverless-code-packaging.md](serverless-code-packaging.md).

### B4. Rules

1. **Timedelta format (REQUIRED)**: `execution_timeout` and `retry_delay`
   must use `__type__: datetime.timedelta` + `seconds: N`. Bare integers
   cause `ValidationException`.
2. **The first scheduled run must resolve to a future time** (scheduled workflows).
   MWAA Serverless combines `start_date` with the next `schedule`-satisfying time-of-day
   and rejects the workflow only if that computed first-run time is already past.
   So `start_date` may be today as long as the schedule still fires later today;
   if today's only schedule-satisfying time has already passed, use a later date.
   Unscheduled workflows (`schedule: null`) have no first-run computation and
   may use any `start_date`, including a past one.
3. **XCom for small values only**: Use S3 for larger payloads.
4. **No `description` in YAML** — it is silently ignored. Pass descriptions
   via `--description` on `create-workflow`/`update-workflow`.
5. **Omit unsupported DAG params**: `max_active_runs`, `dagrun_timeout`,
   `catchup`, `tags`, `on_failure_callback`, etc.
6. **Operator paths fully qualified**: e.g.,
   `airflow.providers.amazon.aws.operators.athena.AthenaOperator`.
7. **No `aws_conn_id`**: MWAA Serverless controls credentials via
   execution role.
8. **Native operators for custom logic**: use `PythonOperator`/`BashOperator`
   for inline custom logic and ship code via `--code` (see B3). Fall back to
   Lambda/Glue/EMR only per the B2 selection rule.
9. **No branching/conditional logic**: `BranchPythonOperator` and the `@task`
   decorator are not supported; only `PythonOperator` and `BashOperator` are
   available for custom code. Keep control flow linear via `dependencies`.
10. **Idempotency**: same as Python path — date-based suffixes.
11. **Schedule expression**: NEVER emit `@daily`, `@hourly`, or any `@`-preset
    unless the user explicitly requests that exact expression. When the user
    gives no preferred time, DERIVE a spread off-peak cron from the `dag_id` so
    each workflow lands in its own slot — never reuse one fixed time across
    workflows. Do this at authoring time (you pick the value and write a literal
    cron into the YAML), so no runtime library is needed. Turn the `dag_id` into
    a stable integer `n` with this one fixed rule — always the same function, so
    the same `dag_id` derives the same `n`, and therefore the same slot, across
    every authoring session: a position-weighted sum
    `n = sum(i * ord(c) for i, c in enumerate(dag_id, 1))` (order-sensitive, so
    word-order variants of a `dag_id` do not collide on one slot; needs no
    runtime library and always works). Do NOT substitute a different function
    (e.g. `zlib.crc32`, or Python's built-in `hash()`, which is also salted per
    process) — a different function yields a different `n` and a different cron
    for the same `dag_id`, breaking reproducibility. Then `minute = 1 + (n % 59)` (1-59,
    non-zero), `hour = 1 + ((n // 59) % 6)` (1-6 UTC), and
    `schedule = "{minute} {hour} * * *"`. If you cannot compute `n` for any
    reason, still pick a varied off-peak time yourself (minute 1-59, hour 1-6
    UTC) per workflow — NEVER give up, skip the schedule, fall back to a single
    fixed time, or use a `@`-preset.

### B5. Write

```yaml
workflow_name:
  dag_id: ...
  schedule: "<off-peak cron derived from dag_id; minute 1-59, hour 1-6 UTC; see B4 rule 11>"
  start_date: "<YYYY-MM-DD, chosen so the first scheduled run resolves to a future time; see B4 rule 2>"
  tasks:
    python_task:
      operator: airflow.providers.standard.operators.python.PythonOperator
      python_callable: my_module.clean_records
    task_name:
      operator: fully.qualified.path
      param: value
      retries: N
      retry_delay:
        __type__: datetime.timedelta
        seconds: N
      execution_timeout:
        __type__: datetime.timedelta
        seconds: N
      dependencies: [upstream_task]
```

---
