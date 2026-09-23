"""Probe agent-advisor model/path recommendations in the target AWS account."""

import argparse
import datetime
import json
import pathlib


SCHEMAS = pathlib.Path(__file__).parent / "schemas"
PROMPT = "Reply with exactly: ok"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _default_mantle_client(region):
    try:
        from anthropic import AnthropicBedrockMantle
    except ImportError as exc:
        raise RuntimeError(
            "Mantle verification requires the anthropic package with "
            "AnthropicBedrockMantle support"
        ) from exc
    return AnthropicBedrockMantle(aws_region=region)


def _default_runtime_client(region):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("Runtime verification requires boto3") from exc
    return boto3.client("bedrock-runtime", region_name=region)


def _default_openai_responses_client(region):
    """Lazily build an OpenAI SDK client pointed at the Bedrock Mantle endpoint.

    Imports are deferred so the offline recommendation/verify code path never
    requires the openai or token-generator packages.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Mantle Responses verification requires the openai package"
        ) from exc
    try:
        from aws_bedrock_token_generator import provide_token
    except ImportError as exc:
        raise RuntimeError(
            "Mantle Responses verification requires aws-bedrock-token-generator"
        ) from exc
    base_url = f"https://bedrock-mantle.{region}.api.aws/openai/v1"
    return OpenAI(base_url=base_url, api_key=provide_token(region=region))


def _probe_openai_responses(client, model_id):
    return client.responses.create(model=model_id, input=PROMPT)


def _response_model_id(response):
    if isinstance(response, dict):
        return response.get("model") or response.get("modelId")
    return getattr(response, "model", None)


def _probe_mantle(client, model_id):
    return client.messages.create(
        model=model_id,
        max_tokens=8,
        messages=[{"role": "user", "content": PROMPT}],
    )


def _probe_converse(client, model_id):
    return client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 8},
    )


def _probe_invoke(client, model_id):
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8,
        "messages": [{"role": "user", "content": PROMPT}],
    }
    return client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body).encode("utf-8"),
    )


def _base_result(workload_id, recommendation):
    identity = recommendation.get("model_identity") or {}
    verification = recommendation["verification"]
    return {
        "workload_id": workload_id,
        "decision_status": recommendation["decision_status"],
        "api_path": recommendation.get("api_path"),
        "path_model_id": identity.get("path_model_id"),
        "invocation_model_id": recommendation.get("invocation_model_id"),
        "region": verification["region"],
        "status": "not_run",
        "checked_at": None,
        "response_model_id": None,
        "error": None,
    }


def verify_workload(
    workload_id,
    recommendation,
    mantle_client_factory=None,
    runtime_client_factory=None,
    openai_responses_client_factory=None,
    now=None,
):
    result = _base_result(workload_id, recommendation)
    if recommendation["decision_status"] != "recommended":
        result["status"] = "not_applicable"
        return result

    checked_at = now or _utc_now()
    result["checked_at"] = checked_at
    model_id = result["invocation_model_id"]
    if not model_id:
        result["status"] = "needs_resolution"
        result["error"] = {
            "type": "UnresolvedInvocationModelId",
            "message": (
                "Resolve an account-invocable inference profile ID before probing; "
                "the verifier will not substitute a model ID."
            ),
        }
        return result

    path = result["api_path"]
    try:
        if path == "mantle_messages":
            factory = mantle_client_factory or _default_mantle_client
            response = _probe_mantle(factory(result["region"]), model_id)
        elif path == "mantle_openai_responses":
            factory = openai_responses_client_factory or _default_openai_responses_client
            response = _probe_openai_responses(factory(result["region"]), model_id)
        elif path == "runtime_converse":
            factory = runtime_client_factory or _default_runtime_client
            response = _probe_converse(factory(result["region"]), model_id)
        elif path == "runtime_invoke":
            factory = runtime_client_factory or _default_runtime_client
            response = _probe_invoke(factory(result["region"]), model_id)
        else:
            raise ValueError(f"verification is not implemented for API path: {path}")
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return result

    result["status"] = "passed"
    result["response_model_id"] = _response_model_id(response)
    return result


def verify_recommendation(
    recommendation,
    workload_ids=None,
    mantle_client_factory=None,
    runtime_client_factory=None,
    openai_responses_client_factory=None,
    now=None,
):
    selected = set(workload_ids or recommendation["workloads"])
    unknown = sorted(selected - set(recommendation["workloads"]))
    if unknown:
        raise ValueError(f"workload not found in recommendation: {', '.join(unknown)}")

    generated_at = now or _utc_now()
    workloads = {}
    for workload_id, workload in recommendation["workloads"].items():
        if workload_id not in selected:
            continue
        workloads[workload_id] = verify_workload(
            workload_id,
            workload,
            mantle_client_factory=mantle_client_factory,
            runtime_client_factory=runtime_client_factory,
            openai_responses_client_factory=openai_responses_client_factory,
            now=generated_at,
        )
    return {
        "schema_version": 1,
        "recommendation_schema_version": recommendation["schema_version"],
        "generated_at": generated_at,
        "workloads": workloads,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="probe agent-advisor Bedrock model/path recommendations"
    )
    parser.add_argument("recommendation", type=pathlib.Path)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="defaults to model-verification.json beside the recommendation",
    )
    parser.add_argument(
        "--workload",
        action="append",
        dest="workloads",
        help="probe only this workload id; repeat to select more than one",
    )
    args = parser.parse_args(argv)

    import jsonschema

    recommendation = json.loads(args.recommendation.read_text())
    jsonschema.validate(
        recommendation,
        json.loads((SCHEMAS / "model-recommendation.json").read_text()),
    )
    result = verify_recommendation(recommendation, workload_ids=args.workloads)
    jsonschema.validate(
        result,
        json.loads((SCHEMAS / "model-verification.json").read_text()),
        format_checker=jsonschema.FormatChecker(),
    )
    output = args.output or args.recommendation.parent / "model-verification.json"
    output.write_text(json.dumps(result, indent=2) + "\n")

    statuses = {item["status"] for item in result["workloads"].values()}
    failed = statuses.intersection({"failed", "needs_resolution"})
    print(
        f"RESULT={'failed' if failed else 'ok'} "
        f"WORKLOADS={len(result['workloads'])}"
    )
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
