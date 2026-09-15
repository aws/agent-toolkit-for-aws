# Cell 0 [markdown]: Model Deployment — SageMaker

# Cell 1: Setup

# %pip install --upgrade 'sagemaker>=3.17.0,<4.0' --quiet  # NOTEBOOK_ONLY

# Cell 2: Configuration

import json
import os

os.environ["AWS_DEFAULT_REGION"] = "[REGION]"

from sagemaker.core import Attribution, set_attribution
from sagemaker.core.resources import TrainingJob
from sagemaker.serve import ModelBuilder

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

TRAINING_JOB_NAME = "[TRAINING_JOB_NAME]"
ROLE_ARN = "[ROLE_ARN]"
INSTANCE_TYPE = "[INSTANCE_TYPE]"
ENDPOINT_NAME = "[ENDPOINT_NAME]"
ADAPTER_IC_NAME = f"{ENDPOINT_NAME}-adapter"
# NOTE FOR AGENT: Only include the ACCEPT_EULA line below for Meta/Llama models.
# For all other models (Apache 2.0, MIT, Qwen License, etc.) remove the ACCEPT_EULA
# variable and the model_builder.accept_eula line entirely — they do not apply.
ACCEPT_EULA = [ACCEPT_EULA]  # Meta/Llama only — remove this line for non-Meta models

# Cell 3: Build Model

training_job = TrainingJob.get(training_job_name=TRAINING_JOB_NAME)
print(f"Training job: {training_job.training_job_name}")
print(f"Model package: {training_job.output_model_package_arn}")

model_builder = ModelBuilder(
    model=training_job,
    role_arn=ROLE_ARN,
)
# Apply the hosting config selected in Step 2 (image, env, and compute for this instance).
model_builder.set_deployment_config(instance_type=INSTANCE_TYPE)
# NOTE FOR AGENT: Only include model_builder.accept_eula for Meta/Llama models.
# Remove this line for all other models.
model_builder.accept_eula = ACCEPT_EULA  # Meta/Llama only — remove for non-Meta models
model = model_builder.build(model_name=ENDPOINT_NAME)
print(f"Model: {model.model_arn}")

# Cell 4: Deploy Endpoint

endpoint = model_builder.deploy(
    endpoint_name=ENDPOINT_NAME,
    inference_component_name=ADAPTER_IC_NAME,
)
print(f"Endpoint: {endpoint.endpoint_name}")

# Cell 5: Test Inference

output = endpoint.invoke(
    body=json.dumps(
        {
            "inputs": "What is the capital of France?",
            "parameters": {"max_new_tokens": 50},
        }
    ),
    inference_component_name=ADAPTER_IC_NAME,
)
print(f"Response: {output.body.read()}")

# Cell 6: Save Manifest
# Save manifest - record output of workflow step for future reference
from pathlib import Path

manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"deploy-{ENDPOINT_NAME}.json"
manifest_path.write_text(
    json.dumps(
        {
            "endpoint_name": ENDPOINT_NAME,
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")
