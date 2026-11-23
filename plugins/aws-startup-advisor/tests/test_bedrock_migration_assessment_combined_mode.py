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


def _generated_run(tmp_path: Path, initiated_by: bool, stop_after: str | None) -> Path:
    run = tmp_path / "bma-1116-1900"
    shutil.copytree(FIXTURES / "bma-generate-mixed", run)
    status = {"migration_id": run.name, "run_id": RUN_ID, "last_updated": "2026-11-16T19:00:00Z", "current_phase": "complete",
              "run_mode": "decide_and_execute", "phases": dict.fromkeys(("discover", "clarify", "design", "estimate", "generate"), "completed")}
    if initiated_by:
        status["initiated_by"] = "GCP_TO_AWS"
    (run / ".phase-status.json").write_text(json.dumps(status))
    if stop_after:
        prefs = json.loads((run / "preferences.json").read_text())
        (run / "host-answers.json").write_text(json.dumps({**_host(prefs), "stop_after": stop_after}))
    return run


def test_a_standalone_run_is_ready_through_generate(tmp_path: Path, capsys) -> None:
    assert _cli(_generated_run(tmp_path, False, None), "generate", capsys)[0] == 0


@pytest.mark.parametrize(("initiated_by", "stop_after"), [(True, "estimate"), (True, None), (False, "estimate"), (True, "clarify")])
def test_a_combined_run_is_never_ready_through_generate(initiated_by, stop_after, tmp_path: Path, capsys) -> None:
    run = _generated_run(tmp_path, initiated_by, stop_after)
    code, out = _cli(run, "generate", capsys)
    assert code == 1 and out["reason"] == "combined_run", out
    if stop_after == "estimate":
        assert _cli(run, "estimate", capsys)[0] == 0
    gen = _module("bma_generate_combined", "generate-ai.py")
    with pytest.raises(gen.GenerateInputError) as raised:
        gen.build_plan(run)
    assert raised.value.code == "combined_run"


@pytest.mark.parametrize(("stop_after", "phases"), [("clarify", ("design", "estimate", "generate")), ("design", ("estimate", "generate"))])
def test_generate_plan_names_a_combined_run_before_any_missing_phase(stop_after, phases, tmp_path: Path) -> None:
    run = _generated_run(tmp_path, True, stop_after)
    status = json.loads((run / ".phase-status.json").read_text())
    status["phases"].update(dict.fromkeys(phases, "pending"))
    (run / ".phase-status.json").write_text(json.dumps(status))
    (run / "estimation-ai.json").unlink()
    gen = _module("bma_generate_early", "generate-ai.py")
    with pytest.raises(gen.GenerateInputError) as raised:
        gen.build_plan(run)
    assert raised.value.code == "combined_run"


def test_a_dangling_host_answers_link_still_marks_a_combined_run(tmp_path: Path, capsys) -> None:
    run = _generated_run(tmp_path, False, None)
    (run / "host-answers.json").symlink_to(tmp_path / "gone.json")
    assert _cli(run, "generate", capsys)[1]["reason"] == "combined_run"
    assert _module("bma_generate_standalone", "generate-ai.py").build_plan(_generated_run(tmp_path / "s", False, None))["routes"]


def test_step_0_returns_a_combined_run_to_the_host_and_never_offers_generate() -> None:
    step0 = SKILL[SKILL.index("## Step 0"):SKILL.index("## Step 1")]
    rule = step0[step0.index("Combined run:"):step0.index("1. ")]
    for phrase in ("`initiated_by`", "`host-answers.json`", "`stop_after`", "control returns to the host", "Rules 4 to 7 never apply"):
        assert phrase in rule, phrase
    lines = [line for line in rule.splitlines() if line.startswith("- (")]
    mismatch = next(i for i, line in enumerate(lines) if "`host_answers_mismatch`" in line)
    stop = next(i for i, line in enumerate(lines) if "named in `stop_after` is" in line)
    assert mismatch < stop and "--through clarify" in lines[mismatch] and "Change answers" in lines[mismatch]
    invalid = next(line for line in lines if "unreadable or not the shape" in line)
    for phrase in ("`host_skill`", "`infrastructure_moves`", "`stop_after`", "`design_constraints`", "`target_region`", "`compliance`", "`value`"):
        assert phrase in invalid, phrase
    for phrase in ("`host_answers_invalid`", "`preferences_invalid`", "`design_invalid`", "`estimate_invalid`", "Design again", "Estimate again", "any other reason"):
        assert phrase in lines[stop], phrase
    step4 = SKILL[SKILL.index("## Step 4"):SKILL.index("## Step 5")]
    assert "In a combined run, do not ask" in step4
    assert "Never in a combined run" in SKILL[SKILL.index("## Step 5"):]
    readiness = SKILL[SKILL.index("## Readiness for other skills"):SKILL.index("## Definitions")]
    assert "`combined_run`" in readiness


def test_preferences_schema_keeps_the_host_source_whatever_chosen_by() -> None:
    schema = (BMA / "references" / "shared" / "schema-preferences.md").read_text(encoding="utf-8")
    row = next(line for line in schema.splitlines() if line.startswith("| `source`"))
    assert "host:<host_skill>" in row and "combined mode" in row
    checklist = schema[schema.index("## Validation"):]
    question_id = next(line for line in checklist.splitlines() if line.startswith("3. "))
    source = next(line for line in checklist.splitlines() if line.startswith("4. "))
    assert "host answer in combined mode" in question_id
    assert "host:<host_skill>" in source and "host answer in combined mode" in source


def test_a_host_started_run_takes_the_profile_route_without_asking() -> None:
    discover = (BMA / "references" / "phases" / "discover" / "discover.md").read_text(encoding="utf-8")
    step1 = discover[discover.index("## Step 1"):discover.index("## Step 2a")]
    assert re.search(r"host-started run takes the Profile route without asking", step1)
    combined = SKILL[SKILL.index("## Combined mode"):SKILL.index("## Readiness for other skills")]
    assert "Profile route" in combined and "supplied-profile route" not in combined
