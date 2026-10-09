"""Guard: Azure's partial-provider volume exception matches GCP's, and
Clarify's Q3 checks provenance before trusting a merged current_costs figure.

PR #425 Cursor review findings 13 and 14 (reproduced in
.agents/tasks/pr425-cursor-fixes/reproductions.md; design in plan.md
Cluster I):

Finding 13 — Azure's `estimate-ai.md` Part 2 partial-window exception used
to just say "use the tier table" for a partial provider's portion, with no
caveat that the tier table (when set by Clarify's auto-resolve) was derived
by summing ONLY the full-window profile(s) of a DIFFERENT provider — using
it for an unrelated partial provider's portion fabricates a volume that was
never observed for that provider. GCP's `estimate-ai.md` already had the
correct "treat as unresolved... scenario rows" language; this fix ports it
into Azure's file verbatim (adapting provider names/cross-references only).

Finding 14 — Clarify's Q3 primary (non-fallback) branch in
`clarify-ai-only.md` used to read `current_costs.monthly_ai_spend` straight
from `ai-workload-profile.json` with no partial-window/cost-completeness
check at all — only the `else sum` fallback branch had that check. Since
Discover's Step 4 merge writes `current_costs.monthly_ai_spend`
unconditionally from a usage profile's `summary.monthly_cost_usd`
(partial-window or not), a 2-day partial capture's raw dollar figure could
flow straight through Q3's primary branch untouched. The fix makes Q3's
primary branch follow `current_costs.source`/`breakdown[]` back to the
originating profile(s) and check each contributor's `partial_window`/
`cost_status` before trusting the figure — which requires Discover's own
merge to stamp those fields onto `current_costs`/`breakdown[]` entries in
the first place (both Anthropic copies and Azure's OpenAI copy).

These are documentation-contract checks (string/shape assertions against the
markdown), matching the existing `test_cost_completeness.py` /
`test_azure_discover_ordering.py` pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _normalize(text: str) -> str:
    """Collapse hard-wrapped markdown prose to single spaces so a multi-word
    phrase can be matched regardless of where the source file wraps lines."""
    return re.sub(r"\s+", " ", text)

AZURE_ESTIMATE_AI = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-ai.md"
)
GCP_ESTIMATE_AI = (
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-ai.md"
)
AZURE_CLARIFY_AI_ONLY = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "clarify"
    / "clarify-ai-only.md"
)
GCP_DISCOVER_ANTHROPIC = (
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md"
)
AZURE_DISCOVER_ANTHROPIC = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md"
)
AZURE_DISCOVER_OPENAI = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-openai-api.md"
)


def test_azure_estimate_ai_has_ported_unresolved_scenario_rows_language() -> None:
    text = _normalize(AZURE_ESTIMATE_AI.read_text(encoding="utf-8"))
    assert "Do NOT fall back to the" in text and "tier table for the partial profile's portion" in text, (
        "Azure's estimate-ai.md Part 2 is missing the ported 'do NOT fall back to the "
        "tier table' caveat from GCP's equivalent exception clause"
    )
    assert "treat the partial profile's portion as **unresolved**" in text
    assert "scenario rows" in text and "not derived from the other provider's volume" in text


def test_azure_estimate_ai_no_longer_unconditionally_directs_to_tier_table() -> None:
    text = _normalize(AZURE_ESTIMATE_AI.read_text(encoding="utf-8"))
    # The old thin clause ended right after "Use the tier table (from `ai_token_volume`)
    # for a profile with no full-window data" with no caveat about whose volume that tier
    # represents. The ported text must now explain WHY the tier can't be borrowed.
    assert "when set by Clarify's auto-resolve" in text
    assert "was derived by summing ONLY the full-window" in text


def test_azure_and_gcp_estimate_ai_partial_provider_exception_match_in_substance() -> None:
    azure_text = _normalize(AZURE_ESTIMATE_AI.read_text(encoding="utf-8"))
    gcp_text = _normalize(GCP_ESTIMATE_AI.read_text(encoding="utf-8"))
    shared_phrases = [
        "Do NOT fall back to the",
        "tier table for the partial profile's portion",
        "was derived by summing ONLY the full-window",
        "treat the partial profile's portion as **unresolved**",
        "plus explicit low/medium/high scenario rows",
        "scenario for the partial provider's portion, not derived from the other provider's volume",
    ]
    for phrase in shared_phrases:
        assert phrase in azure_text, f"Azure estimate-ai.md missing ported phrase: {phrase!r}"
        assert phrase in gcp_text, f"GCP estimate-ai.md missing reference phrase: {phrase!r}"


def test_clarify_q3_first_branch_checks_provenance_before_auto_resolving() -> None:
    text = AZURE_CLARIFY_AI_ONLY.read_text(encoding="utf-8")
    q3_idx = text.index("Q3 — Monthly AI spend on Azure OpenAI / OpenAI?")
    q4_idx = text.index("Q4 — Cross-cloud API call concerns")
    q3_section = text[q3_idx:q4_idx]

    # The primary (first) branch must now follow current_costs.source/breakdown[] back to
    # the contributing profile(s) rather than trusting monthly_ai_spend unconditionally.
    assert "current_costs.source" in q3_section
    assert "breakdown[]" in q3_section
    assert "partial_window" in q3_section
    assert "cost_status" in q3_section
    assert "do NOT auto-resolve" in q3_section or "do NOT trust it blindly" in q3_section


def test_clarify_q3_falls_through_to_asking_normally_when_all_contributors_partial() -> None:
    text = AZURE_CLARIFY_AI_ONLY.read_text(encoding="utf-8")
    q3_idx = text.index("Q3 — Monthly AI spend on Azure OpenAI / OpenAI?")
    q4_idx = text.index("Q4 — Cross-cloud API call concerns")
    q3_section = text[q3_idx:q4_idx]
    assert "fall through to asking normally" in q3_section or "ask normally" in q3_section


def test_discover_merge_stamps_partial_window_and_cost_status_onto_current_costs() -> None:
    for path in (GCP_DISCOVER_ANTHROPIC, AZURE_DISCOVER_ANTHROPIC, AZURE_DISCOVER_OPENAI):
        text = path.read_text(encoding="utf-8")
        step4_idx = text.index("## Step 4: Merge into the AI Workload Profile")
        # Scope the search to the current_costs merge sub-section only.
        current_costs_idx = text.index("current_costs", step4_idx)
        section = text[current_costs_idx : current_costs_idx + 2500]
        assert '"partial_window":' in section, (
            f"{path.name}: current_costs merge does not stamp partial_window onto the "
            f"no-breakdown or breakdown[] entry"
        )
        assert '"cost_status":' in section, (
            f"{path.name}: current_costs merge does not stamp cost_status onto the "
            f"no-breakdown or breakdown[] entry"
        )


def test_anthropic_discover_copies_remain_mirrored_after_this_fix() -> None:
    """Both Anthropic discover-*-api.md copies must still differ only in the documented
    provider-name/wording substitutions, not in the shape of the partial_window/cost_status
    stamping this fix added to both."""
    gcp_text = GCP_DISCOVER_ANTHROPIC.read_text(encoding="utf-8")
    azure_text = AZURE_DISCOVER_ANTHROPIC.read_text(encoding="utf-8")

    for marker in ('"partial_window":', '"cost_status":'):
        assert gcp_text.count(marker) == azure_text.count(marker), (
            f"{marker!r} appears a different number of times in the GCP vs Azure "
            f"Anthropic discover copies — mirror edit likely incomplete"
        )
