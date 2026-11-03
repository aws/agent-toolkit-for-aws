"""Run T01 with a total deadline and private, bounded protocol results.

No SDK is imported in this parent process. Anonymous reporting never calls this
module. Install the locked SDK environment explicitly before account setup;
background calls never download dependencies or start an interactive login.
"""

import base64
import importlib.util
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).with_name("worker.py")
MAX_RESULT_BYTES = 131072
_ACCOUNT = re.compile(r"[0-9]{12}\Z")
_ERRORS = {
    "ACCOUNT_CHANGED": "SETUP_REQUIRED",
    "ACCOUNT_REPORTING_REQUIRED": "SETUP_REQUIRED",
    "ACCOUNT_SELECTION_REQUIRED": "SETUP_REQUIRED",
    "INVALID_ACCOUNT": "SETUP_REQUIRED",
    "INVALID_PROFILE": "SETUP_REQUIRED",
    "NOTICE_VERSION_REQUIRED": "SETUP_REQUIRED",
    "CREDENTIALS_UNAVAILABLE": "SIGN_IN_REQUIRED",
    "SIGN_IN_REQUIRED": "SIGN_IN_REQUIRED",
    "AMBIGUOUS_PROFILE": "ERROR",
    "IDENTITY_RESPONSE_INVALID": "ERROR",
    "IDENTITY_UNAVAILABLE": "ERROR",
    "INTERNAL_ERROR": "ERROR",
    "INVALID_AUDIENCE": "ERROR",
    "PAYLOAD_ALREADY_SIGNED": "ERROR",
    "PAYLOAD_INVALID": "ERROR",
    "PAYLOAD_TOO_LARGE": "ERROR",
    "PROOF_INVALID": "ERROR",
    "PROOF_UNAVAILABLE": "ERROR",
    "PYTHON_VERSION_UNSUPPORTED": "ERROR",
    "SDK_UNAVAILABLE": "ERROR",
    "UNSUPPORTED_PARTITION": "ERROR",
    "CREDENTIALS_TIMEOUT": "ERROR",
    "WORKER_UNAVAILABLE": "ERROR",
    "WORKER_RESULT_INVALID": "ERROR",
    "ACCOUNT_PLATFORM_UNSUPPORTED": "ERROR",
}
_SEND_ERRORS = frozenset({
    "INVALID_PROOF", "ACCOUNT_MISMATCH", "REPORTING_NOT_ALLOWED",
    "VERIFICATION_UNAVAILABLE", "PROOF_REPLAY", "INVALID_REQUEST",
    "PUBLICATION_UNCERTAIN", "HTTP_REJECTED", "PUBLICATION_UNKNOWN", "PAYLOAD_INVALID",
})


def _error(code):
    code = code if code in _ERRORS else "INTERNAL_ERROR"
    return {"status": _ERRORS[code], "reasonCode": code}


def _command():
    # Explicitly synced, locked project environment takes precedence. There is
    # no network bootstrap in a hook and no search through AWS profiles here.
    virtual_python = TELEMETRY / "auth/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if virtual_python.is_file():
        return [str(virtual_python), str(WORKER)]
    if sys.version_info < (3, 10):
        return None
    if all(importlib.util.find_spec(name) is not None for name in ("botocore", "rfc8785")):
        return [sys.executable, str(WORKER)]
    return None


def _stop_tree(process):
    """Clean descendants even after the worker exits or leaves a pipe open."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            # Some platforms report EPERM for an already reaped process group.
            # The leader still gets an individual kill if it is running.
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
    else:
        try:
            subprocess.run(  # nosec B603 B607 - Windows OS utility, fixed argv
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=0.2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


def _communicate_bounded(process, data, timeout):
    """Drain only the protocol limit. An untrusted provider cannot flood RAM."""
    output = bytearray()
    overflow = threading.Event()
    deadline = time.monotonic() + timeout

    def write_input():
        try:
            process.stdin.write(data)
            process.stdin.close()
        except OSError:
            pass

    def read_output():
        try:
            while True:
                chunk = process.stdout.read1(min(4096, MAX_RESULT_BYTES + 1 - len(output)))
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > MAX_RESULT_BYTES:
                    overflow.set()
                    _stop_tree(process)
                    return
        except OSError:
            pass

    writer = threading.Thread(target=write_input, daemon=True)
    reader = threading.Thread(target=read_output, daemon=True)
    writer.start()
    reader.start()
    process.wait(timeout=max(0, deadline - time.monotonic()))
    reader.join(timeout=max(0, deadline - time.monotonic()))
    writer.join(timeout=max(0, deadline - time.monotonic()))
    if reader.is_alive() or writer.is_alive():
        raise subprocess.TimeoutExpired(process.args, timeout)
    return bytes(output), overflow.is_set()


def _run(request, timeout):
    process = None
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            return _error("CREDENTIALS_TIMEOUT")
        if os.name != "posix":
            return _error("ACCOUNT_PLATFORM_UNSUPPORTED")
        deadline = time.monotonic() + timeout
        command = _command()
        if command is None:
            return _error("PYTHON_VERSION_UNSUPPORTED" if sys.version_info < (3, 10) else "SDK_UNAVAILABLE")
        data = json.dumps(request, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(data) > 131072:
            return _error("PAYLOAD_TOO_LARGE")
        if time.monotonic() >= deadline:
            return _error("CREDENTIALS_TIMEOUT")
        options = {"start_new_session": True} if os.name == "posix" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
        process = subprocess.Popen(  # nosec B603 - trusted bundled worker, no shell
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, **options,
        )
        try:
            raw, oversized = _communicate_bounded(process, data, timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _stop_tree(process)
            try:
                process.wait(timeout=0)
            except subprocess.TimeoutExpired:
                # Reaping must not add another wait beyond the hook deadline.
                threading.Thread(target=process.wait, daemon=True).start()
            return _error("CREDENTIALS_TIMEOUT")
        if process.returncode != 0 or oversized:
            return _error("WORKER_RESULT_INVALID")
        value = json.loads(raw)
        if not isinstance(value, dict):
            return _error("WORKER_RESULT_INVALID")
        if request.get("operation") == "send":
            if value.get("status") == "SENT" and type(value.get("httpStatus")) is int and 200 <= value["httpStatus"] < 300:
                return {"status": "SENT", "httpStatus": value["httpStatus"]}
            code = value.get("reasonCode")
            if code not in _SEND_ERRORS:
                return _error("WORKER_RESULT_INVALID")
            return {"status": "SETUP_REQUIRED" if code == "ACCOUNT_MISMATCH" and value.get("status") == "SETUP_REQUIRED" else "ERROR", "reasonCode": code}
        if value.get("status") != "READY":
            return _error(value.get("reasonCode"))
        return value
    except (ValueError, TypeError):
        return _error("WORKER_RESULT_INVALID")
    except Exception:
        return _error("WORKER_UNAVAILABLE")
    finally:
        if process is not None:
            _stop_tree(process)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def prepare_account(profile_name=None, timeout=3.0):
    """Private setup result for the local page. Do not print its account ID."""
    result = _run({"operation": "setup", "profile": profile_name}, timeout)
    if result.get("status") != "READY":
        return result
    account = result.get("awsAccountId")
    if not isinstance(account, str) or not _ACCOUNT.fullmatch(account):
        return _error("WORKER_RESULT_INVALID")
    return {"status": "READY", "awsAccountId": account}


def prepare_report(payload, state, policy, timeout=3.0):
    """Private signed body for immediate transport, never model-visible output."""
    result = _run({
        "operation": "prepare", "profile": state.get("awsProfile"),
        "account": state.get("expectedAwsAccountId"),
        "audience": policy.get("audience"), "payload": payload,
    }, timeout)
    if result.get("status") != "READY":
        return result
    try:
        body = base64.b64decode(result.get("requestBody"), validate=True)
        if not body or len(body) > 65536:
            return _error("WORKER_RESULT_INVALID")
        return {"status": "READY", "requestBody": body}
    except (ValueError, TypeError):
        return _error("WORKER_RESULT_INVALID")


def send_report(body, url, timeout=3.0):
    """Private account HTTP transport, including response reads, under one deadline."""
    result = _run({
        "operation": "send", "url": url, "timeout": timeout,
        "requestBody": base64.b64encode(body).decode("ascii"),
    }, timeout)
    if result.get("status") == "SENT":
        return result
    if result.get("reasonCode") not in _SEND_ERRORS:
        # Failure after starting a worker has an uncertain publication outcome.
        return {"status": "ERROR", "reasonCode": "PUBLICATION_UNKNOWN"}
    return result
