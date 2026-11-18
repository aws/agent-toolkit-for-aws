# Taxonomy Operator — `taxonomy`

A dataset-global operator of the dataset quality evaluation job. It binds one
text operand (Role `Text`), sees the whole dataset at once, and produces one three-level category
tree per requested framing plus per-row assignments. It is not a per-record judge, but it does call
foundation models through Bedrock and its labels are not identical between runs.

## Wire format

```json
{"Operations": [
  {"Operator": "taxonomy", "Config": {"View": [{"Role": "Text", "Column": "prompt"}], "framings": ["task"]}}
]}
```

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `framings` | array of unique strings from `task`, `domain`, `quality`; at least one | all three | Which trees to discover. Each framing is a full pass over the corpus. |

- The parameter name is lowercase `framings`; unknown keys are rejected.
- Columnar formats: bind one column with `View`. Recognized nested formats: omit only the `View`
  binding and keep `Config` for `framings`; the operator then runs on the derived
  prompt and completion (two passes, row columns suffixed `dq_input__prompt` and
  `dq_input__completion`; one pass on the prompt for Nova_CPT and Verl). Without a View the same
  holds on any recognized format.
- Submission details (schema pin, output location, BYOD import) are in
  `../../dataset-service-api.md`.

## What a framing produces

| Framing | The tree groups rows by | Example L1 labels |
|---|---|---|
| `task` | what the row asks the model to do | "Reasoning & Logic", "Code Generation", "Summarization" |
| `domain` | the subject area of the content | "Finance", "Healthcare", "Software Engineering" |
| `quality` | quality-related traits of the text | "Well-specified requests", "Ambiguous or underspecified" |

Per framing the operator embeds every row with a Nova embedding model, clusters the embeddings,
asks a foundation model to name a
three-level hierarchy over the clusters, and assigns every row to a leaf. Category names are
generated, so they differ in wording between runs and between datasets; treat them as observations
about this dataset rather than a stable schema.

## Constraints

| Constraint | Detail |
|---|---|
| Region | **us-east-1 only.** The embedding model is served there and nowhere else; jobs in other regions fail. |
| Minimum rows | 10 rows after binding. Fewer rows fail before any model call. |
| Text length | Every bound value must be at most 49,000 characters. Oversized rows fail the job before any model call, with the first offending row index in the message. |
| Text values | Every bound value must be a non-empty string. |
| Cost | One embedding call per row per framing plus a bounded number of labeling calls per framing, billed through Bedrock. Two framings cost twice one; a nested-format binding doubles it again. |
| Row count | Rows are never dropped or reordered: `output_count` equals `input_count`, and the classified row set round-trips the input exactly. |

## Aggregate result

`aggregate/quality_report.json` has a `taxonomy` key holding a list of runs (one per bound column).
Each run's `result` contains:

| Field | Meaning |
|---|---|
| `input_count`, `output_count` | Rows in and rows returned; always equal (no rows dropped). The classified tally is `classified_count` per framing |
| `excluded_count` | Rows the operator excluded; expected 0 |
| `count_anomaly` | True if any phase count disagreed; expected false |
| `framings` | Object keyed by the framings that ran, each with `l1_count`, `l2_count`, `l3_count`, `classified_count`, `low_confidence_count` |
| `phase_drops`, `phase_drop_reasons` | Per-phase drop bookkeeping; empty or zero in a healthy run |
| `provenance` | Run parameters and model identifiers used |
| `taxonomy_run_id` | Run-unique id correlating the per-framing runs, the report, and the row columns |
| `taxonomy_report_path` | S3 URI of the combined HTML report (`taxonomy_report.html`) staged under the job output |

Example, one framing over 12 rows:

```json
{"taxonomy": [{"view": {"Text": "prompt"}, "params": {"framings": ["task"]}, "result": {
  "input_count": 12, "output_count": 12, "excluded_count": 0, "count_anomaly": false,
  "framings": {"task": {"l1_count": 2, "l2_count": 3, "l3_count": 4, "classified_count": 12,
                        "low_confidence_count": 3}},
  "taxonomy_run_id": "3f9c...", "taxonomy_report_path": "s3://bucket/prefix/.../taxonomy_report.html"}}]}
```

## Row columns

For each requested framing, four columns named `dq_taxonomy_<framing>_<field>__<column>` are added
to every row of `record_level/evaluated_data.jsonl`, where `<column>` is the bound column lowercased
with each run of characters other than letters and digits replaced by `_` and any leading or trailing `_` dropped (without a View the
suffix is `dq_input__prompt` or `dq_input__completion`). Framings that were not requested add no columns.

| Field | Type | Meaning |
|---|---|---|
| `l1` | string | Broadest category assigned to the row |
| `l2` | string | Mid-level subcategory |
| `l3` | string | Leaf category |
| `margin` | number | Confidence margin: `(distance to nearest other category - distance to assigned category) / distance to assigned category`. Below `0.1` the row counts as low-confidence. |

Example for the `task` framing bound to `prompt`: `dq_taxonomy_task_l1__prompt`,
`dq_taxonomy_task_l2__prompt`, `dq_taxonomy_task_l3__prompt`, `dq_taxonomy_task_margin__prompt`.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Job fails immediately with a framings validation message | Unknown, repeated, or empty `framings` | Use a non-empty list of unique values from `task`, `domain`, `quality` |
| "requires at least 10 rows for clustering" | Corpus too small after binding | Add rows or choose a larger dataset |
| "rows exceed the 49,000-character embedding limit" | Oversized text values | Truncate or split those rows with dataset-transformation, then resubmit |
| Embedding calls fail with a model-not-found or access error | Job ran outside us-east-1, or the account lacks access to the Nova embedding model | Run in us-east-1; request Bedrock model access in the job's account |
| `View binds Column ... not present` | Explicit View on a recognized nested format, or a misspelled column | Omit only `View` for nested formats and keep `Config` with `framings`; fix the column name |
