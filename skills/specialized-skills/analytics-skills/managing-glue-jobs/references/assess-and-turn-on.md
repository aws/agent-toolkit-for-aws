<!-- markdownlint-disable MD033 -->
# Assess, confirm safe to retry, and turn on

Sample prompts from the user guide:

- "Assess my Glue jobs in us-west-2 for auto upgrade. Use AWS profile my-profile."
- "Proceed with the eligible jobs, and set up auto upgrade email notifications to data-team@example.com."

## Requirements

These requirements come from the user guide. Check them again on a fresh `get-job` before any change ("Step 4: Turn on").

| Requirement | Field |
|---|---|
| Spark ETL job | `Command.Name` is `glueetl` |
| AWS Glue 2.0 or later | `GlueVersion` isn't `0.9` or `1.0` |
| Retries on | `MaxRetries` is 1 or higher |
| Job run queuing off | `JobRunQueuingEnabled` isn't `true` |
| Safe to retry | Only the user knows. Ask in step 2. |

Never change `MaxRetries` or queuing yourself. Tell the user which setting to change.

## Step 1: Assess (read-only)

1. List the jobs. The projection never selects argument values:

   ```bash
   aws glue get-jobs --region <region> --no-cli-pager \
     --query "Jobs[].{Name:Name,GlueVersion:GlueVersion,Command:Command.Name,MaxRetries:MaxRetries,Queuing:JobRunQueuingEnabled,Script:Command.ScriptLocation}"
   ```

2. Check each job against the requirements table. Skip jobs already set to `auto` or on the latest stable version.
3. For each job that meets the requirements, call `generate_assessment` on the `spark-upgrade` MCP server, one job at a time:
   - `mode`: `auto_version_eligibility_assessment`; `application_type`: `glue`
   - `application_context`: `job_arguments` (from `aws glue get-job --job-name <job> --region <region> --no-cli-pager --query "Job.DefaultArguments"`, passed straight through, never shown), `script_location`, `language` (`python` or `scala`), `source_glue_version`, `target_glue_version` (the latest stable version, 6.0 today)
   - `source_spark_version` / `target_spark_version`: 2.0 = 2.4.3, 3.0 = 3.1.1, 4.0 = 3.3.0, 5.0 = 3.5.4, 5.1 = 3.5.6, 6.0 = 4.1.1
   - All of these inputs are required; a result from a call missing any of them isn't valid.
   - A job passes only when `eligible` is `true` and the response has no `warning` or `note`. Otherwise keep the `breaking_changes[].detail` text for "details".
4. If the server isn't connected, mark the jobs "not analyzed". AWS Glue still runs its own compatibility check after auto upgrade is on. Never judge a script yourself. To connect the server, give the user this MCP configuration and ask them to restart the session:

   ```json
   {"mcpServers": {"spark-upgrade": {"command": "uvx", "args": ["mcp-proxy-for-aws@latest",
     "https://sagemaker-unified-studio-mcp.<region>.api.aws/spark-upgrade/mcp",
     "--service", "sagemaker-unified-studio-mcp", "--region", "<region>", "--read-timeout", "180"]}}}
   ```

## Step 2: Safe to retry (stop)

Reply with this shape, and wait:

```text
AWS Glue can auto upgrade 3 of your 11 jobs.

The following jobs meet the requirements and pass the compatibility check.

| Job              | Current version | Target version      |
|------------------|-----------------|---------------------|
| etl-orders-daily | 4.0             | 6.0 (latest stable) |
| etl-customers    | 4.0             | 6.0 (latest stable) |
| etl-events       | 4.0             | 6.0 (latest stable) |

The following jobs aren't ready for auto upgrade.

| Reason                                | Jobs |
|---------------------------------------|------|
| Require code or configuration changes | 5    |
| Couldn't be analyzed                  | 2    |
| Not Spark ETL (`glueetl`) jobs        | 1    |

Before you turn on auto upgrade, confirm that each job is safe to retry. If an upgraded run fails, AWS Glue retries the run on the previous version, and the retried run writes to the same targets again.

AWS Glue can email you when an upgrade needs approval, expires, fails, finishes, or stops. The emails include job names, AWS Glue versions, and failure reasons.

To turn on auto upgrade for these jobs, enter `proceed`. To also get emails, enter `proceed, email <address>`. To skip a job, add `skip <job>`.
```

Leave out a table that has no rows. On "details", show one row per job with the reason.

## Step 4: Turn on

"Proceed" confirms the jobs in the Step 2 table of jobs that pass the compatibility check, minus skipped jobs, as safe to retry. `update-job` replaces the whole job definition, so a partial update resets every member that it leaves out. For each job, one at a time:

1. Read a fresh copy of the job:

   ```bash
   aws glue get-job --region <region> --no-cli-pager --job-name <job> --query "Job"
   ```

2. Check the requirements table again. If one fails, don't change the job, and tell the user which setting to change.
3. Build the `JobUpdate` from that response. Copy each of these members when present, unchanged: `JobMode`, `JobRunQueuingEnabled`, `Description`, `LogUri`, `Role`, `ExecutionProperty`, `Command`, `DefaultArguments`, `NonOverridableArguments`, `Connections`, `MaxRetries`, `Timeout`, `MaxCapacity`, `WorkerType`, `NumberOfWorkers`, `SecurityConfiguration`, `NotificationProperty`, `CodeGenConfigurationNodes`, `ExecutionClass`, `SourceControlDetails`, `MaintenanceWindow`. Set `GlueVersion` to `auto`. Only two omissions are allowed, because `UpdateJob` rejects them: `AllocatedCapacity` always, and `MaxCapacity` when `WorkerType` is set.
4. If the job has `ProfileName` or `SourceControlDetails`, stop and tell the user: `update-job` can't keep `ProfileName`, and `get-job` doesn't return the source control token. Continue only after the user confirms that job by name.
5. Update the job. The payload holds argument values, so it goes into a temporary file that the same command deletes:

   ```bash
   (D=$(mktemp -d); trap 'rm -rf "$D"' EXIT; umask 077; cat > "$D/u.json" <<'JSON'
   <full JobUpdate JSON>
   JSON
   AWS_SDK_UA_APP_ID=managing-glue-jobs-skill aws glue update-job --region <region> --no-cli-pager --job-name <job> --job-update file://"$D/u.json")
   ```

6. Read the job back:

   ```bash
   aws glue get-job --region <region> --no-cli-pager --job-name <job> --query "Job.{GlueVersion: GlueVersion, MaxRetries: MaxRetries, Role: Role, Command: Command}"
   ```

   `GlueVersion` must be `auto`, and `MaxRetries`, `Role` and `Command` must match what you sent. If not, stop and show the difference. An `InvalidInputException` names the problem: show it. An error that says the account doesn't support auto upgrade stops the batch.

If the user entered `proceed, email <address>`, set up the emails first ([notifications.md](notifications.md), "Set up"), then turn on the jobs. If the email setup fails, still turn on the jobs. A conflict is the exception: it stops the setup and the turn-on. Then reply once:

```text
Auto upgrade is now on for 2 jobs. The jobs stay on AWS Glue 4.0 until you approve an upgrade.

| Job           | GlueVersion | Runs on |
|---------------|-------------|---------|
| etl-customers | `auto`      | 4.0     |
| etl-events    | `auto`      | 4.0     |

**What happens next**
1. You keep running the jobs as usual.
2. AWS Glue analyzes each job and doesn't change the job.
3. If a job needs no changes, AWS Glue emails you and requests your approval. You have 7 days to approve or decline.

If a job needs changes, AWS Glue doesn't upgrade the job. The auto upgrade evaluation summary lists the changes.

**Email notifications**
AWS Glue now emails <address> about auto upgrades in <region>. To start receiving email, open the email titled "AWS Notification - Subscription Confirmation" and choose **Confirm subscription**.

If you miss an email, enter `Which of my Glue jobs in <region> are waiting for upgrade approval?`
```

If the email setup failed, replace the **Email notifications** part with: "The email setup didn't finish: <step> failed with <error>. It created <the resources created in this run, or nothing>. To retry the email setup, enter `proceed, email <address>`." On that retry, run only the email setup: the jobs are already on `auto`, so Step 4 skips them.

If the user entered only `proceed`, leave out the **Email notifications** part and the last line. Replace step 3 with "If a job needs no changes, AWS Glue requests your approval. You have 7 days to approve or decline." End with "To check for approval requests later, enter `Which of my Glue jobs in <region> are waiting for upgrade approval?`"

## New job with auto upgrade

After the user confirms that the job is safe to retry, show this command and run it on "yes":

```bash
AWS_SDK_UA_APP_ID=managing-glue-jobs-skill aws glue create-job --region <region> --no-cli-pager \
  --name <job> --role <role ARN> \
  --command '{"Name": "glueetl", "ScriptLocation": "<s3 script>"}' \
  --glue-version auto --max-retries 1
```

Reply: "AWS Glue created <job> with auto upgrade turned on. New jobs don't require approval. Job runs use the latest stable version from the first run."

## Turn off auto upgrade

After the user names the job and the version, use steps 1, 3, 4, 5, and 6 of "Step 4: Turn on", with `GlueVersion` set to that version, such as `4.0`, instead of `auto`. Skip step 2: the requirements apply only to turning auto upgrade on. In step 6, check that `GlueVersion` is that version. Any evaluation in progress stops.

Reply: "Auto upgrade is off for <job>. Subsequent job runs use AWS Glue <version>."
