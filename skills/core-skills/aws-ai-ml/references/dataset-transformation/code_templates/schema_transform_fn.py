# Cell 0 [markdown]: Schema-transform op skeleton
# Auto-generated schema transform function for: [INSTRUCTION_SUMMARY]
# Copy this file to <project-dir>/scripts/run_NNN/schema_transform_fn.py and run
# it with `python3 schema_transform_fn.py <input> --output <out> --json`. Edit
# only the region marked `# --- EDIT: ... ---` (the per-record mapping) and the
# [TARGET_FORMAT_ID] token; keep the rest so the CLI flags and the stats contract
# the tests and run log depend on stay intact.

# Cell 1: Imports
import json
import os
import sys

# pandas is optional — the transform function uses json-based I/O by default.
# LLM may import pandas if needed for the specific mapping logic.


# Cell 2: Transform function
def transform_dataset(inputs: dict[str, str], output_dir: str) -> dict:
    """Transform records from source schema to target schema.

    Parameters
    ----------
    inputs : dict[str, str]
        Dataset name to local file path mapping.
    output_dir : str
        Directory to write output file(s) to.

    Returns
    -------
    dict
        Schema transform statistics: total_records, transformed_records, errors,
        target_format, output_columns, sample_rows.
    """
    input_path = next(iter(inputs.values()))
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "dataset.jsonl")

    # The per-record mapping to the target format is the `# --- EDIT: ... ---` region below.
    # Example for OpenAI chat format from {prompt, completion}:
    total = 0
    transformed = 0
    errors = 0
    sample_rows = []

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue

            # --- EDIT: per-record mapping to the target format ---
            # Example (OpenAI chat from {prompt, completion}):
            #   out = {"messages": [
            #       {"role": "user", "content": record["prompt"]},
            #       {"role": "assistant", "content": record["completion"]},
            #   ]}
            # Mapping failures must propagate instead of silently dropping records.
            out = record  # --- EDIT: replace with the target-format mapping ---
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            transformed += 1
            if len(sample_rows) < 3:
                sample_rows.append(out)

    return {
        "total_records": total,
        "transformed_records": transformed,
        "errors": errors,
        "target_format": "[TARGET_FORMAT_ID]",  # fill in the resolved target format id
        "output_columns": list(sample_rows[0].keys()) if sample_rows else [],
        "sample_rows": sample_rows,
    }


# Cell 3: CLI (main)
# --show-samples output limits: at most SAMPLE_LIMIT rows, each value cut to
# SAMPLE_VALUE_CHARS characters, so the script itself enforces the
# "Showing records" rule rather than relying on the agent.
SAMPLE_LIMIT = 3
SAMPLE_VALUE_CHARS = 200


def _truncated_record(record):
    """Return *record* with every value cut to SAMPLE_VALUE_CHARS characters."""
    out = {}
    for key, value in record.items():
        text = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, default=str)
        if len(text) <= SAMPLE_VALUE_CHARS:
            out[key] = value
        else:
            out[key] = text[:SAMPLE_VALUE_CHARS] + "..."
    return out


def main():
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Transform records to target schema")
    parser.add_argument("input", help="Input JSONL file path")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    parser.add_argument("--json", action="store_true", help="Output stats as JSON")
    parser.add_argument("--show-samples", action="store_true",
                        help="Include up to 3 transformed rows (sample_rows), each value cut to 200 "
                             "characters, in the output. "
                             "Off by default because rows can contain personal data; use "
                             "only after the user asks to see records")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        if args.json:
            print(json.dumps({"error": f"File not found: {args.input}"}))
        else:
            print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    inputs = {"dataset": args.input}
    with tempfile.TemporaryDirectory() as tmpdir:
        result = transform_dataset(inputs, tmpdir)

        # Copy output from tmpdir to the user-specified output path
        output_file = os.path.join(tmpdir, "dataset.jsonl")
        if os.path.isfile(output_file):
            out_dir = os.path.dirname(args.output)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            import shutil
            shutil.copy2(output_file, args.output)

    # Record content reaches stdout only on request (--show-samples), capped
    # at SAMPLE_LIMIT rows with each value truncated.
    if args.show_samples:
        result["sample_rows"] = [
            _truncated_record(r) for r in result.get("sample_rows", [])[:SAMPLE_LIMIT]
        ]
    else:
        result.pop("sample_rows", None)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Input:    {result['total_records']}")
        print(f"Output:   {result['transformed_records']}")
        print(f"Format:   {result['target_format']}")
        print(f"Columns:  {result['output_columns']}")


if __name__ == "__main__":
    main()


# Cell 4: Notebook Step  # NOTEBOOK_ONLY_SECTION
TARGET_FORMAT = "[TARGET_FORMAT_ID]"


def schema_transform_record(record):
    """Map one source record to [TARGET_FORMAT_ID]."""
    # --- EDIT: notebook per-record mapping ---
    raise NotImplementedError("Replace with target-format mapping")


step_input = [PREVIOUS_OUTPUT_OR_INPUT_PATH]
step_output = (
    f"{RUN_DIR}/step_[STEP_NUMBER]_schema_transform.jsonl"
)
stats = run_record_transform(
    step_input,
    step_output,
    schema_transform_record,
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="schema_transform",
    input_path=step_input,
    output_path=step_output,
    stats=stats,
    parameters={
        "target_format": TARGET_FORMAT,
        "output_columns": [OUTPUT_COLUMNS],
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)
