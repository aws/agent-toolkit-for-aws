# Drilling Into Row-Level Records

Read this page when the user accepts the drill-down offer of `results-and-report.md` or asks for specific records. The results page and the report read the aggregate files only; this page is the one that reads the row-level file.

When the user asks to see specific records (e.g., "show me completions under 20 words", "which records are toxic?", "show the lowest-scoring records"), follow this procedure:

The row-level file, the `Reports.RecordLevel` URI in the job's `metadata.json` (`record_level/evaluated_data.jsonl`), holds the user's whole dataset plus the score columns and can be gigabytes, so the agent reads only what the question needs (`results-and-report.md`'s rule: "sample or filter, never load the full file"): stream the object line by line, keep only the rows the question matches, stop after the first 20 matching rows (a predicate question) or keep the 20 extreme rows over one pass (a ranking question; both below), and keep only the columns the question names (the text columns and the score columns it asks about). Never `aws s3 cp` the whole file to disk and never read a local copy with pandas.

The question has one of two shapes, and the read differs. A predicate question ("completions under 20 words", "records that failed criterion X") names a condition: keep the first 20 matching rows in file order and stop reading, as the script's `--where` mode does. A ranking question ("the 20 lowest-scoring records", "the worst completions") names an extreme, not a condition: the first 20 rows in file order are arbitrary, so the read goes over the whole stream once and keeps a bounded set of the 20 extreme rows (`heapq.nsmallest` for the lowest, `heapq.nlargest` for the highest, with a key on the score column and `CAP` as n); at most 20 rows are in memory at any moment and the file is never held whole.

**Check the size first, once the user has asked for rows.** Before either form below, run `aws s3api head-object --bucket <bucket> --key <key>` on the `Reports.RecordLevel` object named in `metadata.json` and read `ContentLength` (the same check `report-visualization.md` makes before per-record charts). Then say one of these two sentences, with the size filled in:

- Under 50 MB: "Your row-level file is {size} MB; since it's under 50 MB, I'd recommend streaming it from S3 for this question. Would you like to proceed with the streamed read, or would you prefer a sampled read instead?"
- 50 MB or over: "Your row-level file is {size} MB; since it's over 50 MB, I'd recommend not streaming the whole file. A question with a condition can run as the drill-down script's filter, which stops reading after the first 20 matching rows; a ranking question or a measurement summary can run as a sampled read (the first 20 rows of the file, whatever their values, presented as a sample, never as the extremes of the file) or as a new job that computes the number. Which would you prefer?"

Do not execute until the user approves. If the user rejects the recommendation, switch to the alternative and get their explicit approval before proceeding. The sampled read is the script's `--sample <score column> --cap 20` form: the first 20 rows of the file in file order, whatever their values, then stop. It is never a `--where` filter such as `'>=' 0`, which a label column, a negative score or a mostly empty column never matches, so the read would go on through the whole file the user declined. The new job is `results-and-report.md` item 4, "A number the job did not produce".

1. **Filter the scored dataset where it sits** — `<bucket>` and `<key>` are the `record_level/evaluated_data.jsonl` path from `metadata.json` `Reports`. Two forms; pick one:

   **Streamed read** (boto3; works in every account): read the object line by line, keep the matching rows, stop at the cap. When boto3 is not installed the script streams the object through `aws s3 cp <URI> -` instead — the CLI's stdout, piped, nothing on disk, the same stop at the cap (the copy is ended with the read) — and says which transport it used on stderr. The script's stdout is read in the shell and never redirected to a file in the project folder or anywhere else. Example, a predicate question: "completions under 20 words":

```bash
python3 scripts/drill_down_rows.py --metadata <MetadataS3Uri> \
  --where dq_word_count__completion '<' 20 --cap 20
# or name the object: --bucket <bucket> --key <key> in place of --metadata
```

   In this mode the script streams the object line by line, keeps the first `--cap` matching rows in file order (the `--columns` text columns and the named column) and stops reading at the cap; the rest of the file stays on S3. `--metadata` is the job's `MetadataS3Uri` (the script reads `Reports.RecordLevel[0]` from it); `OP` is one of `<`, `<=`, `>`, `>=`, `==`, `!=`.

   **Streamed read, ranking question**: one pass over the whole stream; `heapq.nsmallest` (or `heapq.nlargest` for the highest) keeps a bounded set of the 20 extreme rows seen so far and drops the rest as the stream goes by, so the file is never held in memory. There is no early stop: the lowest row may be the last one. Example: "the 20 lowest-scoring completions on word count":

```bash
python3 scripts/drill_down_rows.py --metadata <MetadataS3Uri> \
  --lowest dq_word_count__completion --cap 20
# --highest COLUMN for the highest-scoring rows
```

   In this mode the script goes once over the whole stream and keeps a bounded set of `--cap` rows with `heapq` (the lowest or the highest on the named column), skipping unscored rows and rows whose value is not a number (one stderr line after `Kept` counts the latter); the kept rows come out sorted by the metric, worst first, and its `Kept N rows` line says they are of the whole file. The column of `--lowest`, `--highest` and `--where` is a flat column name or a dotted path into a nested object: `dq_spec_eval_criteria.<id>.value` names a spec metric's per-row value (`--lowest dq_spec_eval_criteria.completion_word_count.value`); a row without the path, or with `null` there, is unscored, and the kept row carries the value under the dotted path as its key.

   When the score the user ranks by is not in the file (a label-only metric such as `toxicity`, which writes `dq_toxicity_label__<column>` and no score column; `output-schema.md`), say so and offer the route: a new spec job whose spec states that question as a measurement criterion (`results-and-report.md` item 4, "A number the job did not produce"); never rank by a column the file does not carry.

2. **Present results** — show the kept records (limit to 10-20 rows). Include the prompt, completion, and the relevant score column(s). The script prints a text column the job's `pii_detection` flagged on that row as `[REDACTED: PII]`, and a `dq_input__` column (`dq_input__prompt`, `dq_input__completion`: text the service derived from a source column such as `messages`) prints as `[REDACTED: PII]` when any column of that row is flagged; never show such text another way.

3. **Handle column name matching** — output columns are `dq_<metric>__<column>` (e.g., `dq_word_count__answer`, or `dq_word_count__dq_input__completion` for a run without a View). When the user says "word count", match against columns containing that metric name.

**Drilling into spec-driven results:**

To summarize a metric criterion's values (measurements):

Run this only when the user asks for a measurement summary, never for the report, and after the size check above (`aws s3api head-object` on the row-level object and the sentence for its size; 50 MB or over, offer the sampled read or a new job in place of the whole-file pass): `scripts/stream_measurements.py --metadata <MetadataS3Uri>` prints the summary (count, min, mean, max for numbers; label counts for labels, per criterion) by reading the whole row-level file through the client, line by line from S3; it makes no local copy; when boto3 is not installed it streams the file through `aws s3 cp <URI> -` instead — the CLI's stdout, piped, nothing on disk — and says which transport it used on stderr. There is no pandas pass over a local copy.

To find records that failed specific spec criteria, stream with the same cap:

```bash
python3 scripts/drill_down_rows.py --metadata <MetadataS3Uri> --failed completion_min_length
# --failed alone: rows that failed any criterion, each with its failed ids and their reasons
```

In this mode the script keeps the rows whose `dq_spec_eval_pass` is `false` (never `null`) and, with a criterion, only those naming it in `dq_spec_eval_failed_criteria`, and stops at the cap. Each kept row carries which check failed and why, by default: its `dq_spec_eval_failed_criteria` list and a `failed` object `{id: reason, ...}` with each failed criterion's `reason` from `dq_spec_eval_criteria[<id>]`; with a criterion, also that criterion's `reason`. A failed `context: documents` criterion also brings its `evidence`, `quote` and `support` from the same entry (the keys the entry has) in a `context` object `{id: {evidence, quote, support}, ...}` beside `failed`; with a criterion, that criterion's fields appear at the top level beside `reason` too. The output already says which check failed, the judge's reason and the passage it cited, so no second read of the file is needed for them.

**The row keys to filter on** (the spec columns of `output-schema.md` "Row-level columns (spec-driven)"; the fourth, `dq_spec_eval_errored_criteria`, lists the ids that could not be evaluated for the row):

- `dq_spec_eval_pass` — `true` / `false` / `null` for the row (`null`: not evaluated).
- `dq_spec_eval_failed_criteria` — the list of ids of the checks the row failed; the key a "failed criterion X" question filters on.
- `dq_spec_eval_criteria[<id>].outcome` — a `context: documents` criterion's grade: `pass` / `fail` / `not_applicable` / `not_evaluable` (`measured` on a documents metric). A documents entry has no `verdict`; a filter on `verdict` matches no documents row.
- `dq_spec_eval_criteria[<id>].verdict` — a row check's grade, `true` / `false` (`null` on a metric); `dq_spec_eval_criteria[<id>].reason` — the judge's sentence, on every entry.

Example, "which rows failed `ratings_exist`?": `--failed ratings_exist` above keeps the rows whose `dq_spec_eval_failed_criteria` names it. A filter written by hand tests the same key, `"ratings_exist" in (row.get("dq_spec_eval_failed_criteria") or [])`, or the criterion's own grade, `row["dq_spec_eval_criteria"]["ratings_exist"].get("outcome") == "fail"`; it never tests `verdict` on a documents criterion.

Remember: `dq_spec_eval_pass = null` rows were not evaluated — leave them out when counting the rows a question matches (`row.get("dq_spec_eval_pass") is None` skips them). Every pass rate comes from `quality_report.json`, not from a pass over the rows; a pass rate recomputed from the rows is a number the job did not produce and is never stated (`results-and-report.md` item 4).

**Important constraints:**

- Never load the full file into chat context or onto disk. Stream or filter as above and only show the relevant subset.
- Always show at most **20 rows** initially, sorted by the metric, worst first. For a ranking question the 20 kept are the 20 worst of the whole file; for a predicate question they are the worst among the rows kept, which are the first 20 that matched in file order. Report the number of matching records when it is known (a streamed read that stopped at the cap says "at least 20").
- If the cap was reached on a predicate question, tell the user: "At least 20 records match your criteria. Here are the 20 kept, worst first:" and ask whether to narrow the condition or to see more. A ranking question has no cap to reach: its 20 rows are the 20 extreme rows of the whole file; say so.
- The file stays on S3: read it there with one of the two forms above. The record drill-down never downloads the file whole, even when the user asks for "all" matching rows; narrow the condition or page through the cap instead. The taxonomy tree tool (`taxonomy/scripts/taxonomy_summary.py`), run only when the user asks for the trees, streams the row-level object from S3 in the same way and is described in `taxonomy/overview.md` Step 8.

## Spec-Driven Evaluation

Read per-criterion pass rates and failure modes from `spec_eval[0].result` (see `output-schema.md`, "Spec-Driven Evaluation Output"). The healthy and notable range of each deterministic metric is on `result-interpretation.md`, one check per metric.

When the rows that failed one criterion fall into two kinds, do not offer a reworded criterion or a re-run unprompted. Only when the user asks for the narrower count (or asks to drop one kind), offer to reword the criterion to that kind and to add the other as a separate criterion for a re-run; never advise dropping a quality the user named (`spec-authoring.md`, "One criterion per quality"). The job did not compute a pass rate for the narrower reading; only a new job does. A row answer ends with at most one question.

<!-- markdownlint-disable-file MD029 -->
