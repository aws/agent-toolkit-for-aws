"""Tests for bedrock-migration-assessment's readiness handshake (scripts/readiness.py), the only way another skill may consume a run."""
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
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"
ALL_DONE = {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed"}


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


READY = _module("bma_readiness", "readiness.py")


def _run(tmp_path: Path, fixture: str = "bma-estimate-measured", phases: dict | None = None, **status) -> Path:
    run = tmp_path / "bma-1116-1900"
    run.mkdir()
    for f in (FIXTURES / fixture).iterdir():
        shutil.copy(f, run / f.name)
    doc = {"migration_id": "bma-1116-1900", "run_id": RUN_ID, "last_updated": "2026-11-16T19:00:00Z", "current_phase": "complete",
           "phases": dict(ALL_DONE if phases is None else phases)}
    doc.update(status)
    (run / ".phase-status.json").write_text(json.dumps(doc))
    return run


def _cli(run: Path, through: str, capsys) -> tuple[int, dict]:
    code = READY.main([str(run), "--through", through])
    return code, json.loads(capsys.readouterr().out)


def _edit(path: Path, change) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


# --------------------------------------------------------------------------- ready runs

@pytest.mark.parametrize("fixture", ["bma-estimate-measured", "bma-estimate-tier-high-volume", "bma-estimate-price-unavailable"])
@pytest.mark.parametrize("through", ["design", "estimate"])
def test_a_finished_run_is_ready(fixture, through, tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, fixture)
    code, out = _cli(run, through, capsys)
    assert code == 0 and out["ready"] is True and out["run_id"] == RUN_ID and out["through"] == through
    expected = {"ai-workload-profile.json", "preferences.json", "aws-design-ai.json"} | ({"estimation-ai.json"} if through == "estimate" else set())
    assert set(out["artifacts"]) == expected
    for name, entry in out["artifacts"].items():
        assert entry["sha256"] == hashlib.sha256((run / name).read_bytes()).hexdigest()


def test_design_readiness_does_not_need_estimate(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, phases={**ALL_DONE, "estimate": "pending"})
    (run / "estimation-ai.json").unlink()
    assert _cli(run, "design", capsys)[0] == 0
    code, out = _cli(run, "estimate", capsys)
    assert code == 1 and out["reason"] == "phase_incomplete" and "phases.estimate" in out["detail"]


# --------------------------------------------------------------------------- not ready

@pytest.mark.parametrize(("phases", "through", "phase"), [
    ({**ALL_DONE, "clarify": "in_progress"}, "design", "clarify"),
    ({**ALL_DONE, "design": "pending"}, "design", "design"),
    ({**ALL_DONE, "design": "in_progress"}, "estimate", "design"),
    ({"discover": "completed", "clarify": "completed", "design": "completed"}, "estimate", "estimate"),
    ({"discover": "in_progress", "clarify": "pending"}, "design", "discover"),
])
def test_any_earlier_phase_not_completed_is_not_ready(phases, through, phase, tmp_path: Path, capsys) -> None:
    code, out = _cli(_run(tmp_path, phases=phases), through, capsys)
    assert code == 1 and out["reason"] == "phase_incomplete" and f"phases.{phase}" in out["detail"]


@pytest.mark.parametrize(("status", "reason"), [
    ({"owning_skill": "GCP_TO_AWS"}, "not_this_skill"),
    ({"migration_id": "1116-1900"}, "not_this_skill"),
    ({"run_id": "not-a-uuid"}, "status_invalid"),
    ({"phases": {"discover": "done"}}, "status_invalid"),
    ({"phases": {}}, "status_invalid"),
], ids=["gcp-owned", "gcp-id", "bad-run-id", "bad-phase-value", "no-phases"])
def test_a_status_another_skill_wrote_or_a_broken_status_is_not_ready(status, reason, tmp_path: Path, capsys) -> None:
    code, out = _cli(_run(tmp_path, **status), "design", capsys)
    assert code == 1 and out["reason"] == reason


@pytest.mark.parametrize(("break_run", "reason"), [
    (lambda r: (r / ".phase-status.json").unlink(), "status_not_found"),
    (lambda r: (r / ".phase-status.json").write_text("{"), "status_unreadable"),
    (lambda r: (r / ".phase-status.json").write_text("[]"), "status_invalid"),
    (lambda r: (r / "aws-design-ai.json").unlink(), "artifact_missing"),
    (lambda r: (r / "preferences.json").write_text("not json"), "artifact_unreadable"),
    (lambda r: (r / "preferences.json").write_text("[]"), "preferences_invalid"),
    (lambda r: _edit(r / "preferences.json", lambda d: d["metadata"].update(migration_type="full")), "preferences_invalid"),
    (lambda r: _edit(r / "ai-workload-profile.json", lambda d: d.update(summary={})), "profile_invalid"),
    (lambda r: _edit(r / "aws-design-ai.json", lambda d: d["design_blocks"].clear()), "design_invalid"),
    (lambda r: _edit(r / "estimation-ai.json", lambda d: d["cost_comparison"].update(projected_bedrock_monthly=1.0)), "estimate_invalid"),
    (lambda r: _edit(r / "openai-usage-profile.json", lambda d: d["usage_by_model"][0].update(input_tokens=9_000_000)), "estimate_invalid"),
    (lambda r: _edit(r / "openai-usage-profile.json", lambda d: d.update(metadata={})), "estimate_invalid"),
], ids=["no-status", "bad-status-json", "status-array", "no-design", "prefs-not-json", "prefs-array", "prefs-not-ai-only",
        "legacy-profile", "design-tampered", "estimate-tampered", "usage-changed-after-estimate", "usage-broken"])
def test_a_missing_tampered_or_stale_artifact_fails_closed(break_run, reason, tmp_path: Path, capsys) -> None:
    run = _run(tmp_path)
    break_run(run)
    code, out = _cli(run, "estimate", capsys)
    assert code == 1 and out["ready"] is False and out["reason"] == reason and out["detail"]


def test_a_missing_run_directory_is_not_ready(tmp_path: Path, capsys) -> None:
    code, out = _cli(tmp_path / "nope", "design", capsys)
    assert code == 1 and out["reason"] == "run_not_found"


def test_a_consumer_skill_can_run_it_from_its_own_directory(tmp_path: Path) -> None:
    run = _run(tmp_path)
    consumer = PLUGIN_ROOT / "skills" / "llm-to-bedrock"
    script = consumer / ".." / "bedrock-migration-assessment" / "scripts" / "readiness.py"
    out = subprocess.run([sys.executable, str(script), str(run), "--through", "estimate"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["ready"] is True


def test_design_readiness_ignores_a_broken_estimate(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path)
    (run / "estimation-ai.json").write_text("not json")
    assert _cli(run, "design", capsys)[0] == 0
    assert _cli(run, "estimate", capsys)[1]["reason"] == "artifact_unreadable"


def test_the_skill_documents_exactly_the_reasons_the_script_returns() -> None:
    import re
    source = (BMA / "scripts" / "readiness.py").read_text(encoding="utf-8")
    returned = set(re.findall(r'NotReady\("([a-z_]+)"', source))
    returned |= {r for pair in re.findall(r'_json\([^,]+, "([a-z_]+)", "([a-z_]+)"', source) for r in pair}
    section = SKILL[SKILL.index("## Readiness for other skills"):SKILL.index("## Definitions")]
    documented = set(re.findall(r"`([a-z]+_[a-z_]+)`", section))
    assert returned == documented
    assert "python3 scripts/readiness.py <MIGRATION_DIR> --through design|estimate" in section
    assert "must not read `.phase-status.json` itself" in section
