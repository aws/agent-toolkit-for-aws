# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configuration, constants, and models for launch-with-aws scripts."""

import ipaddress
import json
import logging
import os
import re
import socket
import stat
import tempfile
from dataclasses import asdict, dataclass
from typing import List, Optional
from urllib.parse import urlparse

# ── Constants ────────────────────────────────────────────────────────────

DEFAULT_REGION = "us-east-1"
EU_REGION = "eu-central-1"

# Regions the service runs migrations in, with the names shown to the customer.
SUPPORTED_REGIONS = {
    DEFAULT_REGION: "US East (N. Virginia)",
    EU_REGION: "Europe (Frankfurt)",
}

DEFAULT_BASE_URL = f"https://launch-with-aws.{DEFAULT_REGION}.api.aws"

ENV_BASE_URL = "LAUNCH_WITH_AWS_BASE_URL"
ENV_IDC_ISSUER_URL = "LAUNCH_WITH_AWS_IDC_ISSUER_URL"
ENV_SCOPES = "LAUNCH_WITH_AWS_SCOPES"
ENV_REGION = "LAUNCH_WITH_AWS_REGION"

# How each region signal is described to the customer in the upload confirmation.
REGION_SOURCE_LABELS = {
    "explicit": "the region you asked for",
    "environment": f"your {ENV_REGION} setting",
    "saved": "your saved choice",
    "aws-mcp": "your AWS MCP server configuration",
    "aws-profile": "your AWS profile region",
    "default": "the default",
}

SSO_OIDC_REGION = "us-east-1"
IDC_ISSUER_URL = "https://view.awsapps.com/start"

CLIENT_NAME = "Launch with AWS Agent Skill"
SCOPES = ["launch:access"]
TOKEN_EXPIRY_BUFFER_SECS = 300
CALLBACK_TIMEOUT_SECS = 600.0
DEFAULT_TOKEN_LIFETIME_SECS = 28800

# Maximum local session lifetime; re-authentication is required after this.
MAX_SESSION_LIFETIME_SECS = 90 * 24 * 3600  # 90 days

SESSION_DIR = "~/.launch-with-aws"
SESSION_FILE_NAME = "session.json"
# The region the customer confirmed, kept out of the session file so signing out
# does not reset a data-residency choice.
CONFIG_FILE_NAME = "config.json"

AUTH_WAIT_POLL_INTERVAL_SECS = 1.0

REQUEST_TIMEOUT_SECS = 120.0
UPLOAD_TIMEOUT_SECS = 300.0
GITHUB_ZIPBALL_TIMEOUT_SECS = 120.0

DEFAULT_COST_ESTIMATE_REGION = "us-east-1"

# Archive limits, checked against ZIP central-directory metadata (no
# decompression) plus a streamed compressed-size cap.
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024  # 500 MiB compressed
MAX_ARCHIVE_ENTRIES = 100_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB total decompressed
MAX_ENTRY_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MiB per entry
MAX_COMPRESSION_RATIO = 100  # decompressed/compressed per entry

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


# IAM Identity Center issuer hosts accepted for the issuer URL override.
_ALLOWED_ISSUER_HOST_SUFFIXES = (".amazonaws.com", ".awsapps.com")


def validate_issuer_url(url: str) -> str:
    """Validate an IdC issuer URL override, returning it unchanged if allowed.

    Only https URLs whose host is on an allowed issuer domain are accepted.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ConfigError(
            f"Invalid {ENV_IDC_ISSUER_URL}: scheme must be https, got {parsed.scheme!r}. "
            "Refusing to anchor the authentication flow on a non-HTTPS issuer."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ConfigError(f"Invalid {ENV_IDC_ISSUER_URL}: no hostname in {url!r}.")

    if not any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix)
        for suffix in _ALLOWED_ISSUER_HOST_SUFFIXES
    ):
        raise ConfigError(
            f"Invalid {ENV_IDC_ISSUER_URL}: host {hostname!r} is not in the allowed "
            f'issuer domains ({", ".join(_ALLOWED_ISSUER_HOST_SUFFIXES)}). '
            "Only official AWS IAM Identity Center endpoints are permitted."
        )

    return url


def resolve_issuer_url() -> str:
    """Return the IdC issuer URL, honoring a validated env-var override."""
    override = os.environ.get(ENV_IDC_ISSUER_URL)
    if override:
        validated = validate_issuer_url(override)
        logger.warning("Using non-default IdC issuer URL: %s", validated)
        return validated
    return IDC_ISSUER_URL


# ── Local state ──────────────────────────────────────────────────────────


def state_dir() -> str:
    return os.path.expanduser(SESSION_DIR)


def write_private_file(path: str, text: str) -> None:
    """Write text to an owner-only (0600) file in an owner-only directory.

    The write is atomic, so a crash mid-write cannot leave a truncated file.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, stat.S_IRWXU)

    old_umask = os.umask(0o077)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, path)
    finally:
        os.umask(old_umask)


# ── Region selection ─────────────────────────────────────────────────────


@dataclass
class ResolvedRegion:
    """A resolved region and the signal it came from, for the upload prompt."""

    region: str
    source: str

    @property
    def region_name(self) -> str:
        return SUPPORTED_REGIONS[self.region]

    @property
    def source_label(self) -> str:
        return REGION_SOURCE_LABELS[self.source]


def validate_region(region: str) -> str:
    """Return the region unchanged if the service runs migrations there."""
    if region not in SUPPORTED_REGIONS:
        raise ConfigError(
            f"Unsupported region {region!r}. Launch with AWS runs migrations in "
            f'{", ".join(SUPPORTED_REGIONS)}.'
        )
    return region


def base_url_for_region(region: str) -> str:
    """Return the regional API endpoint."""
    return f"https://launch-with-aws.{validate_region(region)}.api.aws"


def _config_file() -> str:
    return os.path.join(state_dir(), CONFIG_FILE_NAME)


def load_saved_region() -> Optional[str]:
    """Return the region confirmed on a previous run, if it is still supported."""
    try:
        with open(_config_file()) as f:
            region = json.load(f).get("region")
    except (OSError, ValueError, AttributeError):
        return None
    return region if region in SUPPORTED_REGIONS else None


def save_region(region: str) -> None:
    """Persist the customer's confirmed region for later runs."""
    validate_region(region)
    write_private_file(_config_file(), json.dumps({"region": region}, indent=2))


_AWS_MCP_HOST_RE = re.compile(r"^aws-mcp\.(?P<region>[a-z0-9-]+)\.api\.aws$")


def region_from_aws_mcp_url(url: str) -> Optional[str]:
    """Return the region an AWS MCP endpoint URL is for, or None if it is not one.

    Anchored on the whole host, so a lookalike domain cannot pass as a region.
    """
    try:
        hostname = urlparse(url).hostname or ""
    except ValueError:
        return None
    match = _AWS_MCP_HOST_RE.match(hostname)
    return match.group("region") if match else None


def _profile_region() -> Optional[str]:
    """Return the AWS region from AWS_REGION, AWS_DEFAULT_REGION, or ~/.aws/config.

    boto3 resolves the last two without credentials. A broken AWS config must not
    block a migration, so any failure just means "no signal".
    """
    # boto3 ignores AWS_REGION, though other AWS SDKs treat it as the standard.
    aws_region = os.environ.get("AWS_REGION")
    if aws_region:
        return aws_region
    try:
        import boto3

        return boto3.Session().region_name
    except Exception:
        logger.debug("Could not read the AWS profile region", exc_info=True)
        return None


def _cell_for_aws_region(aws_region: str) -> str:
    """Map any AWS region to the cell that serves it."""
    return EU_REGION if aws_region.startswith("eu-") else DEFAULT_REGION


def resolve_region(
    explicit: Optional[str] = None, aws_mcp_url: Optional[str] = None
) -> ResolvedRegion:
    """Resolve the region to run a migration in; the first signal found wins.

    The customer confirms whatever this returns before any code is uploaded.
    """
    if explicit:
        return ResolvedRegion(validate_region(explicit), "explicit")

    env_region = os.environ.get(ENV_REGION)
    if env_region:
        return ResolvedRegion(validate_region(env_region), "environment")

    saved = load_saved_region()
    if saved:
        return ResolvedRegion(saved, "saved")

    # Every AWS MCP setup path writes us-east-1, so only an EU endpoint there is a
    # deliberate customer choice; anything else says nothing about them.
    aws_mcp_region = region_from_aws_mcp_url(aws_mcp_url) if aws_mcp_url else None
    if aws_mcp_region and aws_mcp_region.startswith("eu-"):
        return ResolvedRegion(EU_REGION, "aws-mcp")

    profile_region = _profile_region()
    if profile_region:
        return ResolvedRegion(_cell_for_aws_region(profile_region), "aws-profile")

    return ResolvedRegion(DEFAULT_REGION, "default")


class Config:
    """Configuration loaded from environment variables."""

    def __init__(self, region: Optional[str] = None) -> None:
        self.region = validate_region(region) if region else resolve_region().region

        env_url = os.environ.get(ENV_BASE_URL)
        if env_url:
            self.base_url = _validate_base_url(env_url)
            logger.info("Using non-default base URL: %s", self.base_url)
        else:
            self.base_url = base_url_for_region(self.region)


def load_config(region: Optional[str] = None) -> Config:
    return Config(region)
