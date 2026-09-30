import json
import pathlib

import jsonschema
import pytest

import model_recommendation
import verify_model_path


NOW = "2026-07-20T12:00:00+00:00"


def _input(requirements=None):
    return {
        "schema_version": 2,
        "region": "us-east-1",
        "primary_unit": "support-agent",
        "workloads": [
            {
                "workload_id": "support-agent",
                "source": {
                    "provider": "anthropic",
                    "model_ids": ["claude-3-7-sonnet-latest"],
                    "sdk": "anthropic",
                    "api_surface": "messages",
                    "source_paths": ["src/agent.py"],
                },
                "requirements": {
                    "priority": "balanced",
                    "critical_features": ["tool_use"],
                    **(requirements or {}),
                },
                "detected_features": [],
            }
        ],
    }


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or type(
            "Response", (), {"model": "anthropic.claude-sonnet-5"}
        )()
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeMantleClient:
    def __init__(self, messages=None):
        self.messages = messages or FakeMessages()


class FakeRuntimeClient:
    def __init__(self):
        self.converse_calls = []
        self.invoke_calls = []

    def converse(self, **kwargs):
        self.converse_calls.append(kwargs)
        return {"modelId": kwargs["modelId"]}

    def invoke_model(self, **kwargs):
        self.invoke_calls.append(kwargs)
        return {}


def _verify(requirements=None, **kwargs):
    recommendation = model_recommendation.recommend(_input(requirements))
    return verify_model_path.verify_recommendation(
        recommendation, now=NOW, **kwargs
    )


def test_mantle_probe_uses_recommended_clean_id():
    client = FakeMantleClient()
    result = _verify(mantle_client_factory=lambda region: client)
    verification = result["workloads"]["support-agent"]

    assert verification["status"] == "passed"
    assert verification["response_model_id"] == "anthropic.claude-sonnet-5"
    assert client.messages.calls[0]["model"] == "anthropic.claude-sonnet-5"
    assert client.messages.calls[0]["max_tokens"] == 8


def test_converse_probe_uses_resolved_cris_without_substitution():
    client = FakeRuntimeClient()
    result = _verify(
        {
            "governance": ["guardrails"],
            "data_residency": "global_allowed",
        },
        runtime_client_factory=lambda region: client,
    )
    verification = result["workloads"]["support-agent"]

    assert verification["status"] == "passed"
    assert (
        client.converse_calls[0]["modelId"]
        == "global.anthropic.claude-sonnet-5"
    )


def test_invoke_probe_uses_native_bedrock_body():
    client = FakeRuntimeClient()
    result = _verify(
        {
            "requires_native_payload": True,
            "data_residency": "global_allowed",
        },
        runtime_client_factory=lambda region: client,
    )
    verification = result["workloads"]["support-agent"]
    body = json.loads(client.invoke_calls[0]["body"])

    assert verification["status"] == "passed"
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert body["messages"][0]["content"] == verify_model_path.PROMPT


def test_unresolved_runtime_cris_does_not_create_client():
    calls = []
    result = _verify(
        {"governance": ["guardrails"]},
        runtime_client_factory=lambda region: calls.append(region),
    )
    verification = result["workloads"]["support-agent"]

    assert verification["status"] == "needs_resolution"
    assert verification["invocation_model_id"] is None
    assert calls == []


def test_probe_failure_is_structured():
    client = FakeMantleClient(FakeMessages(error=PermissionError("denied")))
    result = _verify(mantle_client_factory=lambda region: client)
    verification = result["workloads"]["support-agent"]

    assert verification["status"] == "failed"
    assert verification["error"] == {
        "type": "PermissionError",
        "message": "denied",
    }


def test_decision_required_is_not_probed():
    result = _verify(
        {
            "preserve_messages_api": True,
            "governance": ["guardrails"],
        }
    )

    assert result["workloads"]["support-agent"]["status"] == "not_applicable"


def test_verification_output_matches_schema():
    result = _verify(mantle_client_factory=lambda region: FakeMantleClient())
    schema = json.loads(
        (
            pathlib.Path(verify_model_path.__file__).parent
            / "schemas"
            / "model-verification.json"
        ).read_text()
    )

    jsonschema.validate(
        result,
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


# --- OpenAI provider verification (mocked, no network) ---------------------


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or type("Resp", (), {"model": "openai.gpt-5.6-sol"})()
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeOpenAIClient:
    def __init__(self, responses=None):
        self.responses = responses or FakeResponses()


def _openai_input(requirements=None):
    return {
        "schema_version": 2,
        "region": "us-east-2",
        "primary_unit": "openai-svc",
        "workloads": [
            {
                "workload_id": "openai-svc",
                "source": {
                    "provider": "openai",
                    "model_ids": ["gpt-5.4"],
                    "sdk": "openai",
                    "api_surface": "responses",
                    "source_paths": ["src/app.py"],
                },
                "requirements": {
                    "priority": "balanced",
                    "critical_features": [],
                    **(requirements or {}),
                },
                "detected_features": [],
            }
        ],
    }


def _verify_openai(requirements=None, **kwargs):
    recommendation = model_recommendation.recommend(_openai_input(requirements))
    return verify_model_path.verify_recommendation(recommendation, now=NOW, **kwargs)


OPUS55 = "anthropic.claude-opus-5-5"
PROFILE_ARN = f"arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.{OPUS55}"
APPLICATION_ARN = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/test-profile"


def _opus_recommendation(provider, path, profile):
    data = _input() if provider == "anthropic" else _openai_input()
    data["region"] = "us-east-1"
    requirements = data["workloads"][0]["requirements"]
    requirements.update(priority="quality", data_residency="geo_required",
                        cris_geography="us", inference_profile_id=profile)
    if provider == "anthropic":
        requirements["preferred_api_path"] = path
    else:
        requirements.update(governance=["guardrails"], preserve_openai_api=False)
    recommendation = model_recommendation.recommend(data)
    jsonschema.validate(recommendation, json.loads(
        (pathlib.Path(verify_model_path.__file__).parent / "schemas/model-recommendation.json").read_text()
    ))
    return recommendation


@pytest.mark.parametrize("provider,path", [
    ("anthropic", "runtime_converse"), ("anthropic", "runtime_invoke"),
    ("openai", "runtime_converse"),
])
@pytest.mark.parametrize("profile", [f"us.{OPUS55}", PROFILE_ARN])
def test_system_profile_id_and_arn_reach_the_selected_probe(provider, path, profile):
    client = FakeRuntimeClient()
    result = verify_model_path.verify_recommendation(
        _opus_recommendation(provider, path, profile),
        runtime_client_factory=lambda region: client,
    )
    assert next(iter(result["workloads"].values()))["status"] == "passed"
    calls = client.converse_calls if path == "runtime_converse" else client.invoke_calls
    assert calls[0]["modelId"] == profile


@pytest.mark.parametrize("profile", [
    PROFILE_ARN.replace("us-east-1", "eu-west-1"),
    PROFILE_ARN.replace("arn:aws:", "arn:aws-us-gov:"),
    PROFILE_ARN.replace("us.anthropic", "global.anthropic"),
    PROFILE_ARN.replace("opus-5-5", "sonnet-5"),
])
def test_system_profile_arn_mismatches_do_not_reach_inference(profile):
    client = FakeRuntimeClient()
    result = verify_model_path.verify_recommendation(
        _opus_recommendation("anthropic", "runtime_converse", profile),
        runtime_client_factory=lambda region: client,
    )
    assert next(iter(result["workloads"].values()))["status"] == "needs_resolution"
    assert not client.converse_calls


def _profile_metadata(regions=("us-east-1", "us-west-2"), model=OPUS55, status="ACTIVE"):
    return {"status": status, "models": [
        {"modelArn": f"arn:aws:bedrock:{region}::foundation-model/{model}"}
        for region in regions
    ]}


@pytest.mark.parametrize("provider,path", [
    ("anthropic", "runtime_converse"), ("anthropic", "runtime_invoke"),
    ("openai", "runtime_converse"),
])
def test_application_profile_metadata_is_verified_before_invoking_its_arn(provider, path):
    client = FakeRuntimeClient()
    reads = []

    class Control:
        def get_inference_profile(self, inferenceProfileIdentifier):
            assert not client.converse_calls and not client.invoke_calls
            reads.append(inferenceProfileIdentifier)
            return _profile_metadata()

    recommendation = _opus_recommendation(provider, path, APPLICATION_ARN)
    assert next(iter(recommendation["workloads"].values()))["invocation_model_id"] == APPLICATION_ARN
    result = verify_model_path.verify_recommendation(
        recommendation, runtime_client_factory=lambda region: client,
        control_client_factory=lambda region: Control(),
    )
    assert next(iter(result["workloads"].values()))["status"] == "passed"
    assert reads == [APPLICATION_ARN, f"us.{OPUS55}"]
    calls = client.converse_calls if path == "runtime_converse" else client.invoke_calls
    assert calls[0]["modelId"] == APPLICATION_ARN


@pytest.mark.parametrize("metadata", [
    _profile_metadata(model="anthropic.claude-sonnet-5"),
    _profile_metadata(regions=("us-east-1", "eu-west-1")),
    _profile_metadata(regions=()),
    _profile_metadata(status="INACTIVE"),
])
def test_application_profile_wrong_model_or_destinations_fail_before_inference(metadata):
    client = FakeRuntimeClient()

    class Control:
        def get_inference_profile(self, inferenceProfileIdentifier):
            return metadata if inferenceProfileIdentifier == APPLICATION_ARN else _profile_metadata()

    result = verify_model_path.verify_recommendation(
        _opus_recommendation("anthropic", "runtime_converse", APPLICATION_ARN),
        runtime_client_factory=lambda region: client,
        control_client_factory=lambda region: Control(),
    )
    assert next(iter(result["workloads"].values()))["status"] == "failed"
    assert not client.converse_calls


def test_application_profile_metadata_denial_does_not_create_runtime_client():
    calls = []

    class Control:
        def get_inference_profile(self, **kwargs):
            raise PermissionError("GetInferenceProfile denied")

    result = verify_model_path.verify_recommendation(
        _opus_recommendation("anthropic", "runtime_converse", APPLICATION_ARN),
        runtime_client_factory=lambda region: calls.append(region),
        control_client_factory=lambda region: Control(),
    )
    verification = next(iter(result["workloads"].values()))
    assert verification["status"] == "failed"
    assert verification["error"]["type"] == "PermissionError"
    assert not calls


def test_application_profile_without_constraints_is_not_invoked():
    recommendation = _opus_recommendation("anthropic", "runtime_converse", APPLICATION_ARN)
    next(iter(recommendation["workloads"].values()))["verification"].pop("allowed_inference_profiles")
    calls = []
    result = verify_model_path.verify_recommendation(
        recommendation, runtime_client_factory=lambda region: calls.append(region),
        control_client_factory=lambda region: calls.append(region),
    )
    assert next(iter(result["workloads"].values()))["status"] == "failed"
    assert not calls


def test_global_application_profile_can_use_an_allowed_reference_after_an_unreadable_one():
    recommendation = model_recommendation.recommend(_input({
        "priority": "quality", "governance": ["guardrails"],
        "data_residency": "global_allowed", "inference_profile_id": APPLICATION_ARN,
    }))
    client = FakeRuntimeClient()

    class Control:
        def get_inference_profile(self, inferenceProfileIdentifier):
            if inferenceProfileIdentifier == f"us.{OPUS55}":
                raise PermissionError("US reference not readable")
            return _profile_metadata(regions=("us-east-1", "eu-west-1"))

    result = verify_model_path.verify_recommendation(
        recommendation, runtime_client_factory=lambda region: client,
        control_client_factory=lambda region: Control(),
    )
    assert next(iter(result["workloads"].values()))["status"] == "passed"
    assert client.converse_calls[0]["modelId"] == APPLICATION_ARN


def test_mantle_responses_probe_calls_responses_create_with_exact_id():
    client = FakeOpenAIClient()
    result = _verify_openai(
        {"api_continuity": "required"},
        openai_responses_client_factory=lambda region: client,
    )
    verification = result["workloads"]["openai-svc"]

    assert verification["status"] == "passed"
    assert verification["api_path"] == "mantle_openai_responses"
    assert client.responses.calls[0]["model"] == "openai.gpt-5.6-sol"
    assert client.responses.calls[0]["input"]
    assert verification["response_model_id"] == "openai.gpt-5.6-sol"


def test_mantle_responses_failure_does_not_substitute_model():
    client = FakeOpenAIClient(FakeResponses(error=RuntimeError("access denied")))
    result = _verify_openai(
        {"api_continuity": "required"},
        openai_responses_client_factory=lambda region: client,
    )
    verification = result["workloads"]["openai-svc"]

    assert verification["status"] == "failed"
    assert verification["invocation_model_id"] == "openai.gpt-5.6-sol"
    # Only the exact selected model was ever probed.
    assert [c["model"] for c in client.responses.calls] == ["openai.gpt-5.6-sol"]


def test_openai_decision_required_is_not_probed():
    called = {"n": 0}

    def factory(region):
        called["n"] += 1
        return FakeOpenAIClient()

    result = _verify_openai(
        {"api_continuity": "required", "governance": ["guardrails"]},
        openai_responses_client_factory=factory,
    )
    verification = result["workloads"]["openai-svc"]

    assert verification["status"] == "not_applicable"
    assert called["n"] == 0  # no client constructed for a non-selected recommendation
