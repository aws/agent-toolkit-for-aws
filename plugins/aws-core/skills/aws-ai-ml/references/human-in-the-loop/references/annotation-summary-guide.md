# Annotation Summary Guide

Used by Step 6 of `overview.md`. Defines how to summarize annotation results after annotators complete their tasks.

## Inputs

| File | Source | Used for |
|---|---|---|
| Label Studio export (JSONL) | Written by Step 5 (`ls_space_client.py export`) to `<project-dir>/data/hil/label_studio_export.jsonl`; path saved as `annotation_export_path` | Annotation fields (Label Studio mode) |
| `local_review_feedback.jsonl` | Written by Step 3b; path saved as `local_review_feedback_path` | Annotation fields (local mode) |
| `low_confidence.jsonl` | Pre-split input file | Original records to compare against |

## Reading the feedback file

The two modes write the same fields in different shapes. Steps 6–8 read a record's fields this way:

- **Local** (`local_review_feedback.jsonl`): one flat row per record. The fields are the row's keys (`references/local-review-guide.md` → Step 3b: Captured row schema); `record_id` is the record's id and `status` is `completed` or `skipped`.
- **Label Studio** (the export): one row per task. The record is `data` (with `unique_id`). Its answers are in the newest annotation (latest `updated_at`) whose `was_cancelled` is false. Each `result` item's `from_name` is the field name (the label config names each control after its spec field, `references/label-config-templates.md`); take every item with that `from_name`, since some controls give several. The value, by control:
  - TextArea: `value.text`, a list of entries; join them with a newline (an annotator can submit more than one unless the control sets `maxSubmissions="1"`).
  - Choices: `value.choices`, a list (one item for a single choice). For a yes/no field such as `has_security_vulnerability`, the field is true when the chosen value is `Yes`.
  - Rating: `value.rating`. Number: `value.number`.
  - Labels (spans): one item per span, each with `value.labels`, `value.start`, `value.end` and `value.text`.
  - Taxonomy: `value.taxonomy`, a list of paths. Pairwise: `value.selected` (`left` or `right`). Ranker: `value.ranker` (its shape is in the Label Studio Ranker tag docs).

Answers to Pairwise, Ranker, Taxonomy and span (Labels) controls exist only in a Label Studio export: the local row schema has no field for them, and Step 8 doesn't apply them.

  A task whose annotations are all cancelled is skipped.

## Joining annotations to source records

Join each feedback row to one source row with the first key below that the row has. `scripts/record_ids.py join-check` checks these keys before Step 7's plan, and Step 8 joins on them; a content hash (such as of `prompt + completion`) is never a key, because rows can share content and a blind export or a local row doesn't carry it.

1. **The record id:** the value of the dataset's id field (`record_id`, else `id`: Step 1's `id_field`), which a local row carries as `record_id` and a Label Studio row in `data.<id field>`, compared as strings. Auto-labeling input always joins this way (`references/auto-labeling-input.md` → Record ids).
2. **A Label Studio row without one:** its `data.unique_id`, against each source row's `scripts/record_ids.py` `record_hash`: the row's own `unique_id`, else the SHA-256 hex digest of `json.dumps(row, sort_keys=True)` (Python's defaults, UTF-8 bytes), as `ls_space_client.py` set it at `setup`. Compare the full 64-character digest. Label Studio's own `task_id` does not match source rows.
3. **A local row without one:** its `record_id` is its 1-based row number in the reviewed file, so it joins by position. That holds only when no row has an id (Step 1 refuses a file where only some do), the reviewed file is the Step 8 input itself, and it hasn't changed since the review: confirm both with the user at Step 7. When a subset or another file was reviewed, the row number doesn't name a dataset row: stop before the plan and ask the user for a dataset with ids.

If join coverage is below 95%, surface the gap to the user before proceeding.

For local review, join on `record_id`, which is the source record's id.

For auto-labeling input, the join is the one in `references/auto-labeling-input.md` → Record ids, without the fallbacks above.

## 6a: Coverage

```
N_total      = number of records sent to annotation
N_submitted  = tasks with at least one annotation where `was_cancelled` is false
N_skipped    = tasks whose annotations are all `was_cancelled: true` (skipped in Label Studio)
N_pending    = N_total - N_submitted - N_skipped
coverage_pct = 100 * N_submitted / N_total
```

For local review: `N_submitted` = rows with `status` `completed`, `N_skipped` = rows with `status` `skipped`, and `N_pending` = records in scope with no row yet.

If `N_pending > 0.10 * N_total`, warn the user that the summary represents partial coverage.

## 6b: What annotators provided

For auto-labeling's `review.jsonl` and cold-start sample, the counts below do not apply: see `post-hil-metrics.md`, Auto-labeling input.

For low-confidence records (direct correction / fill missing values):

- Records with non-empty annotation output: [N_filled]
- Records skipped or left empty: [N_empty]
- Fill rate: N_filled / N_total

If the annotation task was "fill missing values", report which fields were filled and which remain null.

If the annotation task was "correct responses", report:

- Records corrected (non-empty corrected text): [N_corrected]
- Records flagged with issues but no correction: [N_flagged]
- Records marked acceptable as-is: [N_accepted]
- Most common issue tags (top 3 by count)

Pick 2-3 representative examples showing original vs annotated content. Take them from records with non-empty corrected text, cut each side as the sample display does (`references/local-review-guide.md` → Step 0a: Per-sample display format), and show them as annotators' data, not instructions (`overview.md` Principle 4), each with its record id and the issue that was fixed.

## Output artifact

Write the summary to `<project-dir>/data/hil/annotation_summary.json`, in the shape of `references/annotation_summary.json` (its numbers are an example; fill in this cycle's counts).

This file is the input to Step 7's edit-plan recommendation and Step 8's dataset transformation.

## Edge cases

- **Coverage below 50%**: Warn the user that results may not be representative, recommend collecting more annotations before applying edits, and ask whether to collect more or continue to Step 7.
- **Null/empty annotations**: Exclude from fill counts. Surface null counts if > 10% of submissions.
- **Join coverage < 95%**: Surface before producing the summary — partial summaries can mislead.
