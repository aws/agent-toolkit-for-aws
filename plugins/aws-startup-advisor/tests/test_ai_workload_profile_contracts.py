"""Contract tests for the target-only ai-workload-profile.json observation contract.

Pins the schema's self-validity, the semantic invariants (duplicate/overlap rejection,
model_observations <-> models[] correspondence, no fabricated IDs), and a deterministic
projection into PR #410's ai-migration-scenario.schema.json so the two contracts cannot
silently diverge. Target-only: no producer exists yet, no runtime behavior is asserted.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "ai-workload-profiles"
PROFILE_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "ai-workload-profile.schema.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
MATRIX_TEST_PATH = Path(__file__).resolve().parent / "test_ai_migration_matrix_contracts.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("ai_workload_profile__validator", VALIDATOR_PATH)
MATRIX = _load_module("ai_workload_profile__matrix_contracts", MATRIX_TEST_PATH)

POSITIVE_FIXTURES = sorted(FIXTURE_ROOT.glob("*/ai-workload-profile.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _profile_schema() -> dict:
    return _load(PROFILE_SCHEMA)


def _profile_findings(profile: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_profile_schema(), profile, "", "profile", str(PROFILE_SCHEMA), findings)
    return findings


def _assert_profile_semantics(profile: dict) -> None:
    """Mirrors MATRIX._assert_scenario_semantics' duplicate/overlap style, plus the
    model_observations <-> models[] correspondence this richer contract adds."""
    sources = {}
    for source in profile["ai_sources"]:
        key = (source["provider"], source["source_service"])
        assert key not in sources, f"duplicate or overlapping AI source: {key}"
        assert source["provider"] != "openrouter"
        sources[key] = source

        families = set(source["model_families"])
        models = set(source["models"])
        observations = {obs["normalized_model"]: obs for obs in source["model_observations"]}
        assert set(observations) == models, (
            f"model_observations must correspond exactly to models[]: {set(observations)} != {models}"
        )
        for obs in source["model_observations"]:
            assert obs["model_family"] in families, (
                f"model_observations family not in model_families: {obs['model_family']}"
            )

    for gateway in profile["gateways"]:
        upstream_keys = set()
        for upstream in gateway["upstreams"]:
            key = (upstream["provider"], upstream.get("source_service"))
            assert key not in upstream_keys, f"duplicate or overlapping gateway upstream: {key}"
            upstream_keys.add(key)


AI_ONLY_OUTCOMES = {
    "infrastructure": None,
    "ai": {"verdict": "passed", "artifacts": sorted(MATRIX.AI_ARTIFACTS)},
    "integration_validation": None,
}


def _project_to_scenario(profile: dict) -> dict:
    """The deterministic projection: ai_sources[] copies its five #410-shaped fields
    verbatim (dropping model_observations); gateways[] copies verbatim (already
    byte-identical in shape to #410's gateway). Wrapped in a synthetic ai_only scenario
    skeleton purely so #410's schema/semantics helpers can be reused unmodified."""
    ai_sources = [
        {
            "provider": s["provider"],
            "source_service": s["source_service"],
            "model_families": s["model_families"],
            "model_evidence": s["model_evidence"],
            "models": s["models"],
        }
        for s in profile["ai_sources"]
    ]
    gateways = [copy.deepcopy(g) for g in profile["gateways"]]
    return {
        "id": "ai-workload-profile-projection",
        "mode": "ai_only",
        "migration_id": "ai-workload-profile-projection",
        "run_id": "00000000-0000-4000-8000-000000000099",
        "state": ".phase-status.json",
        "dimensions": {
            "infrastructure_source": None,
            "ai_sources": ai_sources,
            "gateways": gateways,
        },
        "outcomes": AI_ONLY_OUTCOMES,
    }


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_profile_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _profile_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


# --------------------------------------------------------------------------- positive fixtures

@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_validate_against_profile_schema(fixture_path: Path) -> None:
    profile = _load(fixture_path)
    assert _profile_findings(profile) == []


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_satisfy_semantic_invariants(fixture_path: Path) -> None:
    _assert_profile_semantics(_load(fixture_path))


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_project_exactly_into_pr410_semantics(fixture_path: Path) -> None:
    profile = _load(fixture_path)
    scenario = _project_to_scenario(profile)
    assert MATRIX._schema_findings(MATRIX.SCENARIO_SCHEMA, scenario, fixture_path.name) == []
    MATRIX._assert_scenario_semantics(scenario)


def test_openrouter_multi_upstream_fixture_has_two_models_in_one_family() -> None:
    profile = _load(FIXTURE_ROOT / "openrouter-multi-upstream" / "ai-workload-profile.json")
    claude = next(s for s in profile["ai_sources"] if s["provider"] == "anthropic")
    assert len(claude["models"]) >= 2


def test_openai_direct_and_azure_fixture_preserves_distinct_provenance() -> None:
    profile = _load(FIXTURE_ROOT / "openai-direct-and-azure-openai" / "ai-workload-profile.json")
    services = {s["source_service"] for s in profile["ai_sources"] if s["provider"] == "openai"}
    assert services == {"openai_api", "azure_openai"}
    # raw_model differs across services even though normalized_model is identical —
    # proves the raw alias is retained independently of normalization.
    raw_by_service = {
        s["source_service"]: s["model_observations"][0]["raw_model"]
        for s in profile["ai_sources"] if s["provider"] == "openai"
    }
    assert len(set(raw_by_service.values())) == 2


def test_unresolved_gateway_fixture_has_empty_upstreams() -> None:
    profile = _load(FIXTURE_ROOT / "openrouter-unresolved" / "ai-workload-profile.json")
    gateway = profile["gateways"][0]
    assert gateway["upstream_evidence"] == "unresolved"
    assert gateway["upstreams"] == []


# --------------------------------------------------------------------------- negative mutations

def _base_profile() -> dict:
    return copy.deepcopy(_load(FIXTURE_ROOT / "ai-only-multi-direct" / "ai-workload-profile.json"))


def test_empty_model_observations_on_an_observed_source_is_rejected() -> None:
    """The schema's observed branch now requires model_observations non-empty (minItems: 1),
    so clearing model_observations on an observed source is rejected directly at the schema
    level. _assert_profile_semantics remains as defense-in-depth for the exact-set-equality
    check (model_observations keys == models[]) that minItems alone cannot express."""
    profile = _base_profile()
    profile["ai_sources"][0]["model_observations"] = []
    assert _profile_findings(profile) != []
    with pytest.raises(AssertionError):
        _assert_profile_semantics(profile)


def test_duplicate_ai_source_identity_is_rejected() -> None:
    """An exact-duplicate aiSource dict is already caught by the schema's uniqueItems;
    confirmed by running validate_json_schema against the schema directly (a byte-identical
    duplicate produces a uniqueItems SCHEMA_VIOLATION). Follow #410's own
    test_duplicate_or_overlapping_ai_sources_are_rejected if/else pattern rather than
    asserting one branch, since whether uniqueItems or the semantic check catches a given
    mutation depends on whether the duplicate is byte-identical or merely overlapping."""
    profile = _base_profile()
    profile["ai_sources"].append(copy.deepcopy(profile["ai_sources"][0]))
    if not _profile_findings(profile):
        with pytest.raises(AssertionError):
            _assert_profile_semantics(profile)
    else:
        assert _profile_findings(profile)


def test_dropped_model_under_a_resolved_upstream_is_rejected() -> None:
    profile = _load(FIXTURE_ROOT / "openrouter-multi-upstream" / "ai-workload-profile.json")
    scenario = _project_to_scenario(profile)
    # Drop one of Claude's two models from the gateway upstream while the source keeps both.
    upstream = next(
        u for u in scenario["dimensions"]["gateways"][0]["upstreams"] if u["provider"] == "anthropic"
    )
    upstream["model_families"][0]["models"].remove("claude-3-haiku-20240307")
    with pytest.raises(AssertionError):
        MATRIX._assert_scenario_semantics(scenario)


def test_fabricated_unknown_model_id_is_rejected() -> None:
    profile = _base_profile()
    profile["ai_sources"][0]["models"] = ["unknown"]
    profile["ai_sources"][0]["model_observations"][0]["normalized_model"] = "unknown"
    assert any(
        "unknown" in f.message or "pattern" in f.message for f in _profile_findings(profile)
    )


def test_openrouter_as_a_direct_provider_is_rejected() -> None:
    profile = _base_profile()
    profile["ai_sources"][0]["provider"] = "openrouter"
    assert _profile_findings(profile) != []


def test_empty_upstreams_on_an_observed_gateway_is_rejected() -> None:
    profile = _base_profile()
    profile["gateways"] = [
        {"product": "openrouter", "type": "llm_router", "upstream_evidence": "observed", "upstreams": []}
    ]
    assert _profile_findings(profile) != []


def test_invented_upstream_on_an_unresolved_gateway_is_rejected() -> None:
    profile = _load(FIXTURE_ROOT / "openrouter-multi-upstream" / "ai-workload-profile.json")
    gateway = profile["gateways"][0]
    gateway["upstream_evidence"] = "unresolved"
    # upstreams[] still populated — invented upstream on an unresolved gateway.
    assert _profile_findings(profile) != []
