#!/usr/bin/env python3
"""Check the v2 Terraform report before infrastructure Generate completes.

This validates the saved contract, not whether Terraform or policy checks ran.
Callers must retain their command receipts and run independent acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def validation_report_errors(value: dict[str, Any]) -> list[str]:
    """Check the existing runtime v2 envelope, without trusting its verdict."""
    errors = []
    if value.get("$schema") != "validation-report/v2":
        errors.append("$schema must be validation-report/v2")
    status = value.get("status")
    if not isinstance(status, str) or status not in {
        "passed", "passed_degraded_offline", "skipped_user_continue",
        "skipped_user_abort", "policy_failed",
    }:
        errors.append("status is outside the runtime contract")
    if value.get("policy_status") != "POLICY_OK":
        errors.append("Completed infrastructure requires policy_status POLICY_OK")
    if not isinstance(status, str) or status not in {"passed", "passed_degraded_offline", "skipped_user_continue"}:
        errors.append("status does not permit infrastructure completion")
    if type(value.get("attempts")) is not int or value["attempts"] < 0:
        errors.append("attempts must be a nonnegative integer")
    for name in ("errors_found", "errors_fixed", "policy_violations"):
        if not isinstance(value.get(name), list):
            errors.append(f"{name} must be an array")
            continue
        for index, item in enumerate(value[name]):
            prefix = f"{name}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("file", "summary"):
                if not isinstance(item.get(field), str):
                    errors.append(f"{prefix}.{field} must be a string")
            if type(item.get("line")) is not int or item["line"] < 0:
                errors.append(f"{prefix}.line must be a nonnegative integer")
            if item.get("severity") not in ("error", "warning"):
                errors.append(f"{prefix}.severity must be error or warning")
            if name == "errors_found" and isinstance(item.get("summary"), str) and len(item["summary"]) > 200:
                errors.append(f"{prefix}.summary exceeds 200 characters")
            if name == "errors_fixed" and (type(item.get("attempt")) is not int or item["attempt"] < 1):
                errors.append(f"{prefix}.attempt must be a positive integer")
    if value.get("policy_violations") != []:
        errors.append("POLICY_OK requires empty policy_violations")
    if type(value.get("offline_fallback_used")) is not bool or (
        value["offline_fallback_used"] != (status == "passed_degraded_offline")
    ):
        errors.append("offline_fallback_used must match passed_degraded_offline")
    if not isinstance(value.get("terraform_version"), str):
        errors.append("terraform_version must be a string")
    try:
        stamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("not UTC")
    except (KeyError, TypeError, AttributeError, ValueError):
        errors.append("timestamp must be an ISO 8601 UTC timestamp")
    return errors



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.report.read_text(encoding="utf-8"))
        errors = (validation_report_errors(value) if isinstance(value, dict)
                  else ["report must be a JSON object"])
    except (OSError, ValueError):
        errors = ["report is missing, unreadable, or invalid JSON"]
    if errors:
        print("RUNTIME_REPORT_FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("RUNTIME_REPORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
