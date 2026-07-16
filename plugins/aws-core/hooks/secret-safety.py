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

# SDK call invocation shapes — matches actual method calls / constructors, not bare text.
# boto3:  client.get_secret_value(...)
# JS v3:  GetSecretValueCommand(...)
# Generic SDK: (Batch)GetSecretValue(Request|Command)?(...)
SDK_CALL_PATTERN = re.compile(
    r'\.\s*(batch[-_]?)?get[-_]?secret[-_]?value\s*\('       # boto3/ruby/go style
    r'|GetSecretValueCommand\s*\('                            # JS SDK v3
    r'|(Batch)?GetSecretValue(Request|Command)?\s*\(',        # other SDKs
    re.I
)

# Read-only text tools that should never be blocked for merely mentioning an API name.
_READ_ONLY_PREFIXES = (
    'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack',
    'cat', 'less', 'more', 'head', 'tail', 'bat',
    'git', 'gh', 'find', 'ls', 'wc', 'diff',
    'awk', 'sed', 'sort', 'uniq', 'cut', 'tr',
    'echo', 'printf', 'man', 'help',
)

# Interpreter flags that indicate inline code execution.
_INTERPRETER_INLINE_RE = re.compile(
    r'(?:python[23]?|python3\.\d+|node|ruby|perl)\s+(?:-[a-zA-Z]*c|-e)\s'
)

# Shell compound operators that indicate the command has multiple parts.
_COMPOUND_OPERATORS_RE = re.compile(r'[;&|`]|\$\(')


def _normalize_op(operation):
    """Collapse casing and -/_ separators so GetSecretValue == get-secret-value."""
    return operation.lower().replace("-", "").replace("_", "")


def _is_read_only_command(command):
    """Check if the command's leading token is a known read-only text tool."""
    stripped = command.lstrip()
    # Skip common prefixes: env vars (FOO=bar), sudo, env, time, etc.
    while True:
        # Skip env var assignments at the start
        if re.match(r'[A-Za-z_][A-Za-z0-9_]*=\S*\s', stripped):
            stripped = re.sub(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', '', stripped)
            continue
        # Skip common wrapper commands
        if re.match(r'(sudo|env|time|nice|nohup|command|builtin)\s', stripped):
            stripped = re.sub(r'^(sudo|env|time|nice|nohup|command|builtin)\s+', '', stripped)
            continue
        break
    first_token = stripped.split()[0] if stripped.split() else ''
    # Strip path prefix (e.g., /usr/bin/grep -> grep)
    first_token = first_token.rsplit('/', 1)[-1]
    return first_token in _READ_ONLY_PREFIXES


def _has_sdk_call_in_inline_code(command):
    """Check if the command executes inline interpreter code containing an SDK call."""
    if _INTERPRETER_INLINE_RE.search(command):
        return SDK_CALL_PATTERN.search(command)
    return False


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
        # Only deny if tool input contains an actual SDK call shape (not just a mention)
        input_str = json.dumps(tool_input)
        if SDK_CALL_PATTERN.search(input_str):
            if "secretsmanager" in input_str.lower():
                deny()
        allow()

    # Check run_script tools for secret fetching in code
    if "run_script" in tool_name:
        for key, val in tool_input.items():
            if isinstance(val, str) and SDK_CALL_PATTERN.search(val):
                deny()
        allow()

    # Check Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # AWS CLI secret fetching (shape-aware: actual `aws secretsmanager get-secret-value`)
        if re.search(r'aws\s+secretsmanager\s+(get-secret-value|batch-get-secret-value)', command, re.I):
            deny()
        # Direct SMA access (shape-aware: actual URL to the agent)
        if SMA_PATTERN.search(command):
            deny()
        # Skip read-only commands that merely mention the API name,
        # but only for simple commands (no compound operators that could
        # chain a secret-fetching command after the read-only prefix).
        if _is_read_only_command(command) and not _COMPOUND_OPERATORS_RE.search(command):
            allow()
        # SDK call invocations in inline interpreter code
        if _has_sdk_call_in_inline_code(command):
            deny()
        # Piped interpreter execution with SDK calls (e.g., heredoc | python3)
        if SDK_CALL_PATTERN.search(command) and "secretsmanager" in command.lower():
            deny()

    allow()


if __name__ == "__main__":
    main()
