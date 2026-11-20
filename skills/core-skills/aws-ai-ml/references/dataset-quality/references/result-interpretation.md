# Result Interpretation

Apply these checks to the results and include any triggered flags in the report. These are **descriptive only** — the dataset quality evaluation flags what's notable in the data; it does not prescribe how to fix it.

**Volume check:**

- If `total_samples` is below the recommended minimum, flag it: "⚠️ Dataset has only [N] records. SageMaker fine-tuning typically needs at least [minimum] records." Read `training-volume-requirements.md` for the number — do not hardcode it here.

**Uniqueness check** (if `uniqueness` metric is present):

The flag names the duplicates as the uniqueness result counts them, `duplicate_records` of `total_records`; no rate is computed from `uniqueness_ratio`.

- If `uniqueness_ratio` > 0.95: healthy, no flag
- If `uniqueness_ratio` 0.70–0.95: "⚠️ [duplicate_records] of [total_records] records are duplicates (uniqueness ratio [uniqueness_ratio]), moderate duplication."
- If `uniqueness_ratio` < 0.70: "🚨 [duplicate_records] of [total_records] records are duplicates (uniqueness ratio [uniqueness_ratio]), heavy duplication."
- To show *which* rows are duplicated, offer the deduplication sub-reference (`deduplication/overview.md`) rather than re-running `uniqueness`.

**Format distribution check** (if `format_distribution` is present):

- If any single format > 90%: "ℹ️ Dataset is [X]% [format]."
- If only 1 format type detected: "ℹ️ All records use the same text structure ([format])."
- Note: Format distribution is **informational only** — most domain-specific training datasets are naturally format-homogeneous. Do NOT label this as "severe" or "warning."

**Compression ratio check:**

- `compression_ratio` = gzip-compressed size / original size — **low means repetitive, high means diverse**. Read `corpus_ratio` for the dataset-level flag.
- If `corpus_ratio` < 0.2: "⚠️ Very low compression ratio ([value]) — content is highly repetitive."
- If `corpus_ratio` > 0.9: "ℹ️ Very high compression ratio ([value]) — content is highly diverse or near-random."

**Toxicity check:**

- If `toxic_records` > 0: "⚠️ [N] toxic samples detected out of [total]."

**Language detection check** (if `language_detection` is present; one entry per bound column):

- Always report the mix: "ℹ️ Languages in [column]: [top codes from `language_counts` with `language_fractions` as %] ([evaluated_count] rows)." Name the codes as the model emits them (`en`, `fr`, `ast`); `sampled: true` means the counts describe a sample.
- If `languages` was set or `min_score` > 0 (see `params`) and `rejected_count` > 0: "⚠️ [rejected_count] rows ([rejected_fraction as %]) in [column] fall outside the language policy ([languages][, min_score [min_score]]) and would be dropped by a language filter." The undetected rows are part of this count, so never add `unknown_count` to it. With neither (no `languages`, `min_score` unset or 0), `rejected_count` equals `unknown_count`; report only the unknown line below.
- If `languages` was set and `rejected_count` is 0: healthy, no flag (every detected row is inside the policy)
- If `unknown_count` > 0: "ℹ️ [unknown_count] rows in [column] have no detectable language (empty or non-text values); a language filter always drops them."
- If `low_confidence_count` > 0: "ℹ️ [low_confidence_count] detected rows scored below [min_score, or 0.5 when it was unset or 0]." These rows can also be in `rejected_count` (always when `min_score` > 0); never add the two counts. The score is a FastText confidence, not a probability, and short texts score lower; never describe it as a percent certainty.
- Nothing has been removed. `dq_language_detection_flagged__<column>` marks exactly the rows the dataset-transformation `LanguageFilter` operator drops with `TextField` = that column, `Languages` = `languages`, `MinScore` = `min_score`; offer that filter (`results-and-report.md`, the next steps) rather than a hand-written one.

**PII detection check** (if `pii_detection` is present; one entry per bound column; field meanings in `on-request-metrics.md` → "PII Detection"; report counts, entity types, and row ids, never a row's text or a PII value, as that section says):

- If `sampled` is true, say so first: "ℹ️ PII was checked on a sample of [evaluated_count] of [total_records] rows; the counts below describe the sample."
- If `pii_row_count` > 0: "⚠️ [pii_row_count] of [assessed_count] checked rows in [column] ([pii_row_rate as %], 95% range [pii_row_rate_ci as %]) contain PII: [types from `pii_type_counts` with their row counts]." Name the entity types as reported (`EMAIL`, `PHONE`). A row can hold several types, so the per-type counts can add up to more than [pii_row_count]; never present them as summing to it.
- If `assessed_count` is 0: "⚠️ None of the [evaluated_count] rows in [column] could be checked (all were unverified, unscannable, empty, or malformed), so whether the column holds PII is unknown." Report the no-verdict breakdown below, and never present this as a clean result.
- If `pii_row_count` is 0 and `assessed_count` > 0: "✅ No PII found in the [assessed_count] checked rows of [column]." Add the next line whenever it applies, since a clean result over a sample with unchecked rows is not a guarantee.
- If `evaluated_count` − `assessed_count` − `empty_count` > 0 (a test only; the difference is never stated, because the job does not report it): "ℹ️ Some rows in [column] got no verdict ([oversize_count] over the size limit, [unscannable_count] with a shape the detector does not read, [malformed_count] malformed; the rest without a usable model answer)." If `pii_found_incomplete_count` > 0, add: "[pii_found_incomplete_count] of the PII rows were only partly checked, so they may hold more types." Never add `unverified_count` to `pii_row_count`: it already includes the partly checked PII rows.
- If `budget_exhausted` is true: "⚠️ The PII check ran out of its request budget; the rows it could not reach are counted as not fully checked."
- Nothing has been changed. To redact the PII or drop those rows, offer the dataset-transformation `PiiRedaction` operator on the same column (`results-and-report.md`, the next steps), and let the user choose the action. A redact or drop run also drops every row it cannot fully scan: the rows above, and rows the dataset quality evaluation job checked that are over the `PiiRedaction` row limit (a text value, or a conversation's JSON, over 40,000 characters). To hand off, activate dataset-transformation and ask for PiiRedaction on this column.

**N-gram diversity check** (if `ngram_diversity` is present; its result is the ratio of unique n-grams to all n-grams for the `N` in `params`):

- Higher means more varied phrasing; there is no fixed band. If the ratio is very low for the domain: "ℹ️ N-gram diversity is [value] (N = [N]) — phrasing is repetitive." Otherwise, no flag.

**Plain text ratio check** (if `plain_text_ratio` is present):

- The expected share of prose-only rows depends on the use case (a chat dataset is mostly prose, a code dataset is not), so there is no fixed band. If the value is unexpected for the domain: "ℹ️ [X]% of rows are plain prose." Otherwise, no flag.

**Topic diversity check** (if `keyword_topic_coverage` ran; its result is `topic_coverage`):

- If `topic_coverage` == 1: "ℹ️ All records fall under a single topic ([topic, the one key in `keyword_topic_counts`'s `topic_counts` when that ran])."
- If `topic_coverage` >= 5: healthy, no flag

**Spec-driven evaluation checks** (if `spec_eval` section is present in `quality_report.json`):

The `spec_eval` value is a list — access fields via `spec_eval[0].result.*`.

First, check coverage — this takes priority over everything else:

- If `spec_eval[0].result.verifier_integrity.all_criteria_covered` is `false`: "🚨 Some criteria could not be implemented: [list ids from `verifier_integrity.verifiers_missing` and `verifier_integrity.verifiers_errored`]. The job succeeded, but these criteria never ran — results do not reflect full spec coverage."
- If `spec_eval[0].result.rows_missing_verdicts` > 0: "ℹ️ [N] records got no spec verdict."
- If `spec_eval[0].result.rows_unmapped` > 0: "🚨 [N] verdicts did not match any evaluated record; the spec results may be incomplete."

Then, per-criterion results (from `spec_eval[0].result.row_level_criteria` and `spec_eval[0].result.aggregate_criteria`):

- For each row **check** criterion (`kind: rule` in the spec; the report's `is_metric` marker absent or `false`. The marker is set by `kind: metric`, or inferred from measurement wording when `kind:` is absent, so a criterion with no `kind:` line that asks for a count or a length comes back `is_metric: true` and is a metric, not a broken check):
  - For a `context: documents` check, the `pass_rate` and `top_failure_modes` read below are the `context_criteria.<id>` entry's (`n_pass`, `pass_rate_denominator`, `pass_rate`, `top_failure_modes`): its `row_level_criteria.<id>` entry reads 0, 0 and null there, which is no verdict, not a healthy check; a dataset that fails every documents check gets the same flag as any other failing check
  - If `pass_rate` < 0.8: "⚠️ [criterion id] ([type]): pass rate [pass_rate * 100:.0f]% ([pass_rate]). Top failure modes, top [N] listed: [one per `top_failure_modes` entry — its `reason` copied whole ([count], [fraction])]" — N is the number of entries the list carries; the list holds the top entries, not every failure mode, so N is never the total number of modes
  - If `pass_rate` >= 0.8: healthy, no flag
  - Include `type` (`code` vs `llm`) so the user knows whether the verdict is deterministic or model-based
- For each **metric** criterion (written `kind: metric` in the spec; the report marks it `is_metric: true`, `pass_rate: null`): no pass-rate flag — it is a measurement, not a check. Present it from its aggregate entry instead:
  - Row scope: every summary field the criterion's entry carries, each as it is (such as `value_summary` and `values`: `values` on a `context: documents` or `prompt:` metric's `row_level_criteria[<id>]` entry; `value_summary` and `n_measured` on a `context: documents` metric only, in its `context_criteria[<id>]` entry; a field not named here goes in under its own name).
    - For a `context: documents` metric, the report's `value_summary` already counts per declared label in the declared order (`values: [a, b, c]`), gives number statistics (`values: 1 to 5`), or, without `values`, counts numbers and texts and gives text length statistics; read it.
    - A `prompt:` metric, and a metric with neither `context: documents` nor `prompt:`, has no `value_summary`: when the entry carries no summary, say the per-row values are in the scored dataset under `dq_spec_eval_criteria[<id>].value` and can be summarized when the user asks (the streaming script in `drill-down.md`); never a statistic computed from the rows for the default presentation.
  - A row `not_evaluable` with reason `value_invalid: <value>` means the judge twice gave a value outside the criterion's `values:`; the fix is to add the label (or widen the range), or drop the line. Reason `value_missing` means the judge of a metric without `values:` twice gave no number or text.
  - Aggregate scope: report `aggregate_criteria[<id>].value`; ignore any `verdict` on an aggregate metric entry
- A row entry with `skip` (check or metric) was set aside by the service before any call (`field_too_long` or `row_too_large`) and is neither a success nor an error; the criterion is not in `dq_spec_eval_errored_criteria`. Read the entry's `reason` and tell the user the remedy that applies; the two kinds, their limits, the report's per-criterion `n_field_too_long` / `n_row_too_large` counts and the remedies are in `output-schema.md` "Set aside before any call"
- For aggregate **check** criteria: report `aggregate_criteria[<id>].value` and its verdict; a failed dataset-level condition is a 🚨 flag. Aggregate criteria carry no `type`; they always run as code
- The field decides what the judge reads. A `prompt:` is used word for word; a description is turned into judge text by a model once per job, with or without documents (without documents, read it in `spec_eval/judge_code.py`). Each `context_criteria.<id>` entry carries `judge_text_source`: `written`, `reused` (judge text read from `judge_texts.json` beside the reused judge code on a `CodeArtifactS3Uri` run, rather than written again for this run), `prompt`, `built_in` (the service's `builtin_faithfulness`) or `description` (the text could not be written, so the description was used word for word)
- `spec_eval[0].result.warnings`: read each entry's `message`. `CONTEXT_TYPE_IGNORED` means a `type:` line on a `context: documents` or `prompt:` criterion was ignored, because the model always judges it (remove the line);
  - `FIELD_WORD_IN_DESCRIPTION` means a continuation line of a description, indented deeper than the `description:` key, begins with a lowercase field word such as `context:` or `kind:` and stayed description text, so a criterion that silently lost a deeper-indented `context: documents` line was judged without the documents (write the line at the `description:` key's column if the field was meant, otherwise reword it);
  - `PASS_RATE_SWITCH_IGNORED` means the `## Pass rate includes not applicable` section is not `true` or `false` and the spec has no `context: documents` criterion, so the default `false` was kept (remove the section, or write `true` or `false`);
  - `CONTEXT_FLAG_DROPPED_NO_DOCUMENTS` means criteria marked `context: documents` were judged without documents (supply `ContextDocumentsS3Uri`);
  - `CONTEXT_DOCUMENTS_UNUSED` means no criterion used the documents;
  - `CONTEXT_FLAG_MISSING_SUSPECTED` names criteria that may need `context: documents`;
  - `JUDGE_TEXT_NOT_WRITTEN` names criteria judged on their description word for word because the judge text could not be written

When computing pass rates from row-level data, **never count `dq_spec_eval_pass = null` as a failure**. The order in which a row is graded `false`, `null` or `true` is item 3 of "Presenting spec-driven results" below, and the column's home is `output-schema.md`, "Row-level columns (spec-driven)". Count only `true` and `false` values.

## Presenting spec-driven results

Read this section when `spec_eval` is present in `quality_report.json`; `results-and-report.md` item 4 sends the agent here.

1. **Surface `spec_eval[0].result.verifier_integrity.all_criteria_covered` first.** If `false`, tell the user explicitly which criteria couldn't be evaluated and that the job succeeded anyway — a green overall result can silently conceal criteria that never ran.

2. **Present per-criterion results** from `spec_eval[0].result.row_level_criteria` and `aggregate_criteria`: criterion id, pass rate, and top failure modes. Group row criteria by `type` (code vs. llm) so the user can see which checks were deterministic and which used a model; aggregate criteria carry no `type` and always run as code. **Metric criteria** (written `kind: metric` in the spec; the report marks them `is_metric: true`, `pass_rate: null`) are measurements, not checks — never report them as failures or flag them on pass rate; summarize from the aggregate entry (row scope: every summary field the entry carries, otherwise the template's on-request words; aggregate scope: `aggregate_criteria[<id>].value`). **A spec whose row criteria are all measurements has no pass/fail at all** — present what the aggregate carries for them and leave the `rows_passed` / `rows_failed` line out of the summary.

3. **Distinguish `null` from `false`** on `dq_spec_eval_pass` in the row-level output. The row is graded in this order: `false` when any check failed; otherwise `null` when any check errored or was set aside by the service before any call (`field_too_long` or `row_too_large`; the two kinds, their limits, the counts and the remedies: `output-schema.md` "Set aside before any call"), or when no check graded the row (outside the sample, the spec has no row checks, or every check abstained); otherwise `true`. So a row with one errored or set-aside check and the rest passing is `null`, not `true`; its errored checks are still listed in `dq_spec_eval_errored_criteria`. `null` means the row was not evaluable — not that it failed. Never count `null` rows as failures.

4. **On a full run** (no `DownSampleRecordCount`): the derived criteria are offered as one option of the Step 13 next-step menu (`results-and-report.md` item 5), named "the checks derived from your spec and their code", never as a separate question after the results. One decision per response (`overview.md` Principle 1): this offer and the next-step menu are the same question, not two.

5. **On a sample run** (`DownSampleRecordCount` was set): show the derived criteria in the results turn, before the full-run question, so the user reviews them before approving the full run. Show each `ELIGIBILITY_CRITERIA` entry from `spec_eval/judge_code.py` (`id`, `description`, and the other fields `spec-authoring.md` Step 6 lists) with its `justification` from `quality_report.json` (`spec_eval[0].result.row_level_criteria` / `aggregate_criteria`), as that Step says. The report's table does not replace this: the review is in chat. Then ask, as the one question of that turn, referring to what the user has just read:
   > "This was a sample run on [N] rows. The checks above are what a full run would reuse. Want to run the full dataset now with them?"
   If yes, assemble the full-dataset job using `CodeArtifactS3Uri` pointing to the sample run's `spec_eval/` folder: its `metadata.json` `Reports.SpecEval` entry ending in `/judge_code.py`, without the file name. If the sample run named a `ContextDocumentsS3Uri` (the criteria use `context: documents`), pass the same folder again beside `CodeArtifactS3Uri` — the folder is not saved with the criteria, and a re-run without it fails with `CONTEXT_REQUIRED_NO_DOCUMENTS`. `codegen_attempts` will show as `0` in the new run's aggregate — confirming re-derivation was skipped. Confirm the plan again (`quality-job-submit.md` Step 12, "Confirm the plan", abbreviated to the changed lines: artifact source, rows, output) before submitting.

Add spec-eval findings to the **Notable Findings** block in the report template:

> **Spec-Driven Evaluation:**
>
> - Criteria coverage: [all_criteria_covered: yes/no — if no, list ids from verifier_integrity.verifiers_missing + verifier_integrity.verifiers_errored]
> - [criterion id]: pass rate [X * 100:.0f]% ([X]), [N] failed, top failure modes: [...]
> - [metric criterion id]: measured — [every summary field the aggregate entry carries, each as it is, such as `value_summary` from the aggregate and `values`; a field the template does not name goes in under its own name; when the entry carries none: "per-row values are in the scored dataset under `dq_spec_eval_criteria[id].value`; ask and I can summarize them"]
> - ...

## Drilling into row-level records

When the user asks to see specific records, or for a measurement summary of a metric criterion, read `drill-down.md` and follow it. That page streams or filters the scored dataset where it sits on S3.
