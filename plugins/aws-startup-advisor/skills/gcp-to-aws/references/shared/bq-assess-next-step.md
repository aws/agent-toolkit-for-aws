# BigQuery next step: bq-assess

**Load when:** BigQuery was detected (`preferences.json` →
`metadata.inventory_clarifications.bigquery_present: true`, or a BigQuery resource marked
`Deferred — specialist engagement` in the design artifact).

This file is the single source for every `bq-assess` mention: the end-of-run offer (`SKILL.md`
Workflow Execution step 10), the report and guide callouts, the Terraform note, and the migration
script. Change commands, paths, or wording here only.

The BigQuery deferral is unchanged. This plugin still names no AWS analytics or warehouse target
and generates no BigQuery export, copy, or load steps. `bq-assess` assesses; it does not move data.

## Description (use verbatim)

`bq-assess` is an open-source AWS sample that assesses a BigQuery warehouse read-only: per-table
data-movement effort and SQL-rewrite scores, a query-engine recommendation (Amazon Athena or Amazon
Redshift Serverless) from the observed workload, and a BigQuery-vs-AWS cost comparison. It runs
locally, needs `roles/bigquery.metadataViewer` (plus `roles/bigquery.resourceViewer` for query-log
analysis), never reads table rows, and needs no AWS account.

## Commands (use exactly)

- **Claude Code:** `/plugin marketplace add aws-samples/sample-bigquery-to-aws-migration`, then
  `/plugin install bq-assess@sample-bigquery-to-aws-migration`, then ask
  `assess BigQuery migration for project <PROJECT_ID>`.
- **Other hosts:** `pip3 install "git+https://github.com/aws-samples/sample-bigquery-to-aws-migration.git"`,
  then `bq-assess --gcp-project <PROJECT_ID> --use-adc --format html,json --output reports/`.
- **Repository:** <https://github.com/aws-samples/sample-bigquery-to-aws-migration>

Put this run's project (check step 1 below) in place of `<PROJECT_ID>` when it is known.

## Existing report check

The end-of-run offer and every surface below use this one check, so they always agree.

1. **This run's project:** `live_metadata.project` in `gcp-resource-inventory.json` when live
   discovery ran. Otherwise the `config.project` of the `google_bigquery_*` resources in that
   inventory, only when they all carry the same literal project ID (not a variable reference such
   as `var.project_id`). Anything else means the project is unknown.
2. **Pointer file:** `bq-assess` 0.10.0 and later write `latest-<PROJECT_ID>.json` into their
   output folder, naming the newest successful run's files. Under the working directory, use the
   first of these that exists: `reports/latest-<PROJECT_ID>.json` (the folder the command above
   uses), then `bq-migration/latest-<PROJECT_ID>.json` (the CLI default).
3. **Usable report** only when all three hold: the pointer exists, its top-level `project_id`
   equals this run's project, and the file named by `files.report_html` exists. Paths under
   `files` are relative to the folder that contains the pointer.

- **Usable report** → link that HTML file, and skip the end-of-run offer.
- **Anything else** → no report: show the commands, and make the offer. This covers an unknown or
  different project, a JSON-only run (no `report_html`), and a run from before 0.10.0 (no
  pointer). When unsure, treat it as no report.

Never block, delay, or prompt for a report while writing an artifact.

## End-of-run offer

`SKILL.md` Workflow Execution step 10 decides when to show it. Text:

> **BigQuery next step:** BigQuery was deferred to specialists in this plan. [the Description
> above] Set it up now?
>
> [A] Yes, set up bq-assess
> [B] Not now — it stays in your report as the BigQuery next step

## Report callout (`decision-report.html`, `migration-report.html`)

Directly under the BigQuery `⚠ Specialist engagement required` callout, render one
`.callout-info` box. Leave the warning callout as the deferral. Use only the report's existing
classes: no new type size, color, or animation. Contents, in order:

1. A bold "BigQuery next step" label, then the Description.
2. Usable report: a link to it, with a path relative to the report file. Otherwise: the Claude Code
   and other-host commands as copyable `<code>` text.
3. A link labeled "Get bq-assess" to the repository.

Write no file name ending in `.json` in this box: the report validator rejects artifact file names
in executive sections.

## Migration guide block (`MIGRATION_GUIDE.md`)

After the BigQuery specialist callout, the same three items in Markdown: a bold "BigQuery next
step" line with the Description; the report link, or the commands as code; and
`[Get bq-assess](https://github.com/aws-samples/sample-bigquery-to-aws-migration)`.

## Terraform note (`terraform/README-BIGQUERY-DEFERRED.md`)

Checklist, in this order:

1. Assess BigQuery with `bq-assess`: the Description, then the usable report's path or the
   commands.
2. Engage your AWS account team and/or a data analytics migration partner for what `bq-assess`
   does not cover: ETL/ELT, BI, and downstream consumers.

## Migration script lines

Emit these `echo` lines after the deferral comment block in `generate-artifacts-scripts.md`:

```bash
echo "BigQuery: AWS target deferred — specialist engagement required."
echo "  Next step: assess BigQuery read-only with bq-assess, an open-source AWS sample:"
echo "    Claude Code: /plugin marketplace add aws-samples/sample-bigquery-to-aws-migration"
echo "                 /plugin install bq-assess@sample-bigquery-to-aws-migration"
echo '    Other hosts: pip3 install "git+https://github.com/aws-samples/sample-bigquery-to-aws-migration.git"'
echo "                 bq-assess --gcp-project <PROJECT_ID> --use-adc --format html,json --output reports/"
echo "  Then engage your AWS account team and/or a data analytics migration partner"
echo "  for ETL/ELT, BI, and downstream consumers."
echo "  No BigQuery export or load steps are generated by this skill."
```
