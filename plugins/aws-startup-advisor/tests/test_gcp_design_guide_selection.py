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
