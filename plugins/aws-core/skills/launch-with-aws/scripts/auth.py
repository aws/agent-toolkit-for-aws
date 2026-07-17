# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""IAM Identity Center PKCE authentication.

Uses SSO OIDC directly:
    1. RegisterClient -> obtain clientId/clientSecret
    2. PKCE authorize via browser -> capture auth code on loopback
    3. CreateToken (authorization_code grant) -> access + refresh tokens
    4. CreateToken (refresh_token grant) -> silent refresh

Tokens cached in ~/.launch-with-aws/session.json (mode 0600).
"""

import base64
import hashlib
import html
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
from typing import Any, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from launch_config import (
    AUTH_WAIT_POLL_INTERVAL_SECS,
    CALLBACK_TIMEOUT_SECS,
    CLIENT_NAME,
    DEFAULT_TOKEN_LIFETIME_SECS,
    ENV_IDC_ISSUER_URL,
    ENV_SCOPES,
    IDC_ISSUER_URL,
    SCOPES,
    SESSION_DIR,
    SESSION_FILE_NAME,
    SSO_OIDC_REGION,
    TOKEN_EXPIRY_BUFFER_SECS,
    ClientCredentials,
    StoredSession,
)

__version__ = "0.1.0"


class SessionExpiredError(Exception):
    """Raised when the session cannot be refreshed non-interactively."""

    pass


def _session_dir() -> str:
    return os.path.expanduser(SESSION_DIR)


def _session_file() -> str:
    return os.path.join(_session_dir(), SESSION_FILE_NAME)


def _create_sso_oidc_client(region: str) -> Any:
    import boto3
    from botocore.config import Config as BotoConfig

    config = BotoConfig(user_agent_extra=f"md/awslabs#launch-with-aws#{__version__}")
    return boto3.client("sso-oidc", region_name=region, config=config)


def _generate_pkce() -> Tuple[str, str]:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _generate_state() -> str:
    return secrets.token_hex(16)


# ── Session persistence ──────────────────────────────────────────────────


def load_session() -> Optional[StoredSession]:
    try:
        with open(_session_file()) as f:
            return StoredSession.from_json(f.read())
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_session(session: StoredSession) -> None:
    directory = _session_dir()
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, stat.S_IRWXU)

    old_umask = os.umask(0o077)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(session.to_json(indent=2))
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, _session_file())
    finally:
        os.umask(old_umask)


def has_valid_session() -> bool:
    session = load_session()
    return bool(session and session.token_expires_at > int(time.time()) + TOKEN_EXPIRY_BUFFER_SECS)


# ── Client registration ──────────────────────────────────────────────────


def _resolve_scopes() -> list[str]:
    env_val = os.environ.get(ENV_SCOPES)
    if env_val:
        return [s.strip() for s in env_val.split(",") if s.strip()]
    return list(SCOPES)


def _register_client() -> ClientCredentials:
    sso_oidc = _create_sso_oidc_client(SSO_OIDC_REGION)
    scopes = _resolve_scopes()

    kwargs: dict[str, Any] = {
        "clientName": CLIENT_NAME,
        "clientType": "public",
        "grantTypes": ["authorization_code", "refresh_token"],
        "scopes": scopes,
        "issuerUrl": os.environ.get(ENV_IDC_ISSUER_URL) or IDC_ISSUER_URL,
        "redirectUris": ["http://127.0.0.1"],
    }

    response = sso_oidc.register_client(**kwargs)

    client_id = response.get("clientId")
    client_secret = response.get("clientSecret")
    if not client_id or not client_secret:
        raise RuntimeError("Client registration response missing credentials")

    expires_at_sec = response.get("clientSecretExpiresAt") or 0
    client_expires_at = sys.maxsize if expires_at_sec == 0 else int(expires_at_sec)

    return ClientCredentials(
        client_id=client_id,
        client_secret=client_secret,
        client_expires_at=client_expires_at,
        authorize_endpoint=f"https://oidc.{SSO_OIDC_REGION}.amazonaws.com/authorize",
        token_endpoint=f"https://oidc.{SSO_OIDC_REGION}.amazonaws.com/token",
        scopes=scopes,
    )


# ── Token exchange ────────────────────────────────────────────────────────


def _exchange_code(
    credentials: ClientCredentials,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> Tuple[str, str, int]:
    sso_oidc = _create_sso_oidc_client(SSO_OIDC_REGION)
    response = sso_oidc.create_token(
        clientId=credentials.client_id,
        clientSecret=credentials.client_secret,
        grantType="authorization_code",
        code=code,
        codeVerifier=code_verifier,
        redirectUri=redirect_uri,
    )

    access_token = response.get("accessToken")
    refresh_token = response.get("refreshToken")
    if not access_token or not refresh_token:
        raise RuntimeError("Token exchange response missing tokens")

    expires_in = response.get("expiresIn") or DEFAULT_TOKEN_LIFETIME_SECS
    return access_token, refresh_token, int(time.time()) + expires_in


def _refresh_token(session: StoredSession) -> Tuple[str, str, int]:
    sso_oidc = _create_sso_oidc_client(SSO_OIDC_REGION)
    response = sso_oidc.create_token(
        clientId=session.client_id,
        clientSecret=session.client_secret,
        grantType="refresh_token",
        refreshToken=session.refresh_token,
    )

    access_token = response.get("accessToken")
    if not access_token:
        raise RuntimeError("Token refresh response missing tokens")

    refresh_token = response.get("refreshToken") or session.refresh_token
    expires_in = response.get("expiresIn") or DEFAULT_TOKEN_LIFETIME_SECS
    return access_token, refresh_token, int(time.time()) + expires_in


# ── Loopback callback server ─────────────────────────────────────────────


class _OAuthState:
    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.auth_code: Optional[str] = None
        self.error: Optional[str] = None
        self.code_received = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def _respond(self, status: int, message: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = f'<html><head><meta charset="utf-8"></head><body><h2>{html.escape(message)}</h2></body></html>'
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        state: _OAuthState = self.server.oauth_state  # type: ignore[attr-defined]
        params = parse_qs(urlparse(self.path).query)

        error = params.get("error", [None])[0]
        if error:
            desc = params.get("error_description", [error])[0]
            self._respond(400, f"Authorization failed: {desc}")
            state.error = f"Authorization denied: {desc}"
            state.code_received.set()
            return

        returned_state = params.get("state", [None])[0]
        code = params.get("code", [None])[0]

        if returned_state != state.expected_state:
            if not code:
                self.send_response(204)
                self.end_headers()
                return
            self._respond(400, "State mismatch")
            state.error = "OAuth state mismatch - possible CSRF"
            state.code_received.set()
            return

        if not code:
            self.send_response(204)
            self.end_headers()
            return

        self._respond(200, "Authenticated - you can close this tab.")
        state.auth_code = code
        state.code_received.set()

    def log_message(self, format: str, *args: object) -> None:
        pass


# ── Public API ────────────────────────────────────────────────────────────


def get_access_token() -> str:
    """Return a valid Bearer access token (non-interactive).

    Tries the cached token and silent refresh. If neither works, raises
    SessionExpiredError so the caller can direct the user to auth-start.
    """
    session = load_session()
    now = int(time.time())

    # 1. Valid cached access token.
    if session and session.token_expires_at > now + TOKEN_EXPIRY_BUFFER_SECS:
        return session.access_token

    # 2. Try silent refresh.
    if session and session.client_expires_at > now:
        try:
            access_token, refresh_tok, token_expires_at = _refresh_token(session)
            updated = StoredSession(
                **{
                    **asdict(session),
                    "access_token": access_token,
                    "refresh_token": refresh_tok,
                    "token_expires_at": token_expires_at,
                }
            )
            save_session(updated)
            return updated.access_token
        except Exception:
            pass

    raise SessionExpiredError("Session expired or not authenticated. Run auth-start to sign in.")


# ── Non-blocking auth (auth-start / auth-wait) ──────────────────────────


def start_auth() -> dict:
    """Attempt auth non-blockingly. Returns immediately.

    Returns:
      - {authenticated: True, reusedCachedSession: True} if cached token valid
      - {authenticated: True, reusedCachedSession: False} if silent refresh worked
      - {authenticated: False, signInUrl: ..., pid: N, port: N} if interactive needed
    """
    session = load_session()
    now = int(time.time())

    if session and session.token_expires_at > now + TOKEN_EXPIRY_BUFFER_SECS:
        return {"authenticated": True, "reusedCachedSession": True}

    if session and session.client_expires_at > now:
        try:
            access_token, refresh_tok, token_expires_at = _refresh_token(session)
            updated = StoredSession(
                **{
                    **asdict(session),
                    "access_token": access_token,
                    "refresh_token": refresh_tok,
                    "token_expires_at": token_expires_at,
                }
            )
            save_session(updated)
            return {"authenticated": True, "reusedCachedSession": False}
        except Exception:
            pass

    credentials: ClientCredentials
    if session and session.client_expires_at > now:
        credentials = session
    else:
        credentials = _register_client()

    code_verifier, code_challenge = _generate_pkce()
    state_value = _generate_state()

    server_script = os.path.join(os.path.dirname(__file__), "auth_callback_server.py")
    # Configuration values are passed to the child over stdin as a JSON blob.
    proc = subprocess.Popen(
        [
            sys.executable,
            server_script,
            "--state",
            state_value,
            "--timeout",
            str(int(CALLBACK_TIMEOUT_SECS)),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        start_new_session=True,
    )

    # Write the config to the child over stdin, then close it so the child sees EOF.
    assert proc.stdin is not None
    proc.stdin.write(
        json.dumps(
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "client_expires_at": credentials.client_expires_at,
                "scopes": credentials.scopes,
                "code_verifier": code_verifier,
            }
        ).encode()
    )
    proc.stdin.close()

    # Child writes port to stdout once bound.
    assert proc.stdout is not None
    assert proc.stderr is not None
    port_line = proc.stdout.readline().decode().strip()
    proc.stdout.close()
    if not port_line.isdigit():
        proc.terminate()
        err_output = proc.stderr.read().decode().strip()
        proc.stderr.close()
        detail = err_output or port_line or "no output"
        raise RuntimeError(f"Callback server failed to start: {detail}")
    proc.stderr.close()
    port = int(port_line)

    redirect_uri = f"http://127.0.0.1:{port}"
    authorize_url = f"{credentials.authorize_endpoint}?" + urlencode(
        {
            "response_type": "code",
            "client_id": credentials.client_id,
            "redirect_uri": redirect_uri,
            "state": state_value,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(credentials.scopes),
        }
    )

    return {
        "authenticated": False,
        "signInUrl": authorize_url,
        "pid": proc.pid,
        "port": port,
    }


def wait_for_auth(pid: int, timeout: Optional[float] = None) -> dict:
    """Block until the background callback server completes auth.

    Args:
        pid: PID of the background callback server (from start_auth).
        timeout: Max seconds to wait (default: CALLBACK_TIMEOUT_SECS).

    Returns:
        {authenticated: True} on success.

    Raises:
        TimeoutError if timeout exceeded.
        RuntimeError if the server exited without completing auth.
    """
    timeout = timeout or CALLBACK_TIMEOUT_SECS
    deadline = time.time() + timeout

    while time.time() < deadline:
        if has_valid_session():
            return {"authenticated": True}

        try:
            os.kill(pid, 0)
        except OSError:
            if has_valid_session():
                return {"authenticated": True}
            raise RuntimeError(
                "Auth callback server exited without completing authentication. "
                "Run auth-start again."
            )

        time.sleep(AUTH_WAIT_POLL_INTERVAL_SECS)

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    raise TimeoutError(f"Authentication timed out after {int(timeout)} seconds")
