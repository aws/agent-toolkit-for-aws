"""Tests for the notice, the consent record, and the session-start hook.

The load-bearing one is TestNoticeIsVerbatim. Everything else guards the state
machine; that guards the wording, which is what a well-meaning edit is most likely
to break. It holds an independent copy of the approved text and compares word for
word, so the notice cannot drift without a test failing.

The client and the skill hook are in test_metric_emission.py.
"""

import json
import os
import re
import shutil
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
import uuid
from pathlib import Path

import pytest
from conftest import CONSENT, PLUGIN_ROOT, run

import notice
import record

# The approved wording, kept here as a second independent copy on purpose: a test
# that imported the string it checks would pass no matter what the string said.
# Both bracketed controls are retained exactly as the source has them and mapped
# back before comparing, so the test proves those two are the only changes.
APPROVED_NOTICE = (
    "AWS Startup Advisor plugin — usage data notice\n"
    "\n"
    "You've installed the AWS Startup Advisor plugin, which provides skills "
    "that help you build on AWS through your AI coding agent. To help us "
    "improve it, we'd like to collect optional usage data about how the plugin "
    "is used. What we collect: which skill you invoked, the plugin version, the "
    "host tool you're using, a randomly generated install identifier, and, for "
    "migration skills, the source cloud provider and which migration phase you "
    "start and complete. The usage data above is not linked to your identity. "
    "You can opt-out by [insert command/config setting]. Opting out does not "
    "change any plugin functionality.\n"
    "\n"
    "[Acknowledge]\n"
)

PLACEHOLDER = "[insert command/config setting]"
ACK_PLACEHOLDER = "[Acknowledge]"

A_UUID = "11111111-2222-3333-4444-555555555555"


def words(text):
    """Collapse whitespace so soft wrapping is not a difference, wording is."""
    return re.sub(r"\s+", " ", text).strip()


def as_source(text):
    """The notice with both substitutions mapped back to their brackets."""
    return (
        words(text)
        .replace(record.OPT_OUT_INSTRUCTION, PLACEHOLDER)
        .replace(words(notice.ACKNOWLEDGE_PROMPT), ACK_PLACEHOLDER)
    )


def write_record(home, status, install_id=A_UUID):
    """Put a record on disk directly, including ones no script will write."""
    directory = home / record.STATE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / record.STATE_FILE_NAME).write_text(
        json.dumps({"installId": install_id, "consentStatus": status})
    )


class TestNoticeIsVerbatim:
    def test_matches_approved_text_word_for_word(self):
        # Normalize before mapping substitutions back, not after: wrapping can put
        # a line break inside a substituted phrase.
        assert as_source(record.disclaimer()) == words(APPROVED_NOTICE)

    def test_opt_out_placeholder_is_substituted(self):
        assert PLACEHOLDER not in record.disclaimer()

    def test_acknowledge_button_label_is_substituted(self):
        # A GUI button label printed into a terminal is a dead string that looks
        # clickable, is not, and asks the user nothing.
        assert ACK_PLACEHOLDER not in record.disclaimer()

    def test_notice_asks_a_question_the_user_can_answer_in_words(self):
        shown = record.disclaimer()
        assert "?" in shown
        # Both answers must be on offer, not just the agreeable one.
        assert "yes" in shown
        assert "opt out" in shown

    def test_opt_out_instruction_names_the_file_and_the_key(self):
        shown = record.disclaimer()
        assert "consentStatus" in shown
        assert record.OPT_OUT in shown
        assert record.DISPLAY_STATE_PATH in shown

    def test_the_named_path_is_where_the_record_actually_lives(self, home):
        # The one failure that would make the notice a lie: a user follows it,
        # edits that file, and the plugin reads a different one.
        expanded = Path(record.DISPLAY_STATE_PATH).expanduser()
        assert expanded == record.state_path()

    def test_notice_names_no_script_and_no_install_path(self):
        # A script can only be named by its absolute path: an unbreakable token
        # over 100 characters long, different for every reader, in the middle of a
        # legal notice.
        shown = record.disclaimer()
        assert "opt_out.py" not in shown
        assert "python" not in shown
        assert str(PLUGIN_ROOT) not in shown

    def test_notice_names_no_slash_command(self):
        # Codex plugins cannot define slash commands, so one named here would be a
        # broken opt-out for every Codex user reading it.
        assert "/aws-startup-advisor:" not in record.disclaimer()

    def test_no_line_exceeds_the_wrap_width(self):
        # The word-for-word test normalizes whitespace and cannot see wrapping at
        # all, so only this one catches a line that renders long because {opt_out}
        # is substituted before wrapping. The clause is prose, not a path, so every
        # line must fit: there is no unbreakable token to excuse.
        wide = [
            line
            for line in record.disclaimer().splitlines()
            if len(line) > notice.WRAP_WIDTH
        ]
        assert wide == []

    def test_the_record_path_is_not_split_across_lines(self):
        # A path broken over a line break is an opt-out the reader has to
        # reassemble by hand, and one they will get wrong.
        assert record.DISPLAY_STATE_PATH in record.disclaimer()

    def test_structure_survives_wrapping(self):
        lines = record.disclaimer().splitlines()
        assert lines[0] == notice.NOTICE_TITLE
        assert lines[1] == ""
        blank_before_question = lines.index("", 2)
        question = " ".join(lines[blank_before_question + 1 :])
        assert question == words(notice.ACKNOWLEDGE_PROMPT)

    def test_show_prints_the_notice_exactly(self, tmp_path):
        result = run("consent/cli.py", "show", home=tmp_path)
        assert result.returncode == 0
        assert result.stdout == record.disclaimer()

    def test_show_records_nothing(self, tmp_path):
        run("consent/cli.py", "show", home=tmp_path)
        assert not (tmp_path / record.STATE_DIR_NAME).exists()


class TestReadState:
    def test_absent_is_none(self, home):
        assert record.read_state() is None
        assert record.consent_status() is None
        assert not record.is_accepted()

    def test_round_trip(self, home):
        record.write_state(record.ACCEPTED)
        state = record.read_state()
        assert state["consentStatus"] == "ACCEPTED"
        assert state["installId"]

    @pytest.mark.parametrize(
        "body",
        [
            '{"installId":',  # truncated
            "not json at all",
            "[]",  # valid json, wrong type
            '{"installId": "%s"}' % A_UUID,  # no status
            '{"consentStatus": "ACCEPTED"}',  # no install id
            '{"installId": "", "consentStatus": "ACCEPTED"}',
            '{"installId": 7, "consentStatus": "ACCEPTED"}',
            '{"installId": "abc", "consentStatus": "ACCEPTED"}',  # not a UUID
            '{"installId": "%s", "consentStatus": "accepted"}' % A_UUID,  # case
            '{"installId": "%s", "consentStatus": "MAYBE"}' % A_UUID,
            # ACCEPTED and OPT_OUT are the only two statuses there are.
            '{"installId": "%s", "consentStatus": "REJECTED"}' % A_UUID,
        ],
    )
    def test_invalid_records_fail_closed(self, home, body):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text(body)
        # Every one of these must read as "no consent", never as acceptance.
        assert record.read_state() is None
        assert not record.is_accepted()

    def test_install_id_must_be_a_uuid_because_the_service_requires_one(self, home):
        # It is sent verbatim as a @required UUID; anything else is a 400.
        write_record(home, record.ACCEPTED, install_id="not-a-uuid")
        assert record.read_state() is None

    def test_an_accepted_record_without_an_install_id_is_invalid(self, home):
        # The gate stays exactly as strict: ACCEPTED is the only status that sends
        # anything, and it is sent verbatim as a @required UUID.
        (home / record.STATE_DIR_NAME).mkdir()
        record.state_path().write_text('{"consentStatus": "ACCEPTED"}')
        assert record.read_state() is None
        assert not record.is_accepted()


class TestWriteState:
    def test_schema_has_exactly_two_keys(self, home):
        record.write_state(record.ACCEPTED)
        written = json.loads(record.state_path().read_text())
        assert set(written) == {"installId", "consentStatus"}

    def test_install_id_is_a_uuid(self, home):
        written = record.write_state(record.OPT_OUT)
        assert uuid.UUID(written["installId"])

    def test_install_id_survives_a_change_of_mind(self, home):
        first = record.write_state(record.ACCEPTED)["installId"]
        second = record.write_state(record.OPT_OUT)["installId"]
        # Flipping the answer must not look like a new install in the metrics.
        assert first == second

    def test_opt_out_record_still_has_an_install_id(self, home):
        assert record.write_state(record.OPT_OUT)["installId"]

    @pytest.mark.parametrize("status", ["MAYBE", "", "REJECTED", "accepted", None])
    def test_refuses_to_write_anything_but_the_two_statuses(self, home, status):
        with pytest.raises(ValueError):
            record.write_state(status)

    def test_leaves_no_temp_files_behind(self, home):
        record.write_state(record.ACCEPTED)
        assert [p.name for p in record.state_dir().iterdir()] == [
            record.STATE_FILE_NAME
        ]


class TestTheNoticesOwnInstructionWorks:
    """What a user gets if they do exactly what the notice tells them.

    The notice says to set `consentStatus` to OPT_OUT in the record file. It does
    not tell them to invent a UUID, so a record carrying only that one key has to
    be a supported input. If it read as corrupt, following the notice would leave
    the user opted out in their own mind and re-prompted next session.
    """

    MINIMAL = '{"consentStatus": "OPT_OUT"}'

    def hand_edit(self, home, body=None):
        directory = home / record.STATE_DIR_NAME
        directory.mkdir(parents=True, exist_ok=True)
        record.state_path().write_text(body or self.MINIMAL)

    def test_is_read_as_opted_out(self, home):
        self.hand_edit(home)
        assert record.consent_status() == record.OPT_OUT
        assert not record.is_accepted()

    def test_silences_the_session_start_hook(self, home):
        self.hand_edit(home)
        assert run("consent/session_start.py", home=home).stdout == ""

    def test_status_reports_off(self, home):
        self.hand_edit(home)
        out = run("consent/cli.py", "status", home=home).stdout
        assert "collection: OFF" in out

    def test_a_utf8_bom_does_not_undo_the_opt_out(self, home):
        # What a Windows editor writes. Rejecting it would re-raise the notice at
        # someone who did exactly what it told them, every session.
        directory = home / record.STATE_DIR_NAME
        directory.mkdir(parents=True, exist_ok=True)
        record.state_path().write_bytes(b"\xef\xbb\xbf" + self.MINIMAL.encode())
        assert record.consent_status() == record.OPT_OUT
        assert not record.is_accepted()
        assert run("consent/session_start.py", home=home).stdout == ""

    def test_a_utf8_bom_does_not_undo_an_acceptance(self, home):
        install_id = record.write_state(record.ACCEPTED)["installId"]
        body = record.state_path().read_text()
        record.state_path().write_bytes(b"\xef\xbb\xbf" + body.encode())
        assert record.is_accepted()
        assert record.read_state()["installId"] == install_id

    def test_opting_back_in_mints_an_install_id(self, home):
        self.hand_edit(home)
        written = record.write_state(record.ACCEPTED)
        # Nothing to preserve, so a new one rather than a record the service
        # would reject.
        assert uuid.UUID(written["installId"])

    def test_a_garbage_install_id_is_replaced_not_preserved(self, home):
        self.hand_edit(home, '{"installId": "nonsense", "consentStatus": "OPT_OUT"}')
        written = record.write_state(record.ACCEPTED)
        assert uuid.UUID(written["installId"])
        assert record.is_accepted()

    def test_the_edit_the_notice_describes_turns_collection_off(self, home):
        # Start from a real accepted record, then make only the change the notice
        # names — leaving the install ID alone, as a hand-edit would.
        install_id = record.write_state(record.ACCEPTED)["installId"]
        self.hand_edit(
            home,
            json.dumps({"installId": install_id, "consentStatus": "OPT_OUT"}),
        )
        assert not record.is_accepted()
        assert record.read_state()["installId"] == install_id


class TestNoEnvironmentSwitch:
    """The record file is the only source of truth.

    No variable may turn collection on, and none may silently *suppress* an
    accepted record either: a user who sets one in their shell would otherwise
    believe they had changed something they had not.
    """

    @pytest.mark.parametrize(
        "name", ["AWS_STARTUP_ADVISOR_TELEMETRY", "DO_NOT_TRACK", "TELEMETRY"]
    )
    def test_no_variable_overrides_the_record(self, home, monkeypatch, name):
        record.write_state(record.ACCEPTED)
        monkeypatch.setenv(name, "off")
        assert record.is_accepted()

    def test_opting_out_needs_no_shell_knowledge(self):
        # The export trap: a bare NAME=value assigns an unexported shell variable
        # no child process can see, so a user can believe they have opted out when
        # they have not. A script cannot be got wrong that way.
        assert "export" not in record.opt_out_help()
        assert "opt_out.py" in record.opt_out_help()


class TestCliUsage:
    @pytest.mark.parametrize(
        "args", [(), ("bogus",), ("show", "extra"), ("check",), ("status", "x")]
    )
    def test_usage_error_exits_2(self, tmp_path, args):
        assert run("consent/cli.py", *args, home=tmp_path).returncode == 2


class TestAcceptAndOptOut:
    def written(self, home):
        path = home / record.STATE_DIR_NAME / record.STATE_FILE_NAME
        return json.loads(path.read_text())

    def test_accept_writes_accepted(self, tmp_path):
        assert run("consent/accept.py", home=tmp_path).returncode == 0
        assert self.written(tmp_path)["consentStatus"] == "ACCEPTED"

    def test_opt_out_writes_opt_out(self, tmp_path):
        assert run("consent/opt_out.py", home=tmp_path).returncode == 0
        assert self.written(tmp_path)["consentStatus"] == "OPT_OUT"

    def test_opt_out_tells_the_user_nothing_is_disabled(self, tmp_path):
        assert "still works" in run("consent/opt_out.py", home=tmp_path).stdout

    def test_accept_output_tells_the_user_how_to_opt_out(self, tmp_path):
        assert "opt_out.py" in run("consent/accept.py", home=tmp_path).stdout

    def test_accept_fails_loudly_when_it_cannot_write(self, tmp_path):
        # A file where the state directory should go: mkdir cannot succeed.
        (tmp_path / record.STATE_DIR_NAME).write_text("")
        result = run("consent/accept.py", home=tmp_path)
        # Must not report success it did not achieve.
        assert result.returncode == 1
        assert result.stderr


class TestStatus:
    def test_reports_on_and_how_to_opt_out(self, tmp_path):
        run("consent/accept.py", home=tmp_path)
        out = run("consent/cli.py", "status", home=tmp_path).stdout
        assert "collection: ON" in out
        assert "opt_out.py" in out

    def test_reports_off_when_opted_out(self, home):
        write_record(home, record.OPT_OUT)
        out = run("consent/cli.py", "status", home=home).stdout
        assert "collection: OFF" in out
        assert "opted out" in out

    def test_reports_nothing_recorded(self, tmp_path):
        out = run("consent/cli.py", "status", home=tmp_path).stdout
        assert "Nothing is recorded yet" in out


class TestSessionStartHook:
    HOOK = "consent/session_start.py"

    def test_speaks_when_no_record_exists(self, tmp_path):
        result = run(self.HOOK, home=tmp_path)
        assert result.returncode == 0
        assert "cli.py" in result.stdout
        assert "VERBATIM" in result.stdout

    def test_instruction_carries_absolute_runnable_paths(self, tmp_path):
        result = run(self.HOOK, home=tmp_path)
        # A ${...PLUGIN_ROOT} would reach the model unexpanded and not run.
        assert "PLUGIN_ROOT" not in result.stdout
        for script in ("cli.py", "accept.py", "opt_out.py"):
            assert str(CONSENT / script) in result.stdout

    @pytest.mark.parametrize(
        "phrase",
        [
            # The failure these prevent: the agent shows the notice and answers
            # the user's question in the same message, so the user reads the
            # answer and never replies to the notice.
            "END YOUR TURN THERE",
            "do not answer their request in the same message",
            "do not call any other tool",
            # The notice carries its own question; the agent added a second one.
            "do not restate it",
            # Pausing is only acceptable if the user need not ask twice.
            "answer their original request in full",
            "repeat themselves",
            # Refusing to work until a telemetry question is answered would be
            # worse than never asking.
            "If they ignore the notice",
            "not a gate",
        ],
    )
    def test_instruction_says_the_things_that_were_got_wrong_before(
        self, tmp_path, phrase
    ):
        # Normalized: the instruction is wrapped and these phrases straddle breaks.
        out = " ".join(run(self.HOOK, home=tmp_path).stdout.split())
        assert phrase in out

    def test_instruction_mentions_no_environment_variable(self, tmp_path):
        out = run(self.HOOK, home=tmp_path).stdout
        assert "export" not in out
        assert "AWS_STARTUP_ADVISOR_TELEMETRY" not in out

    @pytest.mark.parametrize("script", ["consent/accept.py", "consent/opt_out.py"])
    def test_silent_once_answered(self, tmp_path, script):
        run(script, home=tmp_path)
        result = run(self.HOOK, home=tmp_path)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_speaks_again_when_the_record_is_corrupt(self, tmp_path):
        directory = tmp_path / record.STATE_DIR_NAME
        directory.mkdir()
        (directory / record.STATE_FILE_NAME).write_text('{"installId":')
        assert run(self.HOOK, home=tmp_path).stdout != ""

    def test_prints_plain_text_not_a_json_envelope(self, tmp_path):
        # Claude Code takes stdout verbatim as extra context.
        out = run(self.HOOK, home=tmp_path).stdout
        assert out.startswith("[AWS Startup Advisor]")

    def test_does_not_block_on_a_stdin_pipe_that_never_closes(self, tmp_path):
        """A host may hand the hook a pipe it holds open.

        Reading stdin would then block until an EOF that never arrives, the host
        would kill the hook at its timeout, and the notice would silently never
        appear.

        `stdin=subprocess.PIPE` plus `communicate()` will NOT catch that —
        communicate closes stdin at once, so a blocking read passes. The write end
        has to stay open.
        """
        read_fd, write_fd = os.pipe()  # parent keeps write_fd open: no EOF
        try:
            proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
                [sys.executable, str(CONSENT / "session_start.py")],
                stdin=read_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            )
            os.close(read_fd)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                pytest.fail("hook blocked on stdin instead of exiting")
            stdout = proc.stdout.read()
            proc.stdout.close()
        finally:
            os.close(write_fd)

        assert proc.returncode == 0
        assert "cli.py" in stdout  # and it still did its job

    def test_exits_zero_with_a_hook_payload_on_stdin(self, tmp_path):
        payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "x"})
        result = subprocess.run(  # nosec B603 — fixed argv, no shell
            [sys.executable, str(CONSENT / "session_start.py")],
            input=payload,
            capture_output=True,
            text=True,
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0

    def test_exits_zero_even_when_home_is_undiscoverable(self, tmp_path):
        result = subprocess.run(  # nosec B603 — fixed argv, no shell
            [sys.executable, str(CONSENT / "session_start.py")],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0


class TestHookWiring:
    """Against the shipped hooks.json, not a copy of its command.

    The command line is where the Python dependency actually bites, and it is data
    in a JSON file no other test touches.
    """

    HOOKS_JSON = PLUGIN_ROOT / "com.anthropic.claude-code" / "hooks" / "hooks.json"

    WIRED = {
        "SessionStart": "scripts/telemetry/consent/session_start.py",
        "PostToolUse": "scripts/telemetry/metric_emission/skill_invoked.py",
    }

    @classmethod
    def command_for(cls, event):
        hooks = json.loads(cls.HOOKS_JSON.read_text())["hooks"]
        commands = [
            hook["command"]
            for entry in hooks[event]
            for hook in entry["hooks"]
            if cls.WIRED[event] in hook["command"]
        ]
        assert len(commands) == 1, "expected exactly one %s telemetry hook" % event
        return commands[0].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))

    @pytest.mark.parametrize("event", sorted(WIRED))
    def test_tries_every_common_interpreter_name(self, event):
        command = self.command_for(event)
        # python3, then python, then the Windows launcher.
        for interpreter in ("python3", "python", "py -3"):
            assert interpreter in command

    @pytest.mark.parametrize("event", sorted(WIRED))
    def test_the_wired_path_exists(self, event):
        # Catches hooks.json going stale when a script is moved or renamed.
        script = PLUGIN_ROOT / self.WIRED[event]
        assert script.is_file()
        assert str(script) in self.command_for(event)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX shell and PATH shimming")
    @pytest.mark.parametrize("event", sorted(WIRED))
    def test_is_silent_when_no_python_is_installed(self, tmp_path, event):
        """A user with no Python must see nothing, not a hook error.

        The `|| true` is what guarantees it: without it the last fallback exits 127
        and prints "py: command not found", which a host can surface as a failing
        hook. No Python means no record, so no telemetry is lost by staying quiet.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("sh", "cat", "env"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)

        result = subprocess.run(  # nosec B602 — exercising the shipped command
            self.command_for(event),
            shell=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={"HOME": str(tmp_path), "PATH": str(bin_dir)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_the_consent_hook_still_speaks_when_python_is_installed(self, tmp_path):
        result = subprocess.run(  # nosec B602 — as above
            self.command_for("SessionStart"),
            shell=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0
        assert "cli.py" in result.stdout
        assert result.stderr == ""

    def test_the_skill_hook_is_matched_on_the_skill_tool(self):
        # Claude Code has no skill-specific event; skills run through the `Skill`
        # tool, so the matcher is the whole of how this hook finds them.
        entries = json.loads(self.HOOKS_JSON.read_text())["hooks"]["PostToolUse"]
        matching = [
            entry
            for entry in entries
            for hook in entry["hooks"]
            if "skill_invoked.py" in hook["command"]
        ]
        assert len(matching) == 1
        assert matching[0]["matcher"] == "Skill"
