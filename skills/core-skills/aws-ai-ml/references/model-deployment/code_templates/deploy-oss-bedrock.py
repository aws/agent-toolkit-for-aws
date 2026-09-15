# Cell 0 [markdown]: Model Deployment — Bedrock

# Cell 1: Setup

# %pip install --upgrade 'sagemaker>=3.7.1,<4.0' --quiet  # NOTEBOOK_ONLY

# Cell 2: Configuration

import json
import time

import boto3
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.resources import TrainingJob
from sagemaker.serve.bedrock_model_builder import BedrockModelBuilder

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

REGION = "[REGION]"
TRAINING_JOB_NAME = "[TRAINING_JOB_NAME]"
ROLE_ARN = "[ROLE_ARN]"
MODEL_NAME = "[MODEL_NAME]"

sm = boto3.client("sagemaker", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

# Cell 3: Flatten S3 Structure and Start Import

# BedrockModelBuilder passes the root model artifacts path to Bedrock CMI,
# but Bedrock expects config.json at the root of the URI. This cell copies
# files from checkpoints/hf_merged/ to the model artifacts root (server-side).

tj = sm.describe_training_job(TrainingJobName=TRAINING_JOB_NAME)
root = tj["ModelArtifacts"]["S3ModelArtifacts"]
parts = root.replace("s3://", "").split("/", 1)
bucket, root_prefix = parts[0], parts[1].rstrip("/") + "/"
hf_prefix = root_prefix + "checkpoints/hf_merged/"

resp = s3.list_objects_v2(Bucket=bucket, Prefix=root_prefix + "config.json", MaxKeys=1)
if resp.get("KeyCount", 0) > 0:
    print("Files already at root, skipping copy")
else:
    paginator = s3.get_paginator("list_objects_v2")
    copied = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=hf_prefix):
        for obj in page.get("Contents", []):
            filename = obj["Key"].replace(hf_prefix, "")
            if not filename or filename.endswith("/"):
                continue
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": obj["Key"]},
                Key=root_prefix + filename,
            )
            copied += 1
    print(f"Copied {copied} files to root")

training_job = TrainingJob.get(training_job_name=TRAINING_JOB_NAME, region=REGION)
builder = BedrockModelBuilder(model=training_job)

result = builder.deploy(
    job_name=MODEL_NAME,
    imported_model_name=MODEL_NAME,
    role_arn=ROLE_ARN,
)

job_arn = result["jobArn"]
print(f"Import job created: {job_arn}")

# Cell 4: Wait for Import to Complete

bedrock = boto3.client("bedrock", region_name=REGION)

while True:
    resp = bedrock.get_model_import_job(jobIdentifier=job_arn)
    status = resp["status"]
    print(f"Status: {status}")

    if status == "Completed":
        model_arn = resp["importedModelArn"]
        print(f"\nModel imported successfully!")
        print(f"Model ARN: {model_arn}")
        break
    elif status in ("Failed", "Stopped"):
        raise RuntimeError(f"Import {status}: {resp.get('failureMessage', 'Unknown error')}")

    time.sleep(30)

# Cell 5: Test Inference

print("Testing inference (model may need a few minutes to warm up)...")
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)

for attempt in range(1, 25):
    try:
        response = bedrock_runtime.invoke_model(
            modelId=model_arn,
            body=json.dumps(
                {
                    "prompt": "What is the capital of France?",
                    "max_gen_len": 50,
                    "temperature": 0.7,
                }
            ),
        )
        result = json.loads(response["body"].read())
        print(f"Response: {json.dumps(result)[:300]}")
        break
    except bedrock_runtime.exceptions.ModelNotReadyException:
        print(f"  Attempt {attempt}: Model not ready, waiting 30s...")
        time.sleep(30)
else:
    print("Model did not become ready after 12 minutes.")

# Cell 6: Save Manifest
# Save manifest - record output of workflow step for future reference
from pathlib import Path

manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"deploy-{TRAINING_JOB_NAME}.json"
manifest_path.write_text(
    json.dumps(
        {
            "model_id": model_arn,
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")
