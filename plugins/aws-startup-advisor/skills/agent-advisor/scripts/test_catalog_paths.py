"""Catalog-shape guards for the Bedrock path vocabulary.

The two vendored model catalogs, the recommendation input/output schemas and
the verification schema must agree on one set of API path names. The
bedrock-runtime paths (runtime_openai_responses, runtime_openai_chat,
runtime_messages) were added from the public model cards on 2026-11-07; every
such row must cite its docs.aws.amazon.com source and a read date.
"""
import json
import pathlib
import re
import urllib.parse

import pytest

import model_recommendation


SCHEMAS = pathlib.Path(model_recommendation.__file__).parent / "schemas"
RUNTIME_SDK_PATHS = ("runtime_openai_responses", "runtime_openai_chat", "runtime_messages")
GPT_56_MODELS = ("openai_gpt_5_6_sol", "openai_gpt_5_6_terra", "openai_gpt_5_6_luna")
_URL = re.compile(r"https?://[^\s)\]]+")
_READ_2026_11_07_OR_08 = re.compile(r"read 2026-11-0[78]")


def _schema(name):
    return json.loads((SCHEMAS / name).read_text())


def _cites_aws_docs(text):
    """True when `text` contains an https URL whose host is exactly
    docs.aws.amazon.com (hostname equality after urlparse, not a substring)."""
    urls = _URL.findall(text or "")
    return any(
        urllib.parse.urlparse(url).scheme == "https"
        and urllib.parse.urlparse(url).hostname == "docs.aws.amazon.com"
        for url in urls
    )


@pytest.fixture(scope="module")
def catalogs():
    return {
        "anthropic": model_recommendation.load_catalog(),
        "openai": model_recommendation.load_openai_catalog(),
    }


def test_model_path_keys_are_declared_at_the_top_level(catalogs):
    for name, catalog in catalogs.items():
        declared = set(catalog["paths"])
        for model_key, model in catalog["models"].items():
            undeclared = set(model["paths"]) - declared
            assert not undeclared, f"{name}: {model_key} uses undeclared paths {sorted(undeclared)}"


def test_catalog_paths_match_every_schema_enum(catalogs):
    catalog_paths = set()
    for catalog in catalogs.values():
        catalog_paths |= set(catalog["paths"])
    output_enum = set(_schema("model-recommendation.json")["$defs"]["apiPath"]["enum"])
    verification_enum = set(_schema("model-verification.json")["$defs"]["apiPath"]["enum"])
    input_schema = _schema("model-recommendation-input.json")
    requirements = input_schema["properties"]["workloads"]["items"]["properties"]["requirements"]
    input_enum = set(requirements["properties"]["preferred_api_path"]["enum"])

    assert catalog_paths == output_enum
    assert output_enum == verification_enum
    assert output_enum == input_enum


def test_every_path_row_has_the_required_keys(catalogs):
    for name, catalog in catalogs.items():
        for model_key, model in catalog["models"].items():
            for path, row in model["paths"].items():
                for key in ("available", "model_id", "requires_cris"):
                    assert key in row, f"{name}: {model_key}.{path} lacks {key}"
                assert isinstance(row["available"], bool)
                assert isinstance(row["requires_cris"], bool)
                assert row["model_id"]


def test_openai_runtime_rows_are_cris_profiles_on_openai_ids(catalogs):
    for model_key, model in catalogs["openai"]["models"].items():
        if not model_key.startswith("openai_gpt_"):
            continue
        for path in ("runtime_openai_responses", "runtime_openai_chat"):
            assert path in model["paths"], f"{model_key} lacks {path}"
        for path, row in model["paths"].items():
            if path.startswith("runtime_"):
                assert row["requires_cris"] is True, f"{model_key}.{path}"
                assert row["model_id"].startswith("openai."), f"{model_key}.{path}"


def test_openai_runtime_sdk_rows_do_not_appear_on_claude_entries(catalogs):
    for model_key, model in catalogs["openai"]["models"].items():
        if model_key.startswith("anthropic_claude_"):
            for path in ("runtime_openai_responses", "runtime_openai_chat"):
                assert path not in model["paths"], f"{model_key} must not carry {path}"


def test_anthropic_runtime_messages_uses_the_runtime_converse_model_id(catalogs):
    for model_key, model in catalogs["anthropic"]["models"].items():
        paths = model["paths"]
        assert "runtime_messages" in paths, f"{model_key} lacks runtime_messages"
        assert paths["runtime_messages"]["model_id"] == paths["runtime_converse"]["model_id"], model_key
        assert paths["runtime_messages"]["requires_cris"] is True, model_key


def test_runtime_sdk_path_definitions_target_bedrock_runtime(catalogs):
    openai_paths = catalogs["openai"]["paths"]
    for path in ("runtime_openai_responses", "runtime_openai_chat"):
        definition = openai_paths[path]
        assert definition["endpoint"] == "https://bedrock-runtime.{region}.amazonaws.com/openai/v1"
        assert definition["iam_action"] == "bedrock:InvokeModel"
        assert definition["model_id_strategy"] == "cris_inference_profile"
        assert definition["supports_cris"] is True
    assert openai_paths["runtime_openai_responses"]["api"] == "responses"
    assert openai_paths["runtime_openai_chat"]["api"] == "chat_completions"
    messages = catalogs["anthropic"]["paths"]["runtime_messages"]
    assert "bedrock-runtime.{region}.amazonaws.com/anthropic" in messages["client"]
    assert messages["iam_action"] == "bedrock:InvokeModel"
    assert messages["model_id_strategy"] == "cris_inference_profile"
    assert messages["supports_cris"] is True


def test_openai_runtime_converse_strengths_name_both_cloudwatch_namespaces(catalogs):
    text = "\n".join(catalogs["openai"]["paths"]["runtime_converse"]["strengths"])
    assert "AWS/BedrockMantle" in text
    assert "monitoring-mantle-metrics" in text
    assert "invocation logging, and CloudWatch" not in text


def test_new_runtime_rows_cite_public_docs_with_a_read_date(catalogs):
    read_date = re.compile(r"read 20\d\d-\d\d-\d\d")
    for name, catalog in catalogs.items():
        for model_key, model in catalog["models"].items():
            for path, row in model["paths"].items():
                if path not in RUNTIME_SDK_PATHS:
                    continue
                evidence = row.get("evidence", "")
                assert _cites_aws_docs(evidence), f"{name}: {model_key}.{path}"
                assert read_date.search(evidence), f"{name}: {model_key}.{path} lacks a read date"


# --- GPT-5.6 Sol/Terra/Luna re-read from their public model cards (2026-11-08) ---

@pytest.mark.parametrize("model_key", GPT_56_MODELS)
def test_gpt56_models_list_mantle_chat_with_dated_card_evidence(catalogs, model_key):
    row = catalogs["openai"]["models"][model_key]["paths"]["mantle_openai_chat"]
    assert row["available"] is True, model_key
    assert row["requires_cris"] is False, model_key
    assert _cites_aws_docs(row["evidence"]), model_key
    assert _READ_2026_11_07_OR_08.search(row["evidence"]), model_key


def test_gpt56_inference_profile_matrices_follow_the_cards(catalogs):
    models = catalogs["openai"]["models"]
    us_sources = models["openai_gpt_5_4"]["inference_profiles"]["us"]
    sol = models["openai_gpt_5_6_sol"]["inference_profiles"]
    assert set(sol) == {"us", "global"}
    assert sol["us"] == us_sources
    for model_key in ("openai_gpt_5_6_terra", "openai_gpt_5_6_luna"):
        profiles = models[model_key]["inference_profiles"]
        assert set(profiles) == {"us", "in", "us-gov", "global"}, model_key
        assert profiles["us"] == us_sources, model_key
        assert profiles["in"] == ["ap-south-1", "ap-south-2"], model_key
        assert profiles["us-gov"] == ["us-gov-east-1", "us-gov-west-1"], model_key
        assert not any(region.startswith("us-gov-") for region in profiles["global"]), model_key


def test_every_gpt_path_row_carries_a_boolean_guardrails_flag(catalogs):
    models = catalogs["openai"]["models"]
    responses_true = set()
    chat_true = set()
    for model_key, model in models.items():
        if model.get("generation") == "bedrock_native":
            continue
        for path, row in model["paths"].items():
            assert isinstance(row.get("guardrails_supported"), bool), f"{model_key}.{path}"
            if path.startswith("mantle_"):
                assert row["guardrails_supported"] is False, f"{model_key}.{path}"
            if path == "runtime_converse":
                assert row["guardrails_supported"] is True, f"{model_key}.{path}"
            if path == "runtime_openai_responses" and row["guardrails_supported"]:
                responses_true.add(model_key)
            if path == "runtime_openai_chat" and row["guardrails_supported"]:
                chat_true.add(model_key)
    assert responses_true == {"openai_gpt_6_sol", "openai_gpt_6_luna"}
    assert chat_true == {"openai_gpt_6_sol", "openai_gpt_6_luna", "openai_gpt_6_1_sol"}


def test_only_gpt61_sol_mantle_rows_deny_server_side_tools(catalogs):
    models = catalogs["openai"]["models"]
    denied = {
        (model_key, path)
        for model_key, model in models.items()
        for path, row in model["paths"].items()
        if row.get("server_side_tools_supported") is False
    }
    assert denied == {
        ("openai_gpt_6_1_sol", "mantle_openai_responses"),
        ("openai_gpt_6_1_sol", "mantle_openai_chat"),
    }
    for path in ("mantle_openai_responses", "mantle_openai_chat"):
        row = models["openai_gpt_6_1_sol"]["paths"][path]
        assert _cites_aws_docs(row["evidence"])
        assert "read 2026-11-08" in row["evidence"]


@pytest.mark.parametrize("model_key", ("openai_gpt_5_4", "openai_gpt_5_5"))
def test_gpt54_gpt55_scope_structured_outputs_to_the_responses_api(catalogs, model_key):
    paths = catalogs["openai"]["models"][model_key]["paths"]
    assert "structured_output_json" in paths["runtime_openai_responses"]["capabilities"]
    assert "structured_output_json" not in paths["runtime_openai_chat"]["capabilities"]
    assert "structured_output_json" not in paths["runtime_converse"]["capabilities"]
