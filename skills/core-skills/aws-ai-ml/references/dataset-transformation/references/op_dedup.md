## Table of Contents

- [Deduplication Operation (Script-Based)](#deduplication-operation-script-based)
  - [How It Works](#how-it-works)
  - [CLI Usage](#cli-usage)
  - [Parameters](#parameters)
  - [Output Statistics (JSON)](#output-statistics-json)
  - [When Dedup Appears in Combined Instructions](#when-dedup-appears-in-combined-instructions)
- [Notebook Mode](#notebook-mode)
  - [Step cell template](#step-cell-template)
  - [Manifest fields recorded by `record_step`](#manifest-fields-recorded-by-record_step)
  - [Cross-references](#cross-references)

## Deduplication Operation (Script-Based)

**When to use:** The instruction describes removing duplicate or near-duplicate records from the dataset.

**Strategy:** Pre-built script. The agent invokes `scripts/dedup_filter.py` directly — do NOT generate custom dedup logic.

**Trigger phrases:** "deduplicate", "dedup", "remove duplicates", "near-duplicates", "fuzzy dedup", or any instruction that describes eliminating repeated records.

### How It Works

Two levels of deduplication are supported:

| Mode    | Description                                                         | Use Case                                                   |
| ------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| `exact` | MD5 hash of full serialized record. Byte-identical records removed. | Fast pass to remove perfect duplicates                     |
| `fuzzy` | Exact + MinHash LSH on field(s) character n-gram shingles.          | Default — catches near-duplicates (e.g., minor rephrasing) |

The later record is always the one removed (first occurrence is kept).

### CLI Usage

- Default fuzzy dedup: `python3 <skill-scripts-dir>/dedup_filter.py input.jsonl --output deduped.jsonl --json`
- Exact only: add `--mode exact`.
- Explicit fuzzy mode: add `--mode fuzzy`.
- Selected fields: add `--fields prompt chosen rejected`.
- Custom tuning: add `--threshold 0.85 --num-perm 512 --ngram-size 32`.

### Parameters

| Parameter      | Default    | Description                                                                                                                                                                                               |
| -------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--mode`       | `fuzzy`    | Deduplication mode: `exact` (MD5 only) or `fuzzy` (exact + MinHash LSH).                                                                                                                                  |
| `--fields`     | `prompt`   | Fields to use for fuzzy matching. Multiple fields are concatenated. If specified fields are missing from records, those records are excluded from fuzzy comparison (they still pass through exact dedup). |
| `--threshold`  | `0.7`      | Jaccard similarity threshold (0.0–1.0). Lower = more aggressive dedup.                                                                                                                                    |
| `--num-perm`   | `256`      | Number of MinHash permutations. Higher = more accurate but slower.                                                                                                                                        |
| `--ngram-size` | `5`        | Character n-gram size for shingling.                                                                                                                                                                      |
| `--output`     | (required) | Output JSONL file path.                                                                                                                                                                                   |
| `--json`       | off        | Output statistics as JSON to stdout.                                                                                                                                                                      |

### Output Statistics (JSON)

Example: `{"input_records":1000,"total":999,"output_records":937,"exact_duplicates":50,"fuzzy_duplicates":12,"kept":937,"removed":63,"malformed":1,"threshold":0.7,"num_perm":256,"ngram_size":5,"bands":8,"rows":32}`.

`malformed` counts input lines that are not valid UTF-8. They are skipped
without replacement so their bytes are never silently rewritten. Malformed
JSON that is valid UTF-8 continues to pass through exact dedup unchanged.
`input_records` counts every non-blank line attempted, `total` counts the
UTF-8 lines processed by deduplication, and `output_records` equals `kept`.

### When Dedup Appears in Combined Instructions

If a combined instruction mentions dedup alongside other operations (e.g., "clean and deduplicate"), the agent should NOT generate dedup logic. Instead, follow the guidance in `spec_execution_flow.md` → "Combined Instructions with Dedup":

1. Generate and execute the LLM-driven portion (clean/filter) → intermediate file
2. Run `dedup_filter.py` on the intermediate output → final output

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **direct function-call pattern** — `dedup_dataset` is imported in Cell 1's Setup and called directly in the step cell. The step cell heading is `### Step K: dedup`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, and `RUN_DIR`.

Cell 1 import line:

```python
from dedup_filter import dedup_dataset
```

`dedup_filter.py` is a pre-built script the project owns at `<project-dir>/scripts/dedup_filter.py` (copied from the skill on first use; see `notebook_prebuilt_ops.md` → "Bootstrap Procedure"). The notebook never regenerates it and never invokes it via `subprocess.run([...])`. There is no `%%writefile` cell.

### Step cell template

Use `../code_templates/transformation.py` Cell 3. It directly calls
`dedup_dataset`, records configuration and duplicate counts, and calls
`record_step` exactly once. Substitute the input, step number, mode, threshold,
fields, and original instruction.

`dedup_dataset` returns `{input_records, total, output_records, exact_duplicates, fuzzy_duplicates, kept, removed, malformed, mode, threshold, num_perm, ngram_size}` (plus `bands` / `rows` in fuzzy mode). The output is a **single JSONL file** (`step_{K}_dedup.jsonl`) — no special multi-file finalize handling is required.

### Manifest fields recorded by `record_step`

| Argument         | Source / value                                                                                                                                                  |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `step`           | Step number K within this run                                                                                                                                   |
| `op_type`        | `"dedup"`                                                                                                                                                       |
| `instruction`    | Original instruction from the spec                                                                                                                              |
| `input_records`  | Extracted from `stats["input_records"]` (UTF-8 lines processed plus invalid-UTF-8 lines skipped)                                                                 |
| `output_records` | Extracted from `stats["output_records"]` (equal to `stats["kept"]`)                                                                                              |
| `output_path`    | `step_K_output` (single file)                                                                                                                                   |
| `parameters`     | `{"mode", "threshold", "fields", "exact_duplicates", "fuzzy_duplicates", "num_perm", "ngram_size"}` — config flags plus per-mode duplicate counts from `stats`; `stats["malformed"]` remains available in the recorded input/output accounting. |

### Cross-references

- `notebook_prebuilt_ops.md` — self-contained bootstrap procedure that copies `dedup_filter.py` into the project's `scripts/` directory on first use, plus the canonical step-cell pattern.
- `notebook_structure.md` — full cell-by-cell template (markdown header, setup, manifest init, finalize, optional Hub registration).
- `notebook_run_lifecycle.md` — run numbering, append-only semantics, `metadata.run` tag, idempotency guarantees.
- `notebook_delivery.md` — end-to-end procedure that produces and appends a run section.
