# Discovery, Pre-flight, and Path Planning (Phase 1)

Phase 1 of the upgrade skill. Runs environment discovery, pre-flight safety
checks, version-matrix refresh, target selection, and upgrade-path planning
(detection only — version jumps execute in Phase 7). Record every output into
the `.mwaa-upgrade-plan-<env-name>.md` plan (Phase 4 depends on them; a
compaction before Phase 4 loses anything not written to the plan).

## Step 1: Environment Discovery

1. Ask for the MWAA environment name (or detect from context).
2. Fetch environment config:

   ```
   aws mwaa get-environment --name <env>
   ```

   Extract: Airflow version, SourceBucketArn, DagS3Path, RequirementsS3Path,
   RequirementsS3ObjectVersion, PluginsS3Path, PluginsS3ObjectVersion,
   StartupScriptS3Path, StartupScriptS3ObjectVersion, AirflowConfigurationOptions,
   LoggingConfiguration, WeeklyMaintenanceWindowStart, WebserverAccessMode, KmsKey.
3. Fetch requirements.txt from S3 using the exact object version the
   environment references (artifacts may be versioned):

   ```
   aws s3api get-object --bucket <bucket-name-from-SourceBucketArn> --key <RequirementsS3Path> \
     --version-id <RequirementsS3ObjectVersion> /dev/stdout
   ```

   `SourceBucketArn` is an ARN (`arn:aws:s3:::my-bucket`) — use the bare bucket
   name (after `s3:::`) for `--bucket` and `s3://`, not the ARN. If no version
   ID is set, fall back to `aws s3 cp s3://<bucket-name-from-SourceBucketArn>/<RequirementsS3Path> -`.
4. List DAGs via REST API:

   ```
   aws mwaa invoke-rest-api --name <env> --method GET --path /dags
   ```

   Returns up to 100 DAGs per call (default limit). For environments with
   >100 DAGs, paginate with `--query-parameters '{"limit":"100","offset":"0"}'`
   and increment offset until `total_entries` is reached.
5. Identify shared utilities: check for `dags/common/`, `dags/utils/`, or `sys.path` manipulation in local code.
6. **Compute the S3 layout for the new or test environment** (New-environment
   and Rehearsed upgrades only — skip for the Direct in-place upgrade):
   Derive paths for the new or test environment's mutable artifacts, named after
   that environment's name (`<new-env>` for the New-environment upgrade,
   `<test-copy>` for the Rehearsed in-place upgrade). Convention:
   - DAG path: `dags-<env-name>/` (in same bucket)
   - requirements path: `requirements-<env-name>.txt`
   - plugins path: `plugins-<env-name>.zip` (if your current environment has
     plugins)
   - startup path: `startup-<env-name>.sh` (if your current environment has a
     startup script)

   Record these paths in the plan. The approach reference seeds them from your
   current environment's artifacts and uses them at environment creation time.
   Separate paths ensure the new or test environment's changes (AF3-fixed
   DAGs, target-updated requirements, and any plugin/startup changes) never
   affect your current environment, and vice versa.

## Step 2: Pre-flight Safety Checks

1. **S3 versioning**: Check bucket versioning status:

   ```
   aws s3api get-bucket-versioning --bucket <bucket-name-from-SourceBucketArn>
   ```

   If not enabled, recommend enabling and wait for user confirmation before proceeding.
2. **Constraints file validation**: Once the target version is selected (Step 4), download that version's constraints file (see the constraint-file URL template in [mwaa-version-matrix.md](mwaa-version-matrix.md)), cross-reference with current requirements.txt. Flag packages that conflict. Report blockers before proceeding.
3. **KMS key-policy reuse check** (approaches that create a new or test
   environment — New-environment and Rehearsed upgrades only): the new or
   test environment reuses your current environment's `KmsKey` (Step 1) but
   gets a NEW environment ARN. Inspect the CMK key policy/grants
   (`aws kms get-key-policy`, `aws kms list-grants`) for conditions scoped to
   your current environment's ARN; if present, add the new or test
   environment's ARN/role before creating it, or `create-environment`/runtime
   encryption fails `AccessDenied`.
4. **Execution-role trust-policy check** (approaches that create a new or test
   environment — New-environment and Rehearsed upgrades only): if the new or
   test environment reuses your current environment's execution role and that
   role's trust policy has an `aws:SourceArn` condition scoped to your current
   environment's ARN (the confused-deputy guard recommended in
   deploying-mwaa.md), `create-environment` succeeds but the new or test
   environment's tasks fail AssumeRole at runtime. Inspect the role's trust
   policy (`aws iam get-role`) for `aws:SourceArn`/`aws:SourceAccount`
   conditions scoped to your current environment's ARN; if present, add the
   new or test environment's ARN before creating it.

## Step 3: Refresh Version Matrix

Fetch https://docs.aws.amazon.com/mwaa/latest/userguide/airflow-versions.html
and derive `supported_versions`, `eos_versions`, `python_by_version`, and
`latest_by_major` (see [mwaa-version-matrix.md](mwaa-version-matrix.md)). On
fetch failure, retry or ask the user for the supported set — do not plan against
assumed versions (MWAA validates the target at execution time). Map the source
version to its Python version via the matrix (GetEnvironment does not return
Python).

## Step 4: Target Selection

Ask the user for the target Airflow version; offer the maximum supported
version ("latest supported") as the default. Validate:

- `target` is in `supported_versions` (creatable/available), and
- `target` is strictly newer than the source.

On failure, report the reason and re-prompt. Example: source 2.4.3, target
2.5.1 -> reject ("2.5.1 is past end-of-support; choose 2.7.2 or newer, or a
3.x version"). If the source is below 2.4.3, inform the user this is below
supported upgrade paths; recommend manual intervention or recreation and do
not proceed automatically.

## Step 5: Plan the Upgrade Path (no execution)

Detection only; version jumps are EXECUTED later by the engine (Phase 7) on
the new or test environment or your current environment, depending on the
chosen approach. Apply the version-jump rules in
[mwaa-version-matrix.md](mwaa-version-matrix.md) to produce an ordered list of
version jumps. For each version jump record `from`, `to`, `python_change`
(crosses a Python-line boundary), and `crosses_major` (2.x -> 3.x). Also
record `eos_source` (true if the source version is in `eos_versions`;
informational — every remaining approach can upgrade away from an EOS
source). The 2.11.x stepping-stone version is skipped only when the source
is already 2.11.x (Python 3.12).
