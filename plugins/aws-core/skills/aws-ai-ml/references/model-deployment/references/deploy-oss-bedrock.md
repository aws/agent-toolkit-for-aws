# Deploy OSS Merged LoRA to Bedrock CMI

## Scenario

- **Model Type**: OSS (Open Source)
- **Fine-tuning Method**: LoRA
- **Merge Status**: Merged (`merge_weights: true`)
- **Deployment Target**: Bedrock Custom Model Import (CMI)
- **Approach**: SageMaker PySdk `BedrockModelBuilder`

## Overview

Uses the SageMaker PySdk `BedrockModelBuilder` to import a fine-tuned model into Bedrock as a Custom Model Import (CMI). The builder auto-resolves model artifacts from a training job.

**Required inputs** (collected in the steps below):

- Training job name
- Model name
- IAM role ARN (with Bedrock trust policy and S3 read access)
- AWS region (must be us-east-1, us-east-2, us-west-2, or eu-central-1)

## Prerequisites

### Model Size Limit

Bedrock CMI has a 200GB limit for text models (100GB for multimodal). Check before proceeding: run `aws s3api list-objects-v2 --bucket <bucket> --prefix <prefix>/checkpoints/hf_merged/` and sum the `Size` field from all returned objects.
If the model exceeds 200GB, this pathway cannot be used.

### Required Files

The `hf_merged/` folder must contain: `.safetensors` files, `config.json`, `tokenizer.json`, `tokenizer_config.json`.

### SDK Version

Requires `'sagemaker>=3.7.1,<4.0'` with `BedrockModelBuilder` support.

## Workflow

### Step 1: Gather Training Job Name

The training job name was identified in Step 1 of the main workflow. Confirm you have it.

### Step 2: Gather Model Name

Suggest a name for the deployed model based on the training job or use case. Format: lowercase, alphanumeric with hyphens. Confirm with the user.

### Step 3: Verify IAM Role

Use the IAM role from the training job (extracted in Step 1 of the main workflow via `describe-training-job`). We'll assume this role has the necessary permissions for Bedrock deployment.

### Step 4: Confirm Region

Bedrock CMI is available in: us-east-1, us-east-2, us-west-2, eu-central-1 (this matches the AWS Custom Model Import documentation at the time of writing: https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-import-model.html). There is no public API to query CMI region availability, so this may change over time. Note: attempting CMI in an unsupported region does not return a clean "region not supported" error — it typically fails with an access/authorization-style error — so rely on this list plus the linked docs rather than probing.

The region was identified in Step 1. Confirm it's in the supported list. If not, tell the user that Bedrock deployment is not supported for this model in this region.

### Step 5: Confirm Configuration

> "Here's the deployment setup:
>
> - Deployment target: Bedrock
> - Training Job: [job-name]
> - Model Name: [name]
> - IAM Role: [arn]
> - Region: [region]
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
    "# Deploy to Bedrock"
  ]
}

```

### Cells

Each cell's content comes from `../code_templates/deploy-oss-bedrock.py`, split on the `# Cell N:` comments. Each marker starts a new notebook cell — everything between one marker and the next becomes that cell's content.

- **Cell 1**: Setup (pip install)
- **Cell 2**: Configuration
- **Cell 3**: Flatten S3 Structure and Start Import
- **Cell 4**: Wait for Import to Complete
- **Cell 5**: Test Inference
- **Cell 6**: Save Manifest

### Placeholders

Cell 2:

- `[REGION]` → AWS region
- `[TRAINING_JOB_NAME]` → SageMaker training job name
- `[ROLE_ARN]` → IAM role ARN with Bedrock trust policy and S3 read permissions
- `[MODEL_NAME]` → Name for the imported model

All other cells have no placeholders.

### Step 7: Provide Run Instructions

```
To run:
1. Cell 1 — install/upgrade SageMaker SDK
2. Cell 2 — configuration and imports
3. Cell 3 — flattens S3 structure and starts import job via BedrockModelBuilder
4. Cell 4 — waits for import to complete (typically a few minutes)
5. Cell 5 — test inference with a sample prompt
6. Cell 6 — saves the deployment manifest to `manifests/deploy-<name>.json`

```

## Common Issues

- **"Model weights are larger than 200GB"**: Cannot use this pathway.
- **"No module named 'sagemaker.serve.bedrock_model_builder'"**: Upgrade SDK: `pip install --upgrade 'sagemaker>=3.7.1,<4.0'`
- **Import starts but uses wrong region**: Known issue — `BedrockModelBuilder` defaults to us-east-1. The notebook code overrides this.
- **"Access denied to S3"**: Add S3 read permissions to the IAM role for the model bucket.
- **"Provided IAM role could not be assumed"**: Ensure role has trust policy for `bedrock.amazonaws.com`.

## Post-Deployment Summary

After the notebook runs successfully, tell the user:

- **Model**: `[MODEL_NAME]` has been imported to Bedrock
- **How to invoke**: Use the Bedrock `invoke_model` API with the imported model ARN
- **Billing**: Pay per request — no cost while idle
- **Cleanup**: When done, delete the imported model by running `aws bedrock delete-imported-model --model-identifier <model-name>`.
