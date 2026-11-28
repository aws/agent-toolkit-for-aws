#!/usr/bin/env python3
"""Smoke-test deployed Lambda evaluators to verify imports load correctly.

Invokes each Lambda with an empty payload and exits 1 if any fails to import or invoke.

Usage:
    python3 smoke_test_lambda.py --project SafetyABC1 --evaluator deepeval_BiasMetric
    python3 smoke_test_lambda.py --project SafetyABC1 --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.config import Config

# Put scripts/ on sys.path so sibling modules resolve with static imports whether the package
# is installed or the skill directory is copied standalone. Dynamic import is not allowed.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from names import lambda_function_name  # noqa: E402


def smoke_test_one(lambda_client, function_name: str) -> tuple[bool, str]:
    """Invoke a single Lambda with empty payload; return (ok, message)."""
    try:
        resp = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({"session_spans": []}).encode(),
        )
        payload = json.loads(resp["Payload"].read())

        if "errorMessage" in payload:
            err = payload["errorMessage"]
            err_type = payload.get("errorType", "")
            # Match on errorType, not just "No module named": a too-low SDK pin raises
            # ImportError and a truncated handler raises SyntaxError.
            _IMPORT_FAILURES = (
                "Runtime.ImportModuleError",
                "ModuleNotFoundError",
                "ImportError",
                "SyntaxError",
            )
            if any(t in err_type for t in _IMPORT_FAILURES) or "No module named" in err:
                return False, f"BUNDLING FAILED ({err_type or 'no errorType'}): {err}"
            # Any other error is expected with empty input and shows the handler imported.
            return True, f"imports OK (runtime error expected with empty input: {err[:80]})"

        return True, f"imports OK: {json.dumps(payload)[:100]}"
    except Exception as e:
        return False, f"INVOKE ERROR: {e}"


def find_project_lambdas(lambda_client, project: str) -> list[str]:
    """Find all Lambda functions this project's CDK stack created."""
    # A prefix, not a substring: one project's name can occur inside another's.
    prefix = lambda_function_name(project, "")
    functions = []
    paginator = lambda_client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            if name.startswith(prefix):
                functions.append(name)
    return sorted(functions)


def main():
    parser = argparse.ArgumentParser(description="Smoke-test Lambda evaluator imports")
    parser.add_argument("--project", required=True, help="Project name (from names.json)")
    parser.add_argument("--evaluator", help="Specific evaluator name to test")
    parser.add_argument("--all", action="store_true", help="Test all Lambdas for this project")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    # A cold 200MB+ bundle can take 60-120s to start, beyond boto3's 60s default read timeout.
    lambda_client = boto3.client(
        "lambda",
        region_name=args.region,
        config=Config(read_timeout=300, retries={"max_attempts": 0}),
    )

    if args.evaluator:
        fn_name = lambda_function_name(args.project, args.evaluator)
        print(f"Testing: {fn_name}")
        ok, msg = smoke_test_one(lambda_client, fn_name)
        print(f"  {msg}")
        sys.exit(0 if ok else 1)

    elif args.all:
        functions = find_project_lambdas(lambda_client, args.project)
        if not functions:
            print(f"ERROR: no Lambda functions found matching project '{args.project}'")
            sys.exit(1)

        print(f"Found {len(functions)} Lambda(s) for project {args.project}:")
        all_ok = True
        for fn_name in functions:
            ok, msg = smoke_test_one(lambda_client, fn_name)
            status = "✓" if ok else "✗"
            print(f"  {status} {fn_name}: {msg}")
            if not ok:
                all_ok = False

        if all_ok:
            print(f"\nALL {len(functions)} LAMBDAS OK")
        else:
            print("\nFAILED: some Lambdas have import errors. Fix with update_function_code().")

        sys.exit(0 if all_ok else 1)

    else:
        parser.error("Specify --evaluator <name> or --all")


if __name__ == "__main__":
    main()
