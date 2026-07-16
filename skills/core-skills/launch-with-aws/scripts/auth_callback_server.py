#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Background OAuth callback server.

Spawned by auth-start, consumed by auth-wait.
Listens for the OAuth callback, exchanges the code for tokens,
writes session.json, and exits.

Usage:
    python3 auth_callback_server.py --state STATE --timeout 300

Configuration values are read as a JSON blob from stdin.

Writes the bound port number to stdout (one line) so the parent can read it.
"""

import argparse
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dataclasses import fields

from auth import (
    _CallbackHandler,
    _exchange_code,
    _OAuthState,
    save_session,
)
from launch_config import (
    CALLBACK_TIMEOUT_SECS,
    SSO_OIDC_REGION,
    ClientCredentials,
    StoredSession,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--timeout", type=float, default=CALLBACK_TIMEOUT_SECS)
    args = parser.parse_args()

    # Configuration arrives as a JSON blob on stdin.
    raw = sys.stdin.read()
    if not raw:
        sys.stderr.write("No configuration received on stdin\n")
        sys.exit(1)
    payload = json.loads(raw)

    credentials = ClientCredentials(
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        client_expires_at=payload["client_expires_at"],
        authorize_endpoint=f"https://oidc.{SSO_OIDC_REGION}.amazonaws.com/authorize",
        token_endpoint=f"https://oidc.{SSO_OIDC_REGION}.amazonaws.com/token",
        scopes=payload["scopes"],
    )
    code_verifier = payload["code_verifier"]

    oauth_state = _OAuthState(args.state)
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    setattr(server, "oauth_state", oauth_state)
    port = server.server_address[1]

    # Signal port to parent, then close stdout.
    sys.stdout.write(f"{port}\n")
    sys.stdout.flush()
    sys.stdout.close()

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    redirect_uri = f"http://127.0.0.1:{port}"

    if not oauth_state.code_received.wait(timeout=args.timeout):
        server.shutdown()
        sys.exit(1)

    server.shutdown()

    if oauth_state.error or not oauth_state.auth_code:
        sys.exit(1)

    access_token, refresh_tok, token_expires_at = _exchange_code(
        credentials, oauth_state.auth_code, code_verifier, redirect_uri
    )

    new_session = StoredSession(
        **{f.name: getattr(credentials, f.name) for f in fields(ClientCredentials)},
        access_token=access_token,
        refresh_token=refresh_tok,
        token_expires_at=token_expires_at,
    )
    save_session(new_session)


if __name__ == "__main__":
    main()
