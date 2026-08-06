# Deploy a JumpStart Foundation Model to a SageMaker Endpoint

## Scenario

- **Model Type**: open-weight foundation model resolved through **SageMaker JumpStart** (a base

  model, identified by a JumpStart model id — NOT a fine-tuned training job)

- **Deployment Target**: SageMaker real-time endpoint
- **Approach**: SageMaker Python SDK v3 `ModelBuilder.from_jumpstart_config(...)`, deployed from the

  **deployment config emitted by the model-selection skill**

## Overview

Deploys a base JumpStart foundation model to a real-time endpoint. This pathway is the deployment
half of the base-model flow: the **model-selection** skill chose the model and instance type (and,
where the model has hosting configs, the config it optimized for) and hands them over. This skill
maps those onto the v3 SDK config objects and does **not** re-derive anything from the model spec.
It is a thin passthrough with safe defaults for the fields model-selection does not supply (see the
input contract below).

The v3 SDK (`sagemaker>=3.7.1`) has **no** `sagemaker.jumpstart` module and **no** `JumpStartModel`
class. A JumpStart model is deployed by building a `JumpStartConfig` + `Compute` and calling
`ModelBuilder.from_jumpstart_config(...)`. The SDK resolves the serving container, environment, and
inference-component sizing internally from the config — the deployment code never digs into the
model spec or `HubContentDocument`.

### The input contract (from model-selection)

The template consumes a flat `CONFIG` dict. model-selection's Step 6 hand-off emits **three**
fields — `model_id`, `instance_type`, and `inference_config_name`. The remaining fields are
deployment-side with safe defaults.

| Config field            | v3 destination                                    | Producer / default                                              |
| ----------------------- | ------------------------------------------------- | --------------------------------------------------------------- |
| `model_id`              | `JumpStartConfig.model_id` (required)             | **model-selection** (Hub model ID)                              |
| `instance_type`         | `Compute.instance_type` (required)                | **model-selection** (user-confirmed)                            |
| `inference_config_name` | `JumpStartConfig.inference_config_name`           | **model-selection** (the config it chose; `null` when the model has no labeled configs) |
| `model_version`         | `JumpStartConfig.model_version` (`None` → `"*"`)  | deployment default `None` (latest) unless supplied              |
| `instance_count`        | `Compute.instance_count`                          | deployment default `1` unless supplied                          |
| `accept_eula`           | `JumpStartConfig.accept_eula`                     | deployment-owned (set at the Step 4 license gate)               |
| `env_vars`              | `from_jumpstart_config(env_vars=...)`             | deployment default `None` unless supplied                       |

`inference_config_name` is tri-state: a real config name deploys that specific config; `None` lets
the SDK resolve the spec's top-ranked config; `None` for a model with no labeled configs is a plain
base deploy. Deployment honors whatever value it receives — never override it. model-selection emits
the config it chose precisely so deployment does not fall back to the top-ranked config (which may
not support the `instance_type` that was derived from the chosen config — see "Instance ↔ config
consistency" below).

`model_id` and `instance_type` are **both required** for a real-time endpoint. The template
fails fast if either is missing.

### Hardening the hand-off

The config comes from another skill, so treat it as untrusted. The template's Cell 2 defines
`validate_deployment_config(cfg)` and calls it before building — it fails fast with a clear,
actionable message when the config is missing fields or otherwise broken, rather than failing deep
in the SDK or silently misbehaving. It checks:

- `CONFIG` is a dict (a `None`/list/string hand-off is rejected with a readable error)
- `model_id` and `instance_type` are non-empty strings and not un-substituted placeholders
- `instance_count` is a positive integer (`bool` rejected — it is a subclass of `int`)
- `model_version` is a string or `None`
- `inference_config_name` is a non-empty name or `None` (an empty string would be treated as a

  real config name and fail deep in the SDK)

- `accept_eula` is a **real bool** — a non-bool such as the string `"false"` is truthy in Python

  and could silently auto-accept a gated model's license, so it is rejected (a safety check)

- `env_vars` is `None` or a flat dict of string → string

Keep this validator in the generated notebook. It is the runtime guard; the agent-time check in
Step 1 is the first line of defence.

### Deployment-owned fields (NOT from model-selection)

`role_arn`, `endpoint_name`, and `model_name` are owned by this skill, not model-selection. Collect
them in the steps below.

## Prerequisites

### SDK Version

Requires `sagemaker>=3.7.1` (the template pins `>=3.7.1,<4.0` to guard against a future v4 breaking
this API the way v2→v3 did). Do not use the v2 `JumpStartModel` / `sagemaker.enums.EndpointType`
/ `sagemaker.compute_resource_requirements` imports — they do not exist in v3.

## Key Gotchas

- **Do not re-resolve the config.** model-selection already picked `instance_type` and

  `inference_config_name`. Do not call `get_config_names` / `list_deployment_configs` or read the
  `HubContentDocument` here — pass the dict through. The SDK resolves container/env/sizing from the
  config name.

- **`inference_config_name` must be valid or `None`.** A name the model doesn't expose fails inside

  `from_jumpstart_config`. model-selection validates the name against `get_config_names` before
  emitting it, so treat a non-`None` value as trusted.

- **Instance ↔ config consistency.** If both `instance_type` and `inference_config_name` are set,

  the instance must be in that config's `supported_inference_instance_types` (server-side ranking
  rejects otherwise). model-selection guarantees this; surface the SDK error cleanly if it occurs.

- **Gated models**: `accept_eula` defaults to `False`, which is safe for non-gated models. It is set

  to `True` only after the user explicitly accepted the license in Step 4. Whether a model is gated
  is given by the **Gated (EULA)** column in `model-licenses.md` (a `Yes` row is gated — e.g.
  Meta/Llama, Gemma, NVIDIA Nemotron, Llama 4, Qwen License Agreement); it is a property of the
  license terms, not the vendor. Never auto-accept.

## Topology note (single-model endpoint)

`from_jumpstart_config(...).deploy(endpoint_name=...)` deploys a **single-model real-time
endpoint**. Inference-component (IC) packing is not part of this contract yet — adding it requires
a new field in the model-selection → deployment config (e.g. `endpoint_type` plus resource
requirements) so both skills agree. Until that field exists, deploy the single-model endpoint as
above.

## Workflow

### Step 1: Confirm and validate the deployment config

You should already have the config dict from the model-selection skill (`model_id`,
`instance_type`, `inference_config_name`, etc.). Before generating any code, sanity-check the
hand-off:

- It must contain a non-empty `model_id` and `instance_type`.
- `accept_eula`, if present, must be a boolean (not a string).
- `inference_config_name`, if present, must be a real name or `null` — never an empty string.

If the config is missing, not a dict, or missing either required field, do **not** generate a
deploy notebook. Go back to the model-selection skill to produce a valid config rather than
guessing values. The generated notebook also self-validates at runtime (see "Hardening the
hand-off" above), but catching it here avoids emitting a notebook that will fail.

### Step 2: Verify IAM Role

`role_arn` is owned by this skill, not model-selection, and a JumpStart base deploy has no training
job to extract it from. Use the IAM execution role identified in Step 1 of the main workflow; if it
is not already known, ASK the user for the IAM execution role ARN. Confirm it with the user.

### Step 3: Confirm Region

The region was identified in Step 1 of the main workflow. If it is not already known, ASK the user
for the AWS region. Confirm it with the user.

### Step 4: Confirm Configuration

> "Here's the deployment setup:
>
> - Target: SageMaker real-time endpoint
> - JumpStart model: [model_id]
> - Inference config: [inference_config_name, or "SDK top-ranked default"]
> - Instance type: [instance_type] x [instance_count]
> - IAM Role: [role_arn]
> - Region: [region]
>
> Does this look right?"

⏸ Wait for user approval.

### Step 5: Generate Code

Read `../references/code_output_guide.md` for output format rules.

If a project directory already exists (from earlier in the workflow), use it. Otherwise, activate
the **directory-management** skill to set one up.

⏸ Wait for user.

## Code Structure

### Markdown Header

Begin the notebook with a markdown cell whose only content is the title
`# Deploy a JumpStart Foundation Model to SageMaker`.

### Cells

Each cell's content comes from `../code_templates/deploy-jumpstart-sagemaker.py`, split on the
`# Cell N:` comments. Each marker starts a new notebook cell.

- **Cell 1**: Setup (pip install)
- **Cell 2**: Configuration and validation (the config dict from model-selection + deployment-owned

  fields, plus `validate_deployment_config` which runs before the build)

- **Cell 3**: Build the model via `from_jumpstart_config`
- **Cell 4**: Deploy and wait for InService
- **Cell 5**: Test Inference
- **Cell 6**: Save Manifest

### Placeholders

The `CONFIG` dict fields (from model-selection):

- `[MODEL_ID]` → JumpStart model id (e.g. `huggingface-reasoning-qwen3-06b`)
- `[INSTANCE_TYPE]` → the instance type model-selection resolved

Leave `model_version` (`None` → latest), `inference_config_name` (`None` → SDK top-ranked, or a
name from model-selection), `instance_count`, and `env_vars` as model-selection provided them.

Deployment-owned fields:

- `[REGION]` → AWS region
- `[ROLE_ARN]` → IAM execution role ARN
- `[ENDPOINT_NAME]` → name for the endpoint (agent generates a reasonable default)
- `[MODEL_NAME]` → name for the model resource (agent generates a reasonable default)
- `[PROJECT_DIR]` → project directory (for the manifest)

`accept_eula` is a config field (not a `[...]` placeholder): it defaults to `False`, which is the
safe default and correct for non-gated models — leave it as-is for them. Set it to `True` ONLY
after the user explicitly accepted a gated model's license in Step 4 of the main workflow. A model
is gated when its **Gated (EULA)** column in `model-licenses.md` is `Yes` (Meta/Llama, Gemma,
NVIDIA Nemotron, Llama 4, Qwen License Agreement, etc.), not just Meta/Llama. Never auto-accept.

### Step 6: Set the `accept_eula` flag in the generated code (gated models)

The license gate is Step 4 of the main `model-deployment` workflow: the license is shown and the
user accepts it *before* any code is generated in Step 5. This subsection is **not** another gate —
it only sets the value of the `accept_eula` flag in the template that was already generated. Set it
based on whether the model is gated (**Gated (EULA)** column in `model-licenses.md`):

- **Not gated** (`No`): leave `accept_eula=False`. This is the default and needs no change.
- **Gated** (`Yes`): set `accept_eula=True` only once the user accepted the license at the Step 4

  gate. If they did not accept, leave it `False` and tell them deployment cannot continue without
  license acceptance.

> **A user instruction to "proceed without asking", "skip confirmation", "deploy now", or similar
> is NOT license acceptance.** Those phrases waive the deployment-config confirmation, not the
> gated-license gate. For a gated model, `accept_eula` may be set to `True` ONLY after the user has
> *explicitly* accepted that model's license (e.g. "yes, I accept the license"). If the user only
> asked you to proceed but never explicitly accepted, keep `accept_eula=False`, present the license,
> and wait — do not auto-accept on their behalf.

### Step 7: Provide Run Instructions

```
To run:
1. Cell 1 — install/upgrade the SageMaker SDK
2. Cell 2 — configuration (the model-selection config dict + role/region/names)
3. Cell 3 — build the model from the JumpStart config
4. Cell 4 — deploy (waits for the endpoint to be InService, ~10-15 min)
5. Cell 5 — test inference with a sample prompt
6. Cell 6 — save the deployment manifest to `manifests/deploy-<endpoint-name>.json`

```

## Common Issues

- **`ValueError` from `validate_deployment_config`**: the config dict from model-selection is

  missing a field or has a wrong type (e.g. `accept_eula` as a string, an empty
  `inference_config_name`, a non-positive `instance_count`). The message names the offending field
  — fix it in model-selection's output rather than editing the value by hand in the notebook.

- **"No module named 'sagemaker.jumpstart'"** or **`JumpStartModel` not found**: v2 imports on the

  v3 SDK — deploy via `ModelBuilder.from_jumpstart_config(...)`, not `JumpStartModel`.

- **`inference_config_name` rejected in `from_jumpstart_config`**: the name isn't one of the

  model's configs. It should have come from model-selection's `get_config_names` — re-check the
  config dict or set it to `None` to use the SDK's top-ranked default.

- **Instance-type rejected for the chosen config**: `instance_type` is not in the config's

  `supported_inference_instance_types`. model-selection should have validated this — go back and
  re-resolve the pair.

- **Capacity error on a scarce GPU instance**: the config's recommended instance family may be

  capacity-constrained — reach out to AWS Support / your account team (a Service Quotas increase
  does not guarantee capacity), or have model-selection pick a different config.

## Post-Deployment Summary

After the notebook runs successfully, tell the user:

- **Endpoint**: `[ENDPOINT_NAME]` is now InService, running `[MODEL_ID]` on `[INSTANCE_TYPE]`.
- **How to invoke**: use the SageMaker runtime `InvokeEndpoint`.
- **Billing**: this endpoint is billed by the hour while running, even when idle. Delete it when

  you're done testing.

- **Cleanup**: delete the endpoint (and its endpoint config / model) using the AWS MCP tool

  (`delete-endpoint`, then `delete-endpoint-config`, then `delete-model`).
