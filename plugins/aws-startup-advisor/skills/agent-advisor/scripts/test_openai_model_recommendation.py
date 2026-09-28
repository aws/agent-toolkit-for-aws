"""Tests for the OpenAI-to-Bedrock provider module (handoff Section 11 matrix)."""

import json
import pathlib

import jsonschema
import pytest

import model_recommendation
import openai_model_recommendation as oai


SCRIPTS = pathlib.Path(model_recommendation.__file__).parent
OPENAI_CATALOG = model_recommendation.load_openai_catalog()


def _workload(**overrides):
    workload = {
        "workload_id": "chat-svc",
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
        },
        "detected_features": [],
    }
    for key, value in overrides.items():
        if key in {"source", "requirements"}:
            workload[key].update(value)
        else:
            workload[key] = value
    return workload


def _recommend(workload=None):
    return oai.recommend_openai_workload(
        workload or _workload(), "us-east-2", OPENAI_CATALOG
    )


def _codes(items):
    return {item["code"] for item in items}


def _delta_codes(rec):
    return {d["code"] for d in rec["migration_deltas"]}


# --- 11.1 Provider and path selection -------------------------------------

def test_responses_source_with_continuity_recommends_mantle_responses():
    rec = _recommend(
        _workload(requirements={"api_continuity": "required"})
    )
    assert rec["provider_module"] == "openai"
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.6-sol"


def test_chat_completions_gpt5_target_selects_responses_not_chat():
    rec = _recommend(
        _workload(
            source={"api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
        )
    )
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["api_path"] != "mantle_openai_chat"
    assert "chat_completions_to_responses_required" in _codes(rec["blocks"])


def test_chat_completions_case_includes_full_reshape_deltas():
    rec = _recommend(
        _workload(
            source={"api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
            detected_features=["tool_or_function_calling", "conversation_state"],
        )
    )
    codes = _delta_codes(rec)
    assert "chat_to_responses_request" in codes
    assert "chat_to_responses_response" in codes
    assert "chat_to_responses_tools" in codes
    assert "chat_to_responses_state" in codes


def test_governance_selects_runtime_converse():
    rec = _recommend(
        _workload(requirements={"governance": ["guardrails", "invocation_logging"]})
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"


def test_continuity_plus_runtime_only_returns_decision_required():
    rec = _recommend(
        _workload(
            requirements={
                "api_continuity": "required",
                "governance": ["guardrails"],
            }
        )
    )
    assert rec["decision_status"] == "decision_required"
    assert rec["primary_model"] is None
    assert rec["api_path"] is None
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses",
        "runtime_converse",
    }
    assert "model_path_decision_required" in _codes(rec["blocks"])


def test_decision_options_explain_tradeoffs():
    rec = _recommend(
        _workload(
            requirements={"api_continuity": "required", "governance": ["guardrails"]}
        )
    )
    reasons = {o["api_path"]: o["reason"] for o in rec["decision_options"]}
    assert "OpenAI SDK" in reasons["mantle_openai_responses"]
    assert "Bedrock-native" in reasons["runtime_converse"]


# --- 11.2 Model-generation analysis ---------------------------------------

def test_gpt4_to_gpt5_emits_model_generation_finding():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-4o"], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
        )
    )
    assert rec["source_analysis"]["source_family"] == "legacy"
    assert rec["source_analysis"]["model_generation_changes"] is True
    assert "model_generation_hop" in _delta_codes(rec)


def test_oseries_source_is_reasoning_not_legacy():
    rec = _recommend(_workload(source={"model_ids": ["o3-mini"]}))
    assert rec["source_analysis"]["source_family"] == "reasoning"
    assert rec["source_analysis"]["model_generation_changes"] is False


def test_opaque_deployment_name_stays_unknown():
    assert oai.detect_family("prod-default") == "unknown"
    rec = _recommend(_workload(source={"model_ids": ["prod-default"]}))
    assert rec["source_analysis"]["source_family"] == "unknown"


def test_reasoning_workload_requires_output_headroom():
    rec = _recommend()  # gpt-5.4 reasoning
    assert "reasoning_token_headroom" in _codes(rec["tuning"])


def test_reasoning_headroom_is_a_starting_heuristic_not_a_guarantee():
    rec = _recommend()
    msg = next(
        f["remediation"] for f in rec["tuning"] if f["code"] == "reasoning_token_headroom"
    )
    assert "2.5x" in msg
    assert "STARTING heuristic" in msg or "not a guaranteed" in msg


# --- 11.3 Parameter and API behavior --------------------------------------

def test_sampling_is_target_derived_not_source_derived():
    # G01: the Mantle target is openai.gpt-5.4 (accepts sampling), so BOTH an
    # early-GPT-5 source and a GPT-5.4 source get the same target-derived finding.
    early = _recommend(_workload(source={"model_ids": ["gpt-5.1"]}))
    later = _recommend(_workload(source={"model_ids": ["gpt-5.4"]}))
    assert "sampling_params_accepted" in _codes(early["tuning"])
    assert "sampling_params_accepted" in _codes(later["tuning"])
    # G10: penalties/logprobs/stop are called out as rejected separately.
    assert "sampling_penalties_rejected" in _codes(early["tuning"])


def test_gpt54_does_not_get_anthropic_sampling_removal():
    rec = _recommend(_workload(source={"model_ids": ["gpt-5.4"]}))
    assert "sampling_parameters_removed" not in _codes(rec["blocks"])
    assert "sampling_params_accepted" in _codes(rec["tuning"])


def test_n_usage_emits_repeated_call_requirement():
    rec = _recommend(_workload(requirements={"uses_n": True}))
    assert "responses_no_n" in _delta_codes(rec)


def test_tool_results_emit_function_call_output_delta():
    rec = _recommend(_workload(detected_features=["tool_or_function_calling"]))
    assert "tool_result_shape" in _delta_codes(rec)


def test_structured_output_emits_text_format_mapping():
    rec = _recommend(_workload(detected_features=["structured_output_json"]))
    assert "structured_output_text_format" in _delta_codes(rec)


def test_multiturn_state_emits_previous_response_or_app_state():
    rec = _recommend(_workload(requirements={"uses_hosted_state": True}))
    assert "conversation_state_ownership" in _delta_codes(rec)


# --- 11.4 Architecture impacts --------------------------------------------

def _impact_features(rec):
    return {a["feature"] for a in rec["architecture_impacts"]}


def test_hosted_web_search_not_reported_as_live_native_search():
    rec = _recommend(_workload(detected_features=["web_search"]))
    impacts = {a["feature"]: a["impact"] for a in rec["architecture_impacts"]}
    assert "web_search" in impacts
    assert "passthrough" in impacts["web_search"].lower()


def test_file_search_and_vector_stores_produce_retrieval_impacts():
    rec = _recommend(
        _workload(detected_features=["file_search_retrieval", "files_api", "vector_stores"])
    )
    assert {"file_search_retrieval", "files_api", "vector_stores"} <= _impact_features(rec)


def test_assistants_threads_produce_state_impacts():
    rec = _recommend(_workload(detected_features=["assistants_threads"]))
    assert "assistants_threads" in _impact_features(rec)


def test_modalities_are_separate_capability_paths():
    rec = _recommend(
        _workload(detected_features=["audio_modality", "embeddings", "images"])
    )
    assert {"audio_modality", "embeddings", "images"} <= _impact_features(rec)


def test_agentic_workload_uses_trajectory_evaluation():
    rec = _recommend(_workload(detected_features=["tool_or_function_calling"]))
    assert rec["evaluation"]["mode"] == "trajectory"


# --- 11.5 Catalog and verification ----------------------------------------

def test_context_requirement_beyond_every_catalog_window_requires_decision():
    # 2M exceeds every cataloged window (GPT-5.6 is 1M as of 2026-08-21 — a 400K
    # requirement now legitimately passes, which an earlier version of this test
    # used as its probe value). This is the KNOWN-limit-too-small case; the
    # unknown-limit invariant has its own probe below.
    rec = _recommend(_workload(requirements={"min_context_tokens": 2000000}))
    assert rec["decision_status"] == "decision_required"


def test_unknown_limits_do_not_pass_hard_numeric_requirement():
    # Fail-closed invariant: an unknown catalog limit cannot satisfy a hard numeric
    # need. output_token_ceiling is "unknown" on every entry as of 2026-08-21, so it
    # probes the invariant the way min_context_tokens no longer can.
    rec = _recommend(_workload(requirements={"expected_output_tokens": 100000}))
    assert rec["decision_status"] == "decision_required"
    assert "unverified_capacity" in _codes(rec["blocks"])


def test_cris_only_path_with_unresolvable_residency_blocks_explicitly():
    # GPT-5.6 on bedrock-runtime is CRIS-only. A residency posture permitting
    # neither Global nor Geo CRIS must surface an explicit block, not a silent
    # invocation_model_id: None.
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-5.6-terra"], "api_surface": "responses"},
        requirements={"governance": ["guardrails"], "data_residency": "in_region_required"},
    ))
    assert "cris_residency_unresolved" in _codes(rec["blocks"])

def test_no_aws_account_leaves_probe_not_run_and_provisional():
    rec = _recommend()
    assert rec["verification"]["probe_status"] == "not_run"
    assert rec["verification"]["availability_claim"] == "provisional"


def test_decision_required_verification_is_not_applicable():
    rec = _recommend(
        _workload(requirements={"api_continuity": "required", "governance": ["guardrails"]})
    )
    assert rec["verification"]["probe_status"] == "not_applicable"
    assert rec["verification"]["availability_claim"] == "not_selected"


def test_catalog_limits_are_sourced_or_unknown():
    # Limits must be positive sourced integers or the explicit string "unknown" —
    # never a fabricated placeholder. Every model must cite its capability source.
    for model in OPENAI_CATALOG["models"].values():
        for limit in (model["context_window"], model["output_token_ceiling"]):
            assert limit == "unknown" or (isinstance(limit, int) and limit > 0)
        assert model.get("capability_source")


# --- Mixed provider provenance (via orchestrator) -------------------------

def test_mixed_provider_run_keeps_catalog_provenance():
    data = {
        "schema_version": 2,
        "region": "us-east-2",
        "primary_unit": "claude-agent",
        "workloads": [
            {
                "workload_id": "claude-agent",
                "source": {
                    "provider": "anthropic",
                    "model_ids": ["claude-3-7-sonnet-latest"],
                    "sdk": "anthropic",
                    "api_surface": "messages",
                    "source_paths": ["a.py"],
                },
                "requirements": {"priority": "balanced", "critical_features": ["tool_use"]},
                "detected_features": [],
            },
            {
                "workload_id": "openai-svc",
                "source": {
                    "provider": "openai",
                    "model_ids": ["gpt-5.4"],
                    "sdk": "openai",
                    "api_surface": "responses",
                    "source_paths": ["b.py"],
                },
                "requirements": {"priority": "balanced", "critical_features": [], "api_continuity": "required"},
                "detected_features": [],
            },
        ],
    }
    out = model_recommendation.recommend(data)
    assert out["workloads"]["claude-agent"]["provider_module"] == "anthropic"
    assert out["workloads"]["openai-svc"]["provider_module"] == "openai"
    assert out["catalog_provenance"]["claude-agent"]["provider"] == "anthropic"
    assert out["catalog_provenance"]["openai-svc"]["provider"] == "openai"
    # Output validates against the schema.
    schema = json.loads((SCRIPTS / "schemas" / "model-recommendation.json").read_text())
    jsonschema.validate(out, schema)


def test_openai_output_validates_against_schema():
    data = {
        "schema_version": 2,
        "region": "us-east-2",
        "primary_unit": "chat-svc",
        "workloads": [_workload(requirements={"api_continuity": "required"})],
    }
    schemas = SCRIPTS / "schemas"
    jsonschema.validate(
        data, json.loads((schemas / "model-recommendation-input.json").read_text())
    )
    out = model_recommendation.recommend(data)
    jsonschema.validate(
        out, json.loads((schemas / "model-recommendation.json").read_text())
    )


# --- Regression tests for the Codex gap review (G01-G10) -------------------

def _delta_by_code(rec, code):
    return next((d for d in rec["migration_deltas"] if d["code"] == code), None)


def test_g01_runtime_target_is_not_reported_as_gpt5():
    # A Bedrock-native (Nova) target must not carry target_version gpt-5.x.
    rec = _recommend(_workload(requirements={"governance": ["guardrails"]}))
    assert rec["api_path"] == "runtime_converse"
    assert rec["source_analysis"]["target_version"] == "5"  # Claude Sonnet 5, not gpt-5.x
    assert rec["source_analysis"]["target_version"] != "gpt-5.x"


def test_g01_same_version_source_and_target_not_marked_changed():
    # gpt-5.6 source -> openai.gpt-5.6-sol target: version did not change.
    rec = _recommend(_workload(source={"model_ids": ["gpt-5.6"]}))
    assert rec["source_analysis"]["target_version"] == "5.6"
    assert rec["source_analysis"]["version_changed"] is False


def test_g01_legacy_source_to_reasoning_target_marks_generation_change():
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-4o"], "api_surface": "chat_completions"},
                  requirements={"api_continuity": "required"})
    )
    assert rec["source_analysis"]["model_generation_changes"] is True
    assert rec["source_analysis"]["version_changed"] is True


def test_g02_runtime_selection_fails_closed_on_unproven_capability():
    # No runtime_converse candidate has streaming evidence in the catalog, so a
    # workload requiring it must NOT get a silent native claim — it fails closed.
    rec = _recommend(
        _workload(
            requirements={"governance": ["guardrails"], "critical_features": ["streaming"]}
        )
    )
    assert rec["decision_status"] == "decision_required"
    assert "unverified_capability" in _codes(rec["blocks"])


def test_g02_native_only_lists_catalog_evidenced_features():
    # Detected structured output is only feature-probed on gpt-5.4, so the engine
    # falls back past gpt-5.6-sol (no structured-output evidence) to gpt-5.4 and
    # native lists exactly what that catalog entry supports.
    rec = _recommend(
        _workload(detected_features=["tool_or_function_calling", "structured_output_json"])
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.4"  # evidence-driven fallback
    assert set(rec["compatibility"]["native"]) == {
        "tool_or_function_calling",
        "structured_output_json",
    }


def test_g02_vision_requirement_selects_the_evidenced_candidate():
    # image_input_vision is evidenced on gpt-5.6-sol (model card) but not on
    # gpt-5.5/terra/luna/5.4 — the engine must select the evidenced candidate,
    # never claim native on an unevidenced one.
    rec = _recommend(
        _workload(
            requirements={"critical_features": ["image_input_vision"]},
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.6-sol"
    assert "image_input_vision" in rec["compatibility"]["native"]


def test_g03_mantle_keeps_typed_responses_parse():
    rec = _recommend(_workload(detected_features=["structured_output_json"]))
    delta = _delta_by_code(rec, "structured_output_text_format")
    assert delta is not None
    assert "responses.parse" in delta["description"]
    assert "no direct" not in delta["description"].lower()


def test_g04_mantle_state_offers_hosted_and_manual_modes():
    rec = _recommend(_workload(requirements={"uses_hosted_state": True}))
    delta = _delta_by_code(rec, "conversation_state_ownership")
    assert delta is not None
    assert "store=True" in delta["description"]
    assert "store=False" in delta["description"]


def test_g08_feature_status_unknown_blocks_readiness():
    rec = _recommend(
        _workload(
            requirements={"critical_features": ["structured_output_json"]},
            feature_status={"structured_output_json": "unknown"},
        )
    )
    assert "feature_scan_incomplete" in _codes(rec["blocks"])


def test_g08_feature_assessment_is_populated():
    rec = _recommend(
        _workload(
            detected_features=["tool_or_function_calling"],
            feature_status={"web_search": "absent"},
        )
    )
    assert rec["feature_assessment"]["tool_or_function_calling"] == "detected"
    assert rec["feature_assessment"]["web_search"] == "absent"


def test_g06_separate_modalities_emit_additional_targets():
    rec = _recommend(
        _workload(detected_features=["embeddings", "audio_modality", "images"])
    )
    targets = {t["capability"]: t for t in rec["additional_targets"]}
    assert set(targets) == {"embeddings", "audio_modality", "images"}
    # Unknown target model stays unresolved with a named service, never a fake ID.
    for cap, t in targets.items():
        assert t["status"] == "unresolved"
        assert t["candidate"] is None
        assert t["service"]


def test_g06_no_modalities_means_empty_additional_targets():
    rec = _recommend(_workload(detected_features=["tool_or_function_calling"]))
    assert rec["additional_targets"] == []


# --- Regression tests for the consistency re-review (N01-N04, G08 enforcement) ---

import json as _json  # noqa: E402
import pathlib as _pathlib  # noqa: E402

_OUT_SCHEMA = _json.loads(
    (SCRIPTS / "schemas" / "model-recommendation.json").read_text()
)


def _full_recommend(workload):
    data = {
        "schema_version": 2,
        "region": "us-east-2",
        "primary_unit": workload["workload_id"],
        "workloads": [workload],
    }
    return model_recommendation.recommend(data)


def test_n01_decision_required_openai_output_is_schema_valid():
    # A continuity/governance conflict is decision_required; the full artifact must
    # validate (model_generation_changes null before selection is allowed).
    out = _full_recommend(
        _workload(requirements={"api_continuity": "required", "governance": ["guardrails"]})
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert rec["source_analysis"]["model_generation_changes"] is None


def test_n02_absent_feature_is_not_reported_native_or_delta():
    rec = _recommend(
        _workload(feature_status={"structured_output_json": "absent"})
    )
    assert "structured_output_json" not in rec["compatibility"]["native"]
    assert "structured_output_text_format" not in _delta_codes(rec)


def test_n02_status_only_detected_feature_flows_to_behavior():
    # Detected via feature_status (not the array) must still drive native/delta.
    rec = _recommend(
        _workload(detected_features=[], feature_status={"tool_or_function_calling": "detected"})
    )
    assert "tool_or_function_calling" in rec["compatibility"]["native"]
    assert "tool_result_shape" in _delta_codes(rec)


def test_g08_unknown_required_feature_forces_decision_required():
    rec = _recommend(
        _workload(
            requirements={"critical_features": ["structured_output_json"]},
            feature_status={"structured_output_json": "unknown"},
        )
    )
    assert rec["decision_status"] == "decision_required"
    assert "feature_scan_incomplete" in _codes(rec["blocks"])
    assert rec["primary_model"] is None


def test_n03_tool_requirement_never_lands_on_unevidenced_nova():
    # Nova has no asserted capabilities; a governance workload requiring tools must
    # land on the evidenced Converse candidate (Claude), never claim Nova native.
    rec = _recommend(
        _workload(
            requirements={
                "governance": ["guardrails"],
                "critical_features": ["tool_or_function_calling"],
            }
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert "tool_or_function_calling" in rec["compatibility"]["native"]


def test_n04_logprobs_and_stop_not_declared_rejected():
    rec = _recommend(_workload(source={"model_ids": ["gpt-5.4"]}))
    finding = next(
        f for f in rec["tuning"] if f["code"] == "sampling_penalties_rejected"
    )
    # Only the two probed penalties are declared rejected in the message.
    assert "frequency_penalty" in finding["message"]
    assert "presence_penalty" in finding["message"]
    assert "logprobs" not in finding["message"]
    assert "stop" not in finding["message"]
    # logprobs/stop are routed to verification, not rejection.
    assert "verify" in finding["remediation"].lower()


# --- Converse tier mapping (source OpenAI tier -> matching Claude tier) ----

def test_tier_map_sol_source_maps_to_opus_on_converse():
    # Verified 2026-08-21: GPT-5.6 runs on bedrock-runtime via CRIS, so a 5.6
    # source with governance requirements keeps ITS OWN model — the same-model
    # candidate outranks the Claude tier. (Before 2026-08-21 the docs said
    # mantle-only, and this test asserted the Opus fallback.)
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-sol"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec["primary_model"] == "openai.gpt-5.6-sol"
    assert rec["api_path"] == "runtime_converse"


def test_tier_map_sol_cross_family_fallback_is_opus():
    # The Claude tier map is preserved as the cross-family option behind the
    # same-model candidate.
    from openai_model_recommendation import _converse_candidate_order
    order = _converse_candidate_order({"model_ids": ["gpt-5.6-sol"]})
    assert order[0] == "openai_gpt_5_6_sol"
    assert order[1] == "anthropic_claude_opus_4_8"

def test_tier_map_luna_source_maps_to_haiku_on_converse():
    # Same-model-first (2026-08-21): Luna keeps Luna; Haiku is the cross-family
    # fallback in the candidate order.
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-luna"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec["primary_model"] == "openai.gpt-5.6-luna"
    from openai_model_recommendation import _converse_candidate_order
    order = _converse_candidate_order({"model_ids": ["gpt-5.6-luna"]})
    assert order[0] == "openai_gpt_5_6_luna"
    assert order[1] == "anthropic_claude_haiku_4_5"

def test_tier_map_terra_and_55_sources_map_to_sonnet_on_converse():
    # Terra (5.6) keeps itself — same-model runtime path exists. GPT-5.5 has NO
    # runtime path (mantle-only, re-verified 2026-08-21), so its governance
    # Converse target remains the Claude balanced tier.
    rec_terra = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-terra"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec_terra["primary_model"] == "openai.gpt-5.6-terra"
    rec_55 = _recommend(
        _workload(source={"model_ids": ["gpt-5.5"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec_55["primary_model"] == "anthropic.claude-sonnet-5"

def test_tier_map_falls_back_across_tiers_on_capability_evidence():
    # The capability-evidence fallback mechanism: when the first candidate in the
    # order lacks evidence for a critical feature, the engine advances to the next
    # tier that covers it. Exercised with an explicit order because the Luna
    # source no longer produces a Haiku-first order — its same-model candidate
    # carries reasoning evidence and satisfies the requirement directly
    # (2026-08-21 same-model-first change).
    from model_recommendation import load_openai_catalog
    from openai_model_recommendation import _catalog_model_for_path
    catalog = load_openai_catalog()
    hit, unmet = _catalog_model_for_path(
        catalog, "runtime_converse", detected_features=[],
        requirements={"critical_features": ["reasoning"]},
        candidate_order=["anthropic_claude_haiku_4_5", "anthropic_claude_sonnet_5"],
    )
    assert hit is not None
    assert hit[0] == "anthropic_claude_sonnet_5"


def test_same_model_governance_still_recommended_end_to_end():
    # A 5.6 source with governance + reasoning requirement lands on itself.
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-luna"]},
                  requirements={"governance": ["guardrails"],
                                "critical_features": ["reasoning"]})
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.6-luna"
    assert rec["api_path"] == "runtime_converse"
