"""Deny-first handling for Blueprint literals and local identities."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .canonical import nfc

IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
SECRET_RE = re.compile(
    r"(?i)(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:bearer|basic)\s+[A-Za-z0-9._~+/-]+=*|(?:password|passwd|token|secret|api[_-]?key)\s*[:=])"
)
SENSITIVE_KEY_RE = re.compile(r"(?i)(password|passwd|token|secret|credential|private[_-]?key)")


class UnsafeIdentityError(ValueError):
    pass


def safe_identity(value: Any) -> str:
    if not isinstance(value, str):
        raise UnsafeIdentityError("identity_not_string")
    normalized = nfc(value)
    if not IDENTITY_RE.fullmatch(normalized):
        raise UnsafeIdentityError("unsafe_identity")
    return normalized


def safe_literal(value: str) -> str:
    normalized = nfc(value)
    if SECRET_RE.search(normalized):
        return "[REDACTED]"
    if "://" in normalized:
        parsed = urlsplit(normalized)
        if parsed.username is not None or parsed.password is not None:
            return "[REDACTED]"
    return normalized


def sanitize_config(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        if parent_key == "envVars":
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"value", "previewValue"}:
                    result[f"{key}Disposition"] = "redacted_literal"
                else:
                    result[key] = sanitize_config(item, parent_key=key)
            return result
        result = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                result[str(key)] = "[REDACTED]"
            elif str(key) == "value" and parent_key == "headers":
                result["valueDisposition"] = "redacted_literal"
            else:
                result[str(key)] = sanitize_config(item, parent_key=str(key))
        return result
    if isinstance(value, list):
        return [sanitize_config(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        return safe_literal(value)
    return value
