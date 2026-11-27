"""Unit tests for the AWS Context hooks. Run: python3 -m unittest discover -s com.anthropic.claude-code/hooks/tests"""

import base64
import datetime
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import context_steering  # noqa: E402
import hook_config  # noqa: E402
import session_feedback  # noqa: E402

ARN = "arn:aws:context:us-west-2:111122223333:agent-context/ac-0123456789abcdef0123456789abcdef"
READERS = [{"access": "ALLOW", "principalId": "*"}]
CALL = ('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1",'
        '"name":"mcp__plugin_aws-context_aws-context__context___SearchAgentContext","input":{}}]}}\n')
LISTED = ('{"type":"user","message":{"content":[{"type":"tool_result","content":[{"type":"tool_reference",'
          '"tool_name":"mcp__plugin_aws-context_aws-context__context___PutTrace"}]}]}}\n')
CREDS = {"AccessKeyId": "AKIDEXAMPLE", "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"}


class Home:
    """Point every hook path at a fresh temporary directory."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(hook_config, "CONFIG_DIR", root),
            mock.patch.object(hook_config, "CONFIG_FILE", root / "config.json"),
            mock.patch.object(session_feedback, "SPOOL", root / "spool"),
            mock.patch.object(session_feedback, "STATUS_FILE", root / "feedback-status.json"),
            mock.patch.object(session_feedback, "SESSIONS", root / "sessions"),
        ]
        for p in self.patches:
            p.start()
        return root

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


def write_config(root, **cfg):
    (root / "config.json").write_text(json.dumps(cfg))


def transcript(root, text):
    path = root / "t.jsonl"
    path.write_text(text)
    return path


def run_feedback(event):
    """Run the hook and send in-process: a failing Popen makes it skip the detached sender."""
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))), \
            mock.patch.object(session_feedback.subprocess, "Popen", side_effect=OSError):
        session_feedback.main()


class ConfigTests(unittest.TestCase):
    def test_missing_or_bad_config_means_both_hooks_off(self):
        with Home() as root:
            self.assertEqual(hook_config.load(), {"steering": "off", "feedback": "off"})
            (root / "config.json").write_text("not json")
            self.assertEqual(hook_config.load()["feedback"], "off")
            (root / "config.json").write_text("[1, 2]")
            self.assertEqual(hook_config.load()["steering"], "off")

    def test_parse_arn(self):
        self.assertEqual(hook_config.parse_arn(ARN), ("us-west-2", "111122223333", "ac-0123456789abcdef0123456789abcdef"))
        for bad in (None, "", "ac-1", "arn:aws:context:us-west-2:111122223333:context-graph/cg-1",
                    "arn:aws:s3:::bucket", "arn:aws:context::111122223333:agent-context/ac-1"):
            self.assertIsNone(hook_config.parse_arn(bad), bad)

    def test_endpoint_from_arn_or_override(self):
        self.assertEqual(hook_config.endpoint({"graphArn": ARN}), "https://context.us-west-2.api.aws")
        self.assertEqual(hook_config.endpoint({"graphArn": ARN, "endpoint": "https://x.example/"}), "https://x.example")
        self.assertIsNone(hook_config.endpoint({}))


class CredentialTests(unittest.TestCase):
    def files(self, root, config, stored):
        (root / "config").write_text(config)
        (root / "credentials").write_text(stored)
        return mock.patch.dict("os.environ", {"AWS_CONFIG_FILE": str(root / "config"),
                                              "AWS_SHARED_CREDENTIALS_FILE": str(root / "credentials")})

    def test_stored_keys_are_read_without_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp, self.files(Path(tmp), "[profile p]\nregion = us-west-2\n",
                                                               "[p]\naws_access_key_id = A\naws_secret_access_key = B\naws_session_token = C\n"), \
                mock.patch.object(hook_config.subprocess, "run") as run:
            self.assertEqual(hook_config.credentials("p", 1), {"AccessKeyId": "A", "SecretAccessKey": "B", "SessionToken": "C"})
            run.assert_not_called()

    def test_role_in_the_credentials_file_goes_to_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp, self.files(Path(tmp), "",
                                                               "[p]\naws_access_key_id = A\naws_secret_access_key = B\nrole_arn = arn:aws:iam::111122223333:role/r\nsource_profile = base\n"), \
                mock.patch.object(hook_config.shutil, "which", return_value="/usr/bin/aws"), \
                mock.patch.object(hook_config.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"AccessKeyId": "X", "SecretAccessKey": "Y"}))
            self.assertEqual(hook_config.credentials("p", 1)["AccessKeyId"], "X")

    def test_role_and_sso_profiles_go_to_the_cli(self):
        for extra in ("role_arn = arn:aws:iam::111122223333:role/r\nsource_profile = base\n", "sso_session = s\n",
                      "credential_process = /bin/creds\n"):
            with tempfile.TemporaryDirectory() as tmp, self.files(Path(tmp), "[profile p]\n" + extra,
                                                                   "[p]\naws_access_key_id = A\naws_secret_access_key = B\n"), \
                    mock.patch.object(hook_config.shutil, "which", return_value="/usr/bin/aws"), \
                    mock.patch.object(hook_config.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"AccessKeyId": "X", "SecretAccessKey": "Y"}))
                self.assertEqual(hook_config.credentials("p", 1)["AccessKeyId"], "X")
                self.assertIn("export-credentials", run.call_args[0][0])


class SigningTests(unittest.TestCase):
    def test_signature_is_deterministic_and_covers_the_body(self):
        now = datetime.datetime(2026, 11, 19, 12, 0, 0, tzinfo=datetime.timezone.utc)
        url = "https://context.us-west-2.api.aws/api/v1/traces"
        a = hook_config.sign("POST", url, b'{"a":1}', CREDS, "us-west-2", now)
        b = hook_config.sign("POST", url, b'{"a":1}', CREDS, "us-west-2", now)
        c = hook_config.sign("POST", url, b'{"a":2}', CREDS, "us-west-2", now)
        self.assertEqual(a["authorization"], b["authorization"])
        self.assertNotEqual(a["authorization"], c["authorization"])
        self.assertIn("Credential=AKIDEXAMPLE/20261119/us-west-2/context/aws4_request", a["authorization"])
        self.assertIn("SignedHeaders=content-type;host;x-amz-date", a["authorization"])
        self.assertEqual(a["x-amz-date"], "20261119T120000Z")

    def test_session_token_is_signed(self):
        headers = hook_config.sign("POST", "https://h.example/p", b"{}", dict(CREDS, SessionToken="tok"), "us-east-1")
        self.assertEqual(headers["x-amz-security-token"], "tok")
        self.assertIn("x-amz-security-token", headers["authorization"])

    def test_call_returns_by_its_deadline_and_never_raises(self):
        import http.client, threading, time
        release = threading.Event()
        def slow(*a, **k):
            release.wait(5)
            raise http.client.IncompleteRead(b"")
        with mock.patch("urllib.request.urlopen", side_effect=slow):
            started = time.monotonic()
            result = hook_config.call({"graphArn": ARN}, "/x", {}, 0.5, CREDS)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(result.timed_out)
            release.set()
        with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"")):
            self.assertFalse(hook_config.call({"graphArn": ARN}, "/x", {}, 1, CREDS).answered)
        self.assertFalse(hook_config.call({"graphArn": ARN, "endpoint": "not-a-url"}, "/x", {}, 1, CREDS).answered)

    def test_path_takes_the_graph_id_and_requests_carry_the_user_agent(self):
        seen = {}

        def fake(request, timeout):
            seen["url"], seen["agent"] = request.full_url, request.get_header("User-agent")
            raise http.client.IncompleteRead(b"")
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            hook_config.call({"graphArn": ARN}, hook_config.SEARCH_PATH, {}, 2, CREDS,
                             agent=hook_config.user_agent("steering", "abc-123"))
        self.assertTrue(seen["url"].endswith("/api/v1/agent-contexts/ac-0123456789abcdef0123456789abcdef/search"))
        self.assertEqual(seen["agent"], "aws-context-plugin/0.1.0 (claude-code; hook/steering; session/abc-123)")
        self.assertEqual(hook_config.user_agent("steering", "bad id;"), "aws-context-plugin/0.1.0 (claude-code; hook/steering)")
        self.assertEqual(hook_config.user_agent("steering", "abc\n"), "aws-context-plugin/0.1.0 (claude-code; hook/steering)")
        self.assertFalse(session_feedback.SESSION_ID_PATTERN.match("abc\n"))

    def test_a_coral_error_envelope_in_a_200_is_an_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"Output":{"__type":"com.amazon.coral.service#UnknownOperationException"},"Version":"1.0"}'
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = hook_config.call({"graphArn": ARN}, "/x", {}, 2, CREDS)
        self.assertFalse(result.ok)
        self.assertEqual((result.status, result.error_type), (404, "UnknownOperationException"))
        self.assertFalse(result.rejected)  # kept and resent, never dropped as invalid
        for coral_type, status in (("com.amazon.coral.availability#ThrottlingException", 502),
                                   ("com.amazon.coral.service#InternalFailure", 502),
                                   ("com.amazon.coral.service#ExpiredTokenException", 403),
                                   ("com.amazon.coral.validate#ValidationException", 400)):
            response.read.return_value = json.dumps({"Output": {"__type": coral_type}}).encode()
            with mock.patch("urllib.request.urlopen", return_value=response):
                self.assertEqual(hook_config.call({"graphArn": ARN}, "/x", {}, 2, CREDS).status, status, coral_type)

    def test_environment_overrides_the_endpoint(self):
        with mock.patch.dict("os.environ", {"AWS_CONTEXT_ENDPOINT": "https://test.example"}):
            self.assertEqual(hook_config.endpoint({"graphArn": ARN, "endpoint": "https://other.example"}), "https://test.example")

    def test_call_without_credentials_or_arn_does_not_send(self):
        with mock.patch.object(hook_config, "credentials", return_value=None), \
                mock.patch("urllib.request.urlopen") as urlopen:
            self.assertFalse(hook_config.call({"graphArn": ARN, "profile": "p"}, "/x", {}, 1).ok)
            self.assertFalse(hook_config.call({}, "/x", {}, 1, CREDS).ok)
            urlopen.assert_not_called()


SID = "0b6f1c2e-5d4a-4c3b-9a8e-7f6d5c4b3a21"
USER = '{"type":"user","uuid":"u1","message":{"role":"user","content":"which table has solar?"}}'
OK = hook_config.Result(200, body={"sessionId": "x"})
CFG = {"graphArn": ARN, "readers": READERS}


def user(uuid, text="q"):
    return json.dumps({"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}})


def log(*lines):
    return "\n".join([CALL.strip()] + list(lines)) + "\n"


def sent_uuids(call):
    """The uuid of every document sent, in order, across the mock's calls."""
    out = []
    for c in call.call_args_list:
        for doc in c[0][2]["traceDocuments"]:
            out.append(json.loads(base64.b64decode(doc)).get("uuid", "call"))
    return out


def on(root):
    write_config(root, feedback="on", graphArn=ARN, readers=READERS, profile="p")


def status(root):
    return json.loads((root / "feedback-status.json").read_text())


class FeedbackRequestTests(unittest.TestCase):
    def test_each_log_line_is_its_own_document_under_the_session(self):
        records = session_feedback.log_records(USER + "\n\n" + CALL + '{"partial":\n')
        docs, end = session_feedback.next_batch(records, 0)
        req = session_feedback.build_request("sid-1", 0, docs, CFG)
        self.assertEqual([json.loads(base64.b64decode(d)) for d in req["traceDocuments"]], [json.loads(USER), json.loads(CALL)])
        self.assertEqual((end, req["sessionId"], req["format"]), (2, "sid-1", "ANTHROPIC"))
        self.assertEqual(req["accessControlConfig"], {"accessControlList": READERS})
        self.assertNotIn("accessControl", req)
        self.assertEqual(req["traceMetadata"], {"source": "claude-code"})

    def test_text_is_sent_as_recorded(self):
        line = '{"type":"user","message":"password=hunter2"}'
        docs, _ = session_feedback.next_batch([line], 0)
        self.assertEqual(base64.b64decode(session_feedback.build_request("s", 0, docs, CFG)["traceDocuments"][0]).decode(), line)

    def test_lines_split_only_on_newline(self):
        odd = json.dumps({"type": "user", "uuid": "u2", "message": {"content": "a b c\x85d"}}, ensure_ascii=False)
        self.assertEqual(len(session_feedback.log_records(odd + "\n" + USER + "\n")), 2)
        call = CALL.strip().replace('"input":{}', '"input":{"q":"x y"}')
        self.assertTrue(session_feedback.used_context(call + "\n"))

    def test_session_id_follows_the_session_and_the_settings(self):
        key = session_feedback.session_key({"session_id": SID})
        self.assertEqual(key, SID)
        sid = session_feedback.service_session_id(key, CFG)
        self.assertTrue(sid.startswith("content-agent-" + SID + "-"))
        self.assertRegex(sid, r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,1023}$")
        narrowed = dict(CFG, readers=[{"access": "ALLOW", "principalType": "USER", "principalId": "me@example.com"}])
        self.assertNotEqual(sid, session_feedback.service_session_id(key, narrowed))
        for bad in (None, "", "-x", "a b"):
            other = session_feedback.session_key({"session_id": bad, "transcript_path": "/t.jsonl"})
            self.assertRegex(session_feedback.service_session_id(other, CFG), r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,1023}$")

    def test_batches_stay_within_the_call_limits(self):
        records = ['{"n":%d}' % i for i in range(250)]
        sizes, start = [], 0
        while start < len(records):
            docs, start = session_feedback.next_batch(records, start)
            sizes.append(len(docs))
        self.assertEqual(sizes, [100, 100, 50])
        with mock.patch.object(session_feedback, "MAX_BATCH_BYTES", 20):
            docs, end = session_feedback.next_batch(['{"a":"%s"}' % ("x" * 30), '{"a":1}'], 0)
            self.assertEqual((docs, end), ([b'{"a":1}'], 2))  # the oversized line is left out

    def test_request_is_identical_on_resend(self):
        docs, _ = session_feedback.next_batch([USER], 0)
        self.assertEqual(session_feedback.build_request("s", 0, docs, CFG), session_feedback.build_request("s", 0, docs, CFG))
        self.assertNotEqual(session_feedback.build_request("s", 0, docs, CFG)["clientToken"],
                            session_feedback.build_request("s", 1, docs, CFG)["clientToken"])

    def test_cap_keeps_newest_records(self):
        records = ['{"a":1}', '{"b":2}', '{"c":3}']
        with mock.patch.object(session_feedback, "MAX_SESSION_BYTES", 14):
            self.assertEqual(session_feedback.first_unsent(records, 0), 1)
            self.assertEqual(session_feedback.first_unsent(records, 2), 2)

    def test_used_context_counts_only_calls(self):
        self.assertTrue(session_feedback.used_context(CALL))
        self.assertFalse(session_feedback.used_context(LISTED))
        self.assertFalse(session_feedback.used_context('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n'))


class FeedbackMainTests(unittest.TestCase):
    def test_off_or_incomplete_settings_send_nothing(self):
        for cfg in ({}, {"feedback": "off", "graphArn": ARN, "readers": READERS},
                    {"feedback": "on", "readers": READERS}, {"feedback": "on", "graphArn": ARN}):
            with Home() as root, mock.patch.object(hook_config, "call") as call:
                write_config(root, **cfg)
                run_feedback({"session_id": SID, "transcript_path": str(transcript(root, CALL))})
                call.assert_not_called()

    def test_sends_and_clears_the_spool(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=OK) as call:
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, log(user("u1"))))})
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args[0][1], hook_config.PUT_TRACE_PATH)
            self.assertEqual(list((root / "spool").glob("*.json")), [])
            self.assertEqual(status(root)["state"], "sent")
            self.assertIn("2 log lines from 1 sessions, latest sessionId content-agent-%s-" % SID, status(root)["detail"])

    def test_the_spool_holds_no_transcript_text(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=None):
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, log(user("u1", "secret-words"))))})
            job, = (root / "spool").glob("*.json")
            self.assertNotIn("secret-words", job.read_text())

    def test_a_resumed_session_sends_only_its_new_lines(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=OK) as call:
            on(root)
            path = transcript(root, log(user("u1")))
            run_feedback({"session_id": SID, "transcript_path": str(path)})
            run_feedback({"session_id": SID, "transcript_path": str(path)})
            self.assertEqual(call.call_count, 1)
            path.write_text(log(user("u1"), user("u2")))
            run_feedback({"session_id": SID, "transcript_path": str(path)})
            self.assertEqual(sent_uuids(call), ["call", "u1", "u2"])

    def test_a_long_session_goes_oldest_first_and_whole(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=OK) as call, \
                mock.patch.object(session_feedback, "MAX_BATCH_DOCS", 3), mock.patch.object(session_feedback, "MAX_SPOOLED", 2):
            on(root)
            lines = [user("u%d" % i) for i in range(10)]
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, log(*lines)))})
            self.assertEqual(sent_uuids(call), ["call"] + ["u%d" % i for i in range(10)])
            self.assertEqual(call.call_count, 4)

    def test_unsent_lines_go_at_a_later_session_end(self):
        down = hook_config.Result(message="offline")
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(session_feedback, "MAX_BATCH_DOCS", 2):
            on(root)
            path = transcript(root, log(user("u1"), user("u2"), user("u3")))
            with mock.patch.object(hook_config, "call", side_effect=[OK, down]):
                run_feedback({"session_id": SID, "transcript_path": str(path)})
            self.assertEqual(status(root)["state"], "unreachable")
            with mock.patch.object(hook_config, "call", return_value=OK) as call:
                second = root / "other.jsonl"
                second.write_text(CALL)
                run_feedback({"session_id": "other", "transcript_path": str(second)})
                docs = [d for c in call.call_args_list for d in c[0][2]["traceDocuments"]]
                self.assertEqual(len(docs), 3)  # u2 and u3 of the first session, then the other session's line
            self.assertEqual(list((root / "spool").glob("*.json")), [])

    def test_a_resend_is_the_identical_request(self):
        down = hook_config.Result(message="offline")
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS):
            on(root)
            path = transcript(root, log(user("u1")))
            with mock.patch.object(hook_config, "call", return_value=down) as first:
                run_feedback({"session_id": SID, "reason": "clear", "transcript_path": str(path)})
            with mock.patch.object(hook_config, "call", return_value=OK) as second:
                run_feedback({"session_id": SID, "reason": "logout", "transcript_path": str(path)})
            self.assertEqual(first.call_args[0][2], second.call_args[0][2])

    def test_session_without_context_is_not_sent(self):
        with Home() as root, mock.patch.object(hook_config, "call") as call:
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, "only Bash\n"))})
            call.assert_not_called()

    def test_trace_analysis_disabled_keeps_the_job_and_records_status(self):
        refused = hook_config.Result(400, "ValidationException", "Trace analysis is disabled for this agent context")
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=refused):
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, CALL))})
            self.assertEqual(len(list((root / "spool").glob("*.json"))), 1)
            self.assertEqual(status(root)["state"], "trace-analysis-disabled")

    def test_a_rejected_batch_is_left_out_and_the_rest_still_goes(self):
        bad = hook_config.Result(400, "ValidationException", "document too large")
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", side_effect=[bad, OK, OK]) as call, \
                mock.patch.object(session_feedback, "MAX_BATCH_DOCS", 1):
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, log(user("u1"), user("u2"))))})
            self.assertEqual(call.call_count, 3)
            self.assertEqual(list((root / "spool").glob("*.json")), [])
            self.assertEqual(status(root)["state"], "rejected")
            self.assertIn("2 log lines sent", status(root)["detail"])

    def test_access_denied_for_one_session_does_not_block_the_others(self):
        denied = hook_config.Result(403, "AccessDeniedException", "the session was started by another identity")
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS):
            on(root)
            (root / "spool").mkdir()
            a = transcript(root, log(user("a1")))
            b = root / "b.jsonl"
            b.write_text(log(user("b1")))
            with mock.patch.object(hook_config, "call", return_value=OK):
                session_feedback.queue_job({"session_id": "A", "transcript_path": str(a)}, {"graphArn": ARN, "readers": READERS})
            with mock.patch.object(hook_config, "call", side_effect=[denied, OK]) as call:
                run_feedback({"session_id": "B", "transcript_path": str(b)})
                self.assertEqual(call.call_count, 2)
            self.assertEqual(status(root)["state"], "access-denied")
            self.assertEqual(len(list((root / "spool").glob("*.json"))), 1)  # the denied session waits; the other went

    def test_no_credentials_records_status(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=None), \
                mock.patch.object(hook_config, "call") as call:
            on(root)
            run_feedback({"session_id": SID, "transcript_path": str(transcript(root, CALL))})
            call.assert_not_called()
            self.assertEqual(status(root)["state"], "no-credentials")

    def test_hook_queues_then_hands_sending_to_a_detached_process(self):
        with Home() as root, mock.patch.object(hook_config, "call") as call, \
                mock.patch.object(session_feedback.subprocess, "Popen") as popen, \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(
                    {"session_id": SID, "transcript_path": str(transcript(root, CALL))}))):
            on(root)
            session_feedback.main()
            call.assert_not_called()
            self.assertEqual(len(list((root / "spool").glob("*.json"))), 1)
            self.assertTrue(popen.call_args[1]["start_new_session"])
            self.assertEqual(popen.call_args[1]["env"][session_feedback.SENDER_ENV], "1")

    def test_detached_sender_sends_what_is_queued(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=OK) as call, \
                mock.patch.dict("os.environ", {session_feedback.SENDER_ENV: "1"}):
            on(root)
            (root / "spool").mkdir()
            session_feedback.queue_job({"session_id": SID, "transcript_path": str(transcript(root, CALL))}, CFG)
            session_feedback.main()
            self.assertEqual(call.call_count, 1)
            self.assertEqual(list((root / "spool").glob("*.json")), [])

    def test_jobs_for_other_settings_or_older_versions_are_dropped_unsent(self):
        other = dict(CFG, graphArn=ARN.replace("ac-0123", "ac-9999"))
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call") as call, \
                mock.patch.dict("os.environ", {session_feedback.SENDER_ENV: "1"}):
            on(root)
            (root / "spool").mkdir()
            session_feedback.queue_job({"session_id": SID, "transcript_path": str(transcript(root, CALL))}, other)
            (root / "spool" / "1-old.json").write_text(json.dumps(
                {"format": "ANTHROPIC", "agentContextArns": [ARN], "accessControlConfig": {"accessControlList": READERS},
                 "traceDocuments": ["e30KZTMw"]}))
            session_feedback.main()
            call.assert_not_called()
            self.assertEqual(list((root / "spool").glob("*.json")), [])

    def test_failures_get_their_own_states(self):
        for result, state in ((hook_config.Result(403, "ExpiredTokenException", "The security token included in the request is expired"),
                               "credentials-rejected"),
                              (hook_config.Result(403, "AccessDeniedException", "not authorized to perform context:PutTrace"), "access-denied"),
                              (hook_config.Result(message="timed out", timed_out=True), "unreachable"),
                              (hook_config.Result(429, "ThrottlingException", "slow down"), "unreachable"),
                              (hook_config.Result(503, "ServiceUnavailableException", "try later"), "unreachable")):
            with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                    mock.patch.object(hook_config, "call", return_value=result):
                on(root)
                run_feedback({"session_id": SID, "transcript_path": str(transcript(root, CALL))})
                self.assertEqual(status(root)["state"], state)
                self.assertEqual(len(list((root / "spool").glob("*.json"))), 1)

    def test_spool_and_session_files_are_private(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", side_effect=[OK, hook_config.Result(message="offline")]), \
                mock.patch.object(session_feedback, "MAX_BATCH_DOCS", 1):
            on(root)
            run_feedback({"session_id": "a/b", "transcript_path": str(transcript(root, log(user("u1"))))})
            job, = (root / "spool").glob("*.json")
            self.assertNotIn("/", job.stem)
            self.assertEqual(job.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "spool").stat().st_mode & 0o777, 0o700)
            state, = (root / "sessions").glob("*.json")
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "sessions").stat().st_mode & 0o777, 0o700)


class SteeringTests(unittest.TestCase):
    def steer(self, prompt):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt}))), redirect_stdout(out):
            context_steering.main()
        return out.getvalue()

    def test_off_by_default(self):
        with Home(), mock.patch.object(hook_config, "call") as call:
            self.assertEqual(self.steer("who owns the billing reconciliation table?"), "")
            call.assert_not_called()

    def test_hint_sends_nothing(self):
        with Home() as root, mock.patch.object(hook_config, "call") as call:
            write_config(root, steering="hint")
            out = json.loads(self.steer("who owns the billing reconciliation table?"))
            self.assertIn("[AWS Context]", out["hookSpecificOutput"]["additionalContext"])
            call.assert_not_called()

    def test_short_prompts_and_slash_commands_are_skipped(self):
        with Home() as root:
            write_config(root, steering="hint")
            self.assertEqual(self.steer("hi"), "")
            self.assertEqual(self.steer("/context-hooks status please"), "")

    def test_search_adds_named_matches(self):
        found = hook_config.Result(200, body={"items": [
            {"nodeId": "glueTable:x", "properties": {"name": {"stringValue": "orders"}, "nodeType": {"stringValue": "AWS::GLUE::TABLE"}}},
            {"nodeId": "doc:1"}]})
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=found) as call:
            write_config(root, steering="search", graphArn=ARN, profile="p")
            text = json.loads(self.steer("which columns does the orders table have?"))["hookSpecificOutput"]["additionalContext"]
            self.assertIn("orders (AWS::GLUE::TABLE)", text)
            self.assertIn("doc:1", text)
            self.assertEqual(call.call_args[0][1], "/api/v1/agent-contexts/{agentContextId}/search")
            body = call.call_args[0][2]
            self.assertNotIn("agentContextId", body)
            self.assertEqual(body["searchType"], "AUTO")
            self.assertIn("hook/steering", call.call_args[1]["agent"])

    def test_search_failure_falls_back_to_hint(self):
        with Home() as root, mock.patch.object(hook_config, "credentials", return_value=CREDS), \
                mock.patch.object(hook_config, "call", return_value=hook_config.Result(500)):
            write_config(root, steering="search", graphArn=ARN, profile="p")
            text = json.loads(self.steer("which columns does the orders table have?"))["hookSpecificOutput"]["additionalContext"]
            self.assertTrue(text.startswith("[AWS Context]"))
            self.assertNotIn("found possibly related", text)


if __name__ == "__main__":
    unittest.main()
