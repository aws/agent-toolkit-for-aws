import copy
import json
import pathlib
import re

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


def _schema(name):
    scripts = pathlib.Path(model_recommendation.__file__).parent
    return json.loads((scripts / "schemas" / name).read_text())


def test_default_anthropic_messages_lands_on_runtime_messages():
    # bedrock-runtime is the default endpoint (bedrock-endpoint-policy.md); a Messages
    # source keeps its API on bedrock-runtime Messages. Nothing selects Mantle here.
    result = model_recommendation.recommend(_input())
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"
    assert rec["model_identity"]["display_name"] == "Claude Sonnet 5.5"
    assert rec["model_identity"]["version"] == "5.5"
    assert rec["api_path"] == "runtime_messages"
    assert rec["invocation_model_id"] is None  # residency unknown: no CRIS prefix guessed
    assert rec["mantle_selector"] is None
    assert rec["model_identity"]["requires_cris"] is True
    assert rec["model_identity"]["path_model_id"] == rec["primary_model"]
    assert rec["verification"]["probe_status"] == "not_run"
    assert not any("mantle" in block["message"].lower() for block in rec["blocks"])
    jsonschema.validate(result, _schema("model-recommendation.json"))


def test_cost_priority_with_workspaces_selector_uses_clean_mantle_haiku_id():
    # Haiku 5.5 is the fast/low-cost tier, but the model card lists bedrock-mantle for it only in
    # us-gov-west-1. In us-east-1 the Messages path (selected here by the workspaces selector)
    # therefore falls to Haiku 4.5, the Batch-listed explicit alternative, rather than to Sonnet 5.
    rec = _recommend(
        _workload(requirements={"priority": "cost", "mantle_selector": "workspaces"})
    )

    assert rec["api_path"] == "mantle_messages"
    assert rec["primary_model"] == "anthropic.claude-haiku-4-5"
    assert rec["invocation_model_id"] == "anthropic.claude-haiku-4-5"
    assert rec["model_identity"]["requires_cris"] is False
    assert rec["mantle_selector"] == "workspaces"
    # Haiku 5.5 may still appear as a runtime_converse alternative; it must not be a Mantle option here.
    assert not any(
        o["model_key"] == "claude_haiku_5_5" and o["api_path"] == "mantle_messages" for o in rec["alternatives"]
    )


# background_inference (Responses-only) and projects (OpenAI-only) are decisions below.
_MESSAGES_ROUTABLE_SELECTORS = [
    selector for selector in anthropic_model_recommendation.MANTLE_SELECTORS
    if selector not in {"background_inference", "projects"}
]


@pytest.mark.parametrize("selector", _MESSAGES_ROUTABLE_SELECTORS)
def test_every_mantle_selector_selects_mantle_messages_and_is_echoed(selector):
    rec = _recommend(_workload(requirements={"mantle_selector": selector}))

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_messages"
    assert rec["mantle_selector"] == selector
    assert any(f"mantle_selector {selector}" in line for line in rec["rationale"])


# --- Every selector is validated against the final provider and API (PR 588 F4) ---
# Background inference is a Responses API feature on bedrock-mantle
# (inference-responses-api.html, read 2026-11-09); `projects` scopes the
# OpenAI-compatible APIs while Messages scopes by Workspaces (projects.html,
# workspaces.html, read 2026-11-09).

def test_anthropic_messages_with_background_inference_is_a_decision_not_mantle_messages():
    workload = _workload(requirements={"mantle_selector": "background_inference"})
    result = model_recommendation.recommend(_input(workload))
    jsonschema.validate(result, _schema("model-recommendation.json"))
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert rec["mantle_selector"] is None
    assert "selector_api_incompatible" in _codes(rec["blocks"])
    assert "mantle_selector_vs_anthropic_api" in _decision_block(rec)["message"]
    # Both options stay on bedrock-runtime; mantle_messages is never offered.
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_messages", "runtime_converse",
    }
    block = next(b for b in rec["blocks"] if b["code"] == "selector_api_incompatible")
    assert "inference-responses-api.html" in block["message"]
    assert "Responses" in block["message"]


def test_projects_selector_on_an_anthropic_source_is_a_provider_mismatch_decision():
    workload = _workload(requirements={"mantle_selector": "projects"})
    result = model_recommendation.recommend(_input(workload))
    jsonschema.validate(result, _schema("model-recommendation.json"))
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert "selector_provider_mismatch" in _codes(rec["blocks"])
    assert "mantle_selector_provider_mismatch" in _decision_block(rec)["message"]
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_messages", "runtime_converse",
    }
    block = next(b for b in rec["blocks"] if b["code"] == "selector_provider_mismatch")
    assert "anthropic-workspace-id" in block["message"]
    assert "OpenAI-Project" in block["message"]


def test_projects_with_a_preferred_mantle_path_still_never_offers_mantle_messages():
    rec = _recommend(
        _workload(requirements={"preferred_api_path": "mantle_messages",
                                "mantle_selector": "projects"})
    )

    assert rec["decision_status"] == "decision_required"
    assert "selector_provider_mismatch" in _codes(rec["blocks"])
    assert not any(o["api_path"].startswith("mantle_") for o in rec["decision_options"])


def test_background_inference_with_native_payload_offers_runtime_messages_or_invoke():
    rec = _recommend(
        _workload(requirements={"mantle_selector": "background_inference",
                                "requires_native_payload": True})
    )

    assert rec["decision_status"] == "decision_required"
    assert "selector_api_incompatible" in _codes(rec["blocks"])
    assert "mantle_selector_vs_runtime" not in _decision_block(rec)["message"]
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_messages", "runtime_invoke",
    }


def test_mantle_selectors_match_the_input_schema_enum():
    enum = _schema("model-recommendation-input.json")["properties"]["workloads"]["items"][
        "properties"]["requirements"]["properties"]["mantle_selector"]["enum"]
    assert list(anthropic_model_recommendation.MANTLE_SELECTORS) == enum
    with pytest.raises(ValueError, match="unsupported mantle_selector"):
        _recommend(_workload(requirements={"mantle_selector": "because"}))




def test_cost_priority_on_messages_in_govcloud_selects_haiku_5_5():
    # Messages is selected by a verified selector; cost priority alone stays on bedrock-runtime.
    inp = _input(_workload(requirements={"priority": "cost", "mantle_selector": "workspaces"}))
    inp["region"] = "us-gov-west-1"
    rec = model_recommendation.recommend(inp)["workloads"]["support-agent"]
    assert rec["api_path"] == "mantle_messages"
    assert rec["primary_model"] == "anthropic.claude-haiku-5-5"


def test_cost_priority_on_runtime_selects_haiku_5_5_via_profile():
    rec = _recommend(
        _workload(requirements={"priority": "cost", "governance": ["guardrails"], "data_residency": "global_allowed"})
    )
    assert rec["api_path"] == "runtime_converse"
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    assert rec["invocation_model_id"] == "global.anthropic.claude-haiku-5-5"
    geo = _recommend(
        _workload(requirements={"priority": "cost", "governance": ["guardrails"],
                                "data_residency": "geo_required", "cris_geography": "us"})
    )
    assert geo["invocation_model_id"] == "us.anthropic.claude-haiku-5-5"


def test_govcloud_runtime_does_not_receive_a_global_haiku_profile():
    # Global profiles are unavailable in GovCloud; the us. Geo profile covers us-gov-* source Regions.
    inp = _input(_workload(requirements={"priority": "cost", "governance": ["guardrails"], "data_residency": "global_allowed"}))
    inp["region"] = "us-gov-west-1"
    rec = model_recommendation.recommend(inp)["workloads"]["support-agent"]
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    assert rec["invocation_model_id"] != "global.anthropic.claude-haiku-5-5"


def test_haiku_5_5_batch_remediation_names_the_selected_model_not_opus():
    rec = _recommend(
        _workload(requirements={"priority": "cost", "governance": ["guardrails"]}, detected_features=["message_batches"])
    )
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    finding = next(f for f in rec["blocks"] if f["code"] == "message_batches_not_portable")
    assert "Claude Haiku 5.5 does not support Bedrock Batch" in finding["remediation"]
    assert "Opus" not in finding["remediation"]
    assert "Claude Haiku 4.5" in finding["remediation"]


def test_governance_selects_runtime_converse_when_messages_is_a_preference():
    rec = _recommend(
        _workload(
            requirements={"governance": ["guardrails", "invocation_logging"]}
        )
    )

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"
    assert rec["mantle_selector"] is None


@pytest.mark.parametrize("governance", [["invocation_logging"], ["cloudwatch"],
                                        ["invocation_logging", "cloudwatch"]])
def test_runtime_only_logging_governance_keeps_required_messages_on_runtime(governance):
    # invocation logging and CloudWatch apply to every bedrock-runtime path, so they
    # never force a Messages workload onto Converse.
    rec = _recommend(
        _workload(requirements={"preserve_messages_api": True, "governance": governance})
    )

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_messages"
    assert rec["mantle_selector"] is None


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
    assert rec["mantle_selector"] is None
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_messages",
        "runtime_converse",
    }
    assert all(option.get("mantle_selector") is None for option in rec["decision_options"])
    block = next(item for item in rec["blocks"] if item["code"] == "model_path_decision_required")
    assert "messages_vs_converse" in block["message"]
    assert "runtime_messages" in block["remediation"] and "runtime_converse" in block["remediation"]
    jsonschema.validate(
        model_recommendation.recommend(_input(_workload(requirements={
            "preserve_messages_api": True, "governance": ["guardrails"]}))),
        _schema("model-recommendation.json"),
    )


def test_selector_and_guardrails_require_user_decision_with_mantle_option():
    rec = _recommend(
        _workload(requirements={"mantle_selector": "web_search", "governance": ["guardrails"]})
    )

    assert rec["decision_status"] == "decision_required"
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert set(options) == {"mantle_messages", "runtime_converse"}
    assert options["mantle_messages"]["mantle_selector"] == "web_search"
    assert "mantle_selector" not in options["runtime_converse"]
    block = next(item for item in rec["blocks"] if item["code"] == "model_path_decision_required")
    assert "mantle_selector_vs_runtime" in block["message"]


def _decision_block(rec):
    return next(item for item in rec["blocks"] if item["code"] == "model_path_decision_required")


# Invocation logging is captured only on bedrock-runtime (model-invocation-logging.html,
# read 2026-11-08); CloudWatch metrics exist on both endpoints (AWS/BedrockMantle,
# monitoring-mantle-metrics.html, read 2026-11-08) and never constrain the path.

def test_logging_plus_selector_is_a_decision_between_mantle_and_runtime_messages():
    workload = _workload(requirements={"governance": ["invocation_logging"],
                                       "mantle_selector": "workspaces"})
    result = model_recommendation.recommend(_input(workload))
    jsonschema.validate(result, _schema("model-recommendation.json"))
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "decision_required"
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert set(options) == {"mantle_messages", "runtime_messages"}
    assert options["mantle_messages"]["mantle_selector"] == "workspaces"
    assert "mantle_selector_vs_invocation_logging" in _decision_block(rec)["message"]
    assert "CloudWatch" not in _decision_block(rec)["message"]


def test_logging_plus_derived_in_region_is_a_decision_carrying_the_derived_selector():
    workload = _workload(requirements={"governance": ["invocation_logging"],
                                       "data_residency": "in_region_required"})
    result = model_recommendation.recommend(_input(workload))
    jsonschema.validate(result, _schema("model-recommendation.json"))
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "decision_required"
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert set(options) == {"mantle_messages", "runtime_messages"}
    assert options["mantle_messages"]["mantle_selector"] == "in_region_processing"
    assert "in_region_processing_vs_invocation_logging" in _decision_block(rec)["message"]
    assert "runtime_messages" in _decision_block(rec)["remediation"]


def test_cloudwatch_plus_selector_is_recommended_on_mantle_messages():
    rec = _recommend(_workload(requirements={"governance": ["cloudwatch"],
                                             "mantle_selector": "workspaces"}))

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_messages"
    assert rec["mantle_selector"] == "workspaces"


def test_cloudwatch_plus_in_region_derives_the_mantle_selector():
    rec = _recommend(_workload(requirements={"governance": ["cloudwatch"],
                                             "data_residency": "in_region_required"}))

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_messages"
    assert rec["mantle_selector"] == "in_region_processing"


# An explicit bedrock-runtime preference never coexists with a Mantle selector or a
# Converse-only requirement; both are decisions.

def test_preferred_runtime_messages_plus_selector_is_a_decision():
    rec = _recommend(_workload(requirements={"preferred_api_path": "runtime_messages",
                                             "mantle_selector": "workspaces"}))

    assert rec["decision_status"] == "decision_required"
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert set(options) == {"mantle_messages", "runtime_messages"}
    assert options["mantle_messages"]["mantle_selector"] == "workspaces"
    assert "preferred_path_vs_mantle_selector" in _decision_block(rec)["message"]


def test_preferred_runtime_messages_plus_guardrails_is_a_decision():
    rec = _recommend(_workload(requirements={"preferred_api_path": "runtime_messages",
                                             "governance": ["guardrails"]}))

    assert rec["decision_status"] == "decision_required"
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_messages", "runtime_converse",
    }
    assert "preferred_path_vs_converse" in _decision_block(rec)["message"]


def test_preferred_runtime_messages_plus_derived_in_region_is_a_decision():
    workload = _workload(requirements={"preferred_api_path": "runtime_messages",
                                       "data_residency": "in_region_required"})
    result = model_recommendation.recommend(_input(workload))
    jsonschema.validate(result, _schema("model-recommendation.json"))
    rec = result["workloads"]["support-agent"]

    assert rec["decision_status"] == "decision_required"
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert set(options) == {"mantle_messages", "runtime_messages"}
    assert options["mantle_messages"]["mantle_selector"] == "in_region_processing"
    assert "in_region_processing_vs_preferred_api_path" in _decision_block(rec)["message"]


def test_in_region_required_on_a_cris_only_runtime_candidate_derives_mantle():
    rec = _recommend(_workload(requirements={"data_residency": "in_region_required"}))

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_messages"
    assert rec["mantle_selector"] == "in_region_processing"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert rec["invocation_model_id"] == "anthropic.claude-sonnet-5"
    assert any("in_region_processing" in line for line in rec["rationale"])


def test_in_region_required_keeps_opus55_london_on_runtime_messages():
    workload = _workload(
        requirements={"priority": "quality", "data_residency": "in_region_required"}
    )
    data = _input(workload)
    data["region"] = "eu-west-2"
    rec = model_recommendation.recommend(data)["workloads"]["support-agent"]

    assert rec["api_path"] == "runtime_messages"
    assert rec["primary_model"] == "anthropic.claude-opus-5-5"
    assert rec["invocation_model_id"] == "anthropic.claude-opus-5-5"
    assert rec["model_identity"]["requires_cris"] is False
    assert rec["mantle_selector"] is None


def test_preferred_mantle_path_without_selector_fails_closed():
    rec = _recommend(_workload(requirements={"preferred_api_path": "mantle_messages"}))

    assert rec["decision_status"] == "decision_required"
    assert "mantle_selector_required" in _codes(rec["blocks"])
    options = {option["api_path"] for option in rec["decision_options"]}
    assert options == {"runtime_messages", "mantle_messages"}


def test_preferred_mantle_path_with_selector_is_honored():
    rec = _recommend(
        _workload(requirements={"preferred_api_path": "mantle_messages",
                                "mantle_selector": "workspaces"})
    )

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_messages"
    assert rec["mantle_selector"] == "workspaces"


def test_preferred_runtime_messages_is_honored_and_does_not_conflict_with_required_messages():
    rec = _recommend(
        _workload(requirements={"preferred_api_path": "runtime_messages",
                                "preserve_messages_api": True})
    )

    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_messages"


def test_newest_betas_stay_on_runtime_messages_with_a_verification_tune():
    rec = _recommend(_workload(requirements={"newest_anthropic_betas": True}))

    assert rec["api_path"] == "runtime_messages"
    assert rec["mantle_selector"] is None
    finding = next(item for item in rec["tuning"] if item["code"] == "beta_header_verification")
    assert "mantle_only_model_or_api" in finding["remediation"]


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
    limits = {"priority": "cost", "min_context_tokens": 1000000, "expected_output_tokens": 100000}
    # Default path is bedrock-runtime: Haiku 5.5 (1M / 128K) satisfies the limits and is the
    # fast/low-cost tier, while Haiku 4.5 (200K / 64K) is filtered out.
    rec = _recommend(_workload(requirements=limits))
    assert rec["api_path"].startswith("runtime_")
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    assert all(option["model_key"] != "claude_haiku_4_5" for option in rec["alternatives"])
    # On Mantle (selected by a verified selector) in us-east-1 Haiku 5.5 is not served, and
    # Haiku 4.5 is filtered by the limits, so the cost order lands on Sonnet 5 (1M / 128K).
    mantle = _recommend(_workload(requirements={**limits, "mantle_selector": "workspaces"}))
    assert mantle["api_path"] == "mantle_messages"
    assert mantle["model_identity"]["model_key"] == "claude_sonnet_5"
    assert all(option["model_key"] != "claude_haiku_4_5" for option in mantle["alternatives"])


def test_thinking_requirement_filters_haiku():
    # Default path is bedrock-runtime: Haiku 5.5 has extended_thinking and is the cost tier;
    # Haiku 4.5 has no extended_thinking and is excluded.
    rec = _recommend(_workload(requirements={"priority": "cost", "thinking_enabled": True}))
    assert rec["api_path"].startswith("runtime_")
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    assert all(option["model_key"] != "claude_haiku_4_5" for option in rec["alternatives"])
    # On Mantle in us-east-1 Haiku 5.5 is not served and Haiku 4.5 has no extended_thinking,
    # so thinking_enabled lands on Sonnet 5; the Haiku 4.5 exclusion is the real check.
    mantle = _recommend(
        _workload(requirements={"priority": "cost", "thinking_enabled": True, "mantle_selector": "workspaces"})
    )
    assert mantle["api_path"] == "mantle_messages"
    assert mantle["model_identity"]["model_key"] == "claude_sonnet_5"
    assert all(option["model_key"] != "claude_haiku_4_5" for option in mantle["alternatives"])


def test_source_version_hop_requires_explicit_feature_scan():
    rec = _recommend()

    assert rec["source_analysis"] == {
        "detected_version": "3.7",
        "target_version": "5.5",
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
        # Sonnet 5.5 is the balanced default on bedrock-runtime and its Mantle path is
        # GovCloud-only, so the older target this guidance is for (Sonnet 5) is reached
        # through a verified Mantle selector in a commercial Region.
        ({"mantle_selector": "workspaces"}, "mantle_messages"),
    ],
)
def test_older_target_forced_tool_guidance_requires_verified_support(
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
    assert "only after verifying" in finding["remediation"]


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


def test_eu_geo_from_a_us_region_fails_closed_with_a_block():
    rec = _recommend(_workload(requirements={
        "data_residency": "geo_required", "cris_geography": "eu", "governance": ["guardrails"],
    }))
    assert rec["invocation_model_id"] is None
    assert "inference_profile_unresolved" in _codes(rec["blocks"])


@pytest.mark.parametrize(
    "requirements,expected",
    [
        ({"data_residency": "unknown"}, None),
        (
            {"data_residency": "global_allowed"},
            "global.anthropic.claude-sonnet-5-5",
        ),
        # An EU Geo profile is callable only from EU source Regions. From us-east-1, Sonnet 5.5's
        # profile matrix resolves nothing, and the result fails closed (see the next test).
        (
            {"data_residency": "geo_required", "cris_geography": "eu"},
            None,
        ),
        (
            {
                "inference_profile_id": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5"
            },
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5",
        ),
    ],
)
def test_runtime_cris_resolution(requirements, expected):
    requirements["governance"] = ["guardrails"]
    rec = _recommend(_workload(requirements=requirements))

    assert rec["api_path"] == "runtime_converse"
    assert rec["invocation_model_id"] == expected
    assert rec["verification"]["invocation_model_id"] == expected


@pytest.mark.parametrize(
    "pin,requirements",
    [
        # Global profile under US-only residency: the geography constraint must reject the pin.
        (
            "global.anthropic.claude-sonnet-5-5",
            {"data_residency": "geo_required", "cris_geography": "us"},
        ),
        # EU profile under US-only residency.
        (
            "eu.anthropic.claude-sonnet-5-5",
            {"data_residency": "geo_required", "cris_geography": "us"},
        ),
        # Profile for another model.
        ("us.anthropic.claude-opus-4-1", {}),
        # Right model, wrong region in the ARN.
        (
            "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-sonnet-5",
            {},
        ),
        # Wrong partition for us-east-1.
        (
            "arn:aws-us-gov:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5",
            {},
        ),
        # Not a system profile id at all.
        ("arn:aws:bedrock:us-east-1:123456789012:inference-profile/custom", {}),
    ],
)
def test_explicit_pin_on_matrixless_model_still_validates_identity_region_and_geography(
    pin, requirements
):
    requirements = {**requirements, "governance": ["guardrails"], "inference_profile_id": pin}
    rec = _recommend(_workload(requirements=requirements))
    assert rec["api_path"] == "runtime_converse"
    assert rec["invocation_model_id"] is None
    assert "inference_profile_unresolved" in _codes(rec["blocks"])


def test_explicit_pin_on_matrixless_model_is_kept_when_it_matches():
    requirements = {
        "governance": ["guardrails"],
        "data_residency": "geo_required",
        "cris_geography": "us",
        "inference_profile_id": "us.anthropic.claude-sonnet-5",
    }
    rec = _recommend(_workload(requirements=requirements))
    assert rec["invocation_model_id"] == "us.anthropic.claude-sonnet-5"


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

    assert catalog["verified_at"] == "2026-11-10"
    assert catalog["models"]["claude_haiku_5_5"]["paths"]["mantle_messages"]["model_id"] == "anthropic.claude-haiku-5-5"
    assert catalog["models"]["claude_haiku_5_5"]["paths"]["runtime_converse"]["requires_cris"] is True
    assert catalog["models"]["claude_haiku_5_5"]["context_window"] == 1000000
    assert "extended_thinking" in catalog["models"]["claude_haiku_5_5"]["capabilities"]
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
        catalog["models"]["claude_opus_5_5"]["output_token_ceiling"] == 128000
    )


@pytest.mark.parametrize("relative_path", [
    "references/phases/model-recommend/model-recommend.md",
    "references/phases/model-recommend/model-recommend-assemble.md",
    "references/decision-refs/model-selection.md",
])
def test_current_catalog_readers_match_engine_defaults(relative_path):
    skill = pathlib.Path(model_recommendation.__file__).parent.parent
    text = (skill / relative_path).read_text()
    expected = {
        model_recommendation.DEFAULT_CATALOG.name,
        model_recommendation.OPENAI_CATALOG.name,
    }
    catalog_pattern = r"(?:anthropic|openai)-bedrock\.json"
    assert set(re.findall(catalog_pattern, text)) == expected
    if text.startswith("---\n"):
        frontmatter = text.split("---", 2)[1]
        loaded = set(re.findall(r"\bfile:\s*references/vendored/ai/models/(" + catalog_pattern + r")", frontmatter))
        assert loaded == expected


# --- review on #600, round 2: explicit profile pin, Canadian geography ----------------------


def test_explicit_haiku_4_5_profile_pin_is_preserved_over_the_ranked_haiku_5_5():
    rec = _recommend(
        _workload(
            requirements={
                "priority": "cost",
                "governance": ["guardrails"],
                "inference_profile_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            }
        )
    )
    assert rec["model_identity"]["model_key"] == "claude_haiku_4_5"
    assert rec["invocation_model_id"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert "inference_profile_unresolved" not in _codes(rec["blocks"])


def test_unpinned_cost_runtime_still_defaults_to_haiku_5_5():
    rec = _recommend(
        _workload(requirements={"priority": "cost", "governance": ["guardrails"], "data_residency": "global_allowed"})
    )
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"


def test_profile_pin_matching_no_candidate_is_still_rejected():
    rec = _recommend(
        _workload(
            requirements={
                "priority": "cost",
                "governance": ["guardrails"],
                "inference_profile_id": "eu.anthropic.claude-haiku-5-5",
            }
        )
    )
    # eu. is not a Haiku 5.5 profile reachable from us-east-1 and names no other candidate; blocker stays.
    assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
    assert rec["invocation_model_id"] is None
    assert "inference_profile_unresolved" in _codes(rec["blocks"])


def test_canadian_geography_validates_and_resolves_the_ca_profile():
    for region in ("ca-central-1", "ca-west-1"):
        inp = _input(
            _workload(
                requirements={"priority": "cost", "governance": ["guardrails"],
                              "data_residency": "geo_required", "cris_geography": "ca"}
            )
        )
        inp["region"] = region
        rec = model_recommendation.recommend(inp)["workloads"]["support-agent"]  # validates against the input schema
        assert rec["model_identity"]["model_key"] == "claude_haiku_5_5"
        assert rec["invocation_model_id"] == "ca.anthropic.claude-haiku-5-5", region


def test_sonnet55_structured_output_guidance_uses_native_outputs_not_forced_tools():
    # Governance lands on runtime Converse, where the balanced default is Sonnet 5.5. It rejects
    # forced tool_choice but supports native structured outputs, so the guidance says so.
    rec = _recommend(
        _workload(requirements={"governance": ["guardrails"]}, detected_features=["structured_output"])
    )
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"
    finding = next(item for item in rec["blocks"] if item["code"] == "structured_output_portable_pattern")
    assert "Sonnet 5.5 rejects forced any/tool choice" in finding["remediation"]
    assert "native structured outputs" in finding["remediation"]


def test_older_target_forced_tool_guidance_on_runtime_converse():
    # Sonnet 5 on runtime Converse (reachable here by marking Sonnet 5.5 reference_only) keeps the
    # older-target guidance: a forced tool only after verifying support.
    catalog = copy.deepcopy(model_recommendation.load_catalog())
    catalog["models"]["claude_sonnet_5_5"]["selection_status"] = "reference_only"
    rec = model_recommendation.recommend(
        _input(_workload(requirements={"governance": ["guardrails"]}, detected_features=["structured_output"])),
        catalog=catalog,
    )["workloads"]["support-agent"]
    assert (rec["primary_model"], rec["api_path"]) == ("anthropic.claude-sonnet-5", "runtime_converse")
    finding = next(item for item in rec["blocks"] if item["code"] == "structured_output_portable_pattern")
    assert "forced tool without strict" in finding["remediation"]
    assert "only after verifying" in finding["remediation"]
