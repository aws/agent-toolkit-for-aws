"""The web handoff of each migration skill requests the version-2 plan export.

Version 2 carries the retained cost inputs AWS Startup Advisor needs to build the
cost estimate CSV of an imported plan. The emitter defaults to version 1, so a
handoff command without the option exports a plan that gets no CSV.
"""
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HANDOFFS = [
    "skills/gcp-to-aws/references/phases/estimate/estimate.md",
    "skills/gcp-to-aws/references/phases/generate/generate.md",
    "skills/heroku-to-aws/references/phases/estimate/estimate-assemble.md",
    "skills/heroku-to-aws/references/phases/generate/generate-assemble.md",
    "skills/azure-to-aws/references/phases/estimate/estimate.md",
    "skills/azure-to-aws/references/phases/generate/generate.md",
]


@pytest.mark.parametrize("handoff", HANDOFFS)
def test_handoff_command_requests_version_two(handoff: str) -> None:
    commands = [
        line for line in (PLUGIN / handoff).read_text(encoding="utf-8").splitlines()
        if "emit-plan-json.py" in line and "--migration-dir" in line and "--capture-inputs" not in line
    ]
    assert len(commands) == 1, f"{handoff}: expected one handoff command, found {len(commands)}"
    assert "--schema-version 2" in commands[0], f"{handoff}: the handoff command does not request version 2"
