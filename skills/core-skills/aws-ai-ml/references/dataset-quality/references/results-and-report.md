# Results and Report

Step 13 of the quality evaluation: read this page when the job that `quality-job-submit.md` submitted completes. The row-level drill-down continues at `drill-down.md`, read only when the user accepts the drill-down offer.

## Step 13: Present results

Once the evaluation completes (the user confirms the job finished, or you detect completion):

1. Copy the aggregate files one by one, each by its own URI, into `<project-dir>/dq_results/<job-name>/` (`aws s3 cp <uri> <project-dir>/dq_results/<job-name>/`, one command per file): `metadata.json`, the `Reports.Aggregate` file `quality_report.json`, `token_usage_report.json` beside `metadata.json`, and `aggregate/exploratory/findings.json` when the exploratory analysis ran. Never `aws s3 cp --recursive` or `aws s3 sync` on the job's output prefix: that folder holds the row-level file `record_level/evaluated_data.jsonl`, which is never copied. `metadata.json` itself is at `JobConfigDocument.MetadataS3Uri` (`aws sagemaker describe-job --job-name <job-name> --job-category DataQualityEvaluation`; Cell 8 prints it when it waits), and it lists the other URIs under `Reports`. The files, their shapes and the score-column naming are `output-schema.md`: `aggregate/quality_report.json`, `record_level/evaluated_data.jsonl`, `metadata.json`, `token_usage_report.json`, `spec_eval/judge_code.py` when a spec ran (read where it sits on S3), and `aggregate/exploratory/findings.json`. Present the exploratory findings first, as the **Exploratory Analysis** block from Step 7; they are not part of the report. Point the user only at `spec_eval/judge_code.py` under `spec_eval/`.

   **Local copies:** a temporary copy of the aggregate files (`quality_report.json`, `metadata.json`, `token_usage_report.json`, `aggregate/exploratory/findings.json`) goes under the project directory (the working folder of the conversation, where the report is written), in the `dq_results/<job-name>/` folder above, and nowhere else: not `/tmp`, not `mktemp`, not the home directory; `scripts/other_aggregate_fields.py` reads the copy there. The row-level file is never copied for the report.

### Data source rules

- **Result interpretation uses `quality_report.json` only** (aggregate metrics). This file is small and fixed-size regardless of dataset size. All threshold checks and flags come from aggregate metrics.
- **The written report and the chat summary are written from the job's aggregate-level files only** (`quality_report.json`, `metadata.json`, `token_usage_report.json` when present) and the job and dataset descriptions the service returns, with the three exceptions the template's Rules name: the Format row, the volume line's recommended minimum, and the report-generated time. A figure derived from two aggregate numbers (an intersection, a ratio, a rank, a difference, a sum) is not written unless the aggregate carries it. The sources, the exceptions and the taxonomy counts are `report-template.md` "Sources" and "Rules".
- **Record-level data (`evaluated_data.jsonl`) is only read on-demand** — when the user explicitly asks to see specific records (e.g., "show me the toxic samples", "which records failed my spec criteria").
- **When reading record-level data, sample or filter — never load the full file into context.** For large datasets (thousands of rows), use the streamed read of the drill-down procedure in `drill-down.md` to extract only the relevant records. Example: "Here are the 5 records with the lowest word count" rather than loading all 15,000 rows.

Make this clear to the user when presenting results:

> "These findings are based on the **aggregate quality report**. The per-record scored dataset is also available if you'd like to drill into specific records — for example, I can show you the lowest-scoring records for a metric with a per-row score, or list the flagged toxic samples."

A per-row score exists only for a metric whose row column holds a number (`dq_word_count__<column>`, for example; which metrics write row columns: `output-schema.md`, "Scored Dataset Structure"). `toxicity` writes a toxic/not_toxic label per row (`dq_toxicity_label__<column>`) and no score: never say the scored file holds toxicity scores or offer to rank rows by one; its rows can be listed by label (`drill-down.md`, the label-only route).

2. Read `output-schema.md` to understand the result structure. If `exact_dedup` or `fuzzy_dedup` ran, also read `deduplication/references/result-interpretation.md` and present their aggregates (flagged rows, duplicate rate, group count) the way it describes; the uniqueness reading below does not apply to them. If `language_detection` ran, present its language mix and would-be-rejected share per the language detection check in `result-interpretation.md`. If `pii_detection` ran, present its PII share and entity types per the PII detection check there. If `taxonomy` ran, read `taxonomy/references/result-interpretation.md` and present the aggregate's taxonomy fields (the per-column and per-framing counts and the HTML report path) the way that guide describes; the category trees are built on request (`report-template.md` Rules, the taxonomy bullet).

3. **Write the report.** Before presenting anything, **read `report-template.md` now** (every time — do not write from memory) and author `<project-dir>/dq_report_<job-name>.md` following its structure exactly: header table, Notable findings, the sections in order — Spec-driven evaluation, Other aggregate fields (run `scripts/other_aggregate_fields.py` on the local copy of `quality_report.json` and paste its table whole: every field no other section renders), Deterministic metrics, Duplicate detection, Dataset taxonomy, Output files — "*Not run*" lines for absent families, the closing italic line.
   - A report in any other shape is wrong even if its numbers are right.
   - Sources: the job's aggregate-level files — `quality_report.json`, `metadata.json`, `token_usage_report.json` when present — the job and dataset descriptions the service returns (`describe_job`; the dataset description already read at `quality-job.md` Step 9 or `bring-your-own-spec.md` Step 3 — no new lookup for the report), `spec_eval/judge_code.py` (criterion descriptions, when a spec ran), and this capability's metric catalog for built-in explanations.
   - Never the full row-level file.
   - Every section of the template appears; families that did not run get the template's "*Not run*" line.
   - Spec-driven results come first.
   - Exploratory findings are not part of the report.
   - When `exact_dedup`, `fuzzy_dedup` or `taxonomy` ran, also read `report-optional-sections.md`, which fills those two sections.

4. Present a chat summary with **notable findings** flagged from the result interpretation checks below, the report path, and the Output files block. Every number in the chat summary comes from the job's aggregate-level files — `quality_report.json` / `metadata.json` / `token_usage_report.json` — or the report you just wrote; never from the spec, the generation spec, an expectation, or the row-level file. Rules of the chat summary, and of every later answer about the job:
   - **A number the job did not produce is never stated** — not a recomputed pass rate, not a "would have passed" count, not a corrected figure, not a duration (no aggregate file carries one; a figure read off the status panel, the poll time or two timestamps is the agent's, not the job's), not a count obtained by subtraction (rows total minus rows passed is not a failure count the job reported), not a sum across models or criteria. When the user asks what such a figure would be, the answer is that the job did not compute it, and how to run a job that does: a new `spec_eval` job whose spec states that question as a criterion (`quality-job-submit.md` Step 12; a re-run from `CodeArtifactS3Uri` keeps the criteria as they are), whose aggregate then carries the figure.
   - **The volume line decides the readiness sentence.** When the report's Volume line is ⚠ below minimum (`report-template.md`, the volume line; `result-interpretation.md`, Volume check), the chat summary says the count and the minimum and never says the dataset is ready for fine-tuning or that nothing in the results blocks it.
   - Each measurement line carries every summary field the criterion's aggregate entry has, each as it is, the `values` list included. A measurement whose entry carries no summary gets the template's on-request sentence (the per-row values are in the scored dataset under `dq_spec_eval_criteria[<id>].value`; ask and I can summarize them), never a claim that the service "normally" or "usually" writes one.
   - A quoted service sentence (a failure `reason`, `pricing_rule`, an explanation) is copied whole, never cut with an ellipsis (the template's verbatim rule).
   - The summary always carries the drill-down offer above, whether or not a flag was raised.

   The digest:

> **Dataset Quality Report** *(based on aggregate metrics — full report: `dq_report_<job-name>.md`)*
>
> **Spec-driven evaluation:** [only if a spec ran]
>
> - Coverage: [all criteria implemented / N criteria could not be implemented: ids]
> - Rows: [passed] passed · [failed] failed · [not evaluable]
> - [criterion id]: [pass rate % — or, for measurements, every summary field the aggregate entry carries (such as `value_summary` and `values`), otherwise the template's on-request words]
> - ...
>
> **Deterministic Metrics:**
>
> - Compression ratio: [value] — [interpretation]
> - Toxicity: [count] toxic samples out of [total]
> - Topic coverage: [N] topics detected
> - Uniqueness: [ratio] ([unique]/[total] distinct records)
> - ...
>
> **Notable Findings:**
>
> - [List any flags from the result interpretation checks below]
>
> **Bedrock token usage:** [from token_usage_report.json]
>
> **Output files:**
>
> - Report: `<project-dir>/dq_report_<job-name>.md`
> - Metrics: [the `Reports.Aggregate` URI ending in `quality_report.json`]
> - Scored dataset: [the `Reports.RecordLevel` URI]
> - Metadata: [MetadataS3Uri]
> - Spec artifact: [the `Reports.SpecEval` URI ending in `judge_code.py`] [only if a spec ran]

   The Output files block is in every chat summary, with its four lines Report, Metrics, Scored dataset and Metadata (and Spec artifact when a spec ran), each S3 location the full URI pasted from `metadata.json` (its own URI is `JobConfigDocument.MetadataS3Uri` in `describe_job`'s response; read the URI, never build it), never shortened with an ellipsis. The local copies under `dq_results/<job-name>/` and a pointer to the report do not replace these lines.

### Result Interpretation

Apply the threshold checks defined in `result-interpretation.md` and include any triggered flags as **Notable Findings** in the report. The checks are **descriptive only** — the dataset quality evaluation flags what's notable in the data; it does not prescribe how to fix it.

If spec-driven evaluation ran (`spec_eval` present in `quality_report.json`), present it as `result-interpretation.md` "Presenting spec-driven results" says: coverage first, then the per-criterion results, `null` kept apart from `false`; after a sample run, the derived criteria shown in the results turn and then the full-run question (its item 5 carries the re-run rule, whose home is `quality-job-submit.md`, "Re-run from a previously generated code artifact"); after a full run, the derived criteria are one option of the next-step menu below (its item 4), never a separate question. The Checked by column of the report names how each check ran, the `context` label included (`report-template.md`, the Checks table).

5. Offer next steps, last in the reply: the next-step question and its options come after the digest and its Output files block, never before them. The drill-down offer (above) and, when Step 11 did not already settle it, the dashboard ("an interactive dashboard of the report") are always among them, in both choices below. When a spec ran on a full run (no `DownSampleRecordCount`), "the checks derived from your spec and their code" is also among them, in both choices below; it is never asked as its own question (`result-interpretation.md` "Presenting spec-driven results", item 4). The menu is skipped only on the skill-caller lane of `bring-your-own-spec.md` (Step 4S), where another capability called this one and owns what happens next; a person who brought a spec file, or asks for the results of a job that ran a spec, gets the whole menu. **If the exploratory analysis has not run in this session**, also offer "Explore for issues the spec didn't cover" in both choices below.

If flags were raised, ask the user to choose a next step and name each option with what it does. The options are "Dive deeper" (any specific metric or the flagged records), "Clean or filter the dataset" (remove duplicates, filter toxic records, fix encoding issues), "Filter by language" (drop the rows outside the language policy this run flagged), "Redact or remove PII" (redact the PII spans, or drop or tag the rows that hold PII), "Audit duplicates" (see which rows are exact or near-duplicates, and of what, before removing anything), "Review flagged records" (human annotation for records that need manual judgment), "Generate more data" (synthetic examples to address gaps) and "Explore for issues the spec didn't cover" (a free-form pass over the data for problems no metric or requirement anticipated; only if it has not run).

Only offer options that are relevant to the actual findings:

- Low uniqueness, or rows flagged by `exact_dedup` / `fuzzy_dedup` → "Audit duplicates" (routes to the deduplication sub-reference: which rows are duplicates and of what); "Clean or filter" (routes to dataset-transformation) when the user only wants a cleaned local file
- Toxic records, encoding issues, length violations → "Clean or filter" (routes to dataset-transformation)
- Rows flagged by `language_detection` → "Filter by language" (routes to dataset-transformation's `LanguageFilter` with the same `languages` → `Languages`, `min_score` → `MinScore`, and bound column → `TextField`; it drops exactly the flagged rows)
- PII found by `pii_detection` (`pii_row_count` > 0) → "Redact or remove PII" (routes to dataset-transformation's `PiiRedaction` on the same column)
- Spec criteria failing on judged rows, ambiguous toxicity, borderline quality → "Review flagged records" (routes to human-in-the-loop)
- Low diversity, dataset too small, insufficient topic coverage → "Generate more data" (routes to synthetic-dataset-generation)

If no flags were raised, say the dataset looks healthy and ask the user to choose between "Dive deeper" (any specific metric, or sample records), "Explore for issues the spec didn't cover" (a free-form pass over the data; only if it has not run) and "Proceed to fine-tuning".

⏸ Wait for user. The word "skill" never reaches the user here or in any other turn (`overview.md` Principle 7). Route based on user choice:

- "Clean or filter" → activate **dataset-transformation** with the scored dataset path and the specific findings as context
- "Audit duplicates" → read `deduplication/overview.md` and follow it, with the Dataset ARN, the text column, and the uniqueness finding as context
- "Filter by language" → activate **dataset-transformation** with the Dataset ARN and a `LanguageFilter` config carried over from this run: `TextField` = the bound column, `Languages` = `languages`, `MinScore` = `min_score` (omit any the run omitted), plus the `rejected_count` it should remove (a sample's count when `sampled` is true)
- "Redact or remove PII" → activate **dataset-transformation** with the Dataset ARN and a `PiiRedaction` config carried over from this run: `MessagesField` = the column bound with Role `Messages`, or `TextField` = the column bound with Role `Text`. The dataset quality evaluation chooses no action, so ask for it (`DefaultAction`, and `ActionMap` for per-type actions); pass the run's `pii_type_counts` as context. Before submitting, warn that a redact or drop run also drops rows the dataset quality evaluation job checked but `PiiRedaction` cannot fully scan, such as a text value, or a conversation's JSON, over 40,000 characters; dataset-transformation checks its own record limit. The counts describe a sample, so do not promise how many rows the transform will change
- "Review flagged records" → activate **human-in-the-loop** with the scored dataset and the flagged quality issues as the review recommendation
- "Generate more data" → activate **synthetic-dataset-generation** with the gap context (what's missing — diversity, volume, topic coverage)
- "Explore for issues" → read `exploratory-analysis.md` and run the free-form exploratory analysis on the local copy; findings stay in chat
- "The checks derived from your spec" → show in chat each `ELIGIBILITY_CRITERIA` entry from `spec_eval/judge_code.py` with its `justification` from `quality_report.json`, the fields and sources `spec-authoring.md` Step 6 lists

### Visualizing the Report

If the user opted in during `quality-job.md` Step 11 (input 8), generate the dashboard now. If the user did not opt in at Step 11, the dashboard is one option of the Step 13 next-step offer (item 5), never a separate question after it: the offer is the one question of that turn, and a second "Want me to generate an interactive dashboard?" is never asked.

If the user chooses the dashboard, follow `report-visualization.md`.

### Drilling Into Row-Level Records

If the user asks to see specific records (e.g., "show me records that failed a spec criterion", "which records are toxic?", "show the lowest-scoring records"), follow the procedure in `drill-down.md` — stream or filter the scored dataset (never download the whole file: a predicate question such as "records that failed a spec criterion" uses a streamed read that stops after the first 20 matching rows; a ranking question such as "the lowest-scoring records" uses a streamed read that makes one pass over the whole stream and keeps the 20 extreme rows, since the first 20 rows in file order are arbitrary; both reads keep only the named columns) and present up to 20 rows worst-first. A text column the job's `pii_detection` flagged on a row, and on that row every `dq_input__` column the service derived from a source column (`dq_input__prompt` and `dq_input__completion` from `messages`), shows as `[REDACTED: PII]`, as the drill-down script prints it.

A measurement summary of a metric criterion (min / mean / max or a label distribution) is `scripts/stream_measurements.py`, run only when the user asks for one and never for the report, as `drill-down.md` says. The taxonomy's category trees, or the rows in a category, are built only when the user asks, as `taxonomy/overview.md` Step 8 says.

When matching columns in the scored output, use the `dq_<metric>__<column>` pattern; spec results are `dq_spec_eval_pass`, `dq_spec_eval_failed_criteria`, and `dq_spec_eval_criteria`. For example, if the user asks about "toxicity", match columns containing `toxicity` in the name. For runs without a View, the column suffix will be `dq_input__prompt` or `dq_input__completion` (e.g., `dq_word_count__dq_input__completion`).

<!-- markdownlint-disable-file MD029 -->
