"""Tests for azure-to-aws scripts/bma-handoff.py: the sibling routes, the Azure profile conversion, and accepting a bedrock-migration-assessment run."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
FIXTURES = PLUGIN_ROOT / "fixtures"
SCRIPT = SKILLS / "azure-to-aws" / "scripts" / "bma-handoff.py"
RUN_ID = "7c1d2e3f-8a9b-4c0d-9e1f-2a3b4c5d6e7f"
BMA_FILES = ("ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json", "openai-usage-profile.json")
SUB = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/oai"
DEEP_JSON = b"[" * 200000  # nested deep enough that json.loads raises RecursionError


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A plugin layout with azure-to-aws's script beside a real copy of bedrock-migration-assessment."""
    root = tmp_path / "skills"
    (root / "azure-to-aws" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "azure-to-aws" / "scripts" / SCRIPT.name)
    shutil.copytree(SKILLS / "bedrock-migration-assessment", root / "bedrock-migration-assessment",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _cli(tree: Path, *args: str, cwd: Path | None = None) -> tuple[int, dict]:
    script = tree / "azure-to-aws" / "scripts" / SCRIPT.name
    out = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, cwd=cwd or tree, timeout=120)
    return out.returncode, json.loads(out.stdout)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy(models: list[dict], ai_source: str = "azure_openai", infrastructure: list | None = None) -> dict:
    return {"metadata": {"profile_source": "merged"}, "summary": {"ai_source": ai_source}, "models": models,
            "integration": {"pattern": "unknown"}, "infrastructure": infrastructure or [], "detection_signals": [], "workloads": []}


def _model(model_id: str, service: str, *sources: str) -> dict:
    return {"model_id": model_id, "service": service, "detected_via": [s for s in sources if s in ("code", "terraform")],
            "evidence": [{"source": s, "file": "x"} for s in sources], "capabilities_used": ["text_generation"], "usage_context": "chat"}


def _iac_deployment(name: str, model: str | None, azure_id: str | None = None, fmt: str | None = "OpenAI") -> dict:
    entry = {"address": f"azurerm_cognitive_deployment.{name}", "type": "azurerm_cognitive_deployment", "file": "ai.tf",
             "role": "deployment", "config": {"model": {"name": model, **({"format": fmt} if fmt else {})} if model else {}}}
    if azure_id:
        entry["azure_id"] = azure_id
    return entry


def _live_deployment(name: str, model: str | None, source: str = "live") -> dict:
    return {"azure_id": f"{SUB}/deployments/{name}", "type": "Microsoft.CognitiveServices/accounts/deployments", "source": source,
            "role": "deployment", "config": {"model": model} if model else {}}


def _azure_run(tmp_path: Path, infra: bool, profile: dict | None = None) -> Path:
    run = tmp_path / ".migration" / "1125-2100"
    run.mkdir(parents=True)
    (run / "ai-workload-profile.json").write_text(json.dumps(profile or _legacy([_model("gpt-4o", "azure_openai", "code")])))
    resources = [{"azure_id": SUB, "azure_type": "Microsoft.CognitiveServices/accounts"}]
    if infra:
        resources.append({"azure_id": "/subscriptions/0/resourceGroups/rg/providers/Microsoft.Web/sites/app", "azure_type": "Microsoft.Web/sites"})
    (run / "azure-resource-inventory.json").write_text(json.dumps({"resources": resources}))
    return run


def _bma_run(tmp_path: Path, phases: dict | None = None) -> Path:
    run = tmp_path / ".migration" / "bma-1125-2101"
    run.mkdir(parents=True)
    for name in BMA_FILES:
        shutil.copy(FIXTURES / "bma-estimate-measured" / name, run / name)
    status = {"migration_id": run.name, "run_id": RUN_ID, "last_updated": "2026-11-25T21:00:00Z", "initiated_by": "AZURE_TO_AWS",
              "phases": phases or dict.fromkeys(("discover", "clarify", "design", "estimate"), "completed")}
    (run / ".phase-status.json").write_text(json.dumps(status))
    return run


def _legacy_dir(tmp_path: Path) -> Path:
    run = tmp_path / ".migration" / "1125-2100"
    run.mkdir(parents=True, exist_ok=True)
    return run


def _converted(azure: Path, bma: Path) -> None:
    """Stand in for convert: the assessment run already holds the neutral profile this run handed over."""
    shutil.copy(bma / "ai-workload-profile.json", azure / "ai-workload-profile.neutral.json")
    (azure / "ai-handoff.json").write_text(json.dumps({
        "profile_digest": "sha256:" + _sha(azure / "ai-workload-profile.json"), "status": "converted",
        "assessment_profile_digest": "sha256:" + _sha(bma / "ai-workload-profile.json"), "artifacts": {},
        "infrastructure_moves": len(json.loads((azure / "azure-resource-inventory.json").read_text())["resources"]) > 1}))


def _open(tree: Path, azure: Path, bma: Path, stop_after: str, convert: bool = True) -> tuple[int, dict]:
    if convert:
        _converted(azure, bma)
    return _cli(tree, "host-answers", str(azure), str(bma), "--stop-after", stop_after)


def _azure_prefs(run: Path, compliance: list | None = None) -> dict:
    prefs = {"phase": "clarify", "clarify_status": "COMPLETE", "metadata": {"clarify_mode": "wizard"},
             "global": {"target_region": {"disposition": "DETECTED", "value": "us-east-1", "default": "us-east-1",
                                          "source": "every resource is eastus"},
                        "user_geography": {"disposition": "PROPOSED", "value": "single-region", "default": "single-region"}},
             "design_constraints": {"compliance": {"disposition": "ESSENTIAL", "value": ["none"] if compliance is None else compliance,
                                                   "default": None},
                                    "cpu_architecture": {"disposition": "PROPOSED", "value": "x86_64", "default": "x86_64"}}}
    (run / "preferences.json").write_text(json.dumps(prefs))
    return prefs


def _scan_profile() -> dict:
    return json.loads((FIXTURES / "bma-estimate-measured" / "ai-workload-profile.json").read_text())


def _validate(tree: Path, path: Path) -> dict:
    script = tree / "bedrock-migration-assessment" / "scripts" / "validate-ai-profile.py"
    out = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    return json.loads(out.stdout)


def _azure_source(path: Path) -> dict:
    (source,) = [s for s in json.loads(path.read_text())["ai_sources"] if (s["provider"], s["source_service"]) == ("openai", "azure_openai")]
    return source


# --------------------------------------------------------------------------- probe

def test_probe_finds_the_installed_sibling(tree: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    code, out = _cli(tree, "probe", cwd=project)
    assert code == 0 and out["status"] == "present"
    assert Path(out["bma_base"]).resolve() == (tree / "bedrock-migration-assessment").resolve()


def test_probe_reports_a_missing_sibling_as_absent(tree: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    code, out = _cli(tree, "probe")
    assert code == 1 and out["status"] == "absent"


def _break_validator(base: Path) -> None:
    (base / "scripts" / "validate-ai-profile.py").write_text('import json; print(json.dumps({"ok": True, "schema_version": "1.0"}))\n')


def _validator_accepts_azure_legacy(base: Path) -> None:
    path = base / "scripts" / "validate-ai-profile.py"
    path.write_text(path.read_text().replace('LEGACY_TOP_LEVEL_KEYS = ("metadata", "summary", "models", "infrastructure", "current_costs", '
                                             '"detection_signals")', "LEGACY_TOP_LEVEL_KEYS = ()", 1)
                    .replace('LEGACY_SOURCE_KEYS = ("model_id", "service", "detected_via", "capabilities_used", "usage_context")',
                             "LEGACY_SOURCE_KEYS = ()", 1)
                    .replace("    errors = _schema_errors(schema, profile, schema)\n",
                             "    errors = [] if 'summary' in profile else _schema_errors(schema, profile, schema)\n", 1)
                    .replace("    sources = _check_semantics(profile)\n", "    if 'summary' in profile:\n"
                             "        return {'ok': True, 'schema_version': '1.0'}\n    sources = _check_semantics(profile)\n", 1))


def _readiness_finds_missing_runs(base: Path) -> None:
    path = base / "scripts" / "readiness.py"
    path.write_text(path.read_text().replace('raise NotReady("run_not_found"', 'raise NotReady("status_not_found"', 1))


@pytest.mark.parametrize("tamper", [
    lambda b: (b / "scripts" / "readiness.py").unlink(),
    lambda b: (b / "references" / "phases" / "estimate" / "estimate-ai.md").unlink(),
    lambda b: (b / "SKILL.md").write_text((b / "SKILL.md").read_text().replace("name: bedrock-migration-assessment", "name: azure-ai", 1)),
    lambda b: (b / "SKILL.md").write_bytes(b"---\nname: bedrock-migration-assessment\n---\n\xff\n"),
    _break_validator,
    _validator_accepts_azure_legacy,
    lambda b: (b / "scripts" / "validate-ai-profile.py").write_text('import sys; sys.stdout.buffer.write(b"\\xff\\xfe{}")\n'),
    lambda b: (b / "scripts" / "validate-ai-profile.py").write_text('print("validated")\n'),
    lambda b: (b / "scripts" / "validate-ai-profile.py").write_text('print("[" * 200000)\n'),
    _readiness_finds_missing_runs,
], ids=["no-readiness", "no-estimate-phase", "renamed-skill", "skill-md-not-utf8", "validator-accepts-anything",
        "validator-accepts-azure-legacy", "validator-prints-invalid-bytes", "validator-prints-non-json",
        "validator-prints-deep-json", "readiness-misreports-missing-run"])
def test_probe_reports_a_changed_sibling_as_tampered(tamper, tree: Path) -> None:
    tamper(tree / "bedrock-migration-assessment")
    code, out = _cli(tree, "probe")
    assert code == 1 and out["status"] == "tampered" and out["detail"]


def _load_module(tree: Path):
    spec = importlib.util.spec_from_file_location("azure_bma_handoff", tree / "azure-to-aws" / "scripts" / SCRIPT.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired(cmd="x", timeout=1), OSError("cannot launch")], ids=["timeout", "launch-error"])
def test_a_sibling_that_hangs_or_cannot_start_is_tampered(failure, tree: Path, monkeypatch) -> None:
    module = _load_module(tree)

    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(module.subprocess, "run", fail)
    assert module.probe()["status"] == "tampered"


# --------------------------------------------------------------------------- route

def test_route_present_delegates(tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "delegate"
    assert not (run / "ai-handoff.json").exists()


def test_route_absent_with_infrastructure_defers_ai_visibly(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "defer" and out["reason"] == "bma_absent"
    assert "bedrock-migration-assessment" in out["message"] and "azure-to-aws" in out["message"]
    record = json.loads((run / "ai-handoff.json").read_text())
    assert record == {"profile_digest": "sha256:" + _sha(run / "ai-workload-profile.json"), "status": "deferred", "reason": "bma_absent"}


def test_route_absent_ai_only_stops_with_a_named_error(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=False)
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["route"] == "stop" and out["reason"] == "bma_required"
    assert "install" in out["message"].lower() and "bedrock-migration-assessment" in out["message"]
    assert not (run / "ai-handoff.json").exists()


@pytest.mark.parametrize("infra", [True, False])
def test_route_tampered_fails_closed(infra, tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=infra)
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["route"] == "stop" and out["reason"] == "bma_tampered"
    assert ("infrastructure only" in out["message"]) is infra
    assert not (run / "ai-handoff.json").exists()


def test_infra_only_defers_a_tampered_sibling_but_not_an_ai_only_run(tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run), "--infra-only")
    assert code == 0 and out["route"] == "defer" and out["reason"] == "bma_tampered"
    ai_only = _azure_run(tmp_path / "other", infra=False)
    assert _cli(tree, "route", str(ai_only), "--infra-only")[1]["reason"] == "bma_tampered"


def test_infra_only_is_honored_when_the_sibling_is_present(tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True)
    code, out = _cli(tree, "route", str(run), "--infra-only")
    assert code == 0 and out["route"] == "defer" and out["reason"] == "user_chose_infra_only"
    ai_only = _azure_run(tmp_path / "other", infra=False)
    assert _cli(tree, "route", str(ai_only), "--infra-only")[1]["route"] == "delegate"


def test_route_without_an_ai_profile_has_nothing_to_hand_off(tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True)
    (run / "ai-workload-profile.json").unlink()
    (run / "ai-handoff.json").write_text("{}")
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "no_ai" and not (run / "ai-handoff.json").exists()


@pytest.mark.parametrize("bma", ["present", "absent", "tampered"])
@pytest.mark.parametrize("infra", [True, False])
def test_traditional_ml_stays_with_azure_whatever_the_sibling_state(bma, infra, tree: Path, tmp_path: Path) -> None:
    if bma == "absent":
        shutil.rmtree(tree / "bedrock-migration-assessment")
    elif bma == "tampered":
        _break_validator(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=infra, profile=_legacy([_model("prebuilt-invoice", "cognitive_document_intelligence", "terraform")],
                                                            ai_source="other"))
    (run / "ai-handoff.json").write_text(json.dumps({"status": "deferred"}))
    code, out = _cli(tree, "route", str(run))
    assert code == 0 and out["route"] == "traditional_ml" and "design-refs/ai.md" in out["message"]
    assert not (run / "ai-handoff.json").exists()


@pytest.mark.parametrize("ai_source", ["azure_openai", "openai", "anthropic", "both", None])
def test_every_generative_ai_source_delegates(ai_source, tree: Path, tmp_path: Path) -> None:
    profile = _legacy([_model("claude-sonnet-4-5", "anthropic", "code")], ai_source=ai_source or "x")
    if ai_source is None:
        del profile["summary"]
    run = _azure_run(tmp_path, infra=False, profile=profile)
    assert _cli(tree, "route", str(run))[1]["route"] == "delegate"


@pytest.mark.parametrize("command", ["route", "convert"])
@pytest.mark.parametrize("raw", [b"{not json", b"\xff\xfe{}", DEEP_JSON], ids=["not-json", "not-utf8", "too-deep"])
def test_an_unreadable_azure_profile_gets_a_named_error(raw, command, tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True)
    (run / "ai-workload-profile.json").write_bytes(raw)
    code, out = _cli(tree, command, str(run))
    assert code == 1 and out["error"] == "legacy_unreadable", out


@pytest.mark.parametrize(("resources", "route"), [
    ([{"azure_type": "Microsoft.CognitiveServices/accounts"}, {"azure_type": "microsoft.machinelearningservices/workspaces"}], "stop"),
    ([{"azure_type": "Microsoft.Search/searchServices"}], "defer"),
    ([{"azure_type": "Microsoft.Web/sites"}], "defer"),
    ([{"name": "untyped"}], "defer"),
    (["not an object"], "defer"),
    ([], "stop"),
], ids=["cognitive-and-ml-only", "search-is-infrastructure", "app-service", "untyped-row", "non-object-row", "empty"])
def test_only_cognitive_services_and_ml_resources_are_ai(resources, route, tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=False)
    (run / "azure-resource-inventory.json").write_text(json.dumps({"resources": resources}))
    assert _cli(tree, "route", str(run))[1]["route"] == route


def test_a_run_without_an_inventory_has_no_infrastructure(tree: Path, tmp_path: Path) -> None:
    shutil.rmtree(tree / "bedrock-migration-assessment")
    run = _azure_run(tmp_path, infra=True)
    (run / "azure-resource-inventory.json").unlink()
    assert _cli(tree, "route", str(run))[1]["reason"] == "bma_required"


@pytest.mark.parametrize("raw", [b"{not json", DEEP_JSON], ids=["not-json", "too-deep"])
def test_an_unreadable_inventory_gets_a_plain_error_code(raw, tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=False)
    (run / "azure-resource-inventory.json").write_bytes(raw)
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["error"] == "inventory_unreadable" and "Discover" in out["detail"], out


@pytest.mark.parametrize("resources", [7, "Microsoft.Web/sites", None, {"Microsoft.Web/sites": {}}])
def test_an_inventory_whose_resources_is_not_a_list_gets_a_named_error(resources, tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=False)
    (run / "azure-resource-inventory.json").write_text(json.dumps({"resources": resources}))
    code, out = _cli(tree, "route", str(run))
    assert code == 1 and out["error"] == "inventory_unreadable", out


# --------------------------------------------------------------------------- convert

def test_convert_adds_azure_openai_models_that_terraform_live_or_rdfa_proved(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gpt-4o", "azure_openai", "terraform")], infrastructure=[
        _iac_deployment("chat", "gpt-4o"),
        _live_deployment("embed", "text-embedding-3-small"),
        _live_deployment("reason", "o3-mini", source="rdfa"),
    ])))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(_scan_profile()))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 0 and out["ok"] is True and out["not_converted"] == [], out
    source = _azure_source(out_path)
    assert source["models"] == ["gpt-4o", "o3-mini", "text-embedding-3-small"]
    assert source["model_families"] == ["embedding", "gpt", "o_series"]
    by_model = {o["normalized_model"]: o for o in source["model_observations"]}
    assert [(e["provenance"], e["confidence"]) for e in by_model["gpt-4o"]["evidence"]] == [("iac", "medium")]
    assert [(e["provenance"], e["confidence"]) for e in by_model["text-embedding-3-small"]["evidence"]] == [("live_api", "high")]
    assert [(e["provenance"], e["confidence"]) for e in by_model["o3-mini"]["evidence"]] == [("live_api", "medium")]
    profile = json.loads(out_path.read_text())
    assert [s for s in profile["ai_sources"] if s["source_service"] != "azure_openai"] == _scan_profile()["ai_sources"]
    _validate(tree, out_path)


def test_iac_and_live_entries_for_one_deployment_become_one_observation(tree: Path, tmp_path: Path) -> None:
    azure_id = f"{SUB}/deployments/chat"
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_tf_row("GPT-4o-Mini-2024-07-18", "mini")], infrastructure=[
        _iac_deployment("chat", "gpt-4o", azure_id=azure_id),
        _live_deployment("chat", None),
        {**_iac_deployment("mini", "GPT-4o-Mini-2024-07-18", azure_id=f"{SUB}/deployments/mini"), "sources": ["terraform", "live", "rdfa"]},
    ])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["not_converted"] == [], out
    by_model = {o["normalized_model"]: o for o in _azure_source(out_path)["model_observations"]}
    assert sorted(by_model) == ["gpt-4o", "gpt-4o-mini-2024-07-18"]
    assert [e["provenance"] for e in by_model["gpt-4o"]["evidence"]] == ["iac"]
    assert by_model["gpt-4o-mini-2024-07-18"]["raw_model"] == "GPT-4o-Mini-2024-07-18"
    assert [(e["provenance"], e["confidence"]) for e in by_model["gpt-4o-mini-2024-07-18"]["evidence"]] == [
        ("iac", "medium"), ("live_api", "high"), ("live_api", "medium")]
    _validate(tree, out_path)


@pytest.mark.parametrize("live_id", [f"{SUB}/deployments/chat", f"{SUB}/deployments/chat".lower()], ids=["same-case", "other-case"])
def test_live_state_wins_over_a_drifted_terraform_model(live_id, tree: Path, tmp_path: Path) -> None:
    azure_id = f"{SUB}/deployments/chat"
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_iac_deployment("chat", "gpt-4o", azure_id=azure_id),
                                                             {**_live_deployment("chat", "gpt-4.1"), "azure_id": live_id}])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4.1"]
    assert out["not_converted"] == [{"model": "gpt-4o", "reason": "drifted_deployment_model"}]
    assert [e["provenance"] for e in _azure_source(legacy.parent / "ai-workload-profile.neutral.json")["model_observations"][0]["evidence"]] \
        == ["live_api"]


def _tf_row(model_id: str, *names: str) -> dict:
    return {"model_id": model_id, "service": "azure_openai", "detected_via": ["terraform"], "capabilities_used": ["text_generation"],
            "evidence": [{"source": "terraform", "file": "ai.tf", "address": f"azurerm_cognitive_deployment.{n}"} for n in names]}


def _live_row(model_id: str) -> dict:
    return {"model_id": model_id, "service": "azure_openai", "detected_via": [], "capabilities_used": ["text_generation"],
            "evidence": [{"source": "live_az", "pattern": "az cognitiveservices account deployment list"}]}


def _merged_deployment(name: str, model: str) -> dict:
    return {**_iac_deployment(name, None, azure_id=f"{SUB}/deployments/{name}"), "sources": ["terraform", "live"], "config": {"model": model}}


@pytest.mark.parametrize("shape", ["merged", "separate"])
def test_a_terraform_model_row_that_live_state_replaced_is_reported_as_drifted(shape, tree: Path, tmp_path: Path) -> None:
    azure_id = f"{SUB}/deployments/chat"
    infrastructure = [_merged_deployment("chat", "gpt-4.1")] if shape == "merged" else [
        _iac_deployment("chat", "gpt-4o", azure_id=azure_id), _live_deployment("chat", "gpt-4.1")]
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_tf_row("gpt-4o", "chat"), _live_row("gpt-4.1")], infrastructure=infrastructure)))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4.1"], out
    assert out["not_converted"] == [{"model": "gpt-4o", "reason": "drifted_deployment_model"}]
    (observation,) = _azure_source(out_path)["model_observations"]
    assert [(e["provenance"], e["confidence"]) for e in observation["evidence"]] == [("live_api", "high")]
    _validate(tree, out_path)


def test_a_merged_deployment_keeps_terraform_evidence_only_when_terraform_declares_its_model(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_tf_row("gpt-4.1", "chat")], infrastructure=[
        _merged_deployment("chat", "gpt-4.1"), _merged_deployment("by-expression", "gpt-4.1-mini")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["not_converted"] == [], out
    by_model = {o["normalized_model"]: o for o in _azure_source(legacy.parent / "ai-workload-profile.neutral.json")["model_observations"]}
    assert [e["provenance"] for e in by_model["gpt-4.1"]["evidence"]] == ["iac", "live_api"]
    assert [e["provenance"] for e in by_model["gpt-4.1-mini"]["evidence"]] == ["live_api"]


@pytest.mark.parametrize("source", ["live_az", "rdfa_report"])
def test_a_state_row_naming_a_merged_deployment_adds_no_terraform_evidence(source, tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    row = {"model_id": "gpt-4.1-mini", "service": "azure_openai", "detected_via": [],
           "evidence": [{"source": source, "azure_id": f"{SUB}/deployments/by-expression"}]}
    legacy.write_text(json.dumps(_legacy([row], infrastructure=[_merged_deployment("by-expression", "gpt-4.1-mini")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4.1-mini"], out
    (observation,) = _azure_source(legacy.parent / "ai-workload-profile.neutral.json")["model_observations"]
    assert "iac" not in [e["provenance"] for e in observation["evidence"]]


def test_a_terraform_row_for_several_deployments_keeps_the_ones_state_did_not_replace(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_tf_row("gpt-4o", "chat", "batch"), _tf_row("gpt-4o-mini", "undeployed")], infrastructure=[
        _merged_deployment("chat", "gpt-4.1"), _iac_deployment("batch", "gpt-4o", azure_id=f"{SUB}/deployments/batch"),
        _iac_deployment("undeployed", "gpt-4o-mini")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4.1", "gpt-4o", "gpt-4o-mini"] and out["not_converted"] == [], out
    by_model = {o["normalized_model"]: o for o in _azure_source(legacy.parent / "ai-workload-profile.neutral.json")["model_observations"]}
    assert [e["provenance"] for e in by_model["gpt-4o"]["evidence"]] == ["iac"]
    assert [e["provenance"] for e in by_model["gpt-4.1"]["evidence"]] == ["live_api"]


def test_an_rdfa_model_row_that_live_state_replaced_is_reported_as_drifted(tree: Path, tmp_path: Path) -> None:
    azure_id = f"{SUB}/deployments/chat"
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        {"model_id": "gpt-4o", "service": "azure_openai", "detected_via": [], "evidence": [{"source": "rdfa_report", "azure_id": azure_id.upper()}]},
    ], infrastructure=[{**_live_deployment("chat", "gpt-4.1"), "sources": ["live", "rdfa"]}])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4.1"], out
    assert out["not_converted"] == [{"model": "gpt-4o", "reason": "drifted_deployment_model"}]


def test_convert_names_why_each_row_was_not_converted(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        _model("gpt-4o", "azure_openai", "code"),
        _model("claude-sonnet-4-5", "anthropic", "code"),
        _model("prebuilt-invoice", "cognitive_document_intelligence", "terraform"),
        _model("custom-classifier", "azure_ml", "terraform"),
        _model("Kimi-K2.6", "azure_openai", "live_az"),
        {"service": "azure_openai", "model_id": ""},
        "not a row",
    ], infrastructure=[
        _iac_deployment("named-by-expression", None),
        _iac_deployment("kimi", "Kimi-K2.6", fmt="Moonshot AI"),
        _iac_deployment("ok", "gpt-4.1-mini"),
        _iac_deployment("spaced", "gpt 4o"),
        {"azure_id": f"{SUB}", "type": "Microsoft.CognitiveServices/accounts", "source": "live", "role": "account", "config": {"kind": "OpenAI"}},
    ])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0, out
    assert out["converted"] == ["gpt-4.1-mini"]
    assert out["not_converted"] == [
        {"model": "gpt-4o", "reason": "code_evidence_only"},
        {"model": "claude-sonnet-4-5", "reason": "code_evidence_only"},
        {"model": "prebuilt-invoice", "reason": "traditional_ml"},
        {"model": "custom-classifier", "reason": "traditional_ml"},
        {"model": "Kimi-K2.6", "reason": "non_openai_model"},
        {"model": "", "reason": "invalid_model_id"},
        {"model": None, "reason": "invalid_model_id"},
        {"model": None, "reason": "deployment_without_model", "deployment": "azurerm_cognitive_deployment.named-by-expression"},
        {"model": "Kimi-K2.6", "reason": "non_openai_model"},
        {"model": "gpt 4o", "reason": "invalid_model_id"},
    ]
    _validate(tree, legacy.parent / "ai-workload-profile.neutral.json")


@pytest.mark.parametrize("raw", [
    "gpt-4o-2024-08-06", "GPT-4O", "gpt-4o-mini-2024-07-18.ft-0123abcd", "gpt-35-turbo", "o1", "o4-mini", "gpt-image-1",
    "dall-e-3", "whisper", "tts", "tts-hd", "whisperer", "Phi-4", "model-router", "text-embedding-ada-002",
    "gpt-4o:2024", "gpt-4o/eu", "gpt_4o", "gpt-4ö", "gpt-4o+tools",
    "gpt-", "unknown", "-gpt-4o", "ft:gpt-4o-mini:acme::abc",
])
def test_every_deployment_model_name_converts_to_a_valid_profile_or_is_reported(raw, tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_live_deployment("d", raw), _iac_deployment("ok", "gpt-4.1")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0, out
    reported = [n["model"] for n in out["not_converted"]]
    converted = raw.lower() in out["converted"]
    assert converted != (raw in reported), out
    assert converted or out["not_converted"][0]["reason"] in ("invalid_model_id", "non_openai_model")
    _validate(tree, legacy.parent / "ai-workload-profile.neutral.json")


def test_wrongly_typed_azure_profile_items_are_skipped_not_crashed_on(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([
        {"model_id": "gpt-4o", "service": "azure_openai", "detected_via": 7, "evidence": "terraform"},
        {"model_id": "gpt-4.1", "service": "azure_openai", "detected_via": None, "evidence": [7, {"source": "live_az"}]},
        {"model_id": "gpt-4.1-nano", "service": "azure_openai", "detected_via": [], "evidence": []},
        {"model_id": "gpt-4o-mini", "service": "azure_openai", "detected_via": [], "evidence": [{"source": []}, {"source": {}}]},
    ], infrastructure=[
        7, {"role": "deployment", "address": "a", "config": "x"},
        {"role": "deployment", "source": "live", "sources": "rdfa", "config": {"model": {"name": 4}}},
        {"role": "deployment", "address": "b", "config": {"model": {"name": "4o", "format": "OpenAI"}}},
        {"role": "deployment", "source": "bicep", "config": {"model": "gpt-4.1-mini"}},
    ])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0, out
    assert out["converted"] == ["4o", "gpt-4.1"]
    assert out["not_converted"] == [{"model": "gpt-4o", "reason": "no_provenance"},
                                    {"model": "gpt-4.1-nano", "reason": "no_provenance"},
                                    {"model": "gpt-4o-mini", "reason": "no_provenance"},
                                    {"model": None, "reason": "deployment_without_model", "deployment": "a"},
                                    {"model": None, "reason": "invalid_model_id"},
                                    {"model": "gpt-4.1-mini", "reason": "no_provenance"}]
    assert _azure_source(legacy.parent / "ai-workload-profile.neutral.json")["model_families"] == ["gpt", "other"]
    _validate(tree, legacy.parent / "ai-workload-profile.neutral.json")


def test_a_model_converted_from_one_source_is_not_also_reported_as_not_converted(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("GPT-4o", "azure_openai", "code"), _model("gpt-4.1", "azure_openai", "code")],
                                         infrastructure=[_live_deployment("chat", "gpt-4o")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 0 and out["converted"] == ["gpt-4o"]
    assert out["not_converted"] == [{"model": "gpt-4.1", "reason": "code_evidence_only"}]


def test_convert_with_nothing_proved_and_no_scan_writes_nothing(tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([_model("gpt-4o", "azure_openai", "code")])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 1 and out["error"] == "no_ai_sources" and not out_path.exists()
    assert out["not_converted"] == [{"model": "gpt-4o", "reason": "code_evidence_only"}]


def test_a_direct_anthropic_run_hands_over_the_scan_unchanged(tree: Path, tmp_path: Path) -> None:
    scan_doc = {"schema_version": "1.0", "gateways": [], "ai_sources": [{
        "provider": "anthropic", "source_service": "anthropic_api", "model_families": ["claude"], "model_evidence": "observed",
        "models": ["claude-sonnet-4-5"], "model_observations": [{"normalized_model": "claude-sonnet-4-5", "raw_model": "claude-sonnet-4-5",
                                                                 "model_family": "claude",
                                                                 "evidence": [{"provenance": "code", "confidence": "high"}]}]}]}
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(scan_doc))
    run = _azure_run(tmp_path, infra=True, profile=_legacy([_model("claude-sonnet-4-5", "anthropic", "code")], ai_source="anthropic"))
    assert _cli(tree, "route", str(run))[1]["route"] == "delegate"
    code, out = _cli(tree, "convert", str(run), "--scan", str(scan))
    assert code == 0 and out["converted"] == []
    assert json.loads((run / "ai-workload-profile.neutral.json").read_text()) == scan_doc


def test_convert_adds_proof_to_an_azure_openai_source_the_scan_already_has(tree: Path, tmp_path: Path) -> None:
    scan_doc = _scan_profile()
    scan_doc["ai_sources"].append({"provider": "openai", "source_service": "azure_openai", "model_families": ["gpt"],
                                   "model_evidence": "observed", "models": ["gpt-4o"],
                                   "model_observations": [{"normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
                                                           "evidence": [{"provenance": "code", "confidence": "high"}]}]})
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(scan_doc))
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o"),
                                                             _live_deployment("embed", "text-embedding-3-large")])))
    out_path = legacy.parent / "ai-workload-profile.neutral.json"
    assert _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))[0] == 0
    source = _azure_source(out_path)
    assert source["models"] == ["gpt-4o", "text-embedding-3-large"] and source["model_families"] == ["embedding", "gpt"]
    assert [e["provenance"] for e in source["model_observations"][0]["evidence"]] == ["code", "live_api"]
    _validate(tree, out_path)


@pytest.mark.parametrize("upstream", [{"provider": "openai", "source_service": "azure_openai"}, {"provider": "openai"}],
                         ids=["azure-upstream", "service-less-openai-upstream"])
def test_convert_refuses_to_change_an_openai_source_a_gateway_routes_to(upstream, tree: Path, tmp_path: Path) -> None:
    service = upstream.get("source_service", "openai_api")
    scan_doc = {"schema_version": "1.0", "ai_sources": [{
        "provider": "openai", "source_service": service, "model_families": ["gpt"], "model_evidence": "observed",
        "models": ["gpt-4o"], "model_observations": [{"normalized_model": "gpt-4o", "raw_model": "openai/gpt-4o",
                                                      "model_family": "gpt", "evidence": [{"provenance": "code", "confidence": "high"}]}]}],
        "gateways": [{"product": "litellm", "type": "llm_router", "upstream_evidence": "observed", "upstreams": [
            {**upstream, "model_families": [{"family": "gpt", "model_evidence": "observed", "models": ["gpt-4o"]}]}]}]}
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps(scan_doc))
    _validate(tree, scan)
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_live_deployment("chat", "gpt-4.1")])))
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 1 and out["error"] == "convert_conflict" and not (legacy.parent / "ai-workload-profile.neutral.json").exists()


@pytest.mark.parametrize("bad", [b"not json", b"\xff\xfe{}", DEEP_JSON, json.dumps({"schema_version": "1.0", "ai_sources": [], "gateways": [],
                                                                         "summary": {}}).encode()])
def test_convert_rejects_a_scan_the_validator_rejects(bad, tree: Path, tmp_path: Path) -> None:
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o")])))
    scan = tmp_path / "scan.json"
    scan.write_bytes(bad)
    code, out = _cli(tree, "convert", str(legacy.parent), "--scan", str(scan))
    assert code == 1 and out["error"] in {"scan_unreadable", "scan_invalid"}
    assert not (legacy.parent / "ai-workload-profile.neutral.json").exists()


@pytest.mark.parametrize("legacy", [[], {"models": "gpt-4o"}, {"models": [], "infrastructure": {}}], ids=["list", "models-string", "infra-object"])
def test_convert_rejects_a_malformed_azure_profile(legacy, tree: Path, tmp_path: Path) -> None:
    (_legacy_dir(tmp_path) / "ai-workload-profile.json").write_text(json.dumps(legacy))
    code, out = _cli(tree, "convert", str(_legacy_dir(tmp_path)))
    assert code == 1 and out["error"] == "legacy_invalid"


def test_convert_refuses_when_the_sibling_is_not_present(tree: Path, tmp_path: Path) -> None:
    _break_validator(tree / "bedrock-migration-assessment")
    legacy = _legacy_dir(tmp_path) / "ai-workload-profile.json"
    legacy.write_text(json.dumps(_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o")])))
    code, out = _cli(tree, "convert", str(legacy.parent))
    assert code == 1 and out["error"] == "bma_tampered"


def test_convert_opens_the_handoff_with_both_profile_digests(tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True, profile=_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o")]))
    assert _cli(tree, "convert", str(run))[0] == 0
    record = json.loads((run / "ai-handoff.json").read_text())
    assert record == {"profile_digest": "sha256:" + _sha(run / "ai-workload-profile.json"), "status": "converted", "artifacts": {},
                      "infrastructure_moves": True,
                      "assessment_profile_digest": "sha256:" + _sha(run / "ai-workload-profile.neutral.json")}


@pytest.mark.parametrize("name", ["ai-workload-profile.neutral.json", "ai-handoff.json"])
def test_convert_never_writes_through_a_symlink(name, tree: Path, tmp_path: Path) -> None:
    run = _azure_run(tmp_path, infra=True, profile=_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o")]))
    outside = tmp_path / "outside.json"
    outside.write_text("keep")
    (run / name).symlink_to(outside)
    code, out = _cli(tree, "convert", str(run))
    assert code == 1 and out["error"] == "unsafe_destination", out
    assert outside.read_text() == "keep" and (run / name).is_symlink()


# --------------------------------------------------------------------------- host answers and accept

def test_host_answers_pass_region_and_compliance_in_the_assessment_shape(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure, compliance=["hipaa"])
    bma = _bma_run(tmp_path)
    code, out = _open(tree, azure, bma, "clarify")
    assert code == 0 and out["host_answers"] == ["compliance", "target_region"]
    host = json.loads((bma / "host-answers.json").read_text())
    assert host == {"host_skill": "azure-to-aws", "infrastructure_moves": True, "stop_after": "clarify", "design_constraints": {
        "target_region": {"value": "us-east-1", "chosen_by": "extracted", "source": "host:azure-to-aws",
                          "prompt": "Detected by azure-to-aws: us-east-1 (every resource is eastus)",
                          "design_consequence": "Bedrock resources deploy in us-east-1; model availability is checked for this region"},
        "compliance": {"value": ["hipaa"], "chosen_by": "user", "source": "host:azure-to-aws",
                       "prompt": "Do you have any compliance or regulatory requirements? (answered in azure-to-aws Clarify)",
                       "design_consequence": "hipaa gates Bedrock models, regions, and logging"}}}
    record = json.loads((azure / "ai-handoff.json").read_text())
    assert record == {"profile_digest": "sha256:" + _sha(azure / "ai-workload-profile.json"), "assessment_dir": bma.name,
                      "assessment_profile_digest": "sha256:" + _sha(bma / "ai-workload-profile.json"),
                      "status": "in_progress", "artifacts": {}, "infrastructure_moves": True}


@pytest.mark.parametrize(("row", "field", "want"), [
    ({"disposition": "ESSENTIAL", "value": [], "default": None}, "compliance", {"value": ["none"], "chosen_by": "user"}),
    ({"disposition": "ESSENTIAL", "value": None, "default": None, "unanswered": True}, "compliance", None),
    ({"disposition": "ESSENTIAL", "value": "none", "default": None}, "compliance", None),
    ({"disposition": "PROPOSED", "value": ["unknown"], "default": ["unknown"]}, "compliance", {"value": ["unknown"], "chosen_by": "default"}),
    ({"disposition": "PROPOSED", "value": "eu-west-1", "default": "us-east-1"}, "target_region", {"value": "eu-west-1", "chosen_by": "user"}),
    ({"value": "eu-west-1"}, "target_region", None),
    ({"disposition": "N/A", "value": [], "default": None, "reason": "x"}, "compliance", None),
    ({"disposition": "DETECTED", "value": "", "default": ""}, "target_region", None),
    ("eu-west-1", "target_region", None),
], ids=["empty-is-none", "unanswered", "scalar", "proposed-default", "proposed-changed", "no-disposition", "not-applicable", "empty-region",
        "not-a-row"])
def test_each_azure_row_maps_to_one_host_answer_or_none(row, field, want, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    (prefs["global"] if field == "target_region" else prefs["design_constraints"])[field] = row
    (azure / "preferences.json").write_text(json.dumps(prefs))
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "clarify")[0] == 0
    given = json.loads((bma / "host-answers.json").read_text())["design_constraints"]
    answer = given.get(field)
    assert (None if answer is None else {k: answer[k] for k in ("value", "chosen_by")}) == want
    assert answer is None or answer["source"] == "host:azure-to-aws"


@pytest.mark.parametrize("disposition", ["DETECTED", "PROPOSED", "ESSENTIAL"])
def test_every_host_answer_is_a_complete_assessment_wrapper(disposition, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure, compliance=["gdpr", "pci"])
    for section, field in (("global", "target_region"), ("design_constraints", "compliance")):
        prefs[section][field] = {**prefs[section][field], "disposition": disposition}
        prefs[section][field].pop("source", None)
    (azure / "preferences.json").write_text(json.dumps(prefs))
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "clarify")[0] == 0
    given = json.loads((bma / "host-answers.json").read_text())["design_constraints"]
    assert sorted(given) == ["compliance", "target_region"]
    for answer in given.values():
        assert answer["chosen_by"] in ("user", "default", "extracted") and answer["source"] == "host:azure-to-aws"
        assert "question_id" not in answer
        assert all(isinstance(answer[k], str) and answer[k].strip() for k in ("prompt", "design_consequence")), answer


def test_host_answers_for_an_ai_only_run_answer_nothing(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=False)
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "clarify")[0] == 0
    host = json.loads((bma / "host-answers.json").read_text())
    assert host["design_constraints"] == {} and host["infrastructure_moves"] is False


def test_an_infrastructure_run_needs_azure_preferences_before_the_handoff(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    bma = _bma_run(tmp_path)
    code, out = _open(tree, azure, bma, "estimate")
    assert code == 1 and out["error"] == "preferences_missing" and "azure-to-aws Clarify" in out["detail"]
    assert not (bma / "host-answers.json").exists()
    assert json.loads((azure / "ai-handoff.json").read_text())["status"] == "converted"


def test_host_answers_need_a_converted_profile(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    bma = _bma_run(tmp_path)
    code, out = _open(tree, azure, bma, "clarify", convert=False)
    assert code == 1 and out["error"] == "handoff_not_open"


def test_host_answers_refuse_a_run_that_assessed_another_profile(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _converted(azure, bma)
    record = json.loads((azure / "ai-handoff.json").read_text())
    record["assessment_profile_digest"] = "sha256:" + "0" * 64
    (azure / "ai-handoff.json").write_text(json.dumps(record))
    code, out = _open(tree, azure, bma, "clarify", convert=False)
    assert code == 1 and out["error"] == "assessment_profile_mismatch"
    assert json.loads((azure / "ai-handoff.json").read_text())["status"] == "converted" and not (bma / "host-answers.json").exists()


@pytest.mark.parametrize("initiated_by", [None, "GCP_TO_AWS"])
def test_host_answers_and_accept_refuse_a_run_this_skill_did_not_start(initiated_by, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "estimate")[0] == 0
    status = json.loads((bma / ".phase-status.json").read_text())
    status.pop("initiated_by")
    if initiated_by:
        status["initiated_by"] = initiated_by
    (bma / ".phase-status.json").write_text(json.dumps(status))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "handoff_mismatch" and not (azure / "aws-design-ai.json").exists()
    assert _open(tree, azure, bma, "estimate", convert=False)[1]["error"] == "handoff_mismatch"


def test_host_answers_never_write_through_a_symlink(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("keep")
    (bma / "host-answers.json").symlink_to(outside)
    code, out = _open(tree, azure, bma, "clarify")
    assert code == 1 and out["error"] == "unsafe_destination", out
    assert outside.read_text() == "keep"
    assert json.loads((azure / "ai-handoff.json").read_text())["status"] == "converted"


@pytest.mark.parametrize("held", [b"{not json", b"\xff\xfe{}", b"[]", DEEP_JSON])
def test_host_answers_replace_an_unreadable_host_answers_file(held, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    (bma / "host-answers.json").write_bytes(held)
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] in ("host_answers_unreadable", "host_answers_stale") and "host-answers" in out["detail"], out
    assert _open(tree, azure, bma, "estimate", convert=False)[0] == 0
    assert not (azure / "aws-design-ai.json").exists()
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0


def test_accept_clarify_copies_ai_answers_into_azure_preferences(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path, {"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "pending"})
    _open(tree, azure, bma, "clarify")
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 0 and out["ok"] is True, out
    merged = json.loads((azure / "preferences.json").read_text())
    bma_prefs = json.loads((bma / "preferences.json").read_text())
    assert merged["ai_constraints"] == bma_prefs["ai_constraints"]
    assert merged["startup_constraints"] == bma_prefs["startup_constraints"]
    assert {k: merged[k] for k in ("global", "design_constraints", "clarify_status", "phase")} == \
        {k: prefs[k] for k in ("global", "design_constraints", "clarify_status", "phase")}
    assert merged["metadata"]["ai_preferences_source"] == {"assessment_dir": bma.name, "sha256": _sha(bma / "preferences.json"),
                                                           "startup_keys": ["startup_program_status"], "startup_before": {},
                                                           "startup_absent": True}
    record = json.loads((azure / "ai-handoff.json").read_text())
    assert record["status"] == "in_progress" and record["through"] == "clarify"
    assert record["artifacts"] == {"preferences.json": _sha(bma / "preferences.json")}
    assert not (azure / "aws-design-ai.json").exists()


def test_accept_clarify_for_an_ai_only_run_writes_the_assessment_preferences(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=False)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "clarify")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")[0] == 0
    written = json.loads((azure / "preferences.json").read_text())
    source = written["metadata"].pop("ai_preferences_source")
    assert written == json.loads((bma / "preferences.json").read_text()) and source["sha256"] == _sha(bma / "preferences.json")


@pytest.mark.parametrize("before", [{"phase": "clarify", "metadata": {"migration_type": "ai-only"}, "design_constraints": {}}, None],
                         ids=["earlier-azure-preferences", "no-earlier-preferences"])
def test_an_ai_only_accept_keeps_earlier_preferences_for_the_withdrawal(before, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=False)
    if before is not None:
        (azure / "preferences.json").write_text(json.dumps(before))
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    for through in ("clarify", "estimate"):
        assert _cli(tree, "accept", str(azure), str(bma), "--through", through)[0] == 0
    (azure / "ai-workload-profile.json").unlink()
    assert _cli(tree, "route", str(azure))[1]["route"] == "no_ai"
    prefs = azure / "preferences.json"
    assert (json.loads(prefs.read_text()) if prefs.exists() else None) == before


@pytest.mark.parametrize(("held", "advice"), [(b"[]", "move it aside"), (DEEP_JSON, "Clarify again")], ids=["list", "too-deep"])
def test_an_ai_only_accept_stops_on_earlier_preferences_that_are_not_an_object(held, advice, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=False)
    (azure / "preferences.json").write_bytes(held)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "clarify")
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "preferences_unreadable" and advice in out["detail"]
    assert (azure / "preferences.json").read_bytes() == held


def test_accept_estimate_copies_the_design_and_estimate_and_closes_the_handoff(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 0, out
    for name in ("aws-design-ai.json", "estimation-ai.json"):
        assert (azure / name).read_bytes() == (bma / name).read_bytes()
    assert json.loads((azure / "ai-workload-profile.json").read_text())["summary"]["ai_source"] == "azure_openai"
    record = json.loads((azure / "ai-handoff.json").read_text())
    assert record["status"] == "assessment_completed" and record["through"] == "estimate"
    assert set(record["artifacts"]) == {"preferences.json", "aws-design-ai.json", "estimation-ai.json"}


def test_accepting_phase_by_phase_never_reports_unchanged_answers_as_stale(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "estimate")[0] == 0
    for through in ("clarify", "design", "estimate"):
        code, out = _cli(tree, "accept", str(azure), str(bma), "--through", through)
        assert code == 0, out


def test_accept_stops_on_a_run_that_is_not_ready(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path, {"discover": "completed", "clarify": "completed", "design": "in_progress", "estimate": "pending"})
    _open(tree, azure, bma, "design")
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "design")
    assert code == 1 and out["error"] == "assessment_not_ready" and out["reason"] == "phase_incomplete"
    assert not (azure / "aws-design-ai.json").exists()


def test_accept_fails_closed_when_readiness_reports_a_wrong_hash(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    readiness = tree / "bedrock-migration-assessment" / "scripts" / "readiness.py"
    readiness.write_text(readiness.read_text().replace('hashlib.sha256(read[f]).hexdigest()', '"0" * 64'))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "bma_tampered"
    assert not (azure / "aws-design-ai.json").exists() and not (azure / "estimation-ai.json").exists()


@pytest.mark.parametrize("output", ['import sys; sys.stdout.buffer.write(b"\\xff\\xfe{}")\n', 'print("ready")\n', 'print("[" * 200000)\n'],
                         ids=["not-utf8", "not-json", "too-deep"])
def test_accept_fails_closed_when_readiness_prints_garbage(output, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    (tree / "bedrock-migration-assessment" / "scripts" / "readiness.py").write_text(output)
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "bma_tampered"


def test_accept_names_an_assessment_file_removed_after_readiness(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    readiness = tree / "bedrock-migration-assessment" / "scripts" / "readiness.py"
    readiness.write_text(readiness.read_text().replace('if __name__ == "__main__":', (
        "import atexit as _atexit\n"
        "if 'estimate' in sys.argv:\n"
        "    _atexit.register(lambda: (Path(sys.argv[1]) / 'estimation-ai.json').unlink(missing_ok=True))\n"
        'if __name__ == "__main__":'), 1))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "bma_tampered", out
    assert not (azure / "aws-design-ai.json").exists()


@pytest.mark.parametrize("name", ["aws-design-ai.json", "estimation-ai.json", "preferences.json", "ai-handoff.json"])
def test_accept_never_writes_through_a_symlink(name, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    outside = tmp_path / "outside.json"
    shutil.copy(azure / name, outside) if (azure / name).exists() else outside.write_text("{}")
    before = outside.read_bytes()
    (azure / name).unlink(missing_ok=True)
    (azure / name).symlink_to(outside)
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "unsafe_destination", out
    assert outside.read_bytes() == before
    assert name == "aws-design-ai.json" or not (azure / "aws-design-ai.json").exists()


def test_accept_stops_when_discovery_changed_after_the_handoff(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([])))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 1 and out["error"] == "profile_changed"
    assert _open(tree, azure, bma, "estimate", convert=False)[1]["error"] == "profile_changed"


def test_accept_stops_when_azure_answers_changed_after_the_handoff(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    prefs["global"]["target_region"]["value"] = "eu-west-1"
    (azure / "preferences.json").write_text(json.dumps(prefs))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "host_answers_stale" and "host-answers" in out["detail"]


def test_new_host_answers_after_an_estimate_accept_let_clarify_be_accepted_again(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    prefs["global"]["target_region"]["value"] = "eu-west-1"
    (azure / "preferences.json").write_text(json.dumps({**json.loads((azure / "preferences.json").read_text()), "global": prefs["global"]}))
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[1]["error"] == "host_answers_stale"
    assert _open(tree, azure, bma, "clarify", convert=False)[0] == 0
    assert not (azure / "aws-design-ai.json").exists() and not (azure / "estimation-ai.json").exists()
    assert json.loads((azure / "preferences.json").read_text()) == prefs
    bma_prefs = json.loads((bma / "preferences.json").read_text())
    bma_prefs["design_constraints"]["target_region"]["value"] = "eu-west-1"
    (bma / "preferences.json").write_text(json.dumps(bma_prefs))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 0, out
    assert json.loads((azure / "ai-handoff.json").read_text())["through"] == "clarify"


def test_new_host_answers_never_accept_an_assessment_made_under_the_old_ones(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    prefs["global"]["target_region"]["value"] = "eu-west-1"
    (azure / "preferences.json").write_text(json.dumps({**json.loads((azure / "preferences.json").read_text()), "global": prefs["global"]}))
    assert _open(tree, azure, bma, "estimate", convert=False)[0] == 0
    for through in ("clarify", "design", "estimate"):
        code, out = _cli(tree, "accept", str(azure), str(bma), "--through", through)
        assert code == 1 and out["error"] == "assessment_not_ready" and out["reason"] == "host_answers_mismatch", out
    assert not (azure / "aws-design-ai.json").exists() and json.loads((azure / "preferences.json").read_text()) == prefs


def _failing_write(module, name: str):
    real = module._write_bytes

    def write(path, data):
        if path.name == name:
            raise OSError(28, "No space left on device", str(path))
        real(path, data)
    return write


def test_an_accept_interrupted_between_copies_can_still_be_withdrawn(tree: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    module = _load_module(tree)
    monkeypatch.setattr(module, "_write_bytes", _failing_write(module, "estimation-ai.json"))
    assert module.main(["accept", str(azure), str(bma), "--through", "estimate"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "filesystem_error" and "estimation-ai.json" in out["detail"] and str(tmp_path) not in out["detail"]
    assert (azure / "aws-design-ai.json").exists() and not list(azure.glob(".estimation-ai.json.*"))
    record = json.loads((azure / "ai-handoff.json").read_text())
    assert "through" not in record and set(record["pending_artifacts"]) == {"aws-design-ai.json", "estimation-ai.json"}
    (azure / "ai-workload-profile.json").unlink()
    assert _cli(tree, "route", str(azure))[1]["route"] == "no_ai"
    assert not (azure / "aws-design-ai.json").exists() and json.loads((azure / "preferences.json").read_text()) == prefs


def test_an_interrupted_accept_retried_through_an_earlier_phase_removes_the_later_copy(tree: Path, tmp_path: Path, monkeypatch,
                                                                                         capsys) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    module = _load_module(tree)
    monkeypatch.setattr(module, "_write_bytes", _failing_write(module, "estimation-ai.json"))
    assert module.main(["accept", str(azure), str(bma), "--through", "estimate"]) == 1
    capsys.readouterr()
    assert (azure / "aws-design-ai.json").exists()
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 0, out
    assert not (azure / "aws-design-ai.json").exists()
    assert set(json.loads((azure / "ai-handoff.json").read_text())["artifacts"]) == {"preferences.json"}


def test_an_interrupted_accept_finishes_when_run_again(tree: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    module = _load_module(tree)
    monkeypatch.setattr(module, "_write_bytes", _failing_write(module, "aws-design-ai.json"))
    assert module.main(["accept", str(azure), str(bma), "--through", "estimate"]) == 1
    capsys.readouterr()
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")
    assert code == 0, out
    record = json.loads((azure / "ai-handoff.json").read_text())
    assert record["status"] == "assessment_completed" and "pending_artifacts" not in record


def test_new_host_answers_interrupted_before_the_reset_record_is_saved_reopen_on_retry(tree: Path, tmp_path: Path, monkeypatch,
                                                                                         capsys) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    prefs["global"]["target_region"]["value"] = "eu-west-1"
    (azure / "preferences.json").write_text(json.dumps({**json.loads((azure / "preferences.json").read_text()), "global": prefs["global"]}))
    module = _load_module(tree)
    monkeypatch.setattr(module, "_write_bytes", _failing_write(module, "ai-handoff.json"))
    assert module.main(["host-answers", str(azure), str(bma), "--stop-after", "clarify"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "filesystem_error"
    monkeypatch.undo()
    assert _open(tree, azure, bma, "clarify", convert=False)[0] == 0
    bma_prefs = json.loads((bma / "preferences.json").read_text())
    bma_prefs["design_constraints"]["target_region"]["value"] = "eu-west-1"
    (bma / "preferences.json").write_text(json.dumps(bma_prefs))
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 0, out
    assert json.loads((azure / "ai-handoff.json").read_text())["through"] == "clarify"


def test_repeating_unchanged_host_answers_keeps_the_accepted_design(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "design")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "design")[0] == 0
    assert _open(tree, azure, bma, "estimate", convert=False)[0] == 0
    assert (azure / "aws-design-ai.json").exists()
    assert json.loads((azure / "ai-handoff.json").read_text())["through"] == "design"


def test_accept_never_moves_a_handoff_back_to_an_earlier_phase(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "accept_regressed"
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0


def test_accept_without_an_open_handoff_or_with_another_dir_is_refused(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[1]["error"] == "handoff_not_open"
    _open(tree, azure, bma, "estimate")
    other = bma.parent / "bma-1125-2200"
    shutil.copytree(bma, other)
    code, out = _cli(tree, "accept", str(azure), str(other), "--through", "estimate")
    assert code == 1 and out["error"] == "handoff_mismatch"


def test_accept_stops_when_azure_preferences_disappear_after_the_handoff(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "estimate")[0] == 0
    (azure / "preferences.json").unlink()
    code, out = _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")
    assert code == 1 and out["error"] == "preferences_missing"
    assert not (azure / "preferences.json").exists()


@pytest.mark.parametrize("infra_before", [True, False])
def test_a_change_in_whether_infrastructure_moves_reopens_the_handoff(infra_before, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=infra_before)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    assert _open(tree, azure, bma, "estimate")[0] == 0
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    resources = [{"azure_type": "Microsoft.CognitiveServices/accounts"}] + ([] if infra_before else [{"azure_type": "Microsoft.Web/sites"}])
    (azure / "azure-resource-inventory.json").write_text(json.dumps({"resources": resources}))
    for args in (("host-answers", str(azure), str(bma), "--stop-after", "estimate"), ("accept", str(azure), str(bma), "--through", "estimate")):
        code, out = _cli(tree, *args)
        assert code == 1 and out["error"] == "infrastructure_changed", out
    assert _cli(tree, "route", str(azure))[1]["route"] == "delegate"
    assert not (azure / "ai-handoff.json").exists() and not (azure / "aws-design-ai.json").exists()


@pytest.mark.parametrize("field", [{"artifacts": ["aws-design-ai.json"]}, {"pending_artifacts": "x"}, {"through": None},
                                   {"through": "generate"}], ids=["artifacts-list", "pending-string", "through-null", "through-unknown"])
def test_a_handoff_record_with_malformed_fields_is_a_named_error(field, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _converted(azure, bma)
    record = json.loads((azure / "ai-handoff.json").read_text()) | {"status": "in_progress"} | field
    (azure / "ai-handoff.json").write_text(json.dumps(record))
    for command in (("host-answers", str(azure), str(bma), "--stop-after", "clarify"), ("accept", str(azure), str(bma), "--through", "clarify")):
        code, out = _cli(tree, *command)
        assert code == 1 and out["error"] == "handoff_unreadable"
    (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([_model("gpt-4.1", "azure_openai", "code")])))
    assert _cli(tree, "route", str(azure))[1]["route"] == "delegate"
    assert not (azure / "ai-handoff.json").exists()


@pytest.mark.parametrize("change", [
    lambda p: p.update(design_constraints=["compliance"]),
    lambda p: p.update(**{"global": "eastus"}),
    lambda p: p.update(metadata="wizard"),
    lambda p: p.update(startup_constraints=["credits"]),
    lambda p: p["metadata"].update(ai_preferences_source={"startup_keys": "credits"}),
    lambda p: p["metadata"].update(ai_preferences_source=[]),
    lambda p: p.update(**{"global": ""}),
    lambda p: p.update(startup_constraints=[]),
    lambda p: p.update(metadata=[]),
    lambda p: p.update(ai_constraints=None),
], ids=["design-list", "global-string", "metadata-string", "startup-list", "startup-keys-string", "source-list",
        "global-empty-string", "startup-empty-list", "metadata-empty-list", "ai-null"])
@pytest.mark.parametrize("command", ["host-answers", "route"])
def test_azure_preferences_with_a_wrong_field_type_get_a_named_error(change, command, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    bma = _bma_run(tmp_path)
    prefs = _azure_prefs(azure)
    change(prefs)
    (azure / "preferences.json").write_text(json.dumps(prefs))
    if command == "host-answers":
        code, out = _open(tree, azure, bma, "estimate")
    else:
        (azure / "ai-workload-profile.json").unlink()
        code, out = _cli(tree, "route", str(azure))
    assert code == 1 and out["error"] == "preferences_unreadable", out


# --------------------------------------------------------------------------- withdrawing earlier copies

@pytest.mark.parametrize("reroute", ["no_ai", "traditional_ml", "defer", "infra_only", "delegate"])
def test_every_route_withdraws_what_an_earlier_accept_copied(reroute, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    args = ()
    if reroute == "no_ai":
        (azure / "ai-workload-profile.json").unlink()
    elif reroute == "traditional_ml":
        (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([_model("read", "cognitive_vision", "terraform")], ai_source="other")))
    elif reroute == "defer":
        shutil.rmtree(tree / "bedrock-migration-assessment")
    elif reroute == "infra_only":
        args = ("--infra-only",)
    else:
        (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([_model("gpt-4.1", "azure_openai", "code")])))
    out = _cli(tree, "route", str(azure), *args)[1]
    assert out["route"] == ("defer" if reroute == "infra_only" else reroute)
    if reroute == "delegate":
        assert _cli(tree, "convert", str(azure))[1]["error"] == "no_ai_sources"
    for name in ("aws-design-ai.json", "estimation-ai.json", "ai-workload-profile.neutral.json"):
        assert not (azure / name).exists(), name
    assert json.loads((azure / "preferences.json").read_text()) == prefs
    assert (azure / "ai-handoff.json").exists() is (reroute in ("defer", "infra_only"))


@pytest.mark.parametrize("profile_changes", [True, False])
@pytest.mark.parametrize("sibling", ["absent", "tampered"])
def test_a_stop_withdraws_copies_only_when_they_no_longer_match_the_profile(profile_changes, sibling, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=False)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    if profile_changes:
        (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([_model("gpt-4.1", "azure_openai", "code")])))
    if sibling == "absent":
        shutil.rmtree(tree / "bedrock-migration-assessment")
    else:
        _break_validator(tree / "bedrock-migration-assessment")
    code, out = _cli(tree, "route", str(azure))
    assert code == 1 and out["route"] == "stop"
    for name in ("aws-design-ai.json", "estimation-ai.json", "preferences.json", "ai-handoff.json"):
        assert (azure / name).exists() is not profile_changes, name


def test_delegating_again_keeps_a_handoff_for_the_same_profile(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "design")[0] == 0
    assert _cli(tree, "route", str(azure))[1]["route"] == "delegate"
    assert (azure / "aws-design-ai.json").exists()
    assert json.loads((azure / "ai-handoff.json").read_text())["through"] == "design"


def test_delegating_after_a_deferral_clears_the_deferral(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    assert _cli(tree, "route", str(azure), "--infra-only")[1]["route"] == "defer"
    assert _cli(tree, "route", str(azure))[1]["route"] == "delegate"
    assert not (azure / "ai-handoff.json").exists()


@pytest.mark.parametrize("record", [b"[]", b'"converted"', b"{not json", b"\xff\xfe{}", DEEP_JSON])
@pytest.mark.parametrize(("args", "want"), [((), "delegate"), (("--infra-only",), "defer")])
def test_rerouting_replaces_a_handoff_record_that_is_not_an_object(record, args, want, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    (azure / "ai-handoff.json").write_bytes(record)
    assert _cli(tree, "route", str(azure), *args)[1]["route"] == want
    held = azure / "ai-handoff.json"
    assert not held.exists() if want == "delegate" else json.loads(held.read_text())["status"] == "deferred"


def test_rerouting_keeps_an_ai_design_the_handoff_did_not_copy(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    (azure / "aws-design-ai.json").write_text("{}")
    (azure / "ai-workload-profile.json").unlink()
    assert _cli(tree, "route", str(azure))[1]["route"] == "no_ai"
    assert (azure / "aws-design-ai.json").read_text() == "{}"


def test_rerouting_never_follows_a_symlinked_copy(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    outside = tmp_path / "outside.json"
    shutil.copy(azure / "aws-design-ai.json", outside)
    (azure / "aws-design-ai.json").unlink()
    (azure / "aws-design-ai.json").symlink_to(outside)
    (azure / "ai-workload-profile.json").unlink()
    assert _cli(tree, "route", str(azure))[1]["route"] == "no_ai"
    assert outside.exists() and (azure / "aws-design-ai.json").is_symlink()


@pytest.mark.parametrize("azure_ai", [True, False], ids=["azure-ai-constraints", "no-azure-ai-constraints"])
def test_withdrawing_restores_every_field_the_accept_replaced(azure_ai, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    host_value = {"value": "has_credits", "chosen_by": "user", "prompt": "p", "design_consequence": "c"}
    prefs["startup_constraints"] = {"startup_program_status": host_value, "funding_stage": host_value}
    if azure_ai:
        prefs["ai_constraints"] = {"ai_priority": {"value": "quality", "chosen_by": "user"}}
    (azure / "preferences.json").write_text(json.dumps(prefs))
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "clarify")[0] == 0
    bma_prefs = json.loads((bma / "preferences.json").read_text())
    bma_prefs["startup_constraints"] = {"funding_stage": {**host_value, "value": "seed", "chosen_by": "default"}}
    (bma / "preferences.json").write_text(json.dumps(bma_prefs))
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    merged = json.loads((azure / "preferences.json").read_text())
    assert merged["startup_constraints"] == {"startup_program_status": host_value, "funding_stage": bma_prefs["startup_constraints"]["funding_stage"]}
    assert merged["ai_constraints"] == bma_prefs["ai_constraints"]
    (azure / "ai-workload-profile.json").unlink()
    _cli(tree, "route", str(azure))
    assert json.loads((azure / "preferences.json").read_text()) == prefs


def test_converting_again_removes_what_the_previous_handoff_copied(tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True, profile=_legacy([], infrastructure=[_live_deployment("chat", "gpt-4o")]))
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    assert _cli(tree, "convert", str(azure))[0] == 0
    assert not (azure / "aws-design-ai.json").exists() and not (azure / "estimation-ai.json").exists()
    assert json.loads((azure / "preferences.json").read_text()) == prefs
    assert json.loads((azure / "ai-handoff.json").read_text())["status"] == "converted"


@pytest.mark.parametrize("reroute", ["defer", "delegate"])
def test_a_reroute_followed_by_a_failing_convert_leaves_no_stale_copies(reroute, tree: Path, tmp_path: Path) -> None:
    azure = _azure_run(tmp_path, infra=True)
    prefs = _azure_prefs(azure)
    bma = _bma_run(tmp_path)
    _open(tree, azure, bma, "estimate")
    assert _cli(tree, "accept", str(azure), str(bma), "--through", "estimate")[0] == 0
    (azure / "ai-workload-profile.json").write_text(json.dumps(_legacy([_model("gpt-4.1", "azure_openai", "code")])))
    if reroute == "defer":
        assert _cli(tree, "route", str(azure), "--infra-only")[1]["route"] == "defer"
    else:
        assert _cli(tree, "route", str(azure))[1]["route"] == "delegate"
    _break_validator(tree / "bedrock-migration-assessment")
    assert _cli(tree, "convert", str(azure))[1]["error"] == "bma_tampered"
    for name in ("aws-design-ai.json", "estimation-ai.json", "ai-workload-profile.neutral.json"):
        assert not (azure / name).exists(), name
    assert json.loads((azure / "preferences.json").read_text()) == prefs
    held = azure / "ai-handoff.json"
    assert (held.exists() and json.loads(held.read_text())["status"] == "deferred") is (reroute == "defer")
