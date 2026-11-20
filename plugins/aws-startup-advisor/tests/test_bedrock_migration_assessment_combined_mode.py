"""Tests for bedrock-migration-assessment's combined mode: a host skill's host-answers.json and readiness --through clarify."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")
CLARIFY = (BMA / "references" / "phases" / "clarify" / "clarify-ai-only.md").read_text(encoding="utf-8")
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"
THROUGH_CLARIFY = {"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "pending"}


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


READY = _module("bma_readiness_combined", "readiness.py")


def _run(tmp_path: Path, phases: dict, host: dict | None = None) -> Path:
    run = tmp_path / "bma-1119-2100"
    run.mkdir()
    for name in ("ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json", "openai-usage-profile.json"):
        shutil.copy(FIXTURES / "bma-estimate-measured" / name, run / name)
    status = {"migration_id": run.name, "run_id": RUN_ID, "last_updated": "2026-11-19T21:00:00Z",
              "initiated_by": "GCP_TO_AWS", "phases": phases}
    (run / ".phase-status.json").write_text(json.dumps(status))
    if host is not None:
        (run / "host-answers.json").write_text(json.dumps(host))
    return run


def _host(run_prefs: dict, **design) -> dict:
    constraints = {k: run_prefs["design_constraints"][k] for k in ("target_region", "compliance")}
    constraints.update(design)
    return {"host_skill": "gcp-to-aws", "infrastructure_moves": True, "stop_after": "clarify", "design_constraints": constraints}


def _prefs() -> dict:
    return json.loads((FIXTURES / "bma-estimate-measured" / "preferences.json").read_text())


def _cli(run: Path, through: str, capsys) -> tuple[int, dict]:
    code = READY.main([str(run), "--through", through])
    return code, json.loads(capsys.readouterr().out)


def test_clarify_readiness_needs_only_discover_and_clarify(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, THROUGH_CLARIFY)
    (run / "aws-design-ai.json").unlink()
    code, out = _cli(run, "clarify", capsys)
    assert code == 0 and out["ready"] is True and out["through"] == "clarify"
    assert set(out["artifacts"]) == {"ai-workload-profile.json", "preferences.json"}


def test_clarify_readiness_still_checks_preferences(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, THROUGH_CLARIFY)
    (run / "preferences.json").write_text("[]")
    code, out = _cli(run, "clarify", capsys)
    assert code == 1 and out["reason"] == "preferences_invalid"


def test_clarify_readiness_fails_when_clarify_is_not_completed(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, {**THROUGH_CLARIFY, "clarify": "in_progress"})
    code, out = _cli(run, "clarify", capsys)
    assert code == 1 and out["reason"] == "phase_incomplete" and "phases.clarify" in out["detail"]


@pytest.mark.parametrize("through", ["clarify", "design", "estimate"])
def test_host_answers_that_preferences_kept_are_ready(through, tmp_path: Path, capsys) -> None:
    phases = THROUGH_CLARIFY if through == "clarify" else dict.fromkeys(THROUGH_CLARIFY, "completed")
    run = _run(tmp_path, phases, _host(_prefs()))
    code, out = _cli(run, through, capsys)
    assert code == 0 and out["ready"] is True


@pytest.mark.parametrize("field", ["compliance", "target_region"])
def test_preferences_that_changed_a_host_answer_are_not_ready(field, tmp_path: Path, capsys) -> None:
    new = {"compliance": ["gdpr"], "target_region": "eu-west-1"}[field]
    host = _host(_prefs(), **{field: {**_prefs()["design_constraints"][field], "value": new}})
    run = _run(tmp_path, THROUGH_CLARIFY, host)
    code, out = _cli(run, "clarify", capsys)
    assert code == 1 and out["reason"] == "host_answers_mismatch" and field in out["detail"]


def test_a_host_answer_preferences_dropped_is_not_ready(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, THROUGH_CLARIFY, _host(_prefs()))
    prefs = _prefs()
    del prefs["design_constraints"]["compliance"]
    (run / "preferences.json").write_text(json.dumps(prefs))
    code, out = _cli(run, "clarify", capsys)
    assert code == 1 and out["reason"] == "host_answers_mismatch" and "compliance" in out["detail"]


@pytest.mark.parametrize("host", [
    "not json",
    "[]",
    json.dumps({"host_skill": "gcp-to-aws", "design_constraints": {"ai_priority": {"value": "cost"}}}),
    json.dumps({"host_skill": "gcp-to-aws", "design_constraints": {"compliance": ["none"]}}),
    json.dumps({"design_constraints": {}}),
    json.dumps({"host_skill": "gcp-to-aws", "infrastructure_moves": True, "stop_after": "generate", "design_constraints": {}}),
    json.dumps({"host_skill": "gcp-to-aws", "infrastructure_moves": True, "design_constraints": {}}),
    json.dumps({"host_skill": "gcp-to-aws", "infrastructure_moves": "yes", "stop_after": "clarify", "design_constraints": {}}),
], ids=["not-json", "array", "unknown-key", "bare-value", "no-host-skill", "unknown-stop", "no-stop", "non-bool-infra"])
def test_a_broken_host_answers_file_is_not_ready(host, tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, THROUGH_CLARIFY)
    (run / "host-answers.json").write_text(host)
    code, out = _cli(run, "clarify", capsys)
    assert code == 1 and out["reason"] == "host_answers_invalid"


def test_the_documented_host_answers_example_is_accepted(tmp_path: Path, capsys) -> None:
    example = json.loads(SKILL.split("The host then writes", 1)[1].split("```json", 1)[1].split("```", 1)[0])
    run = _run(tmp_path, THROUGH_CLARIFY, example)
    assert _cli(run, "clarify", capsys)[0] == 0


def test_a_run_another_skill_initiated_is_still_this_skills_run(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, dict.fromkeys(THROUGH_CLARIFY, "completed"))
    assert _cli(run, "estimate", capsys)[0] == 0
    status = json.loads((run / ".phase-status.json").read_text())
    status["owning_skill"] = "GCP_TO_AWS"
    (run / ".phase-status.json").write_text(json.dumps(status))
    assert _cli(run, "estimate", capsys)[1]["reason"] == "not_this_skill"


def test_skill_documents_clarify_readiness_and_combined_mode() -> None:
    section = SKILL[SKILL.index("## Readiness for other skills"):SKILL.index("## Definitions")]
    assert "--through discover|clarify|design|estimate" in section
    combined = SKILL[SKILL.index("## Combined mode"):SKILL.index("## Readiness for other skills")]
    for phrase in ("host-answers.json", "stop_after", "initiated_by", "never `owning_skill`"):
        assert phrase in combined, phrase


def test_clarify_skips_only_the_questions_the_host_answered() -> None:
    combined = CLARIFY[CLARIFY.index("## Combined mode"):CLARIFY.index("## Step 0")]
    for phrase in ("host-answers.json", "Q1.5", "Q4", "target_region", "compliance", "as written", "Q11"):
        assert phrase in combined, phrase
    assert re.search(r"Q11[^.]*is still asked", combined)


def test_discover_readiness_reports_the_profile_and_who_started_the_run(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, {"discover": "completed", "clarify": "pending"})
    (run / "preferences.json").unlink()
    code, out = _cli(run, "discover", capsys)
    assert code == 0 and set(out["artifacts"]) == {"ai-workload-profile.json"} and out["initiated_by"] == "GCP_TO_AWS"
    assert _cli(run, "clarify", capsys)[1]["reason"] == "phase_incomplete"
