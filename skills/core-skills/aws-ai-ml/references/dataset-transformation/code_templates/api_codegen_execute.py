# Cell 0 [markdown]: Execute Approved CodeGen Output
# Use only after the CodeGen approval gate in ../references/api-execution-flow.md.

# Cell 1: Configuration
INPUT_DATASET_ARN = "[INPUT_DATASET_ARN]"
DATASET_NAME = "[DATASET_NAME]"
OUTPUT_S3_PATH = "[OUTPUT_S3_URI]"
APPROVED_GENERATED_CODE_S3_URI = "[APPROVED_GENERATED_CODE_S3_URI]"
USER_APPROVED = False
WAIT = False  # Full-dataset generated code is long-running; submit in the background.
JOB_ARN = ""  # Set to the saved ARN when re-attaching after a restart.

# Cell 2: Validate the approval and assemble the execution job
import os
import re
import time

from sagemaker.ai_registry.data_preparer import (
    DataPreparer,
    DataPreparerJobFailedError,
    DataPreparerJobStoppedError,
    DataPreparerJobTimeoutError,
    DatasetJobConfig,
)
from sagemaker.ai_registry.data_preparer.constants import JobCategory
from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
os.environ["SAGEMAKER_PYSDK_CREATED_BY"] = Attribution.SAGEMAKER_AGENT_PLUGIN.value

exec_config = None
if not JOB_ARN:
    if not USER_APPROVED:
        raise RuntimeError(
            "Full-dataset execution is blocked until the user explicitly approves "
            "the generated transformer.py and sample."
        )
    _output_bucket = OUTPUT_S3_PATH.removeprefix("s3://").partition("/")[0]
    if not OUTPUT_S3_PATH.startswith("s3://") or not _output_bucket:
        raise ValueError("OUTPUT_S3_PATH must be an s3:// path")
    if not INPUT_DATASET_ARN:
        raise ValueError(
            "INPUT_DATASET_ARN must be the DataSet ARN retained or recovered "
            "from CodeGen Job 1"
        )
    if not APPROVED_GENERATED_CODE_S3_URI.startswith("s3://"):
        raise ValueError(
            "APPROVED_GENERATED_CODE_S3_URI must be the reviewed Job 1 s3:// artifact"
        )
    _bucket, _, _key = APPROVED_GENERATED_CODE_S3_URI.removeprefix("s3://").partition("/")
    if not _bucket or not _key or _key.endswith("/"):
        raise ValueError(
            "APPROVED_GENERATED_CODE_S3_URI must be an s3:// object URI "
            "(the reviewed Job 1 transformer.py artifact)"
        )
    if not _key.endswith("/transformer.py"):
        raise ValueError(
            "APPROVED_GENERATED_CODE_S3_URI must end in /transformer.py "
            "(the reviewed Job 1 artifact)"
        )

    exec_config = DatasetJobConfig(
        job_category=JobCategory.DATA_TRANSFORMATION,
        input_data_config=[{"DatasetArn": INPUT_DATASET_ARN}],
        output_data_config={"S3OutputPath": OUTPUT_S3_PATH},
        transformation_config={
            "Operations": [
                {
                    "Operator": "BYOC",
                    "Config": {
                        "TransformationCodeS3Uri": APPROVED_GENERATED_CODE_S3_URI,
                    },
                }
            ]
        },
    )

# Cell 3: Execute the approved generated code
if not JOB_ARN:
    _suffix = f"-codegen-exec-{int(time.time())}"
    prefix_source = DATASET_NAME
    if not prefix_source:
        arn_parts = [part for part in INPUT_DATASET_ARN.split("/") if part]
        prefix_source = arn_parts[-2] if len(arn_parts) > 1 else arn_parts[-1]
    normalized_prefix = re.sub(r"[^a-zA-Z0-9-]+", "-", prefix_source).strip("-")
    normalized_prefix = re.sub(r"-+", "-", normalized_prefix) or "dataset"
    _prefix = normalized_prefix[: 63 - len(_suffix)].rstrip("-")
    exec_job_name = f"{_prefix}{_suffix}"

    try:
        job = DataPreparer().transform(
            exec_config,
            job_name=exec_job_name,
            wait=False,
            logs=False,
        )
        JOB_ARN = job.job_arn
        submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(
            f"Submitted approved CodeGen execution in the background at {submitted_at}. "
            f"Re-attach with job_arn: {job.job_arn}"
        )
    except Exception as e:
        print(f"Approved CodeGen execution failed: {type(e).__name__}: {e}")
        raise

# Cell 4: Re-attach to the background full-dataset job
# Cross-session: paste the job_arn printed in Cell 3 after a kernel restart.
if not JOB_ARN:
    raise RuntimeError("Set JOB_ARN to the submitted CodeGen execution job ARN")
current_job_name = JOB_ARN.rstrip("/").rsplit("/", 1)[-1]
job = DataPreparer.attach(JOB_ARN, wait=False)
job_status = job.job_status
if job_status in {"Failed", "Stopped"}:
    raise RuntimeError(
        f"Approved CodeGen execution ended with {job_status}: {job.failure_reason}"
    )
outputs = None
if WAIT or job_status == "Completed":
    try:
        outputs = DataPreparer.attach(JOB_ARN, wait=True)
        job_status = "Completed"
    except DataPreparerJobFailedError as error:
        raise RuntimeError(
            f"Approved CodeGen execution ended with Failed: {error.failure_reason}"
        ) from error
    except DataPreparerJobStoppedError as error:
        raise RuntimeError(
            f"Approved CodeGen execution ended with Stopped: {error}"
        ) from error
    except DataPreparerJobTimeoutError as error:
        raise RuntimeError(
            "Approved CodeGen execution did not complete before the waiter timeout. "
            f"Re-attach with job_arn: {error.job_arn}"
        ) from error
print(f"Job: {current_job_name}  status={job_status}")
if outputs is not None:
    for ds in outputs:
        print(f"Output dataset: {ds.arn}  source={ds.source}")
reattach_result = outputs if job_status == "Completed" else job_status
reattach_result
