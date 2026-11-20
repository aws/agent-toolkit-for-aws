"""Guard: estimate-assemble.md Step 3a must not emit its own close message.

PR #435 review (databaseId 4242622224, round 4): Step 3a already wrote
DECISION.md and, until this fix, also closed with "Your decision is
saved...". estimate.md's own post-HANDOFF_OK step 4 (added for Finding 6,
databaseId 4240400327) closes with the same sentence immediately
afterward, so the message displayed twice on the normal Azure Option A /
PLAN_OK path. This test counts the completion-message substring across
both files and asserts Step 3a contributes zero of them.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ESTIMATE_MD = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases"
    / "estimate" / "estimate.md"
)
ASSEMBLE_MD = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases"
    / "estimate" / "estimate-assemble.md"
)
CLOSE_SENTENCE = "Your decision is saved at"


def _step_3a_section(text: str) -> str:
    start = text.find("### Step 3a")
    assert start != -1, "estimate-assemble.md: Step 3a section not found"
    end = text.find("\n---", start)
    if end == -1:
        end = text.find("\n## Step 4", start)
    assert end != -1, "estimate-assemble.md: could not bound Step 3a section"
    return text[start:end]


def test_step_3a_does_not_emit_its_own_close() -> None:
    assemble_text = ASSEMBLE_MD.read_text(encoding="utf-8")
    section = _step_3a_section(assemble_text)
    assert CLOSE_SENTENCE not in section, (
        "estimate-assemble.md Step 3a emits its own close message again "
        "('Your decision is saved at ...'); the single close owner must be "
        "estimate.md's post-HANDOFF_OK step 4 (PR #435 review, "
        "databaseId 4242622224)"
    )


def test_estimate_md_step_4_is_the_only_close_owner() -> None:
    estimate_text = ESTIMATE_MD.read_text(encoding="utf-8")
    assert CLOSE_SENTENCE in estimate_text, (
        "estimate.md no longer closes Option A with the decision-saved "
        "sentence; the single close owner's text went missing"
    )
    # The close sentence must appear exactly once across the two files
    # combined on the Option A / PLAN_SKIP path.
    assemble_text = ASSEMBLE_MD.read_text(encoding="utf-8")
    total_occurrences = (
        estimate_text.count(CLOSE_SENTENCE) + assemble_text.count(CLOSE_SENTENCE)
    )
    assert total_occurrences == 1, (
        f"expected exactly one close-message owner across estimate.md + "
        f"estimate-assemble.md, found {total_occurrences}"
    )
