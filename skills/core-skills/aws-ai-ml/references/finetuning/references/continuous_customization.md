# Continuous Customization (Multi-Round Fine-Tuning)

Adds a subsequent fine-tuning round on top of an already-customized model. Uses the Model Package ARN from a previous training job as the base model instead of a SageMakerHub model name.

---

## Prerequisites

| Requirement                                                                  | How to obtain                                                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Training data S3 path for current round                                      | Collect from the conversation context, ask user if not available                      |
| Confirmation that data is in correct format for current finetuning strategy  | From dataset-evaluation reference or user is sure it's correct                            |
| Fine-tuning technique                                                        | If not available from context, ask which technique for this round: SFT, DPO, RLVR, or RLAIF |
| Previous model package group name                                            | From the prior output, or help the user find it (Section A instructions)              |
| Previous training job name                                                   | Ask user or get from user's account (Section B instructions)                          |
| Reward function for RLVR as a Lambda Evaluator                               | Ask user if they have one, otherwise follow rlvr_reward_function.md to create one     |
| Reward prompt as a RewardPrompt Evaluator and reward model id for RLAIF      | Ask user if they have one, otherwise follow `rlaif_guide.md`                          |

---

## Output Placement

The output format (notebook or script) should already be established from the conversation context — do not re-ask if it has already been decided. If necessary, the output format guide is in `references/code_output_guide.md`.

- **Notebook mode**: If the user has an existing notebook from the previous round, append these cells under a new markdown header describing the round, e.g., `## DPO Fine-Tuning (Round 2)`. If no prior notebook exists, create a new one with a name reflecting the use case and techniques, e.g., `news-app-sft-to-dpo.ipynb`.
- **Script mode**: Write a new numbered `.py` file in `<project-dir>/scripts/`, e.g., `02_dpo_finetuning_round2.py`. Use `# %%` cell markers to separate logical sections.

---

## Section A: Setup & Credentials

Re-establishes session variables. Required to ensure all variables are defined.

### Agent Instructions

1. Set `NEW_TRAINING_DATA_S3` to the user's dataset S3 path for the current round.
2. Set `PREVIOUS_MODEL_PACKAGE_GROUP_NAME`:
   - **If the prior output is available**: Copy the model package group name from it.
   - **If not**: Run `aws sagemaker list-model-package-groups` with these flags:

     ```
     --query 'ModelPackageGroupSummaryList[].{Name:ModelPackageGroupName,Status:ModelPackageGroupStatus,Created:CreationTime}'
     --output table

     ```

     Optionally add `--name-contains <keyword>` to filter by name.

   - **If you can't identify the name from the list**: Ask the user.

### Code

```python
import boto3
from sagemaker.ai_registry.dataset import DataSet
from sagemaker.core.resources import ModelPackageGroup
from sagemaker.core.helper.session_helper import Session, get_execution_role

# Setup
sm_client = boto3.Session().client("sagemaker")
sagemaker_session = Session(sagemaker_client=sm_client)
bucket = sagemaker_session.default_bucket()
S3_OUTPUT_PATH = f"s3://{bucket}/finetuning-output/"
ROLE_ARN = get_execution_role()

# Configuration
NEW_TRAINING_DATA_S3 = ""  # S3 path to the dataset for this round
PREVIOUS_MODEL_PACKAGE_GROUP_NAME = ""  # Model package group name from the previous round

```

---

## Section B: Retrieve Previous Model Package ARN

Looks up the model package ARN from the previous training job.

### Agent Instructions

1. Ask the user if they have the training job name from the previous fine-tuning round or need help finding it.
2. **If the user provides the name** → Set it as `previous_training_job_name` in the code.
3. **If the user needs help** → Run `aws sagemaker list-training-jobs` with these flags:

   ```
   --status-equals Completed
   --query 'TrainingJobSummaries[].{Name:TrainingJobName,Status:TrainingJobStatus,Created:CreationTime}'
   --output table

   ```

   Present the results and let the user pick the correct job.

4. **If the user is unsure and wants to fill it later** → Leave the placeholder `<previous_training_job_name>` and tell them to replace it before running.

### Code

```python
from sagemaker.core.resources import TrainingJob

previous_training_job_name = "<previous_training_job_name>"  # USER: paste your previous training job name here
job = TrainingJob.get(training_job_name=previous_training_job_name)
previous_model_package_arn = job.output_model_package_arn
print(f"Previous Model Package ARN: {previous_model_package_arn}")

```

> **Troubleshooting**: If this cell throws `ValidationException: Requested resource not found`, the job name is wrong or the output is connected to a different AWS region than where the job ran. Verify the region with `boto3.Session().region_name`.

---

## Section C: Register New Dataset

Registers the current round's training data as a versioned `DataSet`.

### Agent Instructions

- Set `name` to something descriptive of the use case and round, e.g., `"customer-support-chatbot-dpo-round2"`.

### Code

```python
from sagemaker.ai_registry.dataset import DataSet

dataset = DataSet.create(
    name="<dataset_name>",
    source=NEW_TRAINING_DATA_S3,
    wait=True
)
new_dataset_arn = dataset.arn
print(f"New Training Dataset ARN: {new_dataset_arn}")

```

---

## Section D: Add Evaluators

If necessary, use this section to register the custom RLVR reward function or custom RLAIF reward prompt as an evaluator on SageMaker AI Hub Registry.

```python
from sagemaker.ai_registry.evaluator import Evaluator
from sagemaker.ai_registry.air_constants import REWARD_FUNCTION, REWARD_PROMPT

evaluator = Evaluator.create(
    name="",
    type=REWARD_FUNCTION,  # Use REWARD_FUNCTION for RLVR, REWARD_PROMPT for RLAIF
    source="",  # Path to reward function or prompt file
    sagemaker_session=sagemaker_session,
    wait=True
)

print(f"Evaluator ARN: {evaluator.arn}")

```

---

## Section E: Configure and Start Training

Runs the next fine-tuning round. The key difference from the first round: `model` receives `previous_model_package_arn` instead of a base model name.

### Agent Instructions

Choose the trainer class matching the user's technique for this round and pass additional inputs if needed:

| Technique | Import                                                    | Additional Trainer inputs                          |
| --------- | --------------------------------------------------------- | -------------------------------------------------- |
| SFT       | `from sagemaker.train.sft_trainer import SFTTrainer`      |                                                    |
| DPO       | `from sagemaker.train.dpo_trainer import DPOTrainer`      |                                                    |
| RLVR      | `from sagemaker.train.rlvr_trainer import RLVRTrainer`    | `custom_reward_function`                           |
| RLAIF     | `from sagemaker.train.rlaif_trainer import RLAIFTrainer`  | `reward_prompt`, `reward_model_id`, `built_in_metrics` |

### Code (SFT example — swap trainer class for DPO/RLVR/RLAIF)

```python
from sagemaker.train.sft_trainer import SFTTrainer
from sagemaker.train.common import TrainingType

step2_trainer = SFTTrainer(
    model=previous_model_package_arn,
    training_type=TrainingType.LORA,
    model_package_group=PREVIOUS_MODEL_PACKAGE_GROUP_NAME,
    training_dataset=new_dataset_arn,
    s3_output_path=S3_OUTPUT_PATH,
    sagemaker_session=sagemaker_session,
    role=ROLE_ARN,
)
step2_job = step2_trainer.train(wait=True)

print(f"Training Job Name for current round: {step2_job.training_job_name}")
print(f"Training Status: {step2_job.training_job_status}")

```

---

## Rules

- ✅ Reuse the same `PREVIOUS_MODEL_PACKAGE_GROUP_NAME` from the first round so all model versions stay grouped together
- ❌ Do NOT pass `accept_eula` — it only applies to the initial base model download
- ❌ Do NOT re-create the `ModelPackageGroup` — it already exists from the first round
