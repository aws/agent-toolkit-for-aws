## Table of Contents

- [LLM-Driven Schema Transform Operation](#llm-driven-schema-transform-operation)
  - [Output Contract](#output-contract)
  - [Target Format Resolution](#target-format-resolution)
  - [Output Path Convention](#output-path-convention)
  - [Procedure](#procedure)
- [Notebook Mode](#notebook-mode)
  - [Stats parsing (`--json` output)](#stats-keys-consumed-from-run_record_transform)
  - [Manifest fields](#manifest-fields-recorded-by-record_step)
  - [Op-specific notes](#op-specific-notes)

## LLM-Driven Schema Transform Operation

**When to use:** The instruction describes converting records from one schema to another, reformatting columns, or mapping records into a well-known target format (OpenAI chat, SageMaker SFT/DPO/RLVR, HuggingFace preference, Bedrock Nova, VERL, or a user-specified custom format).

**Strategy:** LLM code generation. The agent generates a `transform_dataset(inputs, output_dir) -> dict` function that reads input JSONL file(s), applies the schema mapping, writes output JSONL to `output_dir`, and returns a stats dict.

On the API lane, this broad local intent maps to the built-in
`SchemaConversion` operator only when the complete request is exactly
expressible by its documented `TargetFormat`; other field/column transforms
follow capability-choice precedence in `api-execution-flow.md`.

**Trigger phrases:** "transform", "convert schema", "reformat", "map columns", "to OpenAI chat format", "to SFT format", "to DPO format", "to RLVR format", "to Nova format", or any instruction that describes reshaping records to match a target schema.

### Output Contract

The generated script must emit a JSON stats block with these fields when `--json` is passed:

Example: `{"total_records":10000,"transformed_records":10000,"target_format":"openai_chat","output_columns":["messages"],"sample_rows":[]}`.

- **`total_records` must equal `transformed_records`** unless the instruction explicitly asks to drop rows. Schema transform is a reshape, not a filter — dropping should be done by `filter` or `clean` ops.
- **`sample_rows` only on request.** `transform_dataset` returns up to 3 transformed rows in `sample_rows`; the CLI drops them from its output unless `--show-samples` is passed. Pass it only after the user asks to see records (see `../overview.md` → "Showing records").

### Target Format Resolution

Before generating the transform function, read `references/target_format_resolution.md` to resolve the correct target schema from the instruction (training vs evaluation, model type, technique). Do not rely on memorized schemas.

### Output Path Convention

When the spec's `output` (or a user-supplied output path, in notebook delivery mode) points at a directory rather than a full filename, construct the filename using the pattern:

```
{original_name}_{target_format}.jsonl
```

Examples:

- Input `gen_qa_100k.jsonl` + target `openai_chat` → `gen_qa_100k_openai_chat.jsonl`
- Input `dpo_pairs.parquet` + target `nova_dpo` → `dpo_pairs_nova_dpo.jsonl`

If `output` is already a full file path, use it as-is. `target_format` must match the identifier recorded during Target Format Resolution.

### Procedure

1. **Examine input samples.** Read 1–2 records from the input JSONL to confirm the source schema.

2. **Resolve target format.** Follow `references/target_format_resolution.md`. If the instruction is ambiguous about training vs evaluation, defer to the workflow context (spec metadata, project use case). If still ambiguous, ask the user before generating code.

3. **Generate the transform script.** Create a standalone Python script at `<project-dir>/scripts/run_NNN/schema_transform_fn.py`. The generated script must:
   - Expose `transform_dataset(inputs: dict[str, str], output_dir: str) -> dict` that reads input JSONL, applies the mapping, writes output JSONL to `output_dir`, and returns a stats dict.
   - Wrap it in a `main()` that builds the `inputs` dict, creates a temp `output_dir`, calls the function, and emits the Output Contract stats.
   - Support `--json` flag for structured output.

   The generated script is the committed skeleton at `../code_templates/schema_transform_fn.py` (the `transform_dataset` + `main` body). Read that file and copy it unchanged except the region marked `# --- EDIT: ... ---` (the per-record mapping to the target format); keeping the rest unchanged preserves the CLI flags and the stats contract the tests and run log depend on. Fill the docstring placeholder `[INSTRUCTION_SUMMARY]` and the `[TARGET_FORMAT_ID]` placeholder (the resolved target format id, e.g. `openai_chat`). Do not reconstruct it from memory.

4. **Save the generated script.** Write the script to `<project-dir>/scripts/run_NNN/schema_transform_fn.py` where `run_NNN` corresponds to the current transformation run.

5. **Validate against samples.** Before presenting, run the function against 1–2 sample records from the input and confirm the output matches the resolved target schema. If it doesn't, fix the mapping and re-validate.

6. **Present for user review.** Show the generated transform function, the resolved target format, and the sample output:

   > "I've resolved the target format to **[format name]** with schema **[schema summary]**. Here's the transform function I generated, and a sample transformed record."

   This function is presented and approved **once** in the single Phase A execution-plan review (`spec_execution_flow.md` Phase A, steps 5–6) that covers every generated operation in the run — do **not** run a separate per-op approval pause here. Iterate on it if the user requests changes during that review.

7. **Execute the transform.** After the user approves, run:

   ```bash
   python3 <project-dir>/scripts/run_NNN/schema_transform_fn.py <input_file> --output <run_dir>/step_N_schema_transform.jsonl --json
   ```

8. **Report results.** Parse the JSON output and present:
   - Input record count = output record count (or explain any delta)
   - Target format identifier
   - Output column names
   - 3 sample output rows for user verification

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **inline-function pattern** (`def schema_transform_record(record): ...` + `run_record_transform`). The step cell heading is `### Step K: schema_transform`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, and `RUN_DIR`.

### Step cell template

Use `../code_templates/schema_transform_fn.py` Cell 4. Resolve the target
format first, replace the mapping edit region, and fill its placeholders. The
cell calls `run_record_transform`, records target format and output columns,
and calls `record_step` once.

### Stats keys consumed (from `run_record_transform`)

| Stats key   | Meaning                                                                                                                                                   |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `total`     | Non-blank input lines seen (used as `total_records`)                                                                                                      |
| `kept`      | Records returned non-`None` from `schema_transform_record` (used as `transformed_records`). **Must equal `total`** unless the spec explicitly drops rows. |
| `removed`   | `total - kept`                                                                                                                                            |
| `malformed` | Lines that failed `json.loads()`                                                                                                                          |
| `filtered`  | Records where `schema_transform_record` returned `None`                                                                                                   |

`target_format` and `output_columns` are not produced by `run_record_transform`; the agent supplies them directly in `parameters` because they are determined at cell-generation time, not at runtime.

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                |
| ---------------- | ----------------------------------------------------------------------------- |
| `step`           | Step number K within this run                                                 |
| `op_type`        | `"schema_transform"`                                                          |
| `instruction`    | Original instruction from the spec                                            |
| `input_records`  | Extracted from `stats["total"]` via fallback chain                            |
| `output_records` | Extracted from `stats["kept"]` via fallback chain                             |
| `output_path`    | `data/transformed/run_{RUN_NUM:03d}/step_{K}_schema_transform.jsonl`          |
| `parameters`     | `{"target_format", "output_columns"}` baked into the cell at generation time. |

### Op-specific notes

- Target Format Resolution (see `references/target_format_resolution.md`) happens **once during cell generation** — the agent resolves the format and bakes both the `TARGET_FORMAT` constant and the `schema_transform_record` body into the step cell. The notebook's user does not re-resolve at runtime.
- The "Output Path Convention" rule from the script flow above (`{original_name}_{target_format}.jsonl` when the spec's `output` is a directory) still applies. In the notebook, the per-step output path is the standard `data/transformed/run_{RUN_NUM:03d}/step_{K}_schema_transform.jsonl`, but the **finalize cell** is responsible for honoring the `{name}_{format}.jsonl` rule when copying to `OUTPUT_PATH`. Apply the same naming logic in the finalize cell when `OUTPUT_PATH` is a directory.
- Per the Output Contract above, the script's `total_records == transformed_records` (equivalently, the manifest's `input_records == output_records`) unless the instruction explicitly drops rows. If they differ unexpectedly (e.g. the inline function returned `None`), the agent investigates before recording the manifest entry.
- See `references/target_format_resolution.md` for how the agent picks the right target schema before generating the `schema_transform_record(...)` body.
