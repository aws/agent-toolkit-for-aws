"""Read trusted release configuration. Account sharing is disabled by default.

This file is shipped with the runtime, not selected by an environment variable
or supplied by the sharing page. Enabling account reporting requires approved
notice text and the corresponding reporting service deployment.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

POLICY_PATH = Path(__file__).with_name("policy.json")
_AUDIENCE = re.compile(r"startup-advisor:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:report:v1\Z")


def validate_account_policy(value):
    """Return a normalized policy, or None. Never infer an audience from a URL."""
    if not isinstance(value, dict) or value.get("enabled") is not True or value.get("approved") is not True:
        return None
    version = value.get("noticeVersion")
    text = value.get("noticeText")
    endpoint = value.get("endpoint")
    audience = value.get("audience")
    if type(version) is not int or version < 1:
        return None
    if not isinstance(text, str) or not text.strip() or len(text) > 32768:
        return None
    if not isinstance(audience, str) or not _AUDIENCE.fullmatch(audience):
        return None
    if not isinstance(endpoint, str) or any(ord(char) < 33 for char in endpoint):
        return None
    try:
        url = urlsplit(endpoint)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.port not in (None, 443)
                or url.query or url.fragment or url.path != "/v1/plugin-telemetry-event"):
            return None
    except ValueError:
        return None
    return {
        "enabled": True,
        "approved": True,
        "noticeVersion": version,
        "noticeText": text,
        "endpoint": endpoint,
        "audience": audience,
    }


def account_policy():
    """Load an approved account-reporting policy from the bundled configuration."""
    if os.name != "posix":
        # Account workers require verified descendant cleanup. Other platforms
        # retain anonymous reporting until an equivalent process boundary is
        # implemented and independently validated.
        return None
    try:
        with POLICY_PATH.open(encoding="utf-8") as handle:
            document = json.load(handle)
        return validate_account_policy(document.get("accountReporting"))
    except (OSError, ValueError, AttributeError):
        return None
