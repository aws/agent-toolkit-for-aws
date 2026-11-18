# Result Interpretation — Taxonomy

Apply these checks per framing and include any triggered flags in the report. They are
**descriptive**: the report says what the data contains; the user decides what to do about it.

## Coverage against the use case

If a use case specification or stated goal exists, compare the L1 and L2 categories with the areas
the user said the data should cover.

- An expected area with no matching category: "🚨 No rows cover [area], which the use case calls
  for."
- An expected area covered by fewer than 5% of rows: "⚠️ Only [X]% of rows cover [area]."
- Unexpected large categories: "ℹ️ [X]% of rows are [category], which the use case does not
  mention."

## Balance

- One L1 category with more than 60% of rows: "⚠️ The dataset is dominated by [category] ([X]%)."
- Many leaves with under 1% of rows each: informational; note the long tail and how many rows it
  holds in total.

## Confidence

`low_confidence_count` counts rows whose margin is below 0.1, meaning the assigned category and the
nearest other category were almost equally close.

- Low-confidence share above 20%: "⚠️ [X]% of rows sit near a category boundary; neighbouring
  categories may overlap or the framing may not fit this data well."
- Above 40%: "🚨 Most rows are ambiguous under this framing; treat the tree as indicative only."

## Integrity

`output_count` must equal `input_count`, `excluded_count` should be 0, and `count_anomaly` should be
false. Anything else: "🚨 Row accounting disagrees; treat this run as suspect and rerun." A
completed job should not show this.

## Presenting the tree

Show L1 categories largest first with row counts and percentages, then the largest L2 and L3
children under each, trimmed to what fits in a reply (about eight L1 branches and five children per
node). Point to the HTML report for the full tree. State once that category names are generated for
this run and will read differently on another run.

## Drilling into rows

- **Rows in a category:** filter `dq_taxonomy_<framing>_<level>__<column>` equal to the label; show
  at most 20 rows with the bound text truncated to about 120 characters, and report the total.
- **Low-confidence rows:** filter `dq_taxonomy_<framing>_margin__<column>` below 0.1, sort ascending,
  show at most 20 with their assigned L3 and margin.

Both, like the tree rendering above, are implemented in `../scripts/taxonomy_summary.py` and are built on
request: the script streams the row-level object from S3 line by line and never downloads it (the
user's data, which can be gigabytes), so it is run only when the user asks for a tree or for rows, never for the written report, which carries the aggregate's counts and
the HTML report path. Never load the whole scored file into the conversation; the rows never enter it.

## Where the findings route

- Thin or missing areas → synthetic-dataset-generation, with the missing categories as the gap
  context.
- Filtering, splitting, or rebalancing by category → dataset-transformation, using the row columns
  of this run as the filter fields.
- Quality of one category → dataset-quality on the filtered subset.
