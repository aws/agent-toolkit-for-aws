# Cell 0 [markdown]: Model Deployment — Bedrock

# Cell 1: Setup

# %pip install --upgrade 'sagemaker>=3.7.1,<4.0' --quiet  # NOTEBOOK_ONLY

# Cell 2: Configuration

import json
import os

import boto3

os.environ["AWS_DEFAULT_REGION"] = "[REGION]"

from pprint import pprint

from sagemaker.core import Attribution, set_attribution
from sagemaker.core.resources import TrainingJob
from sagemaker.serve.bedrock_model_builder import BedrockModelBuilder

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = "[REGION]"
TRAINING_JOB_NAME = "[TRAINING_JOB_NAME]"
ROLE_ARN = "[ROLE_ARN]"
CUSTOM_MODEL_NAME = "[CUSTOM_MODEL_NAME]"

# Cell 3: Build and Deploy to Bedrock

training_job = TrainingJob.get(training_job_name=TRAINING_JOB_NAME)
print(f"Training job status: {training_job.training_job_status}")

bedrock_builder = BedrockModelBuilder(model=training_job)

deployment_result = bedrock_builder.deploy(
    role_arn=ROLE_ARN,
    custom_model_name=CUSTOM_MODEL_NAME,
)

deployment_arn = deployment_result["customModelDeploymentArn"]
pprint(f"Deployment Result: {deployment_result}")

# Cell 4: Test Inference

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)
message = "What is the capital of France?"
print(f"Model Inference Message: {message}")
resp = bedrock_runtime.converse(
    modelId=deployment_arn,
    messages=[{"role": "user", "content": [{"text": message}]}],
    inferenceConfig={"maxTokens": 100, "temperature": 0.7},
)

response_str = resp["output"]["message"]["content"][0]["text"]
print(f"Model Response: {response_str}")

# Cell 5: Save Manifest
# Save manifest - record output of workflow step for future reference
from pathlib import Path

manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"deploy-{CUSTOM_MODEL_NAME}.json"
manifest_path.write_text(
    json.dumps(
        {
            "custom_model_name": CUSTOM_MODEL_NAME,
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")
