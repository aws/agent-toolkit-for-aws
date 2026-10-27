"""Guard: AI-only "Option C" route label consults the framework on an absent path.

PR #431 reviewer (leon1418) finding 1: when `migration_path` is absent/missing
from `aws-design-ai.json` AND no OpenRouter subroute matched, the dd38bc2 menu
logic in BOTH gcp-to-aws `estimate.md` and azure-to-aws `estimate-assemble.md`
fell straight through to the "direct/gpt-oss/absent -> adapter" fallback and
showed the ADAPTER label. But Generate's framework-based dispatch
(`generate-artifacts-ai.md` Step 0) routes a confirmed gateway/router framework
(`ai_constraints.ai_framework.value` includes `llm_router` / `api_gateway` /
`voice_platform` / `framework`) to Step 3B gateway config, not the adapter — so
the menu label and the artifact Generate emits disagreed for:
    migration_path absent + gateway framework confirmed + no OpenRouter evidence.

These checks assert the added precedence rule is present in BOTH menus (which
mirror each other), and act as regression guards for the dd38bc2 Mantle/Converse
spellings and the OpenRouter-subroute priority ordering. They anchor on stable
substrings so benign rewording does not trip them.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

GCP_ESTIMATE = (
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate.md"
)
AZURE_ESTIMATE_ASSEMBLE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-assemble.md"
)

AI_ONLY_FILES = [GCP_ESTIMATE, AZURE_ESTIMATE_ASSEMBLE]

# The gateway/router framework set that Generate's Step 0 dispatch treats as
# gateway config (generate-artifacts-ai.md Step 0 / generate-ai.md line 22).
GATEWAY_FRAMEWORK_TOKENS = [
    "llm_router",
    "api_gateway",
    "voice_platform",
    "framework",
]


def _ai_only_section(text: str) -> str:
    """Slice the AI-only decision-gate route-resolution block.

    Both files resolve the option-C label starting at an "OpenRouter subroute"
    numbered step and ending before the next top-level heading. Anchor on the
    OpenRouter subroute marker that dd38bc2 introduced.
    """
    start = text.index("OpenRouter subroute")
    # The route resolution lives inside the decision-gate prose; the next "## "
    # heading (or end of file) bounds it generously enough for substring checks.
    tail = text[start:]
    return tail


def test_absent_migration_path_consults_framework_before_adapter() -> None:
    for f in AI_ONLY_FILES:
        section = _ai_only_section(f.read_text(encoding="utf-8"))
        # The precedence rule must reference the confirmed-framework field.
        assert "ai_constraints.ai_framework.value" in section, (
            f"{f.name}: AI-only option-C resolution no longer consults "
            f"preferences.json -> ai_constraints.ai_framework.value for the "
            f"absent-migration_path case (finding 1)"
        )
        # The absent/missing case must be the trigger for the framework consult.
        assert "absent/missing `migration_path`" in section, (
            f"{f.name}: the framework-precedence check is not tied to an "
            f"absent/missing migration_path (finding 1)"
        )
        # All four gateway-framework tokens must appear in the precedence rule.
        for token in GATEWAY_FRAMEWORK_TOKENS:
            assert token in section, (
                f"{f.name}: gateway-framework token '{token}' missing from the "
                f"absent-migration_path precedence check (finding 1)"
            )


def test_framework_consult_mirrors_generate_dispatch() -> None:
    for f in AI_ONLY_FILES:
        section = _ai_only_section(f.read_text(encoding="utf-8"))
        assert "generate-artifacts-ai.md" in section, (
            f"{f.name}: the framework-precedence rule no longer cites "
            f"generate-artifacts-ai.md's Step 0 dispatch as the reason the "
            f"menu label must match the emitted artifact (finding 1)"
        )


def test_dd38bc2_spellings_and_openrouter_priority_preserved() -> None:
    # Regression guard: the fix is an ADDED precedence check, not a rewrite, so
    # the dd38bc2 Mantle/Converse spellings and OpenRouter-subroute priority must
    # survive untouched.
    for f in AI_ONLY_FILES:
        text = f.read_text(encoding="utf-8")
        assert "mantle_openai_responses" in text, (
            f"{f.name}: the Mantle spelling 'mantle_openai_responses' from "
            f"dd38bc2 was lost"
        )
        assert "converse" in text.lower(), (
            f"{f.name}: the Converse client-swap mapping from dd38bc2 was lost"
        )
        section = _ai_only_section(text)
        openrouter_idx = section.index("OpenRouter subroute")
        migration_path_idx = section.index("migration_path")
        assert openrouter_idx < migration_path_idx, (
            f"{f.name}: the OpenRouter subroute no longer takes priority over "
            f"migration_path (dd38bc2 ordering regressed)"
        )
