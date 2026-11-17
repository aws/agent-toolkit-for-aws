# Cell 0 [markdown]: Run a Direct BYOC Transformation
# Submit a separately authored and reviewed transformer.py. This direct BYOC
# artifact never calls CodeGen and never uses a CodeGen-generated URI.

# Cell 1: Configuration
INPUT_DATASET_ARN = "[INPUT_DATASET_ARN]"
INPUT_SOURCE = "[INPUT_S3_URI]"
DATASET_NAME = "[DATASET_NAME]"
OUTPUT_S3_PATH = "[OUTPUT_S3_URI]"
USER_TRANSFORMATION_CODE_S3_URI = "[USER_TRANSFORMATION_CODE_S3_URI]"
TRANSFORMER_LOCAL_PATH = "[PROJECT_DIR]/scripts/transformer.py"
WAIT = False  # Full-dataset custom code is long-running; submit in the background.
JOB_ARN = ""  # Set to the saved ARN when re-attaching after a restart.

# Cell 2: Ensure the editable transformer directory exists # NOTEBOOK_ONLY_SECTION
from pathlib import Path

Path("[PROJECT_DIR]/scripts").mkdir(parents=True, exist_ok=True)

# Cell 3: Write editable transformer # NOTEBOOK_ONLY_SECTION
%%writefile [PROJECT_DIR]/scripts/transformer.py # NOTEBOOK_ONLY
[TRANSFORMER_SOURCE]

# Cell 4: Upload the reviewed user-authored transformer and register the input
import os
import re
from pathlib import Path

from sagemaker.ai_registry.data_preparer import (
    DataPreparer,
    DataPreparerJobFailedError,
    DataPreparerJobStoppedError,
    DataPreparerJobTimeoutError,
    DatasetJobConfig,
)
from sagemaker.ai_registry.data_preparer.constants import JobCategory
from sagemaker.ai_registry.dataset import DataSet
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.s3 import S3Uploader

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
os.environ["SAGEMAKER_PYSDK_CREATED_BY"] = Attribution.SAGEMAKER_AGENT_PLUGIN.value

input_dataset_arn = None
if not JOB_ARN:
    if not USER_TRANSFORMATION_CODE_S3_URI.startswith("s3://"):
        raise ValueError(
            "Set USER_TRANSFORMATION_CODE_S3_URI to the exact destination "
            "s3:// object URI before submitting."
        )
    _output_bucket = OUTPUT_S3_PATH.removeprefix("s3://").partition("/")[0]
    if not OUTPUT_S3_PATH.startswith("s3://") or not _output_bucket:
        raise ValueError("OUTPUT_S3_PATH must be an s3:// path")

    _bucket, _, _key = USER_TRANSFORMATION_CODE_S3_URI.removeprefix("s3://").partition("/")
    if not _bucket or not _key or _key.endswith("/"):
        raise ValueError("USER_TRANSFORMATION_CODE_S3_URI must be an s3:// object URI")
    if bool(INPUT_DATASET_ARN) == bool(INPUT_SOURCE):
        raise ValueError(
            "Set exactly one of INPUT_DATASET_ARN or INPUT_SOURCE"
        )
    if INPUT_SOURCE:
        _source_bucket, _, _source_key = INPUT_SOURCE.removeprefix("s3://").partition("/")
        if (
            not INPUT_SOURCE.startswith("s3://")
            or not _source_bucket
            or not _source_key
            or _source_key.endswith("/")
        ):
            raise ValueError("INPUT_SOURCE must be an exact s3:// object URI")
        if (
            not re.fullmatch(
                r"[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}",
                DATASET_NAME,
            )
            or len(DATASET_NAME) > 63
        ):
            raise ValueError("DATASET_NAME must be a valid 1-63 character name")

    transformer_path = Path(TRANSFORMER_LOCAL_PATH)
    if not transformer_path.is_file():
        raise FileNotFoundError(
            f"Review and save the editable transformer before submission: {transformer_path}"
        )

    # Keep the authored source visible in the editable transformer.py cell/file;
    # do not obtain it from CodeGen. upload_bytes preserves the exact object URI.
    S3Uploader.upload_bytes(
        transformer_path.read_bytes(),
        USER_TRANSFORMATION_CODE_S3_URI,
    )
    print(f"Uploaded reviewed transformer: {USER_TRANSFORMATION_CODE_S3_URI}")

    input_dataset_arn = INPUT_DATASET_ARN
    if not input_dataset_arn:
        input_dataset = DataSet.create(
            name=DATASET_NAME,
            source=INPUT_SOURCE,
            wait=True,
        )
        print(f"Registered input dataset: {input_dataset.arn}")
        input_dataset_arn = input_dataset.arn

# Cell 5: Assemble the direct BYOC job
byoc_config = None
if not JOB_ARN:
    byoc_config = DatasetJobConfig(
        job_category=JobCategory.DATA_TRANSFORMATION,
        input_data_config=[{"DatasetArn": input_dataset_arn}],
        output_data_config={"S3OutputPath": OUTPUT_S3_PATH},
        transformation_config={
            "Operations": [
                {
                    "Operator": "BYOC",
                    "Config": {
                        "TransformationCodeS3Uri": USER_TRANSFORMATION_CODE_S3_URI,
                    },
                }
            ]
        },
    )

# Cell 6: Execute direct BYOC
import time

if not JOB_ARN:
    _suffix = f"-byoc-{int(time.time())}"
    prefix_source = DATASET_NAME
    if not prefix_source:
        arn_parts = [part for part in INPUT_DATASET_ARN.split("/") if part]
        prefix_source = arn_parts[-2] if len(arn_parts) > 1 else arn_parts[-1]
    normalized_prefix = re.sub(r"[^a-zA-Z0-9-]+", "-", prefix_source).strip("-")
    normalized_prefix = re.sub(r"-+", "-", normalized_prefix) or "dataset"
    _prefix = normalized_prefix[: 63 - len(_suffix)].rstrip("-")
    byoc_job_name = f"{_prefix}{_suffix}"

    try:
        job = DataPreparer().transform(
            byoc_config,
            job_name=byoc_job_name,
            wait=False,
            logs=False,
        )
        JOB_ARN = job.job_arn
        submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(
            f"Submitted direct BYOC in the background at {submitted_at}. "
            f"Re-attach with job_arn: {job.job_arn}"
        )
    except Exception as e:
        print(f"Direct BYOC failed: {type(e).__name__}: {e}")
        raise

# Cell 7: Re-attach to the background full-dataset job
# Cross-session: paste the job_arn printed in Cell 6 after a kernel restart.
if not JOB_ARN:
    raise RuntimeError("Set JOB_ARN to the submitted direct BYOC job ARN")
current_job_name = JOB_ARN.rstrip("/").rsplit("/", 1)[-1]
job = DataPreparer.attach(JOB_ARN, wait=False)
job_status = job.job_status
if job_status in {"Failed", "Stopped"}:
    raise RuntimeError(
        f"Direct BYOC ended with {job_status}: {job.failure_reason}"
    )
outputs = None
if WAIT or job_status == "Completed":
    try:
        outputs = DataPreparer.attach(JOB_ARN, wait=True)
        job_status = "Completed"
    except DataPreparerJobFailedError as error:
        raise RuntimeError(
            f"Direct BYOC ended with Failed: {error.failure_reason}"
        ) from error
    except DataPreparerJobStoppedError as error:
        raise RuntimeError(f"Direct BYOC ended with Stopped: {error}") from error
    except DataPreparerJobTimeoutError as error:
        raise RuntimeError(
            "Direct BYOC did not complete before the waiter timeout. "
            f"Re-attach with job_arn: {error.job_arn}"
        ) from error
print(f"Job: {current_job_name}  status={job_status}")
if outputs is not None:
    for ds in outputs:
        print(f"Output dataset: {ds.arn}  source={ds.source}")
reattach_result = outputs if job_status == "Completed" else job_status
reattach_result
