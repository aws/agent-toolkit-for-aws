# Cell 0 [markdown]: Direct BYOC Transformer
# Copy this file to transformer.py and replace only the EDIT region with the
# user's bespoke transformation. This is user/agent-authored code; do not
# obtain it from CodeGen.

# Cell 1: Imports
import json
import os


# Cell 2: Service entry point
def transform_dataset(inputs: dict[str, str], output_dir: str) -> dict:
    """Transform service-staged inputs and return the BYOC stats contract."""
    input_path = next(iter(inputs.values()))
    # The service creates output_dir before invocation. RestrictedPython allows
    # os.path and os.listdir, but rejects os.makedirs.
    output_path = os.path.join(output_dir, "dataset.jsonl")

    total = 0
    transformed = 0
    errors = 0

    with open(input_path, "r", encoding="utf-8") as source, \
            open(output_path, "w", encoding="utf-8") as destination:
        for line in source:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue

            # --- EDIT: bespoke transformation logic ---
            # Use `continue` to drop a row, or assign a transformed dict to
            # `record`. Implement the user's explicit predicates here.
            # Do not wrap this region in the malformed-input handler: authored
            # logic errors must fail the job instead of silently dropping rows.

            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
            transformed += 1

    return {
        "outputs": [output_path],
        "total_records": total,
        "transformed_records": transformed,
        "errors": errors,
    }
