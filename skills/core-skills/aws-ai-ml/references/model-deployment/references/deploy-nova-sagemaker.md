# Deploy Nova LoRA to SageMaker

## Scenario

- **Model Type**: Nova
- **Fine-tuning Method**: LoRA
- **Deployment Target**: SageMaker Single Model Endpoint
- **Approach**: SageMaker ModelBuilder

## Overview

Deploys a Nova fine-tuned model to a SageMaker endpoint using `ModelBuilder`.

Nova deploys as a model-on-variant (no inference components), so you invoke the endpoint directly without specifying an `InferenceComponentName`.

**Required inputs** (collected in the steps below):

- Training job name
- Instance type
- IAM execution role ARN
- AWS region
- Endpoint name

## Prerequisites

Requires SageMaker Python SDK >= 3.7.0 (installed by Cell 1).

## Workflow

### Important Instructions

- Make sure to use dedicated tools instead of bash commands whenever possible

### Step 1: Gather Training Job Name

The training job name was identified in Step 1 of the main workflow. Confirm you have it.

### Step 2: Determine Instance Type

For this step, you need: **the instance type.**

First, determine the Nova variant from the training job's model package. Use your AWS tool to run `sagemaker describe-training-job` for the training job name and extract the `OutputModelPackageArn` from the response. Then inspect the model package to find the `hub_content_name` (e.g., `nova-textgeneration-micro`).

The following are supported instances by Nova variant (smallest to largest); larger instances support longer context lengths. Treat this as a starting point that may be outdated — instance support changes over time and there is no API that enumerates the supported instance types for a model package. Pick from the list below; if the deploy call rejects the instance type, first try the next larger size within the same family (e.g. ml.g5.12xlarge → ml.g5.24xlarge), and if no larger size is available, escalate to the next family (g5 → g6 → p5).

Nova Micro (`nova-textgeneration-micro`): ml.g5.12xlarge, ml.g5.24xlarge, ml.g6.12xlarge, ml.g6.24xlarge, ml.g6.48xlarge, ml.p5.48xlarge

Nova Lite (`nova-textgeneration-lite`): ml.g6.48xlarge, ml.p5.48xlarge

Nova Lite v2 (`nova-textgeneration-lite-v2`): ml.p5.48xlarge

Nova Pro (`nova-textgeneration-pro`): ml.g6.48xlarge, ml.p5.48xlarge

Present the supported instance types and ask which one the user would like to use. The larger instances will be more expensive, but have larger context windows.

⏸ Wait for user to confirm before moving on.

### Step 3: Verify IAM Role

Use the IAM role from the training job (extracted in Step 1 of the main workflow via `describe-training-job`). This role should already have the necessary SageMaker and S3 permissions. Confirm with the user.

### Step 4: Confirm Region

The region was identified in Step 1 of the main workflow. Nova deployment is supported in: us-east-1, us-west-2, eu-west-2, ap-northeast-1. There is no API that returns feature-level region availability for Nova, so this list may be outdated — treat it as guidance. If the user's region is not listed, warn them it is likely unsupported; if a deploy is attempted in an unlisted region and fails with a region/availability or access error, tell the user Nova SageMaker deployment is not available in that region.

### Step 5: Choose Endpoint Name

Suggest a name based on the model, e.g., `nova-micro-deploy-<timestamp>`. Ask the user to confirm or provide their own.

⏸ Wait for user before moving on.

### Step 6: Confirm Configuration

> "Here's the deployment setup:
>
> - Model: [base-model-name] fine-tuned with LoRA (e.g., "Nova Micro fine-tuned with LoRA")
> - Deployment target: SageMaker Endpoint
> - Training Job: [name]
> - Instance Type: [type]
> - IAM Role: [arn]
> - Region: [region]
> - Endpoint Name: [name]
>
> Does this look right?"

⏸ Wait for user approval.

### Step 7: Generate Code

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
    "# Deploy Nova Fine-Tuned Model to SageMaker"
  ]
}

```

### Cells

Each cell's content comes from `../code_templates/deploy-nova-sagemaker.py`, split on the `# Cell N:` comments. Each marker starts a new notebook cell — everything between one marker and the next becomes that cell's content.

- **Cell 1**: Setup (pip install)
- **Cell 2**: Configuration
- **Cell 3**: Build Model
- **Cell 4**: Deploy Endpoint
- **Cell 5**: Test Inference
- **Cell 6**: Save Manifest

### Placeholders

Cell 2:

- `[REGION]` → AWS region
- `[TRAINING_JOB_NAME]` → Training job name
- `[ROLE_ARN]` → IAM execution role ARN
- `[INSTANCE_TYPE]` → SageMaker instance type (e.g., `ml.g5.12xlarge`)
- `[ENDPOINT_NAME]` → Endpoint name

## Step 8: Provide Run Instructions

```
To run:
1. Cell 1 — install SDK packages, then restart the kernel before continuing
2. Cell 2 — set configuration values
3. Cell 3 — build model via ModelBuilder (~30s, creates SageMaker Model resource)
4. Cell 4 — deploy endpoint (waits for InService, ~10-15 min)
5. Cell 5 — test inference with a sample prompt
6. Cell 6 — saves the deployment manifest to `manifests/deploy-<endpoint-name>.json`

```

## Common Issues

- **"No module named 'sagemaker.core'" or "No module named 'sagemaker.train'"**: Re-run Cell 1 to install the required packages, then restart the kernel.
- **"Must setup local AWS configuration with a region"**: Set `AWS_DEFAULT_REGION` env var or configure `~/.aws/config`
- **"Cannot create already existing endpoint configuration"**: An endpoint with that name already exists. Use a different name or delete the existing one first.
- **Endpoint fails to reach InService**: Check CloudWatch logs for the endpoint. Common causes: wrong instance type for the model size, or IAM role missing permissions.
