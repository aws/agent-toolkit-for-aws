# Cell 0 [markdown]: Filter op skeleton
# Auto-generated filter function for: [INSTRUCTION_SUMMARY]
# Copy this file to <project-dir>/scripts/run_NNN/filter_fn.py and run it with
# `python3 filter_fn.py <input> --output <out> --json`. Edit only the region
# marked `# --- EDIT: ... ---` (the `mask = ...` predicate); keep the rest so the
# CLI flags and the stats contract the tests and run log depend on stay intact.

# Cell 1: Imports
import json
import os
import sys

try:
    import pandas as pd
except ImportError:
    print(
        "Error: 'pandas' is required for filtering operations.\n"
        "Install it with: pip install pandas==2.3.3",
        file=sys.stderr,
    )
    sys.exit(1)


# Cell 2: Transform function
def transform_dataset(inputs: dict[str, str], output_dir: str,
                      write_output: bool = True) -> dict:
    """Filter the dataset, keeping only rows that pass the criteria.

    Loads the whole input JSONL into a pandas DataFrame via
    ``pd.read_json(input_path, lines=True, dtype=False, convert_dates=False)``,
    applies vectorized filter logic, then writes the original bytes for each
    kept record to output_dir as JSONL. Disabling dtype and date inference
    preserves values while evaluating the mask; writing the original lines
    preserves string identifiers, date strings, key order, and formatting.
    Because the load is whole-file (not line-by-line), a malformed line makes
    the pandas read raise rather than being counted, so ``errors`` is always
    reported as 0.

    Parameters
    ----------
    inputs : dict[str, str]
        Dataset name to local file path mapping.
    output_dir : str
        Directory to write output file(s) to.
    write_output : bool
        When False, compute stats + the removed-row sample but do NOT write
        the output JSONL. Used by --preview so a large dataset is not
        serialized just to show a sample. Defaults to True (normal execution).

    Returns
    -------
    dict
        Filter statistics: total, kept, removed counts.
    """
    input_path = next(iter(inputs.values()))
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "dataset.jsonl")

    df = pd.read_json(
        input_path,
        lines=True,
        dtype=False,
        convert_dates=False,
    )
    with open(input_path, "rb") as source:
        source_lines = [line for line in source if line.strip()]
    if len(source_lines) != len(df):
        raise RuntimeError(
            "Could not align parsed JSONL records with their original lines"
        )
    source_position_column = "__sagemaker_source_line_position"
    while source_position_column in df.columns:
        source_position_column = f"_{source_position_column}"
    df[source_position_column] = range(len(df))
    if df.empty:
        outputs = []
        if write_output:
            with open(output_path, "w") as f:
                pass
            outputs = [output_path]
        return {"outputs": outputs, "total_records": 0, "transformed_records": 0, "errors": 0, "removed_sample": []}

    total = len(df)
    # --- EDIT: filter predicate (set `mask`) ---
    # Use vectorized pandas operations:
    #   Compound AND: mask = (df["col1"] > threshold) & (df["col2"].str.contains(pattern))
    #   Compound OR:  mask = (condition_a) | (condition_b)
    #   Regex:        mask = df["col"].str.contains(r"pattern", regex=True, na=False)
    #   Numeric:      mask = df["score"] >= 0.5
    #   Set membership: mask = df["category"].isin({"A", "B", "C"})
    #   Nested field: df["nested_col"] = df["parent"].apply(lambda x: x.get("child"))
    mask = pd.Series(True, index=df.index)
    result = df[mask]
    kept = len(result)

    # Capture a small sample of REMOVED rows here, from the input DataFrame by
    # index (df.drop(result.index)). This is the only place the filter's
    # selection is known, so it is immune to any schema mutation or pandas type
    # coercion that a later input-vs-output text diff would trip over. main()
    # surfaces this in --preview instead of reconstructing removed rows itself.
    removed = df.drop(result.index).drop(
        columns=[source_position_column],
        errors="ignore",
    )
    removed_sample = json.loads(
        removed.head(3).to_json(orient="records", force_ascii=False)
    )

    outputs = []
    if write_output:
        with open(output_path, "wb") as destination:
            for position in result[source_position_column]:
                destination.write(source_lines[int(position)])
        outputs = [output_path]
    return {
        "outputs": outputs,
        "total_records": total,
        "transformed_records": kept,
        "errors": 0,
        "removed_sample": removed_sample,
    }


# Cell 3: CLI (main)
# --show-samples output limits: at most SAMPLE_LIMIT records, each value cut to
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
    import shutil
    import tempfile

    parser = argparse.ArgumentParser(description="Custom filter function")
    parser.add_argument("input", help="Input JSONL file path")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    parser.add_argument("--json", action="store_true", help="Output stats as JSON")
    parser.add_argument("--preview", action="store_true",
                        help="Report how many records would be kept and removed "
                             "without writing output")
    parser.add_argument("--show-samples", action="store_true",
                        help=f"With --preview, also include up to {SAMPLE_LIMIT} removed "
                             f"records (sample_removed), each value cut to "
                             f"{SAMPLE_VALUE_CHARS} characters. Off by default because "
                             "records can contain personal data; use only after the user "
                             "asks to see records")
    args = parser.parse_args()
    if args.show_samples and not args.preview:
        print("Warning: --show-samples has no effect without --preview; "
              "no records are shown.", file=sys.stderr)

    if not os.path.isfile(args.input):
        msg = f"File not found: {args.input}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    tmp_dir = tempfile.mkdtemp()
    try:
        # In --preview, skip writing the full output file: transform_dataset
        # still computes the stats and removed-row sample, but does not
        # serialize the whole dataset just to show a sample.
        result = transform_dataset({"dataset": args.input}, tmp_dir,
                                   write_output=not args.preview)
        total = result.get("total_records", 0)
        kept = result.get("transformed_records", 0)

        if args.preview:
            # transform_dataset computed the removed sample from the input
            # DataFrame by index, so it is exact even when the filter mutates
            # the schema or pandas coerces types. Record content reaches stdout
            # only on request (--show-samples); by default the preview reports
            # counts.
            stats = {
                "total": total,
                "would_keep": kept,
                "would_remove": total - kept,
                "pct_retained": round(kept / total * 100, 2) if total > 0 else 0,
            }
            sample_removed = (
                [_truncated_record(r)
                 for r in result.get("removed_sample", [])[:SAMPLE_LIMIT]]
                if args.show_samples else []
            )
            if args.show_samples:
                stats["sample_removed"] = sample_removed
            if args.json:
                print(json.dumps(stats, ensure_ascii=False, default=str))
            else:
                print(f"Preview: {kept}/{total} records would be retained "
                      f"({stats['pct_retained']}%)")
                if sample_removed:
                    print("Sample records that would be removed:")
                    for r in sample_removed:
                        print(f"  {json.dumps(r, ensure_ascii=False, default=str)}")
            return

        # Move output to final destination
        out_file = os.path.join(tmp_dir, "dataset.jsonl")
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        if os.path.isfile(out_file):
            shutil.move(out_file, args.output)

        stats = {
            "total": total,
            "kept": kept,
            "removed": total - kept,
            "pct_retained": round(kept / total * 100, 2) if total > 0 else 0,
        }

        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total: {total}, Kept: {kept}, Removed: {total - kept} "
                  f"({stats['pct_retained']}% retained)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()


# Cell 4: Notebook Step  # NOTEBOOK_ONLY_SECTION
def filter_record(record):
    """Return the record when it satisfies [FILTER_CRITERIA], otherwise None."""
    # --- EDIT: notebook filter predicate ---
    return record


step_input = [PREVIOUS_OUTPUT_OR_INPUT_PATH]
step_output = f"{RUN_DIR}/step_[STEP_NUMBER]_filter.jsonl"
stats = run_record_transform(
    step_input,
    step_output,
    filter_record,
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="filter",
    input_path=step_input,
    output_path=step_output,
    stats=stats,
    parameters={
        "criteria": "[FILTER_CRITERIA]",
        "pct_retained": round(100 * stats["kept"] / max(stats["total"], 1), 2),
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)
