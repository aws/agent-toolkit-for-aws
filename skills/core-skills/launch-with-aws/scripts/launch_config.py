# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configuration, constants, and models for launch-with-aws scripts."""

import ipaddress
import json
import logging
import os
import socket
from dataclasses import asdict, dataclass
from typing import List
from urllib.parse import urlparse

# ── Constants ────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://launch-with-aws.us-east-1.api.aws"

ENV_BASE_URL = "LAUNCH_WITH_AWS_BASE_URL"
ENV_IDC_ISSUER_URL = "LAUNCH_WITH_AWS_IDC_ISSUER_URL"
ENV_SCOPES = "LAUNCH_WITH_AWS_SCOPES"

SSO_OIDC_REGION = "us-east-1"
IDC_ISSUER_URL = "https://view.awsapps.com/start"

CLIENT_NAME = "Launch with AWS Agent Skill"
SCOPES = ["launch:access"]
TOKEN_EXPIRY_BUFFER_SECS = 300
CALLBACK_TIMEOUT_SECS = 600.0
DEFAULT_TOKEN_LIFETIME_SECS = 28800

SESSION_DIR = "~/.launch-with-aws"
SESSION_FILE_NAME = "session.json"

AUTH_WAIT_POLL_INTERVAL_SECS = 1.0

REQUEST_TIMEOUT_SECS = 120.0
UPLOAD_TIMEOUT_SECS = 300.0
GITHUB_ZIPBALL_TIMEOUT_SECS = 120.0

DEFAULT_COST_ESTIMATE_REGION = "us-east-1"
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024

# ── Models ───────────────────────────────────────────────────────────────


@dataclass
class ClientCredentials:
    """OIDC client registration plus the derived authorize/token endpoints."""

    client_id: str
    client_secret: str
    client_expires_at: int
    authorize_endpoint: str
    token_endpoint: str
    scopes: List[str]


@dataclass
class StoredSession(ClientCredentials):
    """A persisted session: client registration plus the current token pair."""

    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: int = 0

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "StoredSession":
        return cls(**json.loads(text))


# ── Runtime config ───────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

_ALLOWED_HOST_SUFFIXES = (".api.aws", ".amazonaws.com")


class ConfigError(Exception):
    """Raised when configuration is invalid or unsafe."""


def _validate_base_url(url: str) -> str:
    """Validate and return a sanitized base URL.

    Rejects non-HTTPS schemes, hosts outside the AWS domain allowlist,
    and hosts that resolve to private/loopback/link-local addresses.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ConfigError(
            f"Invalid {ENV_BASE_URL}: scheme must be https, got {parsed.scheme!r}. "
            "Refusing to send credentials over a non-HTTPS connection."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ConfigError(f"Invalid {ENV_BASE_URL}: no hostname in {url!r}.")

    if not any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix)
        for suffix in _ALLOWED_HOST_SUFFIXES
    ):
        raise ConfigError(
            f"Invalid {ENV_BASE_URL}: host {hostname!r} is not in the allowed "
            f'domains ({", ".join(_ALLOWED_HOST_SUFFIXES)}). '
            "Only official AWS endpoints are permitted."
        )

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as err:
        raise ConfigError(
            f"Invalid {ENV_BASE_URL}: DNS resolution failed for {hostname!r}: {err}. "
            "Refusing to proceed with an unresolvable host."
        ) from err

    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ConfigError(
                f"Invalid {ENV_BASE_URL}: host {hostname!r} resolves to "
                f"private/loopback/link-local address {ip}. "
                "Refusing to send credentials to a non-public address."
            )

    return url.rstrip("/")


class Config:
    """Configuration loaded from environment variables."""

    def __init__(self) -> None:
        env_url = os.environ.get(ENV_BASE_URL)
        if env_url:
            self.base_url = _validate_base_url(env_url)
            logger.info("Using non-default base URL: %s", self.base_url)
        else:
            self.base_url = DEFAULT_BASE_URL


def load_config() -> Config:
    return Config()
