"""Short-lived loopback sharing page; account details never reach agent stdout."""

import hmac
import http.server
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TELEMETRY), str(TELEMETRY / "consent")]

import notice
import record
from sharing import policy

MAX_BODY = 4096


def _open_browser(url, timeout):
    """Browser helpers cannot print the page capability or outlive launch budget."""
    process = None
    try:
        options = {"start_new_session": True} if os.name == "posix" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("browser.py")), url],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **options,
        )
        return process.wait(timeout=max(0, min(3.0, timeout))) == 0
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
        else:
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=.2, check=False)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        try:
            process.wait(timeout=.1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False
    except OSError:
        return False


def status_result():
    """Only the mode and bounded outcome may be exposed to the coding agent."""
    state = record.read_state()
    if state is None:
        return {"status": "SETUP_REQUIRED", "reasonCode": "CHOICE_REQUIRED"}
    mode = record.sharing_mode(state)
    result = {"reportingMode": mode} if mode else {}
    if state["consentStatus"] == record.OPT_OUT:
        return {**result, "status": "SKIPPED", "reasonCode": "OPT_OUT"}
    if state["consentStatus"] == record.PENDING:
        return {**result, "status": "SETUP_REQUIRED", "reasonCode": "SETUP_PENDING"}
    if state.get("recoveryStatus"):
        return {**result, "status": state["recoveryStatus"], "reasonCode": state["recoveryReason"]}
    if mode == record.ANONYMOUS and state.get("noticeVersion", 1) > notice.NOTICE_VERSION:
        return {**result, "status": "SETUP_REQUIRED", "reasonCode": "NOTICE_RENEWAL_REQUIRED"}
    if mode == record.AWS_ACCOUNT:
        configured = policy.account_policy()
        if configured is None:
            return {**result, "status": "SETUP_REQUIRED", "reasonCode": "ACCOUNT_REPORTING_DISABLED"}
        if state.get("noticeVersion") != configured["noticeVersion"]:
            return {**result, "status": "SETUP_REQUIRED", "reasonCode": "NOTICE_RENEWAL_REQUIRED"}
    return {**result, "status": "READY"}


class SharingServer(http.server.ThreadingHTTPServer):
    """One local interaction, with an ephemeral CSRF token and a fixed origin."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, timeout=120.0):
        super().__init__(("127.0.0.1", 0), SharingHandler)
        self.token = secrets.token_urlsafe(32)
        self.origin = "http://127.0.0.1:%d" % self.server_port
        self.deadline = time.monotonic() + timeout
        self.finished = threading.Event()
        self.result = {"status": "SKIPPED", "reasonCode": "CHOICE_CANCELLED"}
        self.choice_lock = threading.Lock()
        self.account_policy = policy.account_policy()
        self.notice_served = False

    def handle_error(self, request, client_address):
        pass  # Raw request/provider errors must not reach agent-visible stderr.

    def view(self):
        configured = self.account_policy
        with self.choice_lock:
            self.notice_served = True
        state = record.read_state() or {}
        return {
            "anonymousNotice": notice.NOTICE_BODY.format(opt_out=record.OPT_OUT_INSTRUCTION),
            "accountAvailable": configured is not None,
            "accountNotice": configured["noticeText"] if configured else None,
            "selectedAccount": state.get("expectedAwsAccountId"),
            "selectedProfile": state.get("awsProfile"),
            **status_result(),
        }

    def choose(self, body):
        # Serialize decisions within this page. An account lookup runs outside
        # this lock so a user can opt out while a provider is still responding.
        mode = body.get("choice")
        with self.choice_lock:
            if self.finished.is_set() or time.monotonic() >= self.deadline:
                return {"status": "SKIPPED", "reasonCode": "CHOICE_EXPIRED"}
            if mode == "OPT_OUT":
                record.write_state(record.OPT_OUT)
                result = {"status": "SKIPPED", "reasonCode": "OPT_OUT"}
            elif mode == "ANONYMOUS":
                if not self.notice_served:
                    return {"status": "ERROR", "reasonCode": "NOTICE_NOT_SHOWN"}
                record.write_anonymous()
                result = {"status": "READY", "reportingMode": "ANONYMOUS"}
            elif mode == "AWS_ACCOUNT":
                configured = self.account_policy
                if configured is None:
                    return {"status": "ERROR", "reasonCode": "ACCOUNT_REPORTING_DISABLED"}
                if not self.notice_served:
                    return {"status": "ERROR", "reasonCode": "NOTICE_NOT_SHOWN"}
                if policy.account_policy() != configured:
                    return {"status": "SETUP_REQUIRED", "reasonCode": "NOTICE_RENEWAL_REQUIRED"}
                pending = record.begin_account(body.get("awsProfile"), configured["noticeVersion"])
                result = None
            else:
                return {"status": "ERROR", "reasonCode": "INVALID_CHOICE"}
            if result is not None:
                self.result = result
                self.finished.set()
                return result

        # This is the only UI path that loads the credential adapter.
        from sharing import credentials
        remaining = min(3.0, self.deadline - time.monotonic())
        if remaining <= 0:
            return {"status": "SKIPPED", "reasonCode": "CHOICE_EXPIRED"}
        prepared = credentials.prepare_account(body.get("awsProfile"), timeout=remaining)
        with self.choice_lock:
            if self.finished.is_set() or time.monotonic() >= self.deadline:
                return {"status": "SKIPPED", "reasonCode": "CHOICE_EXPIRED"}
            if prepared.get("status") != "READY":
                return {key: prepared[key] for key in ("status", "reasonCode") if key in prepared}
            if policy.account_policy() != configured:
                return {"status": "SETUP_REQUIRED", "reasonCode": "NOTICE_RENEWAL_REQUIRED"}
            if not record.complete_account(pending, prepared["awsAccountId"]):
                return {"status": "SETUP_REQUIRED", "reasonCode": "CHOICE_CHANGED"}
            self.result = {"status": "READY", "reportingMode": "AWS_ACCOUNT"}
            self.finished.set()
            # Private local browser response, never returned by open_sharing.
            return {**self.result, "awsAccountId": prepared["awsAccountId"]}


class SharingHandler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(2.0)

    def log_message(self, *args):
        pass

    def reply(self, code, body, content_type="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, private=False, mutation=False):
        if self.headers.get("Host") != self.server.origin[len("http://"):]:
            return False
        if mutation and self.headers.get("Origin") != self.server.origin:
            return False
        if self.headers.get("Origin") not in (None, self.server.origin):
            return False
        if private:
            value = self.headers.get("X-Sharing-Token", "")
            if not hmac.compare_digest(value, self.server.token):
                return False
        return time.monotonic() < self.server.deadline

    def do_GET(self):
        if not self.allowed(private=self.path == "/state"):
            self.reply(403, {"status": "ERROR", "reasonCode": "REQUEST_DENIED"})
            return
        if self.path == "/state":
            self.reply(200, self.server.view())
        elif self.path in ("/", "/page.js"):
            filename = "page.html" if self.path == "/" else "page.js"
            mime = "text/html; charset=utf-8" if self.path == "/" else "text/javascript; charset=utf-8"
            self.reply(200, Path(__file__).with_name(filename).read_bytes(), mime)
        else:
            self.reply(404, {"status": "ERROR", "reasonCode": "NOT_FOUND"})

    def do_POST(self):
        if self.path != "/choice" or not self.allowed(private=True, mutation=True):
            self.reply(403, {"status": "ERROR", "reasonCode": "REQUEST_DENIED"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY or self.headers.get("Content-Type") != "application/json":
                raise ValueError("invalid request")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict) or set(body) - {"choice", "awsProfile"}:
                raise ValueError("invalid choice")
            self.reply(200, self.server.choose(body))
        except (OSError, ValueError, KeyError, TypeError):
            self.reply(400, {"status": "ERROR", "reasonCode": "CHOICE_NOT_SAVED"})
        except Exception:
            self.reply(500, {"status": "ERROR", "reasonCode": "INTERNAL_ERROR"})


def open_sharing(change=False, timeout=120.0, opener=None):
    """Open locally, returning bounded output even if no browser is available."""
    current = status_result()
    if not change and current["status"] in ("READY", "SKIPPED"):
        return current
    server = SharingServer(timeout=timeout)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05), daemon=True)
    thread.start()
    try:
        # A fragment is not sent in HTTP requests or server logs. Never print
        # this URL: the page and its account details belong to the local user.
        try:
            url = server.origin + "/#" + server.token
            opened = opener(url) if opener else _open_browser(url, server.deadline - time.monotonic())
        except Exception:
            opened = False
        if not opened:
            return {"status": "SKIPPED", "reasonCode": "BROWSER_UNAVAILABLE"}
        server.finished.wait(max(0, server.deadline - time.monotonic()))
        return server.result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
