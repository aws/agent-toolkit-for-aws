import json
import pathlib

import jsonschema
import pytest

import anthropic_model_recommendation
import model_recommendation


VERSION_SCAN_FEATURES = {
    "assistant_prefill",
    "budget_tokens",
    "max_tokens_headroom",
    "refusal_handling",
    "sampling_parameters",
    "tokenizer_rebaseline",
}


def _workload(**overrides):
    workload = {
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
        },
        "detected_features": [],
    }
    for key, value in overrides.items():
        if key in {"source", "requirements"}:
            workload[key].update(value)
        else:
            workload[key] = value
    return workload


def _input(workload=None):
    return {
        "schema_version": 2,
        "region": "us-east-1",
        "primary_unit": "support-agent",
        "workloads": [workload or _workload()],
    }


def _recommend(workload=None):
    return model_recommendation.recommend(_input(workload))["workloads"][
        "support-agent"
    ]


def _codes(items):
    return {item["code"] for item in items}


def test_default_anthropic_messages_prefers_mantle_and_sonnet5():
    # Sonnet 5 (launched 2026-06-30) supports Mantle Messages, so the balanced
    # priority no longer has to escalate to Opus for Messages continuity.
    rec = _recommend()

    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert rec["api_path"] == "mantle_messages"
    assert rec["invocation_model_id"] == "anthropic.claude-sonnet-5"
    assert rec["model_identity"]["path_model_id"] == rec["primary_model"]
    assert rec["verification"]["probe_status"] == "not_run"


def test_cost_priority_on_messages_uses_clean_mantle_haiku_id():
    rec = _recommend(_workload(requirements={"priority": "cost"}))

    assert rec["api_path"] == "mantle_messages"
    assert rec["primary_model"] == "anthropic.claude-haiku-4-5"
    assert rec["model_identity"]["requires_cris"] is False


def test_governance_selects_runtime_converse_when_messages_is_a_preference():
    rec = _recommend(
        _workload(
            requirements={"governance": ["guardrails", "invocation_logging"]}
        )
    )

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"


def test_required_messages_and_governance_require_user_decision():
    rec = _recommend(
        _workload(
            requirements={
                "preserve_messages_api": True,
                "governance": ["guardrails"],
            }
        )
    )

    assert rec["decision_status"] == "decision_required"
    assert rec["primary_model"] is None
    assert rec["api_path"] is None
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "mantle_messages",
        "runtime_converse",
    }
    assert "model_path_decision_required" in _codes(rec["blocks"])


def test_conflicting_paths_without_catalog_candidates_are_rejected():
    workload = _workload(
        requirements={
            "preserve_messages_api": True,
            "governance": ["guardrails"],
            "min_context_tokens": 2000000,
        }
    )

    with pytest.raises(ValueError, match="no candidate for every conflicting"):
        _recommend(workload)


def test_native_payload_selects_runtime_invoke():
    rec = _recommend(
        _workload(requirements={"requires_native_payload": True})
    )

    assert rec["api_path"] == "runtime_invoke"


def test_context_and_output_limits_filter_candidates():
    rec = _recommend(
        _workload(
            requirements={
                "priority": "cost",
                "min_context_tokens": 1000000,
                "expected_output_tokens": 100000,
            }
        )
    )

    assert rec["model_identity"]["model_key"] == "claude_sonnet_5"
    assert all(
        option["model_key"] != "claude_haiku_4_5"
        for option in rec["alternatives"]
    )


def test_thinking_requirement_filters_haiku():
    rec = _recommend(
        _workload(
            requirements={
                "priority": "cost",
                "thinking_enabled": True,
            }
        )
    )

    assert rec["model_identity"]["model_key"] == "claude_sonnet_5"


def test_source_version_hop_requires_explicit_feature_scan():
    rec = _recommend()

    assert rec["source_analysis"] == {
        "detected_version": "3.7",
        "target_version": "5.0",
        "version_changed": True,
    }
    assert "claude_version_hop" in _codes(rec["migration_deltas"])
    assert "version_scan_incomplete" in _codes(rec["blocks"])
    assert {
        feature
        for feature, status in rec["feature_assessment"].items()
        if status == "unknown"
    } == VERSION_SCAN_FEATURES


def test_explicit_absent_status_clears_version_scan_block():
    workload = _workload(
        feature_status={feature: "absent" for feature in VERSION_SCAN_FEATURES}
    )
    rec = _recommend(workload)

    assert "version_scan_incomplete" not in _codes(rec["blocks"])


def test_detected_version_features_emit_blocks_and_tuning():
    rec = _recommend(
        _workload(
            detected_features=[
                "budget_tokens",
                "sampling_parameters",
                "assistant_prefill",
                "refusal_handling",
                "tokenizer_rebaseline",
                "max_tokens_headroom",
            ]
        )
    )

    assert {
        "budget_tokens_removed",
        "sampling_parameters_removed",
        "assistant_prefill_removed",
    }.issubset(_codes(rec["blocks"]))
    assert {
        "refusal_handling",
        "tokenizer_rebaseline",
        "max_tokens_headroom",
    }.issubset(_codes(rec["tuning"]))


@pytest.mark.parametrize(
    "requirements,expected_path",
    [
        ({"preserve_messages_api": True}, "mantle_messages"),
        ({"governance": ["guardrails"]}, "runtime_converse"),
    ],
)
def test_structured_output_uses_portable_forced_tool_guidance(
    requirements, expected_path
):
    rec = _recommend(
        _workload(
            requirements=requirements,
            detected_features=["structured_output"],
        )
    )

    assert rec["api_path"] == expected_path
    assert "structured_output_portable_pattern" in _codes(rec["blocks"])
    assert "structured_output" in _codes(rec["migration_deltas"])
    finding = next(
        item
        for item in rec["blocks"]
        if item["code"] == "structured_output_portable_pattern"
    )
    assert "forced tool without strict" in finding["remediation"]


def test_structured_output_and_citations_emit_conflict():
    rec = _recommend(
        _workload(detected_features=["structured_output", "citations"])
    )

    assert "structured_output_citations_conflict" in _codes(rec["blocks"])


def test_agent_features_produce_architecture_and_trajectory_requirements():
    rec = _recommend(
        _workload(
            requirements={"critical_features": ["agentic", "tool_use"]},
            detected_features=["agent_infra", "server_tools"],
        )
    )

    assert rec["evaluation"]["mode"] == "trajectory"
    assert {item["feature"] for item in rec["architecture_impacts"]} == {
        "agent_infra",
        "server_tools",
    }
    assert rec["compatibility"]["rearchitecture"] == [
        "agent_infra",
        "server_tools",
    ]


@pytest.mark.parametrize(
    "requirements,expected",
    [
        ({"data_residency": "unknown"}, None),
        (
            {"data_residency": "global_allowed"},
            "global.anthropic.claude-sonnet-5",
        ),
        (
            {"data_residency": "geo_required", "cris_geography": "eu"},
            "eu.anthropic.claude-sonnet-5",
        ),
        (
            {
                "inference_profile_id": "arn:aws:bedrock:us-east-1:123:inference-profile/custom"
            },
            "arn:aws:bedrock:us-east-1:123:inference-profile/custom",
        ),
    ],
)
def test_runtime_cris_resolution(requirements, expected):
    requirements["governance"] = ["guardrails"]
    rec = _recommend(_workload(requirements=requirements))

    assert rec["api_path"] == "runtime_converse"
    assert rec["invocation_model_id"] == expected
    assert rec["verification"]["invocation_model_id"] == expected


# The intended treatment of every provider the input schema allows, written here rather than derived
# from the code — a test that reads its expectation out of the constant it is checking cannot catch a
# drift in that constant. "anthropic" means a real recommendation from a module that understands the
# source; "generic" means a recommendation that carries `provider_module_pending` and stays
# provisional; "openai" has its own module and its own test suite.
PROVIDER_TREATMENT = {
    "anthropic": "anthropic",
    "none": "anthropic",  # no detected provider -> Bedrock-native pool
    "unknown": "anthropic",
    "openai": "openai",
    "azure_openai": "generic",
    "google_genai": "generic",
    "bedrock": "generic",
}


def test_every_schema_provider_routes_and_is_labelled_honestly():
    """Every provider the schema allows must route to a real module and be labelled honestly.

    The orchestrator sends everything non-OpenAI to the Anthropic module, which then classifies the
    source against its own ANTHROPIC_POOL. Two places, one rule — so this pins the rule itself, and
    fails if either side moves or if a provider is added to the schema without deciding its
    treatment."""
    scripts = pathlib.Path(model_recommendation.__file__).parent
    schema = json.loads(
        (scripts / "schemas" / "model-recommendation-input.json").read_text()
    )
    # `source` is a $ref into $defs, so the enum is read from there rather than inline.
    assert schema["properties"]["workloads"]["items"]["properties"]["source"] == {
        "$ref": "#/$defs/source"
    }
    providers = schema["$defs"]["source"]["properties"]["provider"]["enum"]
    assert set(providers) == set(PROVIDER_TREATMENT), (
        "a provider was added to the schema without deciding how it is treated"
    )
    assert anthropic_model_recommendation.ANTHROPIC_POOL == {
        p for p, t in PROVIDER_TREATMENT.items() if t == "anthropic"
    }

    for provider, treatment in PROVIDER_TREATMENT.items():
        module = "openai" if treatment == "openai" else "anthropic"
        assert model_recommendation._provider_module(provider) == module, provider
        if module == "openai":
            continue
        rec = _recommend(_workload(source={"provider": provider}))
        assert rec["provider_module"] == treatment, provider
        assert ("provider_module_pending" in _codes(rec["blocks"])) == (
            treatment == "generic"
        ), provider


def test_future_provider_is_explicitly_provisional():
    # OpenAI now has a real provider module; Azure OpenAI remains the pending case.
    rec = _recommend(
        _workload(
            source={
                "provider": "azure_openai",
                "model_ids": ["gpt-5.4"],
                "sdk": "azure_openai",
                "api_surface": "responses",
            }
        )
    )

    assert rec["provider_module"] == "generic"
    assert "provider_module_pending" in _codes(rec["blocks"])


def test_duplicate_workload_ids_are_rejected():
    data = _input()
    data["workloads"].append(_workload())

    with pytest.raises(ValueError, match="duplicate workload_id"):
        model_recommendation.recommend(data)


def test_input_and_output_match_schemas():
    scripts = pathlib.Path(model_recommendation.__file__).parent
    input_data = _input()
    result = model_recommendation.recommend(input_data)

    input_schema = json.loads(
        (scripts / "schemas" / "model-recommendation-input.json").read_text()
    )
    output_schema = json.loads(
        (scripts / "schemas" / "model-recommendation.json").read_text()
    )
    jsonschema.validate(input_data, input_schema)
    jsonschema.validate(result, output_schema)


def test_catalog_records_path_specific_ids_and_limits():
    catalog = model_recommendation.load_catalog()

    assert catalog["verified_at"] == "2026-07-21"
    assert catalog["verified_region"] == "us-east-1"
    assert (
        catalog["models"]["claude_sonnet_5"]["paths"]["mantle_messages"][
            "available"
        ]
        is True
    )
    assert (
        catalog["models"]["claude_haiku_4_5"]["paths"]["mantle_messages"][
            "model_id"
        ]
        == "anthropic.claude-haiku-4-5"
    )
    assert (
        catalog["models"]["claude_haiku_4_5"]["paths"]["runtime_converse"][
            "model_id"
        ]
        == "anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    assert (
        catalog["models"]["claude_opus_4_8"]["output_token_ceiling"] == 128000
    )
