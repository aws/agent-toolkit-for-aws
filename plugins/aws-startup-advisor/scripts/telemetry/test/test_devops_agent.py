"""Reporting the AWS DevOps Agent Space the operate-on-aws skill creates."""

import importlib.util
import json
import shutil
import subprocess  # nosec B404 — test-only, fixed argv
import sys

import pytest
from conftest import CONSENT, PLUGIN_ROOT, TELEMETRY

import agent_space
import client
import notice
import record

SPACE_ID = "3d8e4be4-6254-444a-bb9c-fb85dbb5a726"
CLI = TELEMETRY / "devops_agent_cli.py"
# Loaded by path: only consent/ and metric_emission/ are on the test import path.
_spec = importlib.util.spec_from_file_location("devops_agent_cli", CLI)
devops_agent_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(devops_agent_cli)
CREATED = [{"devOpsAgentSpaceCreated": {"agentSpaceId": SPACE_ID}}]
DISCLOSED = agent_space.DISCLOSED_IN_NOTICE_VERSION


def events(collector):
    return [json.loads(row["body"])["pluginTelemetryEvent"] for row in collector.received]


def run(script, args, home, collector, markers=None):
    env = {"HOME": str(home), "USERPROFILE": str(home), "PATH": "/usr/bin:/bin", client.ENDPOINT_ENV: collector.url}
    env.update(markers or {})
    proc = subprocess.run(  # nosec B603 — fixed argv, no shell
        [sys.executable, str(script), *args], capture_output=True, text=True, env=env, timeout=10,
    )
    # Always 0: the user asked for the Agent Space, not for this.
    assert proc.returncode == 0
    return proc


def status(capsys):
    assert devops_agent_cli.main(["status"]) == 0
    return json.loads(capsys.readouterr().out)


class TestReporting:
    @pytest.fixture(autouse=True)
    def endpoint(self, monkeypatch, home, collector):
        # After `home`, which points the endpoint at a dead address.
        monkeypatch.setenv(client.ENDPOINT_ENV, collector.url)

    def test_the_shipped_notice_names_the_agent_space_id(self):
        assert notice.NOTICE_VERSION >= DISCLOSED
        assert "the ID of the AWS DevOps Agent Space it creates" in notice.NOTICE_BODY

    def test_a_real_acknowledgement_then_reports_the_space(self, home, collector):
        # show → acknowledge → report, through the scripts the skill runs, with no hand-edited record.
        out = json.loads(run(CLI, ("status",), home, collector).stdout)
        assert out["needsNotice"] is True
        run(CONSENT / "cli.py", ("show",), home, collector)
        run(CONSENT / "accept.py", (), home, collector)
        collector.received.clear()  # accept.py's own consentRecorded event
        assert json.loads(run(CLI, ("status",), home, collector).stdout)["needsNotice"] is False
        run(CLI, ("space-created", "--agent-space-id", SPACE_ID), home, collector, {"KIRO_IDE": "1"})
        assert events(collector) == CREATED

    @pytest.mark.parametrize("consent, needs_notice", [("none", True), ("older notice", True), ("opt-out", False)])
    def test_anything_else_sends_nothing(self, home, collector, capsys, consent, needs_notice):
        if consent == "older notice":
            # Acknowledged before the notice named the Agent Space ID.
            written = record.write_state(record.ACCEPTED)
            written["noticeVersion"] = DISCLOSED - 1
            record.state_path().write_text(json.dumps(written))
        elif consent == "opt-out":
            record.write_state(record.OPT_OUT)
        assert status(capsys)["needsNotice"] is needs_notice
        assert devops_agent_cli.main(["space-created", "--agent-space-id", SPACE_ID]) == 0
        assert collector.received == []

    @pytest.mark.parametrize("value", ["My production space", "", "a" * 65, None, 123])
    def test_sends_nothing_that_isnt_an_id(self, home, collector, value):
        record.write_state(record.ACCEPTED)
        assert not agent_space.send_created(value)
        assert collector.received == []


class TestBundle:
    def test_the_operate_on_aws_bundle_runs_on_its_own(self, tmp_path, home, collector):
        # A standalone skill install: the vendored bundle, no enclosing plugin.
        isolated = tmp_path / "operate-on-aws"
        shutil.copytree(PLUGIN_ROOT / "skills/operate-on-aws/references/vendored/telemetry", isolated / "telemetry")
        record.write_state(record.ACCEPTED)
        run(isolated / "telemetry/devops_agent_cli.py", ("space-created", "--agent-space-id", SPACE_ID), home, collector,
            {"KIRO_IDE": "1"})
        assert events(collector) == CREATED
        assert json.loads(collector.received[0]["body"])["source"] == "KIRO"

    def test_the_operate_on_aws_bundle_carries_only_what_it_uses(self):
        bundle = PLUGIN_ROOT / "skills/operate-on-aws/references/vendored/telemetry"
        files = {str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file()}
        assert files == {
            "devops_agent_cli.py", "version.json", "consent/record.py", "consent/notice.py", "consent/cli.py",
            "consent/accept.py", "consent/opt_out.py", "metric_emission/client.py", "metric_emission/agent_space.py",
        }


def test_no_hook_reports_agent_spaces():
    # Only the skill reports, after verifying its own creation; a hook would see other tools' too.
    for manifest in ("com.anthropic.claude-code/hooks/hooks.json", ".cursor-plugin/hooks.json"):
        assert "agent_space" not in (PLUGIN_ROOT / manifest).read_text()
