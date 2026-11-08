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

import pytest

import model_recommendation


SCHEMAS = pathlib.Path(model_recommendation.__file__).parent / "schemas"
RUNTIME_SDK_PATHS = ("runtime_openai_responses", "runtime_openai_chat", "runtime_messages")


def _schema(name):
    return json.loads((SCHEMAS / name).read_text())


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
                assert "docs.aws.amazon.com" in evidence, f"{name}: {model_key}.{path}"
                assert read_date.search(evidence), f"{name}: {model_key}.{path} lacks a read date"
