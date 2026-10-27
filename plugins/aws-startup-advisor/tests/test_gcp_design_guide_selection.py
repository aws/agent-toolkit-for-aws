"""Guard: GCP's 'both' design-guide branch selects by actual provider presence
(PR #425 finding 9).

GCP's design-ai.md used to hardcode the 'both' ai_source branch to always load
exactly ai-gemini-to-bedrock.md and ai-openai-to-bedrock.md — but
discover-anthropic-api.md's own Step 4.5 can set ai_source to 'both' when
Anthropic usage joins a Gemini-or-OpenAI codebase, so 'both' never meant
exactly "Gemini+OpenAI". Azure's design-ai.md already handles its own 'both'
branch conditionally (openai guide, plus the anthropic guide when an Anthropic
model is present) — this guards that GCP now mirrors that pattern instead of
hardcoding Gemini+OpenAI.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
GCP_DESIGN_AI = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md"


def test_both_branch_no_longer_hardcodes_gemini_and_openai_only() -> None:
    text = GCP_DESIGN_AI.read_text(encoding="utf-8")
    assert "load both `ai-gemini-to-bedrock.md` and `ai-openai-to-bedrock.md`" not in text, (
        "GCP design-ai.md's 'both' branch still hardcodes exactly "
        "Gemini+OpenAI (finding 9 regression)"
    )


def test_both_branch_selects_guides_from_actual_provider_presence() -> None:
    text = GCP_DESIGN_AI.read_text(encoding="utf-8")
    assert "ai-anthropic-to-bedrock.md" in text, (
        "GCP design-ai.md's 'both' branch never loads the Anthropic guide"
    )
    both_section_start = text.index('- `"both"`')
    both_section = text[both_section_start:both_section_start + 1200]
    assert "ai-gemini-to-bedrock.md" in both_section, (
        "GCP design-ai.md's 'both' branch no longer references the Gemini guide"
    )
    assert "ai-openai-to-bedrock.md" in both_section, (
        "GCP design-ai.md's 'both' branch no longer references the OpenAI guide"
    )
    assert "ai-anthropic-to-bedrock.md" in both_section, (
        "GCP design-ai.md's 'both' branch no longer references the Anthropic "
        "guide in its own selection logic (not just elsewhere in the file)"
    )
    assert "ACTUALLY" in both_section, (
        "GCP design-ai.md's 'both' branch no longer explains it selects "
        "guides based on actual provider presence rather than a fixed pair"
    )
