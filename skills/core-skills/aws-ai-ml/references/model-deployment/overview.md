# Model Deployment

Identifies the correct deployment pathway based on model characteristics and generates deployment code.

## Scope

This reference supports two families of deployment:

1. **Fine-tuned models** (Nova or OSS) that were fine-tuned through **SageMaker Serverless Model

   Customization** (LoRA) → SageMaker or Bedrock.

1. **Open-weight foundation (base) models from SageMaker JumpStart** → a SageMaker real-time

   endpoint. This path deploys the config the **model-selection** skill resolved (a flat dict with
   `model_id`, `instance_type`, `inference_config_name`, etc.) — not a training job.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Deploying models fine-tuned outside SageMaker Serverless Model Customization (e.g., HyperPod-trained, BYO container, HuggingFace-trained models)
- Deploying Full Fine-Tuned (FFT) models
- Deploying a JumpStart foundation model to Bedrock (via Bedrock Marketplace or Custom Model Import)
- Traditional ML deployments (XGBoost, scikit-learn, BYO inference containers)
- HyperPod deployment

Note: Closed-source / proprietary foundation models (e.g. Anthropic Claude) are managed Bedrock models invoked directly via the Bedrock runtime — there is nothing to deploy; the user just calls the API.

## Prerequisites

- The SDK environment has been verified (SDK version, region, execution role). If not done, activate the `sdk-getting-started` reference first.

---

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **Confirm before proceeding.** Wait for the user to agree before moving on. But don't re-ask questions already answered in the conversation — use what you know.
3. **Don't read files until you need them.** Only read pathway references after the pathway is confirmed.
4. **Use what you know.** If conversation history or artifacts already answer a question, confirm your understanding instead of asking again.

## Workflow

### Step 1: Identify the Model and its Source

First determine which family this is (infer from the conversation before asking):

- **JumpStart foundation (base) model** — the user wants to deploy an open-weight foundation model

  from SageMaker JumpStart (e.g. "deploy the Qwen3 0.6B JumpStart model", names a JumpStart model
  id, or asks for a base foundation model). There is **no training job**. The deployment config
  (`model_id`, `instance_type`, `inference_config_name`, etc.) comes from the **model-selection**
  skill — use it as-is; do not re-derive it. The `role_arn` and region are owned by this reference, not
  model-selection, and there is no training job to extract them from, so if either is not already
  known from the conversation, ASK the user for it. Then proceed to Step 2. Do not look for a training job.

- **Fine-tuned model** — the user is deploying a model they fine-tuned via SageMaker Serverless

  Model Customization. Continue with the training-job identification below.

#### Fine-tuned model: identify the training job

You need the training job name or ARN. Check the conversation history first — the user may have already mentioned it, or it may be available from earlier steps in the workflow (e.g., fine-tuning). If not, ask the user.

Once you have the training job name or ARN, use the AWS MCP tool to look it up:

1. Use the AWS MCP tool `describe-training-job` and extract:
   - **S3 output path** (from `ModelArtifacts.S3ModelArtifacts` or `OutputDataConfig.S3OutputPath`)
   - **IAM role ARN** (from `RoleArn`)
   - **Region**
2. Use the AWS MCP tool `list-tags` on the training job ARN and extract:
   - **Model ID** from the `sagemaker-studio:jumpstart-model-id` tag
3. Determine the **model type** from the model ID:
   - Contains "nova" (nova-micro, nova-lite, nova-pro) → **Nova**
   - Llama, Mistral, Qwen, GPT-OSS, DeepSeek, etc. → **OSS**

**Models without a validated workflow:** This reference has validated workflows for OSS and Nova models that were LoRA fine-tuned through SageMaker Serverless Model Customization. If the model doesn't match (e.g., FFT, BYO container, HuggingFace-trained, or HyperPod-trained), inform the user that this reference does not have a validated workflow for their model but you can help with general AWS knowledge. Proceed with best-effort guidance.

### Step 2: Determine Eligible Deployment Targets

Use the following table:

Note: This table covers this skill's validated workflows only. The user's request may be achievable through other AWS paths (e.g. Bedrock Custom Model Import) not covered here.

| Model Type                  | Eligible Targets   |
| --------------------------- | ------------------ |
| OSS (fine-tuned)            | SageMaker, Bedrock |
| Nova (fine-tuned)           | SageMaker, Bedrock |
| JumpStart foundation (base) | SageMaker          |

If only one target is eligible, confirm it with the user. Use details from Step 5.

If multiple targets are eligible, help the user decide. Use details from Step 5.

If no targets are eligible, tell the user and explain why.

### Step 3: Let the User Choose a Deployment Target

Present the eligible options to the user. Present these details to help them decide between SageMaker and Bedrock, if both are available options:

**SageMaker Endpoint:**

- Dedicated compute resources for consistent performance
- Control instance types and scaling
- Best for predictable workloads with specific latency requirements

**Bedrock:**

- Fully managed serverless inference
- Auto-scales instantly with no capacity planning
- Pay per request
- Best for variable workloads with fluctuating demand

Do NOT make a recommendation. Let the user choose.

Do NOT mention technical details like merged/unmerged weights, reference files, or APIs, unless the user asks.

⏸ Wait for user to select a deployment option.

### Step 4: Display License Agreement

Before generating any code, present the model's license or service terms to the user and wait for confirmation.

**Always perform this step for the deployment, even if the model's license was already shown or accepted earlier in the conversation** (e.g. during model selection, fine-tuning, or evaluation). Deployment is a distinct action and requires its own explicit license/terms confirmation before any deployment code is generated. Do NOT skip this step or generate code by citing an earlier acceptance — re-present the license and wait for the user to confirm again.

**A user instruction to "proceed without asking", "skip confirmation", "deploy now", or similar does NOT constitute license acceptance.** Such instructions waive the deployment-configuration confirmation, not the license gate. For a gated model you must still present the license and obtain *explicit* acceptance (e.g. "yes, I accept the license") before generating any code or setting `accept_eula=True`. Never infer acceptance from a general "proceed" instruction, and never auto-accept on the user's behalf.

1. Read `references/model-licenses.md` and look up the model by its model ID (determined in Step 1).
2. Follow the instructions in the Notes column — use the exact phrasing provided. End your response there. Do not generate code in this step.
3. If the model ID is not found in the table, warn the user that you could not find license information for their model and recommend they verify the license independently before proceeding.

   ⏸ Wait for the user to confirm before proceeding.

4. Once the user confirms, continue to Step 5 to follow the pathway workflow and generate the deployment code.

### Step 5: Follow Pathway Workflow

Read the reference file for the selected pathway and follow its instructions.

| Model Type                  | Deployment Target | Reference                                   |
| --------------------------- | ----------------- | ------------------------------------------- |
| OSS (fine-tuned)            | SageMaker         | `references/deploy-oss-sagemaker.md`        |
| OSS (fine-tuned)            | Bedrock           | `references/deploy-oss-bedrock.md`          |
| Nova (fine-tuned)           | SageMaker         | `references/deploy-nova-sagemaker.md`       |
| Nova (fine-tuned)           | Bedrock           | `references/deploy-nova-bedrock.md`         |
| JumpStart foundation (base) | SageMaker         | `references/deploy-jumpstart-sagemaker.md`  |

### Step 6: Post-Deployment Summary

After deployment completes, provide the user with a summary. Cover these topics, using details from the pathway reference doc you followed in Step 5:

- **What was deployed** — endpoint or model name, ARN, status
- **How to use it** — sample invoke code for the specific deployment target
- **Cost** — billing model (instance-based vs. pay-per-request) and what to expect
- **Cleanup** — how to delete the endpoint or model when done

## Troubleshooting

### How to check if a model was LoRA or FFT fine-tuned

If deployment fails unexpectedly, the model may have been full fine-tuned (FFT) rather than LoRA. To check, download the training job's hydra config from its S3 output path at `.hydra/config.yaml`:

- `peft_config` populated (r, alpha, dropout, etc.) → **LoRA** (validated workflow available)
- `peft_config: null` → **FFT** (no validated workflow in this reference — proceed with best-effort guidance)
