# Format × Metric Mapping

## Default Metric Sets by Format Category

Defaults are deterministic only. `default_metrics` runs the set for the detected format, and every
metric in it runs without a View on the prompt/completion text the service derives from the format
(`dq_input__prompt`, `dq_input__completion` in the output). This page is the one home of the default
sets; `supported-metrics.md` gives each metric's Role, parameters and output, and `on-request-metrics.md`
the five families that are never in a default set.

The ten deterministic metrics of every default set, in one line for the plan summary: word_count, character_count,
format_distribution, plain_text_ratio, compression_ratio, uniqueness, ngram_diversity, mif_score, toxicity (each
runs on the derived text) and effectiveness (dataset-level, one run, no View).

### Prompt+Completion Formats
**Applies to:** HF_Prompt_Completion, HF_Preference, Bedrock_Converse, OpenAI_Messages, SageMaker_Eval, Nova_PPO

**Default columns:** derived prompt, completion (fan-out — each text metric runs on both)

| Deterministic (10 metrics → 19 runs) | How it runs |
|---|---|
| word_count | fan out → prompt; completion (2 runs) |
| character_count | fan out → prompt; completion (2 runs) |
| format_distribution | fan out → prompt; completion (2 runs) |
| plain_text_ratio | fan out → prompt; completion (2 runs) |
| compression_ratio | fan out → prompt; completion (2 runs) |
| uniqueness | fan out → prompt; completion (2 runs) |
| ngram_diversity | fan out → prompt; completion (2 runs) |
| mif_score | fan out → prompt; completion (2 runs) |
| toxicity | fan out → prompt; completion (2 runs) |
| effectiveness | zero-operand → whole dataset (1 run) |

| Duplicate detection, on request (2 metrics → 4 runs) | How it runs |
|---|---|
| exact_dedup | fan out → prompt; completion (2 runs); per-row decision, see `deduplication/` |
| fuzzy_dedup | fan out → prompt; completion (2 runs); per-row decision, see `deduplication/` |

| Language detection, on request | How it runs |
|---|---|
| language_detection | explicit View only, one run per flat text column of the raw record: `prompt` / `completion` on string-valued HF_Prompt_Completion, `prompt` / `chosen` / `rejected` on string-valued HF_Preference, `query` / `response` on SageMaker_Eval. Chat formats (OpenAI_Messages, Bedrock_Converse, Nova_PPO, message-array HF) have no default binding for it: only an additional flat string key alongside the message array (`messages`, or `turns` on Nova_PPO) is bindable; the array itself never is |

| PII detection, on request | How it runs |
|---|---|
| pii_detection | explicit View only, one run per bound column: on chat formats the message array with Role `Messages` (`messages`; `conversations` on ShareGPT-style HF); on string-valued columnar formats a flat text column with Role `Text` (`prompt`, `completion`, `chosen`, `rejected`, `query`, `response`). Contract in `on-request-metrics.md` -> "PII Detection" |

**Total: 10 metrics → 19 runs** (adding `exact_dedup` and `fuzzy_dedup` on request, listed next to `default_metrics`, makes 12 metrics → 23 runs)

### Prompt-Only Formats
**Applies to:** Nova_CPT, Verl

**Default columns:** derived prompt only (no completion to evaluate)

| Deterministic (10 metrics → 10 runs) | How it runs |
|---|---|
| word_count | prompt only (1 run) |
| character_count | prompt only (1 run) |
| format_distribution | prompt only (1 run) |
| plain_text_ratio | prompt only (1 run) |
| compression_ratio | prompt only (1 run) |
| uniqueness | prompt only (1 run) |
| ngram_diversity | prompt only (1 run) |
| mif_score | prompt only (1 run) |
| toxicity | prompt only (1 run) |
| effectiveness | zero-operand → whole dataset (1 run) |

| Duplicate detection, on request (2 metrics → 2 runs) | How it runs |
|---|---|
| exact_dedup | prompt only (1 run); per-row decision, see `deduplication/` |
| fuzzy_dedup | prompt only (1 run); per-row decision, see `deduplication/` |

| Language detection, on request | How it runs |
|---|---|
| language_detection | explicit View only: `text` on Nova_CPT, `prompt` on Verl when it holds plain strings (1 run) |

| PII detection, on request | How it runs |
|---|---|
| pii_detection | explicit View only: `text` (Role `Text`) on Nova_CPT; `prompt` on Verl, with Role `Text` for plain strings or Role `Messages` for a message list (1 run) |

**Total: 10 metrics → 10 runs** (adding `exact_dedup` and `fuzzy_dedup` on request, listed next to `default_metrics`, makes 12 metrics → 12 runs)

### Unrecognized Columnar (Custom)

No defaults — the user must explicitly select metrics and provide column bindings via View.

All metrics from `supported-metrics.md` are available, but each requires an explicit View binding.

### Unrecognized Nested

No validated workflow in this capability (the service's Views bind flat columns only and cannot reach a nested structure); flatten first with dataset-transformation, and never write transformation code inline.

## Column Availability by Format Type

| Format Type | Available columns for View binding |
|---|---|
| Recognized columnar | All flat keys in the first record |
| Recognized nested | Only the additional flat keys alongside `messages`; the derived prompt / completion are reached by omitting the View, never by naming them |
| Unrecognized columnar | All flat keys in the first record |
| Unrecognized nested | No validated workflow (Views bind flat columns only); flatten first with dataset-transformation |

## Notes

- For recognized formats, omitting the View on a `Text` metric runs it on the derived text (prompt/completion or prompt-only depending on format). `Column` and `Label` metrics always need a View; without one the job fails at run time
- Nova_RLVR is recognized and has no default set. Its core columns (`messages`, `reference_answer`) are nested and cannot be bound to any built-in metric (the job rejects nested bindings); built-ins run only on additional flat scalar columns the records may carry, with explicit bindings. Spec-driven evaluation and the exploratory analysis read the whole record.
- Tabular metrics (data_balance, field_balance, etc.) are not in the default set — they require explicit column selection of categorical fields
- Numeric metrics are not in the default set — they require explicit column selection of numeric fields
- `language_detection` is not in the default set and never default-binds, on any format: it always takes an explicit View on a top-level column of plain strings in the raw record. The derived `prompt` / `completion` on nested formats are not bindable for it
- `pii_detection` is not in the default set and never default-binds either: it always takes an explicit View with Role `Messages` (a column of turn lists) or Role `Text` (a column of plain strings) in the raw record, never the derived `prompt` / `completion`
