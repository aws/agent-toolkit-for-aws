# Dataset Quality Report Template

Step 13 writes one Markdown report per completed quality evaluation job, at
`<project-dir>/dq_report_<job-name>.md`, before presenting results in chat.
Author it from the template below. It is the durable record of the run; the
chat summary is a digest of it.

Every number in this report is read from `quality_report.json` or `metadata.json`, or is one of the three named exceptions; a figure derived from two aggregate numbers (an intersection, a ratio, a rank, a difference, a sum) is not written unless the aggregate carries it.
The report and the chat digest carry no advice the user did not ask for; next steps are offered as the choices `results-and-report.md` lists.

## Sources

The report is written from the job's aggregate-level files — `quality_report.json`, `metadata.json`, `token_usage_report.json` when present (the exploratory findings, when present, stay in the conversation) — and the job and dataset descriptions the service returns (`describe_job`; the dataset description already read at `quality-job.md` Step 9 or at `bring-your-own-spec.md` Step 3 — no new lookup for the report). The row-level file is never read for the report.

| Section | Read from |
|---|---|
| Header | `metadata.json` (`DatasetArn`, `JobArn`, `CreatedAt`, `Reports`), `quality_report.json` (`total_samples`), the format (`Format`, a service description — `quality_report.json` → `derived_inputs.format` when present, else the Step 9 detector result marked "(detected)" as this capability's own reading; on the bring-your-own-spec path `DatasetFileFormat` from the dataset description already read — when the Dataset entity cannot be described, `derived_inputs.format` or `n/a`, never a new lookup), the request (`DownSampleRecordCount`) |
| Spec-driven evaluation | `quality_report.json` → `spec_eval[0].result`; which fields, and in which cell of the report each is stated, is the list under this table |
| Deterministic | `quality_report.json` operator entries; one-line explanations from `supported-metrics.md`, or from `on-request-metrics.md` for an on-request family; flags from `result-interpretation.md` |
| Duplicate detection | `quality_report.json` → `exact_dedup` / `fuzzy_dedup`; interpretation per `deduplication/references/result-interpretation.md` |
| Language detection (in Deterministic) | `quality_report.json` → `language_detection`; flags per the language detection check in `result-interpretation.md` |
| PII detection (in Deterministic) | `quality_report.json` → `pii_detection`; flags per the PII detection check in `result-interpretation.md` |
| Dataset taxonomy | `quality_report.json` → `taxonomy` only — per bound column `taxonomy_run_id`, `input_count`, `output_count`, `excluded_count`, `count_anomaly`; per framing `l1_count`, `l2_count`, `l3_count`, `classified_count`, `low_confidence_count`; and the HTML report path `taxonomy_report_path`; interpretation per `taxonomy/references/result-interpretation.md`. The category trees live in the scored rows and are not a report source; they are built when the user asks |
| Measurement summaries | `quality_report.json` only — every summary field the criterion's entry carries (such as `value_summary` and `values`: `values` on a `context: documents` or `prompt:` metric's `row_level_criteria.<id>` entry; `value_summary` and `n_measured` on a `context: documents` metric only, in its `context_criteria.<id>` entry, never on the `row_level_criteria` entry; a `prompt:` metric or a row-only metric has none yet); a metric whose entry carries no summary gets the Measurements column's on-request words. The row-level file is never read for the report |
| Bedrock token usage (header row) | `token_usage_report.json` when present (best-effort, beside `metadata.json`; not listed in `Reports`) — `aggregate` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens`, `total_tokens`) and `per_model`, verbatim; the chat summary's Bedrock token usage line reads the same file. File absent → `n/a` |
| Other aggregate fields | `quality_report.json` → every field no other row of this table renders, printed by `scripts/other_aggregate_fields.py` as a `| Field (path) | Value |` table (its `COVERED` list is the one place that names the rendered paths; among the rest: `title`,`codegen_model_id`,`cost`,`warnings`,`dataset_schema`,`context_documents`, the`context_criteria.<id>` counts other than `n_not_applicable`,`n_not_evaluable` and `n_without_evidence` (those three are in the criterion's Result or Summary cell), `context_summary`,`context_explanation`,`builtin_criterion_explanation`,`context_measurement_explanation`,`context_field_labels`) |

The Spec-driven evaluation row, in full: `quality_report.json` → `spec_eval[0].result` —

- per criterion: `type` (row criteria only; aggregate criteria always run as code), `justification`, `reads`, `pass_rate`, `top_failure_modes`, `is_metric` (the report's marker for a `kind: metric` criterion) from `row_level_criteria` / `aggregate_criteria`;
- for a `context: documents` criterion the Result and Top failure modes cells read `context_criteria.<id>` (`pass_rate`, `n_pass`, `pass_rate_denominator`, `top_failure_modes`), and the Result cell also states its `row_level_criteria.<id>` entry's own `pass_count`, `n_evaluated` and `pass_rate` (0, 0 and null there), so Other aggregate fields does not repeat them,
- and for a metric criterion (`is_metric` true) the Measurements row's Summary cell states the same three fields of its `row_level_criteria.<id>` entry (0, 0 and null there too: a measurement grades no row; the summary carries the measurement), so Other aggregate fields does not repeat them either;
- for a `context: documents` criterion, check or metric, the same cell — the Result cell or the Summary cell — also reads `context_criteria.<id>`'s `n_not_applicable` and `n_not_evaluable`, the rows the documents grading did not grade, and `n_without_evidence`, the graded rows whose cited evidence was not verified against the documents, so Other aggregate fields does not repeat those three (the entry's other counts stay there);
- `n_field_too_long` and `n_row_too_large`, per criterion and each present only when non-zero (on the `row_level_criteria.<id>` or `context_criteria.<id>` entry), in that criterion's Result or Summary cell, never on the Rows line;
- the Coverage line reads `verifier_integrity` — `all_criteria_covered` as its ✅ / 🚨 word, `verifiers_missing` and `verifiers_errored` as JSON lists (`[]` when empty);
- the user-facing `description` ("What you asked") from `ELIGIBILITY_CRITERIA` in `spec_eval/judge_code.py` (fields there: `id`, `description`, `scope`, `type_hint`, plus `threshold`, `inputs`, `reads`, `is_metric` when set)

## Rules

- Transcribe numbers verbatim. Compute nothing beyond percent rendering. A sentence the service wrote (`pricing_rule`, a failure `reason`, an `explanation`) is copied whole, never shortened or paraphrased.
- **Every number comes from the job's aggregate-level files: `quality_report.json`, `metadata.json` or `token_usage_report.json`.**
  - Three exceptions, all asked for by this template and the only three it allows: the **Format** row, a service description (`derived_inputs.format` in `quality_report.json` or `DatasetFileFormat` from the dataset description already read, as the row says; the Step 9 detector result only when the service gives no format, and then marked "(detected)" as this capability's own reading), and the volume line's recommended minimum, this capability's own guidance from `training-volume-requirements.md`, written as the volume line shows it with nothing added after the number, the word recommended marking it as guidance and never as a job figure, and the header's report-generated time, read from the shell clock as the Timestamps rule below says, never a job figure.
  - Nothing from the spec, the generation spec, or the conversation is a result — a spec's sampling target or expected proportion is not a job output.
  - Nothing is computed from the row-level file, which is never read for the report.
- **The chat summary and every later answer about the job follow the same rule.** A number the job did not produce — a recomputed pass rate, a "would have passed" count, a corrected figure, a duration (from the status panel, the poll time or timestamps), a count obtained by subtraction, a sum across models — is never stated, in the report, in the chat summary or in an answer. When the user asks what such a figure would be, the answer is that the job did not compute it and how to run a job that does (a new `spec_eval` job whose spec states that question as a criterion; its aggregate then carries the figure).
- Absent value → `n/a`. Never invent a value or a description.
- A field present in `quality_report.json` for a family or a criterion and not named by this template is still presented, verbatim, under its own name: the template never drops what the aggregate carries. The mechanism is the **Other aggregate fields** section: `scripts/other_aggregate_fields.py` prints every such field as a path-and-value table and the section pastes it whole.
- `context_explanation`, `builtin_criterion_explanation` and `context_measurement_explanation` are presented in **Other aggregate fields** under their own names, never under Notable findings (reserved for triggered flags).
- **Spec columns are transcriptions, not paraphrases:** "What you asked" = `description` from `ELIGIBILITY_CRITERIA` in `judge_code.py`; "How it was interpreted / computed" = `justification` verbatim from this job's `quality_report.json` entry (on a `CodeArtifactS3Uri` re-run it reads "Resolved from provided judge_code.py…" — transcribe that, don't substitute the earlier run's); `reads` = the `reads` list verbatim from the same entry (never inferred from the description), rendered as comma-separated backticked field names (`prompt`, `completion`), not a Python list. Do not drop these columns.
- **"What it means" for built-ins is copied from `supported-metrics.md`, or from `on-request-metrics.md` for `language_detection`, `pii_detection`, the data filters, dedup and taxonomy.** If the catalog has no line for a metric, write `n/a` — do not write your own gloss. `compression_ratio`: low = repetitive, high = diverse (gzip ratio).
- **Notable findings**: only flags a rule in `result-interpretation.md` (or the dedup/taxonomy guides) actually triggers — a check with `pass_rate` ≥ 0.8 gets no flag; the volume rule applies to the report too, not just chat. An ℹ️ rule that fires (the format-distribution line "All records use the same text structure", the language mix, the single-topic line) is a triggered flag and is listed with its ℹ️, in the report and in the chat summary's Notable Findings; "flag" here means any triggered line, not only a warning. Order: spec flags (coverage, failed dataset-level condition, low pass rate) first, then built-in, then dedup/taxonomy.
- **Timestamps** in the header: ISO-8601 with the local offset, taken from the shell (`date +%Y-%m-%dT%H:%M%z`), never assembled by hand.
- Keep the closing italic line verbatim (it tells the reader exploratory findings live in the conversation).
- Every section appears. A family that did not run keeps only its italic `_Not run — …_` line. Exception: on both `bring-your-own-spec.md` lanes the built-in-metric sections (Deterministic, Duplicate detection, Dataset taxonomy) are left out entirely, not marked "Not run". **Other aggregate fields** is never left out on any lane and never empty: when the script prints `none`, the section reads `none`.
- Order is fixed: header → Notable findings → Spec-driven → Other aggregate fields → Deterministic → Duplicate detection → Dataset taxonomy → Output files.
- Metric criteria (written `kind: metric` in the spec; the report marks them `is_metric: true`, `pass_rate: null`) go in **Measurements**, never in Checks, never counted as failures. A row `not_evaluable` with `value_invalid: <value>` in its reason gave a value outside the criterion's `values:` twice; say so and name the value. With `value_missing` the judge of a metric without `values:` twice gave no number or text; say so.
- A row entry with `skip` was set aside by the service before any call (`field_too_long` or `row_too_large`) and is neither a success nor an error. The report carries `n_field_too_long` and `n_row_too_large` per criterion, each present only when non-zero: show them in that criterion's own row — the Checks row's Result cell or the Measurements row's Summary cell — as "set aside: [n_field_too_long] field too long, [n_row_too_large] row too large", a count the entry does not carry left out, and in chat name the remedy that applies. The **Rows** line never carries them: the aggregate has no dataset-level count, and a sum over criteria would count a row set aside for two criteria twice — a new figure, which the first rule forbids. The two kinds, their limits, how each entry counts them and the remedies are in `output-schema.md` "Set aside before any call".
- Aggregate-scope criteria go in **Aggregate criteria**; an aggregate measurement has a `value` and no meaningful verdict — report the value.
- Flags are descriptive (what is notable), not prescriptive (what to do).
- Exploratory (free-form) findings are **not** in the report; they stay in the conversation.
- **Taxonomy (on request).** When `taxonomy` ran, the report shows the aggregate's taxonomy counts (per bound column and per framing, from `quality_report.json` → `taxonomy`) and the HTML report path (`taxonomy_report_path`). The category trees live in the scored rows and are built only when the user asks for the trees or for rows, by `taxonomy/scripts/taxonomy_summary.py`, which streams the row-level object from S3 with the named columns and never downloads it whole (the user's data, which can be gigabytes; `taxonomy/overview.md` Step 8). The script is not run for the report, and the rows never enter the conversation.
- Point the user only at `spec_eval/judge_code.py` under `spec_eval/`; other files there are not part of the contract.

## Template

```markdown
# Dataset Quality Report — [job name]

| | |
|---|---|
| Dataset | `[DatasetArn]` |
| Job | `[job name]` · `[JobArn]` |
| Format | [a service description, the one the Rules allow beside the aggregate-level files: `quality_report.json` → `derived_inputs.format` when present, else the Step 9 detector result followed by "(detected)" — this capability's own reading, not the service's, used only when the service gives no format; on the bring-your-own-spec path, `DatasetFileFormat` from the dataset description already read, never a detector run and never a new lookup for the report — when the Dataset entity cannot be described, `derived_inputs.format` from `quality_report.json`, else `n/a`] |
| Rows | [rows evaluated] of [total][ · spec sample: DownSampleRecordCount = N] |
| Evaluations run | [Spec-driven · Deterministic · Duplicate detection · Taxonomy — list those present] |
| Results written | [CreatedAt from metadata.json] · report generated [`date +%Y-%m-%dT%H:%M%z`] |
| Bedrock tokens | [`token_usage_report.json` → `aggregate` fields verbatim (input_tokens · output_tokens · cache_read_input_tokens · cache_write_input_tokens · total_tokens), then per model from `per_model`; `n/a` when the file is absent] |

## Notable findings

Volume: [total_samples] records · the recommended minimum for [use]: [N] → [⚠️ below the recommended minimum / ✅ meets the recommended minimum]  ← always present when the user said the set is for training or the path is the common quality-job path; dropped on either `bring-your-own-spec.md` lane unless the caller said so; [N] is the recommended minimum `training-volume-requirements.md` gives for [use], this capability's own guidance (the one number here the aggregate does not carry); the line is written exactly in the rendered form, with no bracket, citation, or file name added after the number, because the word recommended already marks the number as this capability's guidance and not a job figure, and the line is correct for a set used only for evaluation because it speaks of fine-tuning

[Then flags from the spec coverage and failure checks first, then result-interpretation.md (deterministic), then the dedup and taxonomy interpretation guides. Use 🚨 / ⚠️ / ℹ️. Descriptive only.]

- 🚨 …
- ⚠️ …
- ℹ️ … ← an informational rule that fired (format distribution, language mix) is listed too

_None._ ← when nothing triggered

## Spec-driven evaluation

_Not run — no specification was selected for this job._ ← when absent

**Spec:** `[SpecS3Uri — or "re-run from CodeArtifactS3Uri <uri>"]` · **Judge model:** `[judge_model_id]` · **Criteria derived:** [grading_criteria_declared] checks · [metric_criteria_declared] measurements · [len(aggregate_criteria)] dataset-level (checks and measurements together; use these three numbers in chat too — never a bare "N criteria") · **Code generation attempts:** [codegen_attempts][ (0 = re-run from a previously generated artifact)]
**Coverage:** [✅ all criteria implemented | 🚨 N criteria could not be implemented: [ids from verifier_integrity.verifiers_missing + verifiers_errored] — the job completed; a green result does not cover these. A criterion counts as errored only when it errors on more than half its rows; fewer errors show in its `error_count` and in `dq_spec_eval_errored_criteria`] · `verifiers_missing`: [the JSON list verbatim, `[]` when empty] · `verifiers_errored`: [the JSON list verbatim, `[]` when empty]
**Rows:** [rows_passed] passed · [rows_failed] failed · [rows_not_evaluable] not evaluable (null ≠ failure) · [llm_api_calls] model calls

> **Skill-caller substitutions** (`bring-your-own-spec.md` Step 4S): for a `characterization` spec omit the **Rows** line above and, in the criteria table, the pass-rate / Result / Top-failure-modes columns — its row criteria are labels, not checks, and "failed" has no meaning;
> - list each criterion's id and its `type` (`code` or `llm`, read from `row_level_criteria.<id>.type`); for a label criterion add `n_evaluated`, for a measurement (a `kind: metric` criterion; the report marks it `is_metric: true`) write "measurement" instead — the report's `n_evaluated` is 0 for every measurement, and a spec made only of measurements has no pass/fail (rule owned by `result-interpretation.md` "Presenting spec-driven results");
> - report `rows_judged` labelled "rows processed (null verdicts included)", `llm_api_calls`, and each aggregate criterion's value summarised (its keys and counts, never rows).
> - Leave the built-in-metric sections out entirely (no "Not run" lines).
> - The Format row comes from the Dataset entity.

### Checks

| Criterion | What you asked | How it was interpreted | Checked by | Result | Top failure modes |
|---|---|---|---|---|---|
| `[id]` | [description from judge_code.py] | [justification] · reads `[reads]` | [code — deterministic, no model / llm — judged per row / context — judged per row against the reference documents, for a `context: documents` criterion; for `builtin_faithfulness`, the service's own criterion, write "context — service built-in"] | [pass_rate as %] ([pass_count]/[n_evaluated]) — for a `context: documents` criterion the cell states both: "graded against the documents: [`context_criteria.<id>.pass_rate` as %] ([`n_pass`] of [`pass_rate_denominator`]); row-level entry: [`pass_count`] passed of [`n_evaluated`] evaluated, `pass_rate` [`pass_rate`]" — its `row_level_criteria.<id>` entry reads 0, 0 and null there, and those three fields are stated here, not by Other aggregate fields (e.g. "graded against the documents: 68% (13 of 19); row-level entry: 0 passed of 0 evaluated, `pass_rate` null"); the cell then adds, from `context_criteria.<id>`, the rows the documents grading did not grade: "not graded against the documents: [`n_not_applicable`] not applicable, [`n_not_evaluable`] not evaluable" and, separately, "without evidence: [`n_without_evidence`]" (a count among the graded rows, the rows inside `pass_rate_denominator`, whose cited evidence was not verified against the documents — in the aggregate's own words, evidence verified means every cited passage exists in the supplied documents, not that the verdict is correct — so it says the evidence was not verified, not that the row was left out), each count transcribed verbatim, a count the entry does not carry left out, and those three counts are stated here, not by Other aggregate fields (e.g. "not graded against the documents: 1 not applicable, 0 not evaluable; without evidence: 0"); when the criterion's entry carries `n_field_too_long` or `n_row_too_large` (on `row_level_criteria.<id>` or `context_criteria.<id>`, each present only when non-zero), the cell adds "set aside: [n_field_too_long] field too long, [n_row_too_large] row too large", the count the entry does not carry left out | [top [N] listed — N = the number of entries `top_failure_modes` carries; one per entry: [reason] ([count], [fraction]), the `reason` copied whole; the list holds the top entries, not every failure mode, so N is never written as the total number of modes — for a `context: documents` criterion from `context_criteria.<id>.top_failure_modes`] |

### Measurements

_None declared._ ← when metric_criteria_declared = 0

| Criterion | What you asked | How it was computed | Computed by | Summary over [n] rows |
|---|---|---|---|---|
| `[id]` | [description] | [justification] · reads `[reads]` | [code / llm] | [every summary field this criterion's `quality_report.json` entry carries, each transcribed as it is — such as `value_summary` and `values` — `values` on a `context: documents` or `prompt:` metric, `value_summary` on a `context: documents` metric only ([n] = its `n_measured`; both in `context_criteria.<id>`, not in its `row_level_criteria` entry); a field this template does not name goes in under its own name; a row-only metric carries none yet. When the entry carries no summary: "Per-row values are in the scored dataset under `dq_spec_eval_criteria[ID].value`; ask and I can summarize them." — never a statistic computed from the rows for the report. Whether or not a summary is there, the cell also states the criterion's `row_level_criteria.<id>` entry, in the Checks row's words: "row-level entry: not graded — [`pass_count`] passed of [`n_evaluated`] evaluated, `pass_rate` [`pass_rate`]" — a metric's entry reads 0, 0 and null there (a measurement grades no row; the summary carries the measurement), and those three fields are stated here, not by Other aggregate fields (e.g. "row-level entry: not graded — 0 passed of 0 evaluated, `pass_rate` null"). For a `context: documents` metric the cell then adds, from `context_criteria.<id>`, the rows the documents grading did not grade, in the Checks row's words: "not graded against the documents: [`n_not_applicable`] not applicable, [`n_not_evaluable`] not evaluable" and, separately, "without evidence: [`n_without_evidence`]" (a count among the graded rows whose cited evidence was not verified against the documents — in the aggregate's own words, evidence verified means every cited passage exists in the supplied documents, not that the verdict is correct — so it says the evidence was not verified, not that the row was left out), each count transcribed verbatim, a count the entry does not carry left out, and those three counts are stated here, not by Other aggregate fields (e.g. "not graded against the documents: 7 not applicable, 0 not evaluable; without evidence: 0"). When the criterion's entry carries `n_field_too_long` or `n_row_too_large` (on `row_level_criteria.<id>` or `context_criteria.<id>`, each present only when non-zero), the cell adds "set aside: [n_field_too_long] field too long, [n_row_too_large] row too large", the count the entry does not carry left out] |

### Aggregate criteria

_None declared._

| Criterion | What you asked | Value | Verdict |
|---|---|---|---|
| `[id]` | [description] | [value] | [pass / fail, or "measurement" for a kind: metric criterion (the report marks it is_metric: true)] |

**Artifact:** `[the Reports.SpecEval entry ending in /judge_code.py]` — the derived criteria and their checker. Re-run the same checks on another dataset version with a `spec_eval` operation whose `CodeArtifactS3Uri` is the `spec_eval/` folder (that URI without `judge_code.py`)[; when the criteria use `context: documents`: , and pass the same `ContextDocumentsS3Uri` again, since the folder is not saved with the artifact].

## Other aggregate fields

[Run `python3 scripts/other_aggregate_fields.py <path to quality_report.json>` (the script is in the `aws-ai-ml` skill's `references/dataset-quality/scripts/` folder; the path is the local copy of the aggregate file) and paste its output here whole: the `| Field (path) | Value |` table, one row per `quality_report.json` field no section above renders, values verbatim. Never retype, shorten or summarize a row, never drop one. The section is never left out and never empty: when the script prints `none`, write `none`. `context_explanation`, `builtin_criterion_explanation` and `context_measurement_explanation` appear here under their own names.]

## Deterministic metrics

_Not run._

| Metric | Bound to | Parameters | Result | What it means |
|---|---|---|---|---|
| `[operator]` | [view columns] | [params or —] | [result fields verbatim] | [one line from supported-metrics.md, or on-request-metrics.md for an on-request family] |

[If `language_detection` ran: one row per bound column with `languages` / `min_score` as Parameters and Result = `evaluated_count`, `sampled`, `language_counts` / `language_fractions`, `unknown_count`, `low_confidence_count`, `rejected_count` / `rejected_fraction`. Add: _Identification only — nothing has been removed; `dq_language_detection_flagged__[column]` marks the rows a `LanguageFilter` with the same policy would drop._]

[If `pii_detection` ran: one row per bound column with Parameters `—` and Result = `evaluated_count` / `total_records` (`sampled`), `assessed_count`, `pii_row_count` / `pii_row_rate` with `pii_row_rate_ci`, `pii_type_counts`, `unverified_count`, `pii_found_incomplete_count`, `oversize_count`, `unscannable_count`, `empty_count`, `malformed_count`, `budget_exhausted`. Add: _Identification only on [a sample of] [evaluated_count] rows — nothing has been changed; `PiiRedaction` redacts or drops PII._ If any row got no verdict or `budget_exhausted` is true, add the matching line from the PII detection check in `result-interpretation.md`, so the report never reads as a complete scan when it was not. Never quote PII values; the report holds none.]

## Duplicate detection

_Not run — exact_dedup / fuzzy_dedup were not selected._

[When `exact_dedup` or `fuzzy_dedup` ran: fill this section as `report-optional-sections.md` "Duplicate detection" says.]

## Dataset taxonomy

_Not run — taxonomy was not selected (us-east-1 only; not in the default set)._

[When `taxonomy` ran: fill this section as `report-optional-sections.md` "Dataset taxonomy" says.]

## Output files

- Aggregate: `[the Reports.Aggregate URI ending in quality_report.json]`
- Record-level: `[Reports.RecordLevel]` — one row per input record with [`dq_<metric>__<column>` columns for the built-ins that ran / `dq_spec_eval_*` columns for the spec — name only the families that ran]
- Metadata: `[MetadataS3Uri]`
- Spec artifact: `[the Reports.SpecEval entry ending in /judge_code.py]` ← spec runs only
- Taxonomy HTML: `[taxonomy_report_path]` ← taxonomy runs only

_Flags are descriptive: they say what is notable in the data, not what to do about it. Exploratory (free-form) findings, if run, were presented in the conversation and are not part of this report._
```

<!-- markdownlint-disable-file MD033 MD056 -->
