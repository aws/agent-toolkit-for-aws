# Cell 0 [markdown]: Model Evaluation

# Cell 1: Configuration

# Set AWS region before importing SageMaker SDK
import os

REGION = "[REGION]"
os.environ["AWS_DEFAULT_REGION"] = REGION

# %pip install --upgrade 'sagemaker>=3.7.1,<4.0' --quiet  # NOTEBOOK_ONLY

import json
from pathlib import Path

from sagemaker.core import Attribution, set_attribution
from sagemaker.train.evaluate import LLMAsJudgeEvaluator

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

# Suppress verbose logging from SageMaker SDK
import logging

logging.getLogger("sagemaker").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)

# Evaluation configuration
MODEL = "[MODEL_ARN]"
DATASET = "[DATASET_S3_URI]"
EVALUATOR_MODEL = "[JUDGE_MODEL]"
BUILTIN_METRICS = [METRICS_LIST]
CUSTOM_METRICS = None
# NOTE FOR AGENT: If user wishes to use custom metrics,
# custom_metrics.json should have been generated previously in the project root.
# Uncomment this code to load the custom metrics from that file:
# CUSTOM_METRICS = json.loads((Path("[PROJECT_DIR]") / "custom_metrics.json").read_text())
S3_OUTPUT = "[S3_OUTPUT_PATH]"
EVALUATE_BASE = [TRUE_OR_FALSE]

# MLflow configuration
MLFLOW_EXPERIMENT_NAME = "[MLFLOW_EXPERIMENT_NAME]"

# Cell 2: Start Evaluation

# Build evaluator kwargs
evaluator_kwargs = dict(
    model=MODEL,
    evaluator_model=EVALUATOR_MODEL,
    dataset=DATASET,
    s3_output_path=S3_OUTPUT,
    evaluate_base_model=EVALUATE_BASE,
    region=REGION,
    mlflow_experiment_name=MLFLOW_EXPERIMENT_NAME,
)

if BUILTIN_METRICS:
    evaluator_kwargs["builtin_metrics"] = BUILTIN_METRICS
if CUSTOM_METRICS:
    evaluator_kwargs["custom_metrics"] = json.dumps(CUSTOM_METRICS)

evaluator = LLMAsJudgeEvaluator(**evaluator_kwargs)

print("✅ Starting evaluation...")
print(f"Model: {MODEL}")
print(f"Dataset: {DATASET}")
print(f"Judge: {EVALUATOR_MODEL}")
if BUILTIN_METRICS:
    print(f"Built-in metrics: {BUILTIN_METRICS}")
if CUSTOM_METRICS:
    print(f"Custom metrics: {len(CUSTOM_METRICS)} defined")

execution = evaluator.evaluate()

print(f"\n✅ Evaluation job started!")
print(f"Job ARN: {execution.arn}")
print(f"Job Name: {execution.name}")
print(f"Status: {execution.status.overall_status}")

# Cell 3: Wait for Completion

execution.wait(target_status="Succeeded", poll=30)

# Cell 4: Show Results

# Display evaluation results
# If evaluate_base_model was True, this shows a comparison between base and custom model
execution.show_results()

# Save manifest
manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"eval-{execution.name}.json"
manifest_path.write_text(
    json.dumps(
        {
            "evaluation_arn": execution.arn,
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")
