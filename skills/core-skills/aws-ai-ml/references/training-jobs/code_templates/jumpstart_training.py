# Cell 0 [markdown]: JumpStart Traditional ML Training

# Cell 1: Install dependencies
%pip install --upgrade 'sagemaker>=3.22.0,<4.0' boto3 -q  # NOTEBOOK_ONLY

# Cell 2: Configure the training job
import re
import time
import uuid

import boto3
from botocore.exceptions import WaiterError
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.jumpstart.configs import JumpStartConfig
from sagemaker.core.training.configs import (
    CheckpointConfig,
    Compute,
    InputData,
    Networking,
    OutputDataConfig,
    StoppingCondition,
)
from sagemaker.train import ModelTrainer

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = ""
ROLE_ARN = "[ROLE_ARN]"
MODEL_ID = "[JUMPSTART_MODEL_ID]"
MODEL_VERSION = ""
TRAINING_S3_URI = "[TRAINING_S3_URI]"
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"
OUTPUT_KMS_KEY_ID = ""
CHECKPOINT_S3_URI = ""
BASE_JOB_NAME = "[BASE_JOB_NAME]"
ACCEPT_EULA = False
HYPERPARAMETERS = {}
OVERRIDE_INSTANCE_TYPE = ""
OVERRIDE_INSTANCE_COUNT = None
SUBNETS = []
SECURITY_GROUP_IDS = []
ENABLE_NETWORK_ISOLATION = False
ENABLE_INTER_CONTAINER_TRAFFIC_ENCRYPTION = False
MAX_RUNTIME_SECONDS = 86400
WAIT_FOR_COMPLETION = False
WAIT_POLL_SECONDS = 60
WAIT_STARTUP_SLACK_SECONDS = 600


def unique_job_prefix(base_job_name):
    """Return a collision-resistant prefix with room for the SDK timestamp suffix."""
    normalized = re.sub(r"[^A-Za-z0-9-]", "-", base_job_name).strip("-") or "training"
    return f"{normalized[:20].rstrip('-')}-{uuid.uuid4().hex[:10]}"


def resolve_submitted_job(sm_client, job_prefix, timeout_seconds=60):
    """Resolve this submission through public SageMaker APIs only."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        summaries = sm_client.list_training_jobs(
            NameContains=job_prefix,
            SortBy="CreationTime",
            SortOrder="Descending",
            MaxResults=10,
        )["TrainingJobSummaries"]
        matches = [
            summary for summary in summaries if summary["TrainingJobName"].startswith(job_prefix)
        ]
        if len(matches) == 1:
            return sm_client.describe_training_job(
                TrainingJobName=matches[0]["TrainingJobName"]
            )
        if len(matches) > 1:
            raise RuntimeError(f"Multiple training jobs matched unique prefix {job_prefix!r}.")
        time.sleep(2)
    raise TimeoutError(f"Training job with prefix {job_prefix!r} was not visible within 60s.")


boto_session = boto3.Session(region_name=REGION or None)
sm_client = boto_session.client("sagemaker")
sm_session = Session(boto_session=boto_session, sagemaker_client=sm_client)
role = ROLE_ARN or get_execution_role()
job_prefix = unique_job_prefix(BASE_JOB_NAME)

# Cell 3: Build the JumpStart trainer
if bool(SUBNETS) != bool(SECURITY_GROUP_IDS):
    raise ValueError("Provide SUBNETS and SECURITY_GROUP_IDS together, or leave both empty.")

jumpstart_config = JumpStartConfig(
    model_id=MODEL_ID,
    model_version=MODEL_VERSION or None,
    accept_eula=ACCEPT_EULA,
)
trainer_kwargs = {
    "jumpstart_config": jumpstart_config,
    "output_data_config": OutputDataConfig(
        s3_output_path=OUTPUT_S3_URI,
        kms_key_id=OUTPUT_KMS_KEY_ID or None,
    ),
    "checkpoint_config": CheckpointConfig(s3_uri=CHECKPOINT_S3_URI)
    if CHECKPOINT_S3_URI
    else None,
    "stopping_condition": StoppingCondition(max_runtime_in_seconds=MAX_RUNTIME_SECONDS),
    "hyperparameters": HYPERPARAMETERS,
    "sagemaker_session": sm_session,
    "role": role,
    "base_job_name": job_prefix,
}
if OVERRIDE_INSTANCE_TYPE or OVERRIDE_INSTANCE_COUNT is not None:
    compute_kwargs = {}
    if OVERRIDE_INSTANCE_TYPE:
        compute_kwargs["instance_type"] = OVERRIDE_INSTANCE_TYPE
    if OVERRIDE_INSTANCE_COUNT is not None:
        compute_kwargs["instance_count"] = OVERRIDE_INSTANCE_COUNT
    trainer_kwargs["compute"] = Compute(**compute_kwargs)
if SUBNETS or ENABLE_NETWORK_ISOLATION or ENABLE_INTER_CONTAINER_TRAFFIC_ENCRYPTION:
    trainer_kwargs["networking"] = Networking(
        subnets=SUBNETS or None,
        security_group_ids=SECURITY_GROUP_IDS or None,
        enable_network_isolation=ENABLE_NETWORK_ISOLATION,
        enable_inter_container_traffic_encryption=ENABLE_INTER_CONTAINER_TRAFFIC_ENCRYPTION,
    )

trainer = ModelTrainer.from_jumpstart_config(**trainer_kwargs)

# Cell 4: Launch and optionally wait
trainer.train(
    input_data_config=[InputData(channel_name="training", data_source=TRAINING_S3_URI)],
    wait=False,
    logs=False,
)
details = resolve_submitted_job(sm_client, job_prefix)
job_name = details["TrainingJobName"]
job_arn = details["TrainingJobArn"]
print(f"Training Job Name: {job_name}")
print(f"Training Job ARN:  {job_arn}")

if WAIT_FOR_COMPLETION:
    wait_budget_seconds = MAX_RUNTIME_SECONDS + WAIT_STARTUP_SLACK_SECONDS
    max_attempts = max(
        1,
        (wait_budget_seconds + WAIT_POLL_SECONDS - 1) // WAIT_POLL_SECONDS + 1,
    )
    try:
        sm_client.get_waiter("training_job_completed_or_stopped").wait(
            TrainingJobName=job_name,
            WaiterConfig={"Delay": WAIT_POLL_SECONDS, "MaxAttempts": max_attempts},
        )
    except WaiterError:
        pass  # Resolve the real status and FailureReason below.
    details = sm_client.describe_training_job(TrainingJobName=job_name)
    if details["TrainingJobStatus"] != "Completed":
        raise RuntimeError(
            f"Training job ended in {details['TrainingJobStatus']}: "
            f"{details.get('FailureReason', 'no failure reason returned')}"
        )
    print(f"Model artifacts: {details.get('ModelArtifacts', {}).get('S3ModelArtifacts', '')}")
