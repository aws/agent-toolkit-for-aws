# Dataset Quality Evaluation Output Schema

## Overview

The dataset quality evaluation writes three output files to a folder of its own under `S3OutputPath`, named by the service. Read the location, never build it: a completed job's `metadata.json` is at `JobConfigDocument.MetadataS3Uri` in DescribeJob, and it lists the other files' S3 URIs under `Reports`. (A job whose dataset was deleted while it ran completes without `MetadataS3Uri`; `scripts/dq_job_output.py` still finds its folder.) A running job has no `MetadataS3Uri` yet; `scripts/dq_job_output.py` finds its folder too (`progress-check.md`).

1. **aggregate/quality_report.json** — dataset-level metric summaries
2. **record_level/evaluated_data.jsonl** — original records with `dq_` score columns appended
3. **metadata.json** — job metadata, Dataset ARN, evaluation config, report S3 paths under `Reports` (`Aggregate`, `RecordLevel`, and `SpecEval` when a spec ran)

When a `spec_eval` operation ran, a fourth artifact is written: **spec_eval/judge_code.py** (see [Spec-Driven Evaluation Output](#spec-driven-evaluation-output)). When `exploratory_analysis` ran, `quality_report.json` gains an `exploratory_analysis` entry and the job adds **aggregate/exploratory/findings.json** (see [Exploratory Analysis Output](#exploratory-analysis-output)). All metrics and the spec share the one `quality_report.json` and the one `evaluated_data.jsonl`. The job also writes `token_usage_report.json` beside `metadata.json`, in the folder of `MetadataS3Uri` (best-effort; not listed in `Reports`; none on an exploratory-only job; the Bedrock tokens of the metrics and spec evaluation, in total and per model, not of the exploratory analysis).

`DataPreparer.evaluate()` returns the **input** DataSet (a dataset quality evaluation job registers no new hub content), so `dq_dataset.source` is the input location, not the output folder.
Submit with `wait=False` to get the job handle (`job.job_name`, `job.job_arn`), call `job.wait()`, then read `MetadataS3Uri` from the handle's `job_config_document` (DescribeJob's `JobConfigDocument`).

## Aggregate Report Structure

Each metric produces a list of runs. A single run (one column binding) is a one-element list. Multiple runs of the same metric on different columns produce multiple elements. The example mixes runs without a View (`dq_input__` tags) and with one.

```json
{
  "total_volume": 500,
  "total_samples": 500,
  "derived_inputs": {
    "format": "OpenAI_Messages",
    "columns": {
      "dq_input__completion": "the content of the last assistant message",
      "dq_input__prompt": "the content of every message before the last assistant message, system messages included, joined with spaces"
    }
  },
  "word_count": [
    {"view": {"Text": "dq_input__prompt"}, "result": {"min": 3, "max": 120, "mean": 28.5}},
    {"view": {"Text": "dq_input__completion"}, "result": {"min": 5, "max": 200, "mean": 65.3}}
  ],
  "uniqueness": [
    {"view": {"Text": "dq_input__completion"}, "params": {"CaseSensitive": true}, "result": {"uniqueness_ratio": 0.95, "total_records": 500, "unique_records": 475, "duplicate_records": 25}}
  ],
  "toxicity": [
    {"view": {"Text": "dq_input__completion"}, "result": {"mean_toxicity_score": 0.03, "toxic_records": 2, "total_records": 500, "scored_records": 500, "threshold": 0.2}}
  ],
  "ngram_diversity": [
    {"view": {"Text": "dq_input__completion"}, "params": {"N": 1}, "result": {"ngram_diversity": 0.82, "N": 1}}
  ],
  "effectiveness": [
    {"view": {}, "result": {"effectiveness": 0.75, "total_volume": 500}}
  ],
  "data_balance": [
    {"view": {"Label": ["difficulty", "topic"]}, "result": {"data_balance": 0.78, "per_field_balance": {"difficulty": 1.0, "topic": 0.56}}}
  ],
  "keyword_topic_counts": [
    {"view": {"Text": "answer"}, "params": {"default_topic": "general"}, "result": {"topic_counts": {"technical": 200, "medical": 150, "general": 100, "legal": 50}}}
  ],
  "language_detection": [
    {"view": {"Text": "question"}, "params": {"languages": ["en"], "min_score": 0.0}, "result": {"evaluated_count": 500, "sampled": false, "language_counts": {"en": 470, "fr": 20, "de": 7, "unknown": 3}, "language_fractions": {"en": 0.94, "fr": 0.04, "de": 0.014, "unknown": 0.006}, "unknown_count": 3, "low_confidence_count": 4, "rejected_count": 30, "rejected_fraction": 0.06}}
  ],
  "pii_detection": [
    {"view": {"Messages": "messages"}, "sampling": {"method": "seeded_random", "seed": 20260831, "sampled_records": 1000, "total_records": 4200}, "result": {"evaluated_count": 1000, "total_records": 4200, "sampled": true, "assessed_count": 992, "pii_row_count": 37, "pii_row_rate": 0.0373, "pii_row_rate_ci": [0.0272, 0.0510], "pii_type_counts": {"EMAIL": 21, "PHONE": 12, "PRIVATE_NAMES": 9}, "unverified_count": 7, "pii_found_incomplete_count": 2, "oversize_count": 0, "unscannable_count": 3, "empty_count": 0, "malformed_count": 0, "num_requests": 1004, "budget_exhausted": false}}
  ]
}
```

### Key points:

- Each metric key uses the **bare operator name** (e.g., `word_count`, `compression_ratio`, `data_balance`) — no `text.` / `tabular.` / `dataset.` prefix
- The value is always a **list** of run objects
- Each run object has: `view` (what columns it ran on; `{}` for effectiveness), optional `params`, and `result`. The one exception is `exploratory_analysis`, which is not a metric: `"exploratory_analysis": [{"result": {"findings": [...]}}]`, no `view` or `params` ([Exploratory Analysis Output](#exploratory-analysis-output))
- The `view` is keyed by the Role the run bound (`{"Text": "answer"}`, `{"Label": ["col1", "col2"]}`, `{"Messages": "messages"}`): one column renders as a string, several as a list. A run without a View shows the derived column it read, `{"Text": "dq_input__completion"}`
- `params` lists the settings the run used, **catalog defaults included**, whether or not the request wrote them (`ngram_diversity` without `N` reports `{"N": 1}`). It is absent for a metric that has no settings with defaults and was given none. `exact_dedup`, `fuzzy_dedup` and `taxonomy` also echo their settings inside `result`
- `derived_inputs` (present only when a run had no View) names the detected `format` and says, per `dq_input__` column, how it was derived from the records
- `language_detection` echoes `languages` (when set) and `min_score` (default `0.0`) under `params`. `language_counts` always carries `unknown`; `rejected_count` counts rows with `language_detection_flagged` true (identification only; the dataset quality evaluation job never drops rows)
- `pii_detection` takes no params, so its runs carry no `params`. A run that evaluated a sample adds a `sampling` block (`method`, `seed`, `sampled_records`, `total_records`), and `result.sampled` is true; every count then describes the sample. Field meanings are in `on-request-metrics.md` → "PII Detection"

## Scored Dataset Structure (Row-Level)

Each record in `evaluated_data.jsonl` contains the original fields plus `dq_` prefixed score columns using the pattern `dq_<metric>__<column>`. Only metrics whose Output is "both" or "row-level" in `supported-metrics.md` (or `on-request-metrics.md` for an on-request family) write row columns; the `Column` / `Label` metrics and the other aggregate-only metrics add none:

```jsonl
{"question": "What is ML?", "answer": "Machine learning is...", "dq_word_count__answer": 3, "dq_compression_ratio__answer": 0.42, "dq_toxicity_label__answer": "not_toxic", "dq_content_structures__answer": "prose_only"}
```

### Column naming rules:

- Single column binding (Role `Text`): `dq_<metric>__<column>` — e.g., `dq_word_count__answer`
- `<column>` is the bound column lowercased, with each run of characters other than letters and digits replaced by one `_` and any leading or trailing `_` dropped (`User-Prompt` → `dq_word_count__user_prompt`). The aggregate `view` tag keeps the original name
- Same metric on different columns: separate columns — `dq_word_count__question` + `dq_word_count__answer`
- Deduplication and taxonomy insert a field segment: `dq_<operator>_<field>__<column>`
- The `<metric>` part is the metric's row-column name, which can differ from the operator name (`toxicity` writes `dq_toxicity_label__<column>`)
- Zero-operand metrics: `dq_<metric>` with no suffix (not applicable to most operators)
- `language_detection` writes three columns per bound column: `dq_lang__<column>` (detected code, `unknown` when undetected), `dq_lang_score__<column>` (confidence in [0, 1], `0` when undetected), `dq_language_detection_flagged__<column>` (boolean: true for exactly the rows the dataset-transformation `LanguageFilter` would drop under the same policy). It always has a View on a raw column, so the suffix is the raw column name, never `dq_input__*`
- `pii_detection` writes three columns per bound column: `dq_pii_flagged__<column>` (boolean), `dq_pii_types__<column>` (comma-separated entity types, empty when none), `dq_pii_status__<column>` (one of the statuses in `on-request-metrics.md` → "PII Detection"). All three are null on rows outside the evaluated sample. It always has a View on a raw column, so the suffix is the raw column name (`dq_pii_flagged__messages`), never `dq_input__*`

### Runs without a View:
A metric run without a View (every `default_metrics` member, or a listed metric with no View) on a recognized format reads text the service derives from the records, on every recognized format, columnar or nested:

- **Derived text columns:** `evaluated_data.jsonl` carries the derived text a run read as `dq_input__prompt` and `dq_input__completion` (prompt only for Nova_CPT and Verl), so each score sits next to the text it scored. `quality_report.json` → `derived_inputs` says how each was derived.
- **Metric score columns:** the suffix is the derived column, `dq_<metric>__dq_input__prompt` and `dq_<metric>__dq_input__completion`.
- **Aggregate view tags:** `{"Text": "dq_input__prompt"}` and `{"Text": "dq_input__completion"}`.

A run with a View on a raw column of the same name is a different run with a different column: on HF_Prompt_Completion, `word_count` without a View writes `dq_word_count__dq_input__completion`, and with `[{"Role": "Text", "Column": "completion"}]` writes `dq_word_count__completion`.

Example row for OpenAI_Messages, `default_metrics`:

```jsonl
{"messages": [...], "dq_input__prompt": "What is ML?", "dq_input__completion": "Machine learning is...", "dq_word_count__dq_input__prompt": 3, "dq_word_count__dq_input__completion": 5, "dq_toxicity_label__dq_input__completion": "not_toxic"}
```

## Spec-Driven Evaluation Output

When a `spec_eval` operation ran, the job writes a `spec_eval/` folder alongside the standard three files, adds a `spec_eval` entry to `quality_report.json`, and adds four `dq_spec_eval_*` columns to `evaluated_data.jsonl`. `metadata.json`'s `Reports` block gains `SpecEval`: the sorted S3 URIs of the files in `spec_eval/`. The judge is the entry ending in `/judge_code.py`, and the folder is that URI without `judge_code.py`.

### Additional output directory: `spec_eval/`

| File | Contents |
|---|---|
| `spec_eval/judge_code.py` | **The contract artifact.** Self-contained module: the derived criteria (`ELIGIBILITY_CRITERIA` — `id`, `description`, `scope`, `type_hint`, plus `threshold`, `inputs`, `reads`, and `is_metric` when set; a `kind: metric` criterion appears as `type_hint: "auto"` with `is_metric: true`, the report's marker for a metric) plus one `_check_<id>` function per criterion. Each criterion's resolved `type` and `justification` are reported in `quality_report.json`. Pass the **folder** that contains it (`s3://…/spec_eval/`) as the `spec_eval` operation's `CodeArtifactS3Uri` to re-run the same checks without re-derivation; a URI ending in `/judge_code.py` is rejected when the job starts. |
| `spec_eval/extracted_criteria.json`, `spec_eval/reproduce.py` | Present, but not part of the contract; do not point the user at them. On a `CodeArtifactS3Uri` re-run, an `extracted_criteria.json` in the folder takes precedence over the criteria embedded in `judge_code.py`, so an edit made only in `judge_code.py`'s `ELIGIBILITY_CRITERIA` is ignored while that file is there. |

Dataset-level (aggregate-scope) results live in `quality_report.json` under `spec_eval[0].result.aggregate_criteria`.

### Row-level columns (spec-driven)

Four fixed columns added to `evaluated_data.jsonl` — no `__<column>` suffix since criteria apply to the whole record, not a bound column:

| Column | Type | Values | Notes |
|---|---|---|---|
| `dq_spec_eval_pass` | tri-state | `true` / `false` / `null` | Computed over **check** criteria only; metric criteria never affect it. The row is graded in this order: `false` when any check failed; otherwise `null` when any check errored or was set aside by the service before any call (`skip` in `dq_spec_eval_criteria`: `field_too_long` or `row_too_large`, below), or when no check graded the row (outside the `DownSampleRecordCount` subset, the spec has no row-level checks, or every check abstained); otherwise `true`. So a row with one errored or set-aside check and the rest passing is `null`, not `true`; its errored checks are still listed in `dq_spec_eval_errored_criteria`. **Never treat `null` as a failure.** |
| `dq_spec_eval_failed_criteria` | list | criterion ids | Check criteria that returned a failing verdict for this row |
| `dq_spec_eval_errored_criteria` | list | criterion ids | Criteria that could not be evaluated for this row. A criterion the service set aside (`skip`, below) is not listed here. |
| `dq_spec_eval_criteria` | dict | per-criterion detail | Keyed by criterion id; two entry shapes, told apart by `source`.; the two shapes are the list under this table |

The `dq_spec_eval_criteria` entry shapes, in full: Keyed by criterion id; two entry shapes, told apart by `source`.

- **Row-only criterion** (`source` `code` / `llm`): `verdict` (`true`/`false` on checks, `null` on metrics), `value` (`null` on checks; number or label on metrics), `reason`, `confidence`, `error_type`.
- **`context: documents` criterion** (`source` `context`; the built-in `builtin_faithfulness` included): no `verdict` — `outcome` (`pass` / `fail` / `not_applicable` / `not_evaluable`; `measured` on a documents metric, which adds `value` and `value_kind`), `support` (`supported` / `unsupported` / `contradicted`), `evidence` (the cited passage ids), `quote` (the cited text), `reason`, `evidence_verified` (`true` when every cited passage exists in the documents — an address check, not the grade), then the service's further fields under their own names (`quote_verified`: `cited` / `document` / `none`; `origin`: `customer_spec` / `built_in`; `attachment`, `relevance`, ...).
- A filter on a documents criterion tests `outcome`, never `verdict`.
- An entry the service set aside before any call also carries `skip`: `field_too_long` or `row_too_large` ("Set aside before any call", below).

For an LLM-backed check the `reason` is the primary output, and `source` tells the user whether a verdict was deterministic or a model's opinion.

Example row fragment (one check, one metric):

```json
"dq_spec_eval_criteria": {
  "completion_min_word_count": {"verdict": true, "value": null, "reason": "completion has 24 words, meets threshold of 15", "confidence": 1.0, "source": "code", "error_type": null},
  "prompt_character_count":    {"verdict": null, "value": 30,   "reason": "prompt contains 30 characters",                  "confidence": 1.0, "source": "code", "error_type": null}
}
```

### Aggregate report: `spec_eval` section

`spec_eval` appears as a one-element list in `quality_report.json`, following the same `{view, result}` pattern as other operators. Shape (abbreviated):

```json
"spec_eval": [
  {
    "view": {},
    "result": {
      "title": "SFT Dataset Quality Requirements",
      "codegen_model_id": "<service-returned model id>",
      "judge_model_id": "<service-returned model id>",
      "rows_total": 8, "rows_requested": 8, "rows_judged": 8,
      "rows_missing_verdicts": 0, "rows_unmapped": 0,
      "rows_passed": 6, "rows_failed": 2, "rows_not_evaluable": 0,
      "grading_criteria_declared": 4,
      "metric_criteria_declared": 2,
      "llm_api_calls": 8,
      "row_level_criteria": {
        "completion_min_word_count": {
          "type": "code", "scope": "row", "locked": false,
          "justification": "Word counting is a deterministic string operation...",
          "threshold": {"min_words": 15},
          "success_count": 8, "error_count": 0,
          "pass_count": 7, "n_evaluated": 8, "pass_rate": 0.875,
          "top_failure_modes": [{"reason": "completion has 9 words, below threshold of 15", "count": 1, "fraction": 1.0}],
          "verifier_status": "generated",
          "reads": ["completion"]
        },
        "prompt_character_count": {
          "type": "code", "scope": "row", "locked": false,
          "justification": "Counting characters in a string is a simple deterministic operation...",
          "threshold": null,
          "success_count": 8, "error_count": 0,
          "pass_count": 0, "n_evaluated": 0, "pass_rate": null,
          "top_failure_modes": null,
          "verifier_status": "generated",
          "reads": ["prompt"],
          "is_metric": true
        }
      },
      "aggregate_criteria": {},
      "cost": {"rows_judged": 8, "llm_calls_made": 8, "llm_calls_avoided_via_code": 40, "savings_pct": 0.83},
      "dataset_schema": {"rows_scanned": 8, "fields": [{"name": "prompt", "types": ["string"], "count": 8, "nullable": false}]},
      "code_version_hash": "<16 hex characters>",
      "codegen_attempts": 1,
      "verifier_integrity": {
        "criteria_declared": 6, "verifiers_generated": 6,
        "verifiers_missing": [], "verifiers_errored": [],
        "all_criteria_covered": true
      }
    }
  }
]
```

Key fields inside `result`:

- `codegen_model_id` / `judge_model_id` — the model IDs returned by the service; see `dataset-service-api.md` Spec-driven evaluation, "Model", for the service's default model and permitted overrides; `codegen_model_id` is `null` on a `CodeArtifactS3Uri` run
- `rows_requested` / `rows_judged` / `rows_missing_verdicts` — coverage evidence; verify no records were silently dropped. `rows_unmapped` > 0 means rows the service could not map; report it
- `grading_criteria_declared` / `metric_criteria_declared` — how many row-level checks vs measurements the spec produced (aggregate-scope criteria are not counted)
- `row_level_criteria` — dict keyed by criterion id (row scope).
  - Each has `type` (`code`/`llm`), `justification` (why it routed there), `reads` (fields consumed), `threshold`, `pass_count` / `n_evaluated` / `pass_rate`, `top_failure_modes`, `verifier_status`.
  - **Metric criteria** (written `kind: metric` in the spec) carry the report's marker `is_metric: true` and `pass_rate: null`;
  - a metric criterion is presented from its aggregate entry, every summary field it carries (such as `value_summary` and `values`: `values` on a `context: documents` or `prompt:` metric's `row_level_criteria` entry; `value_summary`, with `n_measured` beside it, on a `context: documents` metric only, in its `context_criteria.<id>` entry, never on the `row_level_criteria` entry; a `prompt:` or row-only metric has none yet);
  - its per-row values are in `dq_spec_eval_criteria[<id>].value` in the scored dataset and are summarized only when the user asks; never report a metric as a failure.
  - On a `context: documents` criterion the entry's `pass_count` / `n_evaluated` / `pass_rate` read 0 / 0 / null: its result is the `context_criteria.<id>` entry (`n_pass`, `pass_rate_denominator`, `pass_rate`), and the report's Checks row states both, the context result and the three row-entry fields.
- `n_field_too_long`, `n_row_too_large` — on a `row_level_criteria` or `context_criteria` entry, each present only when non-zero: rows the service set aside before any call (`field_too_long` or `row_too_large`); how each entry counts them, and the remedies: "Set aside before any call", below.
- `aggregate_criteria` — dict keyed by criterion id (aggregate scope): dataset-level checks (`value` + verdict) and dataset-level metrics (`value`; written `kind: metric`, marked `is_metric: true`). Each entry carries `value`, `verdict` (`true`/`false` on checks, `null` on metrics), `reason`, `threshold`, `inputs`, `justification` and `source`, and no `pass_rate` or `top_failure_modes`: there is no per-row tally to summarize. Empty `{}` when the spec declared none.
- `is_metric: true`, with `pass_rate: null`: the report's marker for a criterion written `kind: metric`. A spec writes `kind: metric`, never `is_metric`.
- `values`, `value_summary` — `values` on a `context: documents` or `prompt:` metric (its `row_level_criteria` entry): the declared shape; `value_summary` on a `context: documents` metric only, in its `context_criteria.<id>` entry beside `n_measured`: counts per label in the declared order, number statistics, or (no `values`) counts of numbers and texts with text length statistics.
- `n_measured` — on a measured `context: documents` criterion's `context_criteria` entry, beside `values` and `value_summary` and in place of the pass and fail counts: the number of rows the criterion measured, that is rows with a value; a row counted in `n_not_applicable` or `n_not_evaluable` is not among them. The report's Measurements header, "Summary over [n] rows", reads it as its row count.
- `n_not_applicable`, `n_not_evaluable`, `n_without_evidence` — on a `context: documents` criterion's `context_criteria.<id>` entry, check or metric.
  - `n_not_applicable` and `n_not_evaluable` are the rows the documents grading did not grade against the documents (not applicable, not evaluable); they sit outside `pass_rate_denominator`.
  - `n_without_evidence` is a count among the graded rows, inside `pass_rate_denominator`: the rows whose cited evidence was not verified against the documents (in the aggregate's own words, evidence verified means every cited passage exists in the supplied documents, not that the verdict is correct), not rows left out.
  - The report's Checks row Result cell or Measurements row Summary cell states the three beside the criterion's result as "not graded against the documents: [n_not_applicable] not applicable, [n_not_evaluable] not evaluable" and, separately, "without evidence: [n_without_evidence]", a count the entry does not carry left out, so Other aggregate fields does not repeat them; the entry's other counts (`n_fail`, `n_not_applicable_no_claim`, `n_evidence_verified`, `quote_verified`, ...) are presented there.
- `context_criteria.<id>.judge_text_source` — on each `context: documents` criterion and on `builtin_faithfulness`, where the judge text came from: `written` (a model wrote it from the description, once per job), `reused` (read from `judge_texts.json` beside the reused judge code on a `CodeArtifactS3Uri` run, rather than written again for this run), `prompt` (the `prompt:` word for word), `built_in` (the service's fixed text) or `description` (the description word for word, because the text could not be written).
- `warnings` — always present, a list of entries with a `code` and a `message` (read the message). Codes include `CONTEXT_TYPE_IGNORED` (a `type:` line on a `context: documents` or `prompt:` criterion was ignored, because the model always judges it; remove the line),
  - `FIELD_WORD_IN_DESCRIPTION` (a continuation line of a description, indented deeper than the `description:` key, begins with a lowercase field word such as `context:` or `kind:`, so it stayed description text; this is how a criterion that silently lost a deeper-indented `context: documents` line shows up, judged without the documents; write the line at the `description:` key's column if the field was meant, otherwise reword it),
  - `PASS_RATE_SWITCH_IGNORED` (the `## Pass rate includes not applicable` section is not `true` or `false` and the spec has no `context: documents` criterion, so the default `false` was kept; remove the section, or write `true` or `false`),
  - `CONTEXT_FLAG_DROPPED_NO_DOCUMENTS` (a criterion marked `context: documents` was judged without documents because none were supplied),
  - `CONTEXT_DOCUMENTS_UNUSED` (documents supplied, no criterion uses them),
  - `CONTEXT_FLAG_MISSING_SUSPECTED` (a criterion names the documents but has no `context: documents` line)
  - and `JUDGE_TEXT_NOT_WRITTEN` (a criterion's judge text could not be written, so its description was used word for word).
- `cost` — `llm_calls_made` vs `llm_calls_avoided_via_code`; `savings_pct` is the share of naive one-call-per-row-per-criterion LLM calls avoided, by code criteria or by batching
- `code_version_hash` — identifies the judge code that ran; two runs sharing it give the same `code` verdicts at the same thresholds, while `llm` criteria can still differ
- `codegen_attempts` — `0` on a `CodeArtifactS3Uri` run (no code was generated); 1–3 otherwise
- `verifier_integrity.all_criteria_covered` — if `false`, some criteria couldn't be implemented (`verifiers_missing` / `verifiers_errored` name them); the job still completed but results are incomplete; the report's Coverage line prints both lists as JSON (`[]` when empty)

A criterion failing on rows never fails the job: those rows carry `dq_spec_eval_pass: false` and the job reports `Completed`. Neither do criteria the generated code could not implement (`verifier_integrity.all_criteria_covered: false`). The job fails for its inputs, never for a row's verdict: an unreadable spec, a structured spec that does not parse (or a prose spec no criteria could be derived from), duplicate `id` / `identifier` values among the evaluated rows, an empty dataset, evaluation code that could not be generated at all, or a documents folder the job cannot use (`CONTEXT_REQUIRED_NO_DOCUMENTS`, `CONTEXT_DOCUMENT_UNREADABLE`, `CONTEXT_DOCUMENTS_TOO_LARGE`; `dataset-service-api.md` § Spec-driven evaluation names each).

### Set aside before any call

Two cases the service decides before any model call, on a check or a metric alike. The criterion's `dq_spec_eval_criteria` entry carries `skip` with one of the two kinds, and its `reason` says why. A set-aside criterion is neither a success nor an error. This section is the one statement of the two kinds, their limits, how the report counts them and the remedies; `result-interpretation.md` and `report-template.md` point here.

- `field_too_long` — a field the criterion reads is over 12,000 characters; the `reason` names the field and its length.
- `row_too_large` — the request did not fit the model allowance; the `reason` gives the request's size and the allowance.

The `reason` carries the limit in force.

How a set-aside row is reported:

- In the scored dataset: the row is graded in the order above, so it is `null` unless another check failed; the criterion is not listed in `dq_spec_eval_errored_criteria`.
- In the aggregate report: the rows are counted per criterion as `n_field_too_long` and `n_row_too_large`, each present only when non-zero. On a `row_level_criteria` entry the two counts stand on their own, in neither `success_count` nor `error_count` (such an entry has no `n_not_evaluable` field); on a `context_criteria` entry they are counted inside `n_not_evaluable`. Either way a set-aside row is neither a success nor an error.

The remedy, as applicable: shorten the named field, split the row, or narrow the criterion's `reads:` to the fields it needs.

## Exploratory Analysis Output

When an `exploratory_analysis` operation ran, `quality_report.json` holds the agent's findings under `exploratory_analysis`, ranked most consequential first:

```json
"exploratory_analysis": [
  {"result": {"findings": [
    {"title": "Target leakage via created_at timestamp", "evidence": "created_at perfectly separates the classes (AUC=1.0 on a 500-row probe)"},
    {"title": "Label noise in sentiment column", "evidence": "103 rows have text contradicting the label, e.g. 'great product' labeled negative"}
  ]}}
]
```

The same array is in `aggregate/exploratory/findings.json`, which `metadata.json` lists under `Reports.Aggregate`, after `quality_report.json`. The findings contribute nothing to the `dq_` columns. They are descriptive: they report what the agent found, not how to fix it, and each `evidence` carries the values, row counts or statistics behind its finding.

A job whose only operation was `exploratory_analysis` writes no `evaluated_data.jsonl` and no `token_usage_report.json`, and its `quality_report.json` holds only `exploratory_analysis`. Its `metadata.json` carries `DatasetArn`, `JobArn`, `EvaluationConfig`, `CreatedAt` and `Reports.Aggregate`, which lists `quality_report.json` first and the findings file second: `EvaluationConfig` is the stored request config, which also carries the service's `EvaluationConfigSchemaVersion`; `CreatedAt` is the job's creation time, to the second; `Reports.Aggregate` holds the `quality_report.json` and `findings.json` URIs. There is no `Reports.RecordLevel`.

A job with `exploratory_analysis` **fails** when the analysis writes no findings: a missing `findings.json`, or one that is not a non-empty JSON array (an empty file, `[]`, an object), ends the job `Failed`, whatever else the job ran, and a failed job has no `MetadataS3Uri`. The `FailureReason` is `INTERNAL_ERROR`, unless another part of the job failed first and its reason stands. Match `Reports` entries by file name, not position.

## metadata.json

`DatasetArn`, `JobArn`, `EvaluationConfig` (the request's `{"Operations": [...]}`, echoed as sent), `CreatedAt`, and `Reports` (`Aggregate`, `RecordLevel`, and `SpecEval` on spec runs). There is no `EvaluationName`. `metadata.json` records the spec or code **URI, not the document's contents**: for `SpecS3Uri` the user's S3 object remains the only record of what was evaluated against. On an exploratory-only job, see [Exploratory Analysis Output](#exploratory-analysis-output).

## Interpreting Results

The healthy and notable range of each deterministic metric, and where spec-driven pass rates are read, are `result-interpretation.md`, one check per metric (the deterministic checks first, then "Spec-driven evaluation checks").
