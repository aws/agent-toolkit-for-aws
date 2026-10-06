"""Contract tests for target AI-only and combined migration modes.

These tests intentionally validate deterministic fixtures rather than runtime routing.
They pin the contract that later implementation PRs must satisfy without claiming that
all scenarios are supported by the current skills.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "ai-migration-matrix"
PLUGIN_ROOT = FIXTURE_ROOT.parent.parent
ARTIFACT_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
ARTIFACT_MANIFEST = PLUGIN_ROOT / "scripts" / "artifact-contracts.json"
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
EXPECTED_CASES = {
    "infra-only-gcp",
    "infra-only-azure",
    "ai-only-gemini",
    "ai-only-openai",
    "ai-only-openrouter",
    "combined-gcp-gemini",
    "combined-azure-openai",
    "combined-gcp-openai",
    "combined-azure-gemini",
    "combined-gcp-openrouter",
    "combined-azure-openrouter",
}
EXPECTED_COMBINATIONS = {
    ("gcp", "gcp_ai", None),
    ("azure", "azure_openai", None),
    ("gcp", "openai", None),
    ("azure", "gcp_ai", None),
    ("gcp", "openai", "llm_router"),
    ("azure", "anthropic", "llm_router"),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _cases() -> dict[str, tuple[Path, dict]]:
    manifest = _load(FIXTURE_ROOT / "expected-matrix.json")
    assert manifest["contract_version"] == "1.0"
    loaded = {}
    for entry in manifest["cases"]:
        path = FIXTURE_ROOT / entry["snapshot"]
        snapshot = _load(path)
        assert snapshot["id"] == entry["id"]
        loaded[entry["id"]] = (path.parent, snapshot)
    return loaded


def test_manifest_has_complete_scenario_coverage() -> None:
    cases = _cases()
    assert set(cases) == EXPECTED_CASES
    assert len(cases) == len(EXPECTED_CASES)
    assert {case["mode"] for _, case in cases.values()} == {
        "infrastructure_only",
        "ai_only",
        "combined",
    }


def test_infrastructure_ai_and_gateway_are_independent_dimensions() -> None:
    cases = _cases()
    for _, snapshot in cases.values():
        dimensions = snapshot["dimensions"]
        assert set(dimensions) == {"infrastructure_source", "ai_provider", "model_families", "gateway_type", "upstream_provider_signals"}
        assert dimensions["infrastructure_source"] in {None, "gcp", "azure"}
        assert dimensions["ai_provider"] in {None, "gcp_ai", "openai", "azure_openai", "anthropic"}
        assert dimensions["gateway_type"] in {None, "llm_router"}
        assert "openrouter" not in {dimensions["infrastructure_source"], dimensions["ai_provider"]}
        if dimensions["gateway_type"] == "llm_router":
            assert dimensions["ai_provider"] is not None
            assert dimensions["model_families"]
            assert dimensions["upstream_provider_signals"]

    combined = {
        (
            snapshot["dimensions"]["infrastructure_source"],
            snapshot["dimensions"]["ai_provider"],
            snapshot["dimensions"]["gateway_type"],
        )
        for _, snapshot in cases.values()
        if snapshot["mode"] == "combined"
    }
    assert combined == EXPECTED_COMBINATIONS


def test_ai_only_origins_require_no_infrastructure() -> None:
    cases = _cases()
    ai_only = [snapshot for _, snapshot in cases.values() if snapshot["mode"] == "ai_only"]
    assert {(case["dimensions"]["ai_provider"], case["dimensions"]["gateway_type"]) for case in ai_only} == {
        ("gcp_ai", None),
        ("openai", None),
        ("openai", "llm_router"),
    }
    openai = cases["ai-only-openai"][1]
    assert openai["dimensions"]["upstream_provider_signals"] == ["openai", "azure_openai"]
    for snapshot in ai_only:
        assert snapshot["dimensions"]["infrastructure_source"] is None
        assert snapshot["outcomes"]["infrastructure"] is None
        assert snapshot["outcomes"]["integration_validation"] is None


def test_each_case_has_one_shared_run_state() -> None:
    for case_dir, snapshot in _cases().values():
        assert snapshot["state"] == ".phase-status.json"
        state = _load(case_dir / snapshot["state"])
        assert state["migration_id"] == snapshot["migration_id"]
        assert state["run_id"] == snapshot["run_id"]
        assert set(state["phases"].values()) == {"completed"}


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
            assert integration == {"verdict": "passed", "artifact": "integration-validation.json"}
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


def test_success_verdict_rejects_any_failed_child(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "combined-gcp-gemini" / "integration-validation.json"
    failed_children = [
        ("track_results", "infrastructure"),
        ("track_results", "ai"),
        ("checks", "iam_and_secrets"),
    ]

    for section, child in failed_children:
        invalid = _load(source)
        invalid[section][child]["verdict"] = "failed"
        case_dir = tmp_path / f"{section}-{child}"
        case_dir.mkdir()
        (case_dir / "integration-validation.json").write_text(json.dumps(invalid))

        result = subprocess.run(
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

        assert result.returncode == 1
        findings = json.loads(result.stdout)["errors"]
        assert any(finding["code"] == "SCHEMA_VIOLATION" for finding in findings)
