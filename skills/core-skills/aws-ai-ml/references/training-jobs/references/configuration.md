# Training Template Configuration

All templates support notebook and script mode. Notebook-only dependency lines are marked `# NOTEBOOK_ONLY`. Fill every bracketed placeholder before running.

## Common values

| Placeholder | Expected value | Example |
|---|---|---|
| `[PROJECT_DIR]` | Confirmed project root | `./fraud-training` |
| `[ROLE_ARN]` | SageMaker execution role ARN; leave empty only when `get_execution_role()` works | `arn:aws:iam::123456789012:role/SageMakerExecutionRole` |
| `[TRAINING_S3_URI]` | Same-region S3 prefix/object for the training channel | `s3://my-sagemaker-bucket/train/` |
| `[OUTPUT_S3_URI]` | S3 prefix for model artifacts | `s3://my-sagemaker-bucket/output/` |
| `[INSTANCE_TYPE]` | Training instance type verified against quota | `ml.m5.4xlarge` |
| `[BASE_JOB_NAME]` | Human-readable job prefix; the template adds a UUID fragment | `fraud-xgboost` |

Optional verified settings shared by the templates:

- `OUTPUT_KMS_KEY_ID`: KMS key ID/ARN for output artifacts; execution role and caller need the corresponding permissions.
- `CHECKPOINT_S3_URI`: managed checkpoint destination. Required for the custom Spot example; optional for recipe/JumpStart when the selected algorithm supports checkpoints.
- `SUBNETS` and `SECURITY_GROUP_IDS`: provide both to place training containers in a VPC.
- `ENABLE_NETWORK_ISOLATION`: disables container network access; verify required downloads/endpoints remain available.
- `ENABLE_INTER_CONTAINER_TRAFFIC_ENCRYPTION`: enables encryption between distributed training containers and can affect throughput.

These are a bounded, SDK-verified subset rather than an attempt to expose every `CreateTrainingJob` field.

## Recipe template

| Placeholder | Expected value |
|---|---|
| `[RECIPE_NAME_OR_YAML]` | Published SageMaker recipe name or confirmed local YAML path |

Find published names and schemas in the [SageMaker HyperPod recipes catalog](https://github.com/aws/sagemaker-hyperpod-recipes/). `Compute.instance_type` is required. The base recipe plus `RECIPE_OVERRIDES` derives source/image/distributed/compute/hyperparameter settings; explicit networking/output/checkpoint/stopping inputs are applied by `ModelTrainer`. Review `trainer.get_resolved_recipe()` before approval.

`TRAINING_PLAN_ARN` is optional. Populate it only after verifying that the plan matches the requested compute and schedule. `INSTANCE_TYPE` is the required user-confirmed compute input. Leave `INSTANCE_COUNT` and `VOLUME_SIZE_GB` as `None` to preserve recipe/SDK defaults; populate them only when the user explicitly requests an override. Set `TRAINING_IMAGE_URI` only when the selected recipe/provider documentation requires it, using an exact supported tag or digest; recipe requirements may change. Recipe handling has no `accept_eula` parameter; confirm any recipe/provider license prerequisites conversationally.

## JumpStart template

| Placeholder | Expected value |
|---|---|
| `[JUMPSTART_MODEL_ID]` | Exact Hub model ID returned by `model-selection`/Hub discovery |

Pin `MODEL_VERSION` when reproducibility matters. Leave both compute override fields unset to use JumpStart defaults. Set either or both deliberately to override only those values; `OVERRIDE_INSTANCE_COUNT=None` avoids silently forcing a count of one. Set `ACCEPT_EULA=True` only after the user explicitly accepts the gated model license.

## Custom template

| Placeholder | Expected value |
|---|---|
| `[TRAINING_IMAGE_URI]` | Versioned or digest-pinned ECR training image URI; clear when using `ALGORITHM_NAME` |
| `[ALGORITHM_NAME]` | Marketplace algorithm name/ARN; set only when `TRAINING_IMAGE` is empty |
| `[SOURCE_DIR]` | Local/S3 source directory; may be empty for a self-contained image/algorithm |
| `[ENTRY_SCRIPT]` | Script path relative to source directory; required when source directory is set |
| `[REQUIREMENTS]` | Requirements path relative to source directory; optional |

Exactly one of `TRAINING_IMAGE` and `ALGORITHM_NAME` must be non-empty. `SOURCE_DIR` and `ENTRY_SCRIPT` must be provided together. Never silently substitute an unverified `latest` image tag.
