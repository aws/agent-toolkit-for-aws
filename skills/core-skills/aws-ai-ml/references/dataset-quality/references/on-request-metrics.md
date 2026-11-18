# On-Request Metrics

The five metric families that are never in the default set and run only when the user asks for one, each with its section below: data filters (`urls_filter`, `mojibake_filter`, `alphanumeric_filter`, `char_repetition_filter`, `character_length_filter`, `average_line_length_filter`, `word_repetition_filter`), duplicate detection (`exact_dedup`, `fuzzy_dedup`), language detection (`language_detection`), PII detection (`pii_detection`) and dataset composition (`taxonomy`, us-east-1 only). This list is the one place the other pages point to for the families on request; they carry no copy of it. Each is one `Operations` entry (`dataset-service-api.md`), added next to `default_metrics` or on its own. This file is the home of each family's View **Role**, parameters, cost and limits; the default-set metrics are `supported-metrics.md`, and which default set runs on which format is `format-metric-mapping.md`. Role names are case-sensitive.

### Data Filters (Role `Text`, one column)

| Metric | Output | What it measures | Params |
|---|---|---|---|
| urls_filter | both | Detects URLs in records | filter_porn_urls (bool, default true), max_url_to_text_ratio (number, default 0.2) |
| mojibake_filter | both | Detects encoding errors | max_badness (number, default 1), max_mojibake_ratio (number, default 0.05) |
| alphanumeric_filter | both | Checks alphanumeric content ratio | min_alnum_ratio (number, default 0.25), max_alnum_ratio (number, no default) |
| char_repetition_filter | both | Detects character repetition | n (int, default 10), min_char_repetition_ratio (number, default 0.0), max_char_repetition_ratio (number, default 0.5) |
| character_length_filter | both | Filters by character length | min_length (int, default 50), max_length (int or null, default null) |
| average_line_length_filter | both | Checks average line length | min_avg_line_length (number, default 10), max_avg_line_length (number or null, default null), min_lines (int, default 2) |
| word_repetition_filter | both | Detects word-level repetition | n (int, default 10), min_word_repetition_ratio (number, default 0.0), max_word_repetition_ratio (number, default 0.5) |

### Duplicate Detection (Role `Text`, one column)

These run in the same `Operations` list, the same job, and the same `quality_report.json` as any other metric, alone or alongside a scorecard. Neither drops rows: every row comes back with a decision. The deduplication sub-reference (`deduplication/overview.md`) owns their interpretation (duplicate groups); read its `references/result-interpretation.md` whenever they ran.

| Metric | Output | What it measures | Params |
|---|---|---|---|
| exact_dedup | both | Byte-identical (optionally normalized) duplicates; per-row `flagged`, `reason`, `representative_row_id` | Normalize (bool, default false) |
| fuzzy_dedup | both | MinHash near-duplicates on word 5-grams; same per-row decisions | JaccardThreshold (0–1, default 0.7), Lowercase (bool, default true) |

### Language Detection (Role `Text`, one column)

Runs in the same `Operations` list and job as any other metric, at no Bedrock cost, and is not in the default set. It classifies one flat text column per row with the FastText lid.176 model and never drops rows: `language_detection_flagged` marks exactly the rows the dataset-transformation `LanguageFilter` operator would drop under the same `languages`, `min_score`, and column. Always bind it with an explicit View (`{"Role": "Text", "Column": "<col>"}`) on a top-level column holding plain strings. It cannot read `messages` / `conversations` or any nested value, including on recognized chat formats; materialize a flat text column first (dataset-transformation).

| Metric | Output | What it measures | Params |
|---|---|---|---|
| language_detection | both | Detected language per row (`lang`, `lang_score`, `language_detection_flagged`; written as `dq_lang__<col>`, `dq_lang_score__<col>`, `dq_language_detection_flagged__<col>`, an exception to `dq_<metric>__<col>`, see `output-schema.md`) + language mix and would-be-rejected share | languages (list of lowercase lid.176 codes; optional allowlist), min_score (0–1, default 0 = off) |

- **`languages`**: non-empty, no repeats, lowercase codes exactly as lid.176 emits them (mostly ISO 639-1 such as `en`, `fr`; also codes such as `ast`, `ceb`; 176 in all). Uppercase, unsupported, and `unknown` codes are rejected at submit. Omit it for no allowlist.
- **`min_score`**: rows scoring below it are flagged; a row scoring exactly `min_score` is not, matching `LanguageFilter`; `0` disables the threshold. `lang_score` is a FastText confidence, not a calibrated probability.
- **Undetected rows** (null, empty, whitespace-only, or non-string cells) get `lang` = `unknown`, `lang_score` = `0`, and are always flagged, even with neither parameter set.
- **Aggregate:** `evaluated_count`, `sampled`, `language_counts` (always includes `unknown`), `language_fractions`, `unknown_count`, `low_confidence_count` (detected rows below `min_score`, or below 0.5 when `min_score` is unset or 0; a count, not a separate flag: these rows can also be in `rejected_count`, always when `min_score` > 0, so never add the two), `rejected_count`, `rejected_fraction` (rows flagged / evaluated).

### PII Detection (Role `Messages` or `Text`, exactly one column)

This section is the home of the `pii_detection` contract; other files point here.

- **Availability.** Not in the default set: add it to the `Operations` list on request.
- **What it does.** Scans one column per row for PII with a Bedrock model (the service's PII entity taxonomy) and only annotates: no row is changed, redacted, or dropped. Detected values and offsets are never written, but `record_level/evaluated_data.jsonl` holds the original rows, PII included: when reporting, give counts, entity types, and row ids, and never quote a row's text or a PII value; if the user asks to see such rows, warn that they hold PII first. To redact or drop, activate dataset-transformation and ask for PiiRedaction on this column.
- **Cost and sampling.** It runs in the same `Operations` list and job as any other metric, but every evaluated row is a Bedrock call, so it evaluates a seeded random sample of at most 1,000 rows (every row when the dataset is smaller; read the actual size from `evaluated_count` and `total_records`; the `sampling` block is present only when a sample was drawn). Every count and rate then describes the sample.
- **Binding.** Always an explicit View with exactly one operand, on every format: `{"Role": "Messages", "Column": "<col>"}` for a chat column holding each row's turn list (ChatML `role` / `content` or ShareGPT `from` / `value`), or `{"Role": "Text", "Column": "<col>"}` for a flat text column. It never default-binds. No View, or both Roles, fails the job.
- **Params.** None. Any key besides `View` in its `Config` is rejected at submit.
- **Limits.** A row whose scannable text is over 200,000 characters is not sent (`unverified`, counted in `oversize_count`). `PiiRedaction` does not fully scan a text value, or a conversation's JSON, over 40,000 characters, and a redact or drop run drops such a row. That limit is lower than this one, so a row the dataset quality evaluation job checked can still be dropped by a redact or drop run. A per-job request budget and a 2-hour deadline bound the run: rows left when the budget runs out are `unverified` and `budget_exhausted` is true; reaching the deadline fails the job. When the service reports a different limit, its message wins.

| Metric | Output | What it measures | Params |
|---|---|---|---|
| pii_detection | both | Per row: `pii_flagged`, `pii_types`, `pii_status` (written as `dq_pii_flagged__<col>`, `dq_pii_types__<col>`, `dq_pii_status__<col>`, see `output-schema.md`) + share of rows with PII and rows per entity type | none |

- **`pii_status`**: `clean` (examined in full, no PII), `pii_found`, `pii_found_incomplete` (PII found, but part of the row was not examined, so `pii_types` may be incomplete), `unverified` (not fully checked: no usable model answer, budget spent, row over the size cap, or a value the model named that could not be located in the text), `unscannable` (a turn shape, key, or value the detector does not read, including tool-call identifiers), `empty` (nothing to examine), `malformed` (null or missing cell, invalid UTF-8, or not a conversation). `pii_flagged` is true exactly for `pii_found` and `pii_found_incomplete`.
- **`pii_types`**: comma-separated, sorted entity types found in the row (for example `EMAIL,SSN`; `UNK` for a label outside the taxonomy), empty when none. The entity types are the service's PII entity types, the same set the PiiRedaction operator uses.
- **Aggregate:** `evaluated_count`, `total_records`, `sampled`, `assessed_count` (rows with a verdict: `clean`, `pii_found`, `pii_found_incomplete`), `pii_row_count`, `pii_row_rate` (`pii_row_count` / `assessed_count`; null when nothing was assessed), `pii_row_rate_ci` (Wilson 95% interval), `pii_type_counts` (rows per entity type; a row holding several types counts under each, so the counts can sum to more than `pii_row_count`), `unverified_count` (includes the `pii_found_incomplete` rows, so it overlaps `pii_row_count` by `pii_found_incomplete_count`; never add the two), `pii_found_incomplete_count`, `oversize_count`, `unscannable_count`, `empty_count`, `malformed_count`, `num_requests`, `budget_exhausted`.

### Dataset Composition (Role `Text`, one column; us-east-1 only)

Runs in the same `Operations` list and job as any other metric, but only in us-east-1 and at Bedrock cost: it embeds every row with a Nova model served only there and labels the tree with a foundation model through Bedrock. It is therefore not in the default set and is added only after the cost confirmation in the taxonomy sub-reference (`taxonomy/overview.md`), which owns the tree presentation and interpretation.

| Metric | Output | What it measures | Params |
|---|---|---|---|
| taxonomy | both | Per-framing three-level category tree with row counts; per-row `l1`, `l2`, `l3`, `margin` columns; HTML report | framings (list of task, domain, quality; default all three) |

<!-- markdownlint-disable-file MD001 -->
