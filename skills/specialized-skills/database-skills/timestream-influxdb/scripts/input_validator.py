#!/usr/bin/env python3
"""Validate user-provided inputs before AWS CLI or API calls."""
import re
import sys

VALIDATORS = {
    "instance_name": (
        r"^[a-zA-Z][a-zA-Z0-9-]{0,62}$",
        "Must start with letter, alphanumeric/hyphens, max 63 chars",
    ),
    "instance_type": (
        r"^db\.influx\.(medium|large|x?large|[0-9]+xlarge)$",
        "Must be db.influx.{medium|large|xlarge|Nxlarge}",
    ),
    "region": (r"^[a-z]{2}-[a-z]+-\d$", "Must be valid AWS region format (e.g., us-east-1)"),
    "vpc_id": (r"^vpc-[a-f0-9]{8,17}$", "Must be vpc-{hex}"),
    "subnet_id": (r"^subnet-[a-f0-9]{8,17}$", "Must be subnet-{hex}"),
    "sg_id": (r"^sg-[a-f0-9]{8,17}$", "Must be sg-{hex}"),
    "snapshot_id": (r"^[a-zA-Z][a-zA-Z0-9-]{0,254}$", "Must start with letter, max 255 chars"),
    "storage_gb": (lambda v: 20 <= int(v) <= 16384, "Must be 20-16384"),
}


def validate(key, value):
    if key not in VALIDATORS:
        return True, f"No validator for '{key}'"
    rule = VALIDATORS[key]
    if callable(rule[0]):
        try:
            ok = rule[0](value)
        except (ValueError, TypeError):
            ok = False
    else:
        ok = bool(re.match(str(rule[0]), value))
    return ok, rule[1]


def validate_all(**kwargs):
    errors = []
    for k, v in kwargs.items():
        ok, msg = validate(k, v)
        if not ok:
            errors.append(f"  {k}={v} — {msg}")
    if errors:
        print("Validation FAILED:\n" + "\n".join(errors))
        return False
    print("All inputs valid.")
    return True


if __name__ == "__main__":
    pairs = {}
    for arg in sys.argv[1:]:
        k, v = arg.split("=", 1)
        pairs[k] = v
    sys.exit(0 if validate_all(**pairs) else 1)
