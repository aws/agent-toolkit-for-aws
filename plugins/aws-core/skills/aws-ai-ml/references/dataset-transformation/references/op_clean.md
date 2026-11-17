## Table of Contents

- [LLM-Driven Cleaning Operation](#llm-driven-cleaning-operation)
  - [Default Cleaning Operations](#default-cleaning-operations)
  - [Procedure](#procedure)
- [Notebook Mode](#notebook-mode)
  - [Stats parsing (`--json` output)](#stats-keys-consumed-from-run_record_transform)
  - [Manifest fields](#manifest-fields-recorded-by-record_step)
  - [Op-specific notes](#op-specific-notes)

## LLM-Driven Cleaning Operation

**When to use:** The instruction describes any text cleaning, normalization, or structural validation requirement — including standard operations (whitespace normalization, encoding fixes, emoji removal) and domain-specific transformations.

**Strategy:** LLM code generation. The agent generates a Python cleaning function based on the natural-language instruction and the dataset schema. When no specific cleaning instructions are given (e.g., just "clean the data"), the agent generates a script with the **default cleaning operations** listed below.

**Trigger phrases:** "clean", "normalize", "fix text", "whitespace", "encoding", "clean based on", "fix", "correct", or any instruction that describes text-level transformations or structural validation.

### Default Cleaning Operations

When the instruction is generic (e.g., "clean", "normalize text", "clean the dataset"), the agent must fill the template's structural-validation edit region with the applicable defaults below. The template's commented examples are guidance, not an implementation of these checks.

**Text cleaning (applied to all string fields or specified fields):**

1. Fix encoding issues (mojibake) via `ftfy.fix_text()` — required dependency
2. Strip zero-width characters and BOM markers (`\u200B`, `\u200C`, `\u200D`, `\u2060`, `\uFEFF`, `\u00AD`, `\u180E`)
3. Normalize CRLF → LF (`\r\n` → `\n`, `\r` → `\n`)
4. Collapse multiple spaces/tabs to single space
5. Trim 3+ consecutive newlines to 2
6. Strip leading/trailing whitespace

**Structural validation (applied per record):**

1. Remove malformed JSON lines
2. Remove records with blank/empty prompt field
3. Remove records with empty required fields (based on technique: SFT needs `prompt`+`completion`, DPO needs `prompt`+`chosen`+`rejected`)
4. For DPO: remove records where `chosen == rejected`
5. Remove records with too-short responses (< 10 characters)

The agent should adapt these defaults based on context — for example, if the data has no `prompt` field, skip prompt-specific validation. If the instruction specifies additional or different cleaning, incorporate those requirements.

### Procedure

1. **Examine the dataset schema.** Read 3–5 sample records from the input file to understand the field names, types, and content patterns.

2. **Generate the cleaning function.** Based on the instruction and the observed schema, generate a Python script that:
   - Loads the input JSONL file line by line (for graceful malformed JSON handling).
   - Applies text cleaning transformations.
   - Applies structural validation to remove invalid records.
   - Streams cleaned records to the output JSONL file.
   - Reports before/after statistics to stdout as JSON when `--json` is passed.

   The generated script is the committed skeleton at `../code_templates/clean_fn.py` (the `clean_text` + `transform_dataset` + `main` body). Read that file and copy it unchanged except the two regions marked `# --- EDIT: ... ---` (structural validation, text cleaning); keeping the rest unchanged preserves the CLI flags and the stats contract the tests and run log depend on. For a generic clean request, implement the schema-applicable defaults above in those edit regions; do not leave the commented structural examples as the generated behavior. Fill the docstring placeholder `[INSTRUCTION_SUMMARY]` with a one-line description of the cleaning. Do not reconstruct it from memory.

3. **Save the generated script.** Write the script to `<project-dir>/scripts/run_NNN/clean_fn.py` where `run_NNN` corresponds to the current transformation run.

4. **Present for user review.** Show the generated `transform_dataset` function to the user and explain what it does. Ask:

   > "Here's the cleaning function I generated based on your instruction. It will [describe what it does]."

   This function is presented and approved **once** in the single Phase A execution-plan review (`spec_execution_flow.md` Phase A, steps 5–6) that covers every generated operation in the run — do **not** run a separate per-op approval pause here. Iterate on it if the user requests changes during that review.

5. **Execute the cleaning function.** After the user approves, run:

   ```bash
   python3 <project-dir>/scripts/run_NNN/clean_fn.py <input_file> --output <run_dir>/step_N_clean.jsonl --json
   ```

6. **Report results.** Parse the JSON output and present the before/after statistics:
   - Total input records
   - Records kept
   - Records removed
   - Records modified (cleaned)

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **inline-function pattern** (`def clean_record(record): ...` + `run_record_transform`). The step cell heading is `### Step K: clean`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, and `RUN_DIR`.

### Step cell template

Use `../code_templates/clean_fn.py` Cell 4. Replace only its documented edit
region and square-bracket tokens. That cell defines `clean_record`, calls
`run_record_transform`, records `malformed` and `filtered`, and calls
`record_step` exactly once.

`<prev>` is `INPUT_PATH` for K = 1, otherwise the previous step's `step_<K-1>_<prev_op>.jsonl`.

### Stats keys consumed (from `run_record_transform`)

| Stats key   | Meaning                                         |
| ----------- | ----------------------------------------------- |
| `total`     | Non-blank input lines seen                      |
| `kept`      | Records returned non-`None` from `clean_record` |
| `removed`   | `total - kept`                                  |
| `malformed` | Lines that failed `json.loads()`                |
| `filtered`  | Records where `clean_record` returned `None`    |

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                                                                                  |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `step`           | Step number K within this run                                                                                                                   |
| `op_type`        | `"clean"`                                                                                                                                       |
| `instruction`    | Original instruction from the spec                                                                                                              |
| `input_records`  | Extracted from `stats` by trying `input_records`, then `total`, then `records` → `stats["total"]`                                               |
| `output_records` | Extracted from `stats` by trying `output_records`, then `kept`, then `records` → `stats["kept"]`                                                |
| `output_path`    | `data/transformed/run_{RUN_NUM:03d}/step_{K}_clean.jsonl`                                                                                       |
| `parameters`     | At minimum `{"malformed", "filtered"}` from the helper's stats. Add op-specific keys (e.g. `text_cleaned` if the function tracks it) as needed. |

### Op-specific notes

- The fused-LLM case (clean + filter) uses this same step shape — the inline `clean_record` body applies all fused logic in one pass, the `instruction` describes all fused operations, and `op_type` stays `"clean"`. See `spec_execution_flow.md` → "LLM Operation Fusion".
- The chdir guard prohibition still applies: the step cell MUST NOT call `os.chdir(...)` or `sys.path.insert(...)`. Cell 1 owns those.
