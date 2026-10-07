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

The endpoint has no authorizer — the gateway stamps `auth: {type: NONE}` and an
`AnyPrincipal` allow on `execute-api:Invoke` — so this needs no credentials, no
SigV4 and no boto3, and has no third-party imports.

Fire and forget. `post_event` swallows everything and reports failure to nobody: a
telemetry POST is not something the user asked for and must not be able to fail an
operation they did ask for. Every status is treated the same way — a 403 or 400 is
dropped exactly like a timeout, so nothing here depends on which the service sends.

The consent gate is re-checked in `post_event`, so a new call site cannot emit by
forgetting to ask.
"""

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

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


def post_event_status(event, install_id, url, timeout=TIMEOUT_SECONDS):
    """POST one event and report the HTTP status; UNREACHABLE when no connection
    could be made; None when nothing was sent or the outcome is unknown (a
    timeout, a connection dropped mid-request); never raises.

    `install_id` and `url` are passed in so a caller that has already read and
    validated the record is not making this re-derive it. The status lets a
    caller tell a refusal it may retry (403, 429, 5xx) from one it may not (400).

    Everything is inside the try, not just the request: a malformed URL, an
    unserializable event or an unreadable manifest must fail the same silent way
    an unreachable network does.
    """
    try:
        if not record.is_accepted():
            return None

        payload = build_payload(event, install_id)
        if payload is None:
            return None

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except urllib.error.URLError as error:
            # Raised before any response: the connection was never made, unless
            # the reason is a timeout, which may have struck after the send.
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                return None
            return UNREACHABLE
    except BaseException:
        return None


def post_event(event, install_id, url):
    """POST one event. True only if the service accepted it; never raises."""
    status = post_event_status(event, install_id, url)
    return status is not None and 200 <= status < 300


def send_event(event):
    """POST one event, reading the install ID and endpoint for the caller."""
    # .get: an opted-out record is valid without an installId, and post_event
    # re-checks consent anyway, so None here simply means nothing is sent.
    state = record.read_state() or {}
    return post_event(event, state.get("installId"), endpoint())


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
