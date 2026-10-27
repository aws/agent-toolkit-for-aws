"""Markdown-assertion guard for PR #435 review databaseId 4240400324.

A confirmed route change (mixed -> infra-only, or infra -> AI-only) can leave a
stale `estimation-ai.json` or `estimation-infra.json` on disk from an earlier
pass of Estimate. `emit-plan-json.py`'s writer reads these files by presence
alone, so a stale sibling-route file silently resurrects a figure for a route
that no longer applies (e.g. wrongly selecting FULL scope with a stale AI
estimate). This is a smoke-level substring guard, like
`test_decision_gate_wiring.py` — there is no `.md`-interpreter in this repo to
execute against.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ESTIMATE_ASSEMBLE = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate-assemble.md"
)


def test_azure_estimate_assemble_invalidates_stale_sibling_route_artifact() -> None:
    """A confirmed route change (mixed -> infra-only, or infra -> AI-only) must
    invalidate the now-inactive route's stale cost artifact before plan.json
    export, per PR #435 review databaseId 4240400324."""
    text = ESTIMATE_ASSEMBLE.read_text(encoding="utf-8")
    assert "estimation-ai.json" in text and "stale" in text.lower(), (
        "estimate-assemble.md no longer mentions invalidating a stale estimation-ai.json"
    )
    assert "estimation-infra.json" in text, (
        "estimate-assemble.md no longer covers the infra-side stale-artifact case"
    )
    assert re.search(r"delete|invalidat", text, re.IGNORECASE), (
        "estimate-assemble.md no longer describes deleting/invalidating the stale artifact"
    )
