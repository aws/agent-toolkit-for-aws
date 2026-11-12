"""Stage 2 of #566: Claude Sonnet 5.5 as the balanced default and GPT-6.1 Terra recognition."""

import copy

import pytest

import model_recommendation as mr


def _workload(provider, model, surface, region="us-east-1", detected=(), **requirements):
    return {
        "schema_version": 2, "region": region, "primary_unit": "w",
        "workloads": [{
            "workload_id": "w",
            "source": {"provider": provider, "model_ids": [model], "sdk": provider,
                       "api_surface": surface, "source_paths": ["src/app.py"]},
            "requirements": {"data_residency": "global_allowed", **requirements},
            "detected_features": list(detected),
        }],
    }


def _rec(*args, **kwargs):
    return mr.recommend(_workload(*args, **kwargs))["workloads"]["w"]


def _claude(priority, **requirements):
    return _rec("anthropic", "claude-3-7-sonnet-latest", "messages", priority=priority,
                governance=["guardrails"], **requirements)


@pytest.mark.parametrize(("priority", "expected"), [
    ("balanced", "anthropic.claude-sonnet-5-5"),
    ("unknown", "anthropic.claude-sonnet-5-5"),
    ("quality", "anthropic.claude-opus-5-5"),
    ("speed", "anthropic.claude-haiku-5-5"),
    ("cost", "anthropic.claude-haiku-5-5"),
])
def test_priority_defaults(priority, expected):
    assert _claude(priority)["primary_model"] == expected


def test_sonnet_5_stays_selectable_directly_after_sonnet_5_5():
    rec = _claude("balanced")
    assert rec["alternatives"][0]["model"] == "anthropic.claude-sonnet-5"


def test_batch_workload_yields_to_sonnet_5():
    rec = _rec("anthropic", "claude-3-7-sonnet-latest", "messages", detected=["message_batches"],
               priority="balanced", governance=["guardrails"])
    assert (rec["primary_model"], rec["api_path"]) == ("anthropic.claude-sonnet-5", "runtime_converse")
    assert any("does not support Message Batches" in line for line in rec["rationale"])


def test_disabled_thinking_yields_to_sonnet_5():
    rec = _claude("balanced", thinking_enabled=False)
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert "adaptive_thinking_required" not in {b["code"] for b in rec["blocks"] + rec["tuning"]}
    assert any("does not support disabled thinking" in line for line in rec["rationale"])


def _without_sonnet_5():
    catalog = copy.deepcopy(mr.load_catalog())
    catalog["models"]["claude_sonnet_5"]["selection_status"] = "reference_only"
    return catalog


def test_findings_name_sonnet_5_when_it_cannot_be_selected():
    # With Sonnet 5 unavailable for selection, Sonnet 5.5 is chosen and the findings name the
    # alternative instead of silently weakening the requirement.
    data = _workload("anthropic", "claude-3-7-sonnet-latest", "messages", detected=["message_batches"],
                     priority="balanced", governance=["guardrails"], thinking_enabled=False)
    rec = mr.recommend(data, catalog=_without_sonnet_5())["workloads"]["w"]
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"
    batch = next(b for b in rec["blocks"] if b["code"] == "message_batches_not_portable")
    assert "Sonnet 5.5 does not support Bedrock Batch" in batch["remediation"]
    assert "Claude Sonnet 5" in batch["remediation"]
    thinking = next(b for b in rec["blocks"] if b["code"] == "adaptive_thinking_required")
    assert thinking["message"].startswith("Sonnet 5.5 always uses adaptive thinking")
    assert "default high" in thinking["remediation"]
    assert "explicitly select Claude Sonnet 5" in thinking["remediation"]


def test_opus_findings_keep_their_wording():
    rec = _claude("quality", thinking_enabled=False)
    finding = next(b for b in rec["blocks"] if b["code"] == "adaptive_thinking_required")
    assert finding["message"].startswith("Opus 5.5 always uses adaptive thinking")
    assert "default medium" in finding["remediation"]
    assert "select a verified compatible target" in finding["remediation"]


def test_commercial_messages_continuity_keeps_sonnet_5_on_mantle():
    # Sonnet 5.5's Mantle Messages path is GovCloud-only.
    rec = _rec("anthropic", "claude-3-7-sonnet-latest", "messages", priority="balanced",
               preserve_messages_api=True)
    assert (rec["primary_model"], rec["api_path"]) == ("anthropic.claude-sonnet-5", "mantle_messages")


def test_gpt_6_1_terra_source_lands_on_the_same_model_on_mantle():
    rec = _rec("openai", "gpt-6.1-terra", "responses", priority="balanced")
    assert rec["primary_model"] == "openai.gpt-6.1-terra"
    assert rec["api_path"] == "mantle_openai_responses"


@pytest.mark.parametrize(("region", "expected_id"), [
    ("us-east-1", "global.openai.gpt-6.1-terra"),
    ("eu-west-1", "global.openai.gpt-6.1-terra"),
])
def test_gpt_6_1_terra_governance_keeps_the_same_model_on_converse(region, expected_id):
    rec = _rec("openai", "gpt-6.1-terra", "responses", region=region, priority="balanced",
               governance=["guardrails"])
    assert (rec["primary_model"], rec["api_path"]) == ("openai.gpt-6.1-terra", "runtime_converse")
    assert rec["invocation_model_id"] == expected_id


def test_gpt_5_6_terra_governance_maps_to_sonnet_5_5_on_converse():
    rec = _rec("openai", "gpt-4o", "chat_completions", priority="balanced", governance=["guardrails"],
               preserve_openai_api=False)
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"
    assert rec["invocation_model_id"] == "global.anthropic.claude-sonnet-5-5"


@pytest.mark.parametrize("region", ["us-west-2", "us-east-2", "us-gov-west-1"])
def test_gpt_6_1_terra_is_not_selected_on_mantle_outside_us_east_1(region):
    rec = _rec("openai", "gpt-6.1-terra", "responses", region=region, priority="balanced")
    assert not (rec["primary_model"] == "openai.gpt-6.1-terra" and str(rec["api_path"]).startswith("mantle_"))


def test_gpt_6_1_terra_has_no_global_profile_in_me_south_1():
    rec = _rec("openai", "gpt-6.1-terra", "responses", region="me-south-1", priority="balanced",
               governance=["guardrails"])
    assert rec["invocation_model_id"] != "global.openai.gpt-6.1-terra"


@pytest.mark.parametrize("region", ["us-gov-west-1", "us-gov-east-1"])
def test_sonnet_5_5_is_not_given_a_global_profile_in_govcloud(region):
    rec = _rec("anthropic", "claude-3-7-sonnet-latest", "messages",
                                                  region=region, priority="balanced", governance=["guardrails"])
    assert rec["invocation_model_id"] != "global.anthropic.claude-sonnet-5-5"
    assert rec["primary_model"] != "anthropic.claude-sonnet-5-5" or rec["api_path"] == "mantle_messages"


@pytest.mark.parametrize(("residency", "expected"), [
    ("global_allowed", "global.anthropic.claude-sonnet-5-5"),
    ("geo_required", "eu.anthropic.claude-sonnet-5-5"),
])
def test_sonnet_5_5_profile_follows_residency_in_the_eu(residency, expected):
    rec = _rec("anthropic", "claude-3-7-sonnet-latest", "messages", region="eu-west-1", priority="balanced",
               governance=["guardrails"], data_residency=residency, cris_geography="eu")
    assert rec["invocation_model_id"] == expected


# --- review on #607 ---------------------------------------------------------------------------

def _with_feature_status(data, status):
    data["workloads"][0]["feature_status"] = status
    return data


@pytest.mark.parametrize(("detected", "status"), [
    pytest.param(["message_batches"], None, id="array"),
    pytest.param([], {"message_batches": "detected"}, id="feature_status"),
    pytest.param(["message_batches"], {"message_batches": "detected"}, id="both"),
])
def test_batch_yield_reads_every_feature_encoding(detected, status):
    data = _workload("anthropic", "claude-3-7-sonnet-latest", "messages", detected=detected,
                     priority="balanced", governance=["guardrails"])
    if status:
        _with_feature_status(data, status)
    assert mr.recommend(data)["workloads"]["w"]["primary_model"] == "anthropic.claude-sonnet-5"


def test_batch_feature_marked_absent_does_not_yield():
    data = _workload("anthropic", "claude-3-7-sonnet-latest", "messages", priority="balanced",
                     governance=["guardrails"])
    _with_feature_status(data, {"message_batches": "absent"})
    assert mr.recommend(data)["workloads"]["w"]["primary_model"] == "anthropic.claude-sonnet-5-5"


def _gpt4o(**requirements):
    return _rec("openai", "gpt-4o", "chat_completions", priority="balanced", governance=["guardrails"],
                preserve_openai_api=False, **requirements)


def test_openai_converse_default_yields_to_sonnet_5_when_thinking_is_disabled():
    rec = _gpt4o(thinking_enabled=False)
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert "adaptive_thinking_required" not in {b["code"] for b in rec["blocks"] + rec["tuning"]}


def test_openai_converse_keeps_an_explicitly_pinned_sonnet_5_5():
    rec = _gpt4o(thinking_enabled=False, inference_profile_id="global.anthropic.claude-sonnet-5-5")
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"


def test_openai_converse_quality_tier_is_unchanged_by_the_yield():
    rec = _rec("openai", "gpt-4o", "chat_completions", priority="quality", governance=["guardrails"],
               preserve_openai_api=False, thinking_enabled=False)
    assert rec["primary_model"] == "anthropic.claude-opus-5-5"


def test_openai_decision_options_use_the_yielded_converse_model():
    rec = _rec("openai", "gpt-6-sol", "responses", priority="balanced", governance=["guardrails"],
               preserve_openai_api=True, thinking_enabled=False)
    runtime = [o["model"] for o in rec["decision_options"] if o["api_path"] == "runtime_converse"]
    assert "anthropic.claude-sonnet-5-5" not in runtime


@pytest.mark.parametrize("feature", ["streaming", "structured_output_json"])
def test_gpt_6_1_terra_serves_documented_runtime_capabilities(feature):
    rec = _rec("openai", "gpt-6.1-terra", "responses", priority="balanced", governance=["guardrails"],
               critical_features=[feature])
    assert rec["decision_status"] == "recommended"
    assert (rec["primary_model"], rec["api_path"]) == ("openai.gpt-6.1-terra", "runtime_converse")


def test_gpt_6_1_terra_structured_output_carries_the_converse_request_shape():
    rec = _rec("openai", "gpt-6.1-terra", "responses", priority="balanced", governance=["guardrails"],
               critical_features=["structured_output_json"])
    delta = next(d for d in rec["migration_deltas"] if d["code"] == "structured_output_text_format")
    assert delta["description"].startswith("GPT-6.1 Terra runtime JSON Schema output is documented for non-streaming calls")
    assert "additionalModelRequestFields.text.format.strict=true" in delta["description"]


def test_gpt_6_1_terra_keeps_the_non_streaming_json_schema_restriction():
    rec = _rec("openai", "gpt-6.1-terra", "responses", priority="balanced", governance=["guardrails"],
               critical_features=["structured_output_json", "streaming"])
    assert rec["primary_model"] is None
    assert "structured_output_streaming_unverified" in {b["code"] for b in rec["blocks"]}


@pytest.mark.parametrize("feature", ["streaming", "structured_output_json"])
def test_sonnet_5_5_converse_target_serves_documented_capabilities(feature):
    rec = _gpt4o(critical_features=[feature])
    assert rec["decision_status"] == "recommended"
    assert rec["primary_model"] == "anthropic.claude-sonnet-5-5"


# --- follow-up review on #607: conflict options apply the same yield as the rerun --------------

def _conflict(detected=(), status=None, **requirements):
    data = _workload("anthropic", "claude-3-7-sonnet-latest", "messages", detected=detected,
                     priority="balanced", governance=["guardrails"], **requirements)
    if status:
        _with_feature_status(data, status)
    return data


def _option_and_rerun(data, path="runtime_converse"):
    conflicted = copy.deepcopy(data)
    conflicted["workloads"][0]["requirements"]["preserve_messages_api"] = True
    options = mr.recommend(conflicted)["workloads"]["w"]["decision_options"]
    option = next(o for o in options if o["api_path"] == path)
    rerun = mr.recommend(data)["workloads"]["w"]
    assert rerun["api_path"] == path
    return option["model"], rerun["primary_model"]


@pytest.mark.parametrize("kwargs", [
    pytest.param({"thinking_enabled": False}, id="thinking_disabled"),
    pytest.param({"detected": ["message_batches"]}, id="batch_array"),
    pytest.param({"status": {"message_batches": "detected"}}, id="batch_feature_status"),
])
def test_runtime_option_offers_the_model_the_rerun_selects(kwargs):
    assert _option_and_rerun(_conflict(**kwargs)) == ("anthropic.claude-sonnet-5",) * 2


def test_runtime_option_keeps_sonnet_5_5_without_an_unmet_need():
    assert _option_and_rerun(_conflict()) == ("anthropic.claude-sonnet-5-5",) * 2


def test_runtime_option_keeps_an_explicitly_pinned_sonnet_5_5():
    data = _conflict(thinking_enabled=False, inference_profile_id="global.anthropic.claude-sonnet-5-5")
    assert _option_and_rerun(data) == ("anthropic.claude-sonnet-5-5",) * 2


def test_runtime_option_quality_tier_is_unchanged_by_the_yield():
    data = _workload("anthropic", "claude-3-7-sonnet-latest", "messages", priority="quality",
                     governance=["guardrails"], thinking_enabled=False)
    assert _option_and_rerun(data) == ("anthropic.claude-opus-5-5",) * 2


def _mantle_pinned(pin, priority="quality"):
    return _rec("anthropic", "claude-opus-4-8", "messages", priority=priority,
                preferred_api_path="mantle_messages", inference_profile_id=pin)


def test_sonnet_5_5_pin_does_not_select_sonnet_5_by_id_prefix():
    # Sonnet 5.5 is not on Mantle; its pin must not name Sonnet 5 and override the ranked choice.
    rec = _mantle_pinned("global.anthropic.claude-sonnet-5-5")
    assert (rec["api_path"], rec["primary_model"]) == ("mantle_messages", "anthropic.claude-opus-5-5")


@pytest.mark.parametrize("pin", [
    "global.anthropic.claude-sonnet-5",
    "arn:aws:bedrock:us-east-1:111122223333:inference-profile/global.anthropic.claude-sonnet-5",
    "anthropic.claude-sonnet-5",
])
def test_a_pin_naming_sonnet_5_still_selects_it(pin):
    assert _mantle_pinned(pin)["primary_model"] == "anthropic.claude-sonnet-5"


@pytest.mark.parametrize("pin", [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
])
def test_a_versioned_haiku_4_5_pin_still_selects_it_on_the_runtime(pin):
    rec = _rec("anthropic", "claude-opus-4-8", "messages", priority="quality", governance=["guardrails"],
               preferred_api_path="runtime_converse", inference_profile_id=pin)
    assert (rec["primary_model"], rec["invocation_model_id"]) == ("anthropic.claude-haiku-4-5-20251001-v1:0", pin)


def test_mantle_option_honors_a_pin_the_rerun_honors():
    data = _workload("anthropic", "claude-opus-4-8", "messages", priority="quality",
                     governance=["guardrails"], inference_profile_id="anthropic.claude-sonnet-5")
    conflicted = copy.deepcopy(data)
    conflicted["workloads"][0]["requirements"]["preserve_messages_api"] = True
    options = mr.recommend(conflicted)["workloads"]["w"]["decision_options"]
    option = next(o for o in options if o["api_path"] == "mantle_messages")
    data["workloads"][0]["requirements"].pop("governance")
    data["workloads"][0]["requirements"]["preferred_api_path"] = "mantle_messages"
    rerun = mr.recommend(data)["workloads"]["w"]
    assert option["model"] == rerun["primary_model"] == "anthropic.claude-sonnet-5"
