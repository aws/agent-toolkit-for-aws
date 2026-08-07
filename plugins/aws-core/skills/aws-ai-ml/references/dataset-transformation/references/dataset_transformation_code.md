# Dataset Transformation Code Reference

## When to Reference

When generating:

- a dataset transformation function
- a dataset transformation execution script

**follow the exact python skeletons** captured in this document.

## Related Files

- `scripts/transformation_tools.py` — contains `execute_transformation_job()` for running the generated script as a SageMaker Processing Job. Use this when the user wants remote execution instead of local.

## Requirements

- The dataset transformation function should: **ONLY transform the input DataFrame into the target output format. No I/O, no side effects.**
- The dataset transformation execution script should: **ORCHESTRATE the full pipeline: load the dataset using `load_dataset_from`, apply the transformation function, and write the output using `output_dataset_to`.**
- The script must work in two execution contexts:
  - **Local execution**: paths may be S3 URIs or local file paths
  - **SageMaker Processing Job**: inputs are mounted at `/opt/ml/processing/input/` and outputs go to `/opt/ml/processing/output/`

## Generating a dataset transformation function

The transformation function should be saved to its own file at `<project-dir>/scripts/transform_fn.py` so the user can view and edit it directly. The `<project-dir>` is the project directory established by the directory-management reference (e.g., `dpo-to-rlvr-conversion`).

```python
import pandas as pd

def transform_dataset(df: pd.DataFrame) -> pd.DataFrame:
    # Transform each row from source format to target format
    # Return a DataFrame matching the target schema
    transformed = {transformation logic}
    return transformed

```

## Generating a dataset transformation execution script

The execution script imports `transform_dataset` from `transform_fn.py` rather than embedding it inline. Both files must be in the same directory (`<project-dir>/scripts/`).

```python
import pandas as pd
import json
import subprocess
import shutil
import os
import argparse
from transform_fn import transform_dataset

def load_dataset_from(input_location: str, to: str):
    """
    Load a dataset from S3 or local path.
    - input_location: S3 URI or local file path (including SageMaker Processing mounted paths)
    - to: local file path to save the dataset to
    """
    if input_location.startswith("s3://"):
        subprocess.run(["aws", "s3", "cp", input_location, to], check=True)
    else:
        shutil.copy(input_location, to)

def output_dataset_to(output_location: str, from_path: str):
    """
    Output a dataset to S3 or local path.
    - output_location: S3 URI or local directory/file path (including SageMaker Processing mounted paths)
    - from_path: local file path of the transformed dataset to upload/move
    """
    if output_location.startswith("s3://"):
        subprocess.run(["aws", "s3", "cp", from_path, output_location], check=True)
    else:
        os.makedirs(os.path.dirname(output_location) or ".", exist_ok=True)
        shutil.copy(from_path, output_location)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="S3 URI, local path, or /opt/ml/processing/input/...")
    parser.add_argument("--output", required=True, help="S3 URI, local path, or /opt/ml/processing/output/...")
    args = parser.parse_args()

    # 1. Load dataset
    local_input = "/tmp/input_dataset.jsonl"
    load_dataset_from(args.input, to=local_input)

    # 2. Read into DataFrame
    df = pd.read_json(local_input, lines=True)
    print(f"Loaded {len(df)} records")

    # 3. Transform
    df = transform_dataset(df)

    # 4. Write transformed output locally
    local_output = "/tmp/output_dataset.jsonl"
    df.to_json(local_output, orient="records", lines=True)

    # 5. Output to destination
    output_dataset_to(args.output, from_path=local_output)

    print(f"Transformed {len(df)} records -> {args.output}")

```

## Execution Examples

### Local execution

```bash
python transform.py --input s3://my-bucket/data/input.jsonl --output s3://my-bucket/data/output.jsonl

```

### SageMaker Processing Job

Use `execute_transformation_job` from `scripts/transformation_tools.py` to run the script as a SageMaker Processing Job. This function handles container setup, S3 input/output mounting, and job orchestration. Do not manually construct Processing Job logic — always delegate to this tool.

The job is submitted asynchronously (`wait=False`). Use `describe_transformation_job` to check job status.

```python
from scripts.transformation_tools import execute_transformation_job, describe_transformation_job

execute_transformation_job(
    transform_script_path="transform.py",       # Local path to the saved script
    dataset_source_s3="s3://bucket/input.jsonl", # S3 URI of input dataset
    dataset_output_s3="s3://bucket/output/",     # S3 URI for output
)

```

After submitting, check status with:

```python
from scripts.transformation_tools import describe_transformation_job

status = describe_transformation_job(job_name="<job-name>")
print(status)
# Returns: {"job_name": "...", "status": "InProgress|Completed|Failed|Stopped", ...}

```

Call `describe_transformation_job` repeatedly (every ~30 seconds) until `status` is `Completed`, `Failed`, or `Stopped`.
