"""Tests for the OpenAI-to-Bedrock provider module (handoff Section 11 matrix).

Endpoint rule under test (skills/shared/ai/bedrock-endpoint-policy.md): the OpenAI
source stays on bedrock-runtime Responses / Chat Completions on the same model by
default; a bedrock-mantle path is selected only by a mantle_selector (explicit, or
derived from a detected Web Search tool / strict in-Region processing); Guardrails
and multi-model Converse select runtime Converse.
"""

import copy
import json
import pathlib
import re
import urllib.parse

import jsonschema
import pytest

import model_recommendation
import openai_model_recommendation as oai


SCRIPTS = pathlib.Path(model_recommendation.__file__).parent
OPENAI_CATALOG = model_recommendation.load_openai_catalog()
_URL = re.compile(r"https?://[^\s)\]]+")


def _cites_aws_docs(text):
    """True when `text` contains an https URL whose host is exactly
    docs.aws.amazon.com (hostname equality after urlparse, not a substring)."""
    urls = _URL.findall(text or "")
    return any(
        urllib.parse.urlparse(url).scheme == "https"
        and urllib.parse.urlparse(url).hostname == "docs.aws.amazon.com"
        for url in urls
    )


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


def _recommend(workload=None, region="us-east-2"):
    return oai.recommend_openai_workload(
        workload or _workload(), region, OPENAI_CATALOG
    )


def _codes(items):
    return {item["code"] for item in items}


def _delta_codes(rec):
    return {d["code"] for d in rec["migration_deltas"]}


# --- 11.1 Provider and path selection -------------------------------------
#
# bedrock-runtime is the default endpoint (bedrock-endpoint-policy.md); a
# bedrock-mantle path is selected only by a mantle_selector. API continuity alone
# never selects Mantle.

def test_default_responses_source_lands_on_runtime_responses_same_model():
    rec = _recommend()
    assert rec["provider_module"] == "openai"
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["mantle_selector"] is None
    assert rec["model_identity"]["requires_cris"] is True
    # Residency is unknown, so no CRIS prefix is guessed; the block says why.
    assert rec["invocation_model_id"] is None
    block = next(b for b in rec["blocks"] if b["code"] == "cris_residency_unresolved")
    assert "unresolved" in block["message"]
    assert "data_residency" in block["remediation"]


def test_default_with_global_residency_resolves_global_cris_id():
    rec = _recommend(_workload(requirements={"data_residency": "global_allowed"}))
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["invocation_model_id"] == "global.openai.gpt-5.4"
    assert "cris_residency_unresolved" not in _codes(rec["blocks"])


def test_responses_source_with_continuity_lands_on_runtime_responses():
    # Negative test: Responses-only continuity selects bedrock-runtime, not Mantle.
    rec = _recommend(
        _workload(requirements={"api_continuity": "required"})
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["mantle_selector"] is None
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])


def test_chat_completions_continuity_lands_on_runtime_chat_same_model():
    # gpt-5.4 is a recognized same-model identity; its card lists Chat Completions
    # on bedrock-runtime, so the Chat source stays on itself with no reshape.
    rec = _recommend(
        _workload(
            source={"api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["api_path"] == "runtime_openai_chat"
    assert rec["mantle_selector"] is None
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])
    assert "responses_no_n" not in _delta_codes(rec)


def test_continuity_plus_logging_governance_stays_on_runtime_openai_api():
    # invocation_logging / cloudwatch are satisfied on any bedrock-runtime path.
    rec = _recommend(
        _workload(
            requirements={
                "api_continuity": "required",
                "governance": ["invocation_logging", "cloudwatch"],
            }
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.4"


# `workspaces` scopes the Anthropic Messages API and is a provider-mismatch decision below.
@pytest.mark.parametrize("selector", [s for s in oai.MANTLE_SELECTORS if s != "workspaces"])
def test_each_mantle_selector_selects_mantle_and_is_echoed(selector):
    rec = _recommend(_workload(requirements={"mantle_selector": selector}))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["invocation_model_id"] == "openai.gpt-5.4"
    assert rec["mantle_selector"] == selector


def test_mantle_selectors_match_the_input_schema_enum():
    schema = json.loads((SCRIPTS / "schemas" / "model-recommendation-input.json").read_text())
    enum = schema["properties"]["workloads"]["items"]["properties"]["requirements"][
        "properties"]["mantle_selector"]["enum"]
    assert list(oai.MANTLE_SELECTORS) == enum


def test_unknown_mantle_selector_is_rejected():
    with pytest.raises(ValueError, match="mantle_selector"):
        _recommend(_workload(requirements={"mantle_selector": "because"}))


@pytest.mark.parametrize(
    ("catalog_key", "model_id", "card"),
    [
        ("openai_gpt_5_4", "openai.gpt-5.4", "model-card-openai-gpt-54.html"),
        ("openai_gpt_5_5", "openai.gpt-5.5", "model-card-openai-gpt-55.html"),
    ],
)
def test_catalog_gpt54_gpt55_record_public_runtime_and_chat_facts(catalog_key, model_id, card):
    # Public model cards (read 2026-11-06): both models list bedrock-runtime
    # (Responses, Chat Completions, Converse via us./global. CRIS ids; no in-region
    # form), Chat Completions on bedrock-mantle, a 1,050,000-token context window
    # and 128,000 max output. Provenance must be the public card, never an
    # internal reference.
    model = OPENAI_CATALOG["models"][catalog_key]
    paths = model["paths"]
    assert paths["mantle_openai_responses"]["available"] is True
    assert paths["mantle_openai_chat"]["available"] is True
    assert paths["runtime_converse"]["available"] is True
    assert paths["runtime_converse"]["requires_cris"] is True
    assert paths["runtime_converse"]["model_id"] == model_id
    assert f"us.{model_id}" in paths["runtime_converse"]["evidence"]
    assert f"global.{model_id}" in paths["runtime_converse"]["evidence"]
    assert set(model["inference_profiles"]) == {"us", "global"}
    assert model["context_window"] == 1050000
    assert model["output_token_ceiling"] == 128000
    assert card in model["capability_source"]
    for path in paths.values():
        assert "internal reference" not in path["evidence"]
    assert "internal reference" not in model["capability_source"]


def test_runtime_converse_path_text_does_not_grant_in_profile_to_gpt54_gpt55():
    # The GPT-5.4 / GPT-5.5 cards publish only us. and global. CRIS ids; only
    # GPT-5.6 has an in. profile. The shared runtime_converse path text must not
    # attach the in. prefix to the 5.4/5.5 models, and its feature constraints
    # must be stated per model (5.4/5.5 cards list structured outputs on Responses
    # and application inference profiles on Converse, which the GPT-5.6 sentence
    # denies).
    path = OPENAI_CATALOG["paths"]["runtime_converse"]
    strengths = "\n".join(path["strengths"])
    constraints = "\n".join(path["constraints"])
    assert "For GPT-5.6, GPT-5.5 and GPT-5.4" not in strengths
    # in. and us-gov. exist for GPT-5.6 Terra/Luna only; Sol, 5.5 and 5.4 are us./global.
    assert "GPT-5.6 Terra and Luna publish us./in./us-gov./global. ids" in strengths
    assert "us./global. only for GPT-5.6 Sol, GPT-5.5 and GPT-5.4" in strengths
    assert "For GPT-5.6, runtime does not support server-side tool use" in constraints
    # The GPT-5.6 cards (read 2026-11-08) document non-streaming JSON Schema on
    # Responses/Chat Completions; the sentence must not deny structured outputs
    # outright, nor claim them as catalog capabilities.
    assert "does not support server-side tool use, structured outputs" not in constraints
    assert "not yet carried as catalog capabilities" in constraints
    assert "GPT-5.5 / GPT-5.4 on runtime" in constraints
    assert "structured outputs and implicit prompt caching are Responses-only" in constraints
    assert "Guardrails and application inference profiles are Converse-only" in constraints


@pytest.mark.parametrize("source_id,requirements,path", [
    # A Chat source explicitly moved to bedrock-runtime Responses.
    ("gpt-5.4", {"preferred_api_path": "runtime_openai_responses"}, "runtime_openai_responses"),
    # A Chat source explicitly moved to Mantle Responses by selector + preference
    # (GPT-5.6 Sol's card lists Mantle Chat too, so this reshape is a choice).
    ("gpt-5.6-sol", {"preferred_api_path": "mantle_openai_responses",
                     "mantle_selector": "background_inference"}, "mantle_openai_responses"),
])
def test_chat_completions_case_includes_full_reshape_deltas(source_id, requirements, path):
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements=requirements,
            detected_features=["tool_or_function_calling", "conversation_state"],
        ),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == path
    assert "chat_completions_to_responses_required" in _codes(rec["blocks"])
    codes = _delta_codes(rec)
    assert "chat_to_responses_request" in codes
    assert "chat_to_responses_response" in codes
    assert "chat_to_responses_tools" in codes
    assert "chat_to_responses_state" in codes


@pytest.mark.parametrize("source_id", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
def test_gpt56_chat_source_with_selector_keeps_its_own_model_on_mantle_chat(source_id):
    # The GPT-5.6 Sol, Terra and Luna cards (read 2026-11-08) list Chat Completions
    # on bedrock-mantle, so a Chat source with a selector stays on the same model
    # and the same API — no fallback, no reshape.
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements={"mantle_selector": "projects"},
        ),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_chat"
    assert rec["primary_model"] == f"openai.{source_id}"
    assert rec["mantle_selector"] == "projects"
    assert "fallback" not in rec["rationale"][0]
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])


def test_gpt56_sol_chat_with_selector_outside_its_mantle_footprint_falls_to_terra():
    # The region gate is unchanged: Sol's Mantle footprint is us-east-1/us-east-2,
    # so a GovCloud caller lands on Terra's in-region Mantle Chat row.
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-sol"], "api_surface": "chat_completions"},
            requirements={"mantle_selector": "projects"},
        ),
        region="us-gov-west-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_chat"
    assert rec["primary_model"] == "openai.gpt-5.6-terra"
    assert "fallback" in rec["rationale"][0]


def test_governance_selects_runtime_converse():
    # Cross-family Converse tier: an unrecognized source id (gpt-4) with Guardrails.
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-4"]},
            requirements={"governance": ["guardrails", "invocation_logging"]},
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert rec["model_identity"]["display_name"] == (
        "Claude Sonnet 5 (Converse tier match for GPT-5.6 Terra / 5.5 / 5.4)"
    )
    assert rec["model_identity"]["version"] == "5"
    assert rec["mantle_selector"] is None


def test_continuity_plus_converse_only_governance_returns_two_runtime_options():
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
    assert rec["mantle_selector"] is None
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "runtime_openai_responses",
        "runtime_converse",
    }
    assert all(o["mantle_selector"] is None for o in rec["decision_options"])
    assert "model_path_decision_required" in _codes(rec["blocks"])
    assert "Converse-only governance" in rec["blocks"][0]["message"]


def test_decision_options_explain_tradeoffs():
    rec = _recommend(
        _workload(
            requirements={"api_continuity": "required", "governance": ["guardrails"]}
        )
    )
    reasons = {o["api_path"]: o["reason"] for o in rec["decision_options"]}
    assert "OpenAI SDK" in reasons["runtime_openai_responses"]
    assert "Converse" in reasons["runtime_openai_responses"]
    # gpt-5.4 is a recognized same-model identity: Converse keeps the model.
    assert "SAME-MODEL" in reasons["runtime_converse"]


def test_cross_family_converse_option_names_the_bedrock_native_rewrite():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-4"]},
            requirements={"api_continuity": "required", "governance": ["guardrails"]},
        )
    )
    reasons = {o["api_path"]: o["reason"] for o in rec["decision_options"]}
    assert "Bedrock-native" in reasons["runtime_converse"]


# --- Web Search: a Mantle-only server-side tool (mantle_selector web_search) --

def test_detected_web_search_derives_the_mantle_selector():
    rec = _recommend(_workload(detected_features=["web_search"]))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["mantle_selector"] == "web_search"
    impacts = {a["feature"]: a["impact"] for a in rec["architecture_impacts"]}
    assert "bedrock-mantle" in impacts["web_search"]
    assert "passthrough" not in impacts["web_search"].lower()
    assert _cites_aws_docs(impacts["web_search"])
    assert "web_search" not in rec["compatibility"]["rearchitecture"]
    assert "web_search" in rec["compatibility"]["portable"]


def test_web_search_plus_guardrails_offers_a_mantle_option_with_the_selector():
    rec = _recommend(
        _workload(detected_features=["web_search"], requirements={"governance": ["guardrails"]})
    )
    assert rec["decision_status"] == "decision_required"
    assert "model_path_decision_required" in _codes(rec["blocks"])
    assert "web_search" in rec["blocks"][0]["message"]
    mantle = next(o for o in rec["decision_options"] if o["api_path"].startswith("mantle_"))
    assert mantle["api_path"] == "mantle_openai_responses"
    assert mantle["mantle_selector"] == "web_search"
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_converse",
    }


def test_web_search_plus_logging_governance_offers_the_runtime_openai_api():
    rec = _recommend(
        _workload(detected_features=["web_search"],
                  requirements={"governance": ["invocation_logging"]})
    )
    assert rec["decision_status"] == "decision_required"
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_responses",
    }


def test_web_search_marked_absent_does_not_select_mantle():
    rec = _recommend(
        _workload(detected_features=["web_search"], feature_status={"web_search": "absent"})
    )
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["mantle_selector"] is None
    assert "web_search" not in rec["compatibility"]["portable"]


def test_web_search_on_a_runtime_path_stays_rearchitecture():
    compat = oai._compatibility(["web_search"], {}, "runtime_openai_responses",
                                OPENAI_CATALOG["models"]["openai_gpt_5_4"])
    assert "web_search" in compat["rearchitecture"]
    assert "web_search" not in compat["portable"]


# --- Derived in_region_processing ------------------------------------------

def test_in_region_required_on_cris_only_runtime_model_selects_mantle():
    rec = _recommend(_workload(requirements={"data_residency": "in_region_required"}))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["invocation_model_id"] == "openai.gpt-5.4"
    assert rec["mantle_selector"] == "in_region_processing"
    assert "in_region_processing" in rec["rationale"][0]
    assert "cris_residency_unresolved" not in _codes(rec["blocks"])


def test_in_region_required_with_guardrails_stays_on_runtime_and_blocks():
    rec = _recommend(_workload(requirements={
        "data_residency": "in_region_required", "governance": ["guardrails"],
    }))
    assert rec["api_path"] == "runtime_converse"
    assert rec["mantle_selector"] is None
    assert "cris_residency_unresolved" in _codes(rec["blocks"])


# --- Invocation logging vs. a Mantle selector (model-invocation-logging.html,
# read 2026-11-08: logging is captured only on bedrock-runtime) --------------

def _option(rec, api_path):
    return next(o for o in rec["decision_options"] if o["api_path"] == api_path)


def test_logging_plus_explicit_selector_is_a_decision_between_mantle_and_runtime_openai_api():
    out = _full_recommend(_workload(requirements={
        "governance": ["invocation_logging"], "mantle_selector": "projects",
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert rec["mantle_selector"] is None
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_responses",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "projects"
    assert _option(rec, "runtime_openai_responses")["mantle_selector"] is None
    assert "invocation logging" in rec["blocks"][0]["message"]
    assert "CloudWatch" not in rec["blocks"][0]["message"]


def test_logging_plus_derived_in_region_is_a_decision_carrying_the_derived_selector():
    out = _full_recommend(_workload(requirements={
        "governance": ["invocation_logging"], "data_residency": "in_region_required",
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "model_path_decision_required" in _codes(rec["blocks"])
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_responses",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "in_region_processing"
    assert "in_region_processing" in rec["blocks"][0]["message"]
    assert "invocation logging" in rec["blocks"][0]["message"]


# --- CloudWatch never constrains the endpoint (monitoring-mantle-metrics.html,
# read 2026-11-08: Mantle publishes AWS/BedrockMantle metrics) ---------------

def test_cloudwatch_plus_selector_lands_on_mantle_with_the_selector():
    rec = _recommend(_workload(requirements={
        "governance": ["cloudwatch"], "mantle_selector": "projects",
    }))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["mantle_selector"] == "projects"


def test_cloudwatch_plus_in_region_derives_the_mantle_selector():
    rec = _recommend(_workload(requirements={
        "governance": ["cloudwatch"], "data_residency": "in_region_required",
    }))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["mantle_selector"] == "in_region_processing"


def test_cloudwatch_plus_logging_plus_selector_is_still_a_decision():
    rec = _recommend(_workload(requirements={
        "governance": ["cloudwatch", "invocation_logging"], "mantle_selector": "projects",
    }))
    assert rec["decision_status"] == "decision_required"
    assert "model_path_decision_required" in _codes(rec["blocks"])


# --- Guardrails follow the model card's API scope ---------------------------
#
# GPT-6 Sol / GPT-6 Luna list Guardrails on Responses, Chat Completions, Invoke
# and Converse; GPT-6.1 Sol on Chat Completions, Invoke and Converse (not
# Responses); every other GPT card lists Converse only (cards read 2026-11-08).

@pytest.mark.parametrize(("source_id", "surface", "path"), [
    ("gpt-6-sol", "responses", "runtime_openai_responses"),
    ("gpt-6-sol", "chat_completions", "runtime_openai_chat"),
    ("gpt-6-luna", "responses", "runtime_openai_responses"),
    ("gpt-6.1-sol", "chat_completions", "runtime_openai_chat"),
])
def test_guardrails_listed_on_the_openai_api_keep_the_source_api_and_model(
    source_id, surface, path
):
    out = _full_recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": surface},
            requirements={
                "api_continuity": "required", "governance": ["guardrails"],
                "data_residency": "global_allowed",
            },
        ),
        region="us-east-1",
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == path
    assert rec["primary_model"] == f"openai.{source_id}"
    assert rec["invocation_model_id"] == f"global.openai.{source_id}"
    assert rec["mantle_selector"] is None
    assert "model_path_decision_required" not in _codes(rec["blocks"])
    assert OPENAI_CATALOG["models"][oai._SOURCE_MODEL_KEYS[source_id]]["paths"][path][
        "guardrails_supported"] is True


def test_gpt61_sol_responses_with_guardrails_and_continuity_is_a_decision():
    # The GPT-6.1 Sol card scopes Guardrails away from Responses.
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-6.1-sol"]},
            requirements={"api_continuity": "required", "governance": ["guardrails"],
                          "data_residency": "global_allowed"},
        ),
        region="us-east-1",
    )
    assert rec["decision_status"] == "decision_required"
    assert "model_path_decision_required" in _codes(rec["blocks"])
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "runtime_openai_responses", "runtime_converse",
    }
    assert "Converse" in _option(rec, "runtime_openai_responses")["reason"]
    assert _option(rec, "runtime_converse")["model"] == "openai.gpt-6.1-sol"


def test_guardrails_without_continuity_keep_converse_only_models_on_converse():
    rec = _recommend(_workload(requirements={"governance": ["guardrails"]}))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "openai.gpt-5.4"


def test_guardrails_on_the_openai_api_plus_selector_offers_the_runtime_openai_api():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-6-sol"]},
            requirements={"governance": ["guardrails"], "mantle_selector": "server_side_tools"},
        ),
        region="us-east-1",
    )
    assert rec["decision_status"] == "decision_required"
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_responses",
    }
    assert "Guardrails are listed on this API" in _option(rec, "runtime_openai_responses")["reason"]
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "server_side_tools"


# --- An explicit bedrock-runtime preference never coexists with a selector ----

def test_preferred_runtime_path_plus_explicit_selector_is_a_preference_conflict():
    out = _full_recommend(_workload(requirements={
        "preferred_api_path": "runtime_openai_responses",
        "mantle_selector": "background_inference",
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "preferred_api_path_conflict" in _codes(rec["blocks"])
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_responses",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "background_inference"
    assert "background_inference" in rec["blocks"][0]["message"]


def test_preferred_runtime_path_plus_derived_in_region_is_a_preference_conflict():
    out = _full_recommend(_workload(requirements={
        "preferred_api_path": "runtime_openai_responses",
        "data_residency": "in_region_required",
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "preferred_api_path_conflict" in _codes(rec["blocks"])
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "in_region_processing"
    assert _option(rec, "runtime_openai_responses")["mantle_selector"] is None
    assert "in_region_required" in rec["blocks"][0]["message"]


def test_preferred_runtime_path_plus_detected_web_search_is_a_preference_conflict():
    rec = _recommend(_workload(
        detected_features=["web_search"],
        requirements={"preferred_api_path": "runtime_openai_responses"},
    ))
    assert rec["decision_status"] == "decision_required"
    assert "preferred_api_path_conflict" in _codes(rec["blocks"])
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "web_search"


@pytest.mark.parametrize("requirements", [
    {"mantle_selector": "projects"},
    {"mantle_selector": "background_inference"},
    {"data_residency": "in_region_required"},
    {"mantle_selector": "web_search", "governance": ["cloudwatch"]},
])
def test_a_recommended_runtime_path_never_carries_a_selector(requirements):
    rec = _recommend(_workload(requirements=requirements))
    if rec["decision_status"] == "recommended":
        assert rec["api_path"].startswith("mantle_")
        assert rec["mantle_selector"] is not None
    else:
        assert any(o["api_path"].startswith("mantle_") for o in rec["decision_options"])


# --- Background inference is a Mantle Responses API feature
# (inference-responses-api.html, read 2026-11-08) ----------------------------

def test_chat_source_with_background_inference_is_a_decision_between_mantle_responses_and_runtime_chat():
    out = _full_recommend(_workload(
        source={"api_surface": "chat_completions"},
        requirements={"mantle_selector": "background_inference"},
    ))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "selector_api_incompatible" in _codes(rec["blocks"])
    assert _cites_aws_docs(rec["blocks"][0]["message"])
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_chat",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "background_inference"
    assert _option(rec, "runtime_openai_chat")["mantle_selector"] is None


def test_chat_source_with_background_inference_and_free_continuity_reshapes_to_mantle_responses():
    rec = _recommend(_workload(
        source={"api_surface": "chat_completions"},
        requirements={"mantle_selector": "background_inference",
                      "api_continuity": "not_required"},
    ))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["mantle_selector"] == "background_inference"
    assert "chat_completions_to_responses_required" in _codes(rec["blocks"])


def test_preferred_mantle_chat_with_background_inference_is_a_decision():
    rec = _recommend(_workload(
        source={"api_surface": "chat_completions"},
        requirements={"preferred_api_path": "mantle_openai_chat",
                      "mantle_selector": "background_inference"},
    ))
    assert rec["decision_status"] == "decision_required"
    assert _codes(rec["blocks"]) & {"preferred_api_path_conflict", "selector_api_incompatible"}
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "background_inference"


# --- Web Search is a bedrock-mantle Responses API tool (web-search.html, read
# 2026-11-09); every selector is validated against the final provider and API ----

def test_gpt55_chat_source_with_web_search_is_a_decision_between_mantle_responses_and_runtime_chat():
    out = _full_recommend(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
                  requirements={"critical_features": ["web_search"]}),
        region="us-east-1",
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert "selector_api_incompatible" in _codes(rec["blocks"])
    assert _cites_aws_docs(rec["blocks"][0]["message"])
    assert "web-search.html" in rec["blocks"][0]["message"]
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_chat",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "web_search"
    assert _option(rec, "runtime_openai_chat")["mantle_selector"] is None
    assert not any(o["api_path"] == "mantle_openai_chat" for o in rec["decision_options"])


def test_gpt55_chat_with_web_search_and_free_continuity_reshapes_to_mantle_responses():
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
                  requirements={"critical_features": ["web_search"],
                                "api_continuity": "not_required"}),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.5"
    assert rec["mantle_selector"] == "web_search"
    assert "chat_completions_to_responses_required" in _codes(rec["blocks"])
    assert "web_search" in rec["compatibility"]["portable"]


def test_chat_source_with_web_search_plus_logging_never_offers_a_mantle_chat_option():
    out = _full_recommend(_workload(
        source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
        requirements={"critical_features": ["web_search"],
                      "governance": ["invocation_logging"]},
    ), region="us-east-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "mantle_openai_responses", "runtime_openai_chat",
    }
    assert _option(rec, "mantle_openai_responses")["mantle_selector"] == "web_search"


def test_workspaces_selector_on_an_openai_source_is_a_provider_mismatch_decision():
    out = _full_recommend(_workload(requirements={"mantle_selector": "workspaces"}))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert rec["mantle_selector"] is None
    assert "selector_provider_mismatch" in _codes(rec["blocks"])
    block = next(b for b in rec["blocks"] if b["code"] == "selector_provider_mismatch")
    assert _cites_aws_docs(block["message"])
    assert "anthropic-workspace-id" in block["message"]
    assert "`projects`" in block["message"]
    # Both options stay on bedrock-runtime: the source API, or Converse governance.
    assert {o["api_path"] for o in rec["decision_options"]} == {
        "runtime_openai_responses", "runtime_converse",
    }
    assert not any(o["api_path"].startswith("mantle_") for o in rec["decision_options"])


# --- GPT-6.1 Sol lists server-side system tools as unsupported on bedrock-mantle
# (model-card-openai-gpt-6-1-sol.html, read 2026-11-08) -----------------------

@pytest.mark.parametrize(("surface", "selector", "path"), [
    ("responses", "server_side_tools", "mantle_openai_responses"),
    ("chat_completions", "server_side_tools", "mantle_openai_chat"),
    # Web Search is Responses-only: the Chat source reshapes once continuity is free.
    ("chat_completions", "web_search", "mantle_openai_responses"),
])
def test_gpt61_sol_server_side_tool_selectors_fall_to_astra_and_keep_the_selector(
    surface, selector, path
):
    requirements = {"mantle_selector": selector}
    if surface == "responses":
        requirements["api_continuity"] = "required"
    if selector == "web_search":
        requirements["api_continuity"] = "not_required"
    out = _full_recommend(
        _workload(source={"model_ids": ["gpt-6.1-sol"], "api_surface": surface},
                  requirements=requirements),
        region="us-east-1",
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == path
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["mantle_selector"] == selector
    assert "fallback" in rec["rationale"][0]
    assert "server-side system tools" in rec["rationale"][0]


def test_catalog_walk_skips_mantle_rows_that_deny_server_side_tools_only_for_tool_selectors():
    order = ["openai_gpt_6_1_sol", "openai_gpt_6_astra"]
    for selector in ("server_side_tools", "web_search"):
        hit, _ = oai._catalog_model_for_path(
            OPENAI_CATALOG, "mantle_openai_responses", [], {}, candidate_order=order,
            region="us-east-1", selector=selector,
        )
        assert hit[0] == "openai_gpt_6_astra"
    hit, _ = oai._catalog_model_for_path(
        OPENAI_CATALOG, "mantle_openai_responses", [], {}, candidate_order=order,
        region="us-east-1", selector="projects",
    )
    assert hit[0] == "openai_gpt_6_1_sol"


# --- Application inference profiles are Converse-only on bedrock-runtime
# (inference-responses-api.html, read 2026-11-08: Responses/Chat return HTTP 400) --

_APP_PROFILE = "arn:aws:bedrock:us-east-2:123456789012:application-inference-profile/app1"


def test_application_profile_without_continuity_is_recommended_on_converse_with_the_arn():
    out = _full_recommend(_workload(requirements={
        "data_residency": "geo_required", "cris_geography": "us",
        "inference_profile_id": _APP_PROFILE,
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert rec["invocation_model_id"] == _APP_PROFILE


def test_application_profile_with_continuity_is_a_decision_whose_openai_option_has_no_id():
    out = _full_recommend(_workload(requirements={
        "api_continuity": "required", "data_residency": "geo_required",
        "cris_geography": "us", "inference_profile_id": _APP_PROFILE,
    }))
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "application inference profile" in rec["blocks"][0]["message"]
    openai_option = _option(rec, "runtime_openai_responses")
    assert openai_option["invocation_model_id"] is None
    assert "400" in openai_option["reason"]
    assert _cites_aws_docs(openai_option["reason"])
    assert _option(rec, "runtime_converse")["invocation_model_id"] == _APP_PROFILE


def test_application_profile_with_a_preferred_openai_api_is_a_preference_conflict():
    rec = _recommend(_workload(requirements={
        "preferred_api_path": "runtime_openai_responses", "data_residency": "geo_required",
        "cris_geography": "us", "inference_profile_id": _APP_PROFILE,
    }))
    assert rec["decision_status"] == "decision_required"
    assert "preferred_api_path_conflict" in _codes(rec["blocks"])
    assert "application inference profile" in rec["blocks"][0]["message"]
    assert all(
        o["invocation_model_id"] != _APP_PROFILE
        for o in rec["decision_options"] if o["api_path"] != "runtime_converse"
    )


def test_system_profile_with_continuity_stays_on_runtime_responses_with_that_id():
    rec = _recommend(_workload(requirements={
        "inference_profile_id": "us.openai.gpt-5.4", "api_continuity": "required",
        "data_residency": "geo_required", "cris_geography": "us",
    }))
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["invocation_model_id"] == "us.openai.gpt-5.4"


# --- GPT-6 exact-model routing --------------------------------------------

_GPT6_MODELS = (
    ("gpt-6-astra", "openai.gpt-6-astra"),
    ("gpt-6-sol", "openai.gpt-6-sol"),
    ("gpt-6-luna", "openai.gpt-6-luna"),
    ("gpt-6.1-sol", "openai.gpt-6.1-sol"),
)


@pytest.mark.parametrize(("source_id", "target_id"), _GPT6_MODELS)
@pytest.mark.parametrize(("selector", "path"), [
    (None, "runtime_openai_responses"),
    ("server_side_tools", "mantle_openai_responses"),
])
def test_gpt6_supported_region_selects_exact_model_and_validates_schema(
    source_id, target_id, selector, path
):
    critical = ["image_input_vision"] if source_id in {"gpt-6-sol", "gpt-6-luna"} else []
    requirements = {"api_continuity": "required", "critical_features": critical}
    if selector:
        requirements["mantle_selector"] = selector
    workload = _workload(source={"model_ids": [source_id]}, requirements=requirements)
    out = _full_recommend(workload, region="us-east-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert oai.detect_family(source_id) == "reasoning"
    assert rec["decision_status"] == "recommended"
    if selector and source_id == "gpt-6.1-sol":
        # The GPT-6.1 Sol card lists server-side system tools as unsupported on
        # bedrock-mantle (read 2026-11-08): the selector is kept and the walk falls
        # to the next same-family model that serves them.
        assert rec["primary_model"] == "openai.gpt-6-astra"
        assert "fallback" in rec["rationale"][0]
    else:
        assert rec["primary_model"] == target_id
    assert rec["api_path"] == path
    assert rec["mantle_selector"] == selector
    if critical:
        assert "image_input_vision" in rec["compatibility"]["native"]


@pytest.mark.parametrize(("source_id", "target_id"), _GPT6_MODELS)
@pytest.mark.parametrize(
    ("residency", "extra_requirements", "prefix"),
    (
        ("global_allowed", {}, "global."),
        ("geo_required", {"cris_geography": "us"}, "us."),
    ),
)
def test_gpt6_governance_selects_exact_runtime_model_and_cris_id(
    source_id, target_id, residency, extra_requirements, prefix
):
    requirements = {
        "governance": ["guardrails"],
        "data_residency": residency,
        **extra_requirements,
    }
    rec = _recommend(
        _workload(source={"model_ids": [source_id]}, requirements=requirements)
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == target_id
    assert rec["invocation_model_id"] == prefix + target_id
    if source_id in {"gpt-6-sol", "gpt-6-luna"}:
        # Their cards list Guardrails on the Responses API (read 2026-11-08), so the
        # source API stays on bedrock-runtime with the same model and CRIS id.
        assert rec["api_path"] == "runtime_openai_responses"
        assert "Guardrails are listed on Responses" in rec["rationale"][0]
        assert "openai_sdk_to_converse" not in _delta_codes(rec)
    else:
        # GPT-6 Astra and GPT-6.1 Sol scope Guardrails to Converse for a Responses source.
        assert rec["api_path"] == "runtime_converse"
        delta = _delta_by_code(rec, "openai_sdk_to_converse")
        assert "identity is preserved" in delta["description"]
        assert "Bedrock-native model" not in delta["description"]


@pytest.mark.parametrize(
    ("source_id", "region", "geography", "unsupported_id"),
    (
        ("gpt-6-sol", "eu-west-1", "eu", "eu.openai.gpt-6-sol"),
        ("gpt-6.1-sol", "ap-southeast-2", "au", "au.openai.gpt-6.1-sol"),
    ),
)
def test_gpt6_unsupported_geo_profile_falls_back_without_fabricated_id(
    source_id, region, geography, unsupported_id
):
    requirements = {
        "governance": ["guardrails"],
        "data_residency": "geo_required",
        "cris_geography": geography,
    }
    rec = _recommend(
        _workload(source={"model_ids": [source_id]}, requirements=requirements),
        region=region,
    )
    if source_id == "gpt-6-sol":
        # Guardrails are on the Responses API for GPT-6 Sol, so the path stays
        # runtime_openai_responses; no OpenAI model publishes an EU profile, so the
        # engine fails closed instead of fabricating one or switching families silently.
        assert rec["decision_status"] == "decision_required"
        assert "inference_profile_unverified" in _codes(rec["blocks"])
        assert unsupported_id not in {
            option["invocation_model_id"] for option in rec["decision_options"]
        }
    else:
        assert rec["decision_status"] == "recommended"
        assert rec["invocation_model_id"] != unsupported_id
        assert not rec["invocation_model_id"].endswith(
            f"openai.{source_id}"
        )

    conflict = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required", **requirements},
        ),
        region=region,
    )
    assert conflict["decision_status"] == "decision_required"
    assert unsupported_id not in {
        option["invocation_model_id"] for option in conflict["decision_options"]
    }


def test_active_catalog_contains_gpt6_profile_metadata_and_current_provenance():
    assert OPENAI_CATALOG["verified_at"] == "2026-09-24"
    for model_key, _ in _GPT6_MODELS:
        catalog_key = oai._SOURCE_MODEL_KEYS[model_key]
        assert set(OPENAI_CATALOG["models"][catalog_key]["inference_profiles"]) == {
            "us",
            "global",
        }


@pytest.mark.parametrize(("source_id", "target_id"), _GPT6_MODELS)
@pytest.mark.parametrize(("selector", "path"), [
    (None, "runtime_openai_chat"),
    ("server_side_tools", "mantle_openai_chat"),
])
def test_gpt6_chat_completions_preserves_chat_surface(source_id, target_id, selector, path):
    requirements = {"api_continuity": "required"}
    if selector:
        requirements["mantle_selector"] = selector
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements=requirements,
        ),
        region="us-east-1",
    )
    if selector and source_id == "gpt-6.1-sol":
        # GPT-6.1 Sol lists server-side system tools as unsupported on bedrock-mantle
        # (card read 2026-11-08): same-family fallback on the same Chat surface.
        assert rec["primary_model"] == "openai.gpt-6-astra"
        assert rec["mantle_selector"] == selector
    else:
        assert rec["primary_model"] == target_id
    assert rec["api_path"] == path
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])


def test_gpt6_mantle_skips_exact_model_outside_cataloged_region():
    # With a selector, the Mantle walk skips GPT-6 Sol outside its footprint and
    # lands on the same-family model in region (Astra), never on GPT-5.x.
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-6-sol"]},
            requirements={"api_continuity": "required", "mantle_selector": "server_side_tools"},
        ),
        region="us-west-2",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_responses"
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert "exact same model" not in rec["rationale"][0]


# Replaces the PR 1 "deliberate consequence" tests: the candidate walk is now
# same model -> same family (newest first) -> older families (newest first), and
# bedrock-runtime is the default, so a GPT-6 Chat source outside its Mantle
# footprint stays on itself unless a selector puts it on Mantle.
@pytest.mark.parametrize("source_id", ["gpt-6-sol", "gpt-6.1-sol"])
@pytest.mark.parametrize("region", ["us-east-2", "us-west-2"])
def test_gpt6_chat_without_selector_stays_on_itself_via_runtime_chat(source_id, region):
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
        ),
        region=region,
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_chat"
    assert rec["primary_model"] == f"openai.{source_id}"
    assert rec["mantle_selector"] is None
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])


@pytest.mark.parametrize("source_id", ["gpt-6-sol", "gpt-6.1-sol"])
def test_gpt6_chat_with_selector_in_us_west_2_falls_back_to_same_family_astra(source_id):
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required", "mantle_selector": "server_side_tools"},
        ),
        region="us-west-2",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_chat"
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["primary_model"] != "openai.gpt-5.4"
    assert rec["mantle_selector"] == "server_side_tools"
    assert "fallback" in rec["rationale"][0]


@pytest.mark.parametrize("source_id", ["gpt-6-sol", "gpt-6.1-sol"])
def test_gpt6_chat_with_selector_in_us_east_2_prefers_newest_gpt5_over_gpt54(source_id):
    # No GPT-6 model lists Mantle Chat in us-east-2 (Astra: us-east-1/us-west-2),
    # so the walk falls to the GPT-5 family, newest first: GPT-5.6 Sol (its card
    # lists Mantle Chat in us-east-2, read 2026-11-08), never 5.4.
    rec = _recommend(
        _workload(
            source={"model_ids": [source_id], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required", "mantle_selector": "server_side_tools"},
        ),
        region="us-east-2",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "mantle_openai_chat"
    assert rec["primary_model"] != "openai.gpt-5.4"
    assert rec["primary_model"] == "openai.gpt-5.6-sol"
    assert "us-east-2" not in OPENAI_CATALOG["models"]["openai_gpt_6_astra"]["region_availability"]["commercial"]
    assert "fallback" in rec["rationale"][0]


def test_openai_candidate_order_prefers_same_family_then_newer():
    order = oai._openai_candidate_order(OPENAI_CATALOG, {"model_ids": ["gpt-6-sol"]})
    assert order[0] == "openai_gpt_6_sol"
    families = [OPENAI_CATALOG["models"][k]["family"] for k in order]
    assert families == sorted(families, key=lambda f: 0 if f == "openai_gpt_6" else 1)
    assert set(order) == {
        k for k, m in OPENAI_CATALOG["models"].items() if m.get("generation") != "bedrock_native"
    }
    for family in ("openai_gpt_6", "openai_gpt_5"):
        versions = [
            oai._version_tuple(OPENAI_CATALOG["models"][k]["version"])
            for k in order[1:] if OPENAI_CATALOG["models"][k]["family"] == family
        ]
        assert versions == sorted(versions, reverse=True)
    # Sources without a parseable GPT major keep catalog order.
    opaque = oai._openai_candidate_order(OPENAI_CATALOG, {"model_ids": ["o3-mini"]})
    assert opaque == [
        k for k, m in OPENAI_CATALOG["models"].items() if m.get("generation") != "bedrock_native"
    ]


def test_gpt56_sol_responses_in_us_west_2_stays_on_itself_or_falls_to_newest_terra():
    runtime = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-sol"]}, requirements={"api_continuity": "required"}),
        region="us-west-2",
    )
    assert runtime["api_path"] == "runtime_openai_responses"
    assert runtime["primary_model"] == "openai.gpt-5.6-sol"
    # GPT-5.5's cataloged footprint is us-east-1/us-east-2 only, so a Mantle
    # selector in us-west-2 lands on GPT-5.6 Terra (same family, newest in region).
    mantle = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-sol"]},
                  requirements={"mantle_selector": "background_inference"}),
        region="us-west-2",
    )
    assert mantle["decision_status"] == "recommended"
    assert mantle["api_path"] == "mantle_openai_responses"
    assert mantle["primary_model"] == "openai.gpt-5.6-terra"
    assert "us-west-2" not in OPENAI_CATALOG["models"]["openai_gpt_5_5"]["region_availability"]["commercial"]


def test_gpt6_chat_outside_every_mantle_footprint_returns_blocking_decision():
    workload = _workload(
        source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
        requirements={"api_continuity": "required", "mantle_selector": "server_side_tools"},
    )
    out = _full_recommend(workload, region="eu-west-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert rec["primary_model"] is None
    assert "mantle_region_unavailable" in _codes(rec["blocks"])
    assert "eu-west-1" in rec["blocks"][0]["message"]
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "mantle_openai_chat",
        "runtime_converse",
    }
    # Without a selector the same source stays on bedrock-runtime Chat.
    out = _full_recommend(
        _workload(
            source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
            requirements={"api_continuity": "required"},
        ),
        region="eu-west-1",
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_chat"
    assert "mantle_region_unavailable" not in _codes(rec["blocks"])


def test_gpt6_chat_conflict_option_names_chat_completions_surface():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
            requirements={
                "api_continuity": "required",
                "mantle_selector": "server_side_tools",
                "governance": ["guardrails"],
            },
        ),
        region="us-east-1",
    )
    option = next(
        option
        for option in rec["decision_options"]
        if option["api_path"] == "mantle_openai_chat"
    )
    assert "Chat Completions surface" in option["reason"]
    assert "server_side_tools" in option["reason"]
    assert "Responses surface" not in option["reason"]
    assert option["mantle_selector"] == "server_side_tools"


@pytest.mark.parametrize(("selector", "path"), [
    (None, "runtime_openai_chat"),
    ("server_side_tools", "mantle_openai_chat"),
])
def test_gpt6_chat_findings_preserve_chat_request_shapes(selector, path):
    requirements = {"api_continuity": "required", "uses_n": True, "uses_hosted_state": True}
    if selector:
        requirements["mantle_selector"] = selector
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
            requirements=requirements,
            detected_features=["tool_or_function_calling", "conversation_state"],
        ),
        region="us-east-1",
    )
    assert rec["api_path"] == path
    assert "responses_no_n" not in _delta_codes(rec)
    tool_delta = _delta_by_code(rec, "tool_result_shape")
    assert "role: tool" in tool_delta["description"]
    assert "tool_call_id" in tool_delta["description"]
    assert "function_call_output" not in tool_delta["description"]
    state_delta = _delta_by_code(rec, "conversation_state_ownership")
    assert "application-owned message history" in state_delta["description"]
    assert "previous_response_id" not in state_delta["description"]


@pytest.mark.parametrize(("selector", "openai_path", "governance", "other_path"), [
    # multi-model Converse is Converse by definition: continuity vs Converse decision.
    (None, "runtime_openai_chat", {"multi_model_converse": True}, "runtime_converse"),
    # GPT-6 Sol lists Guardrails on Chat Completions (card read 2026-11-08), so the
    # runtime side of the selector-vs-governance decision keeps the Chat API.
    ("server_side_tools", "mantle_openai_chat", {"governance": ["guardrails"]},
     "runtime_openai_chat"),
])
def test_gpt6_chat_conflict_outside_mantle_region_is_schema_valid(
    selector, openai_path, governance, other_path
):
    requirements = {"api_continuity": "required", **governance}
    if selector:
        requirements["mantle_selector"] = selector
    workload = _workload(
        source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
        requirements=requirements,
    )
    out = _full_recommend(workload, region="eu-west-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert {option["api_path"] for option in rec["decision_options"]} == {
        openai_path,
        other_path,
    }
    option = next(
        option for option in rec["decision_options"]
        if option["api_path"] == openai_path
    )
    if selector:
        assert "Requires changing from eu-west-1" in option["reason"]
        assert option["mantle_selector"] == selector
    else:
        assert option["mantle_selector"] is None


def test_gpt6_chat_unknown_required_feature_outside_region_has_two_options():
    workload = _workload(
        source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
        requirements={
            "api_continuity": "required",
            "critical_features": ["streaming"],
        },
        feature_status={"streaming": "unknown"},
    )
    out = _full_recommend(workload, region="eu-west-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert len(rec["decision_options"]) >= 2


@pytest.mark.parametrize(
    "requirements",
    (
        {
            "api_continuity": "preferred",
            "governance": ["guardrails"],
            "critical_features": ["streaming"],
        },
        {
            "api_continuity": "preferred",
            "governance": ["guardrails"],
            "expected_output_tokens": 10000000,
        },
    ),
)
def test_runtime_unresolved_branches_outside_mantle_region_are_schema_valid(
    requirements,
):
    workload = _workload(
        source={"model_ids": ["gpt-6-sol"], "api_surface": "chat_completions"},
        requirements=requirements,
    )
    out = _full_recommend(workload, region="eu-west-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    # Without a selector the OpenAI-API option is bedrock-runtime Chat (no Mantle
    # option, no region change); Converse governance is the other side.
    assert {option["api_path"] for option in rec["decision_options"]} == {
        "runtime_openai_chat",
        "runtime_converse",
    }
    assert all(option["mantle_selector"] is None for option in rec["decision_options"])


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
    # G01: both targets are GPT-5.2+ on a Responses path (gpt-5.1 -> newest GPT-5
    # in catalog, gpt-5.4 -> itself), so BOTH sources get the same target-derived
    # finding.
    early = _recommend(_workload(source={"model_ids": ["gpt-5.1"]}))
    later = _recommend(_workload(source={"model_ids": ["gpt-5.4"]}))
    assert early["primary_model"] == "openai.gpt-5.6-sol"
    assert later["primary_model"] == "openai.gpt-5.4"
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


def test_hosted_web_search_is_reported_as_a_mantle_server_side_tool():
    rec = _recommend(_workload(detected_features=["web_search"]))
    impacts = {a["feature"]: a for a in rec["architecture_impacts"]}
    assert "web_search" in impacts
    assert "bedrock-mantle" in impacts["web_search"]["impact"]
    assert "mantle_selector web_search" in impacts["web_search"]["recommendation"]
    assert "AgentCore Gateway" in impacts["web_search"]["recommendation"]


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
    # GPT-5.6 Sol's output ceiling is still "unknown" (gpt-5.4/5.5 now carry 128000
    # from their cards, so the same-model default would legitimately pass).
    model = OPENAI_CATALOG["models"]["openai_gpt_5_6_sol"]
    assert model["output_token_ceiling"] == "unknown"
    rec = _recommend(_workload(source={"model_ids": ["gpt-5.6-sol"]},
                               requirements={"expected_output_tokens": 100000}))
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
    # A Bedrock-native (Claude) target must not carry target_version gpt-5.x.
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-4"]}, requirements={"governance": ["guardrails"]})
    )
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
    # Neither GPT-5.6 Terra nor any Claude tier has streaming evidence on
    # runtime_converse, so a workload requiring it must NOT get a silent native
    # claim — it fails closed.
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-terra"]},
            requirements={"governance": ["guardrails"], "critical_features": ["streaming"]},
        )
    )
    assert rec["decision_status"] == "decision_required"
    assert "unverified_capability" in _codes(rec["blocks"])


def test_g02_native_only_lists_catalog_evidenced_features():
    # The same model (gpt-5.4) carries the structured-output evidence, so native
    # lists exactly what that catalog entry supports.
    rec = _recommend(
        _workload(detected_features=["tool_or_function_calling", "structured_output_json"])
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert set(rec["compatibility"]["native"]) == {
        "tool_or_function_calling",
        "structured_output_json",
    }


def test_g02_evidence_driven_fallback_skips_unevidenced_newer_models():
    # A gpt-5.1 source has no same-model identity; the walk starts at GPT-5.6 Sol
    # (no structured-output evidence) and falls to GPT-5.5, whose runtime Responses
    # row carries it (card read 2026-11-08), ahead of GPT-5.4.
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.1"]},
                  detected_features=["structured_output_json"])
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.5"
    assert "structured_output_json" in rec["compatibility"]["native"]


def test_g02_vision_requirement_selects_the_evidenced_candidate():
    # image_input_vision is evidenced on the gpt-5.4 card, so the same model is
    # selected with a native claim; terra/luna (no vision evidence) are never
    # claimed native.
    rec = _recommend(
        _workload(
            requirements={"critical_features": ["image_input_vision"]},
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-5.4"
    assert "image_input_vision" in rec["compatibility"]["native"]
    terra = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-terra"]},
                  requirements={"critical_features": ["image_input_vision"]})
    )
    assert terra["primary_model"] != "openai.gpt-5.6-terra"
    assert "image_input_vision" in terra["compatibility"]["native"]


def test_g03_runtime_responses_keeps_typed_responses_parse():
    rec = _recommend(_workload(detected_features=["structured_output_json"]))
    assert rec["api_path"] == "runtime_openai_responses"
    delta = _delta_by_code(rec, "structured_output_text_format")
    assert delta is not None
    assert "responses.parse" in delta["description"]
    assert "bedrock-runtime" in delta["description"]
    assert "no direct" not in delta["description"].lower()


def test_g03_mantle_keeps_typed_responses_parse():
    rec = _recommend(_workload(detected_features=["structured_output_json"],
                               requirements={"mantle_selector": "background_inference"}))
    assert rec["api_path"] == "mantle_openai_responses"
    delta = _delta_by_code(rec, "structured_output_text_format")
    assert "responses.parse" in delta["description"]
    assert "Mantle" in delta["description"]


def test_g04_runtime_state_requires_verification_and_defaults_to_app_owned():
    rec = _recommend(_workload(requirements={"uses_hosted_state": True}))
    assert rec["api_path"] == "runtime_openai_responses"
    delta = _delta_by_code(rec, "conversation_state_ownership")
    assert delta is not None
    assert "store=True" in delta["description"]
    assert "store=False" in delta["description"]
    assert "bedrock-runtime" in delta["description"]


def test_g04_mantle_state_offers_hosted_and_manual_modes():
    rec = _recommend(_workload(requirements={"uses_hosted_state": True,
                                             "mantle_selector": "projects"}))
    assert rec["api_path"] == "mantle_openai_responses"
    delta = _delta_by_code(rec, "conversation_state_ownership")
    assert "store=True" in delta["description"]
    assert "store=False" in delta["description"]
    assert "Mantle" in delta["description"]


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


def _full_recommend(workload, region="us-east-2"):
    data = {
        "schema_version": 2,
        "region": region,
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
            source={"model_ids": ["gpt-4"]},
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
    assert order[1] == "anthropic_claude_opus_5_5"

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

def test_tier_map_terra_and_55_sources_keep_themselves_on_converse():
    # Terra (5.6) and GPT-5.5 are recognized same-model identities with a cataloged
    # runtime_converse path (us./global. CRIS ids), so governance keeps the model.
    rec_terra = _recommend(
        _workload(source={"model_ids": ["gpt-5.6-terra"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec_terra["primary_model"] == "openai.gpt-5.6-terra"
    rec_55 = _recommend(
        _workload(source={"model_ids": ["gpt-5.5"]},
                  requirements={"governance": ["guardrails"]})
    )
    assert rec_55["primary_model"] == "openai.gpt-5.5"
    assert rec_55["api_path"] == "runtime_converse"
    # The Sonnet tier stays the cross-family fallback behind both.
    order = oai._converse_candidate_order({"model_ids": ["gpt-5.5"]})
    assert order[:2] == ["openai_gpt_5_5", "anthropic_claude_sonnet_5"]

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


@pytest.mark.parametrize("surface,path", [
    ("responses", "runtime_openai_responses"),
    ("chat_completions", "runtime_openai_chat"),
])
@pytest.mark.parametrize("region", ["us-east-1", "us-west-2"])
def test_astra_keeps_source_model_and_api_on_runtime(surface, path, region):
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"], "api_surface": surface}),
        region, OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["api_path"] == path
    assert rec["mantle_selector"] is None
    assert rec["source_analysis"]["source_family"] == "reasoning"
    assert rec["source_analysis"]["version_changed"] is False
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])
    assert "sampling_params_accepted" not in _codes(rec["tuning"])
    assert "sampling_params_unverified" in _codes(rec["tuning"])


@pytest.mark.parametrize("surface,path", [
    ("responses", "mantle_openai_responses"),
    ("chat_completions", "mantle_openai_chat"),
])
@pytest.mark.parametrize("region", ["us-east-1", "us-west-2"])
def test_astra_keeps_source_model_and_api_on_mantle_with_selector(surface, path, region):
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"], "api_surface": surface},
                  requirements={"mantle_selector": "server_side_tools"}),
        region, OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["api_path"] == path
    assert rec["mantle_selector"] == "server_side_tools"
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])
    assert "sampling_params_unverified" in _codes(rec["tuning"])


@pytest.mark.parametrize("region", ["us-east-2", "eu-west-1"])
@pytest.mark.parametrize("surface", ["responses", "chat_completions"])
def test_astra_mantle_outside_supported_regions_requires_decision(region, surface):
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"], "api_surface": surface},
                  requirements={"mantle_selector": "server_side_tools"}),
        region, OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "decision_required"
    assert rec["primary_model"] is None
    assert "mantle_region_unavailable" in _codes(rec["blocks"])
    # Without a selector the bedrock-runtime path keeps Astra in those regions.
    runtime = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"], "api_surface": surface}),
        region, OPENAI_CATALOG,
    )
    assert runtime["decision_status"] == "recommended"
    assert runtime["primary_model"] == "openai.gpt-6-astra"
    assert runtime["api_path"].startswith("runtime_openai_")


@pytest.mark.parametrize("surface,preferred,expected,delta", [
    ("chat_completions", "mantle_openai_responses", "mantle_openai_responses",
     "chat_to_responses_request"),
    ("chat_completions", "mantle_openai_chat", "mantle_openai_chat", None),
    ("responses", "mantle_openai_chat", "mantle_openai_chat", "responses_to_chat_request"),
    ("responses", "mantle_openai_responses", "mantle_openai_responses", None),
    ("chat_completions", "runtime_converse", "runtime_converse", "openai_sdk_to_converse"),
    ("responses", "runtime_openai_responses", "runtime_openai_responses", None),
    ("chat_completions", "runtime_openai_chat", "runtime_openai_chat", None),
    ("chat_completions", "runtime_openai_responses", "runtime_openai_responses",
     "chat_to_responses_request"),
    ("responses", "runtime_openai_chat", "runtime_openai_chat", "responses_to_chat_request"),
])
def test_astra_explicit_api_preference_reaches_validated_output(surface, preferred, expected, delta):
    requirements = {"preferred_api_path": preferred, "data_residency": "global_allowed"}
    if preferred.startswith("mantle_"):
        requirements["mantle_selector"] = "server_side_tools"
    data = {
        "schema_version": 2, "region": "us-west-2", "primary_unit": "chat-svc",
        "workloads": [_workload(
            source={"model_ids": ["gpt-6-astra"], "api_surface": surface},
            requirements=requirements,
        )],
    }
    jsonschema.validate(data, json.loads((SCRIPTS / "schemas/model-recommendation-input.json").read_text()))
    result = model_recommendation.recommend(data)
    jsonschema.validate(result, json.loads((SCRIPTS / "schemas/model-recommendation.json").read_text()))
    rec = result["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == expected
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["mantle_selector"] == ("server_side_tools" if expected.startswith("mantle_") else None)
    if expected.startswith("runtime_"):
        assert rec["invocation_model_id"] == "global.openai.gpt-6-astra"
    if delta:
        assert delta in _delta_codes(rec)
    assert not any("GPT-5.x" in block["message"] for block in rec["blocks"])


@pytest.mark.parametrize("preferred,constraints,block", [
    # A selector plus bedrock-runtime-only governance is the root conflict and is
    # reported before the path preference is examined.
    ("mantle_openai_chat", {"governance": ["guardrails"], "mantle_selector": "server_side_tools"},
     "model_path_decision_required"),
    ("mantle_openai_responses", {"governance": ["guardrails"], "mantle_selector": "server_side_tools"},
     "model_path_decision_required"),
    ("mantle_openai_chat", {"governance": ["guardrails"]}, "preferred_api_path_conflict"),
    ("mantle_openai_responses", {}, "preferred_api_path_conflict"),  # no mantle_selector
    ("runtime_converse", {"api_continuity": "required"}, "preferred_api_path_conflict"),
    ("runtime_openai_responses", {"governance": ["guardrails"]}, "preferred_api_path_conflict"),
    ("runtime_invoke", {}, "preferred_api_path_conflict"),
    ("mantle_messages", {}, "preferred_api_path_conflict"),
])
def test_astra_api_preference_conflicts_require_an_explicit_decision(preferred, constraints, block):
    rec = oai.recommend_openai_workload(
        _workload(
            source={"model_ids": ["gpt-6-astra"]},
            requirements={"preferred_api_path": preferred, **constraints},
        ), "us-west-2", OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert block in _codes(rec["blocks"])
    if preferred.startswith("mantle_") and "mantle_selector" not in constraints:
        assert "mantle_selector" in rec["blocks"][0]["message"]


@pytest.mark.parametrize("preferred", ["mantle_openai_responses", "mantle_openai_chat"])
def test_mantle_preference_without_selector_fails_closed_for_every_source(preferred):
    rec = _recommend(_workload(requirements={"preferred_api_path": preferred}))
    assert rec["decision_status"] == "decision_required"
    assert "preferred_api_path_conflict" in _codes(rec["blocks"])
    assert not any(o["api_path"].startswith("mantle_") for o in rec["decision_options"])


# Astra caching evidence (catalog per-path rows): runtime_openai_responses and
# runtime_openai_chat carry prompt_caching; on Mantle only Responses does. The
# invariant: a required cache is checked on the API actually selected.
@pytest.mark.parametrize("region", ["us-east-1", "us-west-2"])
@pytest.mark.parametrize("surface,extra,expected", [
    ("chat_completions", {}, "runtime_openai_chat"),
    ("responses", {}, "runtime_openai_responses"),
    ("chat_completions", {"mantle_selector": "server_side_tools"}, None),
    ("responses", {"mantle_selector": "server_side_tools"}, "mantle_openai_responses"),
    ("responses", {"preferred_api_path": "mantle_openai_chat",
                   "mantle_selector": "server_side_tools"}, None),
    ("chat_completions", {"preferred_api_path": "mantle_openai_responses",
                          "mantle_selector": "server_side_tools"}, "mantle_openai_responses"),
])
def test_astra_required_caching_is_checked_on_the_selected_api(region, surface, extra, expected):
    requirements = {"critical_features": ["prompt_caching"], **extra}
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"], "api_surface": surface},
                  requirements=requirements),
        region, OPENAI_CATALOG,
    )
    assert rec["api_path"] == expected
    if expected is None:
        assert rec["decision_status"] == "decision_required"
        assert "unverified_capability" in _codes(rec["blocks"])
        assert "prompt_caching" in rec["blocks"][0]["message"]
        assert rec["decision_options"][0]["api_path"] == "mantle_openai_responses"
    else:
        assert rec["decision_status"] == "recommended"
        assert "prompt_caching" in rec["compatibility"]["native"]


# --- Required prompt caching is checked on the selected API for EVERY candidate via
# the catalog `prompt_caching_supported` row flag (GPT-5.5 / GPT-5.4 cards: implicit
# caching on the bedrock-runtime Responses API only; read 2026-11-09) -------------

def test_gpt55_chat_with_required_continuity_and_critical_prompt_caching_never_recommends_a_cache_less_row():
    out = _full_recommend(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
                  requirements={"api_continuity": "required",
                                "data_residency": "global_allowed",
                                "critical_features": ["prompt_caching"]}),
        region="us-east-1",
    )
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    # Never a clean GPT-5.5 Chat row with empty buckets.
    assert not (
        rec["decision_status"] == "recommended"
        and rec["primary_model"] == "openai.gpt-5.5"
    )
    if rec["decision_status"] == "recommended":
        assert rec["api_path"] == "runtime_openai_chat"
        assert "prompt_caching" in rec["compatibility"]["native"]
        assert rec["compatibility"]["unsupported"] == []
        row = OPENAI_CATALOG["models"][rec["model_identity"]["model_key"]]["paths"]["runtime_openai_chat"]
        assert row["prompt_caching_supported"] is True
        assert rec["model_identity"]["family"] == "openai_gpt_5"
        # The fallback is explained by the caching scope, not a false "unavailable".
        assert "prompt caching on the Responses API only" in rec["rationale"][0]
        assert "unavailable" not in rec["rationale"][0]
    else:
        assert rec["decision_status"] == "decision_required"
        assert "unverified_capability" in _codes(rec["blocks"])
        assert "prompt_caching" in rec["blocks"][0]["message"]


def test_gpt55_responses_with_critical_prompt_caching_is_recommended_natively():
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "responses"},
                  requirements={"critical_features": ["prompt_caching"]}),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.5"
    assert "prompt_caching" in rec["compatibility"]["native"]
    assert rec["compatibility"]["unsupported"] == []


def test_prompt_caching_decision_names_the_responses_tradeoff_when_no_chat_candidate_has_it():
    catalog = copy.deepcopy(OPENAI_CATALOG)
    catalog["models"] = {
        key: model for key, model in catalog["models"].items()
        if key == "openai_gpt_5_5" or model.get("generation") == "bedrock_native"
    }
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
                  requirements={"api_continuity": "required",
                                "critical_features": ["prompt_caching"]}),
        "us-east-1", catalog,
    )
    assert rec["decision_status"] == "decision_required"
    assert rec["api_path"] is None
    assert "unverified_capability" in _codes(rec["blocks"])
    block = rec["blocks"][0]
    assert "prompt_caching" in block["message"]
    assert "Responses" in block["message"]
    assert "GPT-5.5" in block["message"]
    assert "read 2026-11-09" in block["message"]
    assert "reshape to Responses" in block["message"]
    assert "drop prompt_caching" in block["remediation"]
    assert rec["compatibility"]["native"] == []


def test_gpt55_chat_without_a_caching_requirement_is_still_a_clean_recommendation():
    rec = _recommend(
        _workload(source={"model_ids": ["gpt-5.5"], "api_surface": "chat_completions"},
                  requirements={"api_continuity": "required"}),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_chat"
    assert rec["primary_model"] == "openai.gpt-5.5"
    assert "prompt_caching" not in rec["compatibility"]["native"]
    assert rec["compatibility"]["unsupported"] == []


def test_astra_decision_options_ignore_an_explicitly_absent_cache_signal():
    workload = _workload(
        source={"model_ids": ["gpt-6-astra"], "api_surface": "chat_completions"},
        requirements={"preferred_api_path": "mantle_openai_chat",
                      "mantle_selector": "server_side_tools"},
        detected_features=["prompt_caching"],
        feature_status={"prompt_caching": "absent"},
    )
    options = oai._decision_options(OPENAI_CATALOG, workload, "us-west-2", "server_side_tools")
    assert options[0]["api_path"] == "mantle_openai_chat"
    assert options[0]["mantle_selector"] == "server_side_tools"


@pytest.mark.parametrize("extra,path", [
    ({}, "runtime_openai_chat"),
    ({"mantle_selector": "server_side_tools"}, "mantle_openai_chat"),
])
@pytest.mark.parametrize("signals", [
    {"requirements": {"uses_n": True}},
    {"detected_features": ["multiple_candidates_n"]},
])
def test_astra_chat_n_requires_verification_without_responses_reshape(signals, extra, path):
    workload = _workload(
        source={"model_ids": ["gpt-6-astra"], "api_surface": "chat_completions"}, **signals
    )
    workload["requirements"].update(extra)
    rec = oai.recommend_openai_workload(workload, "us-west-2", OPENAI_CATALOG)
    assert rec["api_path"] == path
    assert "multiple_candidates_n_unverified" in _codes(rec["tuning"])
    assert "responses_no_n" not in _delta_codes(rec)
    assert "chat_completions_to_responses_required" not in _codes(rec["blocks"])


def test_astra_runtime_preserves_model_with_sourced_streaming_and_limits():
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-6-astra"]},
        requirements={
            "governance": ["guardrails"], "critical_features": ["streaming"],
            "data_residency": "global_allowed", "min_context_tokens": 1050000,
            "expected_output_tokens": 128000,
        },
    ))
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "openai.gpt-6-astra"
    assert rec["api_path"] == "runtime_converse"
    assert rec["invocation_model_id"] == "global.openai.gpt-6-astra"
    assert "streaming" in rec["compatibility"]["native"]


@pytest.mark.parametrize("region,geography", [
    ("eu-west-1", "eu"),
    ("eu-west-1", "us"),
    ("ap-south-1", "in"),
])
def test_astra_rejects_unsupported_geo_profile_or_caller_region(region, geography):
    rec = oai.recommend_openai_workload(
        _workload(
            source={"model_ids": ["gpt-6-astra"]},
            requirements={
                "governance": ["guardrails"], "data_residency": "geo_required",
                "cris_geography": geography,
            },
        ), region, OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "decision_required"
    assert "inference_profile_unverified" in _codes(rec["blocks"])


def test_astra_runtime_does_not_inherit_mantle_tools():
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-6-astra"]},
        requirements={"governance": ["guardrails"],
                      "critical_features": ["tool_or_function_calling"]},
    ))
    assert rec["decision_status"] == "decision_required"
    assert rec["primary_model"] is None
    assert "unverified_capability" in _codes(rec["blocks"])


def test_astra_runtime_json_schema_retains_model_and_documented_configuration():
    data = {
        "schema_version": 2, "region": "us-west-2", "primary_unit": "chat-svc",
        "workloads": [_workload(
            source={"model_ids": ["gpt-6-astra"]},
            requirements={"governance": ["guardrails"], "data_residency": "global_allowed",
                          "critical_features": ["structured_output_json"]},
        )],
    }
    jsonschema.validate(data, json.loads((SCRIPTS / "schemas/model-recommendation-input.json").read_text()))
    result = model_recommendation.recommend(data)
    jsonschema.validate(result, json.loads((SCRIPTS / "schemas/model-recommendation.json").read_text()))
    rec = result["workloads"]["chat-svc"]
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_converse"
    assert rec["invocation_model_id"] == "global.openai.gpt-6-astra"
    assert rec["verification"]["availability_claim"] == "provisional"
    assert "structured_output_json" in rec["compatibility"]["native"]
    guidance = next(d["description"] for d in rec["migration_deltas"]
                    if d["code"] == "structured_output_text_format")
    assert "outputConfig.textFormat.structure.jsonSchema" in guidance
    assert "additionalModelRequestFields.text.format.strict=true" in guidance
    assert "JSON string" in guidance and "non-streaming" in guidance


@pytest.mark.parametrize("status,expected", [
    ("detected", "decision_required"), ("absent", "recommended"),
])
def test_astra_json_schema_does_not_claim_streaming_support(status, expected):
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-6-astra"]},
        requirements={"governance": ["guardrails"], "data_residency": "global_allowed",
                      "critical_features": ["structured_output_json"]},
        detected_features=["streaming"], feature_status={"streaming": status},
    ))
    assert rec["decision_status"] == expected
    if expected == "decision_required":
        assert "structured_output_streaming_unverified" in _codes(rec["blocks"])


# The Astra card scopes bedrock-runtime JSON Schema output to non-streaming calls on
# Chat Completions, Responses and Converse alike (model-card-openai-gpt-6-astra.html,
# read 2026-11-08), so the guard covers every runtime API, not only Converse.
@pytest.mark.parametrize("surface,path", [
    ("responses", "runtime_openai_responses"),
    ("chat_completions", "runtime_openai_chat"),
])
@pytest.mark.parametrize("status,expected", [
    ("detected", "decision_required"), ("absent", "recommended"),
])
def test_astra_runtime_openai_apis_apply_the_non_streaming_json_schema_guard(
    surface, path, status, expected
):
    out = _full_recommend(_workload(
        source={"model_ids": ["gpt-6-astra"], "api_surface": surface},
        requirements={"api_continuity": "required", "data_residency": "global_allowed",
                      "critical_features": ["structured_output_json"]},
        detected_features=["streaming"], feature_status={"streaming": status},
    ), region="us-east-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == expected
    if expected == "decision_required":
        block = next(b for b in rec["blocks"] if b["code"] == "structured_output_streaming_unverified")
        assert "non-streaming" in block["message"]
        assert _cites_aws_docs(block["message"])
        assert _option(rec, path)["model"] == "openai.gpt-6-astra"
    else:
        assert rec["api_path"] == path
        assert rec["primary_model"] == "openai.gpt-6-astra"


def test_astra_runtime_responses_structured_output_alone_is_recommended_with_the_text_format_delta():
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-6-astra"]},
        requirements={"api_continuity": "required", "data_residency": "global_allowed",
                      "critical_features": ["structured_output_json"]},
    ), region="us-east-1")
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert "structured_output_json" in rec["compatibility"]["native"]
    assert "structured_output_text_format" in _delta_codes(rec)
    assert "structured_output_streaming_unverified" not in _codes(rec["blocks"])


def test_non_streaming_json_schema_guard_is_keyed_on_astra_not_on_the_source():
    # The guard is Astra-specific. A GPT-6.1 Sol source needing both features has no
    # GPT-6.1 Sol capability evidence for them, so the walk falls to Astra; any block
    # is then about the Astra target, never about GPT-6.1 Sol.
    rec = _recommend(_workload(
        source={"model_ids": ["gpt-6.1-sol"]},
        requirements={"api_continuity": "required", "data_residency": "global_allowed",
                      "critical_features": ["structured_output_json"]},
        detected_features=["streaming"],
    ), region="us-east-1")
    if "structured_output_streaming_unverified" in _codes(rec["blocks"]):
        assert _option(rec, "runtime_openai_responses")["model"] == "openai.gpt-6-astra"
        assert "GPT-6.1" not in rec["blocks"][0]["message"]
    else:
        assert rec["primary_model"] != "openai.gpt-6-astra"


@pytest.mark.parametrize("profile", [
    "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.openai.gpt-6-astra",
    "arn:aws-cn:bedrock:us-west-2:111122223333:inference-profile/us.openai.gpt-6-astra",
    "arn:aws:bedrock:us-west-2:bad-account:inference-profile/us.openai.gpt-6-astra",
    "arn:aws:bedrock:us-west-2:111122223333:application-inference-profile/example",
    "arn:aws:bedrock:us-west-2:111122223333:inference-profile/eu.openai.gpt-6-astra",
    "arn:aws:bedrock:us-west-2:111122223333:inference-profile/us.openai.gpt-5.6-sol",
])
def test_astra_rejects_unverified_profile_arn_or_region(profile):
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"]},
                  requirements={"governance": ["guardrails"], "inference_profile_id": profile}),
        "us-west-2", OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "decision_required"
    assert "inference_profile_unverified" in _codes(rec["blocks"])


@pytest.mark.parametrize("requirement,limit", [
    ("min_context_tokens", 1050001),
    ("expected_output_tokens", 128001),
])
def test_astra_rejects_capacity_above_documented_limit(requirement, limit):
    rec = oai.recommend_openai_workload(
        _workload(source={"model_ids": ["gpt-6-astra"]},
                  requirements={requirement: limit}),
        "us-west-2", OPENAI_CATALOG,
    )
    assert rec["decision_status"] == "decision_required"
    assert "unverified_capacity" in _codes(rec["blocks"])


# --- CRIS profile matrices for GPT-5.6 Sol/Terra/Luna (cards read 2026-11-08) --
#
# Sol publishes us./global. only; Terra and Luna publish us./in./us-gov./global.
# A runtime path must never echo a profile id the card does not publish, and when
# no candidate publishes a callable profile the engine fails closed with a decision.

def _invocation_ids(rec):
    ids = {rec.get("invocation_model_id")}
    ids |= {option["invocation_model_id"] for option in rec.get("decision_options") or []}
    return ids


def test_eu_geo_caller_on_us_only_models_fails_closed_without_fabricated_eu_profile():
    workload = _workload(requirements={"data_residency": "geo_required", "cris_geography": "eu"})
    out = _full_recommend(workload, region="eu-west-1")
    jsonschema.validate(out, _OUT_SCHEMA)
    rec = out["workloads"]["chat-svc"]
    assert rec["decision_status"] == "decision_required"
    assert "inference_profile_unverified" in _codes(rec["blocks"])
    assert not any(
        (invocation_id or "").startswith("eu.openai.") for invocation_id in _invocation_ids(rec)
    )
    options = {option["api_path"]: option for option in rec["decision_options"]}
    assert options["runtime_openai_responses"]["invocation_model_id"] is None
    assert "resolve a profile" in options["runtime_openai_responses"]["reason"]


def test_explicit_eu_profile_for_gpt56_sol_is_never_echoed():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-sol"]},
            requirements={"inference_profile_id": "eu.openai.gpt-5.6-sol",
                          "api_continuity": "required"},
        ),
        region="eu-west-1",
    )
    assert rec["invocation_model_id"] is None
    if rec["decision_status"] == "recommended":
        assert _codes(rec["blocks"]) & {"cris_residency_unresolved", "inference_profile_unverified"}
    assert "eu.openai.gpt-5.6-sol" not in _invocation_ids(rec)


def test_gpt56_terra_accepts_the_india_geo_profile_from_ap_south_1():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-terra"]},
            requirements={"data_residency": "geo_required",
                          "inference_profile_id": "in.openai.gpt-5.6-terra"},
        ),
        region="ap-south-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.6-terra"
    assert rec["invocation_model_id"] == "in.openai.gpt-5.6-terra"
    assert "cris_residency_unresolved" not in _codes(rec["blocks"])


def test_gpt56_luna_accepts_the_govcloud_profile_from_us_gov_west_1():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-luna"]},
            requirements={"inference_profile_id": "us-gov.openai.gpt-5.6-luna"},
        ),
        region="us-gov-west-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["invocation_model_id"] == "us-gov.openai.gpt-5.6-luna"


def test_gpt56_luna_in_govcloud_has_no_global_profile():
    # The Luna card lists no Global profile for GovCloud callers (read 2026-11-08).
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-luna"]},
            requirements={"data_residency": "global_allowed"},
        ),
        region="us-gov-west-1",
    )
    assert rec["invocation_model_id"] is None
    assert _codes(rec["blocks"]) & {"cris_residency_unresolved", "inference_profile_unverified"}
    assert "global.openai.gpt-5.6-luna" not in _invocation_ids(rec)


def test_gpt56_sol_global_profile_from_us_east_1_lists_both_us_and_global():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.6-sol"]},
            requirements={"data_residency": "global_allowed"},
        ),
        region="us-east-1",
    )
    assert rec["decision_status"] == "recommended"
    assert rec["invocation_model_id"] == "global.openai.gpt-5.6-sol"
    allowed = set(rec["verification"]["allowed_inference_profiles"])
    assert {"us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-sol"} <= allowed


# --- GPT-5.4 / GPT-5.5 per-API capabilities (cards read 2026-11-08) ------------
#
# Both cards list 'Structured outputs (JSON Schema; Responses API)': the feature is
# evidenced on runtime Responses only, never on Chat Completions or Converse.

def test_gpt55_structured_output_stays_on_gpt55_runtime_responses():
    rec = _recommend(
        _workload(
            source={"model_ids": ["gpt-5.5"]},
            requirements={"critical_features": ["structured_output_json"],
                          "data_residency": "global_allowed"},
        )
    )
    assert rec["decision_status"] == "recommended"
    assert rec["api_path"] == "runtime_openai_responses"
    assert rec["primary_model"] == "openai.gpt-5.5"
    assert "structured_output_json" in rec["compatibility"]["native"]


@pytest.mark.parametrize("path,unmet", [
    ("runtime_openai_chat", ["structured_output_json"]),
    ("runtime_converse", ["structured_output_json"]),
    ("runtime_openai_responses", []),
])
def test_gpt54_structured_output_is_evidenced_only_on_runtime_responses(path, unmet):
    _hit, missing = oai._catalog_model_for_path(
        OPENAI_CATALOG, path, ["structured_output_json"], {},
        candidate_order=["openai_gpt_5_4"],
    )
    assert missing == unmet


def test_gpt54_guardrails_plus_structured_output_has_no_evidenced_converse_candidate():
    rec = _recommend(
        _workload(
            requirements={"governance": ["guardrails"],
                          "critical_features": ["structured_output_json"],
                          "data_residency": "global_allowed"},
        )
    )
    assert rec["decision_status"] == "decision_required"
    assert "unverified_capability" in _codes(rec["blocks"])
    assert "structured_output_json" not in rec["compatibility"]["native"]


def test_gpt54_chat_source_with_structured_output_does_not_claim_it_on_gpt54_chat():
    rec = _recommend(
        _workload(
            source={"api_surface": "chat_completions"},
            requirements={"critical_features": ["structured_output_json"]},
        ),
        region="us-east-2",
    )
    assert rec["primary_model"] != "openai.gpt-5.4"
    if rec["decision_status"] == "recommended":
        row = OPENAI_CATALOG["models"][rec["model_identity"]["model_key"]]["paths"]["runtime_openai_chat"]
        assert "structured_output_json" in row["capabilities"]
