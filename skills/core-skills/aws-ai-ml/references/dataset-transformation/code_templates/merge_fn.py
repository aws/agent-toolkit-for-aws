# Cell 0 [markdown]: Merge op skeleton
# Auto-generated merge function for: [INSTRUCTION_SUMMARY]
# Copy this file to <project-dir>/scripts/run_NNN/merge_fn.py and run it with
# `python3 merge_fn.py <file1> <file2> ... --output <out> --json`. For a keyed
# join, edit only the region marked `# --- EDIT: ... ---`; keep the rest so the
# CLI flags and the stats contract the tests and run log depend on stay intact.

# Cell 1: Imports
import json
import os
import sys


# Cell 2: Transform function
def transform_dataset(inputs: dict[str, str], output_dir: str) -> dict:
    """Merge JSONL files by direct line append (no JSON parsing).

    Parameters
    ----------
    inputs : dict[str, str]
        Mapping of dataset name to local file path.
    output_dir : str
        Directory to write output file(s) to.

    Returns
    -------
    dict
        Merge statistics including outputs, total_records, transformed_records, errors.
    """
    input_paths = list(inputs.values())
    output_path = os.path.join(output_dir, "dataset.jsonl")
    os.makedirs(output_dir, exist_ok=True)

    source_counts = {}
    total = 0

    with open(output_path, "w", encoding="utf-8") as out:
        # --- EDIT: for a keyed join, replace this append loop ---
        for path in input_paths:
            count = 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.write(line + "\n")
                        count += 1
            source_counts[path] = count
            total += count

    return {
        "outputs": [output_path],
        "total_records": total,
        "transformed_records": total,
        "errors": 0,
        "source_breakdown": source_counts,
    }


# Cell 3: CLI (main)
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Merge JSONL files")
    parser.add_argument("files", nargs="+", help="Input JSONL files")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    parser.add_argument("--json", action="store_true", help="Output stats as JSON")
    args = parser.parse_args()

    for path in args.files:
        if not os.path.isfile(path):
            msg = f"File not found: {path}"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    import shutil
    import tempfile

    inputs = {f"{i}_{os.path.basename(f)}": f for i, f in enumerate(args.files)}
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = transform_dataset(inputs, tmp_dir)
        # Honor the requested output filename
        if result["outputs"][0] != args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            shutil.move(result["outputs"][0], args.output)
            result["outputs"] = [args.output]

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Output: {result['outputs']}")
        print(f"Total:  {result['total_records']}")
        for src, count in result["source_breakdown"].items():
            print(f"  {src}: {count}")


if __name__ == "__main__":
    main()


# Cell 4: Notebook Step  # NOTEBOOK_ONLY_SECTION
step_output = f"{RUN_DIR}/step_[STEP_NUMBER]_merge.jsonl"
stats = transform_dataset(
    {
        f"{index}_{os.path.basename(path)}": path
        for index, path in enumerate(INPUT_FILES)
    },
    RUN_DIR,
)
if stats["outputs"][0] != step_output:
    os.replace(stats["outputs"][0], step_output)
    stats["outputs"] = [step_output]
stats["total"] = stats["total_records"]
stats["kept"] = stats["transformed_records"]
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="merge",
    input_path=INPUT_FILES,
    output_path=step_output,
    stats=stats,
    parameters={
        "input_files": INPUT_FILES,
        "source_breakdown": stats["source_breakdown"],
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)
