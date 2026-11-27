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
   Record each DAG's `is_paused` value in the plan (`Original pause state`).
   Every DAG is still unpaused for its own test run on the new environment or
   test copy, but a DAG paused here stays paused when an environment goes live
   (upgrade-engine.md step 1a, Phase 8.1(c)).
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
3. **Extend environment-scoped permissions** (approaches that create a new or
   test environment — New-environment and Rehearsed upgrades only; the Direct
   in-place upgrade skips this). The new or test environment reuses your
   current environment's execution role and `KmsKey` (Step 1), and the role
   cannot be swapped because downstream resources may trust that exact role
   ARN. But it gets a NEW name and ARN, so anything scoped to your current
   environment denies it. Find every such entry:
   - **Role permission policies**, inline (`aws iam list-role-policies`,
     `aws iam get-role-policy`) and attached (`aws iam
     list-attached-role-policies`, `aws iam get-policy`, `aws iam
     get-policy-version`): resources naming your current environment's log
     groups (the standard statement is scoped to
     `arn:aws:logs:<region>:<account>:log-group:airflow-<current-env>-*`) or
     its ARN.
   - **Role trust policy** (`aws iam get-role`): `aws:SourceArn` conditions
     scoped to your current environment's ARN. Without a match, the new or
     test environment is created but its tasks fail AssumeRole at runtime.
   - **KMS key policy and grants** (`aws kms get-key-policy`, `aws kms
     list-grants`): conditions scoped to your current environment's ARN, and
     CloudWatch Logs conditions (`kms:EncryptionContext:aws:logs:arn`) scoped
     to its log groups, such as
     `arn:aws:logs:<region>:<account>:log-group:airflow-<current-env>-*`.
     Without a match, `create-environment` or runtime encryption fails
     `AccessDenied`, or CloudWatch Logs cannot use the key for the new or
     test environment's log groups.
   - **Other environments using the same resources.** Run `aws mwaa
     list-environments`, then `aws mwaa get-environment --name <env>` for
     each, and note every environment other than your current one whose
     `ExecutionRoleArn` or `KmsKey` matches. Run this in every region the
     entries name. Tag only the list cleanup will remove, against the
     environment that cleanup retires:
     - New-environment upgrade: tag the found entries. Mark one `exclusive`
       only when it names your old (current) environment's exact ARN or its
       `airflow-<old-env>-*` pattern and no other environment matches it.
     - Rehearsed in-place upgrade: tag the added entries the same way,
       against the test copy's ARN and `airflow-<test-copy>-*` pattern.

     A pattern also matches environments whose names start with `<env>-`
     (`airflow-prod-*` covers `prod-eu`). Mark everything else
     `shared (<env or reason>)`, including wildcards such as `airflow-*` and
     entries whose region is `*`.

   For each entry, ADD a matching entry for the new or test environment.
   Never replace or remove your current environment's entry: both
   environments run until switchover. Always add the new environment's own
   log-group pattern (`airflow-<new-env>-*` or `airflow-<test-copy>-*`), even
   when the existing wildcard already matches it by prefix. Cleanup later
   removes one environment's entries: the New-environment upgrade removes
   the old pattern, which may be the wildcard the new environment relied on,
   and the Rehearsed in-place upgrade removes only the test copy's own
   pattern. Prefer a separate statement with its own Sid (letters and
   digits only, for example `MwaaUpgrade<NewEnvName>`) to keep the added
   entry distinct and reviewable; for the Rehearsed in-place upgrade that
   statement is also the entry cleanup later removes. When you must extend
   a condition value list instead, record the exact string. AWS-managed
   policies cannot be edited; add an inline statement instead.

   Find the entries now and list them in the plan. Apply the additions only
   after the user confirms the Phase 4 plan and before `create-environment`:
   show the exact before/after policy diff for each change and apply it only
   after the user approves that change. Record in the plan two labelled lists (policy name, Sid, or the
   exact resource/condition string): the entries you found scoped to your
   current environment, and the entries you added for the new or test
   environment.
   Cleanup removes one list and keeps the other, by approach: the
   New-environment upgrade removes the entries found for the old (current)
   environment and keeps the ones added for the new environment, which is
   now the live one; the Rehearsed in-place upgrade removes the entries
   added for the test copy and keeps your current environment's entries
   (SKILL.md Phase 8.3). Tag the entries in that list `exclusive` or
   `shared (<env or reason>)` using the check above.
   Cleanup removes only entries marked `exclusive` from the list for the
   chosen approach, after re-running the check above (environments may have
   been created since pre-flight). Never remove a `shared` entry. When a
   statement or condition list also names other resources, remove only the
   exact string, not the whole statement. If removing it would leave an empty
   `Resource` list or condition value list, remove the whole statement
   instead; never remove only an `aws:SourceArn` condition, because that
   widens the trust policy. Record KMS grants by grant ID in the same lists.
   Cleanup revokes only `exclusive` grants from the list being removed: the
   old environment's found grants for the New-environment upgrade, or the
   grants added for the test copy for the Rehearsed in-place upgrade
   (`aws kms revoke-grant --key-id <key> --grant-id <id>`). Never revoke a
   grant that is not in that list. Re-run `aws kms list-grants` first and
   skip any recorded grant that is already gone. Show the kept
   shared entries and
   their reasons in the diff.

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
version jumps. For each version jump record `from`, `to`, `python_from` and
`python_to` (the Python line of `from` and `to`, from `python_by_version`),
`python_change` (true when `python_from` differs from `python_to`), and
`crosses_major` (2.x -> 3.x). Also
record `eos_source` (true if the source version is in `eos_versions`;
informational — every remaining approach can upgrade away from an EOS
source). The 2.11.x stepping-stone version is skipped only when the source
is already 2.11.x (Python 3.12).
