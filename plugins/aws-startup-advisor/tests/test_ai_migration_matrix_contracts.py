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


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _manifest() -> dict:
    manifest = _load(FIXTURE_ROOT / "expected-matrix.json")
    assert manifest["contract_version"] == "2.0"
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


def _scenario_validation_findings(snapshot: dict) -> list:
    findings = []
    ARTIFACT_VALIDATOR_MODULE.validate_json_schema(
        _load(SCENARIO_SCHEMA),
        snapshot,
        "",
        "expected-artifacts.json",
        str(SCENARIO_SCHEMA),
        findings,
    )
    return findings


def _validate_scenario(snapshot: dict) -> None:
    assert not _scenario_validation_findings(snapshot)


def _assert_gateway_correspondence(snapshot: dict) -> None:
    dimensions = snapshot["dimensions"]
    providers = {source["provider"] for source in dimensions["ai_sources"]}
    model_families = {
        family
        for source in dimensions["ai_sources"]
        for family in source["model_families"]
    }
    assert dimensions["infrastructure_source"] != "openrouter"
    assert "openrouter" not in providers
    for gateway in dimensions["gateways"]:
        assert set(gateway["upstream_provider_signals"]) <= providers
        assert set(gateway["upstream_model_family_signals"]) <= model_families


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


def _synthetic(
    infrastructure_source: str,
    provider: str,
    source_service: str,
    family: str,
    *,
    openrouter: bool = False,
) -> dict:
    scenario = copy.deepcopy(_cases()["combined-heroku-anthropic"][1])
    scenario["id"] = "synthetic-composition"
    scenario["migration_id"] = "synthetic-composition"
    scenario["dimensions"] = {
        "infrastructure_source": infrastructure_source,
        "ai_sources": [
            {
                "provider": provider,
                "source_service": source_service,
                "model_families": [family],
            }
        ],
        "gateways": [],
    }
    if openrouter:
        scenario["dimensions"]["gateways"] = [
            {
                "product": "openrouter",
                "type": "llm_router",
                "upstream_provider_signals": [provider],
                "upstream_model_family_signals": [family],
            }
        ]
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
        _assert_gateway_correspondence(snapshot)


def test_supported_axes_have_independent_representatives() -> None:
    manifest = _manifest()
    snapshots = [snapshot for _, snapshot in _cases().values()]
    supported = manifest["supported"]

    for infrastructure_source in supported["infrastructure_sources"]:
        assert any(
            snapshot["mode"] == "infrastructure_only"
            and snapshot["dimensions"]["infrastructure_source"] == infrastructure_source
            for snapshot in snapshots
        )
        assert any(
            snapshot["mode"] == "combined"
            and snapshot["dimensions"]["infrastructure_source"] == infrastructure_source
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
    assert direct == {
        "provider": "openai",
        "source_service": "openai_api",
        "model_families": ["gpt"],
    }
    assert azure == {
        "provider": "openai",
        "source_service": "azure_openai",
        "model_families": ["gpt"],
    }


def test_each_case_has_one_shared_run_state_validated_by_repository_tooling() -> None:
    for case_dir, snapshot in _cases().values():
        assert snapshot["state"] == ".phase-status.json"
        state = _load(case_dir / snapshot["state"])
        assert state["migration_id"] == snapshot["migration_id"]
        assert state["run_id"] == snapshot["run_id"]
        assert set(state["phases"].values()) == {"completed"}
        result = _run_artifact_validator(case_dir)
        assert result.returncode == 0, result.stdout + result.stderr


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
    ("infrastructure_source", "provider", "source_service", "family", "openrouter"),
    [
        ("heroku", "google", "vertex_ai", "gemini", False),
        ("heroku", "openai", "openai_api", "gpt", False),
        ("heroku", "openai", "openai_api", "gpt", True),
        ("gcp", "anthropic", "anthropic_api", "claude", False),
        ("azure", "anthropic", "anthropic_api", "claude", False),
    ],
)
def test_non_materialized_compositions_are_schema_valid(
    infrastructure_source: str,
    provider: str,
    source_service: str,
    family: str,
    openrouter: bool,
) -> None:
    scenario = _synthetic(
        infrastructure_source,
        provider,
        source_service,
        family,
        openrouter=openrouter,
    )
    _validate_scenario(scenario)
    _assert_gateway_correspondence(scenario)


def test_future_sources_and_multiple_direct_providers_need_no_schema_enum_change() -> None:
    scenario = _synthetic("future_platform", "future_provider", "future_api", "future_model")
    scenario["dimensions"]["ai_sources"].append(
        {
            "provider": "anthropic",
            "source_service": "anthropic_api",
            "model_families": ["claude"],
        }
    )
    _validate_scenario(scenario)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda scenario: scenario.update(mode="ai_only"),
        lambda scenario: scenario["dimensions"].update(infrastructure_source=None),
        lambda scenario: scenario["dimensions"].update(ai_sources=[]),
        lambda scenario: scenario["outcomes"].update(infrastructure=None),
        lambda scenario: scenario["outcomes"].update(ai=None),
        lambda scenario: scenario["outcomes"].update(integration_validation=None),
        lambda scenario: scenario["dimensions"].update(infrastructure_source="both"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(provider="both"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(provider="openrouter"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(source_service="both"),
        lambda scenario: scenario["dimensions"]["ai_sources"][0].update(model_families=[]),
        lambda scenario: scenario["dimensions"].update(
            gateways=[
                {
                    "product": "both",
                    "type": "llm_router",
                    "upstream_provider_signals": ["anthropic"],
                    "upstream_model_family_signals": ["claude"],
                }
            ]
        ),
    ],
)
def test_schema_rejects_invalid_mode_dimensions_tracks_and_sentinels(mutation) -> None:
    scenario = copy.deepcopy(_cases()["combined-heroku-anthropic"][1])
    mutation(scenario)
    assert _scenario_validation_findings(scenario)


def test_gateway_signals_must_match_retained_ai_sources() -> None:
    scenario = _synthetic("heroku", "openai", "openai_api", "gpt", openrouter=True)
    scenario["dimensions"]["gateways"][0]["upstream_provider_signals"] = ["anthropic"]
    with pytest.raises(AssertionError):
        _assert_gateway_correspondence(scenario)

    scenario = _synthetic("heroku", "openai", "openai_api", "gpt", openrouter=True)
    scenario["dimensions"]["gateways"][0]["upstream_model_family_signals"] = ["claude"]
    with pytest.raises(AssertionError):
        _assert_gateway_correspondence(scenario)


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
