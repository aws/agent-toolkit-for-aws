"""Content lock for references/decision-refs/cost-levers.md.

Cost-optimization levers are the ONLY legal source for discount/lever citations in
agent-advisor estimates and reports. These tests pin the five canonical levers and
verify that estimate.md references cost-levers.md and mentions the drivers[] field.
"""
import pathlib
import re

COST_LEVERS_MD = (pathlib.Path(__file__).parent.parent
                  / "references" / "decision-refs" / "cost-levers.md")
ESTIMATE_MD = (pathlib.Path(__file__).parent.parent
               / "references" / "phases" / "estimate" / "estimate.md")


def _cost_levers_text():
    return COST_LEVERS_MD.read_text()


def _estimate_text():
    return ESTIMATE_MD.read_text()


def test_cost_levers_file_exists():
    assert COST_LEVERS_MD.exists(), COST_LEVERS_MD


def test_only_legal_source_phrase():
    """The doc must state it is the 'only legal source' for levers."""
    text = _cost_levers_text()
    assert "only legal source" in text.lower()


def test_five_levers_present():
    """All five canonical levers must appear in the table."""
    text = _cost_levers_text()
    levers = [
        "Model tier routing",
        "Prompt caching",
        "Batch inference",
        "Scale-to-zero runtimes",
        "Quota scheduling",
    ]
    for lever in levers:
        assert lever in text, f"Lever '{lever}' not found in cost-levers.md"


def test_estimate_references_cost_levers():
    """estimate.md must reference cost-levers.md in its _knowledge frontmatter."""
    text = _estimate_text()
    assert "cost-levers.md" in text


def test_estimate_mentions_drivers():
    """estimate.md must mention the drivers[] field in its steps."""
    text = _estimate_text()
    assert "drivers[]" in text or "drivers[" in text
