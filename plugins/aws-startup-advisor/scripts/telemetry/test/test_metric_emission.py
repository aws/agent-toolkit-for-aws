"""Tests for the telemetry client and the skill-invocation hook.

Two things are checked against independent second copies rather than against the
code's own constants: the PluginSkillId enum (transcribed from the service model)
and the prod endpoint. A test that imported those would pass whatever they said.

Nothing here reaches prod. Every emitting test either points the client at the
local `collector` fixture or asserts that nothing was sent at all.
"""

import json
import os
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
import time

import pytest
from conftest import EMISSION, PLUGIN_ROOT, run

import client
import record
import skill_invoked

# PluginSkillId, transcribed from model/types/plugin-telemetry.smithy.
MODELLED_SKILL_IDS = {
    "AGENT_ADVISOR",
    "ARCHITECT_FOR_STARTUPS",
    "AZURE_TO_AWS",
    "CONTEXTUAL_OFFERS_FOR_STARTUPS",
    "GCP_TO_AWS",
    "HEROKU_TO_AWS",
    "KNOWLEDGE_BASE_FOR_STARTUPS",
    "LLM_TO_BEDROCK",
    "OPERATE_ON_AWS",
    "PROMPT_LIBRARY_FOR_STARTUPS",
    "START_BUILDING_FOR_STARTUPS",
    "TF_BEST_PRACTICES",
}

PROD_HOST = "us-east-1.prod.startup-advisor-extension.saws.activate.aws.dev"

A_UUID = "11111111-2222-3333-4444-555555555555"

SKILLS_DIR = PLUGIN_ROOT / "skills"

# Imported by skills, not a skill: it has no SKILL.md and cannot be invoked.
NOT_A_SKILL = {"shared"}


def accept(home):
    """An accepted record on disk, and its install ID."""
    return record.write_state(record.ACCEPTED)["installId"]


def events(collector):
    """The decoded `pluginTelemetryEvent` of every request the collector got."""
    return [
        json.loads(request["body"])["pluginTelemetryEvent"]
        for request in collector.received
    ]


class TestSkillIdMap:
    def test_every_value_is_a_modelled_enum_member(self):
        # An unmodelled member is a 400 for the whole request.
        assert set(skill_invoked.SKILL_IDS.values()) <= MODELLED_SKILL_IDS

    def test_every_modelled_member_is_reachable(self):
        # Otherwise a skill ships with no way to ever be counted.
        assert set(skill_invoked.SKILL_IDS.values()) == MODELLED_SKILL_IDS

    def test_keys_are_exactly_this_plugin_s_skill_directories(self):
        on_disk = {
            path.name
            for path in SKILLS_DIR.iterdir()
            if path.is_dir() and path.name not in NOT_A_SKILL
        }
        # The map is an allowlist, so a new skill is invisible until added here,
        # and a renamed directory stops being counted silently.
        assert set(skill_invoked.SKILL_IDS) == on_disk

    def test_the_client_agrees_with_the_model(self):
        assert set(client.PLUGIN_SKILL_IDS) == MODELLED_SKILL_IDS


class TestSkillId:
    def test_maps_a_bare_name(self):
        assert skill_invoked.skill_id("gcp-to-aws") == "GCP_TO_AWS"

    @pytest.mark.parametrize(
        "name",
        [
            "aws-startup-advisor:gcp-to-aws",
            "GCP-TO-AWS",
            "  gcp-to-aws  ",
            "some-other-qualifier:gcp-to-aws",
        ],
    )
    def test_tolerates_qualifiers_and_casing(self, name):
        # Hosts qualify skill names differently and undocumentedly, so an
        # unrecognized qualifier is not a reason to lose the event.
        assert skill_invoked.skill_id(name) == "GCP_TO_AWS"

    @pytest.mark.parametrize("name", ["shared", "some-other-plugin-skill", "", None, 7])
    def test_anything_not_ours_is_none(self, name):
        # Upper-casing whatever the host passed would put another plugin's skill
        # names in our request body.
        assert skill_invoked.skill_id(name) is None


class TestSkillName:
    def test_reads_the_claude_code_payload(self):
        payload = {"tool_name": "Skill", "tool_input": {"skill": "gcp-to-aws"}}
        assert skill_invoked.skill_name([], payload) == "gcp-to-aws"

    @pytest.mark.parametrize(
        "argv", [["--skill", "gcp-to-aws"], ["--skill=gcp-to-aws"]]
    )
    def test_the_flag_wins_so_the_hook_is_runnable_by_hand(self, argv):
        payload = {"tool_input": {"skill": "heroku-to-aws"}}
        assert skill_invoked.skill_name(argv, payload) == "gcp-to-aws"

    @pytest.mark.parametrize(
        "payload",
        [{}, {"tool_input": None}, {"tool_input": {}}, {"tool_input": {"skill": 7}}],
    )
    def test_a_payload_without_a_skill_is_none(self, payload):
        assert skill_invoked.skill_name([], payload) is None


class TestReadHookPayload:
    def test_parses_an_object(self):
        from io import StringIO

        stream = StringIO('{"tool_input": {"skill": "gcp-to-aws"}}')
        assert skill_invoked.read_hook_payload(stream)["tool_input"]["skill"]

    @pytest.mark.parametrize("raw", ["", "not json", "[]", '"a string"'])
    def test_anything_else_is_an_empty_dict(self, raw):
        from io import StringIO

        assert skill_invoked.read_hook_payload(StringIO(raw)) == {}

    def test_gives_up_at_the_deadline(self):
        class NeverEnds:
            def read(self):
                time.sleep(30)

        started = time.monotonic()
        assert skill_invoked.read_hook_payload(NeverEnds(), timeout=0.2) == {}
        # The point is that it returns at all; a bare read() would block for 30s.
        assert time.monotonic() - started < 5


class TestEndpoint:
    def test_defaults_to_prod(self, monkeypatch):
        monkeypatch.delenv(client.ENDPOINT_ENV, raising=False)
        assert client.endpoint() == ("https://%s/v1/plugin-telemetry-event" % PROD_HOST)

    def test_the_override_is_honored(self, monkeypatch):
        monkeypatch.setenv(client.ENDPOINT_ENV, "http://127.0.0.1:1/x")
        assert client.endpoint() == "http://127.0.0.1:1/x"

    def test_a_blank_override_falls_back_to_prod(self, monkeypatch):
        # An unset-by-way-of-empty variable must not produce an unusable URL.
        monkeypatch.setenv(client.ENDPOINT_ENV, "   ")
        assert PROD_HOST in client.endpoint()


class TestPostEventIsFireAndForget:
    """`post_event` must never raise and never report a failure to the caller.

    A telemetry POST is not something the user asked for, so it must not be able
    to fail an operation they did ask for.
    """

    def test_sends_when_accepted(self, home, collector):
        install_id = accept(home)
        assert client.post_event({"consentRecorded": {}}, install_id, collector.url)
        assert len(collector.received) == 1

    @pytest.mark.parametrize(
        "url",
        [
            "not a url",
            "http://",
            "nosuchscheme://host/path",
            "http://127.0.0.1:1/unreachable",
        ],
    )
    def test_a_broken_url_returns_false_instead_of_raising(self, home, url):
        install_id = accept(home)
        assert client.post_event({"consentRecorded": {}}, install_id, url) is False

    def test_an_unserializable_event_returns_false(self, home, collector):
        install_id = accept(home)
        assert client.post_event({"bad": object()}, install_id, collector.url) is False
        assert collector.received == []

    def test_a_missing_install_id_returns_false(self, home, collector):
        accept(home)
        assert client.post_event({"consentRecorded": {}}, None, collector.url) is False
        assert collector.received == []

    def test_an_unknown_plugin_version_sends_nothing(
        self, home, collector, monkeypatch
    ):
        # None from plugin_version() is a refusal to send, not a default: a made-up
        # version would misattribute the event.
        install_id = accept(home)
        monkeypatch.setattr(client, "plugin_version", lambda: None)
        assert (
            client.post_event({"consentRecorded": {}}, install_id, collector.url)
            is False
        )
        assert collector.received == []

    def test_a_non_2xx_response_is_false_but_not_an_error(
        self, home, monkeypatch, collector
    ):
        install_id = accept(home)

        class Forbidden:
            status = 403

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(
            client.urllib.request, "urlopen", lambda *a, **k: Forbidden()
        )
        # A rejection is not an error here: it is dropped like any other failure.
        assert (
            client.post_event({"consentRecorded": {}}, install_id, "http://x") is False
        )


class TestPostEventRechecksConsent:
    """The gate is re-checked inside `post_event`, not only at the call site."""

    def test_nothing_recorded_sends_nothing(self, home, collector):
        assert (
            client.post_event({"consentRecorded": {}}, A_UUID, collector.url) is False
        )
        assert collector.received == []

    def test_opted_out_sends_nothing(self, home, collector):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text(
            json.dumps({"installId": A_UUID, "consentStatus": "OPT_OUT"})
        )
        assert (
            client.post_event({"consentRecorded": {}}, A_UUID, collector.url) is False
        )
        assert collector.received == []

    def test_a_hand_edited_opt_out_sends_nothing(self, home, collector):
        # The record the notice's own instruction produces: one key, no install ID.
        # send_event has to cope with that rather than raising a KeyError.
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text('{"consentStatus": "OPT_OUT"}')
        assert client.send_event({"consentRecorded": {}}) is False
        assert collector.received == []

    def test_a_corrupt_record_sends_nothing(self, home, collector):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text('{"installId":')
        assert (
            client.post_event({"consentRecorded": {}}, A_UUID, collector.url) is False
        )
        assert collector.received == []


class TestPayloadMatchesTheModel:
    def test_carries_every_required_field(self, home, collector):
        install_id = accept(home)
        client.post_event({"consentRecorded": {}}, install_id, collector.url)
        body = json.loads(collector.received[0]["body"])
        assert set(body) == {
            "installId",
            "source",
            "pluginVersion",
            "occurredAt",
            "pluginTelemetryEvent",
        }
        assert body["installId"] == install_id

    def test_is_sent_as_json(self, home, collector):
        client.post_event({"consentRecorded": {}}, accept(home), collector.url)
        assert collector.received[0]["content_type"] == "application/json"

    def test_occurred_at_is_epoch_milliseconds_not_seconds(self, home, collector):
        # Seconds would land in 1970 and the service drops nothing, so this is a
        # mistake only a test can catch.
        client.post_event({"consentRecorded": {}}, accept(home), collector.url)
        body = json.loads(collector.received[0]["body"])
        assert isinstance(body["occurredAt"], int)
        assert abs(body["occurredAt"] - time.time() * 1000) < 60_000

    def test_occurred_at_is_not_in_the_future(self, home, collector):
        # The service silently drops anything more than five minutes ahead, with a
        # 200, so a fast clock loses its telemetry with no signal in the response.
        client.post_event({"consentRecorded": {}}, accept(home), collector.url)
        body = json.loads(collector.received[0]["body"])
        assert body["occurredAt"] <= time.time() * 1000 + 1000

    def test_version_comes_from_the_plugin_manifest(self):
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text()
        )
        assert client.plugin_version() == manifest["version"]


class TestDetectSource:
    def test_claude_code_is_recognized(self, monkeypatch):
        for name, _ in client._HOST_MARKERS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CLAUDECODE", "1")
        assert client.detect_source() == "CLAUDE_CODE"

    def test_an_unknown_host_is_other(self, monkeypatch):
        for name, _ in client._HOST_MARKERS:
            monkeypatch.delenv(name, raising=False)
        # Not a plausible guess: a wrong attribution silently moves one host's
        # numbers into another's.
        assert client.detect_source() == "OTHER"

    def test_no_variable_can_set_the_source(self, monkeypatch):
        for name, _ in client._HOST_MARKERS:
            monkeypatch.delenv(name, raising=False)
        # There is no override: the host is detected, never declared.
        monkeypatch.setenv("AWS_STARTUP_ADVISOR_SOURCE", "CURSOR")
        assert client.detect_source() == "OTHER"


class TestEmitSkillInvocationMetric:
    def test_sends_the_modelled_event_shape(self, home, collector):
        install_id = accept(home)
        assert client.emit_skill_invocation_metric(
            install_id, "GCP_TO_AWS", collector.url
        )
        assert events(collector) == [
            {"skillInvoked": {"skill": "GCP_TO_AWS", "eventName": "SKILL_INVOKED"}}
        ]

    @pytest.mark.parametrize("skill", ["gcp-to-aws", "NOT_A_SKILL", "", None])
    def test_an_unmodelled_skill_is_dropped_before_the_wire(
        self, home, collector, skill
    ):
        install_id = accept(home)
        assert (
            client.emit_skill_invocation_metric(install_id, skill, collector.url)
            is False
        )
        assert collector.received == []


class TestSendConsentRecorded:
    def test_sends_the_empty_details_member(self, home, collector, monkeypatch):
        accept(home)
        monkeypatch.setenv(client.ENDPOINT_ENV, collector.url)
        assert client.send_consent_recorded()
        assert events(collector) == [{"consentRecorded": {}}]

    def test_accept_emits_it_end_to_end(self, tmp_path, collector):
        result = run(
            "consent/accept.py",
            home=tmp_path,
            env={client.ENDPOINT_ENV: collector.url},
        )
        assert result.returncode == 0
        assert events(collector) == [{"consentRecorded": {}}]

    def test_opting_out_sends_nothing(self, tmp_path, collector):
        # ConsentRecordedDetails is empty and cannot say which way the user
        # answered, so a request from here would be indistinguishable from a yes.
        result = run(
            "consent/opt_out.py",
            home=tmp_path,
            env={client.ENDPOINT_ENV: collector.url},
        )
        assert result.returncode == 0
        assert collector.received == []

    def test_a_dead_endpoint_does_not_fail_accept(self, tmp_path):
        result = run(
            "consent/accept.py",
            home=tmp_path,
            env={client.ENDPOINT_ENV: "http://127.0.0.1:1/nope"},
        )
        assert result.returncode == 0
        assert "collection is ON" in result.stdout
        # The user is told nothing about one HTTPS request; they said yes, not
        # "report on the network".
        assert "127.0.0.1" not in result.stdout


class TestSkillInvokedHookEndToEnd:
    HOOK = "metric_emission/skill_invoked.py"

    def payload(self, skill):
        return json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Skill",
                "tool_input": {"skill": skill},
            }
        )

    def invoke(self, home, collector, stdin="", args=()):
        proc = subprocess.run(  # nosec B603 — fixed argv, no shell
            [sys.executable, str(EMISSION / "skill_invoked.py"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env={
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                client.ENDPOINT_ENV: collector.url,
            },
        )
        # Always 0 and always silent: the user asked for the skill, not for this.
        assert proc.returncode == 0
        assert proc.stdout == ""
        return proc

    def test_reports_the_skill_from_the_tool_payload(self, home, collector):
        accept(home)
        self.invoke(home, collector, stdin=self.payload("gcp-to-aws"))
        assert events(collector) == [
            {"skillInvoked": {"skill": "GCP_TO_AWS", "eventName": "SKILL_INVOKED"}}
        ]

    def test_reports_the_skill_from_the_flag(self, home, collector):
        accept(home)
        self.invoke(home, collector, args=("--skill", "llm-to-bedrock"))
        assert events(collector) == [
            {"skillInvoked": {"skill": "LLM_TO_BEDROCK", "eventName": "SKILL_INVOKED"}}
        ]

    def test_the_install_id_is_the_recorded_one(self, home, collector):
        install_id = accept(home)
        self.invoke(home, collector, stdin=self.payload("agent-advisor"))
        assert json.loads(collector.received[0]["body"])["installId"] == install_id

    def test_nothing_recorded_sends_nothing(self, home, collector):
        self.invoke(home, collector, stdin=self.payload("gcp-to-aws"))
        assert collector.received == []

    def test_opted_out_sends_nothing(self, home, collector):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text(
            json.dumps({"installId": A_UUID, "consentStatus": "OPT_OUT"})
        )
        self.invoke(home, collector, stdin=self.payload("gcp-to-aws"))
        assert collector.received == []

    @pytest.mark.parametrize(
        "body",
        [
            '{"installId":',
            '{"installId": "abc", "consentStatus": "ACCEPTED"}',
            '{"consentStatus": "ACCEPTED"}',
        ],
    )
    def test_an_invalid_record_sends_nothing(self, home, collector, body):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text(body)
        self.invoke(home, collector, stdin=self.payload("gcp-to-aws"))
        assert collector.received == []

    @pytest.mark.parametrize(
        "skill", ["shared", "some-other-plugins-skill", "Bash", ""]
    )
    def test_a_skill_that_is_not_ours_sends_nothing(self, home, collector, skill):
        accept(home)
        self.invoke(home, collector, stdin=self.payload(skill))
        assert collector.received == []

    @pytest.mark.parametrize("stdin", ["", "not json", "[]"])
    def test_an_unreadable_payload_sends_nothing(self, home, collector, stdin):
        accept(home)
        self.invoke(home, collector, stdin=stdin)
        assert collector.received == []

    def test_a_dead_endpoint_still_exits_zero(self, home):
        accept(home)
        proc = subprocess.run(  # nosec B603 — fixed argv, no shell
            [sys.executable, str(EMISSION / "skill_invoked.py")],
            input=self.payload("gcp-to-aws"),
            capture_output=True,
            text=True,
            env={
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                client.ENDPOINT_ENV: "http://127.0.0.1:1/nope",
            },
        )
        assert proc.returncode == 0
        assert proc.stdout == ""

    def test_does_not_block_on_a_stdin_pipe_that_never_closes(self, home, collector):
        """The hook must read stdin, so it must also survive a pipe with no EOF.

        A host may hand it a pipe it holds open; a bare read() would then stall the
        turn after every single skill call. `communicate()` cannot reproduce this —
        it closes stdin at once — so the write end stays open here.
        """
        accept(home)
        read_fd, write_fd = os.pipe()
        try:
            proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
                [sys.executable, str(EMISSION / "skill_invoked.py")],
                stdin=read_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env={
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    client.ENDPOINT_ENV: collector.url,
                },
            )
            os.close(read_fd)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                pytest.fail("hook blocked on stdin instead of exiting")
            proc.stdout.close()
        finally:
            os.close(write_fd)

        assert proc.returncode == 0
