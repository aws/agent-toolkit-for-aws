"""Guard: cost completeness is tracked separately from window completeness.

PR #425 Cursor review findings 4 and 5 (reproduced in
.agents/tasks/pr425-cursor-fixes/reproductions.md; design in plan.md Cluster C):

Finding 4 — a full-window usage success does not imply the dollar figure is
known. `metadata.partial_window` only tracks whether the USAGE window itself
is short; it says nothing about whether `cost_report` (the dollar-side call)
succeeded. Before this fix, a `cost_report` failure alongside a fully
successful `usage_report/messages` call produced `partial_window: false` with
no signal that the cost figure is actually missing/stale — downstream readers
had no way to tell "usage known, cost unknown" from "usage and cost both
known". The fix adds `metadata.cost_status` (`complete | partial_window |
cost_unavailable`) to the Anthropic usage-profile schema in both
`discover-anthropic-api.md` copies, threads it through both clouds'
`estimate-ai.md` (token volume still counts toward Part 2; the dollar figure
is excluded from Part 1), `llm-to-bedrock/SKILL.md` Step 1.5's
`usage-baseline.json` schema and SUM step, and
`agents/llm2bedrock-report-generator.md` §6.3's presentation rule.

Finding 5 — OpenRouter BYOK-routed spend can double-count against the same
traffic's direct-provider usage profile. The fix adds
`metadata.cost_provenance` to the OpenRouter usage-profile schema. Originally
this was documented as always `"unknown"` (true per-row BYOK detection was
not feasible from the `/activity` response shape alone). A later revision
(openrouter-byok-detection) adds a new `/analytics/query` capture
(`byok_usage`/`openrouter_usage` per model) that makes real detection
possible: `cost_provenance` is now derived per model
(`usage_by_model[].cost_provenance`) and rolled up to
`metadata.cost_provenance`, using a 4-value enum
(`byok_passthrough|mixed|no_byok|unknown`) — `no_byok` is new, a positive
confirmation of no BYOK overlap, distinct from the no-signal `unknown`. The
matching SUM-discipline exception in `llm-to-bedrock/SKILL.md` Step 1.5 now
reads the per-model field (gated on its presence, for backward compatibility
with profiles written before this change) rather than only the profile-level
field.

These are documentation-contract checks (string/shape assertions against the
markdown), matching the existing `test_decision_gate_wiring.py` /
`test_azure_discover_ordering.py` pattern — this plugin's skill files are
instructions read by an LLM agent, not executable code, so there is no
runtime harness to exercise instead.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

ANTHROPIC_DISCOVER_FILES = [
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md",
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md",
]

OPENROUTER_DISCOVER_FILES = [
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-openrouter-api.md",
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-openrouter-api.md",
]

ESTIMATE_AI_FILES = [
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-ai.md",
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-ai.md",
]

SKILL_MD = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "SKILL.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"


# ---------------------------------------------------------------------------
# Finding 4 — cost_status on the Anthropic usage profile
# ---------------------------------------------------------------------------


def test_both_anthropic_discover_copies_document_cost_status_enum() -> None:
    for f in ANTHROPIC_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "metadata.cost_status" in text, (
            f"{f}: missing metadata.cost_status (finding 4 — cost completeness "
            f"distinct from window completeness)"
        )
        for value in ('"complete"', '"partial_window"', '"cost_unavailable"'):
            assert value in text, (
                f"{f}: cost_status enum value {value} not documented"
            )


def test_both_anthropic_discover_copies_document_cost_unavailable_null_semantics() -> None:
    for f in ANTHROPIC_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "summary.monthly_cost_usd: null" in text, (
            f"{f}: cost_unavailable semantics must set summary.monthly_cost_usd "
            f"to null, never 0 or a stale figure"
        )
        assert "never `0`" in text or "never 0" in text, (
            f"{f}: must explicitly rule out 0 as a stand-in for an unknown cost"
        )


def test_both_anthropic_discover_copies_error_handling_table_sets_cost_unavailable() -> None:
    for f in ANTHROPIC_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        error_handling_idx = text.index("## Error Handling")
        error_table = text[error_handling_idx:]
        assert "cost_unavailable" in error_table, (
            f"{f}: Error Handling table does not mention cost_status: "
            f"cost_unavailable for a cost_report failure"
        )
        assert "cost_report" in error_table, (
            f"{f}: Error Handling table row for cost_report failure is missing"
        )


def test_anthropic_discover_copies_remain_mirrored_for_cost_status_text() -> None:
    # The cost_status block added to both copies must be the IDENTICAL text
    # (modulo nothing — the whole block is provider-name-free), confirming the
    # mirrored-edit discipline the task brief and context.json require for
    # these structurally-duplicated files.
    gcp_text = ANTHROPIC_DISCOVER_FILES[0].read_text(encoding="utf-8")
    azure_text = ANTHROPIC_DISCOVER_FILES[1].read_text(encoding="utf-8")
    marker = "**`metadata.cost_status` — cost completeness, independent of `partial_window`.**"
    assert marker in gcp_text and marker in azure_text
    gcp_block = gcp_text[gcp_text.index(marker):gcp_text.index(marker) + 1200]
    azure_block = azure_text[azure_text.index(marker):azure_text.index(marker) + 1200]
    assert gcp_block == azure_block, (
        "cost_status block text has drifted between the gcp-to-aws and "
        "azure-to-aws discover-anthropic-api.md copies"
    )


# ---------------------------------------------------------------------------
# Finding 4 — threading cost_status through estimate-ai.md (both clouds)
# ---------------------------------------------------------------------------


def test_both_estimate_ai_files_exclude_cost_unavailable_dollars_from_part_1() -> None:
    for f in ESTIMATE_AI_FILES:
        text = f.read_text(encoding="utf-8")
        part1_idx = text.index("## Part 1")
        part2_idx = text.index("## Part 2")
        part1_section = text[part1_idx:part2_idx]
        assert "cost_status" in part1_section, (
            f"{f}: Part 1 does not reference cost_status — a cost_unavailable "
            f"profile must be excluded from the dollar-figure precedence chain"
        )
        assert "cost_unavailable" in part1_section
        assert "exclude it from this SUM" in part1_section or "do NOT rank it" in part1_section or "fall through" in part1_section or "fall straight through" in part1_section or "cover that provider" in part1_section


def test_both_estimate_ai_files_still_count_cost_unavailable_volume_in_part_2() -> None:
    for f in ESTIMATE_AI_FILES:
        text = f.read_text(encoding="utf-8")
        part2_idx = text.index("## Part 2")
        part3_idx = text.index("## Part 3")
        part2_section = text[part2_idx:part3_idx]
        assert "cost_status" in part2_section, (
            f"{f}: Part 2 does not reference cost_status — a cost_unavailable "
            f"profile's token volume must still count toward Part 2"
        )
        assert "cost_unavailable" in part2_section
        assert "does NOT disqualify" in part2_section or "normal" in part2_section


# ---------------------------------------------------------------------------
# Finding 4 — llm-to-bedrock SKILL.md usage-baseline.json schema + SUM step
# ---------------------------------------------------------------------------


def test_skill_md_usage_baseline_schema_has_cost_status_per_window() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert '"cost_status"' in text, (
        "SKILL.md's usage-baseline.json schema example does not include "
        "cost_status in its windows.<provider> entries"
    )
    assert "windows.<provider>.cost_status" in text, (
        "SKILL.md's validation rules do not document windows.<provider>.cost_status"
    )


def test_skill_md_sum_step_excludes_cost_unavailable_dollars() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_idx = text.index("## Step 1.5")
    phase_a_idx = text.index("## Phase A")
    step15_section = text[step15_idx:phase_a_idx]
    assert "cost_status" in step15_section
    assert "cost_unavailable" in step15_section
    assert "EXCLUDE it from this dollar SUM" in step15_section, (
        "Step 1.5's SUM-across-profiles logic does not exclude a "
        "cost_unavailable profile's dollars from the summed baseline"
    )


# ---------------------------------------------------------------------------
# Finding 4 — report-generator §6.3 presentation rule
# ---------------------------------------------------------------------------


def test_report_generator_documents_cost_unavailable_presentation_rule() -> None:
    text = REPORT_GENERATOR.read_text(encoding="utf-8")
    section_idx = text.index("## 6.3")
    next_section_idx = text.index("# 6.4")
    section = text[section_idx:next_section_idx]
    assert "cost_status" in section, (
        "§6.3 does not read windows.<provider>.cost_status before presenting "
        "the source-side dollar comparison"
    )
    assert "cost_unavailable" in section
    assert "unavailable" in section.lower()
    assert "savings" in section.lower()


# ---------------------------------------------------------------------------
# Finding 5 — OpenRouter cost_provenance + BYOK overlap SUM exception
# ---------------------------------------------------------------------------


def test_both_openrouter_discover_copies_document_real_cost_provenance_detection() -> None:
    for f in OPENROUTER_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "metadata.cost_provenance" in text, (
            f"{f}: missing metadata.cost_provenance (finding 5 — BYOK/overlap "
            f"spend provenance)"
        )
        assert "usage_by_model[].cost_provenance" in text, (
            f"{f}: missing the per-model usage_by_model[].cost_provenance field "
            f"(openrouter-byok-detection — per-model is the precise signal the "
            f"llm-to-bedrock consumer needs)"
        )
        assert '"byok_passthrough" | "mixed" | "no_byok" |' in text, (
            f"{f}: cost_provenance enum must document the 4-value set including "
            f"the new no_byok value"
        )
        assert "POST /analytics/query" in text, (
            f"{f}: missing the new /analytics/query capture step that supplies "
            f"the real byok_usage/openrouter_usage detection signal"
        )
        assert "byok_usage" in text and "openrouter_usage" in text, (
            f"{f}: missing the Analytics metrics (byok_usage/openrouter_usage) "
            f"the detection logic classifies on"
        )


def test_openrouter_discover_copies_remain_mirrored_for_cost_provenance_text() -> None:
    gcp_text = OPENROUTER_DISCOVER_FILES[0].read_text(encoding="utf-8")
    azure_text = OPENROUTER_DISCOVER_FILES[1].read_text(encoding="utf-8")
    marker = "**`cost_provenance` — now derived from `/analytics/query`"
    assert marker in gcp_text and marker in azure_text
    gcp_block = gcp_text[gcp_text.index(marker):gcp_text.index(marker) + 1800]
    azure_block = azure_text[azure_text.index(marker):azure_text.index(marker) + 1800]
    assert gcp_block == azure_block, (
        "cost_provenance block text has drifted between the gcp-to-aws and "
        "azure-to-aws discover-openrouter-api.md copies"
    )


def test_both_openrouter_discover_copies_have_fourth_analytics_table_row() -> None:
    for f in OPENROUTER_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "| 4 | `POST /analytics/query`" in text, (
            f"{f}: Step 2c Capture Endpoint Table is missing the 4th row for "
            f"the new /analytics/query capture"
        )
        assert "analytics.json" in text


# ---------------------------------------------------------------------------
# PR #425 review 5475407077, Finding B — Priority Tier dollars excluded from
# cost_report are not allowed to produce a "complete" cost_status.
# ---------------------------------------------------------------------------


def test_both_anthropic_discover_copies_detect_priority_tier_rows() -> None:
    for f in ANTHROPIC_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "service_tier" in text, (
            f"{f}: no service_tier parsing documented — Priority Tier rows "
            f"cannot be detected (finding B)"
        )
        assert '"priority"' in text and '"priority_on_demand"' in text, (
            f"{f}: must check for both priority and priority_on_demand "
            f"service_tier values"
        )


def test_both_anthropic_discover_copies_do_not_mark_priority_tier_as_complete() -> None:
    for f in ANTHROPIC_DISCOVER_FILES:
        text = f.read_text(encoding="utf-8")
        assert "Priority Tier dollars are not in" in text, (
            f"{f}: missing the capture_warnings line for excluded Priority "
            f"Tier dollars (finding B)"
        )
        assert "no Priority Tier usage was detected" in text, (
            f"{f}: the 'complete' branch must require that no Priority Tier "
            f"usage was detected, not just a full window + successful cost_report"
        )


def test_skill_md_sum_step_has_byok_overlap_exception() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_idx = text.index("## Step 1.5")
    phase_a_idx = text.index("## Phase A")
    step15_section = text[step15_idx:phase_a_idx]
    assert "byok_passthrough" in step15_section, (
        "Step 1.5 does not document the BYOK/overlap SUM-discipline exception "
        "for OpenRouter + direct-provider double counting"
    )
    assert "cost_provenance" in step15_section
    assert "openrouter-usage-profile.json" in step15_section


def test_skill_md_step15_consumes_per_model_cost_provenance() -> None:
    """openrouter-byok-detection: Step 1.5's de-dupe exception must read the
    per-model usage_by_model[].cost_provenance field the producer now writes,
    including the new no_byok value, while keeping an explicit old-profile
    (field-absent) fallback path for backward compatibility."""
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_idx = text.index("## Step 1.5")
    phase_a_idx = text.index("## Phase A")
    step15_section = text[step15_idx:phase_a_idx]
    assert "no_byok" in step15_section, (
        "Step 1.5 does not mention no_byok — the new positive-signal "
        "cost_provenance value from the per-model detection"
    )
    assert "usage_by_model[].cost_provenance" in step15_section, (
        "Step 1.5 does not read the per-model usage_by_model[].cost_provenance "
        "field produced by discover-openrouter-api.md Step 3"
    )
    assert "old profile" in step15_section.lower() or "backward compat" in step15_section.lower(), (
        "Step 1.5 must document the backward-compatibility fallback for "
        "OpenRouter profiles written before per-model cost_provenance existed"
    )
