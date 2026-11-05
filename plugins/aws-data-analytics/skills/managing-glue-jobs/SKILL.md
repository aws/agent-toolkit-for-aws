---
name: managing-glue-jobs
description: "Manages AWS Glue auto version (GlueVersion = \"auto\") for existing Spark ETL jobs. Setup: assesses each job's auto version eligibility and reports eligible jobs, blocking reasons and effort; enables auto version for the eligible jobs the user confirms; sets up encrypted email notifications. Consent: finds jobs whose upgrade waits for consent, presents the upgrade eligibility report, a risk summary and the risks, and records APPROVE or DECLINE for a job only after the user names that job and decision in a later message. Also applies when a user asks to auto-approve, batch-approve, batch-decline or schedule decisions on pending upgrades: only per-job decisions are recorded. Triggers on: assess glue jobs for auto version, enable glue auto version, glue auto version emails, consent required email, approve or decline a glue upgrade, which glue jobs are waiting for upgrade consent. Not for creating jobs, troubleshooting job runs, CloudWatch alarms or other Glue job management."
metadata:
  version: "1"
  service: [glue]
  task: [assess, audit, plan, configure, review, approve]
  persona: [developer, data-engineer, platform-engineer]
  workload: [data-analytics]
---

# Managing AWS Glue Jobs: Auto Version

Covers AWS Glue auto version (GlueVersion = "auto") for existing Spark ETL jobs. Two workflows, each in its own file: **setup** (assess eligibility, enable auto version, email notifications) and **consent** (review upgrades waiting for consent, then approve or decline one job at a time).

**IMPORTANT**: When this skill is loaded, you MUST read the matching workflow file before responding, even when the answer seems clear from this file. The guardrails below are not sufficient to answer: the steps, facts and explanations each answer needs are only in the workflow files.

## Routing

You MUST read the files listed for the intent before acting or answering, and follow them as the primary source of truth:

| User intent | Read |
|---|---|
| Assess jobs for auto version, why a job is not eligible | [auto-version-setup.md](references/auto-version-setup.md) |
| Enable or turn on auto version, set GlueVersion to auto, "proceed" after the eligible table, a request that names jobs to enable | [auto-version-setup.md](references/auto-version-setup.md) and [enabling-jobs.md](references/enabling-jobs.md) |
| Auto version email notifications, what the notification emails say | [auto-version-setup.md](references/auto-version-setup.md) and [notifications.md](references/notifications.md) |
| Consent required email, pending or waiting upgrade, which jobs wait for consent, review the upgrade eligibility report, approve, decline, auto-approve or schedule approvals, what happens after approving | [auto-version-consent.md](references/auto-version-consent.md) and [consent-review.md](references/consent-review.md); for what the consent required email says, also [notifications.md](references/notifications.md) |

- A request that mixes both (for example "enable etl-a and approve its upgrade"): do not do both. Run only the first workflow up to its first confirmation point, then stop, explain that the other part is a separate step, and ask before starting it. Enabling auto version never creates an upgrade that can be approved in the same conversation: consent is requested only after the job's observation runs.
- If the intent is unclear, or the skill is invoked without a request, show this menu before calling AWS and ask which one the user wants, and for the AWS account and Region:
  1. **Set up auto version:** a read-only assessment of which jobs are eligible (and why the others aren't); then auto version is turned on only for the eligible jobs you confirm; optionally, encrypted email notifications.
  2. **Consent for upgrading the eligible jobs:** review upgrades waiting for your consent (report, recommendation, risks); you approve or decline each job yourself, one at a time.
- Out of scope (creating jobs, troubleshooting job runs, editing scripts or schedules, CloudWatch alarms): say no bundled workflow covers it.

## Where this skill's files live

- **Loaded through the AWS MCP server's `aws___retrieve_skill` tool:** the files are not on disk. Fetch each reference with `aws___retrieve_skill` and the `file` parameter (for example `file="references/auto-version-setup.md"`).
- **Installed locally:** read the files from this skill's directory with relative paths.

User data (payloads, downloaded reports) is never read or written through `aws___retrieve_skill`.

## Guardrails (not a substitute for the workflow)

These hold at all times, including before the workflow file is read. They are guardrails only: you MUST still read the matching workflow file before answering.

- You MUST get a confirmation before any change. To enable auto version: "proceed" (or "enable these") after the eligible table covers exactly the jobs listed in that table in this conversation, and nothing else; a request that names jobs and asks to enable them ("enable etl-a", "enable etl-a if it is eligible") covers only those named jobs that are in the eligible table from the scan in the same turn: show the table first, refuse a named job that is not in it; a listed job with an enable preview flag (ProfileName would be lost, SourceControlDetails round trip unverified) needs its own reply naming the job; any other request to enable jobs that were not in a table you showed ("enable all", "all eligible", even with "I approve") is not a confirmation: run the scan first and show the table. For a job enabled without the eligibility assessment, the confirmation must name the job and state that it is idempotent (safe to re-run against its real sources and sinks); a statement covering several jobs does not count. Consent decisions need a reply that names the job: "approve etl-a", "decline etl-a". The full rule is in [enabling-jobs.md](references/enabling-jobs.md) §6.
- You MUST record `--upgrade-consent APPROVE` or `--upgrade-consent DECLINE` only after the review reply for that job (blocking check, recommendation, report location and consent risks) was presented, in a later user message than the review request that names the job and the decision, after a fresh status check. You MUST NOT approve or decline on a conditional or advance instruction.
- You MUST NOT call `stop-job-upgrade-analysis`, or batch, schedule, script or automate approvals or declines. An approval lets up to 3 production runs execute on the new Glue version against real sinks, and the data they write is not rolled back.
- You MUST give the recommendation line exactly as written in [consent-review.md](references/consent-review.md) (placeholders filled in) and nothing after it: no sentence about what it is based on, whether it is a guarantee or whether it is a decision. You MUST NOT call an upgrade safe or guaranteed. Agreement with the recommendation is not an approval or a decline: only the user's named reply counts.
- You MUST read upgrade analyses only with the status read (`get-job-upgrade-analysis` with its fixed `--query`) and the report read and evaluation summary read commands in [consent-review.md](references/consent-review.md), or the rollback read in [enabling-jobs.md](references/enabling-jobs.md) step 8. A report link can be a presigned URL, which is a credential: never select, show or store it.
- You MUST NOT create or modify IAM roles or policies.
- You MUST NOT install, update or download the AWS CLI or any other software; tell the user what to update and stop. The only exception is aws-encryption-sdk-cli==4.3.0, in a temporary Python environment deleted in the same command, after the user's explicit yes, to decrypt a report encrypted with the job's KMS key ([consent-review.md](references/consent-review.md), Report Retrieval, step 5).
- Auto version calls (`get-job` when reading `AutoUpgradeMetadata`, every `update-job`, `get-job-upgrade-analysis`, `start-job-upgrade-analysis`) go through the AWS CLI (latest version): the Glue auto version operations and fields need a current AWS CLI; the AWS MCP server may not support the auto version API fields until it is updated. Other AWS calls may go through the AWS MCP server's `run_script` tool when it is connected; otherwise use the AWS CLI. See [cli-setup.md](references/cli-setup.md). The eligibility assessment (`generate_assessment`) uses the `spark-upgrade` MCP server when it is connected. It has no AWS API or CLI equivalent; without it, follow the no-server path in [auto-version-setup.md](references/auto-version-setup.md) Phase 0.

## Prerequisites

- AWS credentials for the account and Region in scope; read-only credentials for assessment and review.
- AWS CLI, latest version, with the Glue auto version operations ([cli-setup.md](references/cli-setup.md)).
- Setup assessments (optional): the `spark-upgrade` MCP server ([mcp-configuration.md](references/mcp-configuration.md)). Without it, jobs can still be enabled one at a time ([auto-version-setup.md](references/auto-version-setup.md) Phase 0).

## References

| File | Used by | Contents |
|---|---|---|
| [auto-version-setup.md](references/auto-version-setup.md) | setup | Phases 0-3: assess, enable, notify |
| [auto-version-consent.md](references/auto-version-consent.md) | consent | Phases 0-3: find, review, approve or decline |
| [enabling-jobs.md](references/enabling-jobs.md) | setup | Refusal gate, full JobUpdate merge, verification, what happens next |
| [notifications.md](references/notifications.md) | setup | Event patterns, email templates, KMS key and topic policy |
| [report-format.md](references/report-format.md) | setup | Verdicts and the aggregated report |
| [mcp-configuration.md](references/mcp-configuration.md) | setup | Spark Upgrade MCP server setup |
| [consent-review.md](references/consent-review.md) | consent | Discovery, review reply, condensed and full risk text, decision rule |
| [cli-setup.md](references/cli-setup.md) | both | CLI preflight (setup check, consent check) and conventions |
| [error-handling.md](references/error-handling.md) | setup | Failures and resolutions |

## Troubleshooting

| Symptom | See |
|---|---|
| `generate_assessment` missing, MCP server fails to load, assessment timeout | [mcp-configuration.md](references/mcp-configuration.md), [error-handling.md](references/error-handling.md), or continue without the assessment ([auto-version-setup.md](references/auto-version-setup.md) Phase 0, option 2) |
| `Invalid choice` from an auto version CLI command | [cli-setup.md](references/cli-setup.md) |
| `update-job` errors, account not supported for auto version | [enabling-jobs.md](references/enabling-jobs.md), [error-handling.md](references/error-handling.md) |
| `update-job` `InvalidInputException` | [error-handling.md](references/error-handling.md) |
| Job back on its old version, `UPGRADE_FAILED` | [enabling-jobs.md](references/enabling-jobs.md) step 8; [consent-review.md](references/consent-review.md) (Evaluation Summary Read, Failure Explanation) |
| Notification emails missing or raw JSON | [notifications.md](references/notifications.md) |
| Report missing, decision state errors, status unchanged after a decision | [auto-version-consent.md](references/auto-version-consent.md) |
