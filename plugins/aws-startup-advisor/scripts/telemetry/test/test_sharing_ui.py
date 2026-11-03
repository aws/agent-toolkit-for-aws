"""Browser decisions exercise the real loopback boundary, using isolated state."""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import record
from sharing import policy, ui


@contextmanager
def page(timeout=5):
    server = ui.SharingServer(timeout)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, path="/state", body=None, token=True, headers=None):
    values = {"X-Sharing-Token": server.token} if token else {}
    if body is not None:
        values.update({"Origin": server.origin, "Content-Type": "application/json"})
    values.update(headers or {})
    req = urllib.request.Request(server.origin + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=values)
    with urllib.request.urlopen(req, timeout=4) as response:
        return response.status, json.loads(response.read()), dict(response.headers)


@pytest.fixture
def account_policy(monkeypatch):
    configured = {"enabled": True, "approved": True, "noticeVersion": 3,
                  "noticeText": "Synthetic approved notice for test only",
                  "endpoint": "https://report.example.test/v1/plugin-telemetry-event",
                  "audience": "startup-advisor:test:report:v1"}
    monkeypatch.setattr(policy, "account_policy", lambda: configured)
    return configured


def test_local_page_denies_missing_token_cross_origin_and_wrong_host(home):
    with page() as server:
        assert server.server_address[0] == "127.0.0.1"
        for options in ({"token": False}, {"headers": {"Origin": "https://evil.test"}},
                        {"headers": {"Host": "evil.test"}}):
            with pytest.raises(urllib.error.HTTPError) as error:
                request(server, **options)
            assert error.value.code == 403
        assert record.read_state() is None
        _, state, headers = request(server)
        assert state["accountAvailable"] is False
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_choices_cannot_be_submitted_without_exact_origin(home):
    with page() as server:
        with pytest.raises(urllib.error.HTTPError) as error:
            request(server, "/choice", {"choice": "ANONYMOUS"}, headers={"Origin": "null"})
        assert error.value.code == 403
        assert record.read_state() is None


@pytest.mark.parametrize("choice", ["ANONYMOUS", "OPT_OUT"])
def test_anonymous_and_opt_out_do_not_load_credentials(home, monkeypatch, choice):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name in ("auth", "boto3", "botocore", "sharing.credentials") or (name == "sharing" and "credentials" in (kwargs.get("fromlist") or (args[2] if len(args) > 2 else ()))):
            raise AssertionError("credential adapter entered")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with page() as server:
        request(server)
        _, result, _ = request(server, "/choice", {"choice": choice})
        assert result["status"] in ("READY", "SKIPPED")
        state = record.read_state()
        assert not {"awsProfile", "expectedAwsAccountId"}.intersection(state)
        assert state["consentStatus"] == ("ACCEPTED" if choice == "ANONYMOUS" else "OPT_OUT")


def test_default_release_does_not_start_account_setup(home):
    with page() as server:
        _, result, _ = request(server, "/choice", {"choice": "AWS_ACCOUNT"})
        assert result["reasonCode"] == "ACCOUNT_REPORTING_DISABLED"
        assert record.read_state() is None


def test_account_setup_shows_account_locally_and_returns_only_mode(home, monkeypatch, account_policy):
    from sharing import credentials
    monkeypatch.setattr(credentials, "prepare_account", lambda *a, **kw: {"status": "READY", "awsAccountId": "123456789012"})
    def opener(url):
        origin, token = url.split("/#")
        with urllib.request.urlopen(urllib.request.Request(origin + "/state", headers={"X-Sharing-Token": token})):
            pass
        req = urllib.request.Request(origin + "/choice", data=json.dumps({"choice": "AWS_ACCOUNT", "awsProfile": "dev"}).encode(),
                                     headers={"X-Sharing-Token": token, "Origin": origin, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            assert json.loads(response.read())["awsAccountId"] == "123456789012"
        return True
    result = ui.open_sharing(change=True, timeout=5, opener=opener)
    assert result == {"status": "READY", "reportingMode": "AWS_ACCOUNT"}
    assert record.read_state()["expectedAwsAccountId"] == "123456789012"


def test_opt_out_wins_over_slow_account_lookup(home, monkeypatch, account_policy):
    from sharing import credentials
    started, release = threading.Event(), threading.Event()
    def prepare(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return {"status": "READY", "awsAccountId": "123456789012"}
    monkeypatch.setattr(credentials, "prepare_account", prepare)
    with page() as server, ThreadPoolExecutor(max_workers=1) as pool:
        request(server)
        future = pool.submit(request, server, "/choice", {"choice": "AWS_ACCOUNT"})
        assert started.wait(2)
        assert request(server, "/choice", {"choice": "OPT_OUT"})[1]["reasonCode"] == "OPT_OUT"
        release.set()
        assert future.result()[1]["reasonCode"] == "CHOICE_EXPIRED"
        assert record.read_state()["consentStatus"] == "OPT_OUT"


def test_failed_setup_stays_pending_and_page_can_choose_anonymous(home, monkeypatch, account_policy):
    from sharing import credentials
    monkeypatch.setattr(credentials, "prepare_account", lambda *a, **kw: {"status": "SIGN_IN_REQUIRED", "reasonCode": "SIGN_IN_REQUIRED"})
    with page() as server:
        request(server)
        result = request(server, "/choice", {"choice": "AWS_ACCOUNT"})[1]
        assert result["status"] == "SIGN_IN_REQUIRED"
        assert record.read_state()["consentStatus"] == "PENDING"
        assert request(server, "/choice", {"choice": "ANONYMOUS"})[1]["status"] == "READY"
        assert record.sharing_mode(record.read_state()) == "ANONYMOUS"


def test_opt_out_is_not_reprompted_and_unavailable_browser_writes_nothing(home):
    calls = []
    result = ui.open_sharing(timeout=.01, opener=lambda url: calls.append(url) or False)
    assert result["reasonCode"] == "BROWSER_UNAVAILABLE"
    assert record.read_state() is None
    record.write_state(record.OPT_OUT)
    assert ui.open_sharing(opener=lambda _: pytest.fail("saved opt-out opened page"))["reasonCode"] == "OPT_OUT"


def test_recovery_and_notice_change_prompt_next_interactive_invocation(home, account_policy):
    pending = record.begin_account(notice_version=3)
    accepted = record.complete_account(pending, "123456789012")
    assert ui.status_result()["status"] == "READY"
    assert record.mark_recovery(accepted, "SETUP_REQUIRED", "ACCOUNT_MISMATCH")
    assert ui.status_result()["reasonCode"] == "ACCOUNT_MISMATCH"
    pending = record.begin_account(notice_version=2)
    record.complete_account(pending, "123456789012")
    assert ui.status_result()["reasonCode"] == "NOTICE_RENEWAL_REQUIRED"


def test_reporting_choice_requires_the_page_notice(home):
    with page() as server:
        assert request(server, "/choice", {"choice": "ANONYMOUS"})[1]["reasonCode"] == "NOTICE_NOT_SHOWN"
        assert record.read_state() is None


def test_notice_policy_change_cannot_accept_unseen_version(home, monkeypatch, account_policy):
    with page() as server:
        request(server)
        monkeypatch.setattr(policy, "account_policy", lambda: {**account_policy, "noticeVersion": 4})
        result = request(server, "/choice", {"choice": "AWS_ACCOUNT"})[1]
        assert result["reasonCode"] == "NOTICE_RENEWAL_REQUIRED"
        assert record.read_state() is None


def test_unknown_anonymous_notice_requires_interactive_setup(home):
    record.write_anonymous(notice_version=999)
    assert ui.status_result()["reasonCode"] == "NOTICE_RENEWAL_REQUIRED"


@pytest.mark.skipif(os.name != "posix", reason="POSIX synthetic browser launcher")
def test_browser_launcher_output_is_private_and_hanging_launcher_is_bounded(home, monkeypatch, capfd):
    launcher = home / "test-browser"
    launcher.write_text("#!%s\nimport sys, time\nprint(sys.argv[1], flush=True)\nprint(sys.argv[1], file=sys.stderr, flush=True)\ntime.sleep(10)\n" % sys.executable)
    launcher.chmod(0o700)
    monkeypatch.setenv("BROWSER", str(launcher) + " %s")
    started = time.monotonic()
    assert not ui._open_browser("http://127.0.0.1:1/#synthetic-private-capability", .1)
    assert time.monotonic() - started < .75
    captured = capfd.readouterr()
    assert "synthetic-private-capability" not in captured.out + captured.err
