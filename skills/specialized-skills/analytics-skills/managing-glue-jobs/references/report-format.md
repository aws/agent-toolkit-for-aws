# Eligibility Report Format

The scan result is an eligible-only table, a counts line for every other job, and the offers. Per-job reasons are shown only when the user asks for "details".

## Response Fields

`generate_assessment` in `auto_version_eligibility_assessment` mode, called without `output_path`, returns:

```json
{
  "assessment_id": "as-...",
  "status": "SUCCEEDED",
  "eligible": false,
  "breaking_changes": [ { "type": "<rule type>", "severity": "BLOCK", "detail": "Spark 4.0 dropped codec name lz4raw; setting it fails. Replacement: lz4_raw" } ],
  "total_findings": 1,
  "advisories": [ { "type": "...", "detail": "..." } ],
  "categories_checked": [
    { "category": "spark_config_values", "status": "flagged", "finding_count": 1, "finding_types": ["<rule type>"] },
    { "category": "job_arguments", "status": "clear", "finding_count": 0, "finding_types": [] },
    { "category": "removed_or_incompatible_dependencies", "status": "advisory", "finding_count": 1, "finding_types": ["..."] }
  ],
  "report_location": null,
  "warning": "<present only when the script could not be fetched>",
  "note": "<present only when a check errored and failed open>"
}
```

- A **breaking change** is a BLOCK finding: a Spark config key or value removed or renamed in the target version, a Python module removed or incompatible in the target runtime, or an `--extra-jars` artifact incompatible with the target Glue version. `eligible` is `false` if and only if `breaking_changes` is non-empty; `total_findings` equals its length.
- `advisories` are informational (non-blocking) findings. List them only under `details`; they never change the placement.
- `warning` means the script and build files were not fetched and only `job_arguments` were checked, so `eligible: true` is unverified. `note` means a check errored and failed open.
- The blocking reason is the `detail` string of each `breaking_changes` entry, verbatim.
- The full `spark_upgrade_assessment` mode returns confidence-bucketed counts (`detected_issues.high/medium/total`, `dependency_upgrade_suggestions`); those are not breaking-change verdicts and this skill does not use that mode.

## Placement Mapping

| Condition (per job) | Placement | Classification used in `details` |
|---|---|---|
| `eligible: true`, no `note`, no `warning`, `categories_checked` non-empty, no `flagged` category | eligible table (input stated once on the line under the heading) | ELIGIBLE |
| `eligible: true`, `warning` present, no `note` | not in the table; counted as "could not be fully assessed (only job args checked)" | NEEDS_REVIEW |
| `eligible: true` with a `flagged` category (defensive; should not occur) | not in the table; counted as "could not be fully assessed" | NEEDS_REVIEW |
| `eligible: true` with `note` (failed open), or `categories_checked` empty | not in the table; counted as "could not be assessed" | NEEDS_REVIEW |
| `eligible: false` | not in the table; counted as "need code or config changes" | NEEDS_CODE_CHANGES |
| Tool error after one retry | not in the table; counted as "could not be assessed" | ASSESSMENT_ERROR |
| `MaxRetries` missing or < 1, or run queuing enabled (structural, not assessed) | not in the table; counted as "need code or config changes" | NEEDS_CONFIG_CHANGES |
| Not `glueetl` (streaming, Python shell, Ray) | not in the table; counted as "skipped" | OUT_OF_SCOPE |
| Already on the target version (Glue 6.0) | not in the table; counted as "skipped" | ALREADY_CURRENT |
| Already `GlueVersion = "auto"` | not in the table; counted as "skipped" | ALREADY_AUTO |
| No-server path (no assessment; structural checks passed) | no table: the no-server list in [auto-version-setup.md](auto-version-setup.md) Phase 0, option 2 | NOT_ASSESSED (never ELIGIBLE) |

An unverified pass is not "immediately eligible": a job with `warning`, `note`, empty `categories_checked` or a `flagged` category is never listed in the table.

When the user names a source version, discovery returns only jobs on that version, so jobs already on Glue 6.0 or already `auto` are not counted.

## Check Short Names

Passed checks are the `categories_checked` entries with `status` = `clear`, named with these short names:

| `category` | Short name |
|---|---|
| `spark_config_values` | Spark config |
| `job_arguments` | job args |
| `logging_configuration` | logging |
| `connectors` | connectors |
| `scala_and_sdk_compatibility` | Scala/SDK |
| `glue_platform_configuration` | platform |
| `removed_or_incompatible_dependencies` | dependencies |
| `maven_jar_compatibility` | JARs |

An unknown category is shown as its raw value. `advisory` entries are not passed checks: list them only under `details`.

## The Eligible Table

```text
Immediately eligible for auto version (Glue 4.0 → 6.0): 3 of 11 jobs

Every listed job: script and job args analyzed; passed Spark config, job args, logging, connectors, Scala/SDK, platform, dependencies.

| Job              | Current version |
|------------------|-----------------|
| etl-orders-daily | 4.0             |
| etl-customers    | 4.0             |
| etl-events       | 4.0             |

Not listed: 5 need code or config changes, 2 could not be fully assessed, 1 skipped (not a Spark ETL job).
Say "details" for the reasons per job.
Target: Glue 6.0 (default). For the latest AWS Glue versions, see https://docs.aws.amazon.com/glue/latest/dg/release-notes.html; I can re-run the check for a different target.
Reply "proceed" to enable auto version on the 3 jobs above. I can also set up email notifications for auto version jobs in this Region.
```

- The heading counts the listed jobs against every job in scope.
- The line under the heading states once what every listed job shares: the input analyzed (always script and job args for a listed job) and the checks every listed job passed. The table has two columns: Job and Current version (the job's current `GlueVersion` from the discovery read, for example `4.0`). Keep the heading text and the Job column.
- The counts line names each non-empty group: need code or config changes, could not be fully assessed, could not be assessed, skipped (with the reasons in parentheses). Leave out groups with no jobs.
- With no eligible job, say so in the heading line, show the counts line and the "details" offer, and make no "proceed" offer.
- Before the notifications offer, check for an existing setup with the read-only step 0 of [notifications.md](notifications.md). If notifications are already set up in this Region, say so instead of offering them.
- The table is informational until the user replies "proceed", unless the request already named the jobs to enable (one-turn approval, [enabling-jobs.md](enabling-jobs.md) §6); enabling follows the confirmation there, and each upgrade still waits for its own consent.
- After a one-turn approval, show the table, then the result line for each named job; make the "proceed" offer only for listed jobs that were not named, and leave it out when there are none.

## Details

On "details", list every job that is not in the table, one line each, grouped by classification:

- NEEDS_CODE_CHANGES: `<job>: <category> — <breaking_changes[].detail, verbatim>` (one line per breaking change).
- NEEDS_CONFIG_CHANGES: `<job>: MaxRetries is <value>; auto requires MaxRetries >= 1` or `<job>: job run queuing is enabled`.
- NEEDS_REVIEW: `<job>: <warning or note, verbatim>`, with an offer to re-check the job.
- ASSESSMENT_ERROR: `<job>: <error message>`, with an offer to re-check the job.
- OUT_OF_SCOPE / ALREADY_CURRENT / ALREADY_AUTO: `<job>: <reason>`.
- Advisories for any job: `<job> (advisory): <detail>`.

Every listed reason is the specific finding from the assessment, never a generic "incompatible".
