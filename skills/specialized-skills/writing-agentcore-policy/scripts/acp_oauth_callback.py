#!/usr/bin/env python3
"""Detached OAuth callback process, spawned by acp_oauth.start_login.

Reads one JSON configuration object from stdin (it carries the PKCE verifier and state,
so it never appears on a command line), binds 127.0.0.1:<port>, prints one JSON line
(``{"port": n}`` or ``{"error": text}``) for the parent, then serves the redirect for up
to five minutes, exchanges the authorization code and stores the token under the private
home directory. Prints nothing else.

Environment variables read: AGENTCORE_POLICY_HOME (via acp_common.home_dir).
"""

from __future__ import annotations

import json
import sys

import acp_oauth


def _announce(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        config = json.loads(sys.stdin.read())
        required = (
            "login_id",
            "gateway_arn",
            "token_endpoint",
            "client_id",
            "code_verifier",
            "state",
            "port",
        )
        if not isinstance(config, dict) or any(k not in config for k in required):
            raise ValueError("incomplete configuration")
    except ValueError:
        _announce({"error": "the sign-in callback server received no valid configuration"})
        return 1
    outcome = acp_oauth.serve_login(config, _announce)
    try:
        sys.stdout.close()
    except OSError:
        pass
    return 0 if outcome["status"] == "signed_in" else 1


if __name__ == "__main__":
    sys.exit(main())
