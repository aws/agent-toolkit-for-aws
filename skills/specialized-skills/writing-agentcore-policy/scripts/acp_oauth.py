"""OAuth sign-in for CUSTOM_JWT Gateways: authorization code + PKCE (S256), public client.

``start_login`` discovers the authorization and token endpoints from the Gateway's
OIDC discovery URL, then spawns a detached loopback callback process
(``acp_oauth_callback.py``) listening on 127.0.0.1:``OAUTH_CALLBACK_PORT`` for five
minutes. The callback process exchanges the code (no client secret) and stores the
access token under ``home_dir()/tokens/<sha256(gateway arn)>.json`` (mode 0600).
Tokens are bound to one Gateway ARN, expire locally, and are never printed or returned.
The login session (no secrets) lives in ``home_dir()/login.json``.

Network: only the discovery URL configured on the Gateway (read with GetGateway) and the
endpoints that document lists; HTTPS only, or plain http on a loopback host. The document's
``issuer`` must match the discovery URL, and both endpoints must be on the issuer's origin
(one exception: an Amazon Cognito user pool, whose endpoints are on its
``<domain>.auth.<region>.amazoncognito.com`` domain).

Environment variables read: OAUTH_CALLBACK_PORT (default 8765), AGENTCORE_POLICY_HOME
(via acp_common.home_dir).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import acp_common
from acp_common import SkillError

DEFAULT_CALLBACK_PORT = 8765
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PATH = "/callback"
LOGIN_WINDOW_SECS = 300
CONNECTION_READ_SECS = 5
HTTP_TIMEOUT_SECS = 15
STARTUP_WAIT_SECS = 10
BIND_RETRY_SECS = 5
MAX_BODY_BYTES = 1024 * 1024
ASSUMED_LIFETIME_SECS = 3600
MAX_LIFETIME_SECS = 24 * 3600
EXPIRY_SKEW_SECS = 30
MAX_WAIT_SECS = 300

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# OIDC Discovery 1.0 §4 appends this suffix to the issuer; RFC 8414 §3 inserts the
# well-known segment between the issuer's origin and path (also used for openid-configuration).
_OIDC_SUFFIX = "/.well-known/openid-configuration"
_RFC8414_PREFIXES = ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")
# Cognito user pool issuers (original and "updated" formats); their authorize and token
# endpoints are on the pool's prefix domain, <prefix>.auth.<region>.amazoncognito.com.
_COGNITO_ISSUER_HOST = re.compile(r"(?:issuer-)?cognito-idp\.([a-z0-9-]+)\.amazonaws\.com")

_DONE_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>Signed in</title>"
    "<body><p>Sign-in received. You can close this tab and return to the agent.</p></body>"
)
_FAIL_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>Sign-in failed</title>"
    "<body><p>Sign-in could not be completed. Return to the agent for details.</p></body>"
)


# ── paths and files ──────────────────────────────────────────────────────


def _login_file() -> Path:
    return acp_common.home_dir() / "login.json"


def _token_file(gateway_arn: str) -> Path:
    return acp_common.home_dir() / "tokens" / f"{acp_common.sha256_hex(gateway_arn)}.json"


def _read_json(path: Path) -> Any:
    """A damaged token or login file counts as absent: the developer signs in again."""
    try:
        return acp_common.read_json(path, None)
    except (SkillError, OSError):
        return None


def callback_port() -> int:
    raw = os.environ.get("OAUTH_CALLBACK_PORT")
    if raw is None or raw.strip() == "":
        return DEFAULT_CALLBACK_PORT
    try:
        port = int(raw)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise SkillError("invalid_input", "OAUTH_CALLBACK_PORT must be a port number (0-65535)")
    return port


# ── token store ──────────────────────────────────────────────────────────


def save_token(
    gateway_arn: str, access_token: str, lifetime_secs: int, scope: str | None = None
) -> None:
    tokens = acp_common.home_dir() / "tokens"
    tokens.mkdir(mode=0o700, exist_ok=True)
    os.chmod(tokens, 0o700)
    acp_common.write_json(
        _token_file(gateway_arn),
        {
            "gateway_arn": gateway_arn,
            "access_token": access_token,
            "expires_at": int(time.time()) + int(lifetime_secs),
            "scope": scope,
        },
    )


def get_token(gateway_arn: str) -> str | None:
    """The stored access token for exactly this Gateway, or None when absent/expired."""
    doc = _read_json(_token_file(gateway_arn))
    if not isinstance(doc, dict) or doc.get("gateway_arn") != gateway_arn:
        return None
    token = doc.get("access_token")
    expires = doc.get("expires_at")
    if not isinstance(token, str) or not token or not isinstance(expires, (int, float)):
        return None
    if expires <= time.time() + EXPIRY_SKEW_SECS:
        return None
    return token


def sign_out(gateway_arn: str | None = None) -> dict:
    """Delete the stored token for one Gateway (or all) and cancel a pending sign-in."""
    removed = 0
    if gateway_arn is not None:
        acp_common.parse_gateway_arn(gateway_arn)
        files = [_token_file(gateway_arn)]
    else:
        files = sorted((acp_common.home_dir() / "tokens").glob("*.json"))
    for path in files:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    login = _read_json(_login_file())
    if (
        isinstance(login, dict)
        and login.get("status") == "pending"
        and (gateway_arn is None or login.get("gateway_arn") == gateway_arn)
    ):
        cancel_login()
    return {"signed_out": True, "tokens_removed": removed}


# ── HTTP helpers (IdP endpoints) ─────────────────────────────────────────


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def check_idp_url(url: Any, label: str) -> str:
    """HTTPS only; plain http is accepted solely for a loopback host (local IdP/tests)."""
    if not isinstance(url, str):
        raise SkillError("oauth_failed", f"{label} is missing")
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return url
    raise SkillError("oauth_failed", f"{label} must be an https URL")


def _read_limited(resp: Any) -> bytes:
    body = resp.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise SkillError("oauth_failed", "the identity provider response is too large")
    return body


def _get_json(url: str, label: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT_SECS) as resp:
            doc = json.loads(_read_limited(resp).decode("utf-8"))
    except SkillError:
        raise
    except urllib.error.HTTPError as exc:
        exc.close()
        raise SkillError("oauth_failed", f"{label} returned HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise SkillError("oauth_failed", f"could not reach the {label}") from None
    except ValueError:
        raise SkillError("oauth_failed", f"the {label} is not valid JSON") from None
    if not isinstance(doc, dict):
        raise SkillError("oauth_failed", f"the {label} is not a JSON object")
    return doc


_DEFAULT_PORTS = {"https": 443, "http": 80}


def _origin(url: str) -> str:
    """``scheme://host:port`` from parsed parts; a URL with user info has no valid origin."""
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        raise SkillError("oauth_failed", "an identity provider URL has an invalid port") from None
    if parts.username is not None or parts.password is not None or not parts.hostname:
        raise SkillError("oauth_failed", "an identity provider URL has user info or no host")
    return f"{parts.scheme}://{parts.hostname}:{port}"


def _issuers_for(discovery_url: str) -> set[str]:
    """Issuer values the discovery URL can belong to (OIDC Discovery §4, RFC 8414 §3)."""
    parts = urllib.parse.urlsplit(discovery_url)
    origin = _origin(discovery_url)
    path = parts.path
    issuers = set()
    if path.endswith(_OIDC_SUFFIX):
        issuers.add(origin + path[: -len(_OIDC_SUFFIX)])
    for prefix in _RFC8414_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            issuers.add(origin + path[len(prefix) :])
    if not issuers:
        raise SkillError(
            "oauth_failed",
            "the Gateway's discovery URL is not a /.well-known/openid-configuration or "
            "/.well-known/oauth-authorization-server URL",
        )
    return {issuer.rstrip("/") for issuer in issuers}


def _endpoint_origin_allowed(issuer: str, endpoint: str) -> bool:
    """The endpoint is on the issuer's origin, or on the Cognito domain of a Cognito issuer."""
    if _origin(endpoint) == _origin(issuer):
        return True
    issuer_parts = urllib.parse.urlsplit(issuer)
    endpoint_parts = urllib.parse.urlsplit(endpoint)
    match = _COGNITO_ISSUER_HOST.fullmatch(issuer_parts.hostname or "")
    if not match or issuer_parts.scheme != "https" or endpoint_parts.scheme != "https":
        return False
    if endpoint_parts.port not in (None, 443):
        return False
    region = re.escape(match.group(1))
    return (
        re.fullmatch(
            rf"[a-z0-9-]+\.auth\.{region}\.amazoncognito\.com", endpoint_parts.hostname or ""
        )
        is not None
    )


def discover_endpoints(discovery_url: str) -> dict:
    """``{"issuer", "authorization": str|None, "token"}`` from the Gateway's discovery document.

    The document's ``issuer`` must match the discovery URL, and both endpoints must be on
    the issuer's origin (or, for an Amazon Cognito user pool, on one
    ``<prefix>.auth.<region>.amazoncognito.com`` origin), so a document cannot send the
    sign-in or the authorization code to another host.
    """
    url = check_idp_url(discovery_url, "the Gateway's discovery URL")
    expected = _issuers_for(url)
    doc = _get_json(url, "OIDC discovery document")
    issuer = doc.get("issuer")
    normalized = None
    if isinstance(issuer, str):
        issuer_parts = urllib.parse.urlsplit(issuer)
        if not issuer_parts.query and not issuer_parts.fragment:
            normalized = (_origin(issuer) + issuer_parts.path).rstrip("/")
    if normalized is None or normalized not in expected:
        raise SkillError(
            "oauth_failed",
            "the discovery document's issuer does not match the Gateway's discovery URL",
        )
    assert isinstance(issuer, str)
    token = check_idp_url(doc.get("token_endpoint"), "token_endpoint")
    authorization = doc.get("authorization_endpoint")
    if authorization is not None:
        authorization = check_idp_url(authorization, "authorization_endpoint")
    for label, endpoint in (("token_endpoint", token), ("authorization_endpoint", authorization)):
        if endpoint is not None and not _endpoint_origin_allowed(issuer, endpoint):
            raise SkillError(
                "oauth_failed",
                f"{label} is not on the identity provider's host ({_origin(issuer)})",
            )
    if authorization is not None and _origin(authorization) != _origin(token):
        raise SkillError(
            "oauth_failed", "authorization_endpoint and token_endpoint are on different hosts"
        )
    return {"issuer": issuer, "authorization": authorization, "token": token}


def _scope_text(scope: Any) -> str | None:
    return scope if isinstance(scope, str) and scope.strip() else None


def exchange_code(
    token_endpoint: str, *, code: str, redirect_uri: str, verifier: str, client_id: str
) -> tuple[str, int, str | None]:
    """Token request for a public client. Returns (access_token, lifetime_secs, scope)."""
    check_idp_url(token_endpoint, "token_endpoint")
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
        }
    ).encode("ascii")
    req = urllib.request.Request(
        token_endpoint,
        data=form,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    status = 0
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT_SECS) as resp:
            status = resp.status
            body = _read_limited(resp)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read(MAX_BODY_BYTES)
        except OSError:
            body = b""
        exc.close()
    except (urllib.error.URLError, OSError, TimeoutError):
        raise SkillError("oauth_failed", "could not reach the token endpoint") from None
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not 200 <= status < 300:
        # An IdP can echo request secrets; forward only a standard OAuth error code.
        code_text = payload.get("error")
        suffix = ""
        if (
            isinstance(code_text, str)
            and len(code_text) <= 40
            and all(c.islower() or c == "_" for c in code_text)
        ):
            suffix = f" ({code_text})"
        raise SkillError(
            "oauth_failed",
            f"the token endpoint returned HTTP {status}{suffix}; check the client registration "
            "and redirect URI with the identity provider",
        )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SkillError("oauth_failed", "the token response had no access_token")
    token_type = payload.get("token_type")
    if isinstance(token_type, str) and token_type.lower() != "bearer":
        raise SkillError("oauth_failed", "the token endpoint issued a non-bearer token type")
    stated = payload.get("expires_in")
    if stated is None:
        lifetime = ASSUMED_LIFETIME_SECS
    else:
        try:
            lifetime = int(str(stated).strip())
        except ValueError:
            raise SkillError(
                "oauth_failed", "the token response has an invalid expires_in"
            ) from None
        if lifetime <= 0:
            raise SkillError("oauth_failed", "the token endpoint issued an already-expired token")
    return token, min(lifetime, MAX_LIFETIME_SECS), _scope_text(payload.get("scope"))


# ── login session ────────────────────────────────────────────────────────


def _random_urlsafe(nbytes: int) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge)."""
    verifier = _random_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def build_authorization_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
    scope: str | None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    parts = urllib.parse.urlsplit(authorization_endpoint)
    existing = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = urllib.parse.urlencode(existing + list(params.items()))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _update_login(login_id: str, **fields: Any) -> bool:
    """Update the login session if it is still this login and still pending."""
    current = _read_json(_login_file())
    if (
        not isinstance(current, dict)
        or current.get("login_id") != login_id
        or current.get("status") != "pending"
    ):
        return False
    current.update(fields)
    acp_common.write_json(_login_file(), current)
    return True


def _login_is_current(login_id: str) -> bool:
    current = _read_json(_login_file())
    return (
        isinstance(current, dict)
        and current.get("login_id") == login_id
        and current.get("status") == "pending"
    )


def _spawn_callback(config: dict) -> int:
    """Start the detached callback process; returns the port it bound."""
    script = Path(__file__).resolve().with_name("acp_oauth_callback.py")
    kwargs: dict[str, Any] = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        # -B: never write bytecode into the skill's scripts directory.
        [sys.executable, "-B", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(json.dumps(config).encode("utf-8"))
        proc.stdin.close()
    except OSError:
        pass
    line: list[bytes] = []
    stdout = proc.stdout
    reader = threading.Thread(target=lambda: line.append(stdout.readline()), daemon=True)
    reader.start()
    reader.join(STARTUP_WAIT_SECS)
    try:
        announced = json.loads(line[0].decode("utf-8")) if line and line[0] else None
    except ValueError:
        announced = None
    if not isinstance(announced, dict) or not isinstance(announced.get("port"), int):
        proc.terminate()
        reason = announced.get("error") if isinstance(announced, dict) else None
        raise SkillError(
            "login_unavailable",
            reason if isinstance(reason, str) else "the sign-in callback server did not start",
        )
    proc.stdout.close()
    return announced["port"]


def start_login(
    gateway_arn: str, *, discovery_url: str, client_id: str, scope: str | None = None
) -> dict:
    """Begin a browser sign-in. Returns the authorization URL for the developer to open."""
    acp_common.parse_gateway_arn(gateway_arn)
    if not isinstance(client_id, str) or not client_id.strip():
        raise SkillError("invalid_input", "client_id is required to sign in")
    endpoints = discover_endpoints(discovery_url)
    if not endpoints["authorization"]:
        raise SkillError(
            "oauth_failed",
            "the Gateway's OIDC discovery document has no authorization_endpoint, so browser "
            "sign-in is unavailable",
        )
    cancel_login()
    verifier, challenge = pkce_pair()
    state = _random_urlsafe(24)
    login_id = uuid.uuid4().hex
    now = int(time.time())
    scope = _scope_text(scope)
    session = {
        "login_id": login_id,
        "gateway_arn": gateway_arn,
        "status": "pending",
        "message": "waiting for the browser sign-in to complete",
        "started_at": now,
        "expires_at": now + LOGIN_WINDOW_SECS,
    }
    acp_common.write_json(_login_file(), session)
    try:
        port = _spawn_callback(
            {
                "login_id": login_id,
                "gateway_arn": gateway_arn,
                "token_endpoint": endpoints["token"],
                "client_id": client_id,
                "code_verifier": verifier,
                "state": state,
                "scope": scope,
                "port": callback_port(),
                "timeout": LOGIN_WINDOW_SECS,
            }
        )
    except BaseException:
        _login_file().unlink(missing_ok=True)
        raise
    redirect_uri = f"http://{CALLBACK_HOST}:{port}{CALLBACK_PATH}"
    url = build_authorization_url(
        endpoints["authorization"],
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        challenge=challenge,
        scope=scope,
    )
    _update_login(login_id, authorization_url=url, redirect_uri=redirect_uri)
    return {
        "status": "pending",
        "login_id": login_id,
        "gateway_arn": gateway_arn,
        "idp_host": urllib.parse.urlsplit(endpoints["authorization"]).hostname,
        "authorization_url": url,
        "redirect_uri": redirect_uri,
        "expires_in": LOGIN_WINDOW_SECS,
    }


def _public_login(session: dict) -> dict:
    out = {
        k: session[k]
        for k in ("status", "login_id", "gateway_arn", "message", "authorization_url")
        if k in session
    }
    if session.get("status") == "signed_in" and "token_expires_at" in session:
        out["token_expires_at"] = session["token_expires_at"]
    return out


def login_status(wait_seconds: float = 0) -> dict:
    """Current sign-in state, optionally waiting (up to 5 minutes) for it to settle."""
    deadline = time.monotonic() + max(0.0, min(float(wait_seconds), MAX_WAIT_SECS))
    while True:
        session = _read_json(_login_file())
        if not isinstance(session, dict) or "status" not in session:
            return {"status": "none", "message": "no sign-in is in progress"}
        if session["status"] == "pending" and time.time() > session.get("expires_at", 0) + 5:
            _update_login(
                session.get("login_id", ""),
                status="failed",
                message="the sign-in window (5 minutes) expired; start the sign-in again",
            )
            session = _read_json(_login_file()) or session
        if session["status"] != "pending" or time.monotonic() >= deadline:
            return _public_login(session)
        time.sleep(0.25)


def cancel_login() -> dict:
    """Cancel a pending sign-in; the callback process notices and exits."""
    session = _read_json(_login_file())
    if isinstance(session, dict) and session.get("status") == "pending":
        _update_login(session.get("login_id", ""), status="cancelled", message="sign-in cancelled")
        return {"status": "cancelled"}
    return {"status": "none", "message": "no sign-in is in progress"}


# ── loopback callback server (runs in the detached process) ──────────────


class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: str) -> None:
        super().__init__(address, _CallbackHandler)
        self.expected_state = state
        self.code: str | None = None
        self.failure: str | None = None

    @property
    def finished(self) -> bool:
        return self.code is not None or self.failure is not None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    timeout = CONNECTION_READ_SECS  # per-connection read limit
    server_version = "agentcore-policy"

    def _respond(self, status: int, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        server: _CallbackServer = self.server  # type: ignore[assignment]
        parts = urllib.parse.urlsplit(self.path)
        if parts.path != CALLBACK_PATH:
            self._respond(404, _FAIL_PAGE)
            return
        query = urllib.parse.parse_qs(parts.query)
        got_state = query.get("state", [None])[0]
        if got_state is None or not secrets.compare_digest(got_state, server.expected_state):
            self._respond(400, _FAIL_PAGE)  # forged or stray request: keep waiting
            return
        if "error" in query:
            self._respond(400, _FAIL_PAGE)
            server.failure = "the identity provider declined the authorization request"
            return
        code = query.get("code", [""])[0]
        if not code:
            self._respond(400, _FAIL_PAGE)
            server.failure = "the redirect carried no authorization code"
            return
        self._respond(200, _DONE_PAGE)
        server.code = code

    def do_POST(self) -> None:
        self._respond(404, _FAIL_PAGE)

    do_PUT = do_DELETE = do_HEAD = do_PATCH = do_POST

    def log_message(self, format: str, *args: object) -> None:
        pass


def serve_login(config: dict, announce: Callable[[dict], None]) -> dict:
    """Bind the loopback listener, wait for the redirect, exchange the code, store the token.

    ``announce`` receives ``{"port": n}`` once listening, or ``{"error": text}``.
    Returns ``{"status": "signed_in"|"failed"|"cancelled", "message": str}``; the same
    outcome is written to the login session file. The token is never part of the outcome.
    """
    login_id = config["login_id"]
    server = None
    bind_deadline = time.monotonic() + BIND_RETRY_SECS
    while server is None:
        try:
            server = _CallbackServer((CALLBACK_HOST, int(config["port"])), config["state"])
        except OSError:
            if time.monotonic() >= bind_deadline:
                break
            time.sleep(0.2)  # a previous sign-in may still be releasing the port
    if server is None:
        announce(
            {
                "error": f"could not listen on {CALLBACK_HOST}:{config['port']}; another "
                "sign-in or process is using it (set OAUTH_CALLBACK_PORT to use another port)"
            }
        )
        _update_login(login_id, status="failed", message="the callback port is in use")
        return {"status": "failed", "message": "the callback port is in use"}
    port = server.server_address[1]
    announce({"port": port})
    deadline = time.monotonic() + float(config.get("timeout", LOGIN_WINDOW_SECS))
    try:
        while not server.finished:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = {"status": "failed", "message": "the sign-in window expired"}
                _update_login(login_id, **outcome)
                return outcome
            if not _login_is_current(login_id):
                return {"status": "cancelled", "message": "sign-in cancelled"}
            server.timeout = min(0.5, remaining)
            server.handle_request()
    finally:
        server.server_close()
    if server.failure or not server.code:
        outcome = {
            "status": "failed",
            "message": server.failure or "no authorization code",
        }
        _update_login(login_id, **outcome)
        return outcome
    redirect_uri = f"http://{CALLBACK_HOST}:{port}{CALLBACK_PATH}"
    try:
        token, lifetime, scope = exchange_code(
            config["token_endpoint"],
            code=server.code,
            redirect_uri=redirect_uri,
            verifier=config["code_verifier"],
            client_id=config["client_id"],
        )
    except SkillError as exc:
        outcome = {"status": "failed", "message": exc.message}
        _update_login(login_id, **outcome)
        return outcome
    if not _login_is_current(login_id):
        return {"status": "cancelled", "message": "sign-in cancelled"}
    save_token(config["gateway_arn"], token, lifetime, scope)
    outcome = {"status": "signed_in", "message": "signed in"}
    _update_login(login_id, token_expires_at=int(time.time()) + lifetime, **outcome)
    return outcome
