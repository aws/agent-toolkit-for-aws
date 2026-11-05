# Auto Version Setup Workflow

Set up AWS Glue auto version (GlueVersion = "auto") for a customer's existing Spark ETL jobs in three phases:

1. **Phase 1 — Assess (read-only; needs the `spark-upgrade` server).** Run the SageMaker Unified Studio Spark Upgrade MCP server (`spark-upgrade`) `generate_assessment` tool against each job in scope and aggregate a portfolio-level eligibility report. No job configuration changes. Ask nothing that the request already answers; default the target to Glue 6.0.
2. **Phase 2 — Enable (optional, changes jobs).** For the ELIGIBLE jobs in the table the user confirms ('proceed', or a one-turn approval that names them), or (without the server) the jobs the user names and confirms as idempotent, set GlueVersion to `auto` with a full-configuration `update-job`; the confirmation in [enabling-jobs.md](enabling-jobs.md) §6.
3. **Phase 3 — Notify (optional, creates resources).** Once per account and Region, create an SNS topic, an email subscription, and four EventBridge rules that email auto version state changes for every job in the account and Region.

The user can stop after Phase 1. Before Phase 2 or Phase 3, tell the user that those phases change the account (job definitions; SNS and EventBridge resources) and proceed only with their confirmation. The eligible table's 'proceed' offer is that statement for Phase 2.

Every Glue call in Phases 2 and 3 goes through the AWS CLI from the shell (see [cli-setup.md](cli-setup.md)). The other AWS calls (the Phase 1 reads `sts get-caller-identity`, `glue get-jobs` (or `batch-get-jobs`, with `list-jobs` for a tag scope) and `glue get-job`, and the SNS, EventBridge and KMS calls) may go through the AWS MCP server's `run_script` tool when it is connected; otherwise use the AWS CLI. The `generate_assessment` calls always go through the `spark-upgrade` MCP server.

## Reference Documentation

- [mcp-configuration.md](mcp-configuration.md) -- Spark Upgrade MCP server setup and verification
- [report-format.md](report-format.md) -- Placement mapping, the eligible table and the counts line
- [error-handling.md](error-handling.md) -- Common failures and resolution strategies
- [cli-setup.md](cli-setup.md) -- AWS CLI preflight for auto version calls
- [enabling-jobs.md](enabling-jobs.md) -- Phase 2 refusal gate, full JobUpdate merge, verification, what happens next
- [notifications.md](notifications.md) -- Phase 3 event patterns, email templates, topic policy, existing setups

## Workflow

### Phase 0: Verify Dependencies

Confirm the environment is usable before touching any job:

1. **MCP server**: Verify the `spark-upgrade` MCP server is configured and its tools are loaded. Confirm `generate_assessment` appears in the tool list. If the server or tool is missing, do not stop: give the user this text and wait for the choice:

   > The `spark-upgrade` MCP server is not connected, so I can't run the auto version eligibility assessment. It has no AWS API or CLI equivalent. You can:
   > 1. **Add the server and restart.** I'll give you the configuration; after you restart the session and ask again, I'll run the assessment.
   > 2. **Continue without the assessment.** Tell me which jobs to enable and confirm for each one that it is idempotent (safe to re-run against its real sources and sinks). I'll check each job's configuration, show a preview, and enable it only after you confirm it by name. AWS Glue runs its pre-upgrade eligibility check (the same check the assessment runs) when auto version is enabled, and rolls back a job that isn't eligible.

   On option 1, you MUST read [mcp-configuration.md](mcp-configuration.md) and give the user its configuration. On option 2, follow [No-server path (option 2)](#no-server-path-option-2). You MUST NOT produce an eligibility verdict from the script, job arguments or general Spark knowledge.
2. **Credentials**: Confirm identity and account with `aws sts get-caller-identity`. The caller needs read access to Glue job definitions and their script locations in S3.
3. **Scope**: Take the Region, account and job scope from the request; ask only for a missing Region or account, in one question.
4. **AWS CLI (Phases 2-3 only)**: If the user wants to enable auto version or set up notifications, run the setup check in [cli-setup.md](cli-setup.md) before the first Phase 2 or Phase 3 call. On failure, STOP with the message given there. Do not install, update, or download the AWS CLI or any other software yourself; tell the user what to update and stop.

### No-server path (option 2)

Only when the `spark-upgrade` server is missing and the user chose option 2 in Phase 0:

1. Resolve the target Glue version as in Step 1.2 (Glue 6.0). Phase 2's "already on the target version" check needs it.
2. For each job the user names, run a fresh `aws glue get-job` and classify it with the Phase 1 structural rules only (Step 1.1): OUT_OF_SCOPE (not `glueetl`), NEEDS_CONFIG_CHANGES (`MaxRetries` missing or < 1), the run-queuing refusal (`JobRunQueuingEnabled` = true), ALREADY_CURRENT, ALREADY_AUTO. Every other job is NOT_ASSESSED, never ELIGIBLE.
3. Show the list with each job's classification and ask for a confirmation per NOT_ASSESSED job that names the job and states it is idempotent (for example "enable etl-a, it is idempotent"). If the user says a job is not idempotent or does not know, that job is NOT_ENABLED (idempotency unconfirmed). Explain why: after an approval, up to 3 upgrade runs execute the job on the new version against its real sources and sinks; a failed upgrade run is retried on the current version using a retry attempt, so one trigger can execute the job twice; written data is not rolled back.
4. Continue with Phase 2 for the confirmed NOT_ASSESSED jobs only.

**Constraints:**

- You MUST NOT read the script to judge eligibility or idempotency, and MUST NOT call any job safe or eligible.
- You MUST NOT offer to make a job idempotent.
- The scope is the jobs the user names. Without the assessment, you MUST NOT sweep "all jobs" in the account or Region.
- A statement that covers several jobs ("they're all idempotent") is not a confirmation: list the jobs and ask for each one.
- A job whose most recent assessment in this session is not ELIGIBLE cannot use this path (Phase 2 step 2).

### Phase 1: Assess Eligibility (read-only)

#### Step 1.1: Collect Job Inventory

Announce the scan in one line, without asking anything, for example: "Scanning Glue 4.0 Spark ETL jobs in 111122223333 / us-east-1 and checking each one's auto version eligibility for Glue 6.0 (read-only, about 1 minute per job)." Then enumerate the jobs in scope with one projected `get-jobs` call:

```bash
aws glue get-jobs --region <region> --no-cli-pager --output json \
  --query "Jobs[?GlueVersion=='<source version>'].{Name:Name,GlueVersion:GlueVersion,Command:Command.Name,MaxRetries:MaxRetries,Queuing:JobRunQueuingEnabled,Script:Command.ScriptLocation,Lang:DefaultArguments.\"--job-language\"}"
```

- The CLI paginates automatically, up to 1000 jobs per page. Without a version in the request, drop the filter: `Jobs[].{…}`.
- For an explicit name list, use `aws glue batch-get-jobs --job-names <names…>` with the same projection on `Jobs[]`, and report `JobsNotFound`.
- For a tag scope, use `aws glue list-jobs --tags <k>=<v>` → names → `batch-get-jobs`.
- The projection never selects `DefaultArguments` values except `--job-language`. The assessment's `job_arguments` come from a fresh `aws glue get-job --job-name <job> --query "Job.DefaultArguments"` per assessed job, passed straight to the tool and never printed.

**Constraints:**

- You MUST classify jobs by command name first. Assess only Spark batch jobs (`glueetl`); report `gluestreaming`, `pythonshell`, and Ray jobs as OUT_OF_SCOPE without calling the assessment tool — auto-upgrade does not cover streaming jobs.
- Jobs already on the target version (Glue 6.0) or already set to `"auto"` MUST be reported as-is (ALREADY_CURRENT / ALREADY_AUTO), not re-assessed.
- Jobs with `MaxRetries` missing or < 1 MUST be reported as NEEDS_CONFIG_CHANGES without calling the assessment tool: GlueVersion = "auto" requires `MaxRetries` >= 1 because the canary rollback re-run consumes a retry attempt.
- If the scope exceeds 25 jobs, state the job count and a runtime estimate (about 1 minute per job) in the scan announcement, then continue; do not ask for confirmation.

#### Step 1.2: Run Assessments Sequentially

The default target is Glue 6.0 unless the user names another version; start the scan without asking for the target. The result names the target and points to the AWS Glue versions page (https://docs.aws.amazon.com/glue/latest/dg/release-notes.html) for the latest versions; a different target is a re-run of Phase 1 with that version.

Call `generate_assessment` once per job, **sequentially by default**, with:

- `mode`: `auto_version_eligibility_assessment` — the same static gate the auto-upgrade flow runs before upgrading; never the default `spark_upgrade_assessment` mode
- `application_type`: `glue`; `application_context`: `{"job_arguments": <DefaultArguments>, "script_location": <ScriptLocation>, "language": "python" | "scala", "source_glue_version": <current GlueVersion>, "target_glue_version": <resolved target Glue version>}`
- `source_spark_version` / `target_spark_version`: the Spark version shipped with the job's current GlueVersion, and the Spark version shipped with the resolved target Glue version (AWS Glue versions page: Glue 3.0 = Spark 3.1.1, 4.0 = 3.3.0, 5.0 = 3.5.4, 5.1 = 3.5.6, 6.0 = 4.1.1). Never pass a Spark version that belongs to a different Glue version than `target_glue_version`.
- Omit `output_path`; the response carries the verdict, the categories checked and the findings.

Pass each job's actual details collected in Phase 1 — never assess from assumed defaults.

**Constraints:**

- You MUST NOT parallelize assessment calls unless the user explicitly asks and accepts the throttling risk.
- Phase 1 is read-only against Glue. You MUST NOT call `update-job`, change GlueVersion, trigger an upgrade, or start any job run during Phase 1.
- If an individual assessment fails, record the job as ASSESSMENT_ERROR with the error message and continue — one failure MUST NOT abort the batch. Retry a failed job at most once.
- For batches of 10+ jobs, report progress to the user every 10 jobs (completed / remaining / failures so far).

#### Step 1.3: Present Results

Map each response with [report-format.md](report-format.md) and present the eligible table, the counts line, and the offers exactly as specified there.

**Constraints:**

- You MUST end with the 'proceed' offer (after a one-turn approval, only for listed jobs that were not named); the table is informational until the user replies 'proceed' or the request named the job to enable ([enabling-jobs.md](enabling-jobs.md) §6), and each upgrade still waits for its own consent.
- You MAY offer Phase 2 for ELIGIBLE jobs, and for NOT_ASSESSED jobs on the no-server path. You MUST NOT enable any job without the confirmation in [enabling-jobs.md](enabling-jobs.md) §6.

### Phase 2: Enable Auto Version (optional, changes jobs)

Follow [enabling-jobs.md](enabling-jobs.md) for each job in the confirmed table, in table order (on the no-server path, for each confirmed NOT_ASSESSED job), one job at a time:

1. Fresh `aws glue get-job`.
2. Refusal gate — refuse with the reason and make no change when the job is not `glueetl`, has `MaxRetries` < 1, has `JobRunQueuingEnabled` = true, is already on the target version (Glue 6.0), is already `auto`, or its most recent assessment in this session has a verdict other than ELIGIBLE. The user cannot override a block by asking. After the user fixes the cause (for example sets `MaxRetries` to 1 or more), re-run Phase 1 for that job; the new verdict replaces the old one.
3. Build the full `JobUpdate` from every `JobUpdate` member present in `Job`, with `GlueVersion` = `auto`. Before answering about or performing this phase, you MUST read [enabling-jobs.md](enabling-jobs.md); copy only the listed JobUpdate members.
4. A preview only for a job with an enable preview flag ([enabling-jobs.md](enabling-jobs.md) §5: `ProfileName` would be lost, `SourceControlDetails` round trip unverified, or NOT_ASSESSED); that job waits for its own reply naming the job.
5. `AWS_SDK_UA_APP_ID=managing-glue-jobs-skill aws glue update-job --job-name <job> --job-update file://<temp file>`, inside the temp-file command of [enabling-jobs.md](enabling-jobs.md) §7.
6. Verify with a fresh `get-job` against the payload and the step 1 response; on any unexpected difference stop the batch and offer to set the changed members back with a confirmed full `update-job`.
7. One line per job: `✓ <job>: GlueVersion <old> → auto (enrollment started)` or `✗ <job>: <error verbatim>`.

Then show the "What happens next" block from [enabling-jobs.md](enabling-jobs.md) §9 once for the batch. If a job was enabled without the assessment (NOT_ASSESSED), also tell the user: "AWS Glue is now running its pre-upgrade eligibility check (the same check the assessment runs). If the job isn't eligible, Glue rolls it back to its previous version and turns auto version off for it; nothing runs on the new version." Then verify as in [enabling-jobs.md](enabling-jobs.md) step 8.

**Constraints:**

- You MUST send a full `JobUpdate` built from the fresh `get-job`. You MUST NOT send a partial update (for example only `GlueVersion`), swap `Role`, or include `AllocatedCapacity`. After every successful `update-job`, you MUST re-read the job with `get-job` and compare `GlueVersion` (`auto`) and every member you sent ([enabling-jobs.md](enabling-jobs.md) §8), and report any mismatch; include this check whenever you describe the enable path.
- You MUST NOT change `MaxRetries` or offer to change it, and MUST NOT create new jobs.
- You MUST enable only the jobs in the eligible table the user confirmed with 'proceed', or named in a one-turn approval, in table order, following the confirmation in [enabling-jobs.md](enabling-jobs.md) §6.
- You MUST process jobs sequentially; one job's `update-job` error fails only that job, except an "account not supported" error, which stops the batch.

### Phase 3: Email Notifications (optional, creates resources)

Before answering about or performing this phase, you MUST read [notifications.md](notifications.md); follow it once per account and Region. The setup covers every auto version job in the Region, not only the jobs enabled in this session:

1. Ask only for the recipient email address if the user hasn't given it, and ask the user to confirm that it belongs to personnel authorized to receive job metadata. Use the fixed names in notifications.md. Encrypt the topic with a dedicated new key `alias/<prefix>-notifications` by default, without asking (the preview shows its key policy and its cost; see [AWS KMS pricing](https://aws.amazon.com/kms/pricing/)); use the user's customer-managed KMS key only if the user names one; unencrypted only on the user's explicit opt-out, with a warning.
2. Create the dedicated key if needed, then the SNS topic `glue-auto-version-notifications` encrypted with the key.
3. Create, or reuse when present, the four rules `glue-auto-version-consent-required`, `-upgrade-completed`, `-upgrade-failed`, `-upgrade-stopped` with source `aws.glue-autoversion`, detail-type `Auto Version Job State Change` and the group's `detail.state` values, without a job filter.
4. Add one SNS target per rule with that group's input transformer, or update it only if it differs.
5. Merge the `AllowGlueAutoVersionEventBridge` statement into the topic policy, scoped to the four rule ARNs.
6. Subscribe the email address unless it is already subscribed, and tell the user to click the confirmation link.

Jobs enabled later are covered automatically; do not run Phase 3 again for them.

**Constraints:**

- You MUST scope the topic policy and the dedicated key policy to the four exact rule ARNs. You MUST NOT use `rule/*` or raw-JSON email bodies. You MUST NOT modify or delete any other EventBridge rule unless the user names it.
- You MUST NOT email `UPGRADE_RUN_SUCCEEDED`, `UPGRADE_RUN_FAILED`, `POST_OBSERVING_FAILED`, `OBSERVATION_COMPLETED`, or `EVALUATION_STARTED`.
- Every EventBridge target MUST carry the group InputTransformer from [notifications.md](notifications.md); a target with only Id and Arn sends raw JSON.
- You MUST keep other statements in an existing topic policy.
- You MUST NOT use the AWS managed key `alias/aws/sns`: EventBridge cannot be granted use of it, so deliveries fail.
- You MUST NOT edit an existing key's policy or schedule any key for deletion; you create a key policy only for the dedicated key you create.
- You MUST NOT create an unencrypted topic unless the user explicitly opts out; then warn that it is unencrypted at rest.
- You MUST tell the user that events are best effort: an email can be missed, so check status directly as well.

## Argument Routing

These conditions are additive — apply all that match to suppress the corresponding prompts:

- **No args**: Ask for the Region (and the profile if no default credentials); the scope defaults to all Spark ETL jobs in the Region
- **Account or profile provided**: Skip the credentials prompt
- **Region provided**: Skip the region prompt
- **Job filter provided**: Skip the scope prompt and assess only matching jobs

## Gotchas

- `generate_assessment` operates on the job's script and configuration; it needs S3 read access to the script location. An AccessDenied on the script is a permission gap, not an eligibility verdict.
- The `--read-timeout 180` on the MCP proxy is intentional — assessments can take several minutes per job. Do not lower it.
- Sequential execution is the default because the assessment service throttles aggressively under parallel load.
- Do not enable "trust" for all tool calls by default. Review each tool execution.
- `UpdateJob` replaces the whole job definition. A partial `JobUpdate` resets every omitted member, which is why Phase 2 always merges the full definition from a fresh `get-job`.
- `aws glue get-jobs` returns `AutoUpgradeMetadata` as null; read it from `get-job`.
- `get-jobs` returns full definitions including `DefaultArguments` values; always use the projection.
- Enabling auto version does not start runs; jobs that rarely run take correspondingly long to reach the consent checkpoint.

## Security Considerations

- **Read-only assessment.** Phase 1 reads job definitions (`glue:GetJobs`; `glue:BatchGetJobs` for a name list; `glue:ListJobs` + `glue:BatchGetJobs` for a tag scope; `glue:GetJob` for each assessed job's arguments), reads job scripts from S3 (`s3:GetObject`), and calls the SigV4-protected `generate_assessment` tool. It never calls `UpdateJob`, changes `GlueVersion`, starts job runs, or modifies job scripts. It writes nothing: the assessment is called without `output_path`, so no report is written to S3. Prefer least-privilege credentials scoped to those actions; do not use admin credentials when a scoped role is available.
- **Findings stay in the conversation.** The assessment response carries the findings; this workflow writes no assessment report. If the user asks for a stored report, the assessment can be re-run with an `output_path` in a bucket with default encryption (SSE-S3 or SSE-KMS) and S3 Block Public Access enabled.
- **Job scripts may contain sensitive logic.** Script content is sent to the assessment service for analysis over the SigV4-authenticated, TLS-encrypted MCP endpoint (encrypted in transit); it is not written to disk or echoed into chat beyond the findings needed for the report.
- **No secrets in configuration.** The MCP configuration uses SigV4 via `mcp-proxy-for-aws` and the standard AWS credential chain — never embed access keys in `.mcp.json` or agent configuration files.
- **Error messages can leak paths.** ASSESSMENT_ERROR entries include the tool's error message; these may contain S3 URIs and job names but no credentials. Review before pasting reports into public channels.
- **Consent boundary.** Phases 2 and 3 change the account and run only after the user confirms: Phase 2 after the confirmation in [enabling-jobs.md](enabling-jobs.md) §6; Phase 3 after the recipient and resource names are confirmed. An informational assessment request never becomes a mutating one on its own, and enabling auto version never approves an upgrade — each upgrade still waits for explicit consent.
- **Mutating permissions.** Phase 2 needs `glue:GetJob`, `glue:UpdateJob`, and `iam:PassRole` on the job's existing role (`UpdateJob` passes `Role`). Phase 3 needs `kms:CreateKey`, `kms:CreateAlias`, `kms:TagResource`, `kms:DescribeKey` (for the dedicated key), `sns:CreateTopic`, `sns:Subscribe`, `sns:GetTopicAttributes`, `sns:SetTopicAttributes`, `sns:ListSubscriptionsByTopic`, `sns:ListTopics`, `events:PutRule`, `events:PutTargets`, `events:DescribeRule`, `events:ListTargetsByRule`, and `events:ListRules`; `events:RemoveTargets` and `events:DeleteRule` only if the user asks to delete a named older rule. This workflow does not create or modify IAM roles or policies, and it creates a key policy only for the dedicated key it creates; grant these to the caller separately, scoped to the jobs, topic, and rules involved.
- **Update payloads hold secrets.** The update payload holds `DefaultArguments` values; it is written to a temporary directory deleted in the same command.
- **Notification recipients and encryption.** Emails carry job names, Glue versions, analysis IDs, failure reasons, and an AWS Glue console link — never job data. Subscribe only addresses the user confirms are authorized. Topics are encrypted at rest by default with a customer-managed KMS key: the user's key, or a dedicated key the workflow creates whose policy lets `events.amazonaws.com` use it only for the four rules. The AWS managed key `alias/aws/sns` cannot be used with EventBridge. The topic is unencrypted only on explicit opt-out, with a warning. The topic policy allows `sns:Publish` only from the four rule ARNs. The rules cover every auto version job in the account and Region, so recipients get emails for jobs other people enable too.
- **Audit and monitoring.** Enable S3 server access logging or CloudTrail data events on the report bucket, and use CloudTrail management events and CloudWatch to monitor `UpdateJob`, `StartJobUpgradeAnalysis`, and SNS/EventBridge changes.
- **No-server path.** No new write types: the same full `UpdateJob`, preview and per-job named idempotency confirmation. AWS Glue runs its pre-upgrade eligibility check (the same check the assessment runs), and the service rolls back an ineligible job.
- Follow the [AWS Glue security best practices](https://docs.aws.amazon.com/glue/latest/dg/security.html) and [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) when granting the read access this workflow needs.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `generate_assessment` not in tool list | Wrong MCP server or stale session | Verify the `spark-upgrade` server entry, restart the chat session — see [mcp-configuration.md](mcp-configuration.md); or continue without the assessment (Phase 0, option 2) |
| MCP server failed to load | Configuration or credentials issue | Verify JSON syntax, AWS credentials, and IAM permissions |
| Throttling error | Service limit reached under repeated calls | Wait a few seconds and retry the failed job; keep execution sequential |
| AccessDeniedException | IAM permission issue | Check the error message and fix the permission policy |
| Read timeout during assessment | Large job script takes longer than configured timeout | Increase `--read-timeout` in the MCP config (default 180s) |
| `Invalid choice` from `aws glue get-job-upgrade-analysis` | AWS CLI lacks the auto version APIs | STOP with the message in [cli-setup.md](cli-setup.md) |
| `update-job` says GlueVersion `auto` is not supported for the account | Account not enabled for auto version | Stop the batch; no job was changed |

**Detailed guidance:** [error-handling.md](error-handling.md)
