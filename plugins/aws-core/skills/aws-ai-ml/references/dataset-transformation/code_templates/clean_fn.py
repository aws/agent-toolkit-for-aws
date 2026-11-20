# Cell 0 [markdown]: Clean op skeleton
# Auto-generated cleaning function for: [INSTRUCTION_SUMMARY]
# Copy this file to <project-dir>/scripts/run_NNN/clean_fn.py and run it with
# `python3 clean_fn.py <input> --output <out> --json`. Edit only the regions
# marked `# --- EDIT: ... ---`; keep the rest so the CLI flags and the stats
# contract the tests and run log depend on stay intact.

# Cell 1: Imports
import json
import os
import re
import sys

try:
    import ftfy
except ImportError:
    print(
        "Error: 'ftfy' is required for encoding fixes (e.g., 'naÃ¯ve' → 'naïve').\n"
        "Install it with: pip install ftfy==6.3.1",
        file=sys.stderr,
    )
    sys.exit(1)


# Cell 2: Transform functions
def clean_text(text: str) -> str:
    """Normalize and clean a text string.

    Default operations:
    - Fix encoding (ftfy)
    - Strip zero-width/BOM characters
    - Normalize CRLF to LF
    - Collapse whitespace
    - Trim excessive newlines
    - Strip leading/trailing whitespace
    """
    if not isinstance(text, str):
        return text

    text = ftfy.fix_text(text)

    # Strip zero-width characters and BOM
    text = re.sub(r"[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E]", "", text)

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse multiple spaces/tabs to single space (per line, preserves newlines)
    text = re.sub(r"[^\S\n]+", " ", text)

    # Trim 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def transform_dataset(inputs: dict[str, str], output_dir: str) -> dict:
    """Clean and validate the dataset.

    Parameters
    ----------
    inputs : dict[str, str]
        Mapping of dataset name to local file path.
    output_dir : str
        Directory to write output file(s) to.

    Returns
    -------
    dict
        {"outputs": [...], "total_records": N, "transformed_records": N, "errors": 0}
    """
    input_path = next(iter(inputs.values()))
    output_path = os.path.join(output_dir, "dataset.jsonl")
    os.makedirs(output_dir, exist_ok=True)

    total = 0
    malformed = 0
    cleaned_count = 0
    kept = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue

                if not isinstance(record, dict):
                    malformed += 1
                    continue

                # --- EDIT: structural validation ---
                # Example: skip records with blank prompt
                # if not record.get("prompt", "").strip():
                #     continue

                # --- EDIT: text cleaning ---
                modified = False
                for key, value in record.items():
                    if isinstance(value, str):
                        cleaned = clean_text(value)
                        if cleaned != value:
                            record[key] = cleaned
                            modified = True

                if modified:
                    cleaned_count += 1

                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                kept += 1

    return {
        "outputs": [output_path],
        "total_records": total,
        "transformed_records": kept,
        "errors": total - kept,
    }


# Cell 3: CLI (main)
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Clean dataset")
    parser.add_argument("input", help="Input JSONL file path")
    parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    parser.add_argument("--json", action="store_true", help="Output stats as JSON")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        msg = f"File not found: {args.input}"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as output_dir:
        result = transform_dataset({"dataset": args.input}, output_dir)
        if result["outputs"]:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            shutil.move(result["outputs"][0], args.output)
            result["outputs"] = [args.output]

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Total: {result['total_records']}, Kept: {result['transformed_records']}, "
              f"Errors: {result['errors']}")


if __name__ == "__main__":
    main()


# Cell 4: Notebook Step  # NOTEBOOK_ONLY_SECTION
def clean_record(record):
    """Apply [CLEANING_SUMMARY]; return None to drop a record."""
    if not isinstance(record, dict):
        return None
    # --- EDIT: notebook structural validation and text cleaning ---
    for key, value in list(record.items()):
        if isinstance(value, str):
            record[key] = clean_text(value)
    return record


step_input = [PREVIOUS_OUTPUT_OR_INPUT_PATH]
step_output = f"{RUN_DIR}/step_[STEP_NUMBER]_clean.jsonl"
stats = run_record_transform(
    step_input,
    step_output,
    clean_record,
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="clean",
    input_path=step_input,
    output_path=step_output,
    stats=stats,
    parameters={
        "malformed": stats["malformed"],
        "filtered": stats["filtered"],
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)
