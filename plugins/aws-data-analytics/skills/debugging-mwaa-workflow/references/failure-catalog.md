# MWAA Failure Catalog

Category-keyed context checks and remediation. Categorize in this priority
order: infra, then drift, then code-data. Apply the first that matches the
evidence.

## Category: infra (check first)

| Symptom | Root cause | Context check | Remediation to recommend |
|---------|-----------|---------------|--------------------------|
| Task exits with `Negsignal.SIGKILL` / SIGTERM | Worker OOM | Worker log group; `MaxWorkers` and environment class from get-environment | Move heavy work to Glue/EMR/Lambda; stagger schedules; increase environment class. Scaling workers alone does not fix per-task OOM. |
| Tasks queued, never run | Autoscaling ceiling or scheduler load | Worker/Scheduler logs; `MaxWorkers` | Raise `MaxWorkers`; reduce `core.parallelism`; stagger start times |
| `AccessDenied` / `EntityNotFound` in task logs | IAM gap OR wrong/nonexistent resource OR cross-account | Read the exception's resource ARN, then check which failure it is (below) | Depends on which of the three — see the disambiguation note |
| DAG not appearing in UI | Import/parse error, scan interval not elapsed, `dag_id` collision, not-yet-active, or S3-sync delay | `GET /importErrors` and `GET /dags/{dag_id}` via invoke-rest-api; DAGProcessing log group; confirm `DagS3Path` object exists | See the **DAG not appearing in the UI** checklist below — the cause determines the fix |

### DAG not appearing in the UI

Not a single cause. When you explain the causes — or how to check a DAG that
is not appearing — **cover all five below, each paired with its specific
check**, rather than stopping at the first likely one. The Airflow REST API via
`invoke-rest-api` is the fastest check for most (see `provisioned-diagnostics.md`):
a thorough answer names both scan-interval config keys in step 2 and the
`GET /importErrors` and `GET /dags/{dag_id}` checks (the latter reading
`last_parsed_time`, `fileloc`, and `is_active`/`is_stale`). Do not conclude the
code is broken until 1 and 2 are ruled out.

1. **Import / parse error** — the file is present but fails to parse, so it
   never registers. Check `GET /importErrors` (Airflow REST API) for the file's
   traceback, or the DAGProcessing CloudWatch log group. Fix the code; it
   reappears on the next parse.
2. **Scheduler scan interval not yet elapsed** — a valid new file only lists
   after the DAG-directory scan runs. That cadence is
   `scheduler.dag_dir_list_interval` (Airflow 2.x) /
   `dag_processor.refresh_interval` (Airflow 3.x). The S3-to-container sync is
   only ~30s; the listing delay is this scan interval. Wait one interval before
   assuming a defect.
3. **`dag_id` collision** — if another file already defines the same `dag_id`,
   Airflow keeps one and silently drops the duplicate, so the new file "does not
   appear." Confirm the `dag_id` is unique across the whole `dags/` prefix.
4. **Parsed but not yet registered/active** — after the first successful parse
   the DAG registers. `GET /dags/{dag_id}` and read `last_parsed_time` and
   `fileloc` (present on both Airflow 2.x and 3.x) to confirm it parsed and
   points at the file you uploaded. Check `is_active` on Airflow 2.x; on Airflow
   3.x that field was replaced by `is_stale` (inverted — a stale DAG's file no
   longer parses). The `has_import_errors` flag on the same object points
   straight at a parse failure.
5. **S3-sync delay** — the object must land under the environment's `DagS3Path`.
   Confirm the object exists at that key; MWAA syncs it to the containers within
   ~30s.

### Disambiguating `AccessDenied` / `EntityNotFound`

A denial on a resource is one of four failures; the fix differs for each. Read
the resource ARN from the exception. Determine the account and region the
resource is expected in — this is NOT always the environment's own account.
Cross-account access is common: the execution role may access resources in
another account via resource policies (S3, SNS, KMS, etc.) or via
`sts:AssumeRole` into a role in the target account (configured as an Airflow
AWS connection with IAM role type in Provisioned). Check existence from the
account/role that should have access:

1. **Resource exists, role lacks the action** (true IAM gap) — the classic
   case. Add the missing action to the execution role (same-account) or to
   the assumed role (cross-account). Do not broaden to wildcard. HUMAN-GATED.
2. **Resource does not exist** — the identifier is a placeholder, a typo, or in
   a different region. `AccessDenied` (not `NoSuchBucket`) is common here
   because IAM denies before existence is revealed. Fix the identifier in the
   DAG/workflow (ARTIFACT fix via authoring-mwaa-workflow), not the role.
3. **Resource is cross-account, resource-policy path** — the ARN's account
   differs from the execution role's and access is via a resource policy on
   the target (S3 bucket policy, SNS topic policy, KMS key policy). Needs
   both: the resource policy granting the execution role's principal, and the
   execution role having the action. A role change alone or a resource policy
   alone will not resolve it. HUMAN-GATED.
4. **Resource is cross-account, assume-role path** — the task assumes a role
   in the target account (Provisioned: Airflow AWS connection with IAM role
   type; Serverless: not applicable — no connections). The denial is on the
   assumed role, not the execution role. Check: (a) execution role has
   `sts:AssumeRole` on the target role ARN, (b) the target role's trust
   policy allows the execution role as principal, (c) the target role has the
   needed action on the resource. HUMAN-GATED.

Do not reflexively broaden IAM: adding permissions for a resource that does not
exist (case 2) hides the real bug and leaves a standing over-grant.

### Extracting the required IAM policy from an AccessDeniedException

AWS error messages for access denials follow a consistent format that contains
everything needed to construct the missing IAM statement:

```
User: arn:aws:sts::<account>:assumed-role/<role>/...
is not authorized to perform: <action>
on resource: <resource-arn>
because no identity-based policy allows the <action> action
```

Extract these three fields and construct the minimum policy:

```json
{
  "Effect": "Allow",
  "Action": ["<action>"],
  "Resource": "<resource-arn>"
}
```

For the resource ARN, determine the appropriate scope:

- If the ARN ends in a specific resource ID, keep it exact for least privilege.
- If the ARN contains a log group or prefix pattern (e.g.,
  `/aws/sagemaker/TrainingJobs:*`), use the pattern with a wildcard suffix to
  cover log streams or child resources.
- If the service requires multiple related actions together (e.g.,
  `DescribeLogStreams` often needs `GetLogEvents`), check AWS documentation for
  the minimum action set.

After identifying the needed statement, verify which role requires it:

- The MWAA execution role (for actions the DAG tasks perform directly).
- A service role (e.g., Glue role, SageMaker role) if the denied principal is
  not the MWAA role.
- A cross-account assumed role (case 4 above).

Present the exact policy statement and target role to the user as a
HUMAN-GATED remediation.

## Category: drift (check when code did not change)

A DAG that passed last week and now fails on import, with no code change, is
almost always dependency drift. MWAA re-resolves dependencies on environment
update.

Three artifact paths can carry versioned objects (get-environment returns both
the S3 path and the `*S3ObjectVersion` in use when bucket versioning is
enabled). Always compare the **specific object version the environment is
using**, not the latest object at that path — a newer upload not yet picked up
by the environment is irrelevant to the current failure.

- **requirements.txt** (`RequirementsS3Path` / `RequirementsS3ObjectVersion`):
  compare the pinned version in use against the last known good. Unpinned
  packages resolve to new releases on environment update.
- **plugins.zip** (`PluginsS3Path` / `PluginsS3ObjectVersion`): may bundle
  `.whl` files providing Python packages outside of requirements.txt. A
  changed plugins.zip can introduce or remove packages, native shared
  libraries, or operator plugins. Diff contents (`unzip -l`) between the
  current version and the prior one.
- **Startup script** (`StartupScriptS3Path` / `StartupScriptS3ObjectVersion`):
  installs system libraries (yum/apt) that Python packages depend on (e.g.,
  `libpq-devel` for `psycopg2`, `unixODBC-devel` for `pyodbc`). A changed or
  removed startup script can break packages that compiled against those
  libraries at install time.
- Check whether the environment version was bumped (get-environment
  `AirflowVersion`) — a version change re-resolves the entire provider stack.

Remediation to recommend: pin exact versions in requirements.txt and use the
MWAA constraints file for the target Airflow version; pin `.whl` contents in
plugins.zip; pin system library versions in the startup script; use S3 object
versioning and reference explicit `*S3ObjectVersion` values in environment
config to prevent unintended drift on upload.

## Category: code-data (check last)

- Recent DAG changes: diff the DAG file in S3 against the prior version.
- Data volume spike: an operator that worked on small input may time out or OOM
  on large input — inspect input size for the failing run's data interval.
- Upstream health: a sensor timeout usually means the upstream producer is
  late, not that the DAG is broken.
- Remediation to recommend: fix the code or data; adjust timeouts/retries per
  the authoring-mwaa-workflow rules.

## Category: serverless custom-code failures (Python/Bash)

MWAA Serverless `PythonOperator`/`BashOperator` tasks add failure modes the
Provisioned rows above do not cover. Serverless only.

| Symptom | Root cause | Context check | Remediation to recommend |
|---------|-----------|---------------|--------------------------|
| `ModuleNotFoundError` / `ImportError` in task log | Dep not bundled AND not pre-installed, OR wheel built for the wrong platform | Compare the import against the pre-installed list; inspect the code package layout | Repackage the dep as a wheel matching the current MWAA Serverless platform and Python version (fetch from the [operators-python-bash-detail doc](https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/operators-python-bash-detail.html)) at the zip root; do not bundle pre-installed packages |
| Run fails, "cannot extract code package" / corrupt environment | Bad zip: files not at root, `__pycache__` included, or > 250 MB | Inspect the uploaded object size and layout | Repackage with all files at the root, excluding `__pycache__`; keep uncompressed size <= 250 MB |
| Task uses an unexpected package version | Bundled version shadowed by a pre-installed package | Check whether the package is on the pre-installed list | Design against the pre-installed version, or vendor under a different name if a different version is essential |
| Network call times out / connection refused | No internet access by default | Confirm the workflow has no `NetworkConfiguration` | Recommend a `NetworkConfiguration` VPC with egress, or move the network step to Lambda/Glue. HUMAN-GATED (VPC/networking) |
| Python task killed / OOM | Worker fixed at 1 vCPU / 3 GiB (cannot scale like Provisioned; confirm current specs from the MWAA Serverless docs at runtime) | Task log for MemoryError/SIGKILL; data volume for the run | Offload heavy work to Glue/EMR/Lambda; reduce in-memory footprint. Worker scaling is not available on Serverless |
