## Table of Contents

- [LLM-Driven Filtering Operation](#llm-driven-filtering-operation)
  - [Common Filtering Examples](#common-filtering-examples)
  - [Procedure](#procedure)
- [Notebook Mode](#notebook-mode)
  - [Stats parsing (`--json` output)](#stats-keys-consumed-from-run_record_transform)
  - [Manifest fields](#manifest-fields-recorded-by-record_step)
  - [Op-specific notes](#op-specific-notes)

## LLM-Driven Filtering Operation

**When to use:** The instruction describes criteria for removing records from the dataset — for example, quality score thresholds, content-based filtering, metadata conditions, or Data Improvement recommendations.

**Strategy:** LLM code generation. The agent generates a Python filter function that implements the described criteria, supporting compound conditions (AND/OR), nested field access, regex matching, numeric thresholds, and set membership.

**Trigger phrases:** "filter", "remove records where", "keep only", "quality score", "curate", "exclude", "retain records", or any instruction that describes record-level inclusion/exclusion criteria. Not for language detection: a language filter is the `LanguageFilter` API operator (`api-operator-configs.md`), unless the records already carry a language field. For PII, the default is the `PiiRedaction` API operator and explicit API capability overrides follow `api-execution-flow.md`; never use local hand-written PII patterns or `dataset-quality` `pii_detection` columns, which cover only a sample.

### Common Filtering Examples

#### Filtering Based on Data Quality Scores

When filtering based on `dataset-quality`'s `record_level/evaluated_data.jsonl` output (which contains `dq_` prefixed fields). Metric columns are `dq_<metric>__<column>`, named after the column the metric read (lowercased, each run of characters other than letters and digits replaced by `_` and any leading or trailing `_` dropped); a `dataset-quality` run without a View read the derived text, so its suffix is `dq_input__prompt` or `dq_input__completion`. Check the file's keys for the exact names:

- Spec pass/fail: `mask = df["dq_spec_eval_pass"] != False` keeps null
  unevaluated rows.
- Graded criterion: extract
  `dq_spec_eval_criteria[<id>]["value"]` and keep null or values at/above the
  requested threshold.
- Toxicity: `mask = df["dq_toxicity_label__dq_input__completion"] != "toxic"`.
- Word count: `mask = df["dq_word_count__dq_input__completion"] >= 20`.
- Compound policies combine masks with pandas `&` or `|`.
- Language-detection flag:
  `mask = ~df["dq_language_detection_flagged__prompt"]`, replacing `prompt`
  with the metric's bound column.

#### Other Common Filter Patterns

- Text length: `mask = df["completion"].str.len() >= 50`.
- An existing language field: `mask = df["detected_language"] == "en"`.
  Use the API `LanguageFilter` when language classification is required.
- Category membership:
  `mask = df["category"].isin({"technical", "general"})`.

### Procedure

1. **Examine the dataset schema.** Read 3–5 sample records from the input file to understand the field names, types, and value ranges relevant to the filter criteria.

2. **Generate the filter function.** Based on the instruction and the observed schema, generate a Python script that:
   - Loads the input JSONL file into a pandas DataFrame.
   - Applies the filter predicate using vectorized pandas operations (boolean indexing, string accessors, numeric comparisons).
   - Writes records that pass the filter to the output JSONL file.
   - Reports original count, filtered count, and percentage retained as JSON when `--json` is passed.

   The generated script is the committed skeleton at `../code_templates/filter_fn.py`; it uses pandas DataFrames with vectorized operations for compound conditions, nested field access, and numeric thresholds. Read that file and copy it unchanged except the region marked `# --- EDIT: ... ---` (the `mask = ...` predicate); keeping the rest unchanged preserves the CLI flags and the stats contract the tests and run log depend on. Fill the docstring placeholder `[INSTRUCTION_SUMMARY]` with a one-line description of the filter. Do not reconstruct it from memory.

3. **Save the generated script.** Write the script to `<project-dir>/scripts/run_NNN/filter_fn.py` where `run_NNN` corresponds to the current transformation run.

4. **Preview affected records.** Before executing the full filter, run in preview mode:

   ```bash
   python3 <project-dir>/scripts/run_NNN/filter_fn.py <input_file> --output <run_dir>/step_N_filter.jsonl --preview --json
   ```

   Parse the preview output and present the counts to the user:

   > "This filter would keep **N** of **M** records (**X%** retained). Do you want to see a few of the records it would remove? They may contain personal data."

   The default preview reports counts only. Only if the user asks to see records, re-run with `--show-samples` (`--preview --show-samples --json`), which returns at most 3 removed records with each value cut to 200 characters, and show them (see `../overview.md` → "Showing records").

   This function is presented and approved **once** in the single Phase A execution-plan review (`spec_execution_flow.md` Phase A, steps 5–6) that covers every generated operation in the run — do **not** run a separate per-op approval pause here. Iterate on it if the user requests changes during that review.

5. **Execute the filter function.** After the user approves, run:

   ```bash
   python3 <project-dir>/scripts/run_NNN/filter_fn.py <input_file> --output <run_dir>/step_N_filter.jsonl --json
   ```

6. **Report results.** Parse the JSON output and present the final statistics:
   - Original record count
   - Filtered record count
   - Records removed
   - Percentage of records retained

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **inline-function pattern** (`def filter_record(record): ...` + `run_record_transform`). The step cell heading is `### Step K: filter`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, and `RUN_DIR`.

### Step cell template

Use `../code_templates/filter_fn.py` Cell 4. Replace its predicate edit region
and placeholders. The cell defines `filter_record`, calls
`run_record_transform`, records a human-readable criterion and retention
percentage, and calls `record_step` once.

### Stats keys consumed (from `run_record_transform`)

| Stats key   | Meaning                                                                        |
| ----------- | ------------------------------------------------------------------------------ |
| `total`     | Non-blank input lines seen                                                     |
| `kept`      | Records returned non-`None` from `filter_record` (those passing the predicate) |
| `removed`   | `total - kept`                                                                 |
| `malformed` | Lines that failed `json.loads()`                                               |
| `filtered`  | Records where `filter_record` returned `None`                                  |

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `step`           | Step number K within this run                                                                                                    |
| `op_type`        | `"filter"`                                                                                                                       |
| `instruction`    | Original instruction from the spec                                                                                               |
| `input_records`  | Extracted from `stats["total"]` via fallback chain                                                                               |
| `output_records` | Extracted from `stats["kept"]` via fallback chain                                                                                |
| `output_path`    | `data/transformed/run_{RUN_NUM:03d}/step_{K}_filter.jsonl`                                                                       |
| `parameters`     | At minimum `{"criteria": "<human-readable predicate>", "pct_retained": ...}`. Extend with op-specific keys (thresholds, fields). |

The `criteria` string is the agent's human-readable summary of the filter predicate — capture what the filter actually does so the manifest is auditable. The predicate itself is encoded in the inline function body, not data.

### Op-specific notes

- The "preview removed records" step in the script flow's Procedure is **optional** in notebook mode. To preview, insert a one-off cell that counts how many records `filter_record` would drop on a slice of `INPUT_PATH`, and print only the counts. Never print dropped records in a cell: cell output is saved with the notebook. If the user asks to see records, show at most 2–3 in chat (see `../overview.md` → "Showing records"). The default step cell performs the full filter directly.
