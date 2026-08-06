# Deploy Nova LoRA to Bedrock (PySDK BedrockModelBuilder)

## Scenario

- **Model Type**: Nova
- **Fine-tuning Method**: LoRA
- **Deployment Target**: Bedrock Custom Model
- **Approach**: SageMaker PySdk `BedrockModelBuilder`

## Overview

Uses the SageMaker PySdk `BedrockModelBuilder` to deploy a Nova fine-tuned LoRA model to Bedrock as a Custom Model. The builder auto-detects Nova models and calls `CreateCustomModel`.

**Required inputs** (collected in the steps below):

- Training job name
- Custom model name
- IAM role ARN
- AWS region

## Prerequisites

Requires SageMaker Python SDK >= 3.7.0 with `BedrockModelBuilder` Nova support (installed by Cell 1).

## Workflow

### Important Instructions

- Make sure to use dedicated tools instead of bash commands whenever possible

### Step 1: Gather Training Job Name

The training job name was identified in Step 1 of the main workflow. Confirm you have it.

### Step 2: Gather Custom Model Name

For this step, you need: **a name for the deployed custom model.**

Suggest a name based on the training job or use case, e.g., `nova-micro-bedrock-<timestamp>`. Ask the user to confirm or provide their own.

⏸ Wait for user before moving on.

### Step 3: Verify IAM Role

Use the IAM role from the training job (extracted in Step 1 of the main workflow via `describe-training-job`). We'll assume this role has the necessary permissions for Bedrock deployment.

### Step 4: Confirm Region

The region was identified in Step 1 of the main workflow. Nova → Bedrock deployment is supported in **us-east-1** (this may be outdated — region availability can change and there is no API to query it). If the training job is in a different region, warn the user that Bedrock deployment for this model is likely limited to us-east-1; if an import is attempted elsewhere and fails (note: Nova → Bedrock uses Custom Model Import under the hood, so an unsupported region typically returns an access/authorization-style error rather than a clear region error), confirm it is not supported there.

### Step 5: Confirm Configuration

> "Here's the deployment setup:
>
> - Deployment target: Bedrock (Custom Model)
> - Training Job: [job-name]
> - Custom Model Name: [name]
> - IAM Role: [arn]
> - Region: us-east-1
>
> Does this look right?"

⏸ Wait for user approval.

### Step 6: Generate Code

Read `../references/code_output_guide.md` for output format rules.

If a project directory already exists (from earlier in the workflow), use it. Otherwise, load the **directory-management** reference to set one up.

⏸ Wait for user.

## Code Structure

### Markdown Header

```json
{
  "cell_type": "markdown",
  "metadata": {},
  "source": [
    "# Deploy Nova to Bedrock"
  ]
}

```

### Cells

Each cell's content comes from `../code_templates/deploy-nova-bedrock.py`, split on the `# Cell N:` comments. Each marker starts a new notebook cell — everything between one marker and the next becomes that cell's content.

- **Cell 1**: Setup (pip install)
- **Cell 2**: Configuration (env vars, imports, placeholders)
- **Cell 3**: Build and Deploy to Bedrock (blocks until deployment is Active)
- **Cell 4**: Test Inference
- **Cell 5**: Save Manifest

### Placeholders

Cell 2:

- `[REGION]` → AWS region (us-east-1)
- `[TRAINING_JOB_NAME]` → SageMaker training job name
- `[ROLE_ARN]` → IAM role ARN
- `[CUSTOM_MODEL_NAME]` → Name for the custom model

All other cells have no placeholders.

### Step 7: Provide Run Instructions

```
To run:
1. Cell 1 — install SDK packages
2. Cell 2 — set configuration values
3. Cell 3 — creates custom model via BedrockModelBuilder and deploys (blocks until Active)
4. Cell 4 — test inference with a sample prompt via Converse API
5. Cell 5 — saves the deployment manifest to `manifests/deploy-<name>.json`

```

## Common Issues

- **"ServiceQuotaExceededException: The number of custom models in Creating status has reached the quota limit"**: Too many concurrent model creations. Wait for in-progress models to finish, or delete old custom models.
- **"No module named 'sagemaker.serve.bedrock_model_builder'"**: Re-run Cell 1 to install the required packages, then restart the kernel.
- **"Access denied to S3"**: Add S3 read permissions to the IAM role for the model artifacts bucket.
- **"Provided IAM role could not be assumed"**: Ensure role has trust policy for `bedrock.amazonaws.com`.
- **Deployment status "Failed"**: Check CloudTrail for the `CreateCustomModel` event to see the failure reason.
