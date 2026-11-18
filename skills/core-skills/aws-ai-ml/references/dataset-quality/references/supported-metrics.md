# Supported Dataset Quality Metrics

Each metric is one `Operations` entry (`dataset-service-api.md`). This file is the home of each
metric's View **Role**: every View entry is `{"Role": "<role>", "Column": "<column>"}`, with the
Role named in the section heading. Role names are case-sensitive.

## Deterministic Metrics

### Text Metrics (Role `Text`, one column)

| Metric | Output | What it measures | Params |
|---|---|---|---|
| word_count | both | Word count per record + aggregate min/max/mean | — |
| character_count | both | Character count per record + aggregate min/max/mean | — |
| compression_ratio | both | Gzip compressibility per record + corpus ratio | — |
| uniqueness | aggregate | Ratio of unique records to total records | `CaseSensitive` (bool, default true) |
| ngram_diversity | aggregate | Ratio of unique n-grams to total n-grams | `N` (1-8, default 1) |
| mif_score | aggregate or both | Lexical rarity score (Wikipedia word frequency) | mode (corpus/per_row, default corpus) |
| toxicity | both | Per-row toxic/not_toxic label + aggregate count | — |
| plain_text_ratio | aggregate | Percentage of rows classified as prose_only | — |
| format_distribution | aggregate | Percentage breakdown of format types | — |
| content_structures | row-level | Detected format types per record (prose, code, list, etc.) | — |

### Topic Metrics (Role `Text`, one column)

| Metric | Output | What it measures | Params |
|---|---|---|---|
| keyword_topic_counts | aggregate | Per-topic record counts via keyword matching | topic_keywords (map), default_topic (string) |
| keyword_topic_coverage | aggregate | Count of distinct topics detected | topic_keywords (map), default_topic (string) |

### Tabular/Categorical Metrics (Role `Label`, one or more columns)

Bind with `{"View": [{"Role": "Label", "Column": "col1"}, {"Role": "Label", "Column": "col2"}]}` — one run covers every bound column.

| Metric | Output | What it measures | Params |
|---|---|---|---|
| data_balance | aggregate | Overall balance score across bound categorical columns | — |
| data_balance_ratio | aggregate | Worst min/max count ratio across all bound columns | — |
| field_balance | aggregate | Per-field normalized Shannon entropy (1.0 = uniform) | — |
| field_balance_ratio | aggregate | Per-field min/max count ratio | — |

### Column Metrics (Role `Column`, one or more columns)

Bind many columns to a **single** run, one `{"Role": "Column", "Column": "<col>"}` entry each — the aggregate comes back keyed per column. Do NOT fan out into one metric entry per column; that is only for `Text` role metrics.

Columns declared `NUMERIC` must hold usable ints or finite floats; `CATEGORICAL` accepts any value type.

| Metric | Column type | Output | What it measures | Params |
|---|---|---|---|---|
| mean | NUMERIC | aggregate | Arithmetic mean, per column | — |
| median | NUMERIC | aggregate | Median, per column | — |
| min | NUMERIC | aggregate | Minimum, per column | — |
| max | NUMERIC | aggregate | Maximum, per column | — |
| std_dev | NUMERIC | aggregate | Standard deviation, per column | — |
| percentiles | NUMERIC | aggregate | p5, p25, p50, p75, p95 per column | — |
| skewness | NUMERIC | aggregate | Fisher-Pearson skewness per column — distribution asymmetry. `null` when the column has zero variance | — |
| kurtosis | NUMERIC | aggregate | Excess kurtosis (Fisher) per column — tailedness. `null` when the column has zero variance | — |
| count_zero | NUMERIC | aggregate | Count of zero values per column, with total records | — |
| count_null | CATEGORICAL | aggregate | Count of None/null/missing values per column, with total records | — |
| count_non_numeric | CATEGORICAL | aggregate | Count of values that are not a usable int or finite float (None, strings, booleans, NaN) per column | — |
| mode | CATEGORICAL | aggregate | Most frequent value per column, as `{value, frequency}` entries. Ties are all reported | — |
| value_frequency | CATEGORICAL | aggregate | Full value-frequency distribution per column, as `{value, frequency}` entries | — |

Every metric in this table returns an aggregate only — none of them add `dq_` row columns.

### Dataset-Level Metrics (no Role — no View)

| Metric | Output | What it measures | Params |
|---|---|---|---|
| effectiveness | aggregate | Ratio of dataset size to estimated required size | — |

### On-Request Metrics (five families, never in the default set)

Data filters (`urls_filter` and the other six), duplicate detection (`exact_dedup`, `fuzzy_dedup`), language detection (`language_detection`), PII detection (`pii_detection`) and dataset composition (`taxonomy`, us-east-1 only) run only when the user asks for one; their Roles, parameters, cost and limits are `on-request-metrics.md`.

## Judged Quality (no built-in metrics)

There are no built-in judged metrics. Judged quality requirements are spec criteria (`quality-job.md` Step 10).

## Default Metric Sets

The default set per format category (10 deterministic metrics, 19 runs on prompt+completion formats and 10 on prompt-only formats), and the on-request metrics beside it, are `references/format-metric-mapping.md` (Default Metric Sets by Format Category).

## Output Column Naming

- Row-level columns follow the pattern: `dq_<metric>__<column>` (double underscore + column suffix)
- Single column binding: `dq_word_count__answer`. The suffix is the column lowercased, with each run of characters other than letters and digits replaced by one `_` and any leading or trailing `_` dropped (`User-Prompt` → `dq_word_count__user_prompt`)
- Metrics that bind several columns (`Column` / `Label` roles) are aggregate-only and write no row columns
- Without a View, the suffix is the derived column: `dq_word_count__dq_input__prompt` + `dq_word_count__dq_input__completion`

## Notes

- Nova_RLVR is recognized and has no default set. Its core columns (`messages`, `reference_answer`) are nested and unbindable; built-ins run only on additional flat scalar columns with explicit bindings. Spec-driven evaluation and the exploratory analysis read the whole record.
- Tabular/categorical metrics require columns with low-cardinality categorical values
- Numeric metrics require columns with numeric values
- Zero-operand metrics (effectiveness) take no View — supplying one is rejected at submit
- Embedding-based metrics (remote_clique, chamfer_distance) have no validated workflow in this capability (`overview.md`, "Out of Scope"); the service's metric list says whether it offers them
