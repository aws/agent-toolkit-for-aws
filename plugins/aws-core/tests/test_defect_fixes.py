#!/usr/bin/env python3
"""Tests for Defect 1 (asm-exec env-var resolution) and Defect 2 (secret-safety.py false positives).

These tests verify the fixes without requiring actual AWS credentials or a running
Secrets Manager Agent — they mock the resolution layer and test the logic paths.
"""

import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add the paths so we can import the modules
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(PLUGIN_DIR, 'hooks')
SKILLS_DIR = os.path.join(PLUGIN_DIR, 'skills', 'aws-secrets-manager', 'references')

sys.path.insert(0, HOOKS_DIR)
sys.path.insert(0, SKILLS_DIR)


# ==============================================================================
# Defect 1 Tests: asm-exec env-var resolution
# ==============================================================================

class TestAsmExecEnvVarResolution(unittest.TestCase):
    """Verify that asm-exec resolves {{resolve:secretsmanager:...}} in env vars."""

    def _run_asm_exec(self, args, env_override=None):
        """Run asm-exec as a subprocess with controlled environment."""
        asm_exec_path = os.path.join(SKILLS_DIR, 'asm-exec')
        env = os.environ.copy()
        if env_override:
            env.update(env_override)
        # Disable SMA so it doesn't try to connect
        env.pop('AWS_SECRETS_MANAGER_AGENT_ENDPOINT', None)
        result = subprocess.run(
            [sys.executable, asm_exec_path] + args,
            capture_output=True, text=True, env=env, timeout=10
        )
        return result

    def test_env_var_with_resolve_pattern_is_passed_to_child(self):
        """Env vars containing {{resolve:...}} should be resolved before reaching the child.

        Since we don't have a running SMA or MCP endpoint, this test verifies that
        asm-exec ATTEMPTS to resolve env vars (and fails with an error message),
        rather than silently passing the literal string through.
        """
        env = {
            'APP_SECRET': '{{resolve:secretsmanager:test/secret:SecretString:password}}'
        }
        result = self._run_asm_exec(['--', 'echo', 'hello'], env_override=env)
        # With no SMA or MCP available, asm-exec should exit with error
        # (fail closed) rather than passing the unresolved literal through
        self.assertNotEqual(result.returncode, 0,
                          "asm-exec should fail when it can't resolve an env var reference")
        self.assertIn('ERROR', result.stderr,
                     "asm-exec should report an error for unresolvable env var references")

    def test_env_var_without_pattern_passes_through(self):
        """Env vars NOT containing the resolve pattern should pass through unchanged."""
        result = self._run_asm_exec(
            ['--', sys.executable, '-c', 'import os; print(os.environ.get("NORMAL_VAR", ""))'],
            env_override={'NORMAL_VAR': 'hello_world'}
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('hello_world', result.stdout)

    def test_argv_resolution_still_works(self):
        """Argv-based resolution should still attempt to resolve (and fail closed without SMA)."""
        result = self._run_asm_exec([
            '--', 'echo', '{{resolve:secretsmanager:test/secret:SecretString:key}}'
        ])
        # Should fail closed — no SMA available to resolve
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ERROR', result.stderr)


# ==============================================================================
# Defect 2 Tests: secret-safety.py false positives
# ==============================================================================

class TestSecretSafetyHook(unittest.TestCase):
    """Verify that secret-safety.py blocks real secret fetching but allows read-only commands."""

    def _run_hook(self, tool_name, tool_input):
        """Run the hook with given input and return (exit_code, stdout)."""
        hook_path = os.path.join(HOOKS_DIR, 'secret-safety.py')
        input_data = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
        result = subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, text=True, timeout=5
        )
        return result.returncode, result.stdout

    def _is_denied(self, tool_name, tool_input):
        """Returns True if the hook denies the command."""
        _, stdout = self._run_hook(tool_name, tool_input)
        if stdout.strip():
            try:
                output = json.loads(stdout)
                decision = output.get("hookSpecificOutput", {}).get("permissionDecision", "")
                return decision == "deny"
            except json.JSONDecodeError:
                pass
        return False

    # --- Commands that SHOULD be blocked ---

    def test_blocks_aws_cli_get_secret_value(self):
        """AWS CLI get-secret-value should be blocked."""
        self.assertTrue(self._is_denied("Bash", {
            "command": "aws secretsmanager get-secret-value --secret-id my-secret"
        }))

    def test_blocks_aws_cli_batch_get_secret_value(self):
        """AWS CLI batch-get-secret-value should be blocked."""
        self.assertTrue(self._is_denied("Bash", {
            "command": "aws secretsmanager batch-get-secret-value --secret-id-list my-secret"
        }))

    def test_blocks_sma_direct_access(self):
        """Direct SMA URL access should be blocked."""
        self.assertTrue(self._is_denied("Bash", {
            "command": "curl http://localhost:2773/secretsmanager/get?secretId=mysecret"
        }))

    def test_blocks_boto3_inline_call(self):
        """Inline Python with boto3 client.get_secret_value() should be blocked."""
        self.assertTrue(self._is_denied("Bash", {
            "command": "python3 -c \"import boto3; client = boto3.client('secretsmanager'); client.get_secret_value(SecretId='x')\""
        }))

    def test_blocks_node_inline_sdk_call(self):
        """Inline Node.js with GetSecretValueCommand should be blocked."""
        self.assertTrue(self._is_denied("Bash", {
            "command": "node -e \"const { GetSecretValueCommand } = require('@aws-sdk/client-secrets-manager'); new GetSecretValueCommand({SecretId: 'x'})\""
        }))

    def test_blocks_structured_use_aws(self):
        """Structured use_aws tool call for GetSecretValue should be blocked."""
        self.assertTrue(self._is_denied("use_aws", {
            "service_name": "secretsmanager",
            "operation_name": "GetSecretValue",
            "parameters": {"SecretId": "my-secret"}
        }))

    def test_blocks_structured_batch_get(self):
        """Structured use_aws tool call for BatchGetSecretValue should be blocked."""
        self.assertTrue(self._is_denied("use_aws", {
            "service_name": "secretsmanager",
            "operation_name": "BatchGetSecretValue",
            "parameters": {"SecretIdList": ["secret1"]}
        }))

    # --- Commands that SHOULD NOT be blocked (false positive regression tests) ---

    def test_allows_grep_for_pattern(self):
        """grep for GetSecretValue in logs should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "grep -r 'GetSecretValue' ./logs/"
        }))

    def test_allows_rg_search(self):
        """ripgrep for get_secret_value in source should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "rg get_secret_value src/"
        }))

    def test_allows_git_log_search(self):
        """git log searching for GetSecretValue should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "git log -S GetSecretValue --oneline"
        }))

    def test_allows_cat_file(self):
        """cat of a file mentioning the API should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "cat docs/secrets-rotation-runbook.md"
        }))

    def test_allows_gh_issue_create_with_api_name_in_title(self):
        """gh issue create with GetSecretValue in title should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "gh issue create --title 'asm-exec get-secret-value resolution bug' --body 'details'"
        }))

    def test_allows_find_command(self):
        """find command mentioning the pattern should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "find . -name '*get_secret_value*'"
        }))

    def test_allows_echo_command(self):
        """echo mentioning the API should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "echo 'The GetSecretValue API requires permissions'"
        }))

    def test_allows_awk_processing(self):
        """awk processing logs mentioning the pattern should NOT be blocked."""
        self.assertFalse(self._is_denied("Bash", {
            "command": "awk '/GetSecretValue/ {print $0}' cloudtrail.log"
        }))

    # --- Structured tool false-positive regression ---

    def test_allows_mcp_docs_search_mentioning_api(self):
        """MCP tool searching docs for 'secretsmanager GetSecretValue' should NOT be blocked."""
        self.assertFalse(self._is_denied("mcp__docs_search", {
            "query": "secretsmanager GetSecretValue permissions required"
        }))

    def test_allows_use_aws_non_secretsmanager_service(self):
        """use_aws calling a different service should NOT be blocked even if args mention the pattern."""
        self.assertFalse(self._is_denied("use_aws", {
            "service_name": "iam",
            "operation_name": "GetPolicy",
            "parameters": {"PolicyArn": "arn:aws:iam::123:policy/secretsmanager-get-secret-value-policy"}
        }))

    # --- run_script checks ---

    def test_blocks_run_script_with_sdk_call(self):
        """run_script containing an actual SDK call should be blocked."""
        self.assertTrue(self._is_denied("mcp__run_script", {
            "code": "import boto3\nclient = boto3.client('secretsmanager')\nclient.get_secret_value(SecretId='x')"
        }))

    def test_allows_run_script_mentioning_api_without_call(self):
        """run_script that mentions the API name without calling it should NOT be blocked."""
        self.assertFalse(self._is_denied("mcp__run_script", {
            "code": "# This script audits get_secret_value usage\nprint('Checking permissions for GetSecretValue')"
        }))


if __name__ == '__main__':
    unittest.main()
