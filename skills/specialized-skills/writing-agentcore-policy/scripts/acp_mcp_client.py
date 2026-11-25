"""Minimal MCP (streamable HTTP) client that lists a Gateway's tools.

Speaks JSON-RPC over POST with the standard library only: ``initialize`` (with
protocol-version negotiation), ``notifications/initialized`` and a paginated
``tools/list``. Replies may be plain JSON or a ``text/event-stream``.

Authorization is delegated to a ``sign(request)`` callable that adds headers to
each ``urllib.request.Request`` (SigV4 over that exact request, or a bearer
token). Redirects are never followed so credentials stay with the Gateway.
Nothing here prints, logs or returns credentials.

Environment variables read: none.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from acp_common import SkillError

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_PATH = "/mcp"
CLIENT_INFO = {"name": "agentcore-policy-skill", "version": "0.1.0"}

MAX_PAGES = 200
MAX_TOOLS = 10_000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024

Sign = Callable[[urllib.request.Request], None]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def normalize_url(url: str) -> str:
    """Trailing slashes stripped; ``/mcp`` appended unless the path already ends with it."""
    if not isinstance(url, str) or not url.strip():
        raise SkillError("invalid_input", "the Gateway URL is empty")
    trimmed = url.strip().rstrip("/")
    scheme_end = trimmed.find("://")
    if scheme_end < 0:
        raise SkillError("invalid_input", "the Gateway URL must start with https://")
    query = trimmed.find("?", scheme_end)
    if query >= 0 or "#" in trimmed:
        raise SkillError("invalid_input", "the Gateway URL must not carry a query or fragment")
    return trimmed if trimmed.endswith(MCP_PATH) else trimmed + MCP_PATH


def _http_hint(status: int) -> str:
    if 300 <= status < 400:
        return (
            "the Gateway redirected; redirects are not followed so credentials stay with "
            "the Gateway"
        )
    if status in (401, 403):
        return (
            "the Gateway rejected the credentials (expired token, wrong audience/client, "
            "or missing InvokeGateway permission)"
        )
    if status in (404, 405):
        return "the Gateway does not serve MCP at this endpoint (no MCP capability, or not READY)"
    if status in (406, 415):
        return "the endpoint does not speak MCP streamable HTTP"
    if status == 429:
        return "the Gateway is throttling requests; retry later"
    if status >= 500:
        return "the Gateway failed while handling the request; retry later"
    return "the request was rejected"


def _error_message(body: bytes) -> str:
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if not isinstance(doc, dict):
        return ""
    msg = doc.get("message") or doc.get("Message")
    if msg is None and isinstance(doc.get("error"), dict):
        msg = doc["error"].get("message")
    return f": {msg[:300]}" if isinstance(msg, str) else ""


def _find_reply(value: Any, rpc_id: int) -> dict | None:
    if isinstance(value, list):
        for item in value:
            found = _find_reply(item, rpc_id)
            if found is not None:
                return found
        return None
    if (
        isinstance(value, dict)
        and value.get("id") == rpc_id
        and ("result" in value or "error" in value)
    ):
        return value
    return None


def _read_sse(resp: Any, rpc_id: int) -> dict | None:
    """Read events until the reply to ``rpc_id`` arrives (the stream may stay open)."""
    total = 0
    data: list[str] = []
    while True:
        raw = resp.readline(MAX_RESPONSE_BYTES + 1)
        total += len(raw)
        if total > MAX_RESPONSE_BYTES:
            raise SkillError("mcp_error", "the MCP response exceeded the size limit")
        line = raw.decode("utf-8", "replace").rstrip("\r\n") if raw else None
        if line:
            if line.startswith("data:"):
                chunk = line[5:]
                data.append(chunk.removeprefix(" "))
            continue
        if data:  # blank line or end of stream closes an event
            try:
                found = _find_reply(json.loads("\n".join(data)), rpc_id)
            except ValueError:
                found = None
            data = []
            if found is not None:
                return found
        if line is None:
            return None


class _Session:
    def __init__(self, url: str, sign: Sign, timeout: float) -> None:
        self.url = url
        self.sign = sign
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol: str | None = None
        self.next_id = 1

    def post(self, message: dict, expect_id: int | None) -> dict | None:
        body = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.protocol:
            req.add_header("MCP-Protocol-Version", self.protocol)
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        self.sign(req)
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                self._remember_session(resp.headers.get("Mcp-Session-Id"))
                if expect_id is None:
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in ctype:
                    reply = _read_sse(resp, expect_id)
                    if reply is None:
                        raise SkillError(
                            "mcp_error", "the MCP event stream ended without a reply to the request"
                        )
                    return reply
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = _error_message(exc.read(MAX_ERROR_BYTES))
            except OSError:
                pass
            finally:
                exc.close()
            raise SkillError(
                "mcp_error",
                f"the Gateway MCP endpoint returned HTTP {exc.code}: "
                f"{_http_hint(exc.code)}{detail}",
                http_status=exc.code,
            ) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise SkillError("mcp_error", "could not reach the Gateway MCP endpoint") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SkillError("mcp_error", "the MCP response exceeded the size limit")
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SkillError(
                "mcp_error", "the MCP response was neither JSON nor an event stream"
            ) from None
        reply = _find_reply(doc, expect_id)
        if reply is None:
            raise SkillError("mcp_error", "the MCP response did not contain a reply to the request")
        return reply

    def _remember_session(self, value: str | None) -> None:
        if value and len(value) <= 256 and value.isascii() and value.isprintable():
            self.session_id = value

    def rpc(self, method: str, params: dict) -> dict:
        """The raw JSON-RPC reply, including any ``error`` member."""
        rpc_id = self.next_id
        self.next_id += 1
        reply = self.post(
            {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}, rpc_id
        )
        assert reply is not None
        return reply

    def call(self, method: str, params: dict) -> dict:
        """The JSON-RPC ``result``; an ``error`` becomes a SkillError."""
        reply = self.rpc(method, params)
        err = reply.get("error")
        if err is not None:
            code = err.get("code") if isinstance(err, dict) else None
            text = err.get("message") if isinstance(err, dict) else None
            text = text[:300] if isinstance(text, str) else "no message"
            extra = (
                f"; the Gateway's MCP server does not implement {method}" if code == -32601 else ""
            )
            raise SkillError("mcp_error", f"MCP {method} failed ({code}): {text}{extra}")
        result = reply.get("result")
        return result if isinstance(result, dict) else {}


def _initialize_params(version: str) -> dict:
    return {"protocolVersion": version, "capabilities": {}, "clientInfo": CLIENT_INFO}


def _no_common_version(server: list) -> SkillError:
    return SkillError(
        "mcp_error",
        "the Gateway shares no MCP protocol version with this client "
        f"(client supports {list(SUPPORTED_PROTOCOL_VERSIONS)}, Gateway lists {server})",
        client_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        server_versions=server,
    )


def _initialize(session: _Session) -> None:
    reply = session.rpc("initialize", _initialize_params(SUPPORTED_PROTOCOL_VERSIONS[0]))
    err = reply.get("error")
    if isinstance(err, dict):
        data = err.get("data")
        offered = data.get("supported") if isinstance(data, dict) else None
        if isinstance(offered, list):
            server = [v for v in offered if isinstance(v, str)]
            agreed = next((v for v in SUPPORTED_PROTOCOL_VERSIONS if v in server), None)
            if agreed is None:
                raise _no_common_version(server)
            reply = session.rpc("initialize", _initialize_params(agreed))
            err = reply.get("error")
    if err is not None:
        text = err.get("message") if isinstance(err, dict) else None
        text = text[:300] if isinstance(text, str) else "no message"
        raise SkillError("mcp_error", f"MCP initialize failed: {text}")
    result = reply.get("result")
    version = result.get("protocolVersion") if isinstance(result, dict) else None
    if isinstance(version, str):
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise _no_common_version([version])
        session.protocol = version
    session.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, None)


def list_tools(url: str, sign: Sign, timeout: float = 30) -> list[dict]:
    """``initialize`` then every page of ``tools/list`` at the Gateway's MCP endpoint."""
    session = _Session(normalize_url(url), sign, timeout)
    _initialize(session)
    tools: list[dict] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        result = session.call("tools/list", {"cursor": cursor} if cursor else {})
        page = result.get("tools")
        if isinstance(page, list):
            tools.extend(t for t in page if isinstance(t, dict))
        if len(tools) > MAX_TOOLS:
            raise SkillError("mcp_error", f"the MCP endpoint returned more than {MAX_TOOLS} tools")
        nxt = result.get("nextCursor")
        if not isinstance(nxt, str) or not nxt:
            return tools
        if nxt == cursor:
            raise SkillError("mcp_error", "the MCP endpoint repeated its pagination cursor")
        cursor = nxt
    raise SkillError("mcp_error", f"MCP tools/list did not finish within {MAX_PAGES} pages")
