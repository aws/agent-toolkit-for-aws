## Table of Contents

- [LLM-Driven Merge Operation](#llm-driven-merge-operation)
  - [Optimization Principle](#optimization-principle)
  - [Procedure](#procedure)
- [Notebook Mode](#notebook-mode)
  - [Multiple inputs in the setup cell](#multiple-inputs-in-the-setup-cell)
  - [Stats parsing (`--json` output)](#stats-keys-consumed)
  - [Manifest fields](#manifest-fields-recorded-by-record_step)
  - [Op-specific notes](#op-specific-notes)

## LLM-Driven Merge Operation

**When to use:** The instruction describes combining, concatenating, or merging multiple JSONL files into a single output file.

**Strategy:** LLM code generation. The agent generates a Python merge script optimized for the specific merge requirements. For simple concatenation (the most common case), the generated script uses direct file-level append without JSON parsing/re-serialization. For complex merges requiring deduplication across sources or schema reconciliation, the agent generates appropriate logic.

**Trigger phrases:** "merge", "combine", "concatenate", "join datasets", "append files", or any instruction that describes combining multiple input files into one output.

### Optimization Principle

When the workflow contains **only a merge operation** (single operation, no cleaning/filtering/splitting), or when the merge instruction is a simple concatenation without dedup requirements, the generated script should take the **optimized file-append approach**:

- Read input files line by line and write directly to output (no JSON parsing)
- This avoids the overhead of `json.loads()` + `json.dumps()` for every record
- Significantly faster for large files

When the instruction requires additional processing (deduplication, schema validation), the agent generates a script that parses JSON as needed.

**Important:** Do NOT add metadata fields (e.g., `_source`) to the output records. Provenance is tracked in the merge statistics and manifest only — the output data must remain clean for downstream fine-tuning.

### Procedure

1. **Determine merge complexity.** Examine the instruction to classify the merge:
   - **Simple concatenation**: instruction says "concatenate", "append", "combine" without mentioning dedup or schema validation → use optimized file append
   - **Dedup merge**: instruction mentions "deduplicate across", "remove duplicates" → parse JSON and apply dedup logic

2. **Generate the merge script.** Based on the classification, generate a Python script.

   **For simple concatenation (optimized):** the committed skeleton at `../code_templates/merge_fn.py` (the `transform_dataset` + `main` body) is used as-is — read that file and copy it unchanged (fill the docstring placeholder `[INSTRUCTION_SUMMARY]`). For a keyed join, copy it and replace only the region marked `# --- EDIT: ... ---` (the append loop); keeping the rest unchanged preserves the CLI flags and the stats contract the tests and run log depend on. Do not reconstruct it from memory.

3. **Save the generated script.** Write the script to `<project-dir>/scripts/run_NNN/merge_fn.py` where `run_NNN` corresponds to the current transformation run.

4. **Present for user review.** Show the generated merge function and explain the approach:

   > "I'll merge these files using optimized direct file append (no JSON parsing overhead). This concatenates [N] files into one output."

   This function is presented and approved **once** in the single Phase A execution-plan review (`spec_execution_flow.md` Phase A, steps 5–6) that covers every generated operation in the run — do **not** run a separate per-op approval pause here. Iterate on it if the user requests changes during that review.

5. **Execute the merge function.** After the user approves, run:

   ```bash
   python3 <project-dir>/scripts/run_NNN/merge_fn.py <file1> <file2> [...] --output <run_dir>/step_N_merge.jsonl --json
   ```

6. **Report results.** Parse the JSON output and present:
   - Total records in merged output
   - Per-source record breakdown
   - Output file path

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **inline custom-loop pattern** — `merge` reads multiple files, so the cell does not call `run_record_transform`; it concatenates inputs in a custom loop and builds a `stats` dict matching the `record_step` contract. The step cell heading is `### Step K: merge`. The relevant path variables from Cell 1's Setup are `INPUT_FILES` (a list, not `INPUT_PATH`), `OUTPUT_PATH`, and `RUN_DIR`.

### Multiple inputs in the setup cell

`merge` takes multiple inputs. Set `INPUT_FILES` to the input-path list in
Setup and pass that list as `spec_input` to `init_manifest`.

`INPUT_PATH` (singular) is unused in a merge-only run — `INPUT_FILES` (plural) replaces it. If merge is followed by other ops, those downstream step cells consume the merged file at `step_{K}_merge.jsonl` as their input, exactly like in the script flow.

### Step cell template (custom loop — `run_record_transform` does not apply)

`run_record_transform` takes a **single** input path. Merge takes a **list** of inputs, so this op uses a custom loop instead of the helper. Build a `stats` dict with the keys `record_step` consumes (`total` / `kept` / `records`).

Use `../code_templates/merge_fn.py` Cell 4. It invokes the same
`transform_dataset` implementation as script mode, renames the output to the
step path, records `INPUT_FILES` and the per-source breakdown, and calls
`record_step` once.

For dedup-across-sources merges, replace the inner write loop with a `seen` set and emit a separate `kept` count distinct from `total`; pass `stats["kept"]` as the output count and add a `dedup_removed` entry to `parameters`.

### Stats keys consumed

| Stats key          | Meaning                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| `total`            | Sum of records across all inputs (used as `input_records`)                                        |
| `kept`             | Records written to the merged output (used as `output_records`); equals `total` for simple concat |
| `source_breakdown` | `{path: count}` map per input file                                                                |

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                                                                                                                                                                                 |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `step`           | Step number K within this run                                                                                                                                                                                                                  |
| `op_type`        | `"merge"`                                                                                                                                                                                                                                      |
| `instruction`    | Original instruction from the spec                                                                                                                                                                                                             |
| `input_records`  | `stats["total"]` (sum of records across all inputs)                                                                                                                                                                                            |
| `output_records` | `stats["kept"]` (== `total` for simple concat; smaller for dedup-across-sources)                                                                                                                                                               |
| `output_path`    | `data/transformed/run_{RUN_NUM:03d}/step_{K}_merge.jsonl` (single merged file)                                                                                                                                                                 |
| `parameters`     | `{"input_files": INPUT_FILES, "source_breakdown": stats["source_breakdown"]}`. The agent records provenance in `parameters` only — the merged JSONL itself does **not** carry per-record source metadata (see "Optimization Principle" above). |

### Op-specific notes

- For simple concatenation, `input_records == output_records == stats["total"]`. For dedup-across-sources merges, the inline loop emits a smaller `kept` value and a `dedup_removed` parameter.
- The custom loop is intentionally simple — no JSON parse / re-serialize for plain concat. Add `json.loads` / `json.dumps` only when the merge needs to inspect record contents (e.g. to dedup, validate, or reconcile schema).
