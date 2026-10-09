# Cell 0 [markdown]: Distributed Spark Processing

# Cell 1: Install dependencies
%pip install --upgrade 'sagemaker>=3.22.0,<4.0' boto3 -q  # NOTEBOOK_ONLY

# Cell 2: Configure the processing job
import boto3
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.processing import logs_for_processing_job
from sagemaker.core.shapes import (
    ProcessingInput,
    ProcessingOutput,
    ProcessingS3Input,
    ProcessingS3Output,
)
from sagemaker.core.spark.processing import PySparkProcessor, SparkJarProcessor

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = ""
ROLE_ARN = "[ROLE_ARN]"
APPLICATION_KIND = "pyspark"
SPARK_APPLICATION = "[SPARK_APPLICATION]"
SPARK_MAIN_CLASS = "[SPARK_MAIN_CLASS]"
SPARK_VERSION = ""
SPARK_PYTHON_VERSION = ""
SPARK_CONTAINER_VERSION = ""
SPARK_EVENT_LOGS_S3_URI = "[SPARK_EVENT_LOGS_S3_URI]"
INPUT_S3_URI = "[INPUT_S3_URI]"
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"
INSTANCE_TYPE = "[INSTANCE_TYPE]"
INSTANCE_COUNT = 2
VOLUME_SIZE_GB = 100
MAX_RUNTIME_SECONDS = 86400
BASE_JOB_NAME = "[BASE_JOB_NAME]"
ARGUMENTS = []
SUBMIT_PY_FILES = []
SUBMIT_JARS = []
WAIT_FOR_COMPLETION = False

boto_session = boto3.Session(region_name=REGION or None)
sm_client = boto_session.client("sagemaker")
sm_session = Session(boto_session=boto_session, sagemaker_client=sm_client)
role = ROLE_ARN or get_execution_role()

# Cell 3: Build and submit the Spark processor
processor_kwargs = {
    "role": role,
    "framework_version": SPARK_VERSION or None,
    "py_version": SPARK_PYTHON_VERSION or None,
    "container_version": SPARK_CONTAINER_VERSION or None,
    "instance_type": INSTANCE_TYPE,
    "instance_count": INSTANCE_COUNT,
    "volume_size_in_gb": VOLUME_SIZE_GB,
    "max_runtime_in_seconds": MAX_RUNTIME_SECONDS,
    "base_job_name": BASE_JOB_NAME,
    "sagemaker_session": sm_session,
}
if APPLICATION_KIND == "pyspark":
    processor = PySparkProcessor(**processor_kwargs)
    dependency_kwargs = {
        "submit_py_files": SUBMIT_PY_FILES,
        "submit_jars": SUBMIT_JARS,
    }
elif APPLICATION_KIND == "jar":
    if not SPARK_MAIN_CLASS:
        raise ValueError("SPARK_MAIN_CLASS is required for JAR applications.")
    processor = SparkJarProcessor(**processor_kwargs)
    dependency_kwargs = {
        "submit_class": SPARK_MAIN_CLASS,
        "submit_jars": SUBMIT_JARS,
    }
else:
    raise ValueError("APPLICATION_KIND must be 'pyspark' or 'jar'.")

print(f"Resolved Spark image URI: {processor.image_uri}")

processor.run(
    submit_app=SPARK_APPLICATION,
    inputs=[
        ProcessingInput(
            input_name="input",
            s3_input=ProcessingS3Input(
                s3_uri=INPUT_S3_URI,
                local_path="/opt/ml/processing/input",
                s3_data_type="S3Prefix",
                s3_input_mode="File",
                s3_data_distribution_type="ShardedByS3Key",
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
    spark_event_logs_s3_uri=SPARK_EVENT_LOGS_S3_URI,
    wait=False,
    logs=False,
    **dependency_kwargs,
)

# Cell 4: Report status and optionally wait
job_name = processor.latest_job.processing_job_name
job_arn = sm_client.describe_processing_job(ProcessingJobName=job_name)["ProcessingJobArn"]
print(f"Processing Job Name: {job_name}")
print(f"Processing Job ARN:  {job_arn}")

if WAIT_FOR_COMPLETION:
    logs_for_processing_job(sm_session, job_name, wait=True)
    print(f"Output: {OUTPUT_S3_URI}")
