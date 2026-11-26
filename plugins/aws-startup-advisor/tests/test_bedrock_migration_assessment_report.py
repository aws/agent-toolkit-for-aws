"""Tests for bedrock-migration-assessment's standalone report: report-ai.py plan, write and check, and its wiring in SKILL.md."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
SCRIPT = BMA / "scripts" / "report-ai.py"
PLUGIN_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")
DOC = (BMA / "references/phases/report/report-ai.md").read_text(encoding="utf-8")
ESTIMATE_FIXTURES = ["bma-estimate-measured", "bma-estimate-price-unavailable", "bma-estimate-tier-high-volume"]
GENERATE_FIXTURES = ["bma-generate-same-model", "bma-generate-mixed", "bma-generate-tier-range"]
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"
DONE = {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed"}
HOSTILE = '<script>alert("x")</script> & "q" \'s'


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPORT = _module("bma_report_ai", SCRIPT)


def _run(tmp_path: Path, fixture: str, **status) -> Path:
    run = tmp_path / "bma-1116-1900"
    shutil.copytree(FIXTURES / fixture, run)
    generate = "completed" if (run / "generation-ai.json").exists() else "pending"
    (run / ".phase-status.json").write_text(json.dumps({
        "migration_id": "bma-1116-1900", "run_id": RUN_ID, "last_updated": "2026-11-16T19:00:00Z", "current_phase": "complete",
        "run_mode": "decide_and_execute" if generate == "completed" else "decide", "phases": {**DONE, "generate": generate}, **status}))
    return run


def _cli(*args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def _snapshot(root: Path) -> dict[str, bytes | str]:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() and not p.is_symlink() else f"link:{p.readlink()}" if p.is_symlink() else "dir")
            for p in sorted(root.rglob("*"))}


def _edit(path: Path, change) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc, indent=2))


def _html(run: Path) -> str:
    return (run / "migration-report.html").read_text(encoding="utf-8")


def _visible(text: str) -> str:
    return re.sub(r"<style\b.*?</style>", "", text, flags=re.S)


# --------------------------------------------------------------------------- rendering every fixture

@pytest.mark.parametrize("fixture", ESTIMATE_FIXTURES + GENERATE_FIXTURES)
def test_each_fixture_renders_a_report_that_passes_both_checks(tmp_path: Path, fixture: str) -> None:
    run = _run(tmp_path, fixture)
    code, out = _cli("write", str(run))
    assert code == 0 and out["ok"], out
    code, out = _cli("check", str(run))
    assert code == 0 and out["ok"], out
    proc = subprocess.run([sys.executable, str(PLUGIN_VALIDATOR), str(run / "migration-report.html"), "--mode", "ai_only",
                           "--estimation-ai", str(run / "estimation-ai.json"), "--migration-dir", str(run)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("fixture", ESTIMATE_FIXTURES + GENERATE_FIXTURES)
def test_key_figures_match_the_artifacts(tmp_path: Path, fixture: str) -> None:
    run = _run(tmp_path, fixture)
    REPORT.write(run, None)
    text = _html(run)
    est = json.loads((run / "estimation-ai.json").read_text())
    design = json.loads((run / "aws-design-ai.json").read_text())
    assert f"<code>{est['recommended_model']['model']}</code>" in text
    for row in design["ai_architecture"]["bedrock_models"]:
        assert f"<code>{row['aws_model_id']}</code>" in text and f"<code>{row['source_model_id']}</code>" in text
    point, rng = est["cost_comparison"]["projected_bedrock_monthly"], est["roi_analysis"]["projected_bedrock_monthly_range"]
    if point is not None:
        assert REPORT.money(point) in text
    elif rng["low"] is not None:
        assert f"{REPORT.money(rng['low'])} to {REPORT.money(rng['high'])}" in text
    for model in est["model_comparison"]:
        cost = model["monthly_cost"]
        if isinstance(cost, dict):
            assert f"{REPORT.money(cost['low'])} to {REPORT.money(cost['high'])}" in text


def test_tier_range_shows_both_bounds_as_whole_dollars(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-tier-high-volume")
    REPORT.write(run, None)
    text = _html(run)
    assert "$3 to $572" in text
    assert "10,000,000 to 100,000,000 tokens a month" in text
    assert "$2.86" not in _visible(text)


def test_price_unavailable_is_never_shown_as_zero(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-price-unavailable")
    REPORT.write(run, None)
    text = _visible(_html(run))
    assert "Price unavailable" in text
    assert not re.search(r"\$0(?:\.00)?\b(?![.\d])", text)
    assert "show Price unavailable" in text


def test_artifact_text_is_shown_verbatim(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    ctx = REPORT.gather(run)
    row = ctx["data"]["aws-design-ai.json"]["ai_architecture"]["bedrock_models"][0]
    row["bedrock_price"] = "$12.49 for 1M tokens"
    ctx["data"]["preferences.json"]["design_constraints"]["target_region"]["value"] = "$2.50 answer"
    ctx["data"]["estimation-ai.json"]["recommendation"]["rationale"] = "A $2.50 setup fee and $2.86 a month."
    text = REPORT.render(ctx)
    assert all(t in text for t in ("$12.49 for 1M tokens", "$2.50 answer", "A $2.50 setup fee and $2.86 a month."))


def _share(text: str) -> str:
    return re.sub(r"\s+", " ", re.search(r'<div class="share-card"><p>(.*?)</p>', text, re.S).group(1))


def _add_service_block(ctx: dict, workload: str, model: str, service: str) -> None:
    ctx["data"]["aws-design-ai.json"]["design_blocks"].append({
        "workload_id": workload, "model_id": model, "target_bedrock_model": None, "target_aws_service": service,
        "capability": "text_to_speech", "capability_confidence": "high", "rationale": "Speech goes to an AWS speech service.",
        "confidence_warning": None})
    ctx["data"]["estimation-ai.json"]["services_not_estimated"].append(
        {"workload_id": workload, "target_aws_service": service, "reason": "not_token_priced"})


def test_the_leadership_brief_counts_only_bedrock_workloads_and_names_the_others(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    ctx = REPORT.gather(run)
    _add_service_block(ctx, "openai_api.tts-1", "tts-1", "polly")
    text = REPORT.render(ctx)
    share = _share(text)
    assert share.startswith("Draft estimate for 1 AI workload that uses gpt-4o: running it on Amazon Bedrock"), share
    assert "2 AI workloads" not in share and "tts-1" not in share.split(":")[0]
    assert ("<code>openai_api.tts-1</code> goes to Amazon Polly; its cost and setup are outside this estimate." in share), share
    assert "<li><code>openai_api.tts-1</code>: Amazon Polly</li>" in text
    report, estimate = tmp_path / "migration-report.html", tmp_path / "estimation-ai.json"
    report.write_text(text, encoding="utf-8")
    estimate.write_text(json.dumps(ctx["data"]["estimation-ai.json"]), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(PLUGIN_VALIDATOR), str(report), "--mode", "ai_only", "--estimation-ai", str(estimate),
                           "--migration-dir", str(run)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_the_leadership_brief_groups_workloads_by_aws_service(tmp_path: Path) -> None:
    ctx = REPORT.gather(_run(tmp_path, "bma-generate-mixed"))
    for workload, model, service in (("w.tts", "tts-1", "polly"), ("w.stt", "whisper-1", "transcribe"), ("w.tts-hd", "tts-1-hd", "polly")):
        _add_service_block(ctx, workload, model, service)
    share = _share(REPORT.render(ctx))
    assert share.startswith("Draft estimate for 3 AI workloads that use gpt-5.5, text-embedding-3-small: running them on Amazon Bedrock"), share
    assert ("<code>w.tts</code> and <code>w.tts-hd</code> go to Amazon Polly and <code>w.stt</code> goes to Amazon Transcribe; "
            "their cost and setup are outside this estimate." in share), share


def test_the_leadership_brief_names_no_other_service_when_every_workload_runs_on_bedrock(tmp_path: Path) -> None:
    share = _share(REPORT.render(REPORT.gather(_run(tmp_path, "bma-estimate-measured"))))
    assert share.startswith("Draft estimate for 1 AI workload that uses gpt-4o: running it on Amazon Bedrock"), share
    assert "outside this estimate" not in share


@pytest.mark.parametrize("command", ["plan", "write", "check"])
def test_an_artifact_shape_the_renderer_cannot_read_is_a_named_error(tmp_path: Path, command: str) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    if command == "check":
        REPORT.write(run, None)
    _edit(run / "estimation-ai.json", lambda d: d.update(model_comparison=[1]))
    before = _snapshot(run)
    rc, out = _cli(command, str(run))
    assert rc == 1 and out["ok"] is False and out["error"] == "report_render_failed", out
    assert "appendix-ai" in out["detail"] and "estimation-ai.json" in out["detail"]
    assert _snapshot(run) == before


def test_estimate_asks_for_whole_dollar_figures_in_its_rationale() -> None:
    doc = (BMA / "references/phases/estimate/estimate-ai.md").read_text(encoding="utf-8")
    assert "as whole dollars a month (`$3 to $572`, cents only below $2)" in doc


def test_money_formats_monthly_and_small_figures() -> None:
    assert [REPORT.money(v) for v in (0.02, 1.5, 1.996, 2.5, 19.8, 1234.5, None)] == \
        ["$0.02", "$1.50", "$2", "$3", "$20", "$1,235", "Price unavailable"]
    assert REPORT.money_range(57.2, None) == "from $57"
    assert REPORT.money_range(None, 3) == "Price unavailable"


def test_render_is_reproducible_byte_for_byte(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    assert REPORT.render(REPORT.gather(run)) == REPORT.render(REPORT.gather(run))


def test_the_digest_covers_the_document_with_its_own_value_blanked(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    REPORT.write(run, None)
    text = _html(run)
    meta = REPORT.DIGEST_META.search(text).group(1)
    blank = text.replace(f'content="{meta}"', 'content=""', 1)
    assert meta == hashlib.sha256(blank.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- escaping

def test_untrusted_strings_from_the_artifacts_are_escaped(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    _edit(run / "estimation-ai.json", lambda d: d["recommendation"].update(rationale=HOSTILE, migrate_if=HOSTILE))
    _edit(run / "aws-design-ai.json", lambda d: d["design_blocks"][0].update(rationale=HOSTILE))
    _edit(run / "preferences.json", lambda d: d["design_constraints"]["target_region"].update(prompt=HOSTILE))
    _edit(run / "generation-ai.json", lambda d: d["recommendation"]["key_risks"].append(HOSTILE))
    REPORT.write(run, None)
    text = _html(run)
    assert "<script>" not in text and "alert(\"x\")" not in text
    assert text.count("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &quot;q&quot; &#x27;s") >= 5
    assert REPORT.check(run)["ok"]


def test_hostile_model_and_workload_ids_are_escaped(tmp_path: Path) -> None:
    ctx = REPORT.gather(_run(tmp_path, "bma-generate-tier-range"))
    design = ctx["data"]["aws-design-ai.json"]
    design["design_blocks"][0]["workload_id"] = HOSTILE
    design["ai_architecture"]["bedrock_models"][0]["source_model_id"] = HOSTILE
    ctx["data"]["estimation-ai.json"]["model_comparison"][0]["model"] = HOSTILE
    ctx["migration_id"] = HOSTILE
    text = REPORT.render(ctx)
    assert "<script>" not in text and '"q"' not in _visible(text).split("</head>")[1]


def test_raw_model_and_call_sites_never_reach_the_report(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    REPORT.write(run, None)
    profile = json.loads((run / "ai-workload-profile.json").read_text())
    details = [ev.get("detail") for src in profile.get("ai_sources", []) for obs in src.get("model_observations", [])
               for ev in obs.get("evidence", [])]
    assert details and all(details) and not any(d in _html(run) for d in details)


# --------------------------------------------------------------------------- prior hash and the write target

def test_a_fresh_write_succeeds_and_reports_its_hash(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    assert REPORT.plan(run)["state"] == "absent"
    out = REPORT.write(run, None)
    assert out["sha256"] == hashlib.sha256((run / "migration-report.html").read_bytes()).hexdigest() and not out["replaced"]
    plan = REPORT.plan(run)
    assert plan["state"] == "unchanged" and plan["current"] and plan["sha256"] == out["sha256"]
    assert not [p for p in run.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("case,code", [("exists_no_hash", "report_exists"), ("stale_hash", "report_hash_mismatch"),
                                       ("hash_no_file", "report_hash_unexpected"), ("symlink", "report_target_invalid"),
                                       ("directory", "report_target_invalid"), ("dangling_symlink", "report_target_invalid")])
def test_every_write_refusal_leaves_the_run_directory_unchanged(tmp_path: Path, case: str, code: str) -> None:
    run = _run(tmp_path, "bma-generate-same-model")
    outside = tmp_path / "outside.html"
    outside.write_text("keep me")
    expected = None
    if case in ("exists_no_hash", "stale_hash"):
        REPORT.write(run, None)
        expected = None if case == "exists_no_hash" else "0" * 64
    elif case == "hash_no_file":
        expected = "a" * 64
    elif case == "symlink":
        (run / "migration-report.html").symlink_to(outside)
    elif case == "dangling_symlink":
        (run / "migration-report.html").symlink_to(tmp_path / "nowhere.html")
    else:
        (run / "migration-report.html").mkdir()
    before = _snapshot(run)
    args = ["write", str(run)] + (["--expected-sha256", expected] if expected else [])
    rc, out = _cli(*args)
    assert rc == 1 and out["error"] == code, out
    assert _snapshot(run) == before
    assert outside.read_text() == "keep me" and not (tmp_path / "nowhere.html").exists()


def test_the_right_hash_replaces_the_report(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    first = REPORT.write(run, None)
    _edit(run / "estimation-ai.json", lambda d: d["recommendation"].update(rationale="A new rationale after Estimate again."))
    plan = REPORT.plan(run)
    assert plan["state"] == "unchanged" and not plan["current"]
    out = REPORT.write(run, plan["sha256"].upper())
    assert out["replaced"] and out["sha256"] != first["sha256"]
    assert "A new rationale after Estimate again." in _html(run) and REPORT.check(run)["ok"]


def test_an_edited_or_foreign_report_is_reported_as_edited(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    (run / "migration-report.html").write_text("<html><body>someone else's report</body></html>")
    assert REPORT.plan(run)["state"] == "edited"
    REPORT.write(run, hashlib.sha256((run / "migration-report.html").read_bytes()).hexdigest())
    (run / "migration-report.html").write_bytes(_html(run).replace("Leadership brief", "Board brief").encode())
    assert REPORT.plan(run)["state"] == "edited"
    (run / "migration-report.html").write_bytes(b"\xff\xfe not utf-8")
    assert REPORT.plan(run)["state"] == "edited"
    assert [e["code"] for e in REPORT.check(run)["errors"]] == ["report_edited"]


def test_a_report_the_os_cannot_read_is_named_in_plan_write_and_check(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    REPORT.write(run, None)
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError("denied"))
                        if self.name == "migration-report.html" else original(self))
    for call in (lambda: REPORT.plan(run), lambda: REPORT.write(run, "a" * 64), lambda: REPORT.check(run)):
        with pytest.raises(REPORT.ReportError) as err:
            call()
        assert err.value.code == "report_unreadable"


def test_a_failed_input_check_writes_nothing(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    _edit(run / "estimation-ai.json", lambda d: d["cost_comparison"].update(projected_bedrock_monthly=1.0))
    before = _snapshot(run)
    rc, out = _cli("write", str(run))
    assert rc == 1 and out["error"] == "estimate_invalid"
    assert _snapshot(run) == before


@pytest.mark.parametrize("race,code", [("removed", "artifact_missing"), ("changed", "artifact_changed"), ("usage_unreadable", "artifact_unreadable")])
def test_an_artifact_that_changes_after_the_readiness_check_is_named(tmp_path: Path, monkeypatch, race: str, code: str) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    original = REPORT.readiness.check

    def racing(run_dir: Path, through: str) -> dict:
        result = original(run_dir, through)
        if race == "removed":
            (run_dir / "estimation-ai.json").unlink()
        elif race == "changed":
            _edit(run_dir / "estimation-ai.json", lambda d: d["recommendation"].update(rationale="changed"))
        else:
            monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError("denied"))
                                if self.name == "openai-usage-profile.json" else original_read(self))
        return result

    original_read = Path.read_bytes
    monkeypatch.setattr(REPORT.readiness, "check", racing)
    with pytest.raises(REPORT.ReportError) as err:
        REPORT.write(run, None)
    assert err.value.code == code and not (run / "migration-report.html").exists()


def test_usage_profiles_are_inputs(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    assert "openai-usage-profile.json" in REPORT.plan(run)["inputs"]


@pytest.mark.parametrize("failing", ["mkstemp", "replace"])
def test_a_failed_write_is_named_and_keeps_the_old_report(tmp_path: Path, monkeypatch, failing: str) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    sha = REPORT.write(run, None)["sha256"]
    _edit(run / "estimation-ai.json", lambda d: d["recommendation"].update(rationale="changed"))
    before = _snapshot(run)

    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(REPORT.tempfile if failing == "mkstemp" else REPORT.os, failing, boom)
    with pytest.raises(REPORT.ReportError) as err:
        REPORT.write(run, sha)
    assert err.value.code == "report_write_failed" and _snapshot(run) == before


def test_an_incomplete_estimate_writes_nothing(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    _edit(run / ".phase-status.json", lambda d: d["phases"].update(estimate="in_progress"))
    rc, out = _cli("plan", str(run))
    assert rc == 1 and out["error"] == "phase_incomplete"


# --------------------------------------------------------------------------- check

def _mutated(run: Path, change) -> list[str]:
    (run / "migration-report.html").write_text(change(_html(run)), encoding="utf-8")
    result = REPORT.check(run)
    assert not result["ok"]
    return [e["code"] for e in result["errors"]]


def _section_span(text: str, sid: str) -> str:
    return re.search(rf'<section id="{sid}">.*?</section>\n?', text, re.S).group(0)


def test_check_names_a_deleted_section(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    REPORT.write(run, None)
    assert "report_section_missing" in _mutated(run, lambda t: t.replace(_section_span(t, "exec-risks"), ""))


def test_check_names_a_duplicated_section(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    REPORT.write(run, None)
    assert _mutated(run, lambda t: t.replace(_section_span(t, "appendix-ai"), _section_span(t, "appendix-ai") * 2)) == ["report_section_duplicate"]


def test_check_names_an_edited_section(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    REPORT.write(run, None)
    assert _mutated(run, lambda t: t.replace("Migrate if", "Move if", 1)) == ["report_edited"]


def test_check_names_a_broken_contents_link(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    REPORT.write(run, None)
    assert _mutated(run, lambda t: t.replace('href="#exec-risks"', 'href="#exec-risk"')) == ["report_toc_broken"]


def test_check_names_a_report_whose_inputs_changed(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    REPORT.write(run, None)
    _edit(run / "estimation-ai.json", lambda d: d["recommendation"].update(stay_if="A changed reason."))
    assert [e["code"] for e in REPORT.check(run)["errors"]] == ["report_stale"]


def test_check_names_an_untouched_report_stale_when_a_section_is_added(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    opportunities = json.loads((run / "estimation-ai.json").read_text())["optimization_opportunities"]
    _edit(run / "estimation-ai.json", lambda d: d.update(optimization_opportunities=[]))
    REPORT.write(run, None)
    assert "exec-optimization" not in REPORT.plan(run)["sections"]
    _edit(run / "estimation-ai.json", lambda d: d.update(optimization_opportunities=opportunities))
    assert REPORT.plan(run)["state"] == "unchanged"
    assert [e["code"] for e in REPORT.check(run)["errors"]] == ["report_stale"]


def test_check_without_a_report(tmp_path: Path) -> None:
    rc, out = _cli("check", str(_run(tmp_path, "bma-estimate-measured")))
    assert rc == 1 and out["error"] == "report_not_found"


# --------------------------------------------------------------------------- reruns and combined runs

def test_rerun_after_estimate_again_drops_the_generate_rows(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    REPORT.write(run, None)
    assert "Generated migration artifacts" in _html(run) and "ai-migration/routes/" in _html(run)
    _edit(run / ".phase-status.json", lambda d: (d["phases"].update(generate="pending"), d.update(run_mode="decide")))
    shutil.rmtree(run / "ai-migration")
    _edit(run / "estimation-ai.json", lambda d: d["recommendation"].update(rationale="Estimated again on the high band."))
    plan = REPORT.plan(run)
    assert plan["state"] == "unchanged" and not plan["current"] and not plan["generated"]
    REPORT.write(run, plan["sha256"])
    text = _html(run)
    assert "Generated migration artifacts" not in text and "ai-migration/routes/" not in text
    assert "No migration artifacts were generated in this run." in text and "Estimated again on the high band." in text
    assert REPORT.check(run)["ok"]


def test_a_generate_run_left_on_disk_after_a_reset_is_not_rendered(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-same-model")
    _edit(run / ".phase-status.json", lambda d: d["phases"].update(generate="pending"))
    REPORT.write(run, None)
    assert "No migration artifacts were generated in this run." in _html(run)


@pytest.mark.parametrize("marker", ["initiated_by", "host_answers"])
def test_a_combined_run_gets_no_report(tmp_path: Path, marker: str) -> None:
    run = _run(tmp_path, "bma-estimate-measured", **({"initiated_by": "GCP_TO_AWS"} if marker == "initiated_by" else {}))
    if marker == "host_answers":
        (run / "host-answers.json").write_text(json.dumps({"host_skill": "gcp-to-aws", "infrastructure_moves": True,
                                                           "stop_after": "estimate", "design_constraints": {}}))
    before = _snapshot(run)
    for command in ("plan", "write", "check"):
        rc, out = _cli(command, str(run))
        assert rc == 1 and out["error"] == "combined_run", (command, out)
    assert _snapshot(run) == before


@pytest.mark.parametrize("initiated_by", [None, "GCP_TO_AWS"])
def test_a_combined_run_that_asked_for_generate_gets_no_report(tmp_path: Path, initiated_by: str | None) -> None:
    run = _run(tmp_path, "bma-generate-same-model", **({"initiated_by": initiated_by} if initiated_by else {}))
    (run / "host-answers.json").write_text(json.dumps({"host_skill": "gcp-to-aws", "infrastructure_moves": True,
                                                       "stop_after": "generate", "design_constraints": {}}))
    before = _snapshot(run)
    for command in ("plan", "write", "check"):
        rc, out = _cli(command, str(run))
        assert rc == 1 and out["error"] == "combined_run", (command, out)
    assert _snapshot(run) == before


def test_another_skills_run_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-estimate-measured")
    _edit(run / ".phase-status.json", lambda d: d.update(migration_id="gcp-1116-1900"))
    rc, out = _cli("plan", str(run))
    assert rc == 1 and out["error"] == "not_this_skill"


# --------------------------------------------------------------------------- docs

def test_skill_runs_the_report_after_estimate_and_generate_but_never_in_a_combined_run() -> None:
    step4 = SKILL.split("## Step 4: Estimate")[1].split("## Step 5")[0]
    step5 = SKILL.split("## Step 5: Generate")[1]
    for step in (step4, step5):
        assert "references/phases/report/report-ai.md" in step
    combined = step4.split("In a combined run")[1].split(".")[0]
    assert "report" not in combined
    assert "never written in a combined run" in SKILL and "Never in a combined run" in DOC


def test_the_readiness_contract_says_the_report_is_not_an_artifact() -> None:
    assert "`artifacts` never lists `migration-report.html`" in SKILL.split("## Definitions")[0]


def test_step_0_offers_the_report_on_a_completed_run() -> None:
    step0 = SKILL.split("## Step 0")[1].split("## Step 1")[0]
    for rule in ("6. ", "7. "):
        line = step0.split(f"\n{rule}")[1].split("\n")[0]
        assert "report-ai.py plan" in line, rule


def test_the_report_doc_names_every_error_code_the_script_emits() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    codes = set(re.findall(r'ReportError\("([a-z_]+)"', source)) | set(re.findall(r'"code": "([a-z_]+)"', source))
    assert codes and all(f"`{code}`" in DOC for code in codes), sorted(c for c in codes if f"`{c}`" not in DOC)


def test_error_codes_are_fixed_identifiers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r'ReportError\(f"', source) and not re.search(r'"code": f"', source)


def test_the_report_is_not_a_readiness_artifact(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-same-model")
    REPORT.write(run, None)
    ready = REPORT.readiness.check(run, "generate")
    assert "migration-report.html" not in ready["artifacts"]
