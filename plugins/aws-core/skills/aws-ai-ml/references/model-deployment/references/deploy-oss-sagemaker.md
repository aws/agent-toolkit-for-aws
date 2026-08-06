# Deploy OSS LoRA to SageMaker Multi-Adapter Endpoint

## Scenario

- **Model Type**: OSS (Open Source)
- **Fine-tuning Method**: LoRA
- **Merge Status**: Unmerged (`merge_weights: false`)
- **Deployment Target**: SageMaker Multi-Adapter Endpoint
- **Approach**: SageMaker Python SDK v3 `ModelBuilder`, built directly from the training job

## Overview

Builds via `ModelBuilder(model=training_job)`, which resolves the base model S3 URI and serving container image from the training job's model package + JumpStart metadata — no need to manually query `describe-hub-content` and parse the hub content document JSON in the generated code. Requires `'sagemaker>=3.17.0,<4.0'`.

**Right-sizing philosophy — pick a published hosting configuration, do not invent one.** The base model's recipe ships a set of **pre-benchmarked hosting configurations** (published in the hub document under `RecipeCollection[<recipe>].HostingConfigs`; the recipe source repo calls these `inference_configs`). Each configuration is a self-consistent bundle: an instance type, a serving container image, the container environment (tensor-parallel degree and other LMI/vLLM knobs), and the base inference component's compute requirements — all validated together for that instance. Our job is to surface those alternatives and help the customer **choose one**, not to hand-assemble an instance/env combination. This avoids the failure modes of ad-hoc sizing (e.g., a GPU-fit instance that starves the base inference component on host memory, or a max-model-len the instance can't hold).

**Required inputs** (collected in the steps below):

- Training job name (to resolve JumpStart model ID from tags)
- Hosting configuration — chosen from the recipe's published alternatives (Step 2)
- IAM execution role ARN
- AWS region
- EULA acceptance (from Step 4 of the main workflow)

## Prerequisites

### SDK Version

Requires `'sagemaker>=3.17.0,<4.0'`, which adds fine-tuned support to `list_deployment_configs()` / `set_deployment_config()` (paired PR aws/sagemaker-python-sdk#6041).

## Key Gotchas

- **ArtifactUrl for adapter ICs**: An S3 prefix (directory) works despite docs saying it must be `.tar.gz`. No need to repackage.
- **Container version**: LMI 0.31.0 does NOT have the `vllm_async_service` entrypoint. Use `OPTION_ROLLING_BATCH=lmi-dist` instead.
- **Gated models**: Use JumpStart S3 cache via ModelDataSource to avoid needing HF_TOKEN.
- **Endpoint config**: Including ExecutionRoleArn enables inference-component mode. Do NOT include ModelName in ProductionVariants.

## Workflow

### Step 1: Gather Training Job Name

The training job name was identified in Step 1 of the main workflow. Confirm you have it.

This is needed to look up the JumpStart model ID (from training job tags), which `ModelBuilder` uses to resolve the base model S3 URI and container image automatically.

### Step 2: Select a Hosting Configuration

For this step, you need: **which of the recipe's published hosting configurations to deploy.**

Do NOT invent an instance or hand-tune env vars — enumerate the recipe's published configs, present them, and let the customer pick one.

**Enumerate the alternatives with the SDK (preferred).** The SageMaker Python SDK exposes one unified deployment-config API for both base and fine-tuned models — the base "deployment config" vs recipe "hosting config" split is internal and never surfaces here. Build a `ModelBuilder` from the training job and call `list_deployment_configs()`:

```python
from sagemaker.core.resources import TrainingJob
from sagemaker.serve import ModelBuilder

training_job = TrainingJob.get(training_job_name="[TRAINING_JOB_NAME]")
mb = ModelBuilder(model=training_job, role_arn="[ROLE_ARN]")

for cfg in mb.list_deployment_configs():
    args = cfg["DeploymentArgs"]
    print(cfg["DeploymentConfigName"], args["InstanceType"],
          args["Environment"].get("OPTION_TENSOR_PARALLEL_DEGREE"),
          cfg["IsDefault"])

```

Each returned config uses the SAME shape as the base/JumpStart response, so you read it identically for base and fine-tuned models: a top-level `DeploymentConfigName` (the `Default` profile, else the instance type as a stable identifier) plus a nested `DeploymentArgs` block with `InstanceType`, `ImageUri`, `Environment`, and `ComputeResourceRequirements`. `BenchmarkMetrics` is present but empty (recipes publish none today), and an additive `IsDefault` flag marks the recipe's Default config. `list_deployment_configs(instance_type="ml.g6e.48xlarge")` narrows to configs offering that instance type.

**Fallback (only if you cannot run Python during planning):** resolve the same alternatives read-only with the SageMaker APIs — `DescribeTrainingJob` → `OutputModelPackageArn`; `DescribeModelPackage` → `InferenceSpecification.Containers[0].BaseModel` (`HubContentName`, `HubContentVersion`, `RecipeName`); `DescribeHubContent` (`HubName: SageMakerPublicHub`, `HubContentType: Model`) → parse `HubContentDocument.RecipeCollection`, match `RecipeName`, read its `HostingConfigs` (NOT the top-level `InferenceConfigs`). Same configs `list_deployment_configs()` returns, un-normalized.

**Present the alternatives to the customer** as a table, one row per config, e.g.:

| # | Instance | GPUs | Tensor-parallel | Notes |
|---|----------|------|-----------------|-------|
| 1 (Default) | ml.g6.4xlarge | 1× L4 | 1 | Lowest cost; baseline throughput |
| 2 | ml.g6e.48xlarge | 8× L40S | 8 | Highest throughput; most expensive |

Derive GPU model and rough cost/throughput ordering from the instance family and GPU count (more GPUs / newer accelerator = higher throughput and cost). Recommend the **Default** config (the one with `IsDefault: true`) as the baseline, but let the customer pick any alternative:

> "This recipe publishes N benchmarked hosting configurations. The default is **[Default instance]** ([n] GPU). I'd start there; if you need more throughput or longer context, [larger option] is also published. Which would you like?"

- The customer's chosen config determines `INSTANCE_TYPE` (its `InstanceType`) in Cell 2.
- Do NOT mix and match — do not take one config's instance with another's env/TP. Deploy a config as published.
- If the recipe has only one hosting config, present it and confirm.
- If the model has no recipe hosting config at all, `list_deployment_configs()` / `ModelBuilder.build()` fails with "not supported for deployment" / "does not publish any hosting configurations" — that model isn't deployable via this pathway; tell the customer.

**SDK selection mechanism:** apply the customer's choice with `set_deployment_config(instance_type=...)` — the same unified API, selecting by instance type since recipe configs are largely unnamed:

```python
mb.set_deployment_config(instance_type="ml.g6e.48xlarge")

```

It raises if the instance type isn't published (listing the available ones); `get_deployment_config()` returns the config that will be applied. Cell 3 makes exactly this call before `build()`, so the deployed artifact fails loudly on an unpublished instance instead of silently falling back. So:

- **Any config, including the Default:** set `INSTANCE_TYPE` (Cell 2) to that config's `InstanceType` — for the Default, its own instance type. Cell 3's `set_deployment_config(instance_type=INSTANCE_TYPE)` then applies that published config as-is. This covers different-topology alternatives too (e.g. the 8-GPU / TP=8 `ml.g6e.48xlarge` or `ml.p5.48xlarge`).
- **An instance type not published by the recipe:** `set_deployment_config` rejects it outright (listing the published instance types). Always pick a published instance type from Step 2 so the config is self-consistent.

This requires `'sagemaker>=3.17.0,<4.0'`, which adds fine-tuned support to `list_deployment_configs()` / `set_deployment_config()` (paired PR aws/sagemaker-python-sdk#6041). Cell 1 installs it.

⏸ Wait for user to confirm before moving on.

### Step 3: Verify IAM Role

Use the IAM role from the training job (extracted in Step 1 of the main workflow via `describe-training-job`). This role should already have the necessary SageMaker and S3 permissions. Confirm with the user.

### Step 4: Confirm Region

The region was identified in Step 1 of the main workflow. Confirm it with the user.

### Step 5: Confirm Configuration

> "Here's the deployment setup:
>
> - Target: SageMaker Multi-Adapter Endpoint
> - Training Job: [name]
> - Hosting Configuration: [Default | alternative] — [instance] ([n] GPU, tensor-parallel [k])
> - IAM Role: [arn]
> - Region: [region]
>
> Does this look right?"

Show the hosting configuration the customer selected in Step 2 (which config, and its instance / GPU count / tensor-parallel degree), so they know exactly which published bundle is being deployed.

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
    "# Deploy to SageMaker Multi-Adapter Endpoint"
  ]
}

```

### Cells

Each cell's content comes from `../code_templates/deploy-oss-sagemaker.py`, split on the `# Cell N:` comments. Each marker starts a new notebook cell — everything between one marker and the next becomes that cell's content.

- **Cell 1**: Setup (pip install)
- **Cell 2**: Configuration
- **Cell 3**: Build Model
- **Cell 4**: Deploy Endpoint (creates the endpoint, base inference component, and adapter inference component)
- **Cell 5**: Test Inference
- **Cell 6**: Save Manifest

### Placeholders

Cell 2:

- `[REGION]` → AWS region
- `[INSTANCE_TYPE]` → the `InstanceType` of the hosting config selected in Step 2 (e.g., `ml.g6.4xlarge`). Must be a published instance type.
- `[TRAINING_JOB_NAME]` → Training job name (used to look up JumpStart model ID from tags)
- `[ROLE_ARN]` → IAM execution role ARN
- `[ENDPOINT_NAME]` → Name for the endpoint (agent should generate a reasonable default)
- `[ACCEPT_EULA]` → **Meta/Llama models only.** Set to `True` if the user accepted the license in Step 4 of the main workflow. For all other models (Apache 2.0, MIT, Qwen License, etc.), remove the `ACCEPT_EULA` variable and the `model_builder.accept_eula` line entirely — they do not apply and must not appear in the generated code.

### Step 7: Confirm EULA Acceptance (Meta/Llama models only)

**Skip this step for non-Meta models** — the `ACCEPT_EULA` variable and `model_builder.accept_eula` are only relevant for Meta/Llama models. For all other models they must not appear in the generated code.

For Meta/Llama models: confirm the EULA acceptance from Step 4 of the main workflow. Tell the user: "Since you accepted the license agreement, I've set EULA acceptance to `True` in the deployment code." If the user did not accept the license, tell them deployment cannot continue without license acceptance.

### Step 8: Provide Run Instructions

```
To run:
1. Cell 1 — install/upgrade SageMaker SDK
2. Cell 2 — configuration
3. Cell 3 — build the model via ModelBuilder (creates the SageMaker Model; ~30s)
4. Cell 4 — deploy (creates the endpoint plus the base and adapter inference components; waits for InService, ~5-10 min)
5. Cell 5 — test inference with a sample prompt
6. Cell 6 — saves the deployment manifest to `manifests/deploy-<endpoint-name>.json`

```

## Common Issues

- **"No module named 'sagemaker.core'" or "'sagemaker.serve'"**: SDK too old. Upgrade: `pip install --upgrade 'sagemaker>=3.17.0,<4.0'`
- **"ModuleNotFoundError" for vllm_async_service**: Using LMI 0.31.0 container. Use `OPTION_ROLLING_BATCH=lmi-dist` instead of `OPTION_ENTRYPOINT`.
- **Base IC fails health check**: Check `MinMemoryRequiredInMb` fits within instance memory. Reduce if needed.
- **"Inference Component Name header is required"**: Must pass `InferenceComponentName` when invoking the endpoint.
- **Console shows "Missing required key 'ModelName'"**: This is a console UI issue, not a deployment issue. The endpoint works correctly.
- **Adapter IC fails**: Verify adapter weights exist at `<model-s3-uri>/checkpoints/hf/`. Check that the S3 prefix is accessible.

## Post-Deployment Summary

After the notebook runs successfully, tell the user:

- **Endpoint**: `[ENDPOINT_NAME]` is now InService
- **How to invoke**: Use SageMaker runtime `InvokeEndpoint` with `InferenceComponentName` set to the adapter IC name (derived from the endpoint name)
- **Billing**: This endpoint is billed by the hour while running, even when idle. Delete it when you're done testing.
- **Cleanup**: Delete the adapter inference component first, then the base inference component, then the endpoint:
  1. `aws sagemaker delete-inference-component --inference-component-name <adapter-ic-name>`
  2. Wait for deletion to complete, then `aws sagemaker delete-inference-component --inference-component-name <base-ic-name>`
  3. Wait for deletion to complete, then `aws sagemaker delete-endpoint --endpoint-name <endpoint-name>`
