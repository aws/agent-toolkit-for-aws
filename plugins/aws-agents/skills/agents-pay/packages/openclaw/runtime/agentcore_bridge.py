#!/usr/bin/env python3
"""Bounded JSON bridge for the two AgentCore calls used by OpenClaw."""

from __future__ import annotations

import base64
import datetime as dt
import json
import sys
from decimal import Decimal
from typing import Any, Callable

MAX_INPUT_BYTES = 128 * 1024


class BridgeInputError(ValueError):
    """The caller supplied a request outside the bridge contract."""


def _required_string(
    request: dict[str, Any],
    key: str,
    *,
    max_length: int = 2048,
) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise BridgeInputError(f"invalid {key}")
    return value


def _require_exact_keys(request: dict[str, Any], expected: set[str]) -> None:
    if set(request) != expected:
        raise BridgeInputError("unexpected request fields")


def _client(region: str) -> Any:
    import boto3

    return boto3.client("bedrock-agentcore", region_name=region)


def _dispatch(
    request: dict[str, Any],
    client_factory: Callable[[str], Any] = _client,
) -> dict[str, Any]:
    operation = request.get("operation")
    common = {
        "operation",
        "region",
        "payment_manager_arn",
        "payment_session_id",
        "user_id",
        "agent_name",
    }
    if operation == "get_payment_session":
        _require_exact_keys(request, common)
    elif operation == "process_payment":
        _require_exact_keys(
            request,
            common
            | {
                "payment_instrument_id",
                "client_token",
                "version",
                "payload",
            },
        )
    else:
        raise BridgeInputError("unsupported operation")

    region = _required_string(request, "region", max_length=128)
    agent_name = _required_string(request, "agent_name", max_length=256)
    common_params = {
        "paymentManagerArn": _required_string(request, "payment_manager_arn"),
        "paymentSessionId": _required_string(request, "payment_session_id"),
        "userId": _required_string(request, "user_id", max_length=512),
        "agentName": agent_name,
    }

    if operation == "get_payment_session":
        return client_factory(region).get_payment_session(**common_params)

    version = _required_string(request, "version", max_length=8)
    if version != "2":
        raise BridgeInputError("unsupported x402 version")
    client_token = _required_string(request, "client_token", max_length=128)
    if len(client_token) != 64 or any(c not in "0123456789abcdef" for c in client_token):
        raise BridgeInputError("invalid client token")
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise BridgeInputError("invalid payment payload")

    return client_factory(region).process_payment(
        **common_params,
        paymentInstrumentId=_required_string(request, "payment_instrument_id"),
        clientToken=client_token,
        paymentType="CRYPTO_X402",
        paymentInput={
            "cryptoX402": {
                "version": version,
                "payload": payload,
            }
        },
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    raise TypeError(f"unsupported response type: {type(value).__name__}")


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise BridgeInputError("invalid request size")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise BridgeInputError("request must be an object")
    return parsed


def main() -> int:
    try:
        result = _dispatch(_read_request())
        print(
            json.dumps(
                {"ok": True, "result": result},
                default=_json_default,
                separators=(",", ":"),
            )
        )
        return 0
    except (BridgeInputError, json.JSONDecodeError):
        print('{"ok":false,"error":"invalid bridge request"}')
        return 2
    except Exception:
        # AWS and credential details must not enter OpenClaw output or logs.
        print('{"ok":false,"error":"AgentCore request failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
