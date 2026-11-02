"""Contract tests for the target-only, canonical estimation-ai.json contract.

Pins the schema's self-validity and proves that `cost_by_source[]` projects into
(is a subset of) the matching `aws-design-ai.json`'s `metadata.ai_sources[]` /
`metadata.gateways[].upstreams[]` it was built from, reusing #416's own validator helpers
as the oracle — the same way #416 reused #415's helpers. Target-only: no producer emits
this shape yet (`estimate-ai.md` is unchanged in both skills); no runtime behavior is
asserted.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "estimation-ai"
DESIGN_FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "aws-design-ai"
ESTIMATION_AI_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "estimation-ai.schema.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
SYNC_VENDORED_PATH = PLUGIN_ROOT / "tools" / "sync-vendored.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("estimation_ai__validator", VALIDATOR_PATH)

POSITIVE_FIXTURES = sorted(FIXTURE_ROOT.glob("*/estimation-ai.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _estimation_ai_schema() -> dict:
    return _load(ESTIMATION_AI_SCHEMA)


def _estimation_ai_findings(estimate: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_estimation_ai_schema(), estimate, "", "estimate", str(ESTIMATION_AI_SCHEMA), findings)
    return findings


def _base_estimate() -> dict:
    return copy.deepcopy(_load(FIXTURE_ROOT / "multi-provider-direct" / "estimation-ai.json"))


def _matching_design(case: str) -> dict:
    return _load(DESIGN_FIXTURE_ROOT / case / "aws-design-ai.json")


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_estimation_ai_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _estimation_ai_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


# --------------------------------------------------------------------------- positive fixtures

@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_validate_against_estimation_ai_schema(fixture_path: Path) -> None:
    estimate = _load(fixture_path)
    assert _estimation_ai_findings(estimate) == []


def test_multi_provider_fixture_carries_two_simultaneous_direct_sources() -> None:
    estimate = _load(FIXTURE_ROOT / "multi-provider-direct" / "estimation-ai.json")
    providers = {s["provider"] for s in estimate["cost_by_source"]}
    assert providers == {"anthropic", "openai"}


def test_gateway_fixture_carries_multi_upstream_openrouter_fronting_two_providers() -> None:
    estimate = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "estimation-ai.json")
    claude = next(s for s in estimate["cost_by_source"] if s["provider"] == "anthropic")
    assert len(claude["models"]) == 2
    openai_source = next(s for s in estimate["cost_by_source"] if s["provider"] == "openai")
    assert len(openai_source["models"]) == 1


def test_unknown_source_baseline_propagates_null_to_dependent_deltas() -> None:
    estimate = _base_estimate()
    estimate["current_costs"]["monthly_ai_spend"] = None
    comparison = estimate["cost_comparison"]
    comparison["current_source_monthly"] = None
    comparison["monthly_difference"] = None
    comparison["annual_difference"] = None
    comparison["percent_change"] = None
    for source in estimate["cost_by_source"]:
        for model in source["models"]:
            model["vs_source_percent"] = None

    assert _estimation_ai_findings(estimate) == []
    assert comparison["projected_bedrock_monthly"] is not None

    comparison["projected_bedrock_monthly"] = 0
    assert comparison["projected_bedrock_monthly"] == 0
    assert comparison["projected_bedrock_monthly"] is not None
    assert _estimation_ai_findings(estimate) == []

    comparison["projected_bedrock_monthly"] = "0"
    assert _estimation_ai_findings(estimate) != []


def test_unavailable_target_pricing_preserves_unknown_costs_as_null() -> None:
    estimate = _base_estimate()
    estimate["pricing_source"] = "unavailable"
    comparison = estimate["cost_comparison"]
    comparison["projected_bedrock_monthly"] = None
    comparison["monthly_difference"] = None
    comparison["annual_difference"] = None
    comparison["percent_change"] = None
    for source in estimate["cost_by_source"]:
        for model in source["models"]:
            model["monthly_cost"] = None
            model["vs_source_percent"] = None

    assert _estimation_ai_findings(estimate) == []


# --------------------------------------------------------------------------- cross-phase projection


def _assert_cost_by_source_projects_into_design(estimate: dict, design: dict) -> None:
    """Every `cost_by_source[]` entry's `(provider, source_service, models[])` MUST project
    into (be a subset of) the matching `aws-design-ai.json`'s `metadata.ai_sources[]` /
    `metadata.gateways[].upstreams[]` — same 'projects exactly/subset' style as
    #416's `test_positive_fixtures_project_exactly_into_pr415_semantics`."""
    direct_models: dict[tuple, set] = {}
    for source in design["metadata"]["ai_sources"]:
        direct_models[(source["provider"], source["source_service"])] = set(source["models"])
    upstream_models: dict[tuple, set] = {}
    for gateway in design["metadata"]["gateways"]:
        for upstream in gateway["upstreams"]:
            key = (upstream["provider"], upstream["source_service"])
            models = upstream_models.setdefault(key, set())
            for family in upstream["model_families"]:
                models.update(family["models"])

    for entry in estimate["cost_by_source"]:
        key = (entry["provider"], entry["source_service"])
        allowed = direct_models.get(key) or upstream_models.get(key)
        assert allowed is not None, (
            f"cost_by_source[] entry {key!r} traces to no aws-design-ai.json "
            f"metadata.ai_sources[] entry or metadata.gateways[] upstream"
        )
        entry_models = {m["model"] for m in entry["models"]}
        assert entry_models <= allowed, (
            f"cost_by_source[] entry {key!r} names models {entry_models - allowed!r} "
            f"not present in the matching aws-design-ai.json source"
        )


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_project_into_matching_design_source(fixture_path: Path) -> None:
    estimate = _load(fixture_path)
    design = _matching_design(fixture_path.parent.name)
    _assert_cost_by_source_projects_into_design(estimate, design)


def test_untraceable_model_under_resolved_design_source_is_rejected() -> None:
    """Mirrors #416's `test_design_block_naming_an_untraceable_model_is_rejected` one phase
    forward: a cost_by_source[] entry naming a model not present in the matching
    aws-design-ai.json's resolved ai_sources[]/gateways[] is a fabricated/untraceable model."""
    estimate = _base_estimate()
    design = _matching_design("multi-provider-direct")
    estimate["cost_by_source"][0]["models"][0]["model"] = "made-up-model"
    with pytest.raises(AssertionError):
        _assert_cost_by_source_projects_into_design(estimate, design)


def test_dropped_model_under_a_resolved_gateway_upstream_is_rejected() -> None:
    """Mirrors #416's own test of the same name one phase forward: a model that is removed
    from BOTH the gateway upstream and the direct source in aws-design-ai.json is no longer
    traceable, so a cost_by_source[] entry still naming it must be rejected."""
    estimate = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "estimation-ai.json")
    design = copy.deepcopy(_matching_design("openrouter-gateway-multi-upstream"))
    anthropic_source = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    anthropic_source["models"].remove("claude-3-haiku-20240307")
    anthropic_source["model_observations"] = [
        obs for obs in anthropic_source["model_observations"] if obs["normalized_model"] != "claude-3-haiku-20240307"
    ]
    for gateway in design["metadata"]["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "anthropic":
                for family in upstream["model_families"]:
                    if "claude-3-haiku-20240307" in family["models"]:
                        family["models"].remove("claude-3-haiku-20240307")
    with pytest.raises(AssertionError):
        _assert_cost_by_source_projects_into_design(estimate, design)


# --------------------------------------------------------------------------- negative mutations


def test_duplicate_cost_by_source_identity_is_rejected() -> None:
    estimate = _base_estimate()
    estimate["cost_by_source"].append(copy.deepcopy(estimate["cost_by_source"][0]))
    assert _estimation_ai_findings(estimate) != []


def _assert_cost_by_source_identity_is_unique(estimate: dict) -> None:
    """uniqueItems on cost_by_source[] only rejects byte-identical duplicates; two entries
    with the SAME (provider, source_service) pair but different payloads (an overlapping
    identity, not an exact duplicate) need this semantic check instead, mirroring
    #415's/#416's own key-based duplicate/overlap check for ai_sources[]."""
    seen = set()
    for entry in estimate["cost_by_source"]:
        key = (entry["provider"], entry["source_service"])
        assert key not in seen, f"duplicate or overlapping cost_by_source identity: {key}"
        seen.add(key)


def test_positive_fixtures_have_unique_cost_by_source_identity() -> None:
    for fixture_path in POSITIVE_FIXTURES:
        _assert_cost_by_source_identity_is_unique(_load(fixture_path))


def test_overlapping_cost_by_source_identity_is_rejected() -> None:
    """A second entry with the SAME (provider, source_service) pair but different model
    content is still a duplicate/overlapping identity, not a legitimate second entry —
    schema-level uniqueItems alone cannot catch this (see helper docstring), so the semantic
    helper above is the lock."""
    estimate = _base_estimate()
    overlapping = copy.deepcopy(estimate["cost_by_source"][0])
    overlapping["models"][0]["monthly_cost"] = 1.0
    estimate["cost_by_source"].append(overlapping)
    with pytest.raises(AssertionError):
        _assert_cost_by_source_identity_is_unique(estimate)


def test_openrouter_as_a_direct_cost_by_source_provider_is_rejected() -> None:
    estimate = _base_estimate()
    estimate["cost_by_source"][0]["provider"] = "openrouter"
    assert _estimation_ai_findings(estimate) != []


def test_malformed_cost_by_source_entry_missing_models_is_rejected() -> None:
    estimate = _base_estimate()
    del estimate["cost_by_source"][0]["models"]
    assert _estimation_ai_findings(estimate) != []


def test_recommendation_requires_a_valid_path_enum() -> None:
    estimate = _base_estimate()
    estimate["recommendation"]["path"] = "not_a_real_path"
    assert _estimation_ai_findings(estimate) != []


def test_optimization_opportunity_missing_type_is_rejected() -> None:
    estimate = _base_estimate()
    del estimate["optimization_opportunities"][0]["type"]
    assert _estimation_ai_findings(estimate) != []


def test_services_not_estimated_entry_requires_not_token_priced_reason() -> None:
    estimate = _base_estimate()
    estimate["services_not_estimated"] = [
        {"workload_id": "wl_doc1", "target_aws_service": "textract", "reason": "something_else"}
    ]
    assert _estimation_ai_findings(estimate) != []


# --------------------------------------------------------------------------- vendored byte-identity


def test_vendored_copies_are_byte_identical() -> None:
    """Reuses tools/sync-vendored.py --check (the dedicated CI gate) rather than
    re-implementing filecmp logic inline, matching the project's existing pattern."""
    result = subprocess.run(
        [sys.executable, str(SYNC_VENDORED_PATH), "--check"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
