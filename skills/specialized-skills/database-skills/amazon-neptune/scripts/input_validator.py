#!/usr/bin/env python3
"""
Neptune Skill — Input Validator

Validates user-supplied values before any create/modify/delete operation.
Run before write-path CLI, boto3, CDK, or MCP calls.

Usage:
    python3 scripts/input_validator.py cluster_id=prod-graph region=us-east-1 vpc_id=vpc-0abc123
    python3 scripts/input_validator.py --help

As library:
    from scripts.input_validator import validate_all, ValidationError
    validate_all(cluster_id="prod-graph", region="us-east-1")
"""

import re
import sys


class ValidationError(Exception):
    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(self.report())

    def report(self) -> str:
        return "\n".join(f"  ❌ {e}" for e in self.errors)


# Patterns
CLUSTER_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9\-]{0,62}$")
GRAPH_ID_RE = re.compile(r"^g-[a-z0-9]{10,}$")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d+$")
VPC_ID_RE = re.compile(r"^vpc-[0-9a-f]{8,17}$")
SUBNET_ID_RE = re.compile(r"^subnet-[0-9a-f]{8,17}$")
SG_ID_RE = re.compile(r"^sg-[0-9a-f]{8,17}$")
KMS_KEY_RE = re.compile(
    r"^(arn:aws(?:-cn|-us-gov)?:kms:[a-z0-9\-]+:\d{12}:key/[0-9a-f\-]+|[0-9a-f\-]{36})$"
)
IAM_ROLE_RE = re.compile(r"^arn:aws(?:-cn|-us-gov)?:iam::\d{12}:role/.+$")
S3_URI_RE = re.compile(r"^s3://[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9](/.+)?$")
SNAPSHOT_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9\-]{0,254}$")

MIN_PROVISIONED_MEMORY = 16  # m-NCU (CreateGraph API minimum)
MAX_PROVISIONED_MEMORY = 24576  # m-NCU (CreateGraph API maximum)


def validate_cluster_id(value: str) -> str | None:
    if not CLUSTER_ID_RE.match(value):
        return f"cluster_id '{value}' invalid. Must start with letter, alphanumeric + hyphens, max 63 chars."
    return None


def validate_graph_id(value: str) -> str | None:
    if not GRAPH_ID_RE.match(value):
        return f"graph_id '{value}' invalid. Must match 'g-' followed by lowercase alphanumeric (e.g., g-abc123def4)."
    return None


def validate_region(value: str) -> str | None:
    if not REGION_RE.match(value):
        return f"region '{value}' invalid. Expected format: us-east-1, eu-west-2, etc."
    return None


def validate_vpc_id(value: str) -> str | None:
    if not VPC_ID_RE.match(value):
        return f"vpc_id '{value}' invalid. Expected format: vpc-0abc12345def67890."
    return None


def validate_subnet_ids(values) -> list:
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    errors = []
    for v in values:
        if not SUBNET_ID_RE.match(v):
            errors.append(f"subnet_id '{v}' invalid. Expected format: subnet-0abc12345def67890.")
    return errors


def validate_security_group_ids(values) -> list:
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    errors = []
    for v in values:
        if not SG_ID_RE.match(v):
            errors.append(
                f"security_group_id '{v}' invalid. Expected format: sg-0abc12345def67890."
            )
    return errors


def validate_kms_key(value: str) -> str | None:
    if not KMS_KEY_RE.match(value):
        return f"kms_key '{value}' invalid. Expected KMS key ARN or UUID."
    return None


def validate_iam_role(value: str) -> str | None:
    if not IAM_ROLE_RE.match(value):
        return (
            f"iam_role '{value}' invalid. Expected format: arn:aws:iam::123456789012:role/RoleName."
        )
    return None


def validate_s3_uri(value: str) -> str | None:
    if not S3_URI_RE.match(value):
        return f"s3_uri '{value}' invalid. Expected format: s3://bucket-name/path/."
    return None


def validate_snapshot_id(value: str) -> str | None:
    if not SNAPSHOT_ID_RE.match(value):
        return f"snapshot_id '{value}' invalid. Must start with letter, max 255 chars."
    return None


def validate_provisioned_memory(value) -> str | None:
    try:
        mem = int(value)
    except (ValueError, TypeError):
        return f"provisioned_memory '{value}' invalid. Must be an integer."
    if mem < MIN_PROVISIONED_MEMORY or mem > MAX_PROVISIONED_MEMORY:
        return f"provisioned_memory {mem} invalid. Valid range: {MIN_PROVISIONED_MEMORY}-{MAX_PROVISIONED_MEMORY} m-NCU."
    return None


VALIDATORS = {
    "cluster_id": validate_cluster_id,
    "graph_id": validate_graph_id,
    "region": validate_region,
    "vpc_id": validate_vpc_id,
    "kms_key": validate_kms_key,
    "iam_role": validate_iam_role,
    "s3_uri": validate_s3_uri,
    "snapshot_id": validate_snapshot_id,
    "provisioned_memory": validate_provisioned_memory,
}

LIST_VALIDATORS = {
    "subnet_ids": validate_subnet_ids,
    "security_group_ids": validate_security_group_ids,
}


def validate_all(**kwargs) -> None:
    errors = []
    for key, value in kwargs.items():
        if value is None:
            continue
        if key in VALIDATORS:
            err = VALIDATORS[key](str(value))
            if err:
                errors.append(err)
        elif key in LIST_VALIDATORS:
            errors.extend(LIST_VALIDATORS[key](value))
        else:
            errors.append(
                f"Unknown validator key: '{key}'. Valid keys: {sorted(list(VALIDATORS) + list(LIST_VALIDATORS))}"
            )
    if errors:
        raise ValidationError(errors)


def main():
    if "--help" in sys.argv or len(sys.argv) < 2:
        print("Usage: python3 scripts/input_validator.py key=value [key=value ...]")
        print(f"Valid keys: {sorted(list(VALIDATORS) + list(LIST_VALIDATORS))}")
        sys.exit(0)

    kwargs = {}
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"Invalid argument: {arg}. Use key=value format.")
            sys.exit(1)
        key, value = arg.split("=", 1)
        kwargs[key] = value

    try:
        validate_all(**kwargs)
        print("✅ All validations passed.")
    except ValidationError as e:
        print("Validation failed:")
        print(e.report())
        sys.exit(1)


if __name__ == "__main__":
    main()
