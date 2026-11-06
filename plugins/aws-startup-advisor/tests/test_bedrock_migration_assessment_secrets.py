"""bedrock-migration-assessment states its secret-file rule before any step that looks at the user's project."""
from __future__ import annotations

from pathlib import Path

BMA = Path(__file__).resolve().parent.parent / "skills" / "bedrock-migration-assessment"
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")
CONTROLLER = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
SCAN = (BMA / "references/phases/discover/discover-app-code.md").read_text(encoding="utf-8")


def test_secret_rule_comes_first() -> None:
    rule = "not even with values redacted or only to list variable names"
    assert rule in SKILL and SKILL.index(rule) < SKILL.index("## Step 0")
    assert CONTROLLER.index("never open `.env*` or other secret files") < CONTROLLER.index("## Step 1")
    assert SCAN.index("**Secret file exclusion (HARD") < SCAN.index("Recursively scan the entire target directory tree")
    assert "A value set only in `.env*` or another secret file is not observed: never open the file to find it." in SCAN
