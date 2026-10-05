"""CLI entry, host routing, consent, and standalone distribution contracts."""

import importlib.util
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import PLUGIN_ROOT, TELEMETRY
from test_migration import Project, activity, all_completed, phase_status

CLI = TELEMETRY / "cli.py"
ENDPOINT_ENV = "AWS_STARTUP_ADVISOR_PLUGIN_TELEMETRY_ENDPOINT"
SKILLS = ("azure-to-aws", "gcp-to-aws", "heroku-to-aws", "llm-to-bedrock")


def invoke(p, *args, script=CLI, markers=None, keep_stdin_open=False):
    env = {
        "HOME": str(p.home), "USERPROFILE": str(p.home), "PATH": "/usr/bin:/bin",
        ENDPOINT_ENV: p.collector.url,
    }
    env.update(markers or {})
    before = len(p.collector.received)
    proc = subprocess.Popen(  # nosec B603 — local script and fixture argv
        [sys.executable, str(script), *args], cwd=str(p.root), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if keep_stdin_open:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("the CLI waited for a hook payload on stdin")
    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode == 0, stderr
    bodies = [json.loads(row["body"]) for row in p.collector.received[before:]]
    return stdout, bodies


@pytest.mark.parametrize("markers,source,mode", [
    ({}, "OTHER", "cli"),
    ({"CLAUDECODE": "1"}, "CLAUDE_CODE", "hook"),
    ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, "CLAUDE_CODE", "hook"),
    ({"CURSOR_AGENT": "1"}, "CURSOR", "hook"),
    ({"CURSOR_AGENT": ""}, "OTHER", "cli"),
    ({"CURSOR_VERSION": "fixture", "CLAUDECODE": "1"}, "CURSOR", "hook"),
    ({"CURSOR_PROJECT_DIR": "/fixture"}, "CURSOR", "hook"),
    ({"CURSOR_TRACE_ID": "fixture"}, "CURSOR", "hook"),
    ({"CODEX_SANDBOX": "fixture"}, "CODEX", "cli"),
    ({"KIRO_IDE": "fixture"}, "KIRO", "cli"),
])
def test_status_is_read_only_and_routes_using_shared_host_markers(tmp_path, home, collector, markers, source, mode):
    p = Project(tmp_path, home, collector, phase_status(), consent=None)
    out, bodies = invoke(p, "status", markers=markers, keep_stdin_open=True)
    assert json.loads(out) == {
        "source": source, "reportingMode": mode, "consentStatus": None,
        "pluginVersion": json.loads((PLUGIN_ROOT / "plugin.json").read_text())["version"],
    }
    assert bodies == []
    assert not p.has_snapshot()
    assert not (home / ".aws-startup-advisor").exists()
    assert not (p.run_dir / ".telemetry-lock").exists()


@pytest.mark.parametrize("markers", [
    {"CLAUDECODE": "1"},
    {"CLAUDE_CODE_ENTRYPOINT": "cli"},
    {"CURSOR_AGENT": "1"},
    {"CURSOR_AGENT": "1", "CLAUDECODE": "1"},
    {"CURSOR_VERSION": "fixture", "CLAUDECODE": "1"},
    {"CURSOR_PROJECT_DIR": "/fixture"},
])
def test_hook_hosts_skip_cli_even_with_consent_and_direct_emitter_flags(tmp_path, home, collector, markers):
    p = Project(tmp_path, home, collector, phase_status())
    assert invoke(p, "reconcile", markers=markers, keep_stdin_open=True)[1] == []
    assert invoke(p, "--reconcile", "--via", "cli",
                  script=TELEMETRY / "metric_emission/migration.py", markers=markers)[1] == []
    assert not p.has_snapshot()
    assert not (p.run_dir / ".telemetry-lock").exists()
    assert len(p.hook("--reconcile", env=markers)) == 2
    assert p.snapshot()["via"] == "hook"


@pytest.mark.parametrize("markers,source", [
    ({}, "OTHER"), ({"CODEX_SANDBOX": "fixture"}, "CODEX"), ({"KIRO_IDE": "fixture"}, "KIRO"),
])
def test_cli_keeps_existing_source_and_needs_no_hook_payload(tmp_path, home, collector, markers, source):
    p = Project(tmp_path, home, collector, phase_status())
    bodies = invoke(p, "reconcile", markers=markers, keep_stdin_open=True)[1]
    assert len(bodies) == 2
    assert {b["source"] for b in bodies} == {source}
    assert all("sessionId" not in activity(b) for b in bodies)
    assert p.snapshot()["via"] == "cli"
    assert invoke(p, "reconcile", markers=markers)[1] == []


@pytest.mark.parametrize("consent", [None, "OPT_OUT", "REJECTED"])
def test_cli_leaves_no_trace_without_current_accepted_consent(tmp_path, home, collector, consent):
    p = Project(tmp_path, home, collector, phase_status(), consent=consent)
    (p.root / ".migration/telemetry.json").write_text('{"consent":"granted"}')
    assert invoke(p, "reconcile")[1] == []
    assert not p.has_snapshot()
    assert not (p.run_dir / ".telemetry-lock").exists()


def test_cli_uses_existing_notice_writers_and_opt_out_stops_new_transitions(tmp_path, home, collector):
    p = Project(tmp_path, home, collector, phase_status(), consent=None)
    shown, bodies = invoke(p, "show", script=TELEMETRY / "consent/cli.py")
    import record
    assert shown == record.disclaimer() and bodies == []
    assert not (home / ".aws-startup-advisor").exists()
    assert invoke(p, script=TELEMETRY / "consent/accept.py")[1][0]["pluginTelemetryEvent"] == {"consentRecorded": {}}
    bodies = invoke(p, "reconcile")[1]
    assert len(bodies) == 2
    before = p.snapshot()
    assert invoke(p, script=TELEMETRY / "consent/opt_out.py")[1] == []
    p.write_status(phase_status(current_phase="complete", phases=all_completed(), run_mode="decide"))
    assert invoke(p, "reconcile")[1] == []
    assert p.snapshot() == before
    state = json.loads((home / ".aws-startup-advisor/plugin-telemetry.json").read_text())
    assert state["consentStatus"] == "OPT_OUT"
    assert state["installId"] == bodies[0]["installId"]


def test_cli_preserves_gate_replay_and_each_completion_mode_once(tmp_path, home, collector):
    p = Project(tmp_path, home, collector, phase_status())
    invoke(p, "reconcile")
    p.write_gates({"design": {"reason": "missing", "field": "aws-design.json"}})
    collector.status = 429
    assert activity(invoke(p, "reconcile")[1][0])["eventName"] == "GATE_FAILED"
    assert p.snapshot()["gateFailures"] == []
    collector.status = 200
    assert activity(invoke(p, "reconcile")[1][0])["attributes"]["failureReason"] == "MISSING"
    assert invoke(p, "reconcile")[1] == []
    phases = all_completed()
    phases["generate"] = "pending"
    p.write_status(phase_status(current_phase="complete", phases=phases, run_mode="decide"))
    first = invoke(p, "reconcile")[1]
    p.write_status(phase_status(current_phase="complete", phases=phases, run_mode="decide_and_execute"))
    assert invoke(p, "reconcile")[1] == []
    p.write_status(phase_status(current_phase="complete", phases=all_completed(), run_mode="decide_and_execute"))
    second = invoke(p, "reconcile")[1]
    modes = [activity(b)["attributes"]["runMode"] for b in first + second
             if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert modes == ["DECIDE", "DECIDE_AND_EXECUTE"]
    p.write_status(phase_status(current_phase="estimate", phases=phases))
    invoke(p, "reconcile")
    p.write_status(phase_status(current_phase="complete", phases=all_completed(), run_mode="decide_and_execute"))
    assert all(activity(b)["eventName"] != "RUN_COMPLETED" for b in invoke(p, "reconcile")[1])
    assert invoke(p, "reconcile")[1] == []


def test_cli_and_existing_codex_hook_share_the_current_snapshot_and_lock(tmp_path, home, collector):
    p = Project(tmp_path, home, collector, phase_status())
    markers = {"CODEX_SANDBOX": "fixture", "CLAUDECODE": ""}
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(invoke, p, "reconcile", markers=markers),
                 pool.submit(p.hook, "--reconcile", env=markers)]
        for call in calls:
            call.result()
    events = [activity(json.loads(row["body"])) for row in collector.received]
    assert len(events) == 2
    assert {e["eventName"] for e in events} == {"RUN_STARTED", "PHASE_COMPLETED"}
    assert invoke(p, "reconcile", markers=markers)[1] == []


@pytest.mark.parametrize("skill", SKILLS)
def test_isolated_skill_bundle_reuses_consent_and_reports_its_version(tmp_path, home, collector, skill):
    # This fixture has no enclosing plugin manifest or sibling skills.
    isolated = tmp_path / "isolated-skill"
    shutil.copytree(PLUGIN_ROOT / "skills" / skill / "references/vendored/telemetry", isolated / "telemetry")
    script = isolated / "telemetry/cli.py"
    owner = skill.upper().replace("-", "_")
    p = Project(tmp_path, home, collector, phase_status(owning_skill=owner))
    info = json.loads(invoke(p, "status", script=script)[0])
    assert info["pluginVersion"] == json.loads((PLUGIN_ROOT / "plugin.json").read_text())["version"]
    bodies = invoke(p, "reconcile", script=script)[1]
    assert len(bodies) == 2 and {activity(b)["skill"] for b in bodies} == {owner}
    assert {b["pluginVersion"] for b in bodies} == {info["pluginVersion"]}
    assert invoke(p, "reconcile", script=script)[1] == []
    (isolated / "telemetry/version.json").unlink()
    p.write_status(phase_status(owning_skill=owner, current_phase="complete", phases=all_completed()))
    before = p.snapshot()
    assert invoke(p, "reconcile", script=script)[1] == []
    assert p.snapshot() == before


def bundle_fixture(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_bundles", TELEMETRY / "sync_bundles.py")
    syncer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(syncer)
    assert syncer.sync() == []
    plugin = tmp_path / "plugin"
    (plugin / "scripts/telemetry").mkdir(parents=True)
    for name in syncer.RUNTIME_FILES:
        target = plugin / "scripts/telemetry" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((TELEMETRY / name).read_bytes())
    shared = plugin / "skills/shared/dsl/INTERPRETER.md"
    shared.parent.mkdir(parents=True)
    shared.write_bytes((PLUGIN_ROOT / "skills/shared/dsl/INTERPRETER.md").read_bytes())
    for name in ("plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", ".codex-plugin/plugin.json"):
        manifest = plugin / name
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text('{"version":"2.0.3"}')
    syncer.sync(plugin, write=True)
    return syncer, plugin


def test_generated_bundles_are_current_and_checks_detect_missing_or_stale_files(tmp_path):
    syncer, plugin = bundle_fixture(tmp_path)
    assert syncer.sync(plugin) == []
    target = plugin / "skills/gcp-to-aws/references/vendored/telemetry/metric_emission/client.py"
    target.unlink()
    assert str(target.relative_to(plugin)) in syncer.sync(plugin)
    syncer.sync(plugin, write=True)
    for name in ("plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", ".codex-plugin/plugin.json"):
        (plugin / name).write_text('{"version":"2.0.4"}')
    assert len(syncer.sync(plugin)) == 4
    syncer.sync(plugin, write=True)
    assert syncer.sync(plugin) == []


@pytest.mark.parametrize("manifest", [
    "plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", ".codex-plugin/plugin.json",
])
@pytest.mark.parametrize("mode", ["--check", "--write"])
def test_bundle_command_rejects_manifest_version_drift_without_writing(tmp_path, manifest, mode):
    _, plugin = bundle_fixture(tmp_path)
    script = plugin / "scripts/telemetry/sync_bundles.py"
    shutil.copyfile(TELEMETRY / "sync_bundles.py", script)
    before = {path.relative_to(plugin): path.read_bytes() for path in (plugin / "skills").rglob("*") if path.is_file()}
    (plugin / manifest).write_text('{"version":"2.0.4"}')
    result = subprocess.run(  # nosec B603 — local script and fixed fixture arguments
        [sys.executable, str(script), mode], capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert manifest in result.stdout
    assert "does not match plugin.json version" in result.stdout
    assert "2.0.3" in result.stdout and "2.0.4" in result.stdout
    after = {path.relative_to(plugin): path.read_bytes() for path in (plugin / "skills").rglob("*") if path.is_file()}
    assert after == before
