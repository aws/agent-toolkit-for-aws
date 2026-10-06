"""Contract tests for composable target migration scenarios.

These tests intentionally validate deterministic fixtures rather than runtime routing.
They pin contracts that later implementation PRs must satisfy without claiming current
skill support or treating the representative fixtures as a Cartesian support boundary.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "ai-migration-matrix"
PLUGIN_ROOT = FIXTURE_ROOT.parent.parent
ARTIFACT_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
ARTIFACT_MANIFEST = PLUGIN_ROOT / "scripts" / "artifact-contracts.json"
SCENARIO_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "ai-migration-scenario.schema.json"
INTEGRATION_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "integration-validation.schema.json"
PHASE_STATUS_SCHEMA = PLUGIN_ROOT / "skills" / "shared" / "state" / "phase-status.schema.json"
_VALIDATOR_SPEC = importlib.util.spec_from_file_location("artifact_validator", ARTIFACT_VALIDATOR)
assert _VALIDATOR_SPEC and _VALIDATOR_SPEC.loader
ARTIFACT_VALIDATOR_MODULE = importlib.util.module_from_spec(_VALIDATOR_SPEC)
sys.modules[_VALIDATOR_SPEC.name] = ARTIFACT_VALIDATOR_MODULE
_VALIDATOR_SPEC.loader.exec_module(ARTIFACT_VALIDATOR_MODULE)
INFRA_ARTIFACTS = {
    "aws-design.json",
    "estimation-infra.json",
    "generation-infra.json",
    "validation-report.json",
}
AI_ARTIFACTS = {
    "ai-workload-profile.json",
    "aws-design-ai.json",
    "estimation-ai.json",
    "generation-ai.json",
}
INTEGRATION_CHECKS = {
    "networking",
    "iam_and_secrets",
    "data_flow",
    "observability",
    "deployment_order",
    "cutover",
    "rollback",
    "cost_estimate",
    "validation_dependencies",
}
REQUIRED_ADDITIONS = {
    "infra-only-heroku",
    "ai-only-anthropic",
    "combined-heroku-anthropic",
}
MODELS = {
    "google": "gemini-1.5-pro",
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-20240620",
    "future_provider": "future-model-v1",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _manifest() -> dict:
    manifest = _load(FIXTURE_ROOT / "expected-matrix.json")
    assert manifest["contract_version"] == "3.0"
    return manifest


def _cases() -> dict[str, tuple[Path, dict]]:
    loaded = {}
    for entry in _manifest()["cases"]:
        path = FIXTURE_ROOT / entry["snapshot"]
        snapshot = _load(path)
        assert snapshot["id"] == entry["id"]
        assert entry["id"] not in loaded
        loaded[entry["id"]] = (path.parent, snapshot)
    return loaded


def _schema_findings(schema_path: Path, instance: dict, name: str) -> list:
    findings = []
    ARTIFACT_VALIDATOR_MODULE.validate_json_schema(
        _load(schema_path),
        instance,
        "",
        name,
        str(schema_path),
        findings,
    )
    return findings


def _scenario_validation_findings(snapshot: dict) -> list:
    return _schema_findings(SCENARIO_SCHEMA, snapshot, "expected-artifacts.json")


def _validate_scenario(snapshot: dict) -> None:
    assert not _scenario_validation_findings(snapshot)


def _assert_scenario_semantics(snapshot: dict) -> None:
    dimensions = snapshot["dimensions"]
    assert dimensions["infrastructure_source"] != "openrouter"

    sources = {}
    for source in dimensions["ai_sources"]:
        key = (source["provider"], source["source_service"])
        assert key not in sources, f"duplicate or overlapping AI source: {key}"
        assert source["provider"] != "openrouter"
        sources[key] = source

    for gateway in dimensions["gateways"]:
        upstream_keys = set()
        for upstream in gateway["upstreams"]:
            key = (upstream["provider"], upstream.get("source_service"))
            assert key not in upstream_keys, (
                f"duplicate or overlapping gateway upstream: {key}"
            )
            upstream_keys.add(key)

            if "source_service" in upstream:
                source = sources.get((upstream["provider"], upstream["source_service"]))
                assert source is not None, f"unmatched gateway upstream: {key}"
            else:
                candidates = [
                    source
                    for (provider, _), source in sources.items()
                    if provider == upstream["provider"]
                ]
                assert len(candidates) == 1, (
                    f"service-less upstream must match one source: {upstream['provider']}"
                )
                source = candidates[0]

            families = set(source["model_families"])
            models = set(source["models"])
            seen_families = set()
            for family in upstream["model_families"]:
                assert family["family"] not in seen_families, (
                    f"duplicate or overlapping upstream family: {family['family']}"
                )
                seen_families.add(family["family"])
                assert family["family"] in families, (
                    f"wrongly paired upstream family: {family['family']}"
                )
                assert set(family["models"]) <= models, (
                    f"wrongly paired upstream models: {family['models']}"
                )


def _run_artifact_validator(case_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ARTIFACT_VALIDATOR),
            "--run-dir",
            str(case_dir),
            "--skill",
            "gcp-to-aws",
            "--manifest",
            str(ARTIFACT_MANIFEST),
            "--no-baseline",
            "--json",
        ],
        capture_output=True,
        check=False,
        text=True,
    )


def _source(provider: str, source_service: str, family: str, *models: str) -> dict:
    return {
        "provider": provider,
        "source_service": source_service,
        "model_families": [family],
        "model_evidence": "observed",
        "models": list(models),
    }


def _upstream(provider: str, source_service: str, family: str, *models: str) -> dict:
    return {
        "provider": provider,
        "source_service": source_service,
        "model_families": [
            {
                "family": family,
                "model_evidence": "observed",
                "models": list(models),
            }
        ],
    }


def _gateway(*upstreams: dict) -> dict:
    return {
        "product": "openrouter",
        "type": "llm_router",
        "upstream_evidence": "observed",
        "upstreams": list(upstreams),
    }


def _synthetic(
    infrastructure_source: str,
    provider: str,
    source_service: str,
    family: str,
    model: str,
    *,
    openrouter: bool = False,
) -> dict:
    scenario = copy.deepcopy(_cases()["combined-heroku-anthropic"][1])
    scenario["id"] = "synthetic-composition"
    scenario["migration_id"] = "synthetic-composition"
    source = _source(provider, source_service, family, model)
    scenario["dimensions"] = {
        "infrastructure_source": infrastructure_source,
        "ai_sources": [source],
        "gateways": [],
    }
    if openrouter:
        scenario["dimensions"]["gateways"] = [
            _gateway(_upstream(provider, source_service, family, model))
        ]
    return scenario


def _multi_openrouter_scenario(infrastructure_source: str = "heroku") -> dict:
    scenario = copy.deepcopy(_cases()["combined-heroku-anthropic"][1])
    scenario["id"] = "multi-cardinality-openrouter"
    scenario["migration_id"] = "multi-cardinality-openrouter"
    associations = [
        (
            "anthropic",
            "anthropic_api",
            "claude",
            ["claude-3-5-sonnet-20240620", "claude-3-haiku-20240307"],
        ),
        ("google", "vertex_ai", "gemini", ["gemini-1.5-pro"]),
        ("openai", "openai_api", "gpt", ["gpt-4o"]),
        ("openai", "azure_openai", "gpt", ["gpt-4o"]),
        ("future_provider", "future_api", "future_family", ["future-model-v1"]),
    ]
    scenario["dimensions"] = {
        "infrastructure_source": infrastructure_source,
        "ai_sources": [
            _source(provider, service, family, *models)
            for provider, service, family, models in associations
        ],
        "gateways": [
            _gateway(
                *[
                    _upstream(provider, service, family, *models)
                    for provider, service, family, models in associations
                ]
            )
        ],
    }
    return scenario


def test_manifest_has_fourteen_representative_scenarios_and_all_modes() -> None:
    cases = _cases()
    assert len(cases) == 14
    assert REQUIRED_ADDITIONS <= set(cases)
    assert {case["mode"] for _, case in cases.values()} == {
        "infrastructure_only",
        "ai_only",
        "combined",
    }


def test_every_snapshot_validates_against_scenario_schema() -> None:
    schema = _load(SCENARIO_SCHEMA)
    assert ARTIFACT_VALIDATOR_MODULE.unsupported_keywords(schema) == []
    for _, snapshot in _cases().values():
        _validate_scenario(snapshot)
        _assert_scenario_semantics(snapshot)


def test_supported_axes_have_independent_representatives() -> None:
    manifest = _manifest()
    snapshots = [snapshot for _, snapshot in _cases().values()]
    supported = manifest["supported"]

    for infrastructure_source in supported["infrastructure_sources"]:
        assert any(
            snapshot["mode"] == "infrastructure_only"
            and snapshot["dimensions"]["infrastructure_source"]
            == infrastructure_source
            for snapshot in snapshots
        )
        assert any(
            snapshot["mode"] == "combined"
            and snapshot["dimensions"]["infrastructure_source"]
            == infrastructure_source
            for snapshot in snapshots
        )

    for provider in supported["direct_ai_providers"]:
        assert any(
            snapshot["mode"] == "ai_only"
            and not snapshot["dimensions"]["gateways"]
            and provider
            in {source["provider"] for source in snapshot["dimensions"]["ai_sources"]}
            for snapshot in snapshots
        )
        assert any(
            snapshot["mode"] == "combined"
            and provider
            in {source["provider"] for source in snapshot["dimensions"]["ai_sources"]}
            for snapshot in snapshots
        )

    for product in supported["gateway_products"]:
        assert any(
            snapshot["mode"] == "ai_only"
            and product
            in {gateway["product"] for gateway in snapshot["dimensions"]["gateways"]}
            for snapshot in snapshots
        )
        assert any(
            snapshot["mode"] == "combined"
            and product
            in {gateway["product"] for gateway in snapshot["dimensions"]["gateways"]}
            for snapshot in snapshots
        )


def test_openai_provider_preserves_direct_and_azure_endpoint_provenance() -> None:
    cases = _cases()
    direct = cases["combined-gcp-openai"][1]["dimensions"]["ai_sources"][0]
    azure = cases["combined-azure-openai"][1]["dimensions"]["ai_sources"][0]
    assert direct == _source("openai", "openai_api", "gpt", "gpt-4o")
    assert azure == _source("openai", "azure_openai", "gpt", "gpt-4o")


def test_each_case_shared_artifacts_validate_directly() -> None:
    for case_dir, snapshot in _cases().values():
        assert snapshot["state"] == ".phase-status.json"
        state = _load(case_dir / snapshot["state"])
        assert state["migration_id"] == snapshot["migration_id"]
        assert state["run_id"] == snapshot["run_id"]
        assert set(state["phases"].values()) == {"completed"}
        assert not _schema_findings(
            PHASE_STATUS_SCHEMA, state, ".phase-status.json"
        )

        integration_path = case_dir / "integration-validation.json"
        if integration_path.is_file():
            assert not _schema_findings(
                INTEGRATION_SCHEMA,
                _load(integration_path),
                "integration-validation.json",
            )


def test_required_artifacts_and_verdicts_match_each_mode() -> None:
    for case_dir, snapshot in _cases().values():
        outcomes = snapshot["outcomes"]
        infra = outcomes["infrastructure"]
        ai = outcomes["ai"]
        integration = outcomes["integration_validation"]

        if snapshot["mode"] in {"infrastructure_only", "combined"}:
            assert infra == {"verdict": "passed", "artifacts": sorted(INFRA_ARTIFACTS)}
        else:
            assert infra is None
        if snapshot["mode"] in {"ai_only", "combined"}:
            assert ai == {"verdict": "passed", "artifacts": sorted(AI_ARTIFACTS)}
        else:
            assert ai is None

        integration_path = case_dir / "integration-validation.json"
        if snapshot["mode"] == "combined":
            assert integration == {
                "verdict": "passed",
                "artifact": "integration-validation.json",
            }
            assert integration_path.is_file()
        else:
            assert integration is None
            assert not integration_path.exists()


def test_combined_validation_references_both_tracks_and_all_categories() -> None:
    for case_dir, snapshot in _cases().values():
        if snapshot["mode"] != "combined":
            continue
        validation = _load(case_dir / "integration-validation.json")
        assert validation["schema_version"] == "1.0"
        assert validation["run_id"] == snapshot["run_id"]
        assert validation["verdict"] == "passed"
        assert set(validation["track_results"]) == {"infrastructure", "ai"}
        assert set(validation["track_results"]["infrastructure"]["references"]) == INFRA_ARTIFACTS
        assert set(validation["track_results"]["ai"]["references"]) == AI_ARTIFACTS
        assert set(validation["checks"]) == INTEGRATION_CHECKS
        for result in [*validation["track_results"].values(), *validation["checks"].values()]:
            assert result["verdict"] == "passed"
            assert result["references"]


@pytest.mark.parametrize(
    ("provider", "source_service", "family", "model"),
    [
        ("google", "vertex_ai", "gemini", "gemini-1.5-pro"),
        ("openai", "openai_api", "gpt", "gpt-4o"),
        ("anthropic", "anthropic_api", "claude", "claude-3-5-sonnet-20240620"),
    ],
)
def test_heroku_composes_with_each_direct_ai_provider(
    provider: str, source_service: str, family: str, model: str
) -> None:
    scenario = _synthetic("heroku", provider, source_service, family, model)
    _validate_scenario(scenario)
    _assert_scenario_semantics(scenario)


@pytest.mark.parametrize("infrastructure_source", ["gcp", "azure", "heroku"])
def test_openrouter_dimensions_compose_with_each_infrastructure_source(
    infrastructure_source: str,
) -> None:
    scenario = _multi_openrouter_scenario(infrastructure_source)
    assert isinstance(scenario["dimensions"]["infrastructure_source"], str)
    _validate_scenario(scenario)
    _assert_scenario_semantics(scenario)


def test_multi_cardinality_openrouter_preserves_exact_associations() -> None:
    scenario = _multi_openrouter_scenario()
    dimensions = scenario["dimensions"]
    sources = dimensions["ai_sources"]
    upstreams = dimensions["gateways"][0]["upstreams"]

    assert len({source["provider"] for source in sources}) > 1
    assert len({family for source in sources for family in source["model_families"]}) > 1
    assert len({model for source in sources for model in source["models"]}) > 1
    claude = next(
        family
        for upstream in upstreams
        if upstream["provider"] == "anthropic"
        for family in upstream["model_families"]
        if family["family"] == "claude"
    )
    assert claude["models"] == [
        "claude-3-5-sonnet-20240620",
        "claude-3-haiku-20240307",
    ]
    assert {
        (upstream["provider"], upstream["source_service"]): {
            family["family"]: family["models"]
            for family in upstream["model_families"]
        }
        for upstream in upstreams
    } == {
        (source["provider"], source["source_service"]): {
            source["model_families"][0]: source["models"]
        }
        for source in sources
    }
    assert [
        source["source_service"]
        for source in sources
        if source["provider"] == "openai"
    ] == ["openai_api", "azure_openai"]
    _validate_scenario(scenario)
    _assert_scenario_semantics(scenario)


def test_future_structural_identity_does_not_claim_runtime_support() -> None:
    scenario = _synthetic(
        "future_platform",
        "future_provider",
        "future_api",
        "future_family",
        "future-model-v1",
    )
    scenario["dimensions"]["ai_sources"].append(
        _source(
            "anthropic",
            "anthropic_api",
            "claude",
            "claude-3-5-sonnet-20240620",
        )
    )
    _validate_scenario(scenario)
    _assert_scenario_semantics(scenario)
    assert "future_provider" not in _manifest()["supported"]["direct_ai_providers"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda scenario: scenario["dimensions"]["ai_sources"].append(
            copy.deepcopy(scenario["dimensions"]["ai_sources"][0])
        ),
        lambda scenario: scenario["dimensions"]["ai_sources"].append(
            _source("anthropic", "anthropic_api", "claude", "claude-3-haiku-20240307")
        ),
    ],
)
def test_duplicate_or_overlapping_ai_sources_are_rejected(mutation) -> None:
    scenario = _synthetic(
        "heroku",
        "anthropic",
        "anthropic_api",
        "claude",
        "claude-3-5-sonnet-20240620",
    )
    mutation(scenario)
    if not _scenario_validation_findings(scenario):
        with pytest.raises(AssertionError):
            _assert_scenario_semantics(scenario)
    else:
        assert _scenario_validation_findings(scenario)


@pytest.mark.parametrize("overlap", ["exact", "split", "ambiguous-service"])
def test_duplicate_or_overlapping_gateway_upstreams_are_rejected(overlap: str) -> None:
    scenario = _multi_openrouter_scenario()
    gateway = scenario["dimensions"]["gateways"][0]
    if overlap == "exact":
        gateway["upstreams"].append(copy.deepcopy(gateway["upstreams"][0]))
    elif overlap == "split":
        gateway["upstreams"].append(
            _upstream(
                "anthropic",
                "anthropic_api",
                "claude",
                "claude-3-haiku-20240307",
            )
        )
    else:
        gateway["upstreams"].append(
            {
                "provider": "openai",
                "model_families": [
                    {
                        "family": "gpt",
                        "model_evidence": "observed",
                        "models": ["gpt-4o"],
                    }
                ],
            }
        )
    if not _scenario_validation_findings(scenario):
        with pytest.raises(AssertionError):
            _assert_scenario_semantics(scenario)
    else:
        assert _scenario_validation_findings(scenario)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda upstream: upstream.update(provider="google"),
        lambda upstream: upstream.update(source_service="azure_openai"),
        lambda upstream: upstream["model_families"][0].update(family="claude"),
        lambda upstream: upstream["model_families"][0].update(
            models=["claude-3-5-sonnet-20240620"]
        ),
    ],
)
def test_gateway_upstreams_must_match_retained_ai_sources_exactly(mutation) -> None:
    scenario = _synthetic(
        "heroku", "openai", "openai_api", "gpt", "gpt-4o", openrouter=True
    )
    mutation(scenario["dimensions"]["gateways"][0]["upstreams"][0])
    with pytest.raises(AssertionError):
        _assert_scenario_semantics(scenario)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda scenario: scenario.update(mode="ai_only"),
        lambda scenario: scenario["dimensions"].update(infrastructure_source=None),
        lambda scenario: scenario["dimensions"].update(infrastructure_source=["heroku", "gcp"]),
        lambda scenario: (
            scenario.update(mode="ai_only"),
            scenario["dimensions"].update(
                infrastructure_source=None, ai_sources=[], gateways=[]
            ),
            scenario["outcomes"].update(
                infrastructure=None, ai=None, integration_validation=None
            ),
        ),
        lambda scenario: scenario["dimensions"].update(ai_sources=[]),
        lambda scenario: scenario["outcomes"].update(infrastructure=None),
        lambda scenario: scenario["outcomes"].update(ai=None),
        lambda scenario: scenario["outcomes"].update(integration_validation=None),
        lambda scenario: scenario["dimensions"].update(infrastructure_source="both"),
        lambda scenario: scenario["dimensions"].update(infrastructure_source="openrouter"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(provider="both"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(provider="openrouter"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(source_service="both"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(model_families=[]),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(provider="OpenAI"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(source_service="openai-api"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(model_families=["GPT"]),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(models=["GPT-4o"]),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(models=["unknown"]),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(models=[]),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(
            model_evidence="not_observed"
        ),
        lambda scenario: scenario["dimensions"].update(
            gateways=[
                {
                    "product": "both",
                    "type": "llm_router",
                    "upstream_evidence": "observed",
                    "upstreams": [
                        _upstream("anthropic", "anthropic_api", "claude", MODELS["anthropic"])
                    ],
                }
            ]
        ),
        lambda scenario: scenario["dimensions"].update(
            gateways=[
                {
                    "product": "openrouter",
                    "type": "llm_router",
                    "upstream_evidence": "observed",
                    "upstreams": [],
                }
            ]
        ),
        lambda scenario: scenario["dimensions"].update(
            gateways=[
                {
                    "product": "openrouter",
                    "type": "llm_router",
                    "upstream_evidence": "unresolved",
                    "upstreams": [
                        _upstream("anthropic", "anthropic_api", "claude", MODELS["anthropic"])
                    ],
                }
            ]
        ),
    ],
)
def test_schema_rejects_invalid_modes_ids_cardinality_and_sentinels(mutation) -> None:
    scenario = copy.deepcopy(_cases()["combined-heroku-anthropic"][1])
    mutation(scenario)
    assert _scenario_validation_findings(scenario)


def test_unresolved_gateway_upstreams_are_explicit_and_unambiguous() -> None:
    scenario = _synthetic(
        "heroku", "openai", "openai_api", "gpt", "gpt-4o", openrouter=True
    )
    scenario["dimensions"]["gateways"] = [
        {
            "product": "openrouter",
            "type": "llm_router",
            "upstream_evidence": "unresolved",
            "upstreams": [],
        }
    ]
    _validate_scenario(scenario)
    _assert_scenario_semantics(scenario)

    for evidence in ["observed", None]:
        invalid = copy.deepcopy(scenario)
        if evidence is None:
            del invalid["dimensions"]["gateways"][0]["upstream_evidence"]
        else:
            invalid["dimensions"]["gateways"][0]["upstream_evidence"] = evidence
        assert _scenario_validation_findings(invalid)


def test_integration_validation_accepts_uppercase_and_lowercase_run_ids(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "combined-gcp-gemini" / "integration-validation.json"
    run_ids = {
        "uppercase": ("ABCDEF12-ABCD-4ABC-8DEF-ABCDEF123456", 0),
        "lowercase": ("abcdef12-abcd-4abc-8def-abcdef123456", 0),
        "malformed": ("not-a-uuid", 1),
    }

    for label, (run_id, expected_returncode) in run_ids.items():
        validation = _load(source)
        validation["run_id"] = run_id
        case_dir = tmp_path / label
        case_dir.mkdir()
        (case_dir / "integration-validation.json").write_text(json.dumps(validation))

        result = _run_artifact_validator(case_dir)
        assert result.returncode == expected_returncode
        findings = json.loads(result.stdout)["errors"]
        if expected_returncode == 0:
            assert findings == []
        else:
            assert any(finding["code"] == "SCHEMA_VIOLATION" for finding in findings)


@pytest.mark.parametrize(
    ("section", "child"),
    [
        ("track_results", "infrastructure"),
        ("track_results", "ai"),
        ("checks", "iam_and_secrets"),
    ],
)
def test_success_verdict_rejects_any_failed_child(
    tmp_path: Path, section: str, child: str
) -> None:
    invalid = _load(FIXTURE_ROOT / "combined-gcp-gemini" / "integration-validation.json")
    invalid[section][child]["verdict"] = "failed"
    case_dir = tmp_path / f"{section}-{child}"
    case_dir.mkdir()
    (case_dir / "integration-validation.json").write_text(json.dumps(invalid))

    result = _run_artifact_validator(case_dir)
    assert result.returncode == 1
    findings = json.loads(result.stdout)["errors"]
    assert any(finding["code"] == "SCHEMA_VIOLATION" for finding in findings)


def test_success_verdict_rejects_empty_references(tmp_path: Path) -> None:
    invalid = _load(FIXTURE_ROOT / "combined-gcp-gemini" / "integration-validation.json")
    invalid["checks"]["networking"]["references"] = []
    case_dir = tmp_path / "empty-references"
    case_dir.mkdir()
    (case_dir / "integration-validation.json").write_text(json.dumps(invalid))

    result = _run_artifact_validator(case_dir)
    assert result.returncode == 1
    findings = json.loads(result.stdout)["errors"]
    assert any(finding["code"] == "SCHEMA_VIOLATION" for finding in findings)
