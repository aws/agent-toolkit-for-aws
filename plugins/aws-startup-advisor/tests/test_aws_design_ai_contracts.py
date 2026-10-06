"""Contract tests for the target-only, canonical aws-design-ai.json contract.

Pins the schema's self-validity and proves that `metadata.ai_sources[]` / `metadata.gateways[]`
project exactly into #415's `ai-workload-profile.schema.json` shape, reusing #415's own
semantic-assertion helper (`_assert_profile_semantics`) as the oracle — the same way #415
reused #410's `test_ai_migration_matrix_contracts.py` helpers. Target-only: no producer emits
this shape yet (`design-ai.md` is unchanged in both skills); no runtime behavior is asserted.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "aws-design-ai"
DESIGN_AI_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "aws-design-ai.schema.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
WORKLOAD_PROFILE_TEST_PATH = Path(__file__).resolve().parent / "test_ai_workload_profile_contracts.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("aws_design_ai__validator", VALIDATOR_PATH)
# #415's own test module: imports/executes it to reuse _assert_profile_semantics as the oracle,
# exactly as #415 reused #410's test_ai_migration_matrix_contracts.py (MATRIX) module.
WORKLOAD_PROFILE = _load_module("aws_design_ai__workload_profile_contracts", WORKLOAD_PROFILE_TEST_PATH)

POSITIVE_FIXTURES = sorted(FIXTURE_ROOT.glob("*/aws-design-ai.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _design_ai_schema() -> dict:
    return _load(DESIGN_AI_SCHEMA)


def _design_ai_findings(design: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_design_ai_schema(), design, "", "design", str(DESIGN_AI_SCHEMA), findings)
    return findings


def _project_to_profile(design: dict) -> dict:
    """The deterministic projection: metadata.ai_sources[]/gateways[] already carry the exact
    #415-shaped fields (provider, source_service, model_families, model_evidence, models,
    model_observations for sources; product/type/upstream_evidence/upstreams for gateways) —
    this wraps them in a synthetic ai-workload-profile.json skeleton purely so #415's own
    schema/semantics helpers can be reused unmodified."""
    return {
        "schema_version": "1.0",
        "ai_sources": copy.deepcopy(design["metadata"]["ai_sources"]),
        "gateways": copy.deepcopy(design["metadata"]["gateways"]),
    }


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_design_ai_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _design_ai_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


def test_metadata_rejects_the_retired_single_scalar_ai_source() -> None:
    """additionalProperties: false on the metadata object means a vestigial scalar ai_source
    field (the retired #386-era shape) is rejected outright, not merely undocumented."""
    schema = _design_ai_schema()
    assert schema["definitions"]["metadata"]["additionalProperties"] is False
    assert "ai_source" not in schema["definitions"]["metadata"]["properties"]


# --------------------------------------------------------------------------- positive fixtures

@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_validate_against_design_ai_schema(fixture_path: Path) -> None:
    design = _load(fixture_path)
    assert _design_ai_findings(design) == []


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_project_exactly_into_pr415_semantics(fixture_path: Path) -> None:
    design = _load(fixture_path)
    profile = _project_to_profile(design)
    assert WORKLOAD_PROFILE._profile_findings(profile) == []
    WORKLOAD_PROFILE._assert_profile_semantics(profile)


def test_multi_provider_fixture_carries_two_simultaneous_direct_sources() -> None:
    """Exercises the multi-provider case: one Anthropic-sourced + one OpenAI-sourced
    design_block in a single aws-design-ai.json, with no gateway involved."""
    design = _load(FIXTURE_ROOT / "multi-provider-direct" / "aws-design-ai.json")
    providers = {s["provider"] for s in design["metadata"]["ai_sources"]}
    assert providers == {"anthropic", "openai"}
    assert not design["metadata"]["gateways"]
    assert len(design["design_blocks"]) == 2


def test_gateway_fixture_carries_multi_upstream_openrouter_fronting_two_providers() -> None:
    """Exercises the gateway-fronted multi-upstream case: one OpenRouter gateway fronting
    Anthropic (two models) and OpenAI simultaneously."""
    design = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json")
    gateways = design["metadata"]["gateways"]
    assert len(gateways) == 1
    upstream_providers = {u["provider"] for u in gateways[0]["upstreams"]}
    assert upstream_providers == {"anthropic", "openai"}
    claude = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    assert len(claude["models"]) == 2
    assert len(design["design_blocks"]) == 3


# --------------------------------------------------------------------------- negative mutations

def _base_design() -> dict:
    return copy.deepcopy(_load(FIXTURE_ROOT / "multi-provider-direct" / "aws-design-ai.json"))


def test_old_single_scalar_ai_source_shape_is_rejected() -> None:
    """The retired Azure-only shape: a single scalar metadata.ai_source string standing in
    for the multi-provider reality, instead of metadata.ai_sources[]/gateways[]. Proves the
    sentinel single-identity pattern is actually retired by this contract, not just
    redocumented — directly answering #415's own Cursor-review precedent of locking a negative
    case with an assertion rather than a fixture directory."""
    design = _base_design()
    del design["metadata"]["ai_sources"]
    del design["metadata"]["gateways"]
    design["metadata"]["ai_source"] = "both"
    assert _design_ai_findings(design) != []


def test_old_single_scalar_ai_source_with_one_provider_is_also_rejected() -> None:
    """Even a single-valued old-shape scalar (not just the 'both' sentinel) is rejected,
    because additionalProperties: false on metadata means ai_sources[]/gateways[] are
    required and ai_source is unknown — the scalar shape cannot coexist with the new one."""
    design = _base_design()
    del design["metadata"]["ai_sources"]
    del design["metadata"]["gateways"]
    design["metadata"]["ai_source"] = "anthropic"
    assert _design_ai_findings(design) != []


def test_duplicate_ai_source_identity_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"].append(copy.deepcopy(design["metadata"]["ai_sources"][0]))
    assert _design_ai_findings(design) != []


def test_openrouter_as_a_direct_provider_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"][0]["provider"] = "openrouter"
    assert _design_ai_findings(design) != []


def test_dropped_model_under_a_resolved_gateway_upstream_is_rejected() -> None:
    design = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json")
    profile = _project_to_profile(design)
    upstream = next(
        u for u in profile["gateways"][0]["upstreams"] if u["provider"] == "anthropic"
    )
    upstream["model_families"][0]["models"].remove("claude-3-haiku-20240307")
    with pytest.raises(AssertionError):
        WORKLOAD_PROFILE.MATRIX._assert_scenario_semantics(
            WORKLOAD_PROFILE._project_to_scenario(profile)
        )


def test_design_block_without_exactly_one_target_is_rejected() -> None:
    design = _base_design()
    design["design_blocks"][0]["target_bedrock_model"] = None
    assert _design_ai_findings(design) != []

    design = _base_design()
    design["design_blocks"][0]["target_aws_service"] = "textract"
    assert _design_ai_findings(design) != []


def test_fabricated_unknown_model_in_metadata_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"][0]["models"] = ["unknown"]
    design["metadata"]["ai_sources"][0]["model_observations"][0]["normalized_model"] = "unknown"
    assert _design_ai_findings(design) != []
