# Error Handling for Glue Auto Version Setup

## MCP Server Connection Issues

| Error | Cause | Fix |
|-------|-------|-----|
| MCP server failed to load | Configuration or credentials issue | Verify JSON syntax, check AWS credentials |
| `generate_assessment` missing from tool list | Stale session or wrong server endpoint | Restart the chat session; verify the `spark-upgrade` endpoint URL and region |
| `spark-upgrade` server not configured | No entry in the MCP configuration | Offer the two options in [auto-version-setup.md](auto-version-setup.md) Phase 0: add the server and restart (option 1), or continue without the assessment (option 2) |
| Slow tool loading | First-time server initialization | Tools may take a few seconds on first launch; restart chat if tools don't appear |
| Connection refused / timeout | MCP proxy not running or misconfigured | Verify `mcp-proxy-for-aws` is installed: `uvx mcp-proxy-for-aws@latest --help` |
| Authentication failure | IAM role lacks permissions | Verify the caller's permissions for the SageMaker Unified Studio MCP service |
| Read timeout during assessment | Large job script exceeds configured timeout | Increase `--read-timeout` in MCP config (default 180s) |

## Assessment Invocation Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Throttling error | Service limit reached | Keep calls sequential; wait a few seconds and retry the failed job once |
| AccessDeniedException on get-jobs, list-jobs, batch-get-jobs or get-job | Missing glue:GetJobs, glue:BatchGetJobs (name list or tag scope), glue:ListJobs (tag scope) or glue:GetJob | Add the Glue read permissions to the caller |
| AccessDeniedException on script read | Missing S3 read on the script location | Grant `s3:GetObject` on the job's script path; do not mark the job ineligible for a permission gap |
| InvalidInputException | Incorrect tool parameters | Check the error message; verify script location and version values from `get-job` |
| ResourceNotFoundException | Job deleted between list and assess | Record as ASSESSMENT_ERROR with the message; continue the batch |
| Internal service error | Temporary service overload | Retry once after a few seconds |

## Enable (Phase 2) Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `invalid choice` from the setup check in [cli-setup.md](cli-setup.md) | The installed AWS CLI version lacks the auto version APIs | STOP with the message in [cli-setup.md](cli-setup.md); do not use another tool |
| `update-job` `InvalidInputException`: `GlueVersion "auto" is not supported for account <id>` | Account not enabled for auto version | Stop the whole batch; report that no job was changed after this point |
| `update-job` `InvalidInputException`: `Command should not be null when using GlueVersion "auto".` | The payload lost `Command` | Rebuild the payload per [enabling-jobs.md](enabling-jobs.md) step 4 |
| `update-job` `InvalidInputException`: `GlueVersion "auto" is only supported for Glue ETL jobs.` | The job is not `glueetl` | Refuse the job |
| `update-job` `InvalidInputException`: `MaxRetries must be >= 1 when GlueVersion is "auto".` | `MaxRetries` < 1 or omitted | Refuse the job; do not change `MaxRetries` |
| `update-job` `InvalidInputException`: `Maximum retries was set to N, must be set to 0 with job run queuing enabled` | Job run queuing is on, which is incompatible with auto version (auto needs `MaxRetries` >= 1) | Refuse the job; do not change queuing or `MaxRetries` |
| `update-job`: `MaxCapacity` and `WorkerType` both set | Payload kept `MaxCapacity` | Rebuild the payload per [enabling-jobs.md](enabling-jobs.md) step 4 |
| AccessDeniedException on `update-job` / `iam:PassRole` | Caller lacks `glue:UpdateJob` or `iam:PassRole` on the job's role | Show the error verbatim; the user grants the permission — this workflow does not edit IAM |
| `AutoUpgradeMetadata` missing after 60 s | Enrollment is asynchronous or the account is at its concurrent-analysis limit | Report the job as enabled with enrollment pending; check again later with `get-job` |
| Job rolled back after enable (`UPGRADE_FAILED`, previous `GlueVersion`) | Glue's pre-upgrade eligibility check (the same check the assessment runs) rejected the job or could not complete it | Report per [enabling-jobs.md](enabling-jobs.md) step 8; do not retry or re-enable |
| Post-update difference in a sent member | Service changed or rejected a member | Stop the batch, show the difference, offer to set the changed members back with a confirmed full update-job built from the step 1 get-job response |

## Notification (Phase 3) Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `create-topic`: already exists with different attributes | Existing topic has another KMS key or attributes | Report and ask the user; never change encryption silently |
| Emails never arrive | Subscription unconfirmed, KMS key policy lacks `events.amazonaws.com`, or topic policy missing the rule ARN | Check `list-subscriptions-by-topic`, the key policy, and the `AllowGlueAutoVersionEventBridge` statement |

## Batch-Level Rules

- One job's failure never aborts the batch — record ASSESSMENT_ERROR (Phase 1) or the `update-job` error (Phase 2) and continue; the only exception is the account-not-supported error in Phase 2
- At most one retry per failed job, after a short backoff
- Always include failed jobs in the final report with their error messages — silent drops make the counts lie
