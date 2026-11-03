#!/usr/bin/env python3
"""POST a PluginTelemetryEvent to the Startups Advisor IDE Extension API.

    POST /v1/plugin-telemetry-event
    {
      "installId": "<uuid>",          # @required, UUID shape
      "source": "CLAUDE_CODE",        # @required, PluginSource enum
      "pluginVersion": "2.0.2",       # @required, ExtensionVersion shape
      "occurredAt": 1759276800000,    # @required, epoch milliseconds
      "pluginTelemetryEvent": {...}   # the PluginTelemetryEvent union
    }

Anonymous reporting uses the existing public ingress and needs no AWS SDK.
Account reporting uses the separately installed T01 runtime and an approved
endpoint, audience and notice configured in sharing/policy.json. It is disabled
in the shipped configuration until those integration requirements are met.

Every hook and CLI send validates the current sharing choice here. Account
proofs stay on private worker pipes and account transport has a total deadline.
Public results contain only reporting mode, status and a bounded reason.
Failures never raise into migration work or downgrade account sharing to
anonymous. Legacy anonymous HTTP status handling remains available to the
migration snapshot's retry policy; unknown account outcomes are never retried.
"""

import json
import math
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY), str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

import record  # noqa: E402  (paths set above so this resolves in-plugin)

def _plugin_root():
    """Recognize canonical/plugin-bundled layouts; never treat references/ as a plugin."""
    if _TELEMETRY.parent.name == "scripts":
        return _TELEMETRY.parent.parent
    if (len(_TELEMETRY.parents) > 4
            and _TELEMETRY.parent.name == "vendored"
            and _TELEMETRY.parents[1].name == "references"
            and _TELEMETRY.parents[3].name == "skills"):
        return _TELEMETRY.parents[4]
    return None


PLUGIN_ROOT = _plugin_root()

# Prod is the only stage a customer should reach; beta and gamma are the service
# team's, which is what the override is for. It chooses where an event goes, never
# whether one is sent.
DEFAULT_ENDPOINT = (
    "https://us-east-1.prod.startup-advisor-extension.saws.activate.aws.dev"
    "/v1/plugin-telemetry-event"
)
ENDPOINT_ENV = "AWS_STARTUP_ADVISOR_PLUGIN_TELEMETRY_ENDPOINT"

# Short, because these run inline in an agent turn with a human waiting.
TIMEOUT_SECONDS = 3.0

# post_event_status's answer when no connection could be made at all (offline,
# DNS, refused): unlike a timeout, nothing can have reached the service.
UNREACHABLE = 0

USER_AGENT = "aws-startup-advisor-plugin"

SOURCE_CLAUDE_CODE = "CLAUDE_CODE"
SOURCE_CODEX = "CODEX"
SOURCE_CURSOR = "CURSOR"
SOURCE_KIRO = "KIRO"
SOURCE_OTHER = "OTHER"

# First marker present wins. Claude Code and Cursor Agent CLI markers have been
# verified against running hosts; an unmatched host reports OTHER rather than a plausible guess,
# because a wrong attribution silently moves one host's numbers into another's.
# TODO(StartupEngBlend-3621): confirm the other three.
# Cursor's hook-specific markers precede Claude compatibility variables.
# CURSOR_AGENT can be inherited by a nested CLI, so explicit Codex/Kiro markers
# precede that weaker marker.
_HOST_MARKERS = (
    ("CURSOR_VERSION", SOURCE_CURSOR),  # verified in Cursor's hook environment
    ("CURSOR_PROJECT_DIR", SOURCE_CURSOR),  # verified in Cursor's hook environment
    ("CURSOR_TRACE_ID", SOURCE_CURSOR),  # unverified
    ("CODEX_SANDBOX", SOURCE_CODEX),  # unverified
    ("KIRO_IDE", SOURCE_KIRO),  # unverified
    ("CURSOR_AGENT", SOURCE_CURSOR),  # verified in Cursor Agent CLI
    ("CLAUDECODE", SOURCE_CLAUDE_CODE),  # verified
    ("CLAUDE_CODE_ENTRYPOINT", SOURCE_CLAUDE_CODE),  # verified
)

# The PluginSkillId enum, mirrored from model/types/plugin-telemetry.smithy. An
# unmodelled member is a 400 for the whole request, so it is checked here, last,
# before anything goes on the wire.
PLUGIN_SKILL_IDS = frozenset(
    {
        "ARCHITECT_FOR_STARTUPS",
        "KNOWLEDGE_BASE_FOR_STARTUPS",
        "PROMPT_LIBRARY_FOR_STARTUPS",
        "START_BUILDING_FOR_STARTUPS",
        "AZURE_TO_AWS",
        "GCP_TO_AWS",
        "HEROKU_TO_AWS",
        "LLM_TO_BEDROCK",
        "AGENT_ADVISOR",
        "TF_BEST_PRACTICES",
        "CONTEXTUAL_OFFERS_FOR_STARTUPS",
        "OPERATE_ON_AWS",
    }
)

EVENT_SKILL_INVOKED = "SKILL_INVOKED"

# A bundle reports its own generated version. Only recognized plugin layouts
# may fall back to plugin manifests; unrelated references/plugin.json is ignored.
MANIFEST_PATHS = (_TELEMETRY / "version.json",)
if PLUGIN_ROOT is not None:
    MANIFEST_PATHS += (
        PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
        PLUGIN_ROOT / ".cursor-plugin" / "plugin.json",
        PLUGIN_ROOT / "plugin.json",
    )


def endpoint():
    """The URL to POST to, honoring the override."""
    return os.environ.get(ENDPOINT_ENV, "").strip() or DEFAULT_ENDPOINT


def detect_source():
    """Best-effort PluginSource for the host, or OTHER."""
    for name, source in _HOST_MARKERS:
        if os.environ.get(name, "").strip():
            return source
    return SOURCE_OTHER


def migration_reporting_mode():
    """Use configured plugin hooks when reachable, otherwise the bundled CLI.

    This checks the install layout, not whether a host enabled or ran its hooks.
    """
    source = detect_source()
    manifest_name = {
        SOURCE_CLAUDE_CODE: ".claude-plugin/plugin.json",
        SOURCE_CURSOR: ".cursor-plugin/plugin.json",
    }.get(source)
    if not manifest_name or PLUGIN_ROOT is None:
        return "cli"
    try:
        manifest = json.loads((PLUGIN_ROOT / manifest_name).read_text(encoding="utf-8"))
        if manifest.get("name") != "aws-startup-advisor":
            return "cli"
        hook_file = (PLUGIN_ROOT / manifest["hooks"]).resolve()
        hook_file.relative_to(PLUGIN_ROOT.resolve())
        hooks = json.loads(hook_file.read_text(encoding="utf-8"))["hooks"]
        script = "scripts/telemetry/metric_emission/migration.py"
        if not (PLUGIN_ROOT / script).is_file():
            return "cli"
        events = ("PostToolUse", "Stop") if source == SOURCE_CLAUDE_CODE else (
            "afterFileEdit", "afterShellExecution", "stop",
        )
        for event in events:
            for entry in hooks.get(event, []):
                commands = entry.get("hooks", []) if source == SOURCE_CLAUDE_CODE else [entry]
                if any(script in command.get("command", "") for command in commands):
                    return "hook"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return "cli"


def plugin_version():
    """The plugin's version, or None.

    None is a refusal to send, not a default: a made-up "0.0.0" would pass the
    semver pattern and misattribute the event to a version that does not exist.
    """
    for manifest in MANIFEST_PATHS:
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                version = json.load(handle).get("version")
        except (OSError, ValueError):
            continue
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


def build_payload(event, install_id, now_ms=None):
    """The request body, or None if a required field is missing."""
    version = plugin_version()
    if not install_id or not version:
        return None

    return {
        "installId": install_id,
        "source": detect_source(),
        "pluginVersion": version,
        # The service drops timestamps more than five minutes ahead, silently and
        # with a 200, so a fast clock loses its telemetry with no signal here.
        "occurredAt": int((now_ms if now_ms is not None else time.time() * 1000)),
        "pluginTelemetryEvent": event,
    }


_PRIVATE_EVENT_FIELDS = frozenset({
    "identity", "awsidentityproof", "expectedawsaccountid", "awsaccountid",
    "accountid", "awsprofile", "profile", "credentials", "accesskeyid", "accesskey",
    "awsaccesskeyid", "secretaccesskey", "secretkey", "awssecretaccesskey",
    "sessiontoken", "awssessiontoken", "token", "authorization", "xamzsecuritytoken",
})
_BACKEND_ERRORS = frozenset({
    "INVALID_PROOF", "ACCOUNT_MISMATCH", "REPORTING_NOT_ALLOWED",
    "VERIFICATION_UNAVAILABLE", "PROOF_REPLAY", "INVALID_REQUEST",
    "PUBLICATION_UNCERTAIN",
})


def _event_has_private_fields(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in _PRIVATE_EVENT_FIELDS or _event_has_private_fields(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_event_has_private_fields(child) for child in value)
    return False


def _result(status, reason=None, mode=None):
    result = {"status": status}
    if reason:
        result["reasonCode"] = reason
    if mode:
        result["reportingMode"] = mode
    return result


def _send_event(event, url=None, timeout=TIMEOUT_SECONDS, selected_install_id=None):
    """The sole send path, with private transport status kept out of CLI results."""
    mode = None
    selected = None
    attempted = False
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            return _result("SKIPPED", "DEADLINE_EXCEEDED"), UNREACHABLE
        deadline = time.monotonic() + max(0, timeout)
        selected = record.read_state()
        if not selected:
            return _result("SKIPPED", "CHOICE_REQUIRED"), UNREACHABLE
        mode = record.sharing_mode(selected)
        if selected.get("consentStatus") != record.ACCEPTED:
            reason = "OPT_OUT" if selected.get("consentStatus") == record.OPT_OUT else "SETUP_PENDING"
            return _result("SKIPPED", reason, mode), UNREACHABLE
        if selected.get("recoveryStatus"):
            return _result(selected["recoveryStatus"], selected["recoveryReason"], mode), UNREACHABLE
        if selected_install_id is not None and selected.get("installId") != selected_install_id:
            return _result("SKIPPED", "CHOICE_CHANGED", mode), UNREACHABLE
        if _event_has_private_fields(event):
            return _result("ERROR", "PAYLOAD_INVALID", mode), None
        payload = build_payload(event, selected["installId"])
        if payload is None:
            return _result("ERROR", "PLUGIN_VERSION_UNAVAILABLE", mode), None
        if mode == "AWS_ACCOUNT":
            from sharing import credentials, policy

            configured = policy.account_policy()
            if configured is None:
                return _result("SKIPPED", "ACCOUNT_REPORTING_DISABLED", mode), UNREACHABLE
            if selected.get("noticeVersion") != configured["noticeVersion"]:
                return _result("SETUP_REQUIRED", "NOTICE_RENEWAL_REQUIRED", mode), UNREACHABLE
            # Existing hook callers supply the old default URL. The approved
            # account endpoint takes its place. An override never changes the
            # signed proof's destination or audience.
            overridden = os.environ.get(ENDPOINT_ENV, "").strip()
            if ((overridden and overridden != configured["endpoint"])
                    or (url and url not in (DEFAULT_ENDPOINT, configured["endpoint"]))):
                return _result("ERROR", "ENDPOINT_NOT_ALLOWED", mode), UNREACHABLE
            url = configured["endpoint"]
            payload.update({
                "reportingMode": "AWS_ACCOUNT",
                "expectedAwsAccountId": selected["expectedAwsAccountId"],
                "noticeVersion": selected["noticeVersion"],
            })
            prepared = credentials.prepare_report(payload, selected, configured, deadline - time.monotonic())
            if prepared.get("status") != "READY":
                result = _result(prepared["status"], prepared["reasonCode"], mode)
                if prepared["status"] in ("SIGN_IN_REQUIRED", "SETUP_REQUIRED"):
                    record.mark_recovery(selected, prepared["status"], prepared["reasonCode"])
                return result, UNREACHABLE
            body = prepared["requestBody"]
        elif mode == "ANONYMOUS":
            if selected.get("noticeVersion", 1) > record.notice.NOTICE_VERSION:
                return _result("SETUP_REQUIRED", "NOTICE_RENEWAL_REQUIRED", mode), UNREACHABLE
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            url = url or endpoint()
        else:
            return _result("SKIPPED", "CHOICE_REQUIRED"), UNREACHABLE

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _result("SKIPPED", "DEADLINE_EXCEEDED", mode), UNREACHABLE
        # Lock only the final comparison and submission. Signing happens before
        # this lock, so opt-out and switching remain available during providers.
        with record.state_guard(timeout=min(0.25, remaining)):
            if record.read_state() != selected:
                return _result("SKIPPED", "CHOICE_CHANGED", mode), UNREACHABLE
            if mode == "AWS_ACCOUNT" and policy.account_policy() != configured:
                return _result("SKIPPED", "ACCOUNT_POLICY_CHANGED", mode), UNREACHABLE
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _result("SKIPPED", "DEADLINE_EXCEEDED", mode), UNREACHABLE
            attempted = True
            if mode == "AWS_ACCOUNT":
                transport = credentials.send_report(body, url, timeout=remaining)
                if transport.get("status") == "SENT":
                    return _result("SENT", mode=mode), transport["httpStatus"]
                result = _result(transport["status"], transport["reasonCode"], mode)
            else:
                request = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=remaining) as response:
                        status = response.status
                        if 200 <= status < 300:
                            return _result("SENT", mode=mode), status
                        return _result("ERROR", "HTTP_REJECTED", mode), status
                except urllib.error.HTTPError as error:
                    return _result("ERROR", "HTTP_REJECTED", mode), error.code
                except urllib.error.URLError as error:
                    if isinstance(error.reason, (socket.timeout, TimeoutError)):
                        return _result("ERROR", "PUBLICATION_UNKNOWN", mode), None
                    return _result("ERROR", "NETWORK_UNAVAILABLE", mode), UNREACHABLE
        if result["status"] == "SETUP_REQUIRED":
            record.mark_recovery(selected, result["status"], result["reasonCode"])
        # Account backend failures do not flow through the legacy HTTP retry
        # rules. Unknown publication outcomes and rejected proofs are dropped.
        return result, None
    except OSError:
        return _result("ERROR", "PUBLICATION_UNKNOWN" if attempted else "CHOICE_BUSY", mode), None if attempted else UNREACHABLE
    except BaseException:
        return _result("ERROR", "PUBLICATION_UNKNOWN" if attempted else "INTERNAL_ERROR", mode), None


def send_event_result(event, url=None, timeout=TIMEOUT_SECONDS):
    """Shared hook/CLI result containing no account, profile, credential or proof."""
    return _send_event(event, url=url, timeout=timeout)[0]


def post_event_status(event, install_id, url, timeout=TIMEOUT_SECONDS):
    """Legacy migration status adapter around the shared consent-aware sender."""
    if not install_id:
        return None
    return _send_event(event, url, timeout, selected_install_id=install_id)[1]


def post_event(event, install_id, url):
    """POST one event. True only if the service accepted it; never raises."""
    status = post_event_status(event, install_id, url)
    return status is not None and 200 <= status < 300


def send_event(event):
    """POST one event, reading the install ID and endpoint for the caller."""
    return send_event_result(event)["status"] == "SENT"


def emit_skill_invocation_metric(install_id, skill_id, url):
    """Report that `skill_id` was invoked.

    A skill id that is not a PluginSkillId member is dropped here rather than
    sent. The caller maps a host's skill name onto the enum and may legitimately
    have no match, so that is an ordinary outcome, not an error.
    """
    if skill_id not in PLUGIN_SKILL_IDS:
        return False

    return post_event(
        {"skillInvoked": {"skill": skill_id, "eventName": EVENT_SKILL_INVOKED}},
        install_id,
        url,
    )


def send_consent_recorded():
    """Report that consent was recorded. Only ever sent on acknowledgement.

    `ConsentRecordedDetails` is empty and cannot say which way the user answered,
    so a request from `opt_out.py` would be indistinguishable from a yes — besides
    being a request made on behalf of someone who just said no.
    """
    return send_event({"consentRecorded": {}})
