"""Sharing send boundaries, including changes between signing and submission."""

import io
import json
import subprocess
import sys
import urllib.error

import pytest
from conftest import TELEMETRY

sys.path.insert(0, str(TELEMETRY))
from sharing import credentials, policy, worker
import client
import record


APPROVED_TEST_POLICY = {
    "enabled": True, "approved": True,
    "noticeVersion": 3, "noticeText": "Test fixture only.",
    "endpoint": "https://reporting.example.invalid/v1/plugin-telemetry-event",
    "audience": "startup-advisor:test:report:v1",
}
EVENT = {"skillInvoked": {"skill": "GCP_TO_AWS", "eventName": "SKILL_INVOKED"}}


def account_choice():
    pending = record.begin_account(profile_name="selected", notice_version=3)
    return record.complete_account(pending, "123456789012")


@pytest.fixture
def account_policy(monkeypatch):
    monkeypatch.delenv(client.ENDPOINT_ENV, raising=False)
    monkeypatch.setattr(policy, "account_policy", lambda: dict(APPROVED_TEST_POLICY))
    return dict(APPROVED_TEST_POLICY)


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def captured_opener(monkeypatch, operation):
    class Opener:
        def open(self, request, timeout):
            return operation(request, timeout)
    monkeypatch.setattr(client.urllib.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(credentials, "send_report", lambda body, url, timeout: worker._send_report({
        "requestBody": __import__("base64").b64encode(body).decode(), "url": url, "timeout": timeout,
    }))


def test_bundled_policy_is_disabled():
    assert policy.account_policy() is None


@pytest.mark.parametrize("override", [
    {"approved": False}, {"enabled": False}, {"noticeText": ""},
    {"noticeVersion": True}, {"noticeVersion": 0}, {"audience": "wrong"},
    {"endpoint": "http://reporting.example.invalid/v1/plugin-telemetry-event"},
    {"endpoint": "https://user:password@reporting.example.invalid/v1/plugin-telemetry-event"},
    {"endpoint": "https://reporting.example.invalid/v1/plugin-telemetry-event#fragment"},
    {"endpoint": "https://reporting.example.invalid:8443/v1/plugin-telemetry-event"},
])
def test_account_policy_requires_approved_complete_configuration(override):
    assert policy.validate_account_policy({**APPROVED_TEST_POLICY, **override}) is None


def test_approved_policy_keeps_destination_and_audience():
    assert policy.validate_account_policy(APPROVED_TEST_POLICY) == APPROVED_TEST_POLICY


def test_anonymous_never_calls_credential_adapter(home, collector, monkeypatch):
    record.write_anonymous()
    monkeypatch.setattr(credentials, "prepare_report", lambda *a, **k: pytest.fail("credentials read"))
    result = client.send_event_result(EVENT, url=collector.url)
    assert result == {"status": "SENT", "reportingMode": "ANONYMOUS"}
    body = json.loads(collector.received[0]["body"])
    assert set(body) == {"installId", "source", "pluginVersion", "occurredAt", "pluginTelemetryEvent"}


def test_dependency_free_anonymous_send_cannot_import_sdk_or_open_credentials(home):
    source = """
import builtins, io, json, sys
sys.path.insert(0, %r)
original_import = builtins.__import__
def protected_import(name, *args, **kwargs):
    if name == 'auth' or name.startswith(('botocore', 'rfc8785', 'sharing.credentials')):
        raise AssertionError('anonymous imported credentials')
    return original_import(name, *args, **kwargs)
builtins.__import__ = protected_import
import client, record
original_open = builtins.open
original_io_open = io.open
def guard(function):
    def protected_open(path, *args, **kwargs):
        if '/.aws/' in str(path).replace('\\\\', '/'):
            raise AssertionError('anonymous opened credentials')
        return function(path, *args, **kwargs)
    return protected_open
builtins.open = guard(original_open)
io.open = guard(original_io_open)
record.write_anonymous()
class Accepted:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
client.urllib.request.urlopen = lambda *args, **kwargs: Accepted()
print(json.dumps(client.send_event_result({'consentRecorded': {}})))
""" % str(TELEMETRY / "metric_emission")
    result = subprocess.run(
        [sys.executable, "-S", "-c", source], capture_output=True, text=True,
        env={"HOME": str(home), "USERPROFILE": str(home), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "SENT", "reportingMode": "ANONYMOUS"}
    assert not result.stderr


@pytest.mark.parametrize("event", [
    {"awsAccountId": "123456789012"},
    {"migrationActivity": {"attributes": [{"identity": {"accountId": "123456789012"}}]}},
    {"details": {"aws_profile": "private"}},
    {"details": {"AWS_SECRET_ACCESS_KEY": "do-not-send"}},
    {"details": {"x-amz-security-token": "do-not-send"}},
])
def test_private_event_fields_never_enter_anonymous_payload(home, collector, event):
    record.write_anonymous()
    assert client.send_event_result(event, url=collector.url)["reasonCode"] == "PAYLOAD_INVALID"
    assert not collector.received


@pytest.mark.parametrize("choice", ["missing", "pending", "optout", "invalid"])
def test_unready_choices_send_nothing_or_read_credentials(home, collector, monkeypatch, choice):
    if choice == "pending":
        record.begin_account(notice_version=3)
    elif choice == "optout":
        record.write_state(record.OPT_OUT)
    elif choice == "invalid":
        record.state_dir().mkdir()
        record.state_path().write_text('{"consentStatus":"ACCEPTED","installId":"bad"}')
    monkeypatch.setattr(credentials, "prepare_report", lambda *a, **k: pytest.fail("credentials read"))
    assert client.send_event_result(EVENT, url=collector.url)["status"] == "SKIPPED"
    assert not collector.received


def test_old_record_remains_credential_free_anonymous(home, collector):
    record.state_dir().mkdir()
    record.state_path().write_text(json.dumps({
        "consentStatus": "ACCEPTED", "installId": "11111111-2222-3333-4444-555555555555",
    }))
    assert client.send_event_result(EVENT, url=collector.url)["reportingMode"] == "ANONYMOUS"
    assert not {"reportingMode", "expectedAwsAccountId", "awsIdentityProof"} & json.loads(collector.received[0]["body"]).keys()


def test_disabled_account_mode_keeps_choice_and_sends_nothing(home, monkeypatch):
    selected = account_choice()
    monkeypatch.setattr(credentials, "prepare_report", lambda *a, **k: pytest.fail("credentials read"))
    assert client.send_event_result(EVENT)["reasonCode"] == "ACCOUNT_REPORTING_DISABLED"
    assert record.read_state() == selected


def test_account_mode_rejects_endpoint_override_before_credentials(home, account_policy, monkeypatch):
    account_choice()
    monkeypatch.setenv(client.ENDPOINT_ENV, "https://untrusted.example.invalid/v1/plugin-telemetry-event")
    monkeypatch.setattr(credentials, "prepare_report", lambda *a, **k: pytest.fail("credentials read"))
    assert client.send_event_result(EVENT)["reasonCode"] == "ENDPOINT_NOT_ALLOWED"


def test_changed_notice_stops_before_credentials(home, account_policy, monkeypatch):
    account_choice()
    monkeypatch.setattr(policy, "account_policy", lambda: {**APPROVED_TEST_POLICY, "noticeVersion": 4})
    monkeypatch.setattr(credentials, "prepare_report", lambda *a, **k: pytest.fail("credentials read"))
    assert client.send_event_result(EVENT)["reasonCode"] == "NOTICE_RENEWAL_REQUIRED"


def test_account_signing_uses_saved_selection_and_private_body(home, account_policy, monkeypatch):
    selected = account_choice()
    seen = []

    def prepare(payload, state, configured, timeout):
        assert state == selected
        assert payload["expectedAwsAccountId"] == "123456789012"
        assert payload["noticeVersion"] == 3
        assert payload["reportingMode"] == "AWS_ACCOUNT"
        assert "awsProfile" not in payload
        return {"status": "READY", "requestBody": b'{"private-proof":"secret"}'}

    monkeypatch.setattr(credentials, "prepare_report", prepare)
    captured_opener(monkeypatch, lambda request, timeout: seen.append(request) or Response())
    result = client.send_event_result(EVENT)
    assert result == {"status": "SENT", "reportingMode": "AWS_ACCOUNT"}
    assert seen[0].full_url == account_policy["endpoint"]
    assert seen[0].data == b'{"private-proof":"secret"}'
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("change", ["optout", "anonymous", "account"])
def test_choice_changed_during_signing_prevents_submission(home, account_policy, monkeypatch, change):
    account_choice()

    def prepare(*args):
        if change == "optout":
            record.write_state(record.OPT_OUT)
        elif change == "anonymous":
            record.write_anonymous()
        else:
            pending = record.begin_account("other", 3)
            record.complete_account(pending, "999999999999")
        return {"status": "READY", "requestBody": b'{}'}

    monkeypatch.setattr(credentials, "prepare_report", prepare)
    captured_opener(monkeypatch, lambda *args: pytest.fail("submitted stale selection"))
    assert client.send_event_result(EVENT)["reasonCode"] == "CHOICE_CHANGED"


def test_account_policy_changed_during_signing_prevents_submission(home, account_policy, monkeypatch):
    account_choice()

    def prepare(*args):
        monkeypatch.setattr(policy, "account_policy", lambda: None)
        return {"status": "READY", "requestBody": b'{}'}

    monkeypatch.setattr(credentials, "prepare_report", prepare)
    monkeypatch.setattr(credentials, "send_report", lambda *args, **kwargs: pytest.fail("sent with withdrawn policy"))
    assert client.send_event_result(EVENT)["reasonCode"] == "ACCOUNT_POLICY_CHANGED"


def test_expired_credentials_prompt_next_interactive_run_without_fallback(home, account_policy, monkeypatch):
    selected = account_choice()
    monkeypatch.setattr(credentials, "prepare_report", lambda *args: {
        "status": "SIGN_IN_REQUIRED", "reasonCode": "SIGN_IN_REQUIRED",
    })
    result = client.send_event_result(EVENT)
    assert result["status"] == "SIGN_IN_REQUIRED"
    assert record.read_state()["expectedAwsAccountId"] == selected["expectedAwsAccountId"]
    assert record.read_state()["recoveryStatus"] == "SIGN_IN_REQUIRED"
    monkeypatch.setattr(credentials, "prepare_report", lambda *args: pytest.fail("background attempted recovery"))
    assert client.send_event_result(EVENT)["status"] == "SIGN_IN_REQUIRED"


@pytest.mark.parametrize("code,status", [
    ("ACCOUNT_MISMATCH", "SETUP_REQUIRED"),
    ("PUBLICATION_UNCERTAIN", "ERROR"),
    ("VERIFICATION_UNAVAILABLE", "ERROR"),
    ("PROOF_REPLAY", "ERROR"),
    ("INVALID_PROOF", "ERROR"),
    ("UNRECOGNIZED_SENSITIVE_ERROR", "ERROR"),
])
def test_backend_codes_are_bounded_and_not_legacy_retry_statuses(home, account_policy, monkeypatch, code, status):
    selected = account_choice()
    monkeypatch.setattr(credentials, "prepare_report", lambda *args: {"status": "READY", "requestBody": b'{}'})

    def reject(request, timeout):
        http_status = 403 if code in ("ACCOUNT_MISMATCH", "INVALID_PROOF") else 500
        raise urllib.error.HTTPError(request.full_url, http_status, "private message", {}, io.BytesIO(json.dumps({
            "code": code, "message": "private account 123456789012 and token secret",
        }).encode()))

    captured_opener(monkeypatch, reject)
    result, legacy = client._send_event(EVENT)
    assert legacy is None
    assert result["status"] == status
    assert result["reasonCode"] == (code if code in client._BACKEND_ERRORS else "HTTP_REJECTED")
    assert "123456789012" not in json.dumps(result)
    if code == "ACCOUNT_MISMATCH":
        assert record.read_state()["expectedAwsAccountId"] == selected["expectedAwsAccountId"]
        assert record.read_state()["recoveryStatus"] == "SETUP_REQUIRED"


def test_account_redirect_handler_never_forwards_proof():
    assert worker._NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://elsewhere.example.invalid") is None


@pytest.mark.parametrize("failure", [BrokenPipeError(), ConnectionResetError()])
def test_account_wrapped_network_failures_have_unknown_publication(home, account_policy, monkeypatch, failure):
    account_choice()
    monkeypatch.setattr(credentials, "prepare_report", lambda *args: {"status": "READY", "requestBody": b'{}'})

    def broken(request, timeout):
        raise urllib.error.URLError(failure)

    captured_opener(monkeypatch, broken)
    result, legacy = client._send_event(EVENT)
    assert result["reasonCode"] == "PUBLICATION_UNKNOWN"
    assert legacy is None


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, 0, True, "3"])
def test_invalid_deadline_never_starts_send(home, collector, timeout):
    record.write_anonymous()
    assert client.send_event_result(EVENT, url=collector.url, timeout=timeout)["reasonCode"] == "DEADLINE_EXCEEDED"
    assert not collector.received


def test_legacy_caller_with_stale_install_id_cannot_submit(home, collector):
    record.write_anonymous()
    assert client.post_event_status(EVENT, "11111111-2222-3333-4444-555555555555", collector.url) == client.UNREACHABLE
    assert not collector.received
