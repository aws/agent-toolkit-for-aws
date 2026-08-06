# Cell 0 [markdown]: Deploy a JumpStart Foundation Model to SageMaker

# Cell 1: Setup

# %pip install --upgrade "sagemaker>=3.7.1,<4.0" --quiet  # NOTEBOOK_ONLY

# Cell 2: Configuration and validation

import json
import os
from pathlib import Path

# CONFIG is the deployment config emitted by the model-selection skill. Do NOT re-derive any of
# these fields from the model spec here — model-selection already resolved them. This skill is a
# thin passthrough onto the v3 SDK's from_jumpstart_config API.
CONFIG = {
    "model_id": "[MODEL_ID]",  # REQUIRED — JumpStart model id, e.g. "huggingface-reasoning-qwen3-06b"
    "model_version": None,  # None -> "*" (latest)
    "instance_type": "[INSTANCE_TYPE]",  # REQUIRED for a real-time endpoint
    "instance_count": 1,
    "inference_config_name": None,  # a name from get_config_names, or None -> SDK top-ranked config
    "accept_eula": False,  # True ONLY after explicit acceptance of a gated model's license
    "env_vars": None,  # optional; merged over the config's defaults
}

# Runtime fields owned by deployment (NOT emitted by model-selection).
REGION = "[REGION]"
ROLE_ARN = "[ROLE_ARN]"
ENDPOINT_NAME = "[ENDPOINT_NAME]"
MODEL_NAME = "[MODEL_NAME]"
TAGS = [{"Key": "created-by", "Value": "sagemaker-agent-skill"}]  # add user-provided tags too

os.environ["AWS_DEFAULT_REGION"] = REGION


def validate_deployment_config(cfg):
    """Fail fast with a clear, actionable message if the model-selection config is missing or
    malformed. This guards the deployment against a broken hand-off — a bad config should stop
    here with a readable error, not fail deep inside the SDK or (worse) silently misbehave.
    """
    if not isinstance(cfg, dict):
        raise ValueError(
            f"Deployment config from model-selection must be a dict, got {type(cfg).__name__}. "
            "Re-run the model-selection skill to produce a valid config."
        )
    # model_id and instance_type are both required for a real-time endpoint. Reject empty values
    # and un-substituted placeholders (e.g. "[MODEL_ID]").
    for key in ("model_id", "instance_type"):
        val = cfg.get(key)
        if not isinstance(val, str) or not val.strip() or val.startswith("["):
            raise ValueError(
                f"Deployment config is missing a valid '{key}' (got {val!r}). "
                "model-selection must emit it before deployment can proceed."
            )
    # instance_count must be a positive integer (bool is a subclass of int — reject it explicitly).
    ic = cfg.get("instance_count", 1)
    if isinstance(ic, bool) or not isinstance(ic, int) or ic < 1:
        raise ValueError(
            f"'instance_count' must be an integer >= 1, got {ic!r}. "
            "model-selection must emit a valid instance_count."
        )
    # model_version is a non-empty string or None (None -> latest). An empty/whitespace string
    # would reach JumpStartConfig(model_version="") and fail deep in the SDK.
    mv = cfg.get("model_version")
    if mv is not None and (not isinstance(mv, str) or not mv.strip()):
        raise ValueError(
            f"'model_version' must be a non-empty string or None (None -> latest), got {mv!r}."
        )
    # inference_config_name is tri-state: a non-empty config name, or None for the SDK top-ranked
    # config. An empty string would be treated as a real config name and fail deep in the SDK.
    icn = cfg.get("inference_config_name")
    if icn is not None and (not isinstance(icn, str) or not icn.strip()):
        raise ValueError(
            "'inference_config_name' must be a non-empty config name or None "
            "(use None for the SDK's top-ranked config)."
        )
    # accept_eula MUST be a real bool. A non-bool such as the string "false" is truthy in Python
    # and could silently auto-accept a gated model's license — a safety issue, so reject it.
    eula = cfg.get("accept_eula", False)
    if not isinstance(eula, bool):
        raise ValueError(
            f"'accept_eula' must be a boolean, got {type(eula).__name__} ({eula!r}). "
            "A non-bool value could silently auto-accept a gated model's license."
        )
    # env_vars is None or a flat dict of string -> string.
    ev = cfg.get("env_vars")
    if ev is not None and (
        not isinstance(ev, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in ev.items())
    ):
        raise ValueError(
            "'env_vars' must be None or a dict of string keys to string values. "
            "model-selection must emit it in that shape."
        )


validate_deployment_config(CONFIG)

# Cell 3: Build the model from the JumpStart config

# Cell 2 is intentionally SDK-free (stdlib only) so validate_deployment_config runs without the
# SageMaker SDK installed/importable; the SDK imports and set_attribution therefore live here in
# the build cell rather than the config cell.
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.jumpstart.configs import JumpStartConfig
from sagemaker.core.training.configs import Compute
from sagemaker.serve import ModelBuilder

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

# Map the validated config dict onto the two v3 SDK config objects. The SDK resolves the serving
# container, environment, and inference-component sizing internally from inference_config_name
# (None -> the spec's top-ranked config). accept_eula is a field on JumpStartConfig.
js = JumpStartConfig(
    model_id=CONFIG["model_id"],
    model_version=CONFIG.get("model_version"),  # None -> "*"
    inference_config_name=CONFIG.get("inference_config_name"),
    accept_eula=CONFIG.get("accept_eula", False),
)
compute = Compute(
    instance_type=CONFIG["instance_type"],
    instance_count=CONFIG.get("instance_count", 1),
)
mb = ModelBuilder.from_jumpstart_config(
    jumpstart_config=js,
    compute=compute,
    role_arn=ROLE_ARN,
    env_vars=CONFIG.get("env_vars") or None,
)
model = mb.build(model_name=MODEL_NAME)
print(f"Model built: {getattr(model, 'model_arn', MODEL_NAME)}")

# Cell 4: Deploy to a real-time endpoint and wait for InService

import boto3

# from_jumpstart_config() deploys a single-model real-time endpoint. deploy() blocks until the
# endpoint is InService and returns a core Endpoint (use .invoke() on it).
endpoint = mb.deploy(endpoint_name=ENDPOINT_NAME)
print(f"Deployed {CONFIG['model_id']} to endpoint '{ENDPOINT_NAME}'.")

# Tag for cost attribution / observability.
sm = boto3.client("sagemaker", region_name=REGION)
endpoint_arn = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)["EndpointArn"]
sm.add_tags(ResourceArn=endpoint_arn, Tags=TAGS)

# Cell 5: Test Inference

result = endpoint.invoke(
    body=json.dumps(
        {"inputs": "What is the capital of France?", "parameters": {"max_new_tokens": 50}}
    ),
    content_type="application/json",
)
print(f"Response: {result.body.read().decode('utf-8')}")

# Cell 6: Save Manifest
# Save manifest - record output of workflow step for future reference
from pathlib import Path

manifest_dir = Path("[PROJECT_DIR]") / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
manifest_path = manifest_dir / f"deploy-{ENDPOINT_NAME}.json"
manifest_path.write_text(
    json.dumps(
        {
            "endpoint_name": ENDPOINT_NAME,
            "model_name": MODEL_NAME,
            "model_id": CONFIG["model_id"],
            "model_version": CONFIG.get("model_version"),
            "instance_type": CONFIG["instance_type"],
            "inference_config_name": CONFIG.get("inference_config_name"),
        },
        indent=2,
    )
)
print(f"Manifest saved: {manifest_path}")
