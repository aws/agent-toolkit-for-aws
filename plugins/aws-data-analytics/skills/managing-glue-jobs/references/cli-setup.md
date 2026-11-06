# AWS CLI for Glue Auto Version Calls

Glue auto version operations (`get-job-upgrade-analysis`, `start-job-upgrade-analysis`) and the auto version fields of `get-job` / `update-job` (`GlueVersion` = `auto`, `Job.AutoUpgradeMetadata`) are called through the AWS CLI from the shell: they need a current AWS CLI. Use the latest AWS CLI version; the checks below confirm that it includes these operations. Use the AWS CLI for `get-job-upgrade-analysis`, `start-job-upgrade-analysis`, for reading `Job.AutoUpgradeMetadata` with `get-job`, and for every `update-job`. Other AWS calls may go through the AWS MCP server's `run_script` tool when it is connected; otherwise use the AWS CLI. The auto version calls stay on the AWS CLI because the Glue auto version operations and fields need a current AWS CLI; the AWS MCP server may not support the auto version API fields until it is updated. The eligibility assessment (`generate_assessment`) goes through the `spark-upgrade` MCP server.

## Setup Check

Run before the first Phase 2 or Phase 3 call of the setup workflow, once per session:

```bash
aws glue get-job-upgrade-analysis --generate-cli-skeleton > /dev/null
```

The check reads the AWS CLI's local service model; it makes no AWS call and needs no pager or `groff`. Do not check with `help`: it fails without `groff` or `mandoc` even when the operation exists. If the command exits non-zero (for example `Invalid choice`), STOP and tell the user exactly:

> Your AWS CLI does not include the AWS Glue auto version APIs. Update the AWS CLI to the latest version and retry.

Do not continue with any Phase 2 or Phase 3 step, and do not fall back to another tool. Do not install, update, or download the AWS CLI or any other software yourself; tell the user what to update and stop.

## Consent Check

Run before discovery in the consent workflow, once per session:

```bash
aws glue start-job-upgrade-analysis --generate-cli-skeleton | grep -q '"jobName"'
```

Like the setup check, it makes no AWS call. If the command exits non-zero (the operation is missing — for example `Invalid choice` — or its input has no `jobName`), STOP and tell the user exactly:

> Your AWS CLI does not include the AWS Glue auto version APIs. Update the AWS CLI to the latest version and retry.

Do not continue, and do not fall back to another tool. Do not install, update, or download the AWS CLI or any other software yourself; tell the user what to update and stop.

## Conventions

- Pass `--region <region>` on every call; never rely on a default Region.
- Pass `--no-cli-pager` (or set `AWS_PAGER=""`) on every call so the CLI never waits on a pager.
- JSON documents: with the AWS CLI, pass them with `file://` paths, never as inline shell strings. With the AWS MCP server's `run_script` tool, which has no local file access, pass them directly in the tool call.
- Read `AutoUpgradeMetadata.Status` and analysis statuses as plain strings and compare exact values; new status values can appear.
- `aws glue get-jobs` returns `AutoUpgradeMetadata` as null; only `aws glue get-job` returns it.
- `get-job-upgrade-analysis` returns the report locations as `autoUpgradeEligibilitySummary` and `autoUpgradeEvaluationSummary` (`upgradeEligibilitySummary` and `autoVersionEvaluationSummary` in older CLI versions, which also return `resultPath`), each an `s3://` URI or an `https://` presigned link; call it only with the status read's `--query`, inside the report read command (see [consent-review.md](consent-review.md)), or with the rollback read in [enabling-jobs.md](enabling-jobs.md) step 8. The evaluation summary is read only with the Evaluation Summary Read in [consent-review.md](consent-review.md). Either field naming is fine; no CLI version check is needed for it. `start-job-upgrade-analysis` takes `--job-name`, `--analysis-id`, and `--upgrade-consent`.
