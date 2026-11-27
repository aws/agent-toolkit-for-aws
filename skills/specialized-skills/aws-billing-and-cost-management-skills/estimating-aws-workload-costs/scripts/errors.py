"""The error contract shared by this skill's scripts.

On failure a script prints {"error": {"code": ..., "message": ...}} on stdout and
exits 1. SKILL.md tells the agent how to read it, so every script reports
failures the same way.
"""

import json


class ScriptError(Exception):
    """A request-level failure, printed as {"error": {"code": ..., "message": ...}}."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code, message):
    """Print a request-level error as JSON on stdout and return exit status 1."""
    print(json.dumps({"error": {"code": code, "message": message}}, indent=2))
    return 1
