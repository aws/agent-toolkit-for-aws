"""
Retrieves all deployable models from a SageMaker Hub and outputs structured metadata as JSON.

Usage:
    python get_deployable_models.py <hub-name> [region]

Arguments:
    hub-name    Name of the SageMaker Hub to query (e.g., SageMakerPublicHub)
    region      Optional AWS region override (defaults to boto3 session default)

Output:
    JSON array of model objects with fields: name, data_types, input_modalities,
    output_modalities, size, license, languages, context_window, model_type,
    framework, provider, tasks, bedrock_eligible.
"""

import json
import sys

import boto3
import botocore.exceptions


def get_deployable_models(hub_name, region_name=None):
    """Query a SageMaker Hub and return structured model metadata.

    Args:
        hub_name: Name of the SageMaker Hub.
        region_name: Optional AWS region override.

    Returns:
        List of model dicts with extracted metadata fields.
    """
    sm_client = boto3.client("sagemaker", region_name=region_name)

    # Retrieve all models with pagination
    all_contents = []
    next_token = None

    while True:
        params = {
            "HubName": hub_name,
            "HubContentType": "Model",
            "MaxResults": 100,
        }

        if next_token:
            params["NextToken"] = next_token

        response = sm_client.list_hub_contents(**params)
        all_contents.extend(response.get("HubContentSummaries", []))

        next_token = response.get("NextToken")
        if not next_token:
            break

    # All hub models are deployable to SageMaker endpoints.
    # Extract structured metadata from search keywords for filtering.
    results = []
    for model in all_contents:
        keywords = model.get("HubContentSearchKeywords", [])
        entry = {
            "name": model.get("HubContentName"),
        }

        for kw in keywords:
            if kw.startswith("@data-type:"):
                entry.setdefault("data_types", []).append(kw.split(":", 1)[1])
            elif kw.startswith("@input-modality:"):
                entry.setdefault("input_modalities", []).append(kw.split(":", 1)[1])
            elif kw.startswith("@output-modality:"):
                entry.setdefault("output_modalities", []).append(kw.split(":", 1)[1])
            elif kw.startswith("@model-size:"):
                entry["size"] = kw.split(":", 1)[1]
            elif kw.startswith("@license:"):
                entry["license"] = kw.split(":", 1)[1]
            elif kw.startswith("@language:"):
                entry.setdefault("languages", []).append(kw.split(":", 1)[1])
            elif kw.startswith("@context-window:"):
                entry["context_window"] = kw.split(":", 1)[1]
            elif kw.startswith("@model-type:"):
                entry["model_type"] = kw.split(":", 1)[1]
            elif kw.startswith("@framework:"):
                # Framework (e.g., "pytorch", "tensorflow") stored separately from provider.
                # The filter script matches against 'provider' field only; framework is
                # preserved for informational purposes.
                entry["framework"] = kw.split(":", 1)[1]
            elif kw.startswith("@provider:"):
                entry["provider"] = kw.split(":", 1)[1]
            elif kw.startswith("@task:"):
                entry.setdefault("tasks", []).append(kw.split(":", 1)[1])

        # Bedrock eligibility
        entry["bedrock_eligible"] = "@capability:bedrock_console" in keywords

        # Original creation time for sorting by recency
        original_creation_time = model.get("OriginalCreationTime")
        if original_creation_time:
            entry["original_creation_time"] = (
                original_creation_time.isoformat()
                if hasattr(original_creation_time, "isoformat")
                else str(original_creation_time)
            )

        results.append(entry)

    return results


def list_available_values(models):
    """Extract all unique values for each metadata field across all models.

    Returns a dict of field_name -> sorted list of unique values.
    """
    values: dict[str, set[str]] = {
        "tasks": set(),
        "data_types": set(),
        "input_modalities": set(),
        "output_modalities": set(),
        "sizes": set(),
        "licenses": set(),
        "languages": set(),
        "context_windows": set(),
        "model_types": set(),
        "providers": set(),
        "frameworks": set(),
    }

    for model in models:
        for task in model.get("tasks", []):
            values["tasks"].add(task)
        for dt in model.get("data_types", []):
            values["data_types"].add(dt)
        for im in model.get("input_modalities", []):
            values["input_modalities"].add(im)
        for om in model.get("output_modalities", []):
            values["output_modalities"].add(om)
        if "size" in model:
            values["sizes"].add(model["size"])
        if "license" in model:
            values["licenses"].add(model["license"])
        for lang in model.get("languages", []):
            values["languages"].add(lang)
        if "context_window" in model:
            values["context_windows"].add(model["context_window"])
        if "model_type" in model:
            values["model_types"].add(model["model_type"])
        if "provider" in model:
            values["providers"].add(model["provider"])
        if "framework" in model:
            values["frameworks"].add(model["framework"])

    return {k: sorted(v) for k, v in values.items()}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_deployable_models.py <hub-name> [--list-values] [region]")
        sys.exit(1)

    args = sys.argv[1:]
    list_values_mode = False
    if "--list-values" in args:
        list_values_mode = True
        args.remove("--list-values")

    if not args:
        print("Usage: python get_deployable_models.py <hub-name> [--list-values] [region]")
        sys.exit(1)

    hub_name = args[0]
    region_name = args[1] if len(args) > 1 else None

    try:
        results = get_deployable_models(hub_name, region_name)
    except botocore.exceptions.ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"Error: AWS API call failed ({error_code}): {error_msg}", file=sys.stderr)
        sys.exit(1)
    except botocore.exceptions.NoCredentialsError:
        print(
            "Error: No AWS credentials found. Configure credentials via 'aws configure' or environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)
    except botocore.exceptions.EndpointConnectionError as e:
        print(f"Error: Could not connect to SageMaker endpoint: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if list_values_mode:
        print(json.dumps(list_available_values(results)))
    else:
        print(json.dumps(results))
