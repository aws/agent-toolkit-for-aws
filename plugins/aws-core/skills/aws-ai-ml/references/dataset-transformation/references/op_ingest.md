## Table of Contents

- [LLM-Driven Ingestion Operation](#llm-driven-ingestion-operation)
  - [Output Contract](#output-contract)
  - [Key Conventions](#key-conventions)
  - [Malformed Data Handling](#malformed-data-handling)
  - [S3 File Handling](#s3-file-handling)
  - [Procedure](#procedure)
- [Notebook Mode](#notebook-mode)
  - [Stats parsing (`--json` output)](#stats-keys-consumed)
  - [Manifest fields](#manifest-fields-recorded-by-record_step)
  - [Op-specific notes](#op-specific-notes)

## LLM-Driven Ingestion Operation

**When to use:** The instruction describes loading, importing, or converting a raw dataset file into JSONL UTF-8 format for downstream processing.

**Strategy:** LLM code generation. The agent generates a Python ingestion function that detects the input format, reads the data, and converts it to JSONL.

**Trigger phrases:** "ingest", "load", "import", "convert format", "detect format", "convert to JSONL", "read CSV", "read Parquet", or any instruction that describes loading a raw dataset file.

### Output Contract

The generated ingestion function must return a dict with these fields:

Example: `{"format_type":"csv","encoding":"utf-8","records":10000,"malformed":0,"columns":["prompt","completion"],"column_types":{"prompt":"string","completion":"string"},"null_percentages":{"prompt":0.0,"completion":1.5},"sample_rows":[]}`.

### Key Conventions

- **Output format**: Always JSONL with UTF-8 encoding via `df.to_json(path, orient="records", lines=True, force_ascii=False)`
- **Record preservation**: Output record count must equal valid input record count (malformed records are excluded)
- **Column type mapping**: Use categories: integer, float, boolean, datetime, string
- **Sample rows**: `transform_dataset` returns 3 rows in `sample_rows`, with numpy/pandas types converted to native Python. The CLI drops `sample_rows` from its output unless `--show-samples` is passed; pass it only after the user asks to see records (see `../overview.md` → "Showing records")
- **Error handling**: Return descriptive error for unreadable files or files with no valid records
- **CLI interface**: Support `--json` flag for structured JSON output to stdout, and `--show-samples` to include `sample_rows`

### Malformed Data Handling

The ingest operation must handle malformed input gracefully — never crash, always report what was dropped. The generated script should:

1. **Attempt to recover as much data as possible** from the input file.
2. **Count and report malformed/skipped records** in the output statistics.
3. **Present the malformed count to the user** before proceeding to the next workflow step.

Strategy per format:

| Format        | Approach                                                                               | pandas option                                                  |
| ------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| JSONL         | Read line-by-line with `try/except json.JSONDecodeError`. Skip bad lines, count them.  | N/A (don't use `pd.read_json` for potentially malformed JSONL) |
| CSV/TSV       | Validate logical rows with `csv.reader`, skip width mismatches, then load with pandas. | Read the normalized temporary CSV                              |
| JSON array    | Try `json.loads(file.read())`. If it fails, report error with context.                 | N/A                                                            |
| Parquet/Arrow | Binary formats are either valid or corrupt. Wrap in try/except, report clearly.        | N/A                                                            |
| Mixed/Unknown | Line-by-line attempt to parse as JSON. Classify each line. Report breakdown.           | N/A                                                            |

The output statistics must include a `"malformed"` field:

Example: `{"format_type":"jsonl","records":950,"malformed":50,"columns":["prompt","completion"],"column_types":{"prompt":"string","completion":"string"},"null_percentages":{"prompt":0.0,"completion":0.0},"sample_rows":[]}`.

If `malformed > 0`, the agent should inform the user:

> "I successfully ingested **950** records. **50** lines were malformed and skipped. Would you like to review the skipped lines, or proceed with the 950 valid records?"

### S3 File Handling

The generated ingest script (`../code_templates/ingest_fn.py`) is **local-only**: `main()` guards the input with `os.path.isfile(...)`, reads it with local CSV and pandas readers, and counts logical rows whose width differs from the header before pandas loads a normalized temporary CSV. It never reads an `s3://` URI, and you do **not** add S3-streaming code or an S3-tolerant guard to it. Step 0 defaults an S3 or Hub source to the API lane, and Step 2 revalidates that route. If the user explicitly confirms local execution, resolve the source to one exact S3 object, include the planned project-local staging path in the Step 4 summary, and, after approval, download the object unchanged into `data/raw/`. If a Hub source does not resolve to one unambiguous object, ask the user which object to use. The source remains unchanged, and the staged local file uses the same local-only template.

### Procedure

1. **Examine the confirmed local input file.** Check the file extension and read the first few bytes/lines to understand the format. For an explicitly local S3/Hub route, use the approved unchanged copy staged in `data/raw/`.

2. **Generate the ingestion function.** Based on the file characteristics and the instruction, generate a Python script that:
   - Detects the file format (CSV, JSON, JSONL, Parquet, Arrow/Feather, TSV, raw text) and character encoding.
   - Reads the data using the appropriate pandas reader (`pd.read_csv`, `pd.read_json`, `pd.read_parquet`, etc.).
   - Converts to JSONL UTF-8 via `df.to_json(orient='records', lines=True)`.
   - Returns statistics matching the Output Contract above.
   - Supports `--json` flag for structured output.

   The generated script is the committed skeleton at `../code_templates/ingest_fn.py`. Read that file and copy it unchanged except the region marked `# --- EDIT: ... ---` (the format-specific reader it scaffolds); keeping the rest unchanged preserves the CLI flags and the stats contract the tests and run log depend on. Fill the docstring placeholder `[INSTRUCTION_SUMMARY]` with a one-line description of the ingest. Do not reconstruct it from memory.

3. **Save the generated script.** Write the script to `<project-dir>/scripts/run_NNN/ingest_fn.py` where `run_NNN` corresponds to the current transformation run.

4. **Present for user review.** Show the generated ingestion function and the detected format information:

   > "I've detected your file as **[format]** with **[encoding]** encoding. Here's the ingestion function I generated. It will convert [N] records to JSONL UTF-8."

   This function is presented and approved **once** in the single Phase A execution-plan review (`spec_execution_flow.md` Phase A, steps 5–6) that covers every generated operation in the run — do **not** run a separate per-op approval pause here. Iterate on it if the user requests changes during that review.

5. **Execute the ingestion function.** After the user approves, run:

   ```bash
   python3 <project-dir>/scripts/run_NNN/ingest_fn.py <input_file> --output <run_dir>/step_N_ingest.jsonl --json
   ```

6. **Report results.** Parse the JSON output and present:
   - Detected format and encoding
   - Record count
   - Column names and types
   - Null percentages
   - 3 sample rows for user verification

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. Ingest is a hybrid: when reading non-JSONL local formats (CSV, Parquet, …), the step cell uses the **inline custom-loop pattern** instead of `run_record_transform`. The step cell heading is `### Step K: ingest`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, and `RUN_DIR`.

### Step cell template

Ingest reads a non-JSONL file, so it does not use `run_record_transform`.
Use `../code_templates/ingest_fn.py` Cell 4. It reuses the script template's
format-specific `transform_dataset`, moves the produced JSONL to the step path,
normalizes the stats keys consumed by `record_step`, and records the step once.

The CSV path mirrors the script flow: it uses `csv.reader` to validate logical
rows against the header width, writes only valid rows to a temporary normalized
CSV, and then loads that file with pandas. Blank physical lines and newlines
inside quoted fields therefore do not inflate `malformed`, while width
mismatches are counted and excluded. The JSONL path counts each
`json.JSONDecodeError`. Parquet and JSON-array readers either succeed or
raise—there is no silent partial parse, so `malformed` is 0 for those formats.

`record_step` extracts `input_records` via the fallback chain `input_records | total | records` → `stats["total"]` and `output_records` via `output_records | kept | records` → `stats["kept"]`. The keys above keep the manifest contract identical to the script flow (raw rows in, valid JSONL records out, malformed counted separately).

### Stats keys consumed

| Stats key     | Meaning                                                           |
| ------------- | ----------------------------------------------------------------- |
| `total`       | Parsed records plus the CSV-reader-reported malformed-row count   |
| `kept`        | Valid JSONL records written (used as `output_records`)            |
| `format_type` | Detected format (csv, json, jsonl, parquet, arrow, tsv, raw_text) |
| `encoding`    | Detected input encoding                                           |
| `malformed`   | Lines/rows that could not be parsed                               |
| `columns`     | Output column names                                               |

Optional extras (`column_types`, `null_percentages`) can be added to `stats` and surfaced in `parameters` when useful for the manifest. Never put `sample_rows` or any other record content in `stats` or `parameters`: the manifest is a saved artifact and must hold only counts, field names, types, and paths (see `../overview.md` → "Showing records").

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                  |
| ---------------- | ------------------------------------------------------------------------------- |
| `step`           | Step number within this run (typically `1`)                                     |
| `op_type`        | `"ingest"`                                                                      |
| `instruction`    | Original instruction from the spec                                              |
| `input_records`  | `stats["total"]` — raw rows including malformed                                 |
| `output_records` | `stats["kept"]` — valid JSONL records written                                   |
| `output_path`    | `data/transformed/run_{RUN_NUM:03d}/step_{K}_ingest.jsonl`                      |
| `parameters`     | `{"format_type", "encoding", "malformed", "columns"}` from the local stats dict |

### Op-specific notes

- Ingest is typically step 1 of a run (so `K = 1` and the input is `INPUT_PATH` rather than a prior step's output), but the cell template uses `step=K` for consistency with every other op file.
- S3 and Hub sources default to the DataTransformation API. For an explicit
  local override, the local notebook ingest cell receives the approved,
  unchanged project-local copy in `data/raw/`; it does not add a second S3
  implementation to the local template.
