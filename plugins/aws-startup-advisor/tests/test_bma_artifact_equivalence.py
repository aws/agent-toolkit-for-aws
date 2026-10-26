from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "fixtures/bedrock-migration-assessment/semantic-trace-cases.json"
BASELINES = ROOT / "fixtures/bedrock-migration-assessment/selected-base-semantic-projections.json"
BMA_RUNTIME = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"
VALIDATOR = ROOT / "scripts/validate-artifacts.py"
EVIDENCE = Path("/Users/lkleier/Downloads/startups-pr/.agents/tasks/bedrock-migration-assessment-extraction/practical-equivalence-evidence")
LIMITATION = "The equivalence harness carries its own copy of model-mapping, pricing, generated-file, and report-section rules. The Markdown phase files the agent executes do not read those tables. The harness therefore proves the extracted runtime matches the selected base as of this change, but will NOT detect a future edit to the Markdown that changes mappings, prices, or report composition. Reviewers must check such edits by hand until the tables are moved into shared data files consumed by both (tracked as a follow-up to issue #389)."


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace(request: dict[str, object], tmp_path: Path, scenario: str) -> dict[str, object]:
    request_path = tmp_path / f"{scenario}-trace-request.json"
    request_path.write_text(json.dumps(request))
    completed = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "trace", "--request", str(request_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def execute(request: dict[str, object], tmp_path: Path, scenario: str) -> dict[str, object]:
    request_path = tmp_path / f"{scenario}-execute-request.json"
    request_path.write_text(json.dumps(request))
    completed = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "execute", "--request", str(request_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


HTML_DOCUMENT_SECTIONS = {
    "migration-report.html": ("full", [
        "decision-summary", "exec-assumptions", "exec-services", "exec-costs", "exec-timeline",
        "exec-risks", "appendix-services", "appendix-costs", "appendix-steps", "appendix-artifacts",
    ]),
    "decision-report.html": ("decision", [
        "decision-summary", "exec-assumptions", "exec-services", "exec-costs", "exec-timeline",
        "exec-risks", "decision-cta",
    ]),
}


def assembly_for(target: str, contributions: list[dict[str, object]]) -> dict[str, object]:
    """Complete controller-supplied document with one anchor for the contribution section."""
    if target not in HTML_DOCUMENT_SECTIONS:
        return {"phase": "generate", "target": target, "contributions": contributions,
                "document": "<!-- bma-contributions:ai-notes -->\n"}
    report_mode, section_ids = HTML_DOCUMENT_SECTIONS[target]
    sections = "".join(
        f'<section id="{section_id}">\n<!-- bma-contributions:ai-notes -->\n</section>\n'
        if index == 0 else f'<section id="{section_id}">\n</section>\n'
        for index, section_id in enumerate(section_ids)
    )
    document = (
        '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8"><title>Run</title>'
        "<style>body{font-family:sans-serif}</style></head>\n<body>\n<h1>Run</h1>\n"
        '<nav class="toc"><a href="#decision-summary">Summary</a></nav>\n'
        f"{sections}</body>\n</html>\n"
    )
    return {"phase": "generate", "target": target, "contributions": contributions,
            "document": document, "report_mode": report_mode}


def contribution(target: str, request: dict[str, object], scenario: str) -> dict[str, object]:
    evidence = request["source_evidence"]
    assert isinstance(evidence, list) and evidence
    source = evidence[0]
    assert isinstance(source, dict)
    models = source["models"]
    sites = source["call_sites"]
    assert isinstance(models, list) and models and isinstance(sites, list) and sites
    return {
        "id": f"ai.{scenario}", "bucket": 100, "source_order": 0,
        "target": target, "kind": "subsection", "section": "ai-notes",
        "content": {
            "text": f"Validated {scenario} report contribution.", "links": [],
            "traceability": {
                "provider": source["provider"], "source_service": source["source_service"],
                "model": models[0], "call_sites": sites,
            },
        },
    }


def projection(value: dict[str, object]) -> dict[str, object]:
    route = value["route"]
    estimate = value["estimate"]
    generation = value["generation"]
    state = value["state_decision"]
    assert isinstance(route, dict) and isinstance(estimate, dict)
    assert isinstance(generation, dict) and isinstance(state, dict)
    return {
        "route": [
            route["scan_neutral_source"], route["ai_route_active"],
            route["owning_skill"], route["telemetry_owner"],
        ],
        "associations": [
            [row["provider"], row["source_service"], row["gateway"], row["model"]]
            for row in value["associations"]
        ],
        "mappings": [
            [row["source_model"], row["target_model"], row["migration_path"]]
            for row in value["design_mappings"]
        ],
        "costs": [
            estimate["source_monthly"], estimate["target_monthly"],
            estimate["monthly_delta"], estimate["pricing_source"],
        ],
        "generation": [generation["route"], generation["files"], generation["writer"]],
        "state": [state["action"], state["phase"]],
        "consent": [
            [row["status"], row["profile_written"], row["retry_pending"], row["cost"]]
            for row in value["consent"]
        ],
        "writers": [[target, owner] for target, owner in sorted(value["report_writers"].items())],
    }


CASE_VALUE = json.loads(CASES.read_text())
BASELINE_VALUE = json.loads(BASELINES.read_text())


@pytest.mark.parametrize("scenario", sorted(CASE_VALUE["cases"]))
def test_selected_base_semantic_projection_matches_production_trace(
    tmp_path: Path, scenario: str,
) -> None:
    """The equivalence harness carries its own copy of model-mapping, pricing, generated-file, and report-section rules. The Markdown phase files the agent executes do not read those tables. The harness therefore proves the extracted runtime matches the selected base as of this change, but will NOT detect a future edit to the Markdown that changes mappings, prices, or report composition. Reviewers must check such edits by hand until the tables are moved into shared data files consumed by both (tracked as a follow-up to issue #389)."""
    request = CASE_VALUE["cases"][scenario]
    serialized = json.dumps(request, sort_keys=True)
    forbidden = (
        "selected_base_projection", "design_mappings", "target_monthly",
        "pricing_source", "report_targets", '"generation"', '"status"',
    )
    assert not any(value in serialized for value in forbidden)
    assert "<html" not in serialized and "# Migration Guide" not in serialized
    actual = projection(trace(request, tmp_path, scenario))
    assert actual == BASELINE_VALUE["projections"][scenario]


def test_trace_preserves_openrouter_cardinality_null_zero_and_writer_boundary(tmp_path: Path) -> None:
    openrouter = projection(trace(
        CASE_VALUE["cases"]["openrouter-multi-upstream"],
        tmp_path,
        "openrouter-cardinality",
    ))
    assert len(openrouter["associations"]) == 3
    assert openrouter["associations"][0][2] == "openrouter"
    assert openrouter["associations"][1][2] == "openrouter"
    # claude-3-5-sonnet has no Active target now, so the target and delta are unknown, not zero.
    assert openrouter["costs"][1:3] == [None, None]

    gemini = projection(trace(
        CASE_VALUE["cases"]["gemini-application"],
        tmp_path,
        "gemini-zero",
    ))
    # Observed source cost stays 0. gemini-2.5-pro is not in the registry (source unverified), so its
    # target keeps the name amazon.nova-pro-v1:0 but gets no price.
    assert gemini["costs"] == [0, None, None, "unavailable"]

    delegated = projection(trace(
        CASE_VALUE["cases"]["gcp-combined-vertex"],
        tmp_path,
        "delegated-writers",
    ))
    assert all(owner == "gcp-to-aws" for _, owner in delegated["writers"])


def test_source_below_threshold_and_pure_infrastructure_are_distinct(tmp_path: Path) -> None:
    below = projection(trace(
        CASE_VALUE["cases"]["source-containing-below-threshold"],
        tmp_path,
        "below-threshold",
    ))
    pure = projection(trace(
        CASE_VALUE["cases"]["pure-infrastructure"],
        tmp_path,
        "pure-infrastructure",
    ))
    assert below["route"][:2] == [True, False]
    assert pure["route"][:2] == [False, False]
    assert below["generation"][2] is None and pure["generation"][2] is None


def test_trace_rejects_unknown_source_model(tmp_path: Path) -> None:
    request = json.loads(json.dumps(CASE_VALUE["cases"]["direct-openai"]))
    request["source_evidence"][0]["models"][0] = "fabricated-model"
    request_path = tmp_path / "invalid-trace.json"
    request_path.write_text(json.dumps(request))
    completed = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "trace", "--request", str(request_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert "trace_source_invalid" in completed.stderr


def validator(run: Path, skill: str) -> tuple[int, list[tuple[str, str]]]:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--run-dir", str(run), "--skill", skill,
         "--no-baseline", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    report = json.loads(completed.stdout)
    return completed.returncode, [(item["code"], item["path"]) for item in report["errors"]]


def test_direct_and_delegated_validator_reject_same_invalid_state(tmp_path: Path) -> None:
    state = {
        "migration_id": "0101-0000", "last_updated": "2026-01-01T00:00:00Z",
        "phases": {"discover": "completed"}, "unexpected": True,
    }
    findings = []
    for skill in ("bedrock-migration-assessment", "gcp-to-aws"):
        run = tmp_path / skill
        run.mkdir()
        (run / ".phase-status.json").write_text(json.dumps(state))
        findings.append(validator(run, skill))
    assert findings[0] == findings[1]
    assert findings[0][0] == 1
    assert ("SCHEMA_VIOLATION", "unexpected") in findings[0][1]


@pytest.mark.skipif(
    os.environ.get("BMA_WRITE_EQUIVALENCE_EVIDENCE") != "1",
    reason="opt-in evidence capture",
)
def test_capture_selected_base_to_extracted_evidence(tmp_path: Path) -> None:
    scenarios = []
    for scenario, request in sorted(CASE_VALUE["cases"].items()):
        actual_trace = trace(request, tmp_path, scenario)
        actual_projection = projection(actual_trace)
        selected_base_projection = BASELINE_VALUE["projections"][scenario]
        assert actual_projection == selected_base_projection
        scenarios.append({
            "scenario": scenario,
            "raw_input_sha256": hashlib.sha256(
                json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "selected_base_projection": selected_base_projection,
            "post_extraction_projection": actual_projection,
            "semantic_equal": True,
            "production_trace": actual_trace,
        })
    evidence = {
        "schema_version": 5,
        "status": "PASS",
        "selected_base": CASE_VALUE["selected_base"],
        "input_fixture": "plugins/aws-startup-advisor/fixtures/bedrock-migration-assessment/semantic-trace-cases.json",
        "input_fixture_sha256": digest(CASES),
        "selected_base_fixture": "plugins/aws-startup-advisor/fixtures/bedrock-migration-assessment/selected-base-semantic-projections.json",
        "selected_base_fixture_sha256": digest(BASELINES),
        "selected_base_provenance": BASELINE_VALUE["provenance"],
        "production_entrypoint": "skills/bedrock-migration-assessment/scripts/bma-runtime.py trace",
        "input_boundary": "source/usage observations, durable state, and user decisions only; mappings, target estimates, generation outputs, consent outcomes, and report targets are production-derived",
        "scenarios": scenarios,
        "supersedes": [
            "targeted proved:true",
            "supplemental proved:true/bootstrapProof:true/gateBCompletenessProof:true",
            "schema-version-3 supplied-output serialization evidence",
        ],
        "limitation": LIMITATION,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "deterministic-equivalence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )

    operations = []
    artifact_comparisons = []
    for scenario, request in sorted(CASE_VALUE["cases"].items()):
        actual_trace = trace(request, tmp_path, f"{scenario}-audit")
        mode = request["mode"]
        run = tmp_path / f"{scenario}-run"
        run.mkdir()
        writes = []
        writers = actual_trace["writers"]
        assert isinstance(writers, dict)
        for path, owner in sorted(writers.items()):
            payload = {"schema_version": 1, "scenario": scenario, "artifact": path}
            writes.append({
                "phase": "generate", "path": path, "payload": payload,
                "logical_owner": owner,
            })
        generation = actual_trace["generation"]
        assert isinstance(generation, dict)
        for path in generation["files"]:
            writes.append({
                "phase": "generate", "path": path,
                "payload": f"validated generated file for {scenario}\n",
                "logical_owner": "bedrock-migration-assessment",
            })
        report_writers = actual_trace["report_writers"]
        assert isinstance(report_writers, dict)
        assemblies = [
            assembly_for(target, [contribution(target, request, scenario)])
            for target in sorted(report_writers)
        ]
        result = execute({
            "schema_version": 1, "mode": mode, "scenario": scenario,
            "run_dir": str(run), "state": request["state"],
            "execute_requested": request["user_decisions"]["execute_requested"],
            "consent": [], "clarify_result": None, "writes": writes,
            "assemblies": assemblies,
        }, tmp_path, f"{scenario}-audit")
        scenario_operations = result["operations"]
        assert isinstance(scenario_operations, list)
        operations.extend(scenario_operations)
        for operation in scenario_operations:
            path = run / operation["path"]
            actual_sha = digest(path)
            assert actual_sha == operation["sha256"]
            artifact_comparisons.append({
                "scenario": scenario, "path": operation["path"],
                "logical_owner": operation["logical_owner"],
                "selected_base_contract": "exact path and writer from selected-base semantic projection",
                "expected_sha256": operation["sha256"], "actual_sha256": actual_sha,
                "equal": True,
            })
    identities = [(row["scenario"], row["path"]) for row in operations]
    assert len(identities) == len(set(identities))
    write_audit = {
        "schema_version": 5, "status": "PASS", "producer": "bma-runtime.py execute",
        "production_entrypoint": "skills/bedrock-migration-assessment/scripts/bma-runtime.py execute",
        "input_fixture_sha256": digest(CASES),
        "selected_base_fixture_sha256": digest(BASELINES),
        "assertions": {
            "operation_count": len(operations), "artifact_comparison_count": len(artifact_comparisons),
            "duplicate_final_writes": 0, "last_write_wins_paths": 0,
            "all_artifacts_equal": all(row["equal"] for row in artifact_comparisons),
        },
        "operations": operations, "artifact_comparisons": artifact_comparisons,
        "limitation": LIMITATION,
    }
    (EVIDENCE / "write-audit.json").write_text(
        json.dumps(write_audit, indent=2, sort_keys=True) + "\n"
    )
