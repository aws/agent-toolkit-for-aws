# Handling Progress Check Requests

When the user asks about job progress, status, or how many records have been evaluated (e.g., "how many samples evaluated?", "how many records have been scored?", "what's the status?", "how far along is the evaluation?"), follow this logic:

1. **Locate the job and its outputs.** Run the bundled helper with the job ARN saved from submission:

   ```bash
   python3 <skill-root>/references/dataset-quality/scripts/dq_job_output.py --job-arn <job-arn>
   ```

   It re-attaches to the job (`DataPreparer.attach(job_arn, wait=False)`) and prints one JSON line: `job_name`, `job_status`, `secondary_status`, `failure_reason`, `operators` (the job's `Operator` values), `metadata_s3_uri` (once the job has completed), `output_folder`, and `record_level` (the S3 URI of `record_level/evaluated_data.jsonl` once it exists). If you have only the job name, build the ARN first: `arn:aws:sagemaker:<region>:<account>:job/DataQualityEvaluation/<job-name>` (region and account from the session or `aws sts get-caller-identity`). Take the output location from the helper only; never build it from the output path, the job name or earlier conversation context.
2. **If `job_status` is `InProgress`**, report `secondary_status`, then look at `record_level`. For a job whose only operator is `exploratory_analysis` there are no scored rows: report that the exploratory analysis is running and its findings are written when it finishes. **If it is `Stopping`**, say so and read nothing.
3. **If `record_level` is set:** it is written whole, every row, when the built-in metrics finish and again when spec evaluation finishes, so its line count is always the dataset size, not progress. Never report a line count as records evaluated.
   - Read the first line and list the `dq_` column families present (e.g. `dq_word_count__…`, `dq_toxicity_label__…`, `dq_spec_eval_pass`).
   - Report to the user: "**Results written so far:** [families]. The job is still running." When the job has a `spec_eval` operation and no `dq_spec_eval_` column is present yet, add: "The built-in metrics are done; spec evaluation is still running."
   - Show the S3 URI of the file and offer to show records. Say once that the file holds the user's original rows, with the `dq_` score columns added to each.
   - Show record text only when the user asks for records, and then through `scripts/drill_down_rows.py` as `drill-down.md` describes: a predicate or ranking question names the mode; a plain "show me a few" uses `--lowest` or `--highest` on a `dq_` score column that is present, with `--cap 5`. The script streams the file and prints a text column the job's `pii_detection` flagged on that row as `[REDACTED: PII]`, and a `dq_input__` column (`dq_input__prompt`, `dq_input__completion`: text the service derived from a source column such as `messages`) prints as `[REDACTED: PII]` when any column of that row is flagged. Never read the file by hand to quote rows in chat.
4. **If `record_level` is null:**
   - Report: "The job is in progress (status: [secondary_status]) and no results have been written yet. The service writes the scored rows when a phase finishes, so there is no per-record progress to report."
5. **If the job is in a terminal state:**
   - `Completed`: say so, then return to the results step of the flow that submitted the job and do it in full: the main evaluation flow's Step 13, `results-and-report.md` (write `dq_report_<job-name>.md` from `report-template.md` in the project directory first, then present the results), deduplication's Step 7 (`deduplication/overview.md`, the duplicate report), or taxonomy's Step 7 (`taxonomy/overview.md`, the taxonomy). Tell the flows apart by the helper's `operators`: deduplication runs only `exact_dedup` / `fuzzy_dedup`, taxonomy runs only the `taxonomy` operator, everything else is the main flow. Read that step before writing anything; a session that starts from this page has not read it.
   - `Failed` or `Stopped`: report the status, the `failure_reason` (empty for a stopped job), and the job name and ARN, in plain words. Write no report and do not resubmit; offer a retry only if the user asks.

> **Note:** `evaluated_data.jsonl` is never partial by row: while the job runs it holds every row with the results of the phases finished so far. A job with only built-in metrics writes it once, at the end.
