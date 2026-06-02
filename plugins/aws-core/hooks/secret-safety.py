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
        service = tool_input.get("service_name", tool_input.get("service", ""))
        operation = tool_input.get("operation_name", tool_input.get("operation", ""))
        if service == "secretsmanager" and operation in (
            "get-secret-value", "batch-get-secret-value"
        ):
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

    allow()


if __name__ == "__main__":
    main()
