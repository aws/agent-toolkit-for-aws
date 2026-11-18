# Cell 0 [markdown]: Local Dataset Transformation
# Common notebook cells for a local transformation run. Operation-specific
# notebook cells live in the matching <op>_fn.py template so the same template
# supplies both script mode and notebook mode.

# Cell 1: Setup  # NOTEBOOK_ONLY_SECTION
import json
import os
import sys

if os.path.basename(os.getcwd()) == "notebooks":
    os.chdir("..")
PROJECT_ROOT = os.getcwd()

sys.path.insert(0, "scripts")
from transform_helpers import finalize, init_manifest, record_step, run_record_transform

RUN_NUM = [RUN_NUMBER]
SPEC_PATH = f"specs/transformation_spec_run_{RUN_NUM:03d}.json"
INPUT_PATH = "[INPUT_LOCATION]"
OUTPUT_PATH = "[OUTPUT_LOCATION]"
RUN_DIR = f"data/transformed/run_{RUN_NUM:03d}"
HUB_ARN = [HUB_ARN_OR_NONE]
# Account that must own every s3:// bucket the run reads or writes. None means the
# caller's own account; set it only to the spec's expected_bucket_owner.
EXPECTED_BUCKET_OWNER = [EXPECTED_BUCKET_OWNER_OR_NONE]
HUB_REGISTRATION_ROLE_ARN = [HUB_REGISTRATION_ROLE_ARN_OR_NONE]
HUB_REGISTRATION_TIMEOUT_SECONDS = 600

os.makedirs(RUN_DIR, exist_ok=True)

# Cell 2: Initialize Manifest  # NOTEBOOK_ONLY_SECTION
writer = init_manifest(
    project_dir=".",
    run_number=RUN_NUM,
    spec_input=[INPUT_PATH],
    final_output=OUTPUT_PATH,
    hub_content_arn=HUB_ARN,
)

# Cell 3: Dedup Step  # NOTEBOOK_ONLY_SECTION
from dedup_filter import dedup_dataset

step_input = [PREVIOUS_OUTPUT_OR_INPUT_PATH]
step_output = f"{RUN_DIR}/step_[STEP_NUMBER]_dedup.jsonl"
stats = dedup_dataset(
    step_input,
    step_output,
    mode="[DEDUP_MODE]",
    threshold=[DEDUP_THRESHOLD],
    fields=[DEDUP_FIELDS],
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="dedup",
    input_path=step_input,
    output_path=step_output,
    stats=stats,
    parameters={
        "mode": "[DEDUP_MODE]",
        "threshold": [DEDUP_THRESHOLD],
        "fields": [DEDUP_FIELDS],
        "exact_duplicates": stats["exact_duplicates"],
        "fuzzy_duplicates": stats["fuzzy_duplicates"],
        "num_perm": stats["num_perm"],
        "ngram_size": stats["ngram_size"],
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)

# Cell 4: Split Step  # NOTEBOOK_ONLY_SECTION
from dataset_split import split_dataset

split_dir = f"{RUN_DIR}/step_[STEP_NUMBER]_split"
stats = split_dataset(
    [PREVIOUS_OUTPUT_OR_INPUT_PATH],
    split_dir,
    train_ratio=[TRAIN_RATIO],
    val_ratio=[VAL_RATIO],
    test_ratio=[TEST_RATIO],
    strategy="[SPLIT_STRATEGY]",
    stratify_field=[STRATIFY_FIELD_OR_NONE],
    seed=[RANDOM_SEED],
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
record_step(
    writer,
    step=[STEP_NUMBER],
    op_type="split",
    input_path=[PREVIOUS_OUTPUT_OR_INPUT_PATH],
    output_path=f"{split_dir}/",
    stats=stats,
    parameters={
        "strategy": "[SPLIT_STRATEGY]",
        "ratios": [[TRAIN_RATIO], [VAL_RATIO], [TEST_RATIO]],
        "seed": [RANDOM_SEED],
        "splits": {
            "train": stats["train_count"],
            "val": stats["val_count"],
            "test": stats["test_count"],
        },
    },
    instruction="[ORIGINAL_INSTRUCTION]",
)

# Cell 5: Finalize Single Output  # NOTEBOOK_ONLY_SECTION
finalize(
    writer,
    final_path=OUTPUT_PATH,
    last_step_output=[LAST_STEP_OUTPUT],
    expected_bucket_owner=EXPECTED_BUCKET_OWNER,
)
print(f"Manifest: manifests/transformation_manifest_run_{RUN_NUM:03d}.json")
print(f"Output: {OUTPUT_PATH}")

# Cell 6: Finalize Split Outputs  # NOTEBOOK_ONLY_SECTION
if not OUTPUT_PATH.endswith("/"):
    raise ValueError(
        "A Transformation Spec whose final operation is split must set output "
        "to a directory/prefix ending in '/'."
    )
split_output_prefix = OUTPUT_PATH.rstrip("/")
final_outputs = []
last_step_outputs = []
for split_name, split_path in stats["paths"].items():
    final_outputs.append(f"{split_output_prefix}/split_{split_name}.jsonl")
    last_step_outputs.append(split_path)
finalize(writer, final_path=final_outputs, last_step_output=last_step_outputs,
         expected_bucket_owner=EXPECTED_BUCKET_OWNER)

# Cell 7: Register with SageMaker Hub  # NOTEBOOK_ONLY_SECTION
if HUB_ARN:
    import time

    from botocore.exceptions import ClientError
    from sagemaker.ai_registry.dataset import DataSet
    from sagemaker.core import Attribution, set_attribution

    set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
    _, hub_separator, hub_name = HUB_ARN.rpartition(":hub/")
    if not hub_separator or not hub_name:
        raise ValueError(
            "HUB_ARN must be a SageMaker Hub ARN ending in ':hub/<hub-name>'"
        )
    targets = (
        writer.final_output
        if isinstance(writer.final_output, list)
        else [writer.final_output]
    )
    base_dataset_name = "[DATASET_NAME]"
    arns = []
    for s3_uri in targets:
        if not s3_uri.startswith("s3://"):
            raise RuntimeError(
                "Hub registration requires an s3:// OUTPUT_PATH; "
                f"got {s3_uri!r}"
            )
        dataset_name = base_dataset_name
        if len(targets) > 1:
            stem = os.path.splitext(os.path.basename(s3_uri))[0]
            suffix = stem[len("split_"):] if stem.startswith("split_") else stem
            _suffix = f"-{suffix}"
            _prefix = base_dataset_name[: 63 - len(_suffix)].rstrip("-")
            dataset_name = f"{_prefix}{_suffix}"
        pending_dataset = DataSet.create(
            name=dataset_name,
            source=s3_uri,
            wait=False,
            hub_name=hub_name,
            role=HUB_REGISTRATION_ROLE_ARN,
        )
        deadline = time.monotonic() + HUB_REGISTRATION_TIMEOUT_SECONDS
        while True:
            try:
                registered_dataset = DataSet.get(
                    name=pending_dataset.name,
                    version=pending_dataset.version,
                    hub_name=hub_name,
                )
            except ClientError as error:
                error_code = error.response.get("Error", {}).get("Code", "")
                if error_code not in (
                    "ResourceNotFound",
                    "ResourceNotFoundException",
                ):
                    raise
            else:
                status = getattr(
                    registered_dataset.status,
                    "value",
                    registered_dataset.status,
                )
                if status == "Available":
                    arns.append(registered_dataset.arn)
                    break
                if status == "ImportFailed":
                    raise RuntimeError(
                        f"Hub registration failed for {dataset_name!r}"
                    )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Hub registration timed out for {dataset_name!r}"
                )
            time.sleep(5)
    writer.set_hub_content_arn(arns if len(arns) > 1 else arns[0])
    writer.write()
