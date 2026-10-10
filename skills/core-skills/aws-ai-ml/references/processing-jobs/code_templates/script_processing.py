# Cell 0 [markdown]: Script or Custom-Container Processing

# Cell 1: Install dependencies
%pip install --upgrade 'sagemaker>=3.22.0,<4.0' boto3 -q  # NOTEBOOK_ONLY

# Cell 2: Configure the processing job
import boto3
from sagemaker.core import Attribution, image_uris, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.processing import ScriptProcessor, logs_for_processing_job
from sagemaker.core.shapes import (
    ProcessingInput,
    ProcessingOutput,
    ProcessingS3Input,
    ProcessingS3Output,
)

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = ""
ROLE_ARN = "[ROLE_ARN]"
SCRIPT_PATH = "[SCRIPT_PATH]"
CUSTOM_IMAGE_URI = ""
IMAGE_FRAMEWORK = "[IMAGE_FRAMEWORK]"
IMAGE_VERSION = ""
IMAGE_PYTHON_VERSION = ""
INPUT_S3_URI = "[INPUT_S3_URI]"
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"
INSTANCE_TYPE = "[INSTANCE_TYPE]"
INSTANCE_COUNT = 1
VOLUME_SIZE_GB = 30
MAX_RUNTIME_SECONDS = 86400
BASE_JOB_NAME = "[BASE_JOB_NAME]"
ARGUMENTS = []
WAIT_FOR_COMPLETION = False

boto_session = boto3.Session(region_name=REGION or None)
region = boto_session.region_name
sm_client = boto_session.client("sagemaker")
sm_session = Session(boto_session=boto_session, sagemaker_client=sm_client)
role = ROLE_ARN or get_execution_role()
image_uri = CUSTOM_IMAGE_URI or image_uris.retrieve(
    framework=IMAGE_FRAMEWORK,
    region=region,
    version=IMAGE_VERSION or None,
    py_version=IMAGE_PYTHON_VERSION or None,
    instance_type=INSTANCE_TYPE,
)
print(f"Resolved processing image URI: {image_uri}")

# Cell 3: Build and submit the processor
processor = ScriptProcessor(
    image_uri=image_uri,
    role=role,
    command=["python3"],
    instance_type=INSTANCE_TYPE,
    instance_count=INSTANCE_COUNT,
    volume_size_in_gb=VOLUME_SIZE_GB,
    max_runtime_in_seconds=MAX_RUNTIME_SECONDS,
    base_job_name=BASE_JOB_NAME,
    sagemaker_session=sm_session,
)
processor.run(
    code=SCRIPT_PATH,
    inputs=[
        ProcessingInput(
            input_name="input",
            s3_input=ProcessingS3Input(
                s3_uri=INPUT_S3_URI,
                local_path="/opt/ml/processing/input",
                s3_data_type="S3Prefix",
                s3_input_mode="File",
            ),
        )
    ],
    outputs=[
        ProcessingOutput(
            output_name="output",
            s3_output=ProcessingS3Output(
                s3_uri=OUTPUT_S3_URI,
                local_path="/opt/ml/processing/output",
                s3_upload_mode="EndOfJob",
            ),
        )
    ],
    arguments=ARGUMENTS,
    wait=False,
    logs=False,
)

# Cell 4: Report status and optionally wait
job_name = processor.latest_job.processing_job_name
job_arn = sm_client.describe_processing_job(ProcessingJobName=job_name)["ProcessingJobArn"]
print(f"Processing Job Name: {job_name}")
print(f"Processing Job ARN:  {job_arn}")

if WAIT_FOR_COMPLETION:
    logs_for_processing_job(sm_session, job_name, wait=True)
    print(f"Output: {OUTPUT_S3_URI}")
