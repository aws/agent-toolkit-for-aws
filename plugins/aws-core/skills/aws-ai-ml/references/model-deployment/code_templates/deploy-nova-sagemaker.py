# Cell 0 [markdown]: Model Deployment — SageMaker

# Cell 1: Setup

# %pip install --upgrade 'sagemaker>=3.7.1,<4.0' --quiet  # NOTEBOOK_ONLY

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

# Cell 3: Build Model

training_job = TrainingJob.get(training_job_name=TRAINING_JOB_NAME)
print(f"Training job: {training_job.training_job_name}")

model_builder = ModelBuilder(
    model=training_job,
    role_arn=ROLE_ARN,
    instance_type=INSTANCE_TYPE,
)
model = model_builder.build()
print(f"Model: {model.model_name}")
print(f"Image: {model_builder.image_uri}")
print(f"Env vars: {model_builder.env_vars}")

# Cell 4: Deploy Endpoint

endpoint = model_builder.deploy(endpoint_name=ENDPOINT_NAME)
print(f"Endpoint: {endpoint.endpoint_name}")
print(f"Status: {endpoint.endpoint_status}")

# Cell 5: Test Inference

output = endpoint.invoke(
    body=json.dumps(
        {
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "max_tokens": 50,
        }
    ),
    content_type="application/json",
)
print(f"Response: {json.loads(output.body.read())}")

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
