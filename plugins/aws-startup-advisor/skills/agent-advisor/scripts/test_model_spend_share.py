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
    assert "midpoint of `total_monthly_magnitude_usd` is 0" in est
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
    for default in ("`prototype` 1,000", "`growing` 30,000", "`high` 300,000", "otherwise 1,000", "20,000 input", "2,000 output"):
        assert default in est, default
    assert "assumed (not answered)" in est


def test_estimate_postcondition_requires_the_share_fields():
    assertion = next(line for line in ESTIMATE_MD.read_text().splitlines()
                     if line.strip().startswith("- _assert:"))
    for field in ("model_share_of_total", "model_spend_dominates", "usage_volume"):
        assert field in assertion, field


def test_dominant_driver_levers_are_real_cost_levers():
    est, levers = _flat(ESTIMATE_MD), COST_LEVERS_MD.read_text()
    rule = est[est.index("When `model_spend_dominates` is true, the FIRST"):]
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


# --- Driver order, shared session count, other classes, length mapping ------------------------

def test_estimate_example_leads_with_the_token_driver_when_model_spend_dominates():
    example = _estimate_example()
    assert example["model_spend_dominates"] is True
    first = example["drivers"][0]
    assert "model tokens" in first["driver"]
    assert first["lever"] in TOKEN_LEVERS
    # The effect is sized from the unit's own model band (40-120 for 1,000 sessions).
    unit = example["units"][first["unit"]]
    assert unit["breakdown"]["model_tokens"] in first["effect"]


def test_driver_order_is_applied_in_step_5_after_the_flag():
    est = _flat(ESTIMATE_MD)
    step4 = est[est.index("## Step 4"):est.index("## Step 5")]
    # The flag needs the Step 5 totals (system-level lines included), so Step 4 cannot order.
    assert "Step 5 applies the rule below once the flag is computed" in step4
    step5 = est[est.index("**Model spend share (always emitted).**"):]
    assert "move the model-token driver of the unit with the largest `model_tokens` band to `drivers[0]`" in step5
    # The agent_session example driver is the token driver the rule asks for.
    assert '"driver": "model tokens (sessions × tokens per session)"' in step4


def test_compute_and_model_tokens_use_one_session_count():
    est = _flat(ESTIMATE_MD)
    assert "The session count for compute is the same `sessions_per_month` the model line uses" in est
    assert "or the same stated session default, marked the same way" in est


def test_other_classes_keep_their_own_volume():
    est = _flat(ESTIMATE_MD)
    rule = est[est.index("**Model tokens for other classes**"):]
    rule = rule[:rule.index("**batch units**")]
    assert "OWN volume" in rule
    assert "Never apply the agent session default" in rule
    # The service bullet states no volume, so the rule must supply one.
    assert "service unit that calls a model, also state a requests-per-month assumption" in rule
    assert "assumed (not answered): tokens per call" in rule


def test_clarify_asks_usage_volume_and_never_inherits_it():
    clarify = _flat(CLARIFY / "clarify.md")
    full_set = clarify[clarify.index("walks the FULL existing per-unit question set"):]
    full_set = full_set[:full_set.index(")")+1]
    assert "`usage_volume`" in full_set
    delta = clarify[clarify.index("ONE batched delta question"):]
    delta = delta[:delta.index("Non-agent units")]
    assert "usage volume" in delta
    assert "EXCEPT `usage_volume`: an unmentioned volume stays `unknown`" in delta


def test_length_mapping_is_recorded_and_reaches_the_assumptions():
    assert "set `session_length` to the length picked" in _flat(CLARIFY / "clarify-business.md")
    assert "`usage_volume.session_length` records which length" in _flat(CLARIFY / "clarify.md")
    assert "length mapping\" to the unit's `assumptions`" in _flat(ESTIMATE_MD)
    assert "only when both token fields came from that mapping" in _flat(ESTIMATE_MD)
    assert "drop `session_length`" in _flat(CLARIFY / "clarify.md")


@pytest.mark.parametrize(("length", "valid"), [("medium", True), ("long", True), ("huge", False)])
def test_seed_session_length(length, valid):
    schema = json.loads(SEED_SCHEMA.read_text())
    seed = {"units": {"agent": {"usage_volume": {"session_length": length}}}}
    if valid:
        jsonschema.validate(seed, schema)
    else:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(seed, schema)


def test_session_length_rule_stays_inside_its_bullet():
    # Review nit on #667: the continuation lines lost their indent and read as a new rule.
    lines = ESTIMATE_MD.read_text().splitlines()
    start = next(k for k, line in enumerate(lines) if "When `usage_volume.session_length` is present" in line)
    end = next(k for k in range(start, len(lines)) if lines[k].startswith("- **Model tokens for other classes**"))
    assert all(line.startswith("  ") for line in lines[start + 1:end]), lines[start:end]


def test_session_default_follows_expected_scale():
    # Follow-up to #667/#623: an unanswered sessions_per_month takes its default from the
    # unit's expected_scale, so a "high" workload is not priced as 1,000 sessions a month.
    est = _flat(ESTIMATE_MD)
    rule = est[est.index("Sessions a month follow the unit's `expected_scale`"):]
    rule = rule[:rule.index("Tokens per session default")]
    for tier, sessions in (("prototype", "1,000"), ("growing", "30,000"), ("high", "300,000")):
        assert f"`{tier}` {sessions}" in rule, tier
    assert "otherwise 1,000" in rule
    assert scoring.LEGAL_VALUES["expected_scale"] == ["prototype", "growing", "high", "unknown"]


@pytest.mark.parametrize(("value", "valid"), [("yes", True), ("unknown", True), ("maybe", False)])
def test_seed_accepts_instance_type_requirement(value, valid):
    schema = json.loads(SEED_SCHEMA.read_text())
    seed = {"units": {"agent": {"instance_type_requirement": value}}}
    if valid:
        jsonschema.validate(seed, schema)
    else:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(seed, schema)
