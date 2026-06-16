#!/usr/bin/env python3
"""PreToolUse hook: block direct secret fetching from AWS Secrets Manager.

Reads JSON from stdin, checks tool_name and tool_input, and returns
a deny decision if the call would fetch secret values directly.

Use {{resolve:secretsmanager:secret-id:SecretString:key}} with asm-exec instead.
"""

import json
import re
import sys

DENY_MSG = (
    "Direct secret fetching is blocked. "
    "Use {{resolve:secretsmanager:secret-id:SecretString:key}} with asm-exec instead. "
    "Run /aws-secrets-manager for details."
)

SMA_PATTERN = re.compile(
    r'(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|::1):2773/secretsmanager/get'
)

# Match the operation regardless of casing/separators:
# GetSecretValue, get_secret_value, get-secret-value, BatchGetSecretValue, ...
GSV_PATTERN = re.compile(r'(batch[-_]?)?get[-_]?secret[-_]?value', re.I)

# Structured operation names normalized to lowercase, no separators.
GSV_OPERATIONS = ("getsecretvalue", "batchgetsecretvalue")


def _normalize_op(operation):
    """Collapse casing and -/_ separators so GetSecretValue == get-secret-value."""
    return operation.lower().replace("-", "").replace("_", "")


def deny():
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_MSG
        }
    }, sys.stdout)
    sys.exit(0)


def allow():
    sys.exit(0)


def main():
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Check structured AWS tool calls (use_aws or MCP AWS tools)
    if tool_name == "use_aws" or tool_name.startswith("mcp__"):
        service = (tool_input.get("service_name") or tool_input.get("service") or tool_input.get("serviceName") or "").lower()
        operation = tool_input.get("operation_name") or tool_input.get("operation") or tool_input.get("operationName") or ""
        if service == "secretsmanager" and _normalize_op(operation) in GSV_OPERATIONS:
            deny()
        # Fallback: search all string values for secret-fetching patterns
        if GSV_PATTERN.search(json.dumps(tool_input)):
            if "secretsmanager" in json.dumps(tool_input).lower():
                deny()
        # Check run_script tools for secret fetching in code
        if "run_script" in tool_name:
            for key, val in tool_input.items():
                if isinstance(val, str) and GSV_PATTERN.search(val):
                    deny()
            if GSV_PATTERN.search(json.dumps(tool_input)):
                deny()
        allow()

    # Check Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # AWS CLI secret fetching
        if re.search(r'aws\s+secretsmanager\s+(get-secret-value|batch-get-secret-value)', command, re.I):
            deny()
        # Direct SMA access
        if SMA_PATTERN.search(command):
            deny()
        # boto3/SDK secret fetching in scripts
        if GSV_PATTERN.search(command):
            deny()

    allow()


if __name__ == "__main__":
    main()
