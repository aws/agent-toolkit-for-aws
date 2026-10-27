"""Guard: PR #436 round-4 Finding 3 — §6.3 must read capture_warnings independently
of the partial-window and cost_unavailable gates, and must not print an unqualified
savings/premium percentage when a full-window, available-cost baseline still carries
a capture_warnings entry (e.g. an excluded mixed OpenRouter row, or a model whose
cost_provenance resolved "uncertain")."""
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"


def test_section_6_3_reads_capture_warnings_independently() -> None:
    text = REPORT_GENERATOR.read_text(encoding="utf-8")
    idx = text.index("## 6.3 Sum token usage")
    next_idx = text.index("The migration plan may map multiple source models")
    section = text[idx:next_idx]
    assert "`capture_warnings`" in section
    assert "independently of the two checks above" in section
    assert "do NOT print an unqualified savings/premium percentage" in section


def test_full_window_available_cost_baseline_with_mixed_exclusion_is_qualified() -> None:
    """Simulates the reviewer's scenario: full window, available cost, but a
    capture_warnings entry from an excluded mixed OpenRouter row. The gate from
    the fix must flag this baseline for qualification/suppression."""
    baseline = {
        "summary": {"monthly_cost_usd_is_blended_estimate": False, "monthly_cost_usd": 500.0},
        "windows": {"openrouter": {"cost_status": "complete", "partial_window": False}},
        "capture_warnings": [
            "claude-sonnet-5 classified mixed (BYOK + independent OpenRouter usage) — "
            "excluded entirely to avoid double-counting the BYOK portion, but this also "
            "drops its independent OpenRouter-funded usage from the baseline, which is "
            "NOT reflected in the figure above."
        ],
    }

    def should_print_unqualified_savings_pct(baseline: dict) -> bool:
        if baseline["summary"]["monthly_cost_usd_is_blended_estimate"]:
            return False
        if any(w["cost_status"] == "cost_unavailable" for w in baseline["windows"].values()):
            return False
        if baseline["capture_warnings"]:
            return False
        return True

    # Sanity: the OLD two-gate-only logic (ignoring capture_warnings) would have
    # allowed an unqualified percentage here — that was the bug.
    old_gate_allows = (
        not baseline["summary"]["monthly_cost_usd_is_blended_estimate"]
        and not any(w["cost_status"] == "cost_unavailable" for w in baseline["windows"].values())
    )
    assert old_gate_allows is True, "sanity: old two-gate logic missed this case"

    assert should_print_unqualified_savings_pct(baseline) is False, (
        "a full-window, available-cost baseline with a non-empty capture_warnings "
        "must not get an unqualified savings/premium percentage"
    )


def test_empty_capture_warnings_still_allows_unqualified_percentage() -> None:
    """Sanity: the new gate must not become a universal suppressor — a baseline
    with no capture_warnings, full window, and available cost should still get an
    unqualified percentage (otherwise the fix would be a behavior regression, not
    a targeted disclosure gate)."""
    baseline = {
        "summary": {"monthly_cost_usd_is_blended_estimate": False},
        "windows": {"openrouter": {"cost_status": "complete"}},
        "capture_warnings": [],
    }

    def should_print_unqualified_savings_pct(baseline: dict) -> bool:
        if baseline["summary"]["monthly_cost_usd_is_blended_estimate"]:
            return False
        if any(w["cost_status"] == "cost_unavailable" for w in baseline["windows"].values()):
            return False
        if baseline["capture_warnings"]:
            return False
        return True

    assert should_print_unqualified_savings_pct(baseline) is True
