# Cell 0 [markdown]: Athena or Redshift Dataset Processing

# Cell 1: Install dependencies
%pip install --upgrade 'sagemaker>=3.22.0,<4.0' boto3 -q  # NOTEBOOK_ONLY

# Cell 2: Configure the processing job
import boto3
from sagemaker.core import Attribution, image_uris, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.processing import ScriptProcessor, logs_for_processing_job
from sagemaker.core.shapes import (
    AthenaDatasetDefinition,
    DatasetDefinition,
    ProcessingInput,
    ProcessingOutput,
    ProcessingS3Output,
    RedshiftDatasetDefinition,
)

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = ""
ROLE_ARN = "[ROLE_ARN]"
SOURCE_KIND = "athena"
PROCESSING_SCRIPT = "[QUERY_PROCESSING_SCRIPT]"
CUSTOM_IMAGE_URI = ""
IMAGE_FRAMEWORK = "[IMAGE_FRAMEWORK]"
IMAGE_VERSION = ""
IMAGE_PYTHON_VERSION = ""
QUERY_RESULT_S3_URI = "[QUERY_RESULT_S3_URI]"
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"
OUTPUT_FORMAT = "PARQUET"
INSTANCE_TYPE = "[INSTANCE_TYPE]"
MAX_RUNTIME_SECONDS = 86400
BASE_JOB_NAME = "[BASE_JOB_NAME]"
WAIT_FOR_COMPLETION = False

ATHENA_CATALOG = "[ATHENA_CATALOG]"
ATHENA_DATABASE = "[ATHENA_DATABASE]"
ATHENA_WORK_GROUP = "primary"
ATHENA_QUERY = "[ATHENA_QUERY]"

REDSHIFT_CLUSTER = "[REDSHIFT_CLUSTER]"
REDSHIFT_DATABASE = "[REDSHIFT_DATABASE]"
REDSHIFT_DB_USER = "[REDSHIFT_DB_USER]"
REDSHIFT_CLUSTER_ROLE_ARN = "[REDSHIFT_CLUSTER_ROLE_ARN]"
REDSHIFT_QUERY = "[REDSHIFT_QUERY]"

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

# Cell 3: Build the dataset definition and submit
if SOURCE_KIND == "athena":
    source = DatasetDefinition(
        athena_dataset_definition=AthenaDatasetDefinition(
            catalog=ATHENA_CATALOG,
            database=ATHENA_DATABASE,
            work_group=ATHENA_WORK_GROUP,
            query_string=ATHENA_QUERY,
            output_s3_uri=QUERY_RESULT_S3_URI,
            output_format=OUTPUT_FORMAT,
        ),
        local_path="/opt/ml/processing/input/query",
    )
elif SOURCE_KIND == "redshift":
    source = DatasetDefinition(
        redshift_dataset_definition=RedshiftDatasetDefinition(
            cluster_id=REDSHIFT_CLUSTER,
            database=REDSHIFT_DATABASE,
            db_user=REDSHIFT_DB_USER,
            cluster_role_arn=REDSHIFT_CLUSTER_ROLE_ARN,
            query_string=REDSHIFT_QUERY,
            output_s3_uri=QUERY_RESULT_S3_URI,
            output_format=OUTPUT_FORMAT,
        ),
        local_path="/opt/ml/processing/input/query",
    )
else:
    raise ValueError("SOURCE_KIND must be 'athena' or 'redshift'.")

processor = ScriptProcessor(
    image_uri=image_uri,
    role=role,
    command=["python3"],
    instance_type=INSTANCE_TYPE,
    instance_count=1,
    max_runtime_in_seconds=MAX_RUNTIME_SECONDS,
    base_job_name=BASE_JOB_NAME,
    sagemaker_session=sm_session,
)
processor.run(
    code=PROCESSING_SCRIPT,
    inputs=[ProcessingInput(input_name="query", dataset_definition=source)],
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
