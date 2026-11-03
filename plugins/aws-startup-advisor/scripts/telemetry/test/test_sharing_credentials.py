"""Private worker protocol and cleanup without real AWS credentials or calls."""

import base64
import http.server
import json
import os
import sys
import time
import threading
from types import SimpleNamespace

import pytest
from conftest import TELEMETRY

sys.path.insert(0, str(TELEMETRY))
from sharing import credentials, policy


def test_missing_runtime_is_bounded_without_starting_process(home, monkeypatch):
    monkeypatch.setattr(credentials, "_command", lambda: None)
    result = credentials.prepare_account()
    assert result["reasonCode"] in {"SDK_UNAVAILABLE", "PYTHON_VERSION_UNSUPPORTED"}
    assert set(result) == {"status", "reasonCode"}


def test_unsupported_account_platform_never_starts_worker(home, monkeypatch):
    monkeypatch.setattr(credentials, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(credentials, "_command", lambda: pytest.fail("started unsupported worker"))
    assert credentials.prepare_account() == {
        "status": "ERROR", "reasonCode": "ACCOUNT_PLATFORM_UNSUPPORTED",
    }


def test_unsupported_account_platform_never_loads_approved_policy(monkeypatch):
    monkeypatch.setattr(policy, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(policy, "POLICY_PATH", SimpleNamespace(
        open=lambda **kwargs: pytest.fail("loaded unsupported account policy"),
    ))
    assert policy.account_policy() is None


@pytest.mark.parametrize("value", [
    {"status": "READY", "awsAccountId": "bad"},
    {"status": "READY", "awsAccountId": "123456789012", "private": "secret"},
])
def test_setup_result_returns_only_valid_account_id(monkeypatch, value):
    monkeypatch.setattr(credentials, "_run", lambda *args: value)
    result = credentials.prepare_account()
    assert "secret" not in json.dumps(result)
    if value["awsAccountId"] == "bad":
        assert result["reasonCode"] == "WORKER_RESULT_INVALID"
    else:
        assert result == {"status": "READY", "awsAccountId": "123456789012"}


@pytest.mark.parametrize("body", [None, "not-base64", base64.b64encode(b'x' * 65537).decode()])
def test_report_worker_body_is_bounded_and_validated(monkeypatch, body):
    monkeypatch.setattr(credentials, "_run", lambda *args: {"status": "READY", "requestBody": body})
    assert credentials.prepare_report({}, {}, {})["reasonCode"] == "WORKER_RESULT_INVALID"


def test_signed_body_stays_on_private_protocol(monkeypatch):
    monkeypatch.setattr(credentials, "_run", lambda *args: {
        "status": "READY", "requestBody": base64.b64encode(b'{"awsIdentityProof":"secret"}').decode(),
    })
    assert credentials.prepare_report({}, {}, {})["requestBody"] == b'{"awsIdentityProof":"secret"}'


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("parent_waits", [True, False])
def test_worker_cleanup_kills_descendants_on_timeout_and_success(home, monkeypatch, parent_waits):
    marker = home / "descendant-survived"
    child = "from pathlib import Path; import time; time.sleep(0.6); Path(%r).write_text('alive')" % str(marker)
    parent = "import subprocess,sys,time,json; subprocess.Popen([sys.executable,'-c',%r]); " % child
    parent += "time.sleep(30)" if parent_waits else "print(json.dumps({'status':'READY','awsAccountId':'123456789012'}))"
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", parent])
    started = time.monotonic()
    result = credentials.prepare_account(timeout=0.15)
    assert time.monotonic() - started < 1
    # A descendant inherits stdout even after its parent exits. That still must
    # hit the same lifetime limit and clean the whole process group.
    assert result["reasonCode"] == "CREDENTIALS_TIMEOUT"
    time.sleep(0.65)
    assert not marker.exists()


def test_worker_cannot_print_arbitrary_provider_details(home, monkeypatch, capsys):
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", "print('secret credentials')"])
    assert credentials.prepare_account()["reasonCode"] == "WORKER_RESULT_INVALID"
    assert capsys.readouterr() == ("", "")


def test_unknown_worker_error_is_normalized(home, monkeypatch):
    code = "import json; print(json.dumps({'status':'ERROR','reasonCode':'secret'}))"
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", code])
    assert credentials.prepare_account() == {"status": "ERROR", "reasonCode": "INTERNAL_ERROR"}


def test_worker_input_reaches_eof_before_provider_resolution(home, monkeypatch):
    code = "import sys,json; json.loads(sys.stdin.read()); print(json.dumps({'status':'READY','awsAccountId':'123456789012'}))"
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", code])
    assert credentials.prepare_account() == {"status": "READY", "awsAccountId": "123456789012"}


def test_oversized_worker_output_is_capped_and_never_printed(home, monkeypatch, capsys):
    code = "import sys; sys.stdout.write('x' * 10000000); sys.stdout.flush()"
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", code])
    assert credentials.prepare_account()["reasonCode"] == "WORKER_RESULT_INVALID"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, 0, True, "3"])
def test_invalid_worker_deadline_is_rejected_without_starting(home, monkeypatch, timeout):
    monkeypatch.setattr(credentials, "_command", lambda: pytest.fail("started worker"))
    assert credentials.prepare_account(timeout=timeout)["reasonCode"] == "CREDENTIALS_TIMEOUT"


@pytest.mark.parametrize("drip", ["headers", "body"])
def test_account_transport_watchdog_bounds_slow_response(home, monkeypatch, drip):
    body = b'{"code":"INVALID_PROOF"}'

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                if drip == "headers":
                    wire = b'HTTP/1.1 403 Forbidden\r\nContent-Length: 24\r\n\r\n' + body
                    for byte in wire:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.015)
                else:
                    self.send_response(403)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.015)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local_url = "http://127.0.0.1:%d/test" % server.server_port
    # Only this synthetic child routes the trusted HTTPS request to a local
    # fixture. The released account transport never permits an HTTP policy.
    source = """
import runpy, urllib.request
runtime = runpy.run_path(%r)
original = urllib.request.build_opener()
class LocalFixture:
    def open(self, request, timeout):
        local = urllib.request.Request(%r, data=request.data, method='POST')
        return original.open(local, timeout=timeout)
urllib.request.build_opener = lambda *args: LocalFixture()
runtime['main']()
""" % (str(credentials.WORKER), local_url)
    monkeypatch.setattr(credentials, "_command", lambda: [sys.executable, "-c", source])
    try:
        started = time.monotonic()
        result = credentials.send_report(b'{}', "https://example.invalid/v1/plugin-telemetry-event", timeout=0.15)
        assert time.monotonic() - started < 0.4
        assert result == {"status": "ERROR", "reasonCode": "PUBLICATION_UNKNOWN"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_real_worker_signs_synthetic_credentials_without_sts_or_model_output(home, monkeypatch, capsys):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret-never-a-real-key")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "synthetic-session-token")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(home / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / "no-credentials"))
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    payload = {
        "installId": "11111111-2222-3333-4444-555555555555", "source": "OTHER",
        "pluginVersion": "2.0.4", "occurredAt": 1700000000000,
        "pluginTelemetryEvent": {"consentRecorded": {}}, "reportingMode": "AWS_ACCOUNT",
        "expectedAwsAccountId": "123456789012", "noticeVersion": 3,
    }
    result = credentials.prepare_report(
        payload, {"expectedAwsAccountId": "123456789012"},
        {"audience": "startup-advisor:test:report:v1"}, timeout=3,
    )
    if result.get("reasonCode") in ("SDK_UNAVAILABLE", "PYTHON_VERSION_UNSUPPORTED"):
        pytest.skip("locked SDK not installed")
    assert result["status"] == "READY"
    wire = json.loads(result["requestBody"])
    assert wire["expectedAwsAccountId"] == "123456789012"
    assert wire["awsIdentityProof"]["headers"]["x-amz-security-token"] == "synthetic-session-token"
    assert "synthetic-secret-never-a-real-key" not in result["requestBody"].decode()
    assert capsys.readouterr() == ("", "")
