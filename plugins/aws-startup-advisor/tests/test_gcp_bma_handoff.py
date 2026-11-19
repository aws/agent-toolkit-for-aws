"""Tests for gcp-to-aws scripts/bma-handoff.py: the four sibling routes, the profile conversion, and accepting a bedrock-migration-assessment run."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
FIXTURES = PLUGIN_ROOT / "fixtures"
SCRIPT = SKILLS / "gcp-to-aws" / "scripts" / "bma-handoff.py"
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"
BMA_FILES = ("ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json", "openai-usage-profile.json")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A plugin layout with gcp-to-aws's script beside a real copy of bedrock-migration-assessment."""
    root = tmp_path / "skills"
    (root / "gcp-to-aws" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "gcp-to-aws" / "scripts" / SCRIPT.name)
    shutil.copytree(SKILLS / "bedrock-migration-assessment", root / "bedrock-migration-assessment",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _cli(tree: Path, *args: str, cwd: Path | None = None) -> tuple[int, dict]:
    script = tree / "gcp-to-aws" / "scripts" / SCRIPT.name
    out = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, cwd=cwd or tree, timeout=120)
    return out.returncode, json.loads(out.stdout)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy(models: list[dict], **extra) -> dict:
    return {"metadata": {"profile_source": "merged"}, "summary": {"ai_source": "gemini"}, "models": models,
            "integration": {"pattern": "direct_sdk"}, "infrastructure": [], "workloads": [], **extra}


def _model(model_id: str, service: str, *sources: str) -> dict:
    return {"model_id": model_id, "service": service, "detected_via": list(sources),
            "evidence": [{"source": s, "file": "x"} for s in sources], "capabilities_used": ["text_generation"], "usage_context": "chat"}


def _gcp_run(tmp_path: Path, infra: bool, profile: dict | None = None) -> Path:
    run = tmp_path / ".migration" / "1119-2100"
    run.mkdir(parents=True)
    (run / "ai-workload-profile.json").write_text(json.dumps(profile or _legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "code")])))
    if infra:
        (run / "gcp-resource-inventory.json").write_text(json.dumps({"resources": [{"type": "google_cloud_run_v2_service"}]}))
    return run


def _bma_run(tmp_path: Path, phases: dict | None = None) -> Path:
    run = tmp_path / ".migration" / "bma-1119-2101"
    run.mkdir(parents=True)
    for name in BMA_FILES:
        shutil.copy(FIXTURES / "bma-estimate-measured" / name, run / name)
    status = {"migration_id": run.name, "run_id": RUN_ID, "last_updated": "2026-11-19T21:00:00Z", "initiated_by": "GCP_TO_AWS",
              "phases": phases or dict.fromkeys(("discover", "clarify", "design", "estimate"), "completed")}
    (run / ".phase-status.json").write_text(json.dumps(status))
    return run


def _legacy_dir(tmp_path: Path) -> Path:
    run = tmp_path / ".migration" / "1119-2100"
    run.mkdir(parents=True, exist_ok=True)
    return run


def _converted(gcp: Path, bma: Path) -> None:
    """Stand in for convert: the assessment run already holds the neutral profile this run handed over."""
    shutil.copy(bma / "ai-workload-profile.json", gcp / "ai-workload-profile.neutral.json")
    (gcp / "ai-handoff.json").write_text(json.dumps({
        "profile_digest": "sha256:" + _sha(gcp / "ai-workload-profile.json"), "status": "converted",
        "assessment_profile_digest": "sha256:" + _sha(bma / "ai-workload-profile.json"), "artifacts": {}}))


def _open(tree: Path, gcp: Path, bma: Path, stop_after: str, convert: bool = True) -> tuple[int, dict]:
    if convert:
        _converted(gcp, bma)
    return _cli(tree, "host-answers", str(gcp), str(bma), "--stop-after", stop_after)


# --------------------------------------------------------------------------- probe

def test_probe_finds_the_installed_sibling(tree: Path) -> None:
    code, out = _cli(tree, "probe")
    assert code == 0 and out["status"] == "present"
    assert Path(out["bma_base"]).resolve() == (tree / "bedrock-migration-assessment").resolve()


def test_probe_runs_from_the_users_project_directory(tree: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assert _cli(tree, "probe", cwd=project)[1]["status"] == "present"


def test_probe_reports_a_missing_sibling_as_absent(tree: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    code, out = _cli(tree, "probe")
    assert code == 1 and out["status"] == "absent"


def _break_validator(base: Path) -> None:
    (base / "scripts" / "validate-ai-profile.py").write_text('import json; print(json.dumps({"ok": True}))\n')


def _ready_on_anything(base: Path) -> None:
    (base / "scripts" / "readiness.py").write_text('import json; print(json.dumps({"ready": True}))\n')


@pytest.mark.parametrize("tamper", [
    lambda b: (b / "scripts" / "readiness.py").unlink(),
    lambda b: (b / "references" / "phases" / "design" / "design-ai.md").unlink(),
    lambda b: (b / "SKILL.md").write_text((b / "SKILL.md").read_text().replace("name: bedrock-migration-assessment", "name: other-skill", 1)),
    lambda b: (b / "SKILL.md").unlink(),
    _break_validator,
    _ready_on_anything,
], ids=["no-readiness", "no-design-phase", "renamed-skill", "no-skill-md", "validator-accepts-legacy", "readiness-always-ready"])
def test_probe_reports_a_changed_sibling_as_tampered(tamper, tree: Path) -> None:
    tamper(tree / "bedrock-migration-assessment")
    code, out = _cli(tree, "probe")
    assert code == 1 and out["status"] == "tampered" and out["detail"]


# --------------------------------------------------------------------------- the four routes

def test_route_present_delegates(tree: Path, tmp_path: Path) -> None:
    run = _gcp_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "delegate"
    assert not (run / "ai-handoff.json").exists()


def test_route_absent_with_infrastructure_defers_ai_visibly(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "defer" and out["reason"] == "bma_absent"
    assert "bedrock-migration-assessment" in out["message"]
    record = json.loads((run / "ai-handoff.json").read_text())
    assert record["status"] == "deferred" and record["reason"] == "bma_absent"
    assert record["profile_digest"] == "sha256:" + _sha(run / "ai-workload-profile.json")


def test_route_absent_ai_only_stops_with_a_named_error(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=False)
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["route"] == "stop" and out["reason"] == "bma_required"
    assert "install" in out["message"].lower() and "bedrock-migration-assessment" in out["message"]
    assert not (run / "ai-handoff.json").exists()


def test_a_skip_record_billing_profile_is_not_infrastructure(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=False)
    (run / "billing-profile.json").write_text(json.dumps({"services": [], "warnings": ["skipped"]}))
    assert _cli(tree, "route", str(run))[1]["reason"] == "bma_required"
    (run / "billing-profile.json").write_text(json.dumps({"services": [{"service": "Cloud Run"}]}))
    assert _cli(tree, "route", str(run))[1]["route"] == "defer"


@pytest.mark.parametrize("infra", [True, False])
def test_route_tampered_fails_closed(infra, tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=infra)
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["route"] == "stop" and out["reason"] == "bma_tampered"
    assert not (run / "ai-handoff.json").exists()


def test_tampered_with_infrastructure_continues_only_when_the_user_chose_infra_only(tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run), "--infra-only")
    assert code == 0 and out["route"] == "defer" and out["reason"] == "bma_tampered"
    assert json.loads((run / "ai-handoff.json").read_text())["reason"] == "bma_tampered"


def test_infra_only_does_not_rescue_an_ai_only_run(tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=False)
    assert _cli(tree, "route", str(run), "--infra-only")[1]["reason"] == "bma_tampered"


def test_route_without_an_ai_profile_has_nothing_to_hand_off(tree: Path, tmp_path: Path) -> None:
    run = _gcp_run(tmp_path, infra=True)
    (run / "ai-workload-profile.json").unlink()
    (run / "ai-handoff.json").write_text("{}")
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "no_ai" and not (run / "ai-handoff.json").exists()


# --------------------------------------------------------------------------- convert

def _scan_profile() -> dict:
    return json.loads((FIXTURES / "bma-estimate-measured" / "ai-workload-profile.json").read_text())


def _validate(tree: Path, path: Path) -> dict:
    script = tree / "bedrock-migration-assessment" / "scripts" / "validate-ai-profile.py"
    out = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    return json.loads(out.stdout)


def test_convert_adds_vertex_models_that_iac_or_monitoring_proved(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        _model("gemini-2.5-flash-preview-05-20", "vertex_ai_generative", "monitoring"),
        _model("Gemini-1.5-Pro-002", "vertex_ai_generative", "code", "terraform"),
        _model("text-embedding-004", "vertex_ai_embeddings", "terraform"),
    ])))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(_scan_profile()))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 0 and out["ok"] is True and out["not_converted"] == []
    profile = json.loads(out_path.read_text())
    vertex = [s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("google", "vertex_ai")]
    assert len(vertex) == 1
    assert vertex[0]["models"] == ["gemini-1.5-pro", "gemini-2.5-flash", "text-embedding-004"]
    assert vertex[0]["model_families"] == ["embedding", "gemini"]
    by_model = {o["normalized_model"]: o for o in vertex[0]["model_observations"]}
    assert by_model["gemini-2.5-flash"]["raw_model"] == "gemini-2.5-flash-preview-05-20"
    assert by_model["gemini-2.5-flash"]["evidence"][0] == {"provenance": "live_api", "confidence": "high",
                                                             "detail": "gcp-to-aws Cloud Monitoring publisher tokens"}
    assert by_model["gemini-1.5-pro"]["raw_model"] == "Gemini-1.5-Pro-002"
    assert [e["provenance"] for e in by_model["gemini-1.5-pro"]["evidence"]] == ["iac"]
    assert [s for s in profile["ai_sources"] if s["provider"] == "openai"] == [s for s in _scan_profile()["ai_sources"] if s["provider"] == "openai"]
    _validate(tree, out_path)


def test_convert_never_guesses_a_service_from_code_or_names(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        _model("gemini-2.5-flash", "vertex_ai_generative", "code"),
        _model("claude-3-5-sonnet", "vertex_partner_model", "monitoring"),
        _model("gpt-4o", "openai_api", "code"),
        _model("gemini-2.0-flash-lite-001", "vertex_ai_generative", "terraform"),
    ])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0
    assert {(n["model"], n["reason"]) for n in out["not_converted"]} == {
        ("gemini-2.5-flash", "code_evidence_only"),
        ("claude-3-5-sonnet", "unsupported_service"),
        ("gpt-4o", "code_evidence_only"),
    }
    profile = json.loads(out_path.read_text())
    assert profile["schema_version"] == "1.0" and profile["gateways"] == []
    assert [s["models"] for s in profile["ai_sources"]] == [["gemini-2.0-flash-lite"]]
    _validate(tree, out_path)


def test_convert_with_nothing_proved_and_no_scan_writes_nothing(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "code")])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 1 and out["error"] == "no_ai_sources" and not out_path.exists()


def test_convert_adds_proof_to_a_vertex_source_the_scan_already_has(tree: Path, tmp_path: Path) -> None:
    scan_doc = _scan_profile()
    scan_doc["ai_sources"].append({"provider": "google", "source_service": "vertex_ai", "model_families": ["gemini"],
                                   "model_evidence": "observed", "models": ["gemini-2.5-flash"],
                                   "model_observations": [{"normalized_model": "gemini-2.5-flash", "raw_model": "gemini-2.5-flash",
                                                           "model_family": "gemini",
                                                           "evidence": [{"provenance": "code", "confidence": "high"}]}]})
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(scan_doc))
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "monitoring", "code")])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    assert _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))[0] == 0
    vertex = [s for s in json.loads(out_path.read_text())["ai_sources"] if s["source_service"] == "vertex_ai"]
    assert len(vertex) == 1 and vertex[0]["models"] == ["gemini-2.5-flash"]
    assert [e["provenance"] for e in vertex[0]["model_observations"][0]["evidence"]] == ["code", "live_api"]
    _validate(tree, out_path)


def test_convert_merges_rows_that_name_the_same_model(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        _model("publishers/google/models/gemini-2.5-flash-preview-05-20", "vertex_ai_generative", "monitoring"),
        _model("gemini-2.5-flash", "vertex_ai_generative", "terraform"),
        _model("gemini-2.5-flash-lite", "vertex_ai_generative", "terraform"),
        _model("gemini-3", "vertex_ai_generative", "terraform"),
    ])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    assert _cli(tree, "convert", str(legacy.parent))[0] == 0
    (source,) = json.loads(out_path.read_text())["ai_sources"]
    assert source["models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3"]
    flash = source["model_observations"][0]
    assert flash["raw_model"] == "publishers/google/models/gemini-2.5-flash-preview-05-20"
    assert [e["provenance"] for e in flash["evidence"]] == ["live_api", "iac"]
    _validate(tree, out_path)


def test_convert_refuses_to_change_a_vertex_source_a_gateway_routes_to(tree: Path, tmp_path: Path) -> None:
    scan_doc = {"schema_version": "1.0", "ai_sources": [{
        "provider": "google", "source_service": "vertex_ai", "model_families": ["gemini"], "model_evidence": "observed",
        "models": ["gemini-2.5-pro"], "model_observations": [{"normalized_model": "gemini-2.5-pro", "raw_model": "google/gemini-2.5-pro",
                                                              "model_family": "gemini", "evidence": [{"provenance": "code", "confidence": "high"}]}]}],
        "gateways": [{"product": "openrouter", "type": "llm_router", "upstream_evidence": "observed", "upstreams": [
            {"provider": "google", "source_service": "vertex_ai",
             "model_families": [{"family": "gemini", "model_evidence": "observed", "models": ["gemini-2.5-pro"]}]}]}]}
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(scan_doc))
    _validate(tree, scan)
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform")])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 1 and out["error"] == "convert_conflict" and not out_path.exists()


@pytest.mark.parametrize("bad", ["not json", json.dumps({"schema_version": "1.0", "ai_sources": [], "gateways": []})])
def test_convert_rejects_a_scan_the_validator_rejects(bad, tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform")])))
    scan = tmp_path / "scan.json"
    scan.write_text(bad if bad == "not json" else json.dumps({**json.loads(bad), "summary": {}}))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 1 and out["error"] in {"scan_unreadable", "scan_invalid"} and not out_path.exists()


def test_convert_refuses_when_the_sibling_is_not_present(tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 1 and out["error"] == "bma_tampered"


# --------------------------------------------------------------------------- host answers and accept

def _gcp_prefs(run: Path) -> dict:
    bma = json.loads((FIXTURES / "bma-estimate-measured" / "preferences.json").read_text())
    prefs = {"metadata": {"migration_type": "full", "clarify_mode": "wizard"},
             "design_constraints": {k: bma["design_constraints"][k] for k in ("target_region", "compliance")},
             "startup_constraints": {}}
    prefs["design_constraints"]["availability"] = {"value": "single-az", "chosen_by": "default", "prompt": "p",
                                                   "design_consequence": "c", "source": "default:Q5"}
    (run / "preferences.json").write_text(json.dumps(prefs))
    return prefs


def test_host_answers_pass_only_region_and_compliance_and_open_the_handoff(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    prefs = _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    code, out = _open(tree, gcp, bma, "clarify")
    assert code == 0
    host = json.loads((bma / "host-answers.json").read_text())
    expected = {k: {f: v for f, v in prefs["design_constraints"][k].items() if f not in ("question_id", "source")} | {"source": "host:gcp-to-aws"}
                for k in ("target_region", "compliance")}
    assert host == {"host_skill": "gcp-to-aws", "infrastructure_moves": True, "stop_after": "clarify", "design_constraints": expected}
    record = json.loads((gcp / "ai-handoff.json").read_text())
    assert record == {"profile_digest": "sha256:" + _sha(gcp / "ai-workload-profile.json"), "assessment_dir": bma.name,
                      "assessment_profile_digest": "sha256:" + _sha(bma / "ai-workload-profile.json"),
                      "status": "in_progress", "artifacts": {}}


def test_host_answers_for_an_ai_only_run_answer_nothing(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=False)
    bma = _bma_run(tmp_path)
    assert _open(tree, gcp, bma, "clarify")[0] == 0
    host = json.loads((bma / "host-answers.json").read_text())
    assert host["design_constraints"] == {} and host["infrastructure_moves"] is False


def test_accept_clarify_copies_ai_answers_into_gcp_preferences(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    prefs = _gcp_prefs(gcp)
    bma = _bma_run(tmp_path, {"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "pending"})
    _open(tree, gcp, bma, "clarify")
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "clarify")
    assert code == 0 and out["ok"] is True
    merged = json.loads((gcp / "preferences.json").read_text())
    bma_prefs = json.loads((bma / "preferences.json").read_text())
    assert merged["ai_constraints"] == bma_prefs["ai_constraints"]
    assert merged["startup_constraints"]["startup_program_status"] == bma_prefs["startup_constraints"]["startup_program_status"]
    assert merged["design_constraints"] == prefs["design_constraints"]
    assert merged["metadata"]["migration_type"] == "full"
    assert merged["metadata"]["ai_preferences_source"] == {"assessment_dir": bma.name, "sha256": _sha(bma / "preferences.json"),
                                                           "startup_keys": ["startup_program_status"], "startup_before": {}}
    record = json.loads((gcp / "ai-handoff.json").read_text())
    assert record["status"] == "in_progress" and record["through"] == "clarify"
    assert record["artifacts"] == {"preferences.json": _sha(bma / "preferences.json")}
    assert not (gcp / "aws-design-ai.json").exists()


def test_accept_clarify_for_an_ai_only_run_writes_the_assessment_preferences(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=False)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "clarify")
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "clarify")[0] == 0
    written = json.loads((gcp / "preferences.json").read_text())
    source = written["metadata"].pop("ai_preferences_source")
    assert written == json.loads((bma / "preferences.json").read_text()) and source["sha256"] == _sha(bma / "preferences.json")


def test_accept_estimate_copies_the_design_and_estimate_and_closes_the_handoff(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")
    assert code == 0
    for name in ("aws-design-ai.json", "estimation-ai.json"):
        assert (gcp / name).read_bytes() == (bma / name).read_bytes()
    assert json.loads((gcp / "ai-workload-profile.json").read_text())["summary"]["ai_source"] == "gemini"
    merged = json.loads((gcp / "preferences.json").read_text())
    assert merged["ai_constraints"] == json.loads((bma / "preferences.json").read_text())["ai_constraints"]
    record = json.loads((gcp / "ai-handoff.json").read_text())
    assert record["status"] == "assessment_completed" and record["through"] == "estimate"
    assert set(record["artifacts"]) == {"preferences.json", "aws-design-ai.json", "estimation-ai.json"}


def test_accept_stops_on_a_run_that_is_not_ready(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path, {"discover": "completed", "clarify": "completed", "design": "in_progress", "estimate": "pending"})
    _open(tree, gcp, bma, "design")
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "design")
    assert code == 1 and out["error"] == "assessment_not_ready" and out["reason"] == "phase_incomplete"
    assert not (gcp / "aws-design-ai.json").exists()


def test_accept_fails_closed_when_readiness_reports_a_wrong_hash(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    base = tree / "bedrock-migration-assessment" / "scripts"
    real = (base / "readiness.py").read_text()
    (base / "readiness.py").write_text(real.replace('hashlib.sha256(read[f]).hexdigest()', '"0" * 64'))
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "bma_tampered"
    assert not (gcp / "aws-design-ai.json").exists() and not (gcp / "estimation-ai.json").exists()


def test_accept_stops_when_discovery_changed_after_the_handoff(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    (gcp / "ai-workload-profile.json").write_text(json.dumps(_legacy([])))
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "profile_changed"


def test_a_changed_profile_cannot_reopen_the_old_assessment_run(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    (gcp / "ai-workload-profile.json").write_text(json.dumps(_legacy([])))
    code, out = _open(tree, gcp, bma, "estimate", convert=False)
    assert code == 1 and out["error"] == "profile_changed"
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[1]["error"] == "profile_changed"
    fresh = bma.parent / "bma-1119-2300"
    shutil.copytree(bma, fresh)
    assert _open(tree, gcp, fresh, "estimate")[0] == 0
    assert _cli(tree, "accept", str(gcp), str(fresh), "--through", "estimate")[0] == 0


def test_accept_stops_when_gcp_answers_changed_after_the_handoff(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    prefs = _gcp_prefs(gcp)
    bma = _bma_run(tmp_path, {"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "pending"})
    _open(tree, gcp, bma, "clarify")
    prefs["design_constraints"]["target_region"]["value"] = "eu-west-1"
    (gcp / "preferences.json").write_text(json.dumps(prefs))
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "host_answers_stale"


def test_accept_without_an_open_handoff_is_refused(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    bma = _bma_run(tmp_path)
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "handoff_not_open"


def test_accept_refuses_an_assessment_dir_the_handoff_did_not_name(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    other = bma.parent / "bma-1119-2200"
    shutil.copytree(bma, other)
    code, out = _cli(tree, "accept", str(gcp), str(other), "--through", "estimate")
    assert code == 1 and out["error"] == "handoff_mismatch"


def test_host_answers_refuse_a_run_that_assessed_another_profile(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _converted(gcp, bma)
    record = json.loads((gcp / "ai-handoff.json").read_text())
    record["assessment_profile_digest"] = "sha256:" + hashlib.sha256(json.dumps(GOOD_PROFILE_FOR_TEST).encode()).hexdigest()
    (gcp / "ai-handoff.json").write_text(json.dumps(record))
    code, out = _open(tree, gcp, bma, "clarify", convert=False)
    assert code == 1 and out["error"] == "assessment_profile_mismatch"
    assert json.loads((gcp / "ai-handoff.json").read_text())["status"] == "converted" and not (bma / "host-answers.json").exists()


def test_host_answers_refuse_a_run_the_user_started_before_writing(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    status = json.loads((bma / ".phase-status.json").read_text())
    del status["initiated_by"]
    (bma / ".phase-status.json").write_text(json.dumps(status))
    code, out = _open(tree, gcp, bma, "clarify")
    assert code == 1 and out["error"] == "handoff_mismatch" and not (bma / "host-answers.json").exists()


def test_host_answers_need_a_converted_profile(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    bma = _bma_run(tmp_path)
    code, out = _open(tree, gcp, bma, "clarify", convert=False)
    assert code == 1 and out["error"] == "handoff_not_open"


def test_convert_opens_the_handoff_with_both_profile_digests(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform")])))
    assert _cli(tree, "convert", str(legacy.parent))[0] == 0
    record = json.loads((legacy.parent / "ai-handoff.json").read_text())
    assert record == {"profile_digest": "sha256:" + _sha(legacy), "status": "converted", "artifacts": {},
                      "assessment_profile_digest": "sha256:" + _sha(legacy.parent / "ai-workload-profile.neutral.json")}


def test_accept_never_moves_a_handoff_back_to_an_earlier_phase(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[0] == 0
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "accept_regressed"
    assert json.loads((gcp / "ai-handoff.json").read_text())["status"] == "assessment_completed"
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[0] == 0


def test_a_project_billed_only_for_vertex_ai_has_no_infrastructure(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=False)
    (run / "billing-profile.json").write_text(json.dumps({"services": [
        {"gcp_service": "Vertex AI", "gcp_service_type": "google_vertex_ai_endpoint", "ai_signals": ["vertex_ai"]}]}))
    (run / "gcp-resource-inventory.json").write_text(json.dumps({"resources": [{"type": "google_vertex_ai_endpoint"}]}))
    assert _cli(tree, "route", str(run))[1]["reason"] == "bma_required"
    (run / "billing-profile.json").write_text(json.dumps({"services": [
        {"gcp_service": "Vertex AI", "gcp_service_type": "google_vertex_ai_endpoint", "ai_signals": ["vertex_ai"]},
        {"gcp_service": "Cloud Run", "gcp_service_type": "google_cloud_run_v2_service", "ai_signals": []}]}))
    assert _cli(tree, "route", str(run))[1]["route"] == "defer"


def test_accept_refuses_a_run_another_skill_or_the_user_started(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    status = json.loads((bma / ".phase-status.json").read_text())
    del status["initiated_by"]
    (bma / ".phase-status.json").write_text(json.dumps(status))
    code, out = _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "handoff_mismatch" and not (gcp / "aws-design-ai.json").exists()


def test_an_inventory_with_no_resources_is_not_infrastructure(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _gcp_run(tmp_path, infra=False)
    (run / "gcp-resource-inventory.json").write_text(json.dumps({"metadata": {}, "resources": []}))
    assert _cli(tree, "route", str(run))[1]["reason"] == "bma_required"


GOOD_PROFILE_FOR_TEST = {"schema_version": "1.0", "gateways": [], "ai_sources": [{
    "provider": "anthropic", "source_service": "anthropic_api", "model_families": ["claude"], "model_evidence": "not_observed",
    "models": [], "model_observations": []}]}


@pytest.mark.parametrize("reroute", ["no_ai", "defer"])
def test_rerouting_removes_what_an_earlier_accept_copied(reroute, tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    prefs = _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[0] == 0
    if reroute == "no_ai":
        (gcp / "ai-workload-profile.json").unlink()
    else:
        shutil.rmtree(tree / "bedrock-migration-assessment")
    assert _cli(tree, "route", str(gcp))[1]["route"] == reroute
    for name in ("aws-design-ai.json", "estimation-ai.json", "ai-workload-profile.neutral.json"):
        assert not (gcp / name).exists(), name
    assert json.loads((gcp / "preferences.json").read_text()) == prefs
    assert (gcp / "ai-handoff.json").exists() is (reroute == "defer")


def test_rerouting_keeps_an_ai_design_the_handoff_did_not_copy(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    (gcp / "aws-design-ai.json").write_text("{}")
    (gcp / "ai-workload-profile.json").unlink()
    assert _cli(tree, "route", str(gcp))[1]["route"] == "no_ai"
    assert (gcp / "aws-design-ai.json").read_text() == "{}"


def test_convert_reports_rows_without_a_model_id(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform"),
                                          {"service": "vertex_ai_generative", "model_id": ""}, "not a row"])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["not_converted"] == [{"model": "", "reason": "invalid_model_id"},
                                                  {"model": None, "reason": "invalid_model_id"}]


def test_withdrawing_restores_a_startup_answer_the_accept_replaced(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True)
    prefs = _gcp_prefs(gcp)
    prefs["startup_constraints"] = {"startup_program_status": {"value": "has_credits", "chosen_by": "user", "prompt": "p",
                                                               "design_consequence": "c"}}
    (gcp / "preferences.json").write_text(json.dumps(prefs))
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "design")[0] == 0
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[0] == 0
    (gcp / "ai-workload-profile.json").unlink()
    _cli(tree, "route", str(gcp))
    assert json.loads((gcp / "preferences.json").read_text()) == prefs


def test_converting_again_removes_what_the_previous_handoff_copied(tree: Path, tmp_path: Path) -> None:
    gcp = _gcp_run(tmp_path, infra=True, profile=_legacy([_model("gemini-2.5-flash", "vertex_ai_generative", "terraform")]))
    prefs = _gcp_prefs(gcp)
    bma = _bma_run(tmp_path)
    _open(tree, gcp, bma, "estimate")
    assert _cli(tree, "accept", str(gcp), str(bma), "--through", "estimate")[0] == 0
    assert _cli(tree, "convert", str(gcp))[0] == 0
    assert not (gcp / "aws-design-ai.json").exists() and not (gcp / "estimation-ai.json").exists()
    assert json.loads((gcp / "preferences.json").read_text()) == prefs
    assert json.loads((gcp / "ai-handoff.json").read_text())["status"] == "converted"


def test_infra_only_is_honored_when_the_sibling_is_present(tree: Path, tmp_path: Path) -> None:
    run = _gcp_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run), "--infra-only")
    assert code == 0 and out["route"] == "defer" and out["reason"] == "user_chose_infra_only"
    assert json.loads((run / "ai-handoff.json").read_text())["reason"] == "user_chose_infra_only"
    ai_only = _gcp_run(tmp_path / "other", infra=False)
    assert _cli(tree, "route", str(ai_only), "--infra-only")[1]["route"] == "delegate"
