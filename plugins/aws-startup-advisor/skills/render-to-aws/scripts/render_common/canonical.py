"""Canonical Unicode, JSON, digest, and identity helpers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return nfc(value)
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = nfc(str(key))
            if normalized_key in normalized:
                raise ValueError("duplicate_normalized_key")
            normalized[normalized_key] = normalize(item)
        return normalized
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            normalize(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def generated_id(prefix: str, *parts: str) -> str:
    canonical_input = "\0".join(nfc(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(canonical_input).hexdigest()[:24]}"


def byte_sort_key(value: str) -> bytes:
    return nfc(value).encode("utf-8")
