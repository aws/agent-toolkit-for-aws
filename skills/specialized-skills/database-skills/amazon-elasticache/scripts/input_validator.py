#!/usr/bin/env python3
"""
ElastiCache Input Validator

Validates and sanitizes user-provided values before they are interpolated into
CLI commands. Prevents shell injection and ensures identifiers conform to AWS
naming rules.

Usage (as a library):
    from input_validator import validate_cache_name, sanitize_for_cli, validate_all

    ok, err = validate_cache_name("my-cache")
    safe = sanitize_for_cli("my-cache; rm -rf /")
    errors = validate_all({"cache_name": "my-cache", "region": "us-east-1"})

Usage (standalone -- validates a set of key=value pairs):
    python input_validator.py cache_name=my-cache region=us-east-1 subnet_id=subnet-abc123
"""

from __future__ import annotations

import re
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------
# Each function returns (is_valid: bool, error_message: str | None).
# A None error_message means the value is valid.
# ---------------------------------------------------------------------------


def validate_cache_name(name: str) -> tuple[bool, Optional[str]]:
    """Validate an ElastiCache cache or cluster name.

    Rules:
    - 1 to 40 characters
    - Alphanumeric characters and hyphens only
    - Must start with a letter
    - No consecutive hyphens
    - Must not end with a hyphen

    Note: Serverless cache names must be lowercase. Node-based cluster names
    are case-insensitive (AWS lowercases them). This validator enforces
    lowercase to ensure compatibility with both deployment types.
    """
    if not name:
        return False, "Cache name must not be empty"
    if len(name) > 40:
        return False, f"Cache name must be 1-40 characters (got {len(name)})"
    if not re.match(r'^[a-z]', name):
        return False, "Cache name must start with a lowercase letter (serverless requires lowercase; node-based is case-insensitive but lowercased by AWS)"
    if not re.match(r'^[a-z0-9-]+$', name):
        return False, "Cache name may only contain lowercase alphanumeric characters and hyphens"
    if '--' in name:
        return False, "Cache name must not contain consecutive hyphens"
    if name.endswith('-'):
        return False, "Cache name must not end with a hyphen"
    return True, None


def validate_replication_group_id(rg_id: str) -> tuple[bool, Optional[str]]:
    """Validate a replication group ID.

    Same rules as cache name: 1-40 chars, alphanumeric + hyphens, starts with
    a letter, no consecutive hyphens, no trailing hyphen.
    """
    if not rg_id:
        return False, "Replication group ID must not be empty"
    if len(rg_id) > 40:
        return False, f"Replication group ID must be 1-40 characters (got {len(rg_id)})"
    if not re.match(r'^[a-zA-Z]', rg_id):
        return False, "Replication group ID must start with a letter"
    if not re.match(r'^[a-zA-Z0-9-]+$', rg_id):
        return False, "Replication group ID may only contain alphanumeric characters and hyphens"
    if '--' in rg_id:
        return False, "Replication group ID must not contain consecutive hyphens"
    if rg_id.endswith('-'):
        return False, "Replication group ID must not end with a hyphen"
    return True, None


def validate_subnet_id(subnet_id: str) -> tuple[bool, Optional[str]]:
    """Validate an AWS subnet ID (subnet-<8-17 hex chars>)."""
    if not subnet_id:
        return False, "Subnet ID must not be empty"
    if not re.match(r'^subnet-[0-9a-f]{8,17}$', subnet_id):
        return False, "Subnet ID must match pattern subnet-<8-17 hex characters> (e.g. subnet-0abc1234def56789a)"
    return True, None


def validate_security_group_id(sg_id: str) -> tuple[bool, Optional[str]]:
    """Validate an AWS security group ID (sg-<8-17 hex chars>)."""
    if not sg_id:
        return False, "Security group ID must not be empty"
    if not re.match(r'^sg-[0-9a-f]{8,17}$', sg_id):
        return False, "Security group ID must match pattern sg-<8-17 hex characters> (e.g. sg-0abc1234def56789a)"
    return True, None


def validate_region(region: str) -> tuple[bool, Optional[str]]:
    """Validate an AWS region code (e.g. us-east-1, eu-west-2, ap-southeast-1)."""
    if not region:
        return False, "Region must not be empty"
    if not re.match(r'^[a-z]{2}-[a-z]+-\d+$', region):
        return False, "Region must match AWS region pattern (e.g. us-east-1, eu-west-2)"
    return True, None


def validate_engine_version(version: str) -> tuple[bool, Optional[str]]:
    r"""Validate an engine version string.

    Accepted formats:
    - Major only: "7" (used by serverless MajorEngineVersion)
    - Major.minor: "7.1", "8.2"
    - Major.minor.patch: "7.0.4", "7.1.0"
    """
    if not version:
        return False, "Engine version must not be empty"
    if not re.match(r'^\d+(\.\d+){0,2}$', version):
        return False, "Engine version must match pattern <major>[.<minor>[.<patch>]] (e.g. 7, 7.1, 7.0.4)"
    return True, None


def validate_vpc_id(vpc_id: str) -> tuple[bool, Optional[str]]:
    """Validate an AWS VPC ID (vpc-<8-17 hex chars>)."""
    if not vpc_id:
        return False, "VPC ID must not be empty"
    if not re.match(r'^vpc-[0-9a-f]{8,17}$', vpc_id):
        return False, "VPC ID must match pattern vpc-<8-17 hex characters> (e.g. vpc-0abc1234def56789a)"
    return True, None


def validate_kms_key_id(key_id: str) -> tuple[bool, Optional[str]]:
    """Validate a KMS key ID.

    Accepts either:
    - A UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    - A KMS key ARN: arn:aws:kms:<region>:<account>:key/<key-id>
    - A KMS alias ARN: arn:aws:kms:<region>:<account>:alias/<alias-name>
    """
    if not key_id:
        return False, "KMS key ID must not be empty"

    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    arn_pattern = r'^arn:aws:kms:[a-z0-9-]+:\d{12}:(key|alias)/[a-zA-Z0-9/_-]+$'

    if re.match(uuid_pattern, key_id):
        return True, None
    if re.match(arn_pattern, key_id):
        return True, None

    return False, (
        "KMS key ID must be a UUID (e.g. 12345678-1234-1234-1234-123456789abc) "
        "or a KMS ARN (e.g. arn:aws:kms:us-east-1:123456789012:key/<key-id>)"
    )


def validate_snapshot_name(name: str, serverless: bool = False) -> tuple[bool, Optional[str]]:
    """Validate a snapshot name.

    Rules:
    - 1 to 255 characters for serverless snapshots, 1 to 40 for node-based
    - Alphanumeric characters and hyphens only
    - Must start with a letter
    - No consecutive hyphens
    - Must not end with a hyphen
    """
    if not name:
        return False, "Snapshot name must not be empty"
    max_len = 255 if serverless else 40
    if len(name) > max_len:
        label = "serverless" if serverless else "node-based"
        return False, f"Snapshot name must be 1-{max_len} characters for {label} (got {len(name)})"
    if not re.match(r'^[a-zA-Z]', name):
        return False, "Snapshot name must start with a letter"
    if not re.match(r'^[a-zA-Z0-9-]+$', name):
        return False, "Snapshot name may only contain alphanumeric characters and hyphens"
    if '--' in name:
        return False, "Snapshot name must not contain consecutive hyphens"
    if name.endswith('-'):
        return False, "Snapshot name must not end with a hyphen"
    return True, None


# ---------------------------------------------------------------------------
# CLI sanitization safety net
# ---------------------------------------------------------------------------

# Shell metacharacters that could enable command injection
_SHELL_METACHARACTERS = re.compile(r'[;&|`$(){}!<>\'\"\\\n\r\x00]')


def sanitize_for_cli(value: str) -> str:
    """Strip shell metacharacters from a value as a defense-in-depth safety net.

    This is NOT a substitute for proper validation -- always validate inputs
    first using the validate_* functions. This function provides an additional
    layer of protection by removing characters that could be interpreted by
    a shell if a value is accidentally interpolated into a command string.

    Returns the sanitized string with all shell metacharacters removed.
    """
    return _SHELL_METACHARACTERS.sub('', value)


# ---------------------------------------------------------------------------
# Bulk validation
# ---------------------------------------------------------------------------

# Map of recognized parameter keys to their validator functions
_VALIDATORS = {
    "cache_name": validate_cache_name,
    "replication_group_id": validate_replication_group_id,
    "subnet_id": validate_subnet_id,
    "security_group_id": validate_security_group_id,
    "region": validate_region,
    "engine_version": validate_engine_version,
    "vpc_id": validate_vpc_id,
    "kms_key_id": validate_kms_key_id,
    "snapshot_name": validate_snapshot_name,
}


def validate_all(params: dict) -> list[str]:
    """Validate all recognized keys in a parameter dict.

    Takes a dict like {"cache_name": "my-cache", "region": "us-east-1"} and
    validates every key that has a known validator. Keys not recognized are
    silently skipped (they may be application-specific parameters).

    Returns a list of error messages. An empty list means all recognized
    parameters passed validation.
    """
    errors = []
    for key, value in params.items():
        validator = _VALIDATORS.get(key)
        if validator is None:
            continue
        if not isinstance(value, str):
            errors.append(f"{key}: expected a string, got {type(value).__name__}")
            continue
        is_valid, error_msg = validator(value)  # type: ignore[operator]
        if not is_valid:
            errors.append(f"{key}: {error_msg}")
    return errors


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    """Validate key=value pairs passed on the command line."""
    if len(sys.argv) < 2:
        print("Usage: python input_validator.py key=value [key=value ...]")
        print("Example: python input_validator.py cache_name=my-cache region=us-east-1")
        print()
        print("Recognized keys:", ", ".join(sorted(_VALIDATORS.keys())))
        sys.exit(0)

    params = {}
    for arg in sys.argv[1:]:
        if '=' not in arg:
            print(f"Error: argument '{arg}' is not in key=value format")
            sys.exit(2)
        key, value = arg.split('=', 1)
        params[key] = value

    errors = validate_all(params)

    if errors:
        print("Validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("All inputs valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
