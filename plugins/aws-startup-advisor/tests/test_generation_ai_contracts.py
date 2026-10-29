"""Contract tests for the target-only, canonical generation-ai.json contract.

Pins the schema's self-validity and proves that `artifacts_by_source[]` projects into
(is a subset of) the matching `estimation-ai.json`'s `cost_by_source[]` it was built from —
one phase forward from `test_estimation_ai_contracts.py`'s own projection into
`aws-design-ai.json`. Target-only: no producer emits this shape yet (`generate-ai.md` /
`generate-artifacts-ai.md` are unchanged in both skills); no runtime behavior is asserted.
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
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "generation-ai"
ESTIMATION_FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "estimation-ai"
GENERATION_AI_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "generation-ai.schema.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
SYNC_VENDORED_PATH = PLUGIN_ROOT / "tools" / "sync-vendored.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("generation_ai__validator", VALIDATOR_PATH)

POSITIVE_FIXTURES = sorted(FIXTURE_ROOT.glob("*/generation-ai.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _generation_ai_schema() -> dict:
    return _load(GENERATION_AI_SCHEMA)


def _generation_ai_findings(generation: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_generation_ai_schema(), generation, "", "generation", str(GENERATION_AI_SCHEMA), findings)
    return findings


def _base_generation() -> dict:
    return copy.deepcopy(_load(FIXTURE_ROOT / "multi-provider-direct" / "generation-ai.json"))


def _matching_estimation(case: str) -> dict:
    return _load(ESTIMATION_FIXTURE_ROOT / case / "estimation-ai.json")


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_generation_ai_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _generation_ai_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


# --------------------------------------------------------------------------- positive fixtures

@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_validate_against_generation_ai_schema(fixture_path: Path) -> None:
    generation = _load(fixture_path)
    assert _generation_ai_findings(generation) == []


def test_multi_provider_fixture_carries_two_simultaneous_direct_sources() -> None:
    generation = _load(FIXTURE_ROOT / "multi-provider-direct" / "generation-ai.json")
    providers = {s["provider"] for s in generation["artifacts_by_source"]}
    assert providers == {"anthropic", "openai"}


def test_gateway_fixture_carries_multi_upstream_openrouter_fronting_two_providers() -> None:
    generation = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "generation-ai.json")
    claude = next(s for s in generation["artifacts_by_source"] if s["provider"] == "anthropic")
    assert len(claude["models"]) == 2
    openai_source = next(s for s in generation["artifacts_by_source"] if s["provider"] == "openai")
    assert len(openai_source["models"]) == 1


# --------------------------------------------------------------------------- cross-phase projection


def _assert_artifacts_by_source_projects_into_estimation(generation: dict, estimation: dict) -> None:
    """Every `artifacts_by_source[]` entry's `(provider, source_service, models[])` MUST
    project into (be a subset of) the matching `estimation-ai.json`'s `cost_by_source[]` —
    one phase forward from the estimate-level projection into `aws-design-ai.json`."""
    allowed_models: dict[tuple, set] = {}
    for entry in estimation["cost_by_source"]:
        key = (entry["provider"], entry["source_service"])
        allowed_models[key] = {m["model"] for m in entry["models"]}

    for entry in generation["artifacts_by_source"]:
        key = (entry["provider"], entry["source_service"])
        allowed = allowed_models.get(key)
        assert allowed is not None, (
            f"artifacts_by_source[] entry {key!r} traces to no estimation-ai.json "
            f"cost_by_source[] entry"
        )
        entry_models = {m["model"] for m in entry["models"]}
        assert entry_models <= allowed, (
            f"artifacts_by_source[] entry {key!r} names models {entry_models - allowed!r} "
            f"not present in the matching estimation-ai.json cost_by_source[] entry"
        )


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_project_into_matching_estimation_source(fixture_path: Path) -> None:
    generation = _load(fixture_path)
    estimation = _matching_estimation(fixture_path.parent.name)
    _assert_artifacts_by_source_projects_into_estimation(generation, estimation)


def test_untraceable_model_under_resolved_estimation_source_is_rejected() -> None:
    """Mirrors the estimate-level untraceable-model negative one phase forward: an
    artifacts_by_source[] entry naming a model not present in the matching
    estimation-ai.json's cost_by_source[] is a fabricated/untraceable model."""
    generation = _base_generation()
    estimation = _matching_estimation("multi-provider-direct")
    generation["artifacts_by_source"][0]["models"][0]["model"] = "made-up-model"
    with pytest.raises(AssertionError):
        _assert_artifacts_by_source_projects_into_estimation(generation, estimation)


def test_dropped_model_under_a_resolved_gateway_upstream_is_rejected() -> None:
    """Mirrors the estimate-level dropped-model negative one phase forward: a model removed
    from the matching estimation-ai.json's cost_by_source[] entry is no longer traceable, so
    an artifacts_by_source[] entry still naming it must be rejected."""
    generation = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "generation-ai.json")
    estimation = copy.deepcopy(_matching_estimation("openrouter-gateway-multi-upstream"))
    anthropic_entry = next(s for s in estimation["cost_by_source"] if s["provider"] == "anthropic")
    anthropic_entry["models"] = [
        m for m in anthropic_entry["models"] if m["model"] != "claude-3-haiku-20240307"
    ]
    with pytest.raises(AssertionError):
        _assert_artifacts_by_source_projects_into_estimation(generation, estimation)


# --------------------------------------------------------------------------- negative mutations


def test_duplicate_artifacts_by_source_identity_is_rejected() -> None:
    generation = _base_generation()
    generation["artifacts_by_source"].append(copy.deepcopy(generation["artifacts_by_source"][0]))
    assert _generation_ai_findings(generation) != []


def _assert_artifacts_by_source_identity_is_unique(generation: dict) -> None:
    """uniqueItems on artifacts_by_source[] only rejects byte-identical duplicates; two
    entries with the SAME (provider, source_service) pair but different payloads (an
    overlapping identity, not an exact duplicate) need this semantic check instead,
    mirroring the equivalent helper in test_estimation_ai_contracts.py."""
    seen = set()
    for entry in generation["artifacts_by_source"]:
        key = (entry["provider"], entry["source_service"])
        assert key not in seen, f"duplicate or overlapping artifacts_by_source identity: {key}"
        seen.add(key)


def test_positive_fixtures_have_unique_artifacts_by_source_identity() -> None:
    for fixture_path in POSITIVE_FIXTURES:
        _assert_artifacts_by_source_identity_is_unique(_load(fixture_path))


def test_overlapping_artifacts_by_source_identity_is_rejected() -> None:
    """A second entry with the SAME (provider, source_service) pair but different generated
    file content is still a duplicate/overlapping identity, not a legitimate second entry —
    schema-level uniqueItems alone cannot catch this (see helper docstring), so the semantic
    helper above is the lock."""
    generation = _base_generation()
    overlapping = copy.deepcopy(generation["artifacts_by_source"][0])
    overlapping["models"][0]["generated_files"] = ["src/ai/other_client.py"]
    generation["artifacts_by_source"].append(overlapping)
    with pytest.raises(AssertionError):
        _assert_artifacts_by_source_identity_is_unique(generation)


def test_openrouter_as_a_direct_artifacts_by_source_provider_is_rejected() -> None:
    generation = _base_generation()
    generation["artifacts_by_source"][0]["provider"] = "openrouter"
    assert _generation_ai_findings(generation) != []


def test_malformed_artifacts_by_source_entry_missing_models_is_rejected() -> None:
    generation = _base_generation()
    del generation["artifacts_by_source"][0]["models"]
    assert _generation_ai_findings(generation) != []


def test_rollback_plan_mechanism_must_be_feature_flag() -> None:
    generation = _base_generation()
    generation["rollback_plan"]["mechanism"] = "manual_cutover"
    assert _generation_ai_findings(generation) != []


def test_production_readiness_checklist_requires_at_least_five_items() -> None:
    generation = _base_generation()
    generation["production_readiness_checklist"] = generation["production_readiness_checklist"][:2]
    assert _generation_ai_findings(generation) != []


def test_generated_files_entry_requires_at_least_one_file() -> None:
    generation = _base_generation()
    generation["artifacts_by_source"][0]["models"][0]["generated_files"] = []
    assert _generation_ai_findings(generation) != []


# --------------------------------------------------------------------------- vendored byte-identity


def test_vendored_copies_are_byte_identical() -> None:
    """Reuses tools/sync-vendored.py --check (the dedicated CI gate) rather than
    re-implementing filecmp logic inline, matching the project's existing pattern (and
    test_estimation_ai_contracts.py's own choice to leave this check to the dedicated tool)."""
    result = subprocess.run(
        [sys.executable, str(SYNC_VENDORED_PATH), "--check"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
