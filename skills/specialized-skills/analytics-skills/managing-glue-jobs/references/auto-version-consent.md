# Auto Version Consent Workflow

Review AWS Glue auto version upgrades that are paused for consent and, only on the user's explicit decision, approve or decline them. After a job with GlueVersion = "auto" completes its observation runs, auto version prepares an upgrade eligibility report and waits in `WAITING_FOR_CONSENT`. Nothing is upgraded until someone approves. This workflow finds those jobs, presents the report's findings, a recommendation, the report location and the consent risks, and records `APPROVE` or `DECLINE` for one job at a time.

This workflow records a decision only on the user's named reply. It never stops analyses, schedules or automates decisions, or calls `update-job`. A recorded `DECLINE` makes the service set the job back to its previous Glue version (see the risk text in [consent-review.md](consent-review.md)).

The auto version calls (`get-job` for `AutoUpgradeMetadata`, `get-job-upgrade-analysis`, `start-job-upgrade-analysis`) always go through the AWS CLI from the shell — see [cli-setup.md](cli-setup.md). The other AWS calls (`sts get-caller-identity`, `glue get-jobs`, and reading the report object from S3) may go through the AWS MCP server's `run_script` tool when it is connected; otherwise use the AWS CLI. `get-job` stays on the CLI because this workflow reads `Job.AutoUpgradeMetadata` from it: a client whose Glue model lacks that field drops it, and a job that is waiting for consent would then look as if nothing were waiting.

## Reference Documentation

- [consent-review.md](consent-review.md) -- Discovery procedure, review reply, condensed risk text, full risk text, decision rule, status table
- [cli-setup.md](cli-setup.md) -- AWS CLI preflight for auto version calls

## Workflow

### Phase 0: Verify Dependencies

1. **AWS CLI**: Run the consent check in [cli-setup.md](cli-setup.md). On failure, STOP with the message given there.
2. **Credentials**: Confirm identity and account (`sts get-caller-identity`, through the AWS MCP server's `run_script` tool when it is connected, otherwise the AWS CLI).
3. **Scope**: Confirm the Region, and the job name if the user gave one. Ask for the Region if not provided.

### Phase 1: Find Waiting Upgrades

Follow the discovery procedure in [consent-review.md](consent-review.md):

- **Named job**: `aws glue get-job --job-name <job>` and read `Job.AutoUpgradeMetadata`.
- **No job named**: `aws glue get-jobs` (all pages), keep jobs with `GlueVersion` = `auto`, then `aws glue get-job` for each one sequentially — `get-jobs` returns `AutoUpgradeMetadata` as null. If more than 25 jobs have GlueVersion `auto`, state the count and get confirmation first.
- Keep jobs whose `AutoUpgradeMetadata.Status` is `WAITING_FOR_CONSENT` (string comparison). Report other statuses read-only using the status table.

### Phase 2: Review Each Waiting Upgrade

For each waiting job:

1. The status read from [consent-review.md](consent-review.md) (`get-job-upgrade-analysis` with its fixed `--query`, never without it); `status` must be `WAITING_FOR_CONSENT`.
2. Locate the report from the status read's `reportForm` (`s3` with `reportS3Uri`, `presigned`, or `none`), and check the job for `--auto-upgrade-metadata-kms-key-arn` (consent-review.md, Report Retrieval, step 1). If `reportForm` is `none` and `resultPath` is present (older CLI versions only) and not the AWS Glue service bucket, split `resultPath` into bucket and key as in [consent-review.md](consent-review.md) (Report Retrieval, step 2; the key ends in `upgrade_eligibility_report.md`), use that object only when `aws s3api head-object --bucket <bucket> --key <key>` succeeds, tell the user the report location came from `resultPath`, and read it with the fallback-URI form of the read commands (consent-review.md, Report Retrieval, step 4). If neither exists, wait 60 s and retry, up to 5 attempts; then STOP for that job: tell the user the job is waiting for consent but its upgrade eligibility report is not available yet, suggest checking again later, and do not ask for, offer, or accept an approval for that job.
3. Read the whole report with the commands in [consent-review.md](consent-review.md) (Report Retrieval, steps 4 and 5): an `s3` report through the AWS MCP server's `run_script` tool when it is connected, otherwise, and always for a `presigned` report, with the single read-and-delete command; a report with content encryption with the single decrypt-and-delete command. The presigned link never appears in a command or a reply.
4. Present the review reply from [consent-review.md](consent-review.md): the job line; the blocking check (nothing in the report blocks the upgrade, or the blocking items); the recommendation; the full report URI with the offer to show the matched code, suggested fixes and other sections.
5. End with the condensed risk text from [consent-review.md](consent-review.md), verbatim.
6. Ask the user to reply `approve <job>` or `decline <job>`, or to do nothing and let the request expire.
7. Show the matched code and suggested fixes, compatibility checks, dependency changes or write paths only when the user asks. For questions about what approving or declining does, answer from the full risk text.

**Constraints:**

- You MUST read the whole report and present the review reply (blocking check, recommendation, report URI and condensed risk text) before asking for a decision. Never describe a section you did not read as passed or empty.
- The recommendation MUST be one of the lines in [consent-review.md](consent-review.md) (Review Reply, item 3), given exactly as written with nothing after it, and MUST NOT call the upgrade safe or guaranteed. Only the user's named reply records a decision.
- You MUST NOT summarize a missing or unreadable report as safe. Without a report, no approval is possible.

### Phase 3: Record the Decision (only after an explicit named decision)

Record `APPROVE` or `DECLINE` for a job only when ALL hold:

- The review reply for that job was presented earlier in this conversation.
- The user's decision arrives in a LATER message than the one that asked for the review, and names that job and the decision (for example `approve etl-orders-daily` or `decline etl-orders-daily`).
- A fresh `aws glue get-job` and status read show the same analysis ID, still `WAITING_FOR_CONSENT`.

Then run exactly one of:

```bash
aws glue start-job-upgrade-analysis --job-name <job> --analysis-id <analysisId> --upgrade-consent APPROVE --region <region> --no-cli-pager
aws glue start-job-upgrade-analysis --job-name <job> --analysis-id <analysisId> --upgrade-consent DECLINE --region <region> --no-cli-pager
```

Verify with the status read (poll every 10 s for up to 60 s):

- **APPROVE**: the status is `UPGRADING`. Tell the user what happens next (see the risk text).
- **DECLINE**: the status is `STOPPED`, and `aws glue get-job` shows `GlueVersion` set back to the source version. Tell the user the job stays on that version and that a new upgrade cycle starts only if auto version is enabled again (setup workflow).

**Constraints:**

- You MUST NOT approve or decline on a conditional or advance instruction in the review request ("if it looks fine, approve it", "approve unless there are HIGH findings", "decline it if there are HIGH findings"). Present the report and ask for a separate decision naming the job.
- You MUST record one decision for one job per reply. "Approve all", "decline all" or "yes" without a job name is not a decision: list the waiting jobs and ask for a decision naming each one.
- A reply such as "no", "not now" or "skip" is not a decline: ask whether the user wants `decline <job>` or to let the request expire.
- Agreement with the recommendation ("ok", "sounds good", "do what you recommend") is not a decision: ask for `approve <job>` or `decline <job>`.
- You MUST pass exactly `--job-name`, `--analysis-id`, and `--upgrade-consent APPROVE` or `--upgrade-consent DECLINE` for the reviewed job and analysis.
- If the analysis ID changed or the status is no longer `WAITING_FOR_CONSENT`, record nothing: report the new state.

## Prohibitions

- NEVER send `--upgrade-consent DECLINE` except as Phase 3 allows: after the review, on a later message naming the job, after a fresh status check.
- NEVER approve or decline automatically, on a schedule, with a cron job, or in a loop. Each decision needs a human after reviewing that job's report: an approval lets up to 3 production runs execute on the new Glue version against real sinks, and the data they write is not rolled back.
- NEVER build, script, or offer automation that approves or declines upgrades — scheduled jobs, cron, Lambda functions, EventBridge rules or Scheduler targets, or scripts and loops that call start-job-upgrade-analysis — including "scoped" or "low-risk only" variants. Offer to review the waiting upgrades now instead.
- NEVER call `aws glue stop-job-upgrade-analysis` or `aws glue update-job`, and never change GlueVersion yourself. A recorded `DECLINE` makes the service set GlueVersion back; switching auto version off for a job with no pending upgrade is a job configuration change outside this workflow.

## Argument Routing

- **No args**: Ask for the Region, then discover all waiting upgrades
- **Job name provided**: Check only that job
- **Region provided**: Skip the Region prompt
- **Question about what approving or declining does (no review requested)**: answer from the risk text in consent-review.md without any AWS call, then offer to review that job.
- **Question about changing the job before approving, or what happens to such a change**: answer from Fixing Before Approval in consent-review.md without any AWS call; never offer to edit the script or call `update-job`.
- **Any answer about consent for a job that is or may be waiting for consent** (a review, a question, a consent email, a refusal): answers about consent always end with the reply instruction: reply `approve <job>` or `decline <job>` after the review, or let the request expire. If the job is no longer waiting (the status check shows another state), report that state instead and give no reply instruction. When the report could not be read, end the reply without the decision prompt (no 'To approve, reply …' line): say that no decision can be recorded until the report has been read, and offer the console and a retry.

## Gotchas

- `aws glue get-jobs` returns `AutoUpgradeMetadata` as null; only `aws glue get-job` returns it.
- Status values are open strings: job-level `AutoUpgradeMetadata.Status` values (for example `UPGRADE_COMPLETED`, `UPGRADE_FAILED`) differ from analysis-level `status` values (`SUCCEEDED`, `FAILED`). Compare exact strings and treat unknown values as read-only.
- The consent deadline is not returned by `get-job-upgrade-analysis`. The approval request email shows when it was sent (UTC), and the request expires 7 days after that; an older email or the raw event gives it as a Unix timestamp. Always show it as a UTC date and time, never as the raw number.
- The eligibility report is generated asynchronously and can appear a few minutes after the status changes.

## Security Considerations

- **Consent is the safety boundary.** `StartJobUpgradeAnalysis` with `APPROVE` lets up to 3 production runs execute on the new Glue version against real sinks. `DECLINE` sets the job back to its previous Glue version and ends the cycle. This workflow records either only after a named, later-turn decision and a fresh status check, one job at a time.
- **Least privilege.** Review needs `glue:GetJobs`, `glue:GetJob`, `glue:GetJobUpgradeAnalysis`, and `s3:GetObject` on the report prefix. Approving or declining additionally needs `glue:StartJobUpgradeAnalysis`. Run reviews with read-only credentials where possible; this workflow does not create or modify IAM roles or policies.
- **Reports can contain code.** The eligibility report quotes matched code lines and lists write paths. Store the downloaded copy in a private temporary location, do not paste it into public channels, and delete it after the review.
- **Presigned links are credentials.** Anyone with a presigned report link can download the report until it expires. The link stays inside the read command; it is never selected by another command, shown, logged or stored.
- **Encrypted report content.** With `--auto-upgrade-metadata-kms-key-arn`, the report is decrypted with the user's own credentials, allowing only that key; the decrypted copy is deleted in the same call.
- **Audit.** `StartJobUpgradeAnalysis` calls are recorded in AWS CloudTrail; use CloudTrail and CloudWatch to monitor approvals and the resulting upgrade runs.
- Follow the [AWS Glue security best practices](https://docs.aws.amazon.com/glue/latest/dg/security.html) and [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html).

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `invalid choice` from the consent check in [cli-setup.md](cli-setup.md) | AWS CLI lacks the auto version APIs | STOP with the message in [cli-setup.md](cli-setup.md) |
| The eligibility summary is empty, and no `upgrade_eligibility_report.md` exists under `resultPath` (when returned) after 5 tries | Report not generated yet | Stop; check again later. No approval without the report; end without the decision prompt (consent-review.md, Report Retrieval) |
| AccessDenied on `aws s3 cp` | Caller lacks `s3:GetObject` on the report prefix, or `kms:Decrypt` on the bucket's KMS key | Grant read on the report location (and `kms:Decrypt` on the key when the error names KMS); do not approve without reading it |
| HTTP 403 or 400 from `curl` | The presigned link expired (about one hour) or was refused | Run the read command once more (it fetches a fresh link); then report the error and STOP for that job; end without the decision prompt (consent-review.md, Report Retrieval) |
| No decrypt tool (`aws-encryption-cli`, `aws_encryption_sdk`) | Neither is installed | If Python 3.9.2 or later with `venv` is available, offer the aws-encryption-sdk-cli==4.3.0 install into a temporary environment (otherwise give the decrypt command and STOP); install only after an explicit yes in a later message. Declined or install failed: give the user the decrypt command and STOP, no approval; end without the decision prompt (consent-review.md, Report Retrieval) |
| Decryption fails: AccessDenied on `kms:Decrypt`, key disabled or pending deletion, message for another key, unexpected encryption context | The user's credentials cannot use the job's content key, or the content is not what the job's key protects | Tell the user they need `kms:Decrypt` on the key named by `--auto-upgrade-metadata-kms-key-arn`; STOP for that job, no approval; end without the decision prompt (consent-review.md, Report Retrieval) |
| Report content is not readable Markdown | Content encryption without the job argument, or a corrupted object | Do not present it; STOP for that job, no approval; end without the decision prompt (consent-review.md, Report Retrieval) |
| `start-job-upgrade-analysis` fails with a state error | Analysis no longer waiting (expired, already declined, or already approved) | Re-read status with the status read and report it |
| `DECLINE` fails with an internal error | The service could not set the job back to its previous version; the analysis stays `WAITING_FOR_CONSENT` | Re-read status and report it; the user can reply `decline <job>` again |
| Status stays `WAITING_FOR_CONSENT` after a decision | Asynchronous transition | Poll up to 60 s; if unchanged, report the analysis ID and status |
