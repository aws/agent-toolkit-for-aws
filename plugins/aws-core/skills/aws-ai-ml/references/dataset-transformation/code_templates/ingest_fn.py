# Cell 0 [markdown]: Ingest op skeleton
# Auto-generated ingestion function for: [INSTRUCTION_SUMMARY]
# Copy this file to <project-dir>/scripts/run_NNN/ingest_fn.py and run it with
# `python3 ingest_fn.py <input> --output <out> --json`. Edit only the region
# marked `# --- EDIT: ... ---` (the format-specific reader); keep the rest so the
# CLI flags and the stats contract the tests and run log depend on stay intact.

# Cell 1: Imports
import csv
import json
import os
import sys
import tempfile

try:
    import pandas as pd
except ImportError:
    print(
        "Error: 'pandas' is required for ingestion operations.\n"
        "Install it with: pip install pandas==2.3.3",
        file=sys.stderr,
    )
    sys.exit(1)


# Cell 2: Transform function
def transform_dataset(inputs: dict[str, str], output_dir: str) -> dict:
    """Detect format, read data, and convert to JSONL UTF-8.

    Parameters
    ----------
    inputs : dict[str, str]
        Mapping of dataset name to local file path.
    output_dir : str
        Directory to write output file(s) to.

    Returns
    -------
    dict
        Ingestion statistics plus {"outputs", "total_records",
        "transformed_records", "errors"} for DP compatibility.
    """
    input_path = next(iter(inputs.values()))
    output_path = os.path.join(output_dir, "dataset.jsonl")
    os.makedirs(output_dir, exist_ok=True)

    # Detect format from extension and file content:
    #   .csv / .tsv → validate logical rows with csv.reader, then pd.read_csv
    #   .json       → json.loads(file.read())
    #   .jsonl      → line-by-line json.loads with try/except
    #   .parquet    → pd.read_parquet(input_path)
    #   .arrow / .feather → pd.read_feather(input_path)
    # Detect encoding with chardet if available, fallback to utf-8

    # Default skeleton: CSV ingestion example.
    # --- EDIT: format-specific reader ---
    malformed = 0
    normalized_path = None
    try:
        with open(input_path, "r", encoding="utf-8", newline="") as source:
            reader = csv.reader(source)
            header = next((row for row in reader if row), None)
            if header is None:
                raise pd.errors.EmptyDataError("No CSV header")

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                suffix=".csv",
                dir=output_dir,
                delete=False,
            ) as normalized:
                normalized_path = normalized.name
                writer = csv.writer(normalized)
                writer.writerow(header)
                for fields in reader:
                    if not fields:
                        continue
                    if len(fields) != len(header):
                        malformed += 1
                        continue
                    writer.writerow(fields)

        df = pd.read_csv(normalized_path, encoding="utf-8")
    except pd.errors.EmptyDataError:
        with open(output_path, "w", encoding="utf-8") as f:
            pass
        return {
            "format_type": "csv",
            "encoding": "utf-8",
            "records": 0,
            "malformed": 0,
            "columns": [],
            "column_types": {},
            "null_percentages": {},
            "sample_rows": [],
            "outputs": [output_path],
            "total_records": 0,
            "transformed_records": 0,
            "errors": 0,
        }
    finally:
        if normalized_path and os.path.exists(normalized_path):
            os.remove(normalized_path)

    if df.empty:
        with open(output_path, "w", encoding="utf-8") as f:
            pass
        return {
            "format_type": "csv",
            "encoding": "utf-8",
            "records": 0,
            "malformed": malformed,
            "columns": list(df.columns),
            "column_types": {},
            "null_percentages": {},
            "sample_rows": [],
            "outputs": [output_path],
            "total_records": malformed,
            "transformed_records": 0,
            "errors": malformed,
        }

    # Write output as JSONL UTF-8
    df.to_json(output_path, orient="records", lines=True, force_ascii=False)

    # Build statistics
    columns = list(df.columns)
    col_type_map = {"int64": "integer", "float64": "float", "bool": "boolean",
                    "datetime64[ns]": "datetime"}
    column_types = {
        c: col_type_map.get(str(df[c].dtype), "string") for c in columns
    }
    null_pcts = {c: round(df[c].isna().mean() * 100, 2) for c in columns}
    # Convert sample rows to native Python types
    sample_rows = json.loads(df.head(3).to_json(orient="records", force_ascii=False))

    return {
        "format_type": "csv",
        "encoding": "utf-8",
        "records": len(df),
        "malformed": malformed,
        "columns": columns,
        "column_types": column_types,
        "null_percentages": null_pcts,
        "sample_rows": sample_rows,
        "outputs": [output_path],
        "total_records": len(df) + malformed,
        "transformed_records": len(df),
        "errors": malformed,
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

    parser = argparse.ArgumentParser(description="Ingest and convert to JSONL")
    parser.add_argument("input", help="Input file path")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    parser.add_argument("--json", action="store_true", help="Output stats as JSON")
    parser.add_argument("--show-samples", action="store_true",
                        help="Include up to 3 converted rows (sample_rows), each value cut to 200 "
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

    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        result = transform_dataset({"dataset": args.input}, tmpdir)
        if args.output and result.get("outputs"):
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            shutil.move(result["outputs"][0], args.output)
            result["outputs"] = [args.output]

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
        print(f"Format:   {result['format_type']}")
        print(f"Encoding: {result['encoding']}")
        print(f"Records:  {result['records']}")
        print(f"Columns:  {result['columns']}")
        print(f"Outputs:  {result.get('outputs', [])}")


if __name__ == "__main__":
    main()


# Cell 4: Notebook Step  # NOTEBOOK_ONLY_SECTION
# Adapt the script template's format-specific reader for [DETECTED_FORMAT].
import shutil
import tempfile

step_output = f"{RUN_DIR}/step_[STEP_NUMBER]_ingest.jsonl"
with tempfile.TemporaryDirectory() as notebook_ingest_dir:
    stats = transform_dataset(
        {"dataset": INPUT_PATH},
        notebook_ingest_dir,
    )
    shutil.copy2(stats["outputs"][0], step_output)
stats = {
    "total": stats["total_records"],
    "kept": stats["transformed_records"],
    "format_type": stats["format_type"],
    "encoding": stats["encoding"],
    "malformed": stats["malformed"],
    "columns": stats["columns"],
}
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="ingest",
    input_path=INPUT_PATH,
    output_path=step_output,
    stats=stats,
    parameters={
        "format_type": stats["format_type"],
        "encoding": stats["encoding"],
        "malformed": stats["malformed"],
        "columns": stats["columns"],
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)
