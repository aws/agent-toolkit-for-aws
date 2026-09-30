# Authoring — Path A: Python DAG (MWAA Provisioned)

Detailed steps for the provisioned / Python-DAG path. The agent is routed here from the authoring-mwaa-workflow SKILL.md "Step 0: Route to Path"; it does not need the Serverless (Path B) reference.

## Path A: Python DAG (MWAA Provisioned)

See [dag-patterns.md](dag-patterns.md) for templates and examples.

### A1. Gather Context

1. **Airflow version** — exact MWAA-supported version (e.g., 3.2.1, 2.10.3).
   Determines provider package, operators, template variables.
2. **Resource identifiers** — look up via AWS tools. No placeholders unless
   user explicitly says to. If a lookup returns not-found (empty list,
   nonexistent ARN, no results), record it as **unresolved** and continue
   through A3. Do not ask the user yet — A3 confirms whether an operator
   exists for the action, which informs the question. Present unresolved
   resources only after A3, framing as: "[Operator] exists and requires
   [parameter] — resource was not found in your account. Provide an ID,
   create it, or skip?"
3. **Schedule** — NEVER use `@daily`/`@hourly` (or any `@`-preset) unless the
   user explicitly asks for that exact expression. If the user has no
   preference, derive a spread off-peak cron from the `dag_id` (minute 1-59,
   hour 1-6 UTC; see A6 rule 15) — do not reuse a single fixed time across DAGs.
4. **Failure notifications** — SNS, Slack, email, or none.

### A2. Environment Discovery

1. **Ask for target environment** — "Do you have an existing MWAA
   environment for this DAG?" Skip if already provided or user said
   "create new."
2. **If environment exists:**
   a. Fetch config:

      ```
      aws mwaa get-environment --name <env-name>
      ```

      Extract: Airflow version (overrides A1 if different), Python version,
      SourceBucketArn, RequirementsS3Path, RequirementsS3ObjectVersion,
      PluginsS3Path, PluginsS3ObjectVersion, StartupScriptS3Path,
      StartupScriptS3ObjectVersion.
   b. Fetch requirements.txt from S3 using the exact version in use:
      - If `RequirementsS3ObjectVersion` is present (bucket has versioning):

        ```
        aws s3api get-object --bucket <bucket-name-from-SourceBucketArn> --key <RequirementsS3Path> \
          --version-id <RequirementsS3ObjectVersion> /dev/stdout
        ```

      - If `RequirementsS3ObjectVersion` is absent (no versioning):

        ```
        aws s3 cp s3://<bucket-name-from-SourceBucketArn>/<RequirementsS3Path> -
        ```

      Skip asking user to provide if fetched. Ask only if path is empty or
      file missing.
   c. Fetch startup script (if `StartupScriptS3Path` is set):
      - Versioned: `aws s3api get-object --bucket <bucket> --key
        <StartupScriptS3Path> --version-id <StartupScriptS3ObjectVersion>
        /dev/stdout`
      - Unversioned: `aws s3 cp s3://<bucket>/<StartupScriptS3Path> -`
      Record which system packages are installed (yum/apt lines). Some
      Python packages in requirements.txt depend on system libraries
      (e.g., `psycopg2` needs `libpq-devel`, `pyodbc` needs
      `unixODBC-devel`).
   d. Inspect plugins.zip (if `PluginsS3Path` is set):
      - Download to a temp path (with `--version-id` if versioned).
      - List contents: `unzip -l /tmp/plugins.zip`
      - Look for bundled `.whl` files — these provide Python packages
        outside of requirements.txt. Record their package names and
        versions for A4 validation.
      - Also note any operator plugins or hook modules.
   e. Introspect via invoke-rest-api (all use
      `aws mwaa invoke-rest-api --name <env-name> --method GET --path <path>`):
      - `/connections` — configured external systems
      - `/variables` — parameterized values
      - `/pools` — concurrency configuration
      - `/dags` — existing DAGs (for cross-DAG triggering)
      - `/datasets` (Airflow 2.4–2.x) or `/assets` (3.0+) — event
        dependencies. Skip if version < 2.4.

      Each of these is a paginated collection (Airflow REST default `limit`
      100). On a large environment pass
      `--query-parameters '{"limit":"100","offset":"0"}'` and re-issue with
      `offset` incremented by 100 until you have read `total_entries` items,
      so introspection does not miss a connection/variable/DAG the new DAG
      references beyond the first 100.
3. **If no environment** — ask user to provide requirements.txt or confirm
   starting fresh. Skip all introspection.

How introspection informs downstream steps:

- **Connections** → operator choices in A3
- **Variables** → parameterization in A7 (Write)
- **Pools** → pool assignments if concurrency needed
- **DAGs + assets** → cross-DAG patterns in A7
- **Startup script** → system library availability for A4 validation
- **Plugins .whl files** → already-installed packages for A4 validation
- **ExecutionRoleArn** → permissions validation in A5

### A3. Validate Operators

1. Look up operator constructor parameters for the exact provider version.
   Never guess from memory. Provide subagents the full version context.
2. Verify template variables exist in the Airflow version (e.g., `tomorrow_ds`
   removed in 3.x → use `macros.ds_add(ds, 1)`).

### A4. Requirements Validation

Validate that the environment's installed packages support the operators
chosen in A3. The effective package set is the union of requirements.txt
AND any `.whl` files bundled in plugins.zip. Skip entirely for Path B
(Serverless has a fixed package set).

1. **Resolve constraints file** for the Airflow + Python version:
   `https://raw.githubusercontent.com/apache/airflow/constraints-{airflow_version}/constraints-{python_version}.txt`
2. **Build effective package inventory**:
   - Packages from requirements.txt (with pinned versions).
   - Packages from plugins.zip `.whl` files (name + version extracted
     from the wheel filename: `{name}-{version}-*.whl`).
   - Treat both sources as installed — a package in either satisfies
     operator dependencies.
3. **Check existing packages** against constraints:
   - Version conflicts → warning: "this will fail at install time."
   - Packages absent from constraints (custom) → informational note.
4. **Check for missing provider packages** needed by A3's operators:
   - Identify absent packages (not in requirements.txt OR plugins.zip
     wheels); determine version from constraints.
5. **Check system library dependencies**:
   - For each new package that requires system libraries (e.g.,
     `psycopg2` → `libpq-devel`, `pyodbc` → `unixODBC-devel`,
     `cryptography` → `openssl-devel`), verify the startup script
     installs them.
   - If a required system library is missing from the startup script,
     flag it: "requirements.txt install will fail — `<package>` needs
     `<library>` installed via startup script."
6. **Present findings** with risk statements.
7. **If changes needed, ask:** "OK to update requirements.txt?"
   Also ask about startup script updates if system libraries are missing.
   - Skip ask if user pre-approved ("update requirements as needed").
   - If approved: queue update (applied at deploy or as explicit step).
     For startup script changes, queue those alongside requirements.
   - If declined: warn operators may not be installable; loop back to A3
     with constraint — only operators whose providers are already in
     requirements.txt or plugins.zip.
8. **If starting fresh** (no requirements.txt): generate from A3's
   operators + constraints versions. Flag any system library needs for
   the startup script.

Skip conditions:

- User said "don't touch requirements.txt" → skip update offer; still
  warn if operators need missing packages.
- Starting fresh → generate from scratch (no check, just build).

### A5. Permissions Validation

Validate that the MWAA execution role grants access to all AWS resources the
DAG will interact with at runtime. Skip if no environment exists yet: inline
creation (see deploying-mwaa.md) builds the role scoped to exactly the DAG's
Action/Resource needs, so coverage is established at role-build time and a
separate A5 pass isn't required.

1. **Extract resource ARNs from the DAG**:
   - S3 buckets (output locations, data sources)
   - SNS topics (failure callbacks)
   - Glue databases/tables (catalog access)
   - Athena workgroups
   - Any other service resources (Redshift, EMR, SageMaker, etc.)
2. **Fetch the execution role policy**:
   Extract the role name from the environment's `ExecutionRoleArn` (the segment
   after `role/`; for path-qualified roles, include the path, e.g.,
   `path/role-name`). Do NOT pass the full ARN to `--role-name`.
   - `aws iam list-attached-role-policies --role-name <role-name>`
   - For each attached policy:
     `aws iam get-policy --policy-arn <arn>` then
     `aws iam get-policy-version --policy-arn <arn> --version-id <default-version>`
   - `aws iam list-role-policies --role-name <role-name>` (inline policies)
   - `aws iam get-role-policy --role-name <role-name> --policy-name <name>`
     for each inline policy
3. **Check coverage** — for each extracted resource ARN, verify a matching
   Allow statement exists in the policy (exact ARN or wildcard pattern).
   Common gaps:
   - S3 output bucket for Athena/EMR results (role often only covers the
     MWAA source bucket)
   - SNS topic for failure notifications (role may only cover the
     environment's default alert topic)
   - Cross-account resources (require both IAM and resource policy)
4. **Present findings** with the exact ARNs that are missing.
5. **If gaps found, ask:** "OK to update the execution role policy to add
   these permissions?" Present the specific Resource additions.
   - If approved: re-fetch the policy immediately before writing
     (`get-role-policy`), then `put-role-policy` with a document that PRESERVES
     all existing statements and appends only the new pairs (it overwrites the
     whole named policy). Restate the shared-role blast radius in the confirmation.
   - If declined: warn that the DAG will fail at runtime with
     AccessDenied / InvalidRequestException.

### A6. Rules

1. **Timeout chain**: `dagrun_timeout >= sum(service timeouts + retries)`.
   Every task gets `execution_timeout`. Sensors use their own `timeout`.
2. **Deferrable**: use `deferrable=True` on every supporting operator.
   Only available in Airflow 2.7+. Do NOT use for versions before 2.7.
3. **Retries**: sensor=0, API=3, compute=1 (expensive) or 2 (cheap
   idempotent), DQ=2, teardown=2.
   Always `retry_exponential_backoff=True` + `max_retry_delay`.
4. **No top-level code or heavy imports**: only `from airflow...` imports
   and constant definitions at module level. All boto3/json/logic inside
   functions. Top-level code degrades scheduler parsing.
5. **No polling in tasks**: never write `while True` + `sleep` inside a
   task. Use the deferrable operator, or split into submit + `@task` sensor.
6. **Fan-out via `.expand()`**: use dynamic task mapping for parallel work.
   Never create tasks inside a Python loop (degrades parsing).
7. **XCom for small values only**: do not push large dataframes or blobs
   to XCom. Use S3 for large payloads and pass the S3 key via XCom.
8. **File organization**: only DAG files and direct Python deps in `dags/`.
   SQL, YAML, config, scripts go elsewhere (e.g., `scripts/`, `sql/`).
   Use `.airflowignore` to exclude non-DAG files from parsing.
9. **Callbacks**: `on_failure_callback` and similar publish dag_id, task_id,
   start_date, end_date, log_url, and the exception TYPE only (never the
   message/traceback — it can carry secrets; CWE-532). Import boto3 inside the
   callback.
10. **Idempotency**: date-based suffixes (`{{ ds_nodash }}`).
11. **No `verbose=True`**: floods CloudWatch unless explicitly asked.
12. **No `aws_conn_id`**: omit — uses default connection.
13. **Docstrings on `@task` functions**: always include.
14. **No unused variables**: every constant must be referenced.
15. **Schedule expression**: NEVER emit `@daily`, `@hourly`, or any `@`-preset
    unless the user explicitly requests that exact expression (presets bunch
    every DAG at midnight / top-of-hour and congest the scheduler). When the
    user gives no preferred time, DERIVE a spread off-peak cron from the
    `dag_id` so each DAG lands in its own slot — never reuse one fixed time
    across DAGs. Do this at authoring time — you pick the value and write a
    literal cron into the DAG (no top-level logic in the DAG file, per rule 4),
    so no runtime library is needed. Turn the `dag_id` into a stable integer
    `n` with this one fixed rule — always the same function, so the same
    `dag_id` derives the same `n`, and therefore the same slot, across every
    authoring session: a position-weighted sum
    `n = sum(i * ord(c) for i, c in enumerate(dag_id, 1))` (order-sensitive, so
    word-order variants of a `dag_id` do not collide on one slot; needs no
    runtime library and always works). Do NOT substitute a different function
    (e.g. `zlib.crc32`, or Python's built-in `hash()`, which is also salted per
    process) — a different function yields a different `n` and a different cron
    for the same `dag_id`, breaking reproducibility. Then `minute = 1 + (n % 59)` (1-59,
    non-zero), `hour = 1 + ((n // 59) % 6)` (1-6 UTC), and
    `schedule = "{minute} {hour} * * *"`. If you cannot compute `n` for any
    reason, still pick a varied off-peak time yourself (minute 1-59, hour 1-6
    UTC) per DAG — NEVER give up, skip the schedule, fall back to a single fixed
    time, or use a `@`-preset.
16. **`catchup=False` with a fixed past `start_date`**: always set `catchup=False`
    unless the user explicitly wants historical backfill. On Airflow 2.x `catchup`
    defaults to True, so a fixed past `start_date` (see dag-patterns.md) plus a
    schedule backfills every missed interval in one burst when the DAG is
    unpaused. AF3 defaults it False; set it explicitly so behavior matches on both.

### A7. Write

```
imports (airflow only at top)
constants
callback function
default_args
DAG context manager
  tasks with dependencies at end
```

---
