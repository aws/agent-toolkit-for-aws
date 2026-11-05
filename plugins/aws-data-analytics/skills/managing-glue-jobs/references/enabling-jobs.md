<!-- markdownlint-disable MD033 -->
# Enabling Auto Version on an Existing Job (Phase 2)

Process one job at a time, in the order of the confirmed table. Every Glue call here goes through the AWS CLI (`aws glue ...`, see [cli-setup.md](cli-setup.md)), with `--region <region>`.

## 1. Fresh Job Definition

```bash
aws glue get-job --job-name <job> --region <region> --no-cli-pager
```

Use this response, not the Phase 1 inventory: the job may have changed since the assessment.

## 2. Refusal Gate

Refuse with the stated reason and make no change when any row matches:

| Condition (from the fresh `Job`) | Reason given to the user |
|----------------------------------|--------------------------|
| `Command.Name` is not `glueetl` | Auto version covers Spark batch ETL jobs only. |
| `MaxRetries` missing or < 1 | Auto version requires `MaxRetries` >= 1: a failed upgrade run is retried on the current version using a retry attempt. This workflow does not change `MaxRetries`; the user decides on retry safety for the job. |
| `JobRunQueuingEnabled` is `true` | Job run queuing is not compatible with auto version. |
| `GlueVersion` is the target version (Glue 6.0) | Already on the target version; no upgrade applies. |
| `GlueVersion` is `auto` | Already enrolled in auto version. |
| Its most recent assessment in this session has a verdict other than ELIGIBLE | Show the Phase 1 blocking reason. The user cannot override a block by asking. After the user fixes the cause (for example sets `MaxRetries` to 1 or more), re-run Phase 1 for that job; the new verdict replaces the old one. |
| Not assessed, and the user has not confirmed this job as idempotent | Ask for the per-job idempotency confirmation; if unknown, do not enable. |

Do NOT offer to change `MaxRetries`, disable queuing, or fix code as part of this workflow. Creating a new job with GlueVersion `auto` is out of scope: a job created as auto upgrades directly without a consent checkpoint.

## 4. Build the Full JobUpdate

`UpdateJob` replaces the whole job definition: any member left out of `JobUpdate` is reset to its default. Never send a partial update such as only `GlueVersion`.

Copy each of these `JobUpdate` members from `Job` when present, unchanged:

`JobMode`, `JobRunQueuingEnabled`, `Description`, `LogUri`, `Role`, `ExecutionProperty`, `Command`, `DefaultArguments`, `NonOverridableArguments`, `Connections`, `MaxRetries`, `Timeout`, `MaxCapacity`, `WorkerType`, `NumberOfWorkers`, `SecurityConfiguration`, `NotificationProperty`, `GlueVersion`, `CodeGenConfigurationNodes`, `ExecutionClass`, `SourceControlDetails`, `MaintenanceWindow`

Then apply these rules:

- Set `GlueVersion` to `"auto"`. This is the only value that changes.
- Never include `AllocatedCapacity` (deprecated).
- If `WorkerType` is set, drop `MaxCapacity` (`UpdateJob` rejects both together). If `WorkerType` is not set, keep `MaxCapacity`.
- Copy `Role` verbatim. Never substitute a different role.
- Do not copy read-only `Job` members that are not in `JobUpdate`: `Name`, `CreatedOn`, `LastModifiedOn`, `AutoUpgradeMetadata`, `AllocatedCapacity`. `ProfileName` is also not in `JobUpdate` and cannot be preserved by this call: if the job has `ProfileName`, list it as a field that may be lost and get the user's confirmation for that job before continuing.
- If the job has `SourceControlDetails`, copy it but warn in the preview that `get-job` does not return the source control auth token and the round trip through `update-job` is not verified; get the user's confirmation for that job before continuing.

Write the payload only inside the update command (step 7).

## 5. Preview (only for jobs with an enable preview flag)

A job has an enable preview flag when `ProfileName` would be lost, its `SourceControlDetails` round trip is unverified, or it is NOT_ASSESSED. Show the user, for each such job:

- **Changed**: `GlueVersion: <old> -> auto` (the only changed value).
- **Preserved**: the names of the copied members, without values — `DefaultArguments` and `NonOverridableArguments` can carry secrets; show only the key count (for example "DefaultArguments (2 keys)").
- **Dropped**: each omitted member with its reason (`AllocatedCapacity`: deprecated; `MaxCapacity`: conflicts with `WorkerType`; `ProfileName`: not supported by `UpdateJob`).
- **Enable preview flags**: `ProfileName` would be lost; `SourceControlDetails` round trip not verified (only when present).
- **Enable preview flag (NOT_ASSESSED jobs only)**: "Not assessed. After the update, AWS Glue runs its pre-upgrade eligibility check (the same check the assessment runs). If the job is not eligible, Glue rolls it back to Glue <current> and turns auto version off for it; nothing runs on the new version. If it is eligible, nothing is upgraded until you approve later."

Every other job gets only the one-line result after step 8.

## 6. Confirmation

Enable a job only when it is in the eligible table the user confirmed with "proceed" (or "enable these") in this conversation, or when it is named in a one-turn approval (below). A request to enable jobs before any table was shown is not a confirmation: run the scan (auto-version-setup.md Phase 1) and show the table. Jobs with an enable preview flag need their own reply naming the job. If the table is from earlier in a long session, say so and offer to re-scan; the fresh get-job, the refusal gate and AWS Glue's own eligibility check still apply.

**One-turn approval.** A request that names each job and asks to enable it (for example "enable etl-a" or "enable etl-a if it is eligible") confirms exactly the named jobs, and only those in the eligible table from the scan in that turn: run Phase 1, show the table, then enable each named job that is in it, in table order. Refuse a named job that is not in the table and give its Phase 1 reason (a block cannot be overridden). Do not enable a listed job the request did not name; offer "proceed" for those. A request without job names ("enable all eligible jobs", even with "I approve") is not a one-turn approval: show the table and wait for "proceed". On the no-server path there is no eligible table, so the NOT_ASSESSED rule below applies. A named job with an enable preview flag still gets its preview and waits for its own reply. The approval covers only the scan in the same turn, and it is never an upgrade consent decision.

For a NOT_ASSESSED job (no-server path), the confirmation names the job and states it is idempotent, for example "enable etl-a, it is idempotent". "They are all idempotent", "yes", or a list does not count: ask again for each job. If the user does not know or says the job is not idempotent, do not enable it: list it as NOT_ENABLED with the reason (after an approval, upgrade runs re-run the job against its real sources and sinks, and a failed upgrade run is retried).

## 7. Update

Write the payload to a temporary directory that is deleted in the same command:

```bash
(D=$(mktemp -d); trap 'rm -rf "$D"' EXIT; umask 077; cat > "$D/u.json" <<'JSON'
<full JobUpdate JSON>
JSON
AWS_SDK_UA_APP_ID=managing-glue-jobs-skill aws glue update-job --job-name <job> --job-update file://"$D/u.json" --region <region> --no-cli-pager)
```

The heredoc terminator `JSON` starts at column 0.

The `AWS_SDK_UA_APP_ID` prefix adds `app/managing-glue-jobs-skill` to the call's user agent so the change can be attributed in AWS CloudTrail; keep it on the command. The command is POSIX shell. In PowerShell, write the payload with `New-TemporaryFile`, set `$env:AWS_SDK_UA_APP_ID = 'managing-glue-jobs-skill'`, run `aws glue update-job … --job-update file://<path>`, then `Remove-Item <path>` in the same command.

After a successful update, always run step 8 before you report the job as enabled; when you describe this path, include that step. Show `UpdateJob` errors verbatim. For `InvalidInputException` messages, see [error-handling.md](error-handling.md). An error saying GlueVersion `auto` is not supported for the account stops the whole batch (the account is not enabled for auto version); any other error fails only that job — record it and continue with the next confirmed job.

## 8. Verify

Run `aws glue get-job --job-name <job>` again and compare it with the payload you sent:

- `GlueVersion` is `auto`.
- Every other member you sent in the payload has the same value. Glue recomputes `MaxCapacity` and `AllocatedCapacity` from `WorkerType` and `NumberOfWorkers`, so exclude them when `WorkerType` is set.
- A member that was absent from the step 1 response and now has a service default (for example `ExecutionClass` `STANDARD`, `Timeout` 2880) is informational: report it, do not stop.
- `Job.AutoUpgradeMetadata` is present (poll every 10 s for up to 60 s). Compare `Status` as a string: `OBSERVING` or a `PENDING_*` value right after the update means enrollment started. For a NOT_ASSESSED job, Glue is still running its pre-upgrade eligibility check (the same check the assessment runs): poll `get-job` every 30 s for up to 5 min.
- `UPGRADE_FAILED` (or `FAILED` from `aws glue get-job-upgrade-analysis`) with the job back on its previous `GlueVersion` means Glue's pre-upgrade eligibility check (the same check the assessment runs) rejected the job, or could not complete it, and rolled it back. Read the reason with this command only (it selects no report location). The analysis ID is `Job.AutoUpgradeMetadata.AnalysisId` from the first poll that showed the metadata: after a rollback, get-job no longer shows AutoUpgradeMetadata, so keep the ID from that poll.

  `aws glue get-job-upgrade-analysis --job-name <job> --analysis-id <analysisId> --region <region> --no-cli-pager --query "{status:status,sourceVersion:sourceVersion,targetVersion:targetVersion,errorMessage:errorMessage}"`

  Report the version the job is on (from `get-job`; `sourceVersion` in this read is the version the analysis started from), the label "Not upgraded: AWS Glue rolled the job back to Glue <version>; auto version is off for this job" and `errorMessage` verbatim (free text, for example "Pre-upgrade eligibility check failed: breaking changes detected"). Then read the evaluation summary with the Evaluation Summary Read in [consent-review.md](consent-review.md) and report its blocking findings (its Compatibility Assessment section); if it is not available yet, say so and point to the AWS Glue console (the job's View Auto upgrade analysis). Do not re-enable, retry or change the job. Offer option 1 of [auto-version-setup.md](auto-version-setup.md) Phase 0 (the `spark-upgrade` server) to see the blocking reasons before any new attempt.
- When the service has rolled the job back, skip `GlueVersion` in the comparison: a rollback is not a verify failure; any other difference still is.
- If the status is still `OBSERVING` with `GlueVersion` `auto` after 5 min: say the pre-upgrade eligibility check has most likely passed (the read APIs do not report the check's result; it normally finishes within about 4 minutes). A rollback will show as `UPGRADE_FAILED` (and as an email if Phase 3 is set up). Check again later with `get-job`.

If a member you sent has a different value, or `ProfileName` was lost: STOP the batch, show the field-by-field difference, and offer to set the changed members back: a full `update-job` built from the step 1 response with the same rules as step 4, using the step 7 command, after the user's confirmation naming the job.

## 9. What Happens Next

Tell the user once for the batch, with the versions filled in:

```text
What happens next:
- Nothing runs now. Each job keeps running on Glue <old> on its normal schedule.
- After 3 successful runs, the upgrade to Glue <target> waits for your approval. You'll get an email if notifications are set up; you can also check in the AWS Glue console or ask me.
- Approve within 7 days (the email shows when the 7 days started, in UTC) to upgrade. If you don't approve, or you decline, the job stays on Glue <old>; after an expiry, a new cycle starts on a later run.
- AWS Glue can roll a job back to Glue <old> and turn auto version off for it before any upgrade run: when its own eligibility check finds breaking changes, when an observation run on Glue <old> fails, or when its check after the observation runs finds blocking issues. You'll get an email if notifications are set up, and I can explain the reason from the job's evaluation summary.
```

- Review and approve with the consent workflow ([auto-version-consent.md](auto-version-consent.md)).
- To opt out, set the job back to a specific Glue version with the same full-update rules as step 4 (fresh `get-job`, full `JobUpdate`, confirmation naming the job), using the step 7 command, with its `AWS_SDK_UA_APP_ID` prefix — never a partial update.
