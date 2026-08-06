# RLAIF (Reinforcement Learning from AI Feedback) Template — Custom Reward Prompt

# Cell 0 [markdown]: Fine-Tuning

# Cell 1: Install Dependencies

# %pip install --upgrade 'sagemaker>=3.7.1,<4.0' boto3 -q  # NOTEBOOK_ONLY

# Cell 2: Setup & Credentials

import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from sagemaker.ai_registry.air_constants import REWARD_PROMPT
from sagemaker.ai_registry.dataset import DataSet
from sagemaker.ai_registry.evaluator import Evaluator
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.resources import ModelPackageGroup
from sagemaker.train.common import TrainingType
from sagemaker.train.rlaif_trainer import RLAIFTrainer

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

# Setup
sm_client = boto3.Session().client("sagemaker")
sagemaker_session = Session(sagemaker_client=sm_client)
bucket = sagemaker_session.default_bucket()

# Configuration - USER please fill in these fields with your information:

BASE_MODEL = ""  # Sagemaker Hub model id
TRAINING_DATA_S3 = ""  # S3 path
S3_OUTPUT_PATH = f"s3://{bucket}/finetuning-output/"
ROLE_ARN = get_execution_role()  # You can change this to a specific role
ACCEPT_EULA = (
    False  # Set to True to accept the base model's End-User License Agreement (OSS models only)
)
MODEL_PACKAGE_GROUP_NAME = ""  # Auto-generated based on use case

# Reward model — the Bedrock LLM used as judge
# Available models and regions: see references/rlaif_guide.md
REWARD_MODEL_ID = ""

# Cell 3: Register Custom Reward Prompt

# Insert path to the custom Jinja prompt file (usually ../scripts/custom_reward_prompt.jinja)
CUSTOM_PROMPT_PATH = ""

reward_prompt_evaluator = Evaluator.create(
    name="[GENERATE A NAME FOR THE EVALUATOR HERE]",  # lowercase alphanumeric + hyphens, max 20 chars
    type=REWARD_PROMPT,
    source=CUSTOM_PROMPT_PATH,
    sagemaker_session=sagemaker_session,
    wait=True,
)
REWARD_PROMPT_ARN = reward_prompt_evaluator.arn
print(f"Reward Prompt Evaluator ARN: {REWARD_PROMPT_ARN}")

# Cell 4: Create Dataset and Model Package Group

# Create Model Package Group
try:
    model_package_group = ModelPackageGroup.create(
        model_package_group_name=MODEL_PACKAGE_GROUP_NAME,
        model_package_group_description="",
    )
    print(f"Created new model package group named {MODEL_PACKAGE_GROUP_NAME}")
except ClientError as e:
    if e.response["Error"]["Code"] in ("ResourceInUse", "ValidationException"):
        model_package_group = ModelPackageGroup.get(
            model_package_group_name=MODEL_PACKAGE_GROUP_NAME
        )
        print(
            f"There is already a model package group with the name {MODEL_PACKAGE_GROUP_NAME}.\nIf you want to save your finetuned model under a different name, change the value of MODEL_PACKAGE_GROUP_NAME in the previous cell."
        )
    else:
        raise

# Create Dataset
dataset = DataSet.create(name=MODEL_PACKAGE_GROUP_NAME, source=TRAINING_DATA_S3, wait=True)
TRAINING_DATASET_ARN = dataset.arn

print(f"Here is your model package group ARN: {model_package_group.model_package_group_arn}\n")
print(f"Here is your training dataset ARN: {dataset.arn}")

# Cell 5: Configure Trainer

trainer = RLAIFTrainer(
    model=BASE_MODEL,
    model_package_group=model_package_group,
    reward_model_id=REWARD_MODEL_ID,
    reward_prompt=REWARD_PROMPT_ARN,  # ARN of the registered custom prompt evaluator
    training_dataset=TRAINING_DATASET_ARN,
    s3_output_path=S3_OUTPUT_PATH,
    sagemaker_session=sagemaker_session,
    # accept_eula=ACCEPT_EULA,  # Uncomment for Meta models
    role=ROLE_ARN,
)

print("Here are the recommended hyperparameters for the current training job:")
print(f"Batch size:    {trainer.hyperparameters.global_batch_size}")
print(f"Learning rate: {trainer.hyperparameters.learning_rate}")
print(f"Epochs:        {trainer.hyperparameters.max_epochs}")

# Cell 6: Hyperparameter Overrides

# To change a hyperparameter, uncomment its corresponding line, and set the value you want.

# Note: If the value you choose is not supported for your model, you will get an error indicating the allowed range.

# Uncomment the following line to change the learning rate
# trainer.hyperparameters.learning_rate = 0.0002

# Uncomment the following line to change the batch size
# trainer.hyperparameters.global_batch_size = 16

# Uncomment the following line to change the number of epochs
# trainer.hyperparameters.max_epochs = 5

# Cell 7: Start Training

# Start training
training_job = trainer.train(wait=True)

print(f"Training Job Name: {training_job.training_job_name}")
print(f"Training Status: {training_job.training_job_status}")

# Save manifest
manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"training-{training_job.training_job_name}.json"
manifest_path.write_text(
    json.dumps(
        {
            "training_job_name": training_job.training_job_name,
            "model_package_group_name": MODEL_PACKAGE_GROUP_NAME,
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")

# Cell 8: Plot and Display Metrics  # NOTEBOOK_ONLY_SECTION

import matplotlib.pyplot as plt
import mlflow
from mlflow.tracking import MlflowClient

run_id = training_job.mlflow_details.mlflow_run_id
mlflow.set_tracking_uri(training_job.mlflow_config.mlflow_resource_arn)
client = MlflowClient()

metrics = [
    "critic/rewards/mean",
    "response_length/mean",
    "actor/entropy_loss",
    "actor/grad_norm",
    "critic/advantages/mean",
]

fig, axes = plt.subplots(1, len(metrics), figsize=(4 * len(metrics), 3))
for idx, metric in enumerate(metrics):
    history = client.get_metric_history(run_id, metric)
    if history:
        axes[idx].plot(
            [h.step for h in history],
            [h.value for h in history],
            linewidth=2,
            marker="o",
            markersize=4,
        )
        axes[idx].set_xlabel("Step")
        axes[idx].set_ylabel(metric.split("/")[-1])
        axes[idx].set_title(metric, fontweight="bold")
        axes[idx].grid(True, alpha=0.3)

plt.suptitle(f"Training Metrics: {training_job.training_job_name}", fontweight="bold")
plt.tight_layout()
plt.show()
