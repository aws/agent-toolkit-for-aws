# Deduplication Operators — `exact_dedup` and `fuzzy_dedup`

Both are dataset-global deterministic operators. Each binds exactly one text operand, sees the whole
dataset at once, and annotates every row. Neither drops rows and neither calls a foundation model;
decisions are reproducible across runs of the same input.

## Wire format

Each is one entry of the `evaluation_config` `Operations` list. Parameters sit next to `View`
inside `Config`, and the View binds Role `Text`:

```json
{"Operations": [
  {"Operator": "exact_dedup", "Config": {"View": [{"Role": "Text", "Column": "prompt"}], "Normalize": false}},
  {"Operator": "fuzzy_dedup", "Config": {"View": [{"Role": "Text", "Column": "prompt"}], "JaccardThreshold": 0.7, "Lowercase": true}}
]}
```

- Columnar formats: bind one column with `View`. Omitting `View` on any recognized format runs the
  operator on the derived prompt and completion (two runs, two reports, row columns suffixed
  `dq_input__prompt` and `dq_input__completion`; one run on the prompt for Nova_CPT and Verl).
- Recognized nested formats (`messages` arrays): omit only the `View` binding and keep `Config` for
  the parameters; a View naming `prompt` or `completion` fails, because those are not columns of the
  records. The operator runs on the derived prompt and completion as above.
- Parameter names are case-sensitive exactly as shown. Unknown keys are rejected
  (`additionalProperties: false`).
- Submission details (schema pin, output location, BYOD import) are in
  `../../dataset-service-api.md`.

## `exact_dedup`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `Normalize` | boolean | `false` | When true: strip, collapse whitespace runs to one space, and lowercase before hashing. When false, a duplicate is a byte-exact match of the field as provided. |

Semantics: rows are grouped by identical (optionally normalized) text. In each group the **first
occurrence in input order** is the representative; every later occurrence is flagged.

## `fuzzy_dedup`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `JaccardThreshold` | number in (0, 1] | `0.7` | Target Jaccard similarity for near-duplicate clustering. |
| `Lowercase` | boolean | `true` | Lowercase before shingling. No whitespace normalization is applied. |

Semantics: MinHash over word-level 5-gram shingles with 128 permutations and a fixed seed, then
locality-sensitive hashing to find candidate pairs, then transitive clustering. In each cluster a
deterministic **cluster survivor** is the representative; it is not necessarily the first
occurrence. Every other cluster member is flagged.

Two consequences the user should hear before trusting the numbers:

- The threshold tunes probabilistic candidate generation, not a hard floor. Pairs near the
  threshold can be missed or included (the LSH S-curve). Higher values flag fewer, closer matches;
  lower values cluster more aggressively.
- Clusters close transitively, so two rows in one cluster may each be below the threshold relative
  to some other member.

Rows with fewer than five words are skipped by the fuzzy pass and are never flagged as
near-duplicates; use `exact_dedup` for very short fields.

## Aggregate result

`aggregate/quality_report.json` has one key per operator, holding a list of runs. Each run's
`result` object contains:

| Field | Meaning |
|---|---|
| `input_count` | Rows the operator saw |
| `duplicate_count` | Rows flagged (later occurrences for exact; non-survivors for fuzzy) |
| `duplicate_groups` | Groups of size two or more |
| `distinct_count` | `input_count - duplicate_count`: rows that would remain if flagged rows were dropped |
| `duplicate_rate` | `duplicate_count / input_count`, `0.0` for empty input |
| `normalize` | (exact only) echo of the applied parameter |
| `jaccard_threshold`, `lowercase` | (fuzzy only) echoes of the applied parameters |
| `decision_schema_version` | Version of the shared row-decision contract; the version this page describes is `"1.0"` |

Worked example (exact, 8 rows, two groups of duplicates, three later occurrences):

```json
{"exact_dedup": [{"view": {"Text": "prompt"}, "params": {"Normalize": false}, "result": {
  "input_count": 8, "distinct_count": 5, "duplicate_count": 3, "duplicate_groups": 2,
  "duplicate_rate": 0.375, "normalize": false, "decision_schema_version": "1.0"}}]}
```

## Row columns

`record_level/evaluated_data.jsonl` carries every input row plus, per operator, four columns named
`dq_<operator>_<field>__<column>`, where `<column>` is the bound column lowercased with each run of
characters other than letters and digits replaced by `_` and any leading or trailing `_` dropped
(without a View the suffix is
`dq_input__prompt` or `dq_input__completion`):

| Field | Type | Meaning |
|---|---|---|
| `row_id` | string | The input row index as a string, minted by the operator; the id that `representative_row_id` values refer back to |
| `flagged` | boolean | True only for rows a deduplication pass would drop. Representatives and unique rows are false |
| `reason` | string | `exact_duplicate` / `near_duplicate` for flagged rows, `representative` for the retained member of a group, `unique` when no duplicate exists |
| `representative_row_id` | string | Row id of the group's retained row. Unflagged rows reference themselves |

Example for `exact_dedup` bound to `prompt`: `dq_exact_dedup_row_id__prompt`,
`dq_exact_dedup_flagged__prompt`, `dq_exact_dedup_reason__prompt`,
`dq_exact_dedup_representative_row_id__prompt`.

Joining `representative_row_id` back to `row_id` reconstructs every duplicate group; the helper
script `../scripts/dedup_decisions.py` does this.

## Limits and failure modes

- Rows are never dropped by the service. `distinct_count` is a projection, not an output size.
- Both operators reject a missing or non-string text value and a mistyped parameter with a
  user-facing validation error; fix the binding or the parameter and resubmit.
- Runtime scales with row count and the fuzzy operator dominates; job start-up is described in
  `../../quality-job-submit.md` Step 12b.
