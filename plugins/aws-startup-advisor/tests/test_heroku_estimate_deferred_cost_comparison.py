"""Guard: a deferred (unmatched) database's Heroku cost can't read as savings.

Review finding (leon1418, PR #434 round 5, databaseId 4242786526,
estimate-cost-engine.md): Discover captures a Heroku Postgres Advanced
add-on's pool-sum cost (e.g. 4x 4G-Performance = $600/mo) into the Heroku
baseline total. Design defers that same database (plan: "advanced" has no
row in postgres-rds-sizing.json), so no AWS service is produced for it. Part
3's cost comparison and `financial_summary` then compare the FULL Heroku
baseline (including the $600 line) against the AWS total (with no line for
that database) — the $600 reads as pure AWS savings with no database
replacement or retained-cost disclosure.

Fix: thread the deferred resource's resource_id from Design into Estimate,
sum any deferred resource's already-priced Heroku cost into
`current_costs.deferred_resource_cost`, and mark the whole-stack comparison
`cost_comparison.comparison_status: "incomplete_unmatched_services"` whenever
that sum is nonzero — propagated into `financial_summary` and the generated
report, with a mandatory caveat beside the savings figure (reusing the
existing baseline_note mandatory-caveat pattern already required in
generate-report.md).

Documentation-contract test (string/shape assertions against the markdown),
matching the existing `test_heroku_postgres_advanced_pricing.py` pattern.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DESIGN_MAPPING = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "design"
    / "design-mapping.md"
)

COST_ENGINE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-cost-engine.md"
)

ESTIMATE_ASSEMBLE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-assemble.md"
)

GENERATE_REPORT = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "generate"
    / "generate-report.md"
)


def test_design_mapping_deferred_entry_carries_resource_id() -> None:
    text = DESIGN_MAPPING.read_text(encoding="utf-8")
    section_idx = text.index("### 2F: Specialist Gate")
    section = text[section_idx:]
    assert '"resource_id"' in section
    assert "`resource_id`" in section
    # Required fields list must name resource_id explicitly.
    required_idx = section.index("**Required fields**")
    required = section[required_idx: required_idx + 1200]
    assert "resource_id" in required


def test_cost_engine_part1b_computes_deferred_resource_cost() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    assert "## Part 1b: Flag Deferred-Resource Cost" in text
    part1b_idx = text.index("## Part 1b: Flag Deferred-Resource Cost")
    part2_idx = text.index("## Part 2: Calculate Projected AWS Costs")
    part1b = text[part1b_idx:part2_idx]
    assert "deferred_resource_cost" in part1b
    assert "deferred_resource_services" in part1b
    assert "deferred[]" in part1b


def test_cost_engine_part3_defines_comparison_status_and_keeps_full_baseline() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    part3_idx = text.index("## Part 3: Cost Comparison")
    part4_idx = text.index("## Part 4: Migration Cost Considerations")
    part3 = text[part3_idx:part4_idx]
    assert "comparison_status" in part3
    assert "incomplete_unmatched_services" in part3
    assert "unmatched_deferred_cost" in part3
    assert "unmatched_deferred_services" in part3
    assert "do not subtract or hide" in part3 or "do **not** subtract or hide" in part3


def test_cost_engine_part8_soft_trigger_table_has_comparison_status_row() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    part8_idx = text.index("## Part 8: Recommendation")
    part8 = text[part8_idx:]
    soft_idx = part8.index("Soft triggers")
    outcome_idx = part8.index("**Outcome derivation:**")
    soft_table = part8[soft_idx:outcome_idx]
    assert "comparison_status ==" in soft_table


def test_estimate_assemble_financial_summary_propagates_comparison_status() -> None:
    text = ESTIMATE_ASSEMBLE.read_text(encoding="utf-8")
    financial_summary_idx = text.index('"financial_summary"')
    section = text[financial_summary_idx: financial_summary_idx + 1500]
    assert "comparison_status" in section


def test_generate_report_renders_unmatched_deferred_caveat_in_exec_costs() -> None:
    text = GENERATE_REPORT.read_text(encoding="utf-8")
    exec_costs_idx = text.index("| `exec-costs`")
    exec_costs_row_end = text.index("\n", exec_costs_idx)
    exec_costs_row = text[exec_costs_idx:exec_costs_row_end]
    assert "comparison_status" in exec_costs_row
    assert "unmatched_deferred_services" in exec_costs_row

    step1_idx = text.index("## Step 1: Gather figures")
    step2_idx = text.index("## Step 2:")
    step1 = text[step1_idx:step2_idx]
    assert "comparison_status" in step1
