"""Shared helpers for the writing-agentcore-policy scripts.

Environment variables read (by name only):
    AGENTCORE_POLICY_STATE_DIR  working-directory session state (default ./.agentcore-policy)
    AGENTCORE_POLICY_HOME       private per-user state such as OAuth tokens (default ~/.agentcore-policy)
boto3 itself reads AWS_PROFILE, AWS_REGION and AWS_DEFAULT_REGION.

Nothing in this module prints. Commands print one JSON object through the entry point.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTROL_SERVICE = "bedrock-agentcore-control"
DEFAULT_STATE_DIR = ".agentcore-policy"

_GATEWAY_ARN = re.compile(
    r"^arn:(?P<partition>aws[a-z-]*):bedrock-agentcore:(?P<region>[a-z0-9-]+):"
    r"(?P<account>\d{12}):gateway/(?P<gateway_id>[A-Za-z0-9][A-Za-z0-9_-]{0,99})$"
)


class SkillError(Exception):
    """An expected failure. The message is shown to the agent; it never carries secrets."""

    def __init__(self, kind: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"kind": self.kind, "message": self.message, **self.details}}


@dataclass(frozen=True)
class GatewayArn:
    arn: str
    partition: str
    region: str
    account: str
    gateway_id: str


def parse_gateway_arn(arn: str) -> GatewayArn:
    match = _GATEWAY_ARN.match(arn.strip()) if isinstance(arn, str) else None
    if match is None:
        raise SkillError(
            "invalid_input",
            "expected a Gateway ARN like "
            "arn:aws:bedrock-agentcore:<region>:<account>:gateway/<gateway-id>",
            input="gateway_arn",
        )
    return GatewayArn(arn=arn.strip(), **match.groupdict())


def missing_dependency(package: str, install: str, needed_for: str) -> SkillError:
    """One wording for every missing package: what is missing, what it is for, how to install.

    The agent relays this to the developer; it never installs software itself.
    """
    return SkillError(
        "missing_dependency",
        f"{package} is missing; it is needed {needed_for}. Install it with `{install}`, "
        "then rerun `doctor`.",
        package=package,
        install=install,
    )


def session(region: str | None = None) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise missing_dependency(
            "boto3", "pip install boto3", "to call AWS (Gateway discovery and policy submission)"
        ) from exc
    sess = boto3.Session(region_name=region) if region else boto3.Session()
    if not sess.region_name:
        raise SkillError(
            "invalid_input",
            "no AWS Region configured; pass --region or set AWS_REGION",
            input="region",
        )
    return sess


def control_client(sess: Any) -> Any:
    from botocore.config import Config

    config = Config(
        retries={"mode": "standard", "max_attempts": 3},
        connect_timeout=5,
        read_timeout=10,
        user_agent_extra="writing-agentcore-policy-skill",
    )
    return sess.client(CONTROL_SERVICE, config=config)


_ERROR_KINDS = {
    "AccessDeniedException": "access_denied",
    "UnauthorizedException": "access_denied",
    "ResourceNotFoundException": "not_found",
    "ThrottlingException": "throttled",
    "ServiceQuotaExceededException": "quota_exceeded",
    "ValidationException": "validation",
    "ConflictException": "conflict",
    "ExpiredToken": "credentials",
    "ExpiredTokenException": "credentials",
    "UnrecognizedClientException": "credentials",
    "InvalidClientTokenId": "credentials",
}


def aws_error(exc: Exception, operation: str) -> SkillError:
    """Map a botocore failure to a SkillError without response bodies or identity text."""
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

    if isinstance(exc, NoCredentialsError):
        return SkillError(
            "credentials",
            "no AWS credentials found; configure a profile (for example `aws sso login`) and retry",
            operation=operation,
        )
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        kind = _ERROR_KINDS.get(code, "aws_error")
        if kind == "validation":
            message = exc.response.get("Error", {}).get("Message", "request rejected")
        elif kind == "credentials":
            message = "AWS credentials are expired or invalid; refresh them and retry"
        else:
            message = f"{operation} failed with {code}"
        return SkillError(kind, message, operation=operation, code=code)
    if isinstance(exc, BotoCoreError):
        return SkillError(
            "aws_error", f"{operation} failed: {type(exc).__name__}", operation=operation
        )
    return SkillError("aws_error", f"{operation} failed", operation=operation)


def state_dir(path: str | None = None) -> Path:
    chosen = path or os.environ.get("AGENTCORE_POLICY_STATE_DIR") or DEFAULT_STATE_DIR
    directory = Path(chosen).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def home_dir() -> Path:
    chosen = os.environ.get("AGENTCORE_POLICY_HOME") or "~/.agentcore-policy"
    directory = Path(chosen).expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def read_json(path: Path, default: Any = None) -> Any:
    """The parsed file, or ``default`` when it does not exist.

    A file that exists but is not valid JSON stops the command with a clear error instead of
    being treated as empty, so a damaged state file (drafts, context) is never overwritten
    with a fresh, empty one.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except ValueError:
        raise SkillError(
            "invalid_input",
            f"{path.name} in {path.parent} is damaged (not valid JSON); move it aside or restore it, "
            "then run the command again",
            file=str(path),
        ) from None


def write_json(path: Path, obj: Any) -> None:
    """Write atomically. Every file is created 0600 (by ``mkstemp``) before any content lands,
    so state files and OAuth tokens are never readable by other users, even briefly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        # mkstemp creates the file 0600 on POSIX (os.fchmod does not exist on Windows).
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def confined_path(path: str, *, input_name: str) -> Path:
    """Resolve a path the agent passed; it must stay inside the working directory.

    ``~`` is not expanded, and the check runs on the fully resolved path (symlinks followed),
    so an absolute path, ``..`` or a link is accepted only when it ends inside the directory
    the developer runs the skill in.
    """
    base = Path.cwd().resolve()
    resolved = (base / Path(path)).resolve()
    if not resolved.is_relative_to(base):
        raise SkillError(
            "invalid_input",
            f"{input_name} must be a path inside the working directory: {path}",
            input=input_name,
        )
    return resolved


def read_input_file(path: str, *, input_name: str) -> str:
    """Read a file the agent wrote in the working directory (statement, params, drafts)."""
    file = confined_path(path, input_name=input_name)
    if not file.is_file():
        raise SkillError("invalid_input", f"{input_name} not found: {path}", input=input_name)
    return file.read_text(encoding="utf-8")


def read_statement_file(path: str) -> str:
    """Read a policy statement the agent wrote to a file (avoids shell quoting)."""
    text = read_input_file(path, input_name="statement_file")
    if not text.strip():
        raise SkillError("invalid_input", "statement file is empty", input="statement_file")
    return text.strip() + "\n"
