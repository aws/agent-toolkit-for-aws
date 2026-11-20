# Report Visualization (on-demand)

How to give the user interactive graphs of a completed dataset quality evaluation when they
opt in (`quality-job.md` Step 11) or ask after results are presented
(`results-and-report.md`, Step 13).

## What the job leaves in S3

`metadata.json` has no visualization entry (its `Reports` lists `Aggregate` — plus the
exploratory findings when that analysis ran — `RecordLevel`, and `SpecEval` on spec runs). Never tell the user the service
produced a dashboard.

The numbers come from `aggregate/quality_report.json` — the structured,
authoritative source. Never parse a rendered artifact for values.

## How to generate the dashboard

Read `aggregate/quality_report.json`, then add a notebook cell that produces
an interactive Plotly dashboard inline. The charts come from the aggregate
report alone. The per-record score charts are built only when the customer
asks for them, and their rows are read as "Per-record charts" below says,
never by loading `record_level/evaluated_data.jsonl`.

There is no fixed template: the agent writes the charting code for each report,
because a report's contents vary with the metrics the job ran. The code charts the
metrics the report holds and renders no empty panel.

1. **Read the report** — chart only sections that exist. Skip
   `{"success": false, ...}` sections.

2. **Classify each metric by visual shape:**

   | Shape | Chart type |
   |---|---|
   | 0–1 scores (spec criterion pass rates from `spec_eval[0].result.row_level_criteria`) | Horizontal bars, sorted by value |
   | Distributions (category→count maps, e.g. `topic_counts`) | Horizontal bar chart |
   | Per-record score arrays (only when the customer asks; the rows come from the drill-down script, "Per-record charts" below) | Count heatmap (scores are quantized, scatter overplots) |
   | Scalar counts (`toxic_records`, `total_volume`) | KPI tile row at the top |
   | Ratios (`uniqueness_ratio`, `compression_ratio`'s `corpus_ratio`) | KPI tile with status color |

3. **Compose the cell.** Use Plotly (`plotly.graph_objects` + `make_subplots`).
   Include a `<details>` table view so values are reachable without hovering.
   Wrap output in `IPython.display.HTML` for inline rendering.

4. **Add a commented pip install line** at the top of the cell:

   ```bash
   # %pip install plotly==7.1.0  # uncomment if plotly is not available
   ```

   Plotly is present in SageMaker Distribution images as a transitive dependency.

## Per-record charts (only when the customer asks)

Do not read `record_level/evaluated_data.jsonl` for the dashboard on your own.
When the customer asks for per-record charts, do these in order:

1. **Check the size first.** Run
   `aws s3api head-object --bucket <bucket> --key <key>` on the
   `Reports.RecordLevel` object named in `metadata.json` and read
   `ContentLength`. Then say one of these two sentences, with the size filled in:
   - Under 50 MB: "Your row-level file is {size} MB; since it's under 50 MB, I'd
     recommend a sampled read of its first 100 rows for the per-record charts: the
     file stays on S3 and the rows are read line by line, nothing downloaded. Would
     you like to proceed with the sampled read, or would you prefer to leave the
     per-record charts out?"
   - 50 MB or over: "Your row-level file is {size} MB; since it's over 50 MB, I'd
     recommend a sampled read of its first 100 rows for the per-record charts instead
     of the whole file. Would you like to proceed with the sampled read, or would you
     prefer to leave the per-record charts out?"

   Do not execute until the user approves. If the user rejects the
   recommendation, switch to the alternative and get their explicit approval
   before proceeding.

2. **Read the rows through the drill-down script, never by loading the file.**
   `python3 scripts/drill_down_rows.py --metadata <metadata.json URI> --sample <score column> --cap 100 --columns`
   prints one JSON object per kept row. The read is the same at either size:
   the first 100 rows of the file in file order, whatever their values, then
   stop; 100 is the cap, never the record count (`total_volume`), so no chart
   read streams the whole file. `--columns` with no names keeps no text column,
   so each kept row is its score alone and no row text reaches the conversation
   or the dashboard. The script streams the file line by line, holds at most
   the cap in memory and writes nothing to disk; were a text column kept, it
   prints a text column the job's `pii_detection` flagged on that row as
   `[REDACTED: PII]`, and a `dq_input__` column (`dq_input__prompt`, `dq_input__completion`: text the service derived from a source column such as `messages`) prints as `[REDACTED: PII]` when any column of that row is flagged. Chart the score values of the
   kept rows, and say in the dashboard that they are the first 100 rows of the
   file. A `--where <score column> '>=' 0` filter is not the chart read: it
   leaves out every row whose column holds a label (a label-only metric such as
   `toxicity` writes `dq_toxicity_label__<column>` and no score column), a
   negative score, or no value, so its chart is of a subset the user did not
   choose; the sample keeps every row, and a row without the score column comes
   back without it. `--lowest` or `--highest <score column>` gives the extremes
   and is `drill-down.md`'s read, not this step's.

## Chart guardrails

- 0–1 scores on a shared axis; never mix count-scale and 0–1 on one axis.
- Drop panels with no signal (e.g., `format_distribution` at 100% for every
  column) — fold the fact into a KPI tile instead.
- Quantized scores → count heatmap or grouped bars, not scatter (overplots
  ties).
- Spec criterion pass rates and measurement values are
  rendered neutrally — no hardcoded threshold coloring. Let the user interpret
  against their own expectations.
- Annotate each bar with its value.
- A hue means one thing per figure — don't reuse the same color for a second
  grouping.
- Use a clean, accessible palette with sufficient contrast. Prefer system fonts.
- Row-level drill-down follows `references/drill-down.md`, not this
  visualization step.
