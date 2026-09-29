# Deploying MWAA Artifacts

Deploy a just-authored artifact, and redeploy fixes, for both flavors. Every
state-mutating step here requires explicit user confirmation with the impact
stated (production safety). Warn on prod-named/tagged targets.

## Provisioned: deploy a DAG

1. Resolve the target environment's `SourceBucketArn` and `DagS3Path` via
   `aws mwaa get-environment --name <env>` (or `list-environments` when the name
   is vague). `SourceBucketArn` is an ARN (`arn:aws:s3:::my-bucket`) — derive
   the bare bucket name (the part after `s3:::`) and use THAT wherever a bucket
   name or `s3://` URI is needed (the `s3 cp` below, `--bucket` args, and the
   Serverless `--definition-s3-location`/`--code` `Bucket` field), never the
   full ARN.
2. **Check for dag_id conflicts before upload**: query `/dags/{dag_id}` via
   `invoke-rest-api`. If a DAG with the same ID already exists from a
   different `fileloc`, warn and ask whether to remove the old file — Airflow
   silently ignores the duplicate.
3. Upload the DAG object (use the bare bucket name from step 1, not the ARN):
   `aws s3 cp <local-dag>.py s3://<bucket-name>/<DagS3Path>/<dag>.py`.
4. The environment syncs from S3 and parses on its own schedule (seconds to a
   few minutes). Readiness after upload is testing-mwaa-workflow's Step 1, not
   this phase's job.

## Provisioned: post-deploy verification

After uploading, verify the scheduler parsed the new file and resolved any
conflicts. MWAA syncs from S3 on a scheduler cycle (seconds to a few minutes).

1. **Poll parse status** (after upload): the scheduler discovers new files on
   a periodic scan cycle. The governing config key differs by version:
   - AF2: `scheduler.dag_dir_list_interval`
   - AF3: `dag_processor.refresh_interval` (`dag_dir_list_interval` is
     deprecated)

   Fetch the configured value from `get-environment` →
   `AirflowConfigurationOptions`. If unset, both default to 300s (5 min).

   Recommended strategy: wait 30s after upload, then check once. If absent,
   wait the full configured interval and check again. Do not tight-poll at
   15s intervals — the file cannot appear between scan cycles.

   Re-query `/dags/{dag_id}` until `last_parsed_time` advances past the
   upload timestamp.
2. **Verify correct file**: confirm `fileloc` points to the newly uploaded
   filename.
3. **Confirm no import errors**: query `/importErrors` — an empty list means
   the DAG parsed cleanly.
4. **Confirm activation**: on **AF2 (REST API v1)** check `is_active: true`; on
   **AF3 (REST API v2)** the `is_active` field does not exist — check
   `is_stale: false` instead and never wait on `is_active` (it reads as
   absent/false forever on AF3). Query the `/dags` collection endpoint (not the
   per-DAG endpoint, which can lag). A parsed DAG remains untriggerable until
   the scheduler marks it ready — typically 1-5 minutes after first parse. If
   handing off to testing, testing's Step 1 readiness check handles this wait;
   if deploying standalone, poll until ready before reporting success.
5. **Spot-check schedule**: verify the returned schedule (field name varies by
   Airflow version: `schedule_interval` in 2.x (v1), `timetable_summary` in 3.x (v2)) matches
   the intended cron expression.

If verification fails (import error, wrong file, stale parse), diagnose before
proceeding to test. Common causes: syntax error in the DAG, dag_id collision
with another file, or S3 eventual-consistency delay (retry after 30s).

## Provisioned: create an environment inline (only if none exists and the user approves)

Creation is a plan-validate-execute operation with explicit confirmation. It
provisions VPC, subnets, security groups, an execution role, and an S3 bucket,
then `aws mwaa create-environment`. Poll `aws mwaa get-environment` until
`Status` is `AVAILABLE` (CREATING -> AVAILABLE takes ~20-40 minutes; this is the
environment-creation wait). The user may instead supply an existing
environment's name, in which case skip creation.

Apply the secure defaults from the "Secure defaults" section below. A minimal
secure inline creation looks like:

```
aws mwaa create-environment --name <env> \
  --airflow-version <version> \
  --source-bucket-arn arn:aws:s3:::<bucket> \
  --dag-s3-path dags/ \
  --execution-role-arn <role-arn> \
  --kms-key <customer-managed-key-arn> \
  --webserver-access-mode PRIVATE_ONLY \
  --network-configuration '{"SubnetIds":["<subnet-a>","<subnet-b>"],"SecurityGroupIds":["<sg>"]}' \
  --logging-configuration '{"TaskLogs":{"Enabled":true,"LogLevel":"INFO"},"SchedulerLogs":{"Enabled":true,"LogLevel":"INFO"}}'
```

- `--kms-key` (customer-managed): omitting it silently falls back to the
  AWS-owned key (immutable post-create) — state the choice explicitly.
- `--webserver-access-mode PRIVATE_ONLY` unless public web access is a stated
  requirement; scope the security group to known CIDRs, never `0.0.0.0/0`.
- `--logging-configuration`: enable at least Task and Scheduler logs at `INFO`
  so runtime failures and security-relevant events are captured from creation.
  MWAA also supports Webserver/Worker/DagProcessing log groups — enable per your
  observability needs.

**Inline-created execution role (trust + least privilege):** when the role is
built from scratch, scope its trust policy to the MWAA service principals
(`airflow.amazonaws.com` and `airflow-env.amazonaws.com`) and add
`aws:SourceArn` / `aws:SourceAccount` conditions to prevent the confused-deputy
problem. Grant only the exact Action/Resource pairs the DAGs need (the S3
artifact bucket, CloudWatch Logs, plus any services the DAGs call) — never
`*FullAccess` or `service:*`.

## Serverless: deploy a workflow

1. Determine whether a code package is needed. `--code` is required ONLY when:
   - `PythonOperator` references an external module (`python_callable:
     module.function`), OR
   - `BashOperator` references an external script file.

   Inline `bash_command` strings (e.g., `echo`, `sleep`, `python3 -c '...'`)
   work without `--code`.

   If needed, build the code package and upload it to S3 (see
   [serverless-code-packaging.md](serverless-code-packaging.md)):
   `aws s3 cp my_code.zip s3://<bucket>/<code-key>`.
2. New: `aws mwaa-serverless create-workflow --name <name>
   --role-arn <execution-role-arn>
   --description "<workflow description>"
   --definition-s3-location '{"Bucket":"<bucket-name>","ObjectKey":"<yaml-key>"}'`, adding
   `--code '{"S3Location":{"Bucket":"<bucket-name>","ObjectKey":"<code-key>"}}'` when the
   workflow uses custom code per step 1. The YAML is validated synchronously
   here — a definition error surfaces now, not at run time.
3. Existing: the user supplies the workflow ARN; skip creation.
4. Inspect existing workflow: `aws mwaa-serverless get-workflow
   --workflow-arn <arn>` (requires `--workflow-arn`, not `--name`).

Recommend S3 versioning and a pinned `VersionId` in the `--code`/definition
locations for production reproducibility.

**Code snapshotting:** the service snapshots the code at
`create-workflow`/`update-workflow` time (`CodeSnapshottedAt` in the
response). Updating the S3 object alone does NOT update the workflow's
code — call `update-workflow` with `--code` again to re-snapshot.

## Redeploy (fix loop)

Reused when testing-mwaa-workflow delegates an ARTIFACT or ENVIRONMENT fix:

- Provisioned: re-run the `aws s3 cp` upload (same path) after regenerating the
  DAG; for an ENVIRONMENT fix, update `requirements.txt`/`plugins.zip` in S3 and
  `aws mwaa update-environment` with the new `RequirementsS3Path`/version.
- Serverless: `aws mwaa-serverless update-workflow --workflow-arn <arn>
  --role-arn <execution-role-arn> --definition-s3-location '{"Bucket":"<bucket-name>","ObjectKey":"<yaml-key>"}'`; for a code
  fix, re-upload the package AND call `update-workflow` with
  `--code '{"S3Location":{...}}'` (both steps required — re-uploading to S3
  alone does not re-snapshot). `--role-arn` is required even when unchanged.

## Production safety

`create-environment`, `update-environment`, `create-workflow`, and
`update-workflow` are the state-mutating operations. Present each command and
its impact; obtain explicit confirmation before running it. Never disable
termination/deletion protection or other safeguards without explicit
confirmation and justification.

## Secure defaults

When this skill provisions resources from scratch (no pre-existing
environment), apply secure defaults and surface each one in the deploy
confirmation so the user approves the security posture, not just the resource:

- **S3 buckets**: enable SSE-KMS (customer-managed key) and Block Public Access;
  attach a scoped bucket policy — never a public or account-wide grant.
- **MWAA environment**: pass `--kms-key` (customer-managed) and
  `--webserver-access-mode PRIVATE_ONLY` unless public web access is explicitly
  required; scope `SecurityGroupIds` to known CIDRs — never `0.0.0.0/0`.
- **SNS topics**: enable server-side encryption and restrict `Publish` to the
  execution role; confirm subscribers are expected recipients.
- **CloudWatch log groups**: associate a KMS key for encryption at rest.
- **Monitoring**: after the environment is created, point the user at its
  built-in CloudWatch metrics dashboard (on the environment details page) and
  the one-click **Create recommended alarms** action, which provisions a
  curated, AWS-managed alarm set so health regressions and failures are caught
  from creation. Use the console action rather than hardcoding an alarm
  list/thresholds (they stay current); see
  https://docs.aws.amazon.com/mwaa/latest/userguide/monitoring-dashboard.html

State each default (and any deviation, such as an AWS-owned key or public
web access) explicitly so the deviation is a conscious, confirmed choice.

**AWS security best practices (verify at runtime):** these defaults track — but
do not replace — the canonical MWAA security best practices, which AWS updates
over time. Verify the security posture against them before finalizing:

- Provisioned: https://docs.aws.amazon.com/mwaa/latest/userguide/security-best-practices.html
- Serverless: https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/security-best-practices.html
