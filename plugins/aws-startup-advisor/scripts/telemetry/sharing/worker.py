"""Private credential worker. Its output belongs only to the local adapter."""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TELEMETRY))

BACKEND_ERRORS = frozenset({
    "INVALID_PROOF", "ACCOUNT_MISMATCH", "REPORTING_NOT_ALLOWED",
    "VERIFICATION_UNAVAILABLE", "PROOF_REPLAY", "INVALID_REQUEST",
    "PUBLICATION_UNCERTAIN",
})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send_report(value):
    """Send inside the parent's watchdog; socket timeouts alone are not total."""
    body = base64.b64decode(value.get("requestBody"), validate=True)
    if not body or len(body) > 65536:
        return {"status": "ERROR", "reasonCode": "PAYLOAD_INVALID"}
    request = urllib.request.Request(
        value.get("url"), data=body,
        headers={"Content-Type": "application/json", "User-Agent": "aws-startup-advisor-plugin"},
        method="POST",
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=value.get("timeout")) as response:
            if 200 <= response.status < 300:
                return {"status": "SENT", "httpStatus": response.status}
            return {"status": "ERROR", "reasonCode": "HTTP_REJECTED"}
    except urllib.error.HTTPError as error:
        code = "HTTP_REJECTED"
        try:
            raw = error.read(4097)
            document = json.loads(raw) if len(raw) <= 4096 else None
            proposed = document.get("code") if isinstance(document, dict) else None
            if proposed in BACKEND_ERRORS:
                code = proposed
        except (OSError, ValueError, TypeError):
            pass
        status = "SETUP_REQUIRED" if error.code == 403 and code == "ACCOUNT_MISMATCH" else "ERROR"
        return {"status": status, "reasonCode": code}
    except Exception:
        # A wrapped broken pipe/reset may occur after transmission. No report
        # is retried merely because the transport lacks a response.
        return {"status": "ERROR", "reasonCode": "PUBLICATION_UNKNOWN"}


def main():
    from auth import AccountIdentity, AccountReportingError, AwsAccountReporter

    try:
        # The parent writes one bounded JSON request then closes the pipe. Close
        # stdin before resolving providers so credential_process cannot ask for
        # input through this channel. MFA prompting is also disabled by T01.
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise AccountReportingError("PAYLOAD_TOO_LARGE")
        request = json.loads(raw)
        with open(os.devnull, "rb") as empty:
            os.dup2(empty.fileno(), 0)
        if not isinstance(request, dict):
            raise AccountReportingError("PAYLOAD_INVALID")
        operation = request.get("operation")
        if operation == "send":
            result = _send_report(request)
        elif operation == "setup":
            reporter = AwsAccountReporter(
                "startup-advisor:account-inspection:report:v1", request.get("profile")
            )
            account = reporter.setup()
            result = {"status": "READY", "awsAccountId": account.account_id}
        elif operation == "prepare":
            reporter = AwsAccountReporter(request.get("audience"), request.get("profile"))
            prepared = reporter.prepare_report(
                request.get("payload"), AccountIdentity(request.get("account"))
            )
            result = {
                "status": "READY",
                "requestBody": base64.b64encode(prepared.request_body()).decode("ascii"),
            }
        else:
            raise AccountReportingError("PAYLOAD_INVALID")
    except AccountReportingError as error:
        result = error.as_result()
    except Exception:
        result = {"status": "ERROR", "reasonCode": "INTERNAL_ERROR"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
