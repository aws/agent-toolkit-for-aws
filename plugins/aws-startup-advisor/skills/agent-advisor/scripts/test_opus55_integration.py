"""Opus 5.5 selection, profile, pricing, and estimate-contract regressions."""

import importlib.util
import shutil
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

import pytest

import model_recommendation as mr
import openai_model_recommendation as oai


SKILLS = Path(mr.__file__).resolve().parents[2]
MODEL = "anthropic.claude-opus-5-5"


def _recommend(region="us-east-1", provider="anthropic", source_model="claude-opus-4-8",
               detected_features=(), **requirements):
    workload = {
        "workload_id": "reasoning",
        "source": {
            "provider": provider,
            "model_ids": [source_model],
            "sdk": "anthropic" if provider == "anthropic" else "openai",
            "api_surface": "messages" if provider == "anthropic" else "responses",
            "source_paths": ["src/app.py"],
        },
        "requirements": {
            "priority": "quality",
            "preferred_api_path": "runtime_converse",
            "data_residency": "global_allowed",
            **requirements,
        },
        "detected_features": list(detected_features),
    }
    return mr.recommend({
        "schema_version": 2, "region": region, "primary_unit": "reasoning", "workloads": [workload],
    })["workloads"]["reasoning"]


def _script(name):
    path = SKILLS / "llm-to-bedrock" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"opus55_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", ["runtime_converse", "runtime_invoke", "mantle_messages"])
def test_quality_and_thinking_select_opus55_on_each_supported_path(path):
    rec = _recommend(preferred_api_path=path, thinking_enabled=True, min_context_tokens=1000000)
    assert rec["primary_model"] == MODEL
    assert rec["model_identity"]["output_token_ceiling"] == 128000
    assert rec["invocation_model_id"] == (MODEL if path == "mantle_messages" else "global." + MODEL)
    assert rec["verification"]["probe_status"] == "not_run"


@pytest.mark.parametrize("region,prefix", [
    ("us-east-1", "us"), ("eu-west-1", "eu"), ("ap-southeast-2", "au"),
    ("ap-northeast-1", "jp"), ("us-gov-west-1", "us"),
])
def test_geo_ids_match_supported_source_regions(region, prefix):
    rec = _recommend(region, data_residency="geo_required", cris_geography=prefix)
    assert rec["primary_model"] == MODEL
    assert rec["invocation_model_id"] == prefix + "." + MODEL


@pytest.mark.parametrize("region,requirements", [
    ("us-gov-west-1", {}),
    ("us-east-1", {"data_residency": "geo_required", "cris_geography": "eu"}),
    ("ap-southeast-1", {"data_residency": "geo_required", "cris_geography": "au"}),
    ("us-east-1", {"inference_profile_id": "us.anthropic.claude-opus-4-8"}),
    ("us-east-1", {"data_residency": "geo_required", "cris_geography": "us",
                   "inference_profile_id": "global." + MODEL}),
])
def test_invalid_or_forbidden_profiles_remain_blocked(region, requirements):
    rec = _recommend(region, **requirements)
    assert rec["primary_model"] == MODEL
    assert rec["invocation_model_id"] is None
    assert "inference_profile_unresolved" in {item["code"] for item in rec["blocks"]}


def test_mantle_unavailable_region_does_not_restore_opus48():
    rec = _recommend("eu-west-1", preferred_api_path="mantle_messages")
    assert rec["primary_model"] == "anthropic.claude-sonnet-5"
    assert all("opus-4-8" not in item["model"] for item in rec["alternatives"])


def test_explicit_disabled_thinking_cannot_silently_be_preserved():
    rec = _recommend(thinking_enabled=False)
    assert "adaptive_thinking_required" in {item["code"] for item in rec["blocks"]}


def test_opus5_to_opus55_keeps_the_version_migration_scan():
    rec = _recommend(source_model="claude-opus-5")
    assert rec["source_analysis"]["detected_version"] == "5.0"
    assert rec["source_analysis"]["target_version"] == "5.5"
    assert "version_scan_incomplete" in {item["code"] for item in rec["blocks"]}


def test_batch_migration_does_not_suggest_an_unsupported_opus55_batch_job():
    rec = _recommend(detected_features=["message_batches"])
    finding = next(item for item in rec["blocks"] if item["code"] == "message_batches_not_portable")
    assert "does not support Bedrock Batch" in finding["remediation"]
    assert "Opus 4.6" in finding["remediation"]
    impact = next(item for item in rec["architecture_impacts"] if item["feature"] == "message_batches")
    assert impact["recommendation"] == finding["remediation"]
    assert "CreateModelInvocationJob" not in impact["recommendation"]


def test_old_catalog_does_not_restore_opus48_to_the_current_pool():
    catalog = mr.load_catalog(mr.MODELS_DIR / "anthropic-bedrock-2026-07-21.json")
    workload = {
        "workload_id": "old",
        "source": {"provider": "none"},
        "requirements": {"priority": "quality"},
    }
    rec = mr.recommend({"region": "us-east-1", "primary_unit": "old", "workloads": [workload]}, catalog)
    assert rec["workloads"]["old"]["primary_model"] == "anthropic.claude-sonnet-5"


def test_openai_quality_cross_family_path_uses_the_same_opus55_contract():
    rec = _recommend(provider="openai", source_model="gpt-4", preserve_openai_api=False,
                     governance=["guardrails"])
    assert rec["primary_model"] == MODEL
    assert rec["invocation_model_id"] == "global." + MODEL


def test_openai_sampling_remediation_uses_selected_target_constraints():
    rec = _recommend(provider="openai", source_model="gpt-4", preserve_openai_api=False,
                     governance=["guardrails"], detected_features=["sampling_params"])
    assert rec["primary_model"] == MODEL
    finding = next(item for item in rec["blocks"] if item["code"] == "sampling_parameters_removed")
    assert "parameter_removed confirmation" in finding["remediation"]
    assert "do not rescale" in finding["remediation"]
    assert "sampling_via_converse" not in {item["code"] for item in rec["tuning"]}
    model = mr.load_openai_catalog()["models"]["anthropic_claude_sonnet_5"]
    blocks, tuning, _ = oai._reasoning_findings(
        {"model_ids": ["gpt-4"]}, {}, model, "runtime_converse", ["sampling_params"]
    )
    assert "sampling_parameters_removed" not in {item["code"] for item in blocks}
    assert "sampling_via_converse" in {item["code"] for item in tuning}


def test_available_openai_same_model_still_outranks_cross_family_quality():
    rec = _recommend(provider="openai", source_model="gpt-5.6-sol", preserve_openai_api=False,
                     governance=["guardrails"])
    assert rec["primary_model"] == "openai.gpt-5.6-sol"


def test_openai_quality_does_not_restore_opus48_when_opus55_is_unavailable():
    catalog = mr.load_openai_catalog()
    catalog["models"]["anthropic_claude_opus_5_5"]["paths"]["runtime_converse"]["available"] = False
    source = {"model_ids": ["gpt-4"]}
    requirements = {"priority": "quality"}
    chosen, unmet = oai._catalog_model_for_path(
        catalog, "runtime_converse", [], requirements,
        candidate_order=oai._converse_candidate_order(source, requirements),
    )
    assert chosen[0] == "anthropic_claude_sonnet_5"
    assert not unmet


def test_current_catalogs_have_no_opus48_migration_target():
    assert "claude_opus_4_8" not in mr.load_catalog()["models"]
    assert "anthropic_claude_opus_4_8" not in mr.load_openai_catalog()["models"]
    assert "anthropic_claude_opus_4_8" not in oai._CONVERSE_TIER_ORDER


@pytest.mark.parametrize("path", ["runtime_converse", "runtime_invoke", "mantle_messages"])
@pytest.mark.parametrize("feature", ["structured_output", "assistant_prefill"])
def test_opus55_structured_remedies_never_prescribe_forced_tool_choice(path, feature):
    rec = _recommend(preferred_api_path=path, detected_features=[feature])
    assert rec["primary_model"] == MODEL
    code = "assistant_prefill_removed" if feature == "assistant_prefill" else "structured_output_portable_pattern"
    remedy = next(item["remediation"] for item in rec["blocks"] if item["code"] == code)
    delta = next(item["description"] for item in rec["migration_deltas"] if item["code"] == "structured_output")
    assert remedy == delta
    assert "automatic tool choice" in remedy
    assert "application schema validation and bounded retries" in remedy
    assert "no native schema guarantee" in remedy
    assert "Use a forced tool" not in remedy


def test_required_structured_output_is_checked_without_a_detected_source_feature():
    rec = _recommend(critical_features=["structured_output"])
    assert "structured_output_portable_pattern" in {item["code"] for item in rec["blocks"]}


@pytest.mark.parametrize("cloud", ["gcp-to-aws", "azure-to-aws"])
def test_price_cache_preserves_existing_deployment_rates_without_recommending_opus48(cloud):
    text = (SKILLS / cloud / "references/shared/pricing-cache.md").read_text()
    assert "Opus 4.8" in text
    assert "rates are retained for existing deployments only" in text
    assert "or automatic fallback" in text
    assert _script("bedrock_pricing").lookup("us-east-1", "anthropic.claude-opus-4-8")["available"]


@pytest.mark.parametrize("priority", ["quality", "balanced", "speed", "cost", "unknown"])
@pytest.mark.parametrize("path", ["runtime_converse", "runtime_invoke", "mantle_messages"])
def test_automatic_primary_and_alternatives_never_select_opus48(priority, path):
    rec = _recommend(priority=priority, preferred_api_path=path)
    targets = [rec["primary_model"], *(item["model"] for item in rec["alternatives"])]
    assert all("opus-4-8" not in target for target in targets)


@pytest.mark.parametrize("region,prefix,expected", [
    ("us-east-1", "global.", (0.004, 0.020)),
    ("us-east-1", "us.", (0.0044, 0.022)),
    ("eu-west-1", "eu.", (0.0044, 0.022)),
    ("ap-southeast-2", "au.", (0.0044, 0.022)),
    ("ap-northeast-1", "jp.", (0.0044, 0.022)),
    ("us-east-1", "", (0.0044, 0.022)),
    ("us-gov-west-1", "us.", (0.0048, 0.024)),
    ("us-gov-west-1", "", (0.0048, 0.024)),
])
def test_pricing_uses_the_region_and_profile_not_just_model_name(region, prefix, expected):
    result = _script("bedrock_pricing").lookup(region, prefix + MODEL)
    assert result["available"]
    assert (result["input_per_1k_usd"], result["output_per_1k_usd"]) == expected
    assert "2026-09-24" in result["note"]


@pytest.mark.parametrize("region,model", [
    ("us-gov-west-1", "global." + MODEL),
    ("eu-west-1", MODEL),
    ("us-east-1", "jp." + MODEL),
    ("us-east-1", "anthropic.claude-opus-5"),
    ("us-east-1", MODEL + "0"),
    ("us-east-1", MODEL + "-20260922-v1:0"),
    ("cn-north-1", "global." + MODEL),
])
def test_unknown_or_mismatched_price_dimensions_fail_closed_without_network(region, model):
    result = _script("bedrock_pricing").lookup(region, model)
    assert result["available"] is False
    assert result["input_per_1k_usd"] is None


@pytest.mark.parametrize("region,prefix", [("ap-southeast-2", "au"), ("ap-northeast-1", "jp")])
def test_iam_covers_both_profile_and_foundation_model(region, prefix):
    policy = _script("iam_policy").generate_policy([prefix + "." + MODEL], region, "123456789012")
    resources = policy["Statement"][0]["Resource"]
    assert f"arn:aws:bedrock:*::foundation-model/{MODEL}" in resources
    assert f"arn:aws:bedrock:{region}:123456789012:inference-profile/{prefix}.{MODEL}" in resources


def test_govcloud_iam_uses_the_govcloud_partition():
    policy = _script("iam_policy").generate_policy(["us." + MODEL], "us-gov-west-1", "123456789012")
    assert all(arn.startswith("arn:aws-us-gov:") for arn in policy["Statement"][0]["Resource"])


def test_bare_opus55_is_mantle_for_iam_but_not_a_runtime_probe():
    policy = _script("iam_policy").generate_policy([MODEL], "us-east-1", "123456789012")
    assert policy["Statement"][0]["Sid"] == "BedrockMantleInference"
    result = _script("preflight_bedrock").probe_model(None, MODEL)
    assert result["ok"] is False
    assert result["reason"] == "inference_profile_required"


def test_each_anthropic_pool_model_has_a_numeric_cache_row_in_both_clouds():
    for cloud in ("gcp-to-aws", "azure-to-aws"):
        text = (SKILLS / cloud / "references/shared/pricing-cache.md").read_text()
        rows = [line.split("|")[1:-1] for line in text.splitlines() if line.startswith("|")]
        for model in mr.load_catalog()["models"].values():
            model_id = model["paths"]["runtime_converse"]["model_id"]
            matching = [row for row in rows if len(row) >= 8 and
                        row[1].strip().removeprefix("global.").removeprefix("us.") == model_id]
            assert matching, (cloud, model_id)
            assert all(float(row[3].strip()) > 0 and float(row[4].strip()) > 0 for row in matching)


@pytest.mark.parametrize("cloud", ["gcp-to-aws", "azure-to-aws"])
def test_build_price_guard_rejects_a_missing_default_model_rate(tmp_path, cloud):
    script = SKILLS.parent / "scripts/validate-model-pricing.py"
    spec = importlib.util.spec_from_file_location("model_price_guard", script)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    paths = [
        "agent-advisor/scripts/model_recommendation.py",
        f"agent-advisor/references/models/{mr.DEFAULT_CATALOG.name}",
        "gcp-to-aws/references/shared/pricing-cache.md",
        "azure-to-aws/references/shared/pricing-cache.md",
    ]
    for relative in paths:
        target = tmp_path / "skills" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SKILLS / relative, target)
    assert guard.validate_model_pricing(tmp_path) == []
    cache = tmp_path / "skills" / cloud / "references/shared/pricing-cache.md"
    cache.write_text("\n".join(line for line in cache.read_text().splitlines() if MODEL not in line))
    assert guard.validate_model_pricing(tmp_path) == [
        f"{cloud}: candidate {MODEL} has no numeric Active price row."
    ]


def test_gemini_cost_comparison_uses_the_recommended_model_and_correct_denominator():
    text = (SKILLS / "gcp-to-aws/references/design-refs/ai-gemini-to-bedrock.md").read_text()
    assert "Claude Opus 5.5 Global ($4/$20)" in text
    assert "$2,100" in text and "+75%" in text
    assert "$2,310" in text and "+92.5%" in text
    assert (150 * 4 + 75 * 20) / 1200 - 1 == 0.75
    assert "when Batch is required because Opus 5.5 has no Batch tier" in text


def test_new_catalog_records_batch_and_thinking_constraints():
    for catalog, key in [(mr.load_catalog(), "claude_opus_5_5"),
                         (mr.load_openai_catalog(), "anthropic_claude_opus_5_5")]:
        model = catalog["models"][key]
        assert model["batch_supported"] is False
        assert model["adaptive_thinking_only"] is True
        assert model["lifecycle_status"] == "active"


def test_pricing_and_selection_share_the_verified_profile_region_matrix():
    expected = mr.load_catalog()["models"]["claude_opus_5_5"]["inference_profiles"]
    assert _script("bedrock_pricing")._OPUS55_PROFILE_REGIONS == expected
    assert mr.load_openai_catalog()["models"]["anthropic_claude_opus_5_5"]["inference_profiles"] == expected


@pytest.mark.parametrize("cloud", ["gcp-to-aws", "azure-to-aws"])
def test_long_context_estimates_do_not_apply_the_legacy_claude_surcharge(cloud):
    text = (SKILLS / cloud / "references/phases/estimate/estimate-ai.md").read_text()
    assert "**Long-context surcharge:**" not in text
    rule = text.split("**Long-context pricing:**", 1)[1].split("\n\n", 1)[0]
    assert "no long-context surcharge" in rule
    assert "same per-token rates throughout its 1M context" in rule
    assert "Global $4/$20" in rule and "GovCloud $4.80/$24" in rule
    assert "instead of guessing" in rule


@pytest.mark.parametrize("region,prefix,monthly", [
    ("us-east-1", "global.", 1040),
    ("us-east-1", "us.", 1144),
    ("us-gov-west-1", "us.", 1248),
])
def test_long_context_quote_uses_the_flat_published_rate(region, prefix, monthly):
    rate = _script("bedrock_pricing").lookup(region, prefix + MODEL)
    cost = 60000 * rate["input_per_1k_usd"] + 40000 * rate["output_per_1k_usd"]
    assert cost == pytest.approx(monthly)


@pytest.mark.parametrize("provider,path", [
    ("anthropic", "runtime_converse"),
    ("anthropic", "runtime_invoke"),
    ("openai", "runtime_converse"),
])
@pytest.mark.parametrize("explicit", [False, True])
def test_london_runtime_retains_bare_model_without_requiring_cris(provider, path, explicit):
    requirements = {"preferred_api_path": path, "data_residency": "unknown"}
    if explicit:
        requirements["inference_profile_id"] = MODEL
    if provider == "openai":
        requirements.update(preserve_openai_api=False, governance=["guardrails"])
    rec = _recommend("eu-west-2", provider=provider,
                     source_model="claude-opus-4-8" if provider == "anthropic" else "gpt-4",
                     **requirements)
    assert rec["invocation_model_id"] == MODEL
    assert rec["model_identity"]["requires_cris"] is False
    assert "inference_profile_unresolved" not in {item["code"] for item in rec["blocks"]}
    assert "allowed_inference_profiles" not in rec["verification"]
    assert not any("Resolve and probe" in item for item in rec["verification"]["required_checks"])


def test_london_preserves_explicit_profiles_and_rejects_conflicting_geography():
    rec = _recommend("eu-west-2", inference_profile_id="eu." + MODEL,
                     data_residency="geo_required", cris_geography="eu")
    assert rec["invocation_model_id"] == "eu." + MODEL
    assert rec["model_identity"]["requires_cris"] is True
    rec = _recommend("eu-west-2", inference_profile_id=MODEL,
                     data_residency="geo_required", cris_geography="us")
    assert rec["invocation_model_id"] is None
    assert _recommend("us-east-1", inference_profile_id=MODEL)["invocation_model_id"] is None


def test_london_runtime_preflight_iam_and_price_agree_on_the_selected_path(monkeypatch):
    exceptions = ModuleType("botocore.exceptions")
    exceptions.ClientError = type("ClientError", (Exception,), {})
    exceptions.BotoCoreError = type("BotoCoreError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "botocore", ModuleType("botocore"))
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exceptions)
    calls = []
    client = SimpleNamespace(
        meta=SimpleNamespace(region_name="eu-west-2"),
        converse=lambda **kwargs: calls.append(kwargs),
    )
    assert _script("preflight_bedrock").probe_model(client, MODEL)["ok"]
    assert calls[0]["modelId"] == MODEL
    policy = _script("iam_policy").generate_policy([MODEL], "eu-west-2", "123456789012")
    statement = policy["Statement"][0]
    assert "bedrock:InvokeModel" in statement["Action"]
    assert f"arn:aws:bedrock:*::foundation-model/{MODEL}" in statement["Resource"]
    assert all("bedrock-mantle" not in action
               for item in policy["Statement"] for action in item["Action"])
    price = _script("bedrock_pricing").lookup("eu-west-2", MODEL)
    assert price["available"]
    assert (price["input_per_1k_usd"], price["output_per_1k_usd"]) == (0.0044, 0.022)
    assert "runtime-in-region" in price["note"]
