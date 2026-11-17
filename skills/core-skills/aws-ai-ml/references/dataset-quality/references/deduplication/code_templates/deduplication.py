# Dataset Deduplication Template
# Cell structure for a deduplication notebook or script. Submits ONE dataset quality evaluation job
# that runs exact_dedup and/or fuzzy_dedup on a single text field and summarizes the decisions from
# the aggregate report; it writes no copy of the dataset. The duplicate groups are listed on request
# by scripts/dedup_decisions.py (overview.md Step 8), which streams the scored rows from S3.
#
# Prerequisites: the SDK is installed as sagemaker-python-sdk-setup.md says, and the dataset is
# registered in the SageMaker AI Registry (DatasetArn) or is an S3 or
# local file that the conditional Cells 3 and 4 upload and register.
# Before generating, copy scripts/dedup_decisions.py into <project-dir>/scripts/ — Cell 6
# imports it from [PROJECT_SCRIPTS_DIR]. Every bracketed placeholder is documented in overview.md Step 5.
# Dependencies: sagemaker-core, sagemaker-train, boto3 (or the AWS CLI for the S3 reads).

# Cell 0 [markdown]: Dataset Deduplication
# Runs the SageMaker Dataset Quality Evaluation `exact_dedup` / `fuzzy_dedup` operators on **[TEXT_COLUMN]**.
# The job is identification-only: every row comes back with a duplicate decision. The job flags
# rows and drops nothing. No foundation model is called by this job.

# Cell 1: Configuration

DATASET_ARN = "[DATASET_ARN]"            # Hub content ARN of the registered dataset; set by Cell 4 on the S3 and local-file entries
TEXT_COLUMN = [TEXT_COLUMN]              # "my_text_field" (quoted), or None (unquoted) for nested formats
DEDUP_MODE = "[DEDUP_MODE]"              # "exact", "fuzzy", or "both"
NORMALIZE = [NORMALIZE]                  # exact_dedup: strip, collapse whitespace, lowercase first
JACCARD_THRESHOLD = [JACCARD_THRESHOLD]  # fuzzy_dedup: target Jaccard similarity in (0, 1]
LOWERCASE = [LOWERCASE]                  # fuzzy_dedup: lowercase before shingling
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"        # S3 prefix the job writes its output folder under
JOB_BASE_NAME = "[JOB_BASE_NAME]"        # alphanumeric and hyphens; the SDK appends a timestamp to name the job
ROLE_ARN = [ROLE_ARN]                    # the role Step 4 settled, "arn:aws:iam::...:role/..." (quoted); None (unquoted) only when the session identity is itself a SageMaker execution role
PROJECT_SCRIPTS_DIR = "[PROJECT_SCRIPTS_DIR]"  # e.g. "<project-dir>/scripts", where dedup_decisions.py was copied
LOCAL_WORK_DIR = "[LOCAL_WORK_DIR]"      # e.g. "<project-dir>/manifests/dedup", for the job's metadata.json and aggregate report (the row-level file is streamed from S3, never saved)
WAIT = [WAIT]                            # True: notebook, and the script's run-it-and-wait option. False: the script's start-but-don't-wait option.

if (not JOB_BASE_NAME.isascii() or JOB_BASE_NAME.startswith("-")
        or not JOB_BASE_NAME.replace("-", "").isalnum()):
    raise ValueError(f"JOB_BASE_NAME must start with a letter or digit and use only ASCII letters, digits, and hyphens; "
                     f"got {JOB_BASE_NAME!r}")

# Cell 2: Verify the SDK and the region

import json

import boto3
from sagemaker.ai_registry import DataPreparer, DatasetJobConfig
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
REGION = DATASET_ARN.split(":")[3] if DATASET_ARN else None  # the dataset's region is the job's region; None: the session's region (a dataset registered by Cell 4)
session = Session(boto_session=boto3.Session(region_name=REGION))
SUPPORTED_REGIONS = ("us-east-1", "us-west-2")  # where the Dataset Quality Evaluation dedup operators run
if session.boto_region_name not in SUPPORTED_REGIONS:
    raise RuntimeError(
        f"deduplication runs in {SUPPORTED_REGIONS}; the job's region is {session.boto_region_name}"
    )
print(f"Region: {session.boto_region_name}")

# Cell 3: Upload dataset to S3  [CONDITIONAL: local-file entry point only]
# Include only when the user provides a local file path (overview.md Step 1). Skip if the dataset is
# already in S3 or the user has a DatasetArn. The same two cells as ../../../code_templates/notebook_cells.py
# Cells 6 and 7; they run only after the Step 5 confirmation.

INPUT_BUCKET = "[INPUT_BUCKET]"  # target bucket for BYOD uploads
LOCAL_DATASET_PATH = "[LOCAL_DATASET_PATH]"  # the path as the user gave it; a \ or " in it written as \\ or \"
DATASET_S3_KEY = "byod/[HUB_CONTENT_NAME]/[DATASET_FILENAME]"  # the file name the same way

# The upload is a Python call in the notebook and in the script alike: no shell reads the path or the
# file name, so a quote, a space, $, { or a backtick in them stays literal.
session.boto_session.client("s3").upload_file(LOCAL_DATASET_PATH, INPUT_BUCKET, DATASET_S3_KEY)
print(f"Uploaded to: s3://{INPUT_BUCKET}/{DATASET_S3_KEY}")

# Cell 4: Register the dataset in the SageMaker AI Registry  [CONDITIONAL: BYOD only]
# Skip if the user already has a DatasetArn. DataSet.create registers one data file into the
# account's SageMaker AI Registry (../../dataset-import.md). A new name gets version 1.0.0; a name
# already registered gets the next major version. The cell does not read Cell 3's variables.
#   * Dataset in S3: the user's own file URI (one data file, never a folder).
#   * Local file: the URI Cell 3 printed, s3://<input bucket>/byod/<hub content name>/<filename>.

HUB_CONTENT_NAME = "[HUB_CONTENT_NAME]"  # e.g. "my-data": letters, digits and hyphens
DATASET_S3_URI = "[DATASET_S3_URI]"      # e.g. "s3://my-input-bucket/datasets/my-data/train.jsonl": the data file's full URI
DATASET_FORMAT = "[DATASET_FORMAT]"      # e.g. "HF_Prompt_Completion": the parent's format check result (Step 2); the SDK does not check it against the file

import inspect

from sagemaker.ai_registry import DataSet
from sagemaker.train.defaults import TrainDefaults

if not HUB_CONTENT_NAME:
    raise ValueError("Set HUB_CONTENT_NAME (the dataset's Hub content name) before registering.")

# The registration role: Cell 1's ROLE_ARN, or the SDK's default role when it is None.
REGISTRATION_ROLE_ARN = ROLE_ARN or TrainDefaults.get_role(sagemaker_session=session)

# A Custom registration passes no validation role.
VALIDATION_ROLE_ARN = REGISTRATION_ROLE_ARN if DATASET_FORMAT != "Custom" else None

# Passes validation_role_arn when the installed SDK takes it.
VALIDATION_ARGS = ({"validation_role_arn": VALIDATION_ROLE_ARN}
                   if "validation_role_arn" in inspect.signature(DataSet.create).parameters else {})

# Registers in the job's region (Cell 2's session).
dataset = DataSet.create(
    name=HUB_CONTENT_NAME,
    source=DATASET_S3_URI,
    dataset_file_format=DATASET_FORMAT,
    role=REGISTRATION_ROLE_ARN,
    **VALIDATION_ARGS,
    wait=False,
    sagemaker_session=session,
)
dataset.wait()  # returns when the entry is Available

DATASET_ARN = dataset.arn
print(f"Dataset registered: {dataset.name} version {dataset.version}")
print(f"Dataset ARN: {DATASET_ARN}")

# Cell 5: Submit the deduplication job

view = [{"Role": "Text", "Column": TEXT_COLUMN}] if TEXT_COLUMN else None


def _metric(name, **params):
    """Build one Operations entry; View is omitted for recognized nested formats."""
    config = dict(params)
    if view:
        config["View"] = view
    return {"Operator": name, "Config": config}


metrics = []
if DEDUP_MODE in ("exact", "both"):
    metrics.append(_metric("exact_dedup", Normalize=NORMALIZE))
if DEDUP_MODE in ("fuzzy", "both"):
    metrics.append(_metric("fuzzy_dedup", JaccardThreshold=JACCARD_THRESHOLD, Lowercase=LOWERCASE))
if not metrics:
    raise ValueError(f"DEDUP_MODE must be 'exact', 'fuzzy', or 'both', got {DEDUP_MODE!r}")

dq_config = DatasetJobConfig(
    input_data_config=[{"DatasetArn": DATASET_ARN}],
    output_data_config={"S3OutputPath": OUTPUT_S3_URI},
    schema_version="3.0.0",  # required: unpinned, the SDK resolves an older request version
)
dq_config.evaluation_config = {"Operations": metrics}

# The role goes on the DataPreparer envelope, never on the DatasetJobConfig.
preparer = DataPreparer(base_job_name=JOB_BASE_NAME, sagemaker_session=session,
                        **({"role": ROLE_ARN} if ROLE_ARN else {}))
job = preparer.evaluate(dq_config, wait=False)  # submits, returns the Job handle
print("Role used:", preparer.role)  # the role the SDK resolved (or the one passed) for this job
print(json.dumps({"job_name": job.job_name, "job_arn": job.job_arn}))  # keep both: attach() takes the ARN, describe_job the name

if WAIT:  # Cell 1's flag: True unless the user chose start-but-don't-wait
    job.wait()  # polls until a terminal state; it does NOT raise on failure, hence the check below
    if job.job_status != "Completed":
        raise RuntimeError(f"job {job.job_name} ended {job.job_status}: {job.failure_reason}")
    # metadata.json lists the job's output files; DescribeJob names it once the job has completed.
    METADATA_S3_URI = json.loads(job.job_config_document).get("MetadataS3Uri")
    if not METADATA_S3_URI:  # no MetadataS3Uri (troubleshooting.md)
        raise RuntimeError(f"job {job.job_name} completed without MetadataS3Uri; find its outputs with "
                           f"dataset-quality/scripts/dq_job_output.py --job-arn {job.job_arn}")
    print("Job:", job.job_name, "| ARN:", job.job_arn, "| metadata:", METADATA_S3_URI)  # ARN re-attaches later
else:
    print(f"Submitted; not waiting. Re-attach later with job_arn: {job.job_arn}")
    raise SystemExit(0)  # the cells below read the completed job's outputs; run them after re-attaching

# Cell 6: Summarize the duplicate decisions from the aggregate report

import sys

sys.path.insert(0, PROJECT_SCRIPTS_DIR)
from dedup_decisions import fetch_outputs, operators_for_mode, summarize

OPERATORS = operators_for_mode(DEDUP_MODE)
paths = fetch_outputs(METADATA_S3_URI, LOCAL_WORK_DIR)  # saves metadata.json and the aggregate report; the row-level file stays on S3
# The aggregate only: the per-operator counts (identification only, nothing removed). The scored rows
# (the user's data) are streamed from S3 only when the user asks for the duplicate groups
# (overview.md Step 8, the helper's --groups option).
summary = summarize(paths["aggregate"], None, TEXT_COLUMN, OPERATORS)
print(summary["text"])
print("Row-level decisions:", paths["record_level"])  # streamed on request only, never downloaded

# Cell 7 [markdown]: Next steps
# The printed `metadata.json` lists the S3 URIs of the job's outputs: `aggregate/quality_report.json`
# and `record_level/evaluated_data.jsonl`. Ask the agent to show the largest duplicate
# groups, to rerun with a different threshold, or to run a full quality scorecard on the dataset.
