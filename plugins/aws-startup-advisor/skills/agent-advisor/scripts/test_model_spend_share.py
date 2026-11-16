"""Contract for B5 (#566 feedback F5): model spend is sized from usage volume, its share of the
estimate is always reported, and the estimate and report lead with it when it dominates.

Estimate runs in the LLM layer, so these tests pin the phase docs, the worked example and the
seed schema that the phase follows.
"""
import json
import pathlib
import re

import jsonschema
import pytest

import scoring

SKILL = pathlib.Path(__file__).parent.parent
PHASES = SKILL / "references" / "phases"
ESTIMATE_MD = PHASES / "estimate" / "estimate.md"
CLARIFY = PHASES / "clarify"
GENERATE_REPORT_MD = PHASES / "generate" / "generate-report.md"
RECOMMENDATION_DOC_MD = SKILL / "references" / "output-templates" / "recommendation-doc.md"
COST_LEVERS_MD = SKILL / "references" / "decision-refs" / "cost-levers.md"
SEED_SCHEMA = pathlib.Path(__file__).parent / "schemas" / "seed.json"

TOKEN_LEVERS = (
    "Model tier routing (Sonnet→Haiku for triage/simple items)",
    "Prompt caching",
    "Batch inference",
)


def _flat(path):
    return " ".join(path.read_text().split())


def _estimate_example():
    text = ESTIMATE_MD.read_text()
    step5 = text[text.index("## Step 5"):]
    block = re.search(r"```json\n(.*?)\n```", step5, re.DOTALL).group(1)
    return json.loads(block)


def _midpoint(band):
    low, high = (float(x) for x in band.split("-"))
    return (low + high) / 2


# --- Estimate ---------------------------------------------------------------------------------

def test_estimate_example_share_matches_its_own_bands():
    example = _estimate_example()
    share = _midpoint(example["total_model"]) / _midpoint(example["total_monthly_magnitude_usd"])
    assert example["model_share_of_total"] == round(round(share / 0.05) * 0.05, 2)
    assert example["model_spend_dominates"] is (example["model_share_of_total"] > 0.5)


def test_estimate_example_note_leads_with_dominance_when_it_dominates():
    example = _estimate_example()
    assert example["model_spend_dominates"] is True
    assert example["note"].startswith("Model spend dominates this estimate")


def test_estimate_defines_share_threshold_and_null_rule():
    est = _flat(ESTIMATE_MD)
    assert "`model_spend_dominates` is evaluated on the rounded share: `true` when it is above 0.5" in est
    assert "`null` only when `total_model` is `null`" in est
    assert "`false` when the share is `null`" in est


def test_estimate_share_survives_unverified_components_and_counts_system_lines():
    est = _flat(ESTIMATE_MD)
    rule = est[est.index("**Model spend share (always emitted).**"):]
    rule = rule[:rule.index("Single-unit runs")]
    # An unverified compute line must not hide a model-dominated bill.
    assert "+ unverified" in rule and "numeric part" in rule
    # The denominator is the written total, system-level lines included.
    assert "including any system-level line" in rule
    assert "evaluated on the rounded share" in rule


def test_estimate_sizes_model_tokens_from_usage_volume_with_a_stated_default():
    est = _flat(ESTIMATE_MD)
    assert "answers.json.units[<unit_id>].usage_volume" in est
    for default in ("1,000 sessions", "20,000 input", "2,000 output"):
        assert default in est, default
    assert "assumed (not answered)" in est


def test_estimate_postcondition_requires_the_share_fields():
    assertion = next(line for line in ESTIMATE_MD.read_text().splitlines()
                     if line.strip().startswith("- _assert:"))
    for field in ("model_share_of_total", "model_spend_dominates", "usage_volume"):
        assert field in assertion, field


def test_dominant_driver_levers_are_real_cost_levers():
    est, levers = _flat(ESTIMATE_MD), COST_LEVERS_MD.read_text()
    rule = est[est.index("When `model_spend_dominates` is true (Step 5)"):]
    rule = rule[:rule.index("latency tolerance")]
    for lever in TOKEN_LEVERS:
        assert f'"{lever}"' in rule, lever
        assert f"| {lever}" in levers, lever


# --- Generate ---------------------------------------------------------------------------------

def test_report_leads_the_cost_section_with_the_dominance_callout():
    report = GENERATE_REPORT_MD.read_text()
    section = report[report.index("Cost summary</h2>"):report.index("Per-{{ UNITS.length")]
    assert "{{ IF ESTIMATE.model_spend_dominates }}" in section
    assert "ESTIMATE.model_share_of_total" in section
    assert "Model spend dominates." in section


def test_report_cost_note_cannot_contradict_the_flag():
    assert "never contradicting `estimate.json.model_spend_dominates`" in _flat(GENERATE_REPORT_MD)


def test_recommendation_doc_cost_section_leads_with_dominance():
    doc = RECOMMENDATION_DOC_MD.read_text()
    section = doc[doc.index("## 10. Cost magnitude"):doc.index("## 11.")]
    assert "model_spend_dominates is true" in section
    assert "Model spend dominates" in section


# --- Clarify and seed -------------------------------------------------------------------------

def test_clarify_collects_usage_volume_as_an_unscored_input():
    clarify = _flat(CLARIFY / "clarify.md")
    assert "`usage_volume` (per agent_session unit, NOT scored)" in clarify
    assert "answers.json.units[<unit_id>].usage_volume" in clarify
    for audience in ("clarify-business.md", "clarify-technical.md"):
        assert "**usage_volume**" in (CLARIFY / audience).read_text(), audience
    assert "usage_volume" not in scoring.DIMENSIONS


def test_usage_volume_does_not_change_scores():
    answers = {"session_duration": "15min_to_8hr", "traffic_pattern": "steady"}
    volume = {"sessions_per_month": 50000, "input_tokens_per_session": 100000,
              "output_tokens_per_session": 5000}
    assert scoring.score({"answers": {**answers, "usage_volume": volume}}) == scoring.score(
        {"answers": answers})


@pytest.mark.parametrize("volume", [
    {"sessions_per_month": 2000, "input_tokens_per_session": 20000, "output_tokens_per_session": 2000},
    {"sessions_per_month": "unknown"},
    {},
])
def test_seed_accepts_usage_volume(volume):
    schema = json.loads(SEED_SCHEMA.read_text())
    jsonschema.validate({"units": {"agent": {"usage_volume": volume}}}, schema)


@pytest.mark.parametrize("volume", [
    {"sessions_per_month": -1},
    {"sessions_per_month": "lots"},
    {"sessions_per_month": 10.5},
    {"requests_per_month": 100},
])
def test_seed_rejects_bad_usage_volume(volume):
    schema = json.loads(SEED_SCHEMA.read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"units": {"agent": {"usage_volume": volume}}}, schema)
