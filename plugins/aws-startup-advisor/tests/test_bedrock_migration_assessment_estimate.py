"""Tests for bedrock-migration-assessment's Estimate phase: the figures, the estimation-ai.json check, and the phase wiring."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
ESTIMATE_FIXTURES = sorted(p.parent for p in FIXTURES.glob("bma-estimate-*/estimation-ai.json"))
TIER = FIXTURES / "bma-estimate-tier-high-volume"
MEASURED = FIXTURES / "bma-estimate-measured"
UNAVAILABLE = FIXTURES / "bma-estimate-price-unavailable"
DOC = (BMA / "references/phases/estimate/estimate-ai.md").read_text(encoding="utf-8")
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EST = _module("bma_estimate_ai", "estimate-ai.py")
TIERS = json.loads((BMA / "references/vendored/ai/token-volume-tiers.json").read_text(encoding="utf-8"))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(run: Path) -> tuple[dict, dict, dict, list[dict]]:
    usage = [_json(run / n) for n in EST.USAGE_FILES if (run / n).exists()]
    return _json(run / "aws-design-ai.json"), _json(run / "ai-workload-profile.json"), _json(run / "preferences.json"), usage


def _figures(run: Path, usage: list[dict] | None = None, prefs_edit=None) -> dict:
    design, profile, prefs, found = _inputs(run)
    if prefs_edit:
        prefs_edit(prefs)
    return EST.build_figures(design, profile, prefs, found if usage is None else usage, TIERS)


def _usage(source: str, rows: list[dict], cost: float | None = 17.5, partial: bool = False, status: str = "complete") -> dict:
    return {"metadata": {"source": source, "window_days": 30, "active_days": 5 if partial else 30, "partial_window": partial, "cost_status": status},
            "summary": {"monthly_cost_usd": cost}, "usage_by_model": rows}


def _codes(estimate: dict, figures: dict) -> set[str]:
    return {e["code"] for e in EST.check_estimate(estimate, figures).get("errors", [])}


# --------------------------------------------------------------------------- copies and wiring

def test_contract_copy_matches_the_canonical_schema() -> None:
    assert (BMA / "references/contracts/estimation-ai.schema.json").read_bytes() == \
        (PLUGIN_ROOT / "scripts/contracts/estimation-ai.schema.json").read_bytes()


def test_source_provider_pricing_matches_gcp_to_aws_pricing_cache() -> None:
    shared = (PLUGIN_ROOT / "skills/shared/ai/source-provider-pricing.md").read_text(encoding="utf-8")
    gcp = (PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/pricing-cache.md").read_text(encoding="utf-8")
    section = gcp[gcp.index("## Source Provider Pricing"):gcp.index("## Security Baseline")].rstrip()
    assert shared[shared.index("## Source Provider Pricing"):].rstrip() == section


def test_skill_runs_estimate_after_design() -> None:
    step4 = SKILL[SKILL.index("## Step 4: Estimate"):]
    assert "references/phases/estimate/estimate-ai.md" in step4 and "scripts/estimate-ai.py check" in step4
    assert 'set `phases.estimate` to `"completed"` and `current_phase` to `"complete"`' in step4
    assert "Generate is not in this skill yet. After Estimate, show its summary and stop." in SKILL
    contracts = _json(PLUGIN_ROOT / "scripts/artifact-contracts.json")["skills"]["bedrock-migration-assessment"]
    assert contracts["estimation-ai.json"] == {"json_schema": "scripts/contracts/estimation-ai.schema.json"}


def test_estimate_doc_runs_plan_and_check_without_temporary_files() -> None:
    assert "scripts/estimate-ai.py plan $MIGRATION_DIR" in DOC and "scripts/estimate-ai.py check $MIGRATION_DIR" in DOC
    assert "Do not redirect it to a file" in DOC and "write nothing outside `$MIGRATION_DIR`" in DOC
    assert "Copy its numbers; never recompute" in DOC
    assert "Provisioned Throughput has no 1-year or 3-year term" in DOC


def test_design_doc_names_the_price_grammar_estimate_reads() -> None:
    design = (BMA / "references/phases/design/design-ai.md").read_text(encoding="utf-8")
    assert "`<input>/<output> per 1M tokens`, `<rate> per 1M tokens` (an embedding), `<rate> per image`, or `unverified`" in design
    assert "source's rate from `source-provider-pricing.md`" in design


# --------------------------------------------------------------------------- price parsing

@pytest.mark.parametrize(("price", "want"), [
    ("2.20/13.20 per 1M tokens", (2.2, 13.2)), ("$5.50/$33.00 per 1M tokens (In-Region)", (5.5, 33.0)),
    ("0.02 per 1M tokens", (0.02, 0.0)), ("0.11/0.55 per 1M tokens (US Geo, up to 100K prompt tokens)", (0.11, 0.55)),
    ("0.04 per image", None), ("unverified (no Geo price)", None), ("about 2 dollars", None), (None, None), (7, None),
])
def test_rate_reads_the_design_price_grammar(price, want) -> None:
    assert EST.rate(price) == want


# --------------------------------------------------------------------------- fixtures

@pytest.mark.parametrize("run", ESTIMATE_FIXTURES, ids=lambda p: p.name)
def test_fixture_estimates_pass_the_check(run: Path) -> None:
    assert EST.check_estimate(_json(run / "estimation-ai.json"), EST.figures_for(run))["ok"] is True


@pytest.mark.parametrize("run", ESTIMATE_FIXTURES, ids=lambda p: p.name)
def test_cli_plan_and_check_succeed(run: Path, tmp_path: Path, capsys) -> None:
    for f in run.iterdir():
        shutil.copy(f, tmp_path / f.name)
    assert EST.main(["plan", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert EST.main(["check", str(tmp_path)]) == 0


def test_corpus_covers_measured_tier_and_unavailable() -> None:
    assert {EST.figures_for(r)["token_volume"]["basis"] for r in ESTIMATE_FIXTURES} == {"measured", "tier"}
    assert EST.figures_for(UNAVAILABLE)["pricing_source"] == "unavailable"


# --------------------------------------------------------------------------- measured arithmetic

def test_measured_figures_match_hand_arithmetic() -> None:
    f = EST.figures_for(MEASURED)
    assert f["token_volume"] == {"basis": "measured", "monthly_input_tokens": 3_000_000, "monthly_output_tokens": 1_000_000, "input_share": 0.75}
    assert f["cost_comparison"] == {"current_source_monthly": 17.5, "projected_bedrock_monthly": 19.8, "monthly_difference": 2.3,
                                    "annual_difference": 27.6, "percent_change": 13.14}
    assert f["source_list_monthly_range"] == {"low": 17.5, "high": 17.5} and f["source_measured_monthly"] == 17.5
    assert f["cost_by_source"] == [{"provider": "openai", "source_service": "openai_api",
                                    "models": [{"model": "gpt-4o", "monthly_cost": 19.8, "vs_source_percent": 13.14}]}]


@pytest.mark.parametrize("model", ["gpt-4o", "GPT-4o", "openai/gpt-4o"])
def test_usage_model_names_match_case_and_provider_prefix(model) -> None:
    usage = [_usage("openai_usage_api", [{"model": model, "input_tokens": 3_000_000, "output_tokens": 1_000_000}])]
    assert _figures(MEASURED, usage)["cost_comparison"]["projected_bedrock_monthly"] == 19.8


def test_partial_window_usage_falls_back_to_the_tier() -> None:
    usage = [_usage("openai_usage_api", [{"model": "gpt-4o", "input_tokens": 3_000_000, "output_tokens": 1_000_000}], partial=True)]
    f = _figures(MEASURED, usage)
    assert f["token_volume"]["basis"] == "tier" and f["cost_comparison"]["projected_bedrock_monthly"] is None


def test_unavailable_cost_keeps_measured_volume_but_no_measured_spend() -> None:
    usage = [_usage("openai_usage_api", [{"model": "gpt-4o", "input_tokens": 3_000_000, "output_tokens": 1_000_000}], cost=None,
                    status="cost_unavailable")]
    f = _figures(MEASURED, usage)
    assert f["token_volume"]["basis"] == "measured" and f["source_measured_monthly"] is None
    assert f["cost_comparison"]["current_source_monthly"] == 17.5  # list price at the measured volume


def test_anthropic_cache_tokens_count_as_input_and_openrouter_uses_prompt_and_completion() -> None:
    assert EST._row_tokens({"input_tokens": 1, "cache_read_tokens": 10, "cache_creation_tokens": 100, "output_tokens": 5}) == (111, 5)
    assert EST._row_tokens({"prompt_tokens": 7, "completion_tokens": 3, "reasoning_tokens": 2}) == (7, 3)
    assert EST._row_tokens({"input_tokens": 4, "input_cached_tokens": 3, "output_tokens": 1}) == (4, 1)


def test_openrouter_rows_a_direct_profile_also_counts_are_left_out() -> None:
    direct = _usage("openai_usage_api", [{"model": "gpt-4o", "input_tokens": 3_000_000, "output_tokens": 1_000_000}])
    router = _usage("openrouter_usage_api", [{"model": "openai/gpt-4o", "prompt_tokens": 9_000_000, "completion_tokens": 1_000_000,
                                              "monthly_cost_usd": 5.0, "cost_provenance": "uncertain"}], cost=5.0)
    assert EST.measured_volume([direct, router])["gpt-4o"] == {"input_tokens": 3_000_000, "output_tokens": 1_000_000, "full_window": True}
    f = _figures(MEASURED, [direct, router])
    assert [x["model"] for x in f["overlap_excluded"]] == ["openai/gpt-4o"] and f["spend_excludes_usd"] == 5.0
    router["usage_by_model"][0]["cost_provenance"] = "no_byok"
    assert EST.measured_volume([direct, router])["gpt-4o"]["input_tokens"] == 12_000_000


def test_unmatched_usage_models_are_reported() -> None:
    usage = [_usage("openai_usage_api", [{"model": "gpt-4o", "input_tokens": 1, "output_tokens": 1},
                                         {"model": "gpt-4.1-mini", "input_tokens": 5, "output_tokens": 5}])]
    assert _figures(MEASURED, usage)["usage_unmatched"] == ["gpt-4.1-mini"]


def test_a_model_on_two_rows_gets_a_range_not_a_point() -> None:
    design, profile, prefs, usage = _inputs(MEASURED)
    row = copy.deepcopy(design["ai_architecture"]["bedrock_models"][0])
    row.update(aws_model_id="global.openai.gpt-5.6-terra", bedrock_price="2.00/12.00 per 1M tokens")
    design["ai_architecture"]["bedrock_models"].append(row)
    f = EST.build_figures(design, profile, prefs, usage, TIERS)
    assert f["projected_bedrock_monthly_range"] == {"low": 18.0, "high": 19.8}
    assert f["cost_comparison"]["projected_bedrock_monthly"] is None and f["per_model"]["gpt-4o"]["monthly_cost"] is None


# --------------------------------------------------------------------------- tier arithmetic

@pytest.mark.parametrize(("tier", "low", "high"), [("low", 0.0, 6.6), ("medium", 6.6, 66.0), ("high", 66.0, 660.0), ("very_high", 660.0, None)])
def test_tier_range_prices_the_band_bounds(tier, low, high) -> None:
    def edit(prefs):
        prefs["ai_constraints"]["ai_token_volume"]["value"] = tier
    f = _figures(MEASURED, [], edit)
    assert f["token_volume"]["basis"] == "tier" and f["projected_bedrock_monthly_range"] == {"low": low, "high": high}
    assert f["cost_comparison"]["projected_bedrock_monthly"] is None


def test_unknown_tier_is_an_input_error() -> None:
    def edit(prefs):
        prefs["ai_constraints"]["ai_token_volume"]["value"] = "huge"
    with pytest.raises(EST.EstimateInputError) as err:
        _figures(MEASURED, [], edit)
    assert err.value.code == "token_volume_unknown"


def test_missing_q7_uses_the_dont_know_default() -> None:
    f = _figures(MEASURED, [], lambda prefs: prefs["ai_constraints"].pop("ai_token_volume"))
    assert f["token_volume"]["tier"] == TIERS["dont_know"]["default"]


def test_an_unpriced_row_nulls_the_total_and_marks_pricing_unavailable() -> None:
    f = EST.figures_for(UNAVAILABLE)
    assert f["projected_bedrock_monthly_range"] == {"low": None, "high": None} and f["pricing_source"] == "unavailable"


def test_router_availability_follows_target_family() -> None:
    assert EST.figures_for(TIER)["router_available"] is True
    assert EST.figures_for(MEASURED)["router_available"] is False


# --------------------------------------------------------------------------- check: negatives

def _mutated(run: Path, mutate) -> set[str]:
    estimate = copy.deepcopy(_json(run / "estimation-ai.json"))
    mutate(estimate)
    return _codes(estimate, EST.figures_for(run))


def _set(d: dict, key: str, value) -> None:
    d[key] = value


@pytest.mark.parametrize(("run", "mutate", "code"), [
    (MEASURED, lambda e: _set(e["cost_comparison"], "projected_bedrock_monthly", 18.0), "figure_mismatch"),
    (MEASURED, lambda e: _set(e["cost_comparison"], "percent_change", 10.0), "figure_mismatch"),
    (MEASURED, lambda e: _set(e["token_volume"], "monthly_input_tokens", 1), "figure_mismatch"),
    (TIER, lambda e: _set(e["roi_analysis"]["projected_bedrock_monthly_range"], "high", 9999), "figure_mismatch"),
    (TIER, lambda e: e["roi_analysis"].pop("source_list_monthly_range"), "figure_mismatch"),
    (UNAVAILABLE, lambda e: _set(e["cost_comparison"], "projected_bedrock_monthly", 0), "figure_mismatch"),
    (UNAVAILABLE, lambda e: _set(e, "pricing_source", "cached"), "figure_mismatch"),
    (MEASURED, lambda e: _set(e["cost_by_source"][0]["models"][0], "monthly_cost", 1.0), "cost_by_source"),
    (TIER, lambda e: e["cost_by_source"].pop(), "cost_by_source"),
    (UNAVAILABLE, lambda e: e["services_not_estimated"].append({"workload_id": "x", "target_aws_service": "textract", "reason": "not_token_priced"}),
     "services_not_estimated"),
    (MEASURED, lambda e: _set(e["recommended_model"], "model", "us.anthropic.claude-sonnet-5"), "recommended_model"),
    (MEASURED, lambda e: e["optimization_opportunities"].append(dict(e["optimization_opportunities"][0], type="provisioned_throughput",
                                                                     commitment="1-year")), "provisioned_throughput_term"),
    (MEASURED, lambda e: e["optimization_opportunities"].append(dict(e["optimization_opportunities"][0], type="intelligent_prompt_routing")),
     "prompt_routing_unavailable"),
    (MEASURED, lambda e: _set(e["roi_analysis"], "justification", "App Runner"), "app_runner"),
    (MEASURED, lambda e: _set(e["migration_cost_considerations"], "categories", ["people"]), "schema_violation"),
    (MEASURED, lambda e: e.pop("recommendation"), "schema_violation"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_check_rejects(run, mutate, code) -> None:
    assert code in _mutated(run, mutate)


def test_check_accepts_provisioned_throughput_with_the_real_terms() -> None:
    def mutate(e):
        e["optimization_opportunities"].append(dict(e["optimization_opportunities"][0], type="provisioned_throughput",
                                                    commitment="no-commit, 1-month, or 6-month"))
    assert _mutated(MEASURED, mutate) == set()


def test_recommend_stay_forces_the_stay_path() -> None:
    design, profile, prefs, usage = _inputs(MEASURED)
    design["ai_architecture"]["honest_assessment"] = "recommend_stay"
    figures = EST.build_figures(design, profile, prefs, usage, TIERS)
    estimate = _json(MEASURED / "estimation-ai.json")
    assert "recommendation_stay" in _codes(estimate, figures)
    estimate["recommendation"]["path"] = "stay"
    assert "recommendation_stay" not in _codes(estimate, figures)


# --------------------------------------------------------------------------- CLI errors

def _run_dir(tmp_path: Path, source: Path) -> Path:
    for f in source.iterdir():
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


@pytest.mark.parametrize(("edit", "error"), [
    (lambda d: (d / "aws-design-ai.json").unlink(), "design_not_found"),
    (lambda d: (d / "aws-design-ai.json").write_text(json.dumps({**_json(d / "aws-design-ai.json"), "design_blocks": []})), "design_invalid"),
    (lambda d: (d / "openai-usage-profile.json").write_text(json.dumps({"metadata": {}})), "usage_unreadable"),
    (lambda d: (d / "estimation-ai.json").unlink(), "estimate_not_found"),
    (lambda d: (d / "openai-usage-profile.json").write_text(json.dumps({**_json(d / "openai-usage-profile.json"),
                                                                        "metadata": {**_json(d / "openai-usage-profile.json")["metadata"], "cost_status": "x"}})),
     "usage_unreadable"),
    (lambda d: (d / "openai-usage-profile.json").write_text(json.dumps({**_json(d / "openai-usage-profile.json"), "usage_by_model": [
        {"model": "gpt-4o", "input_tokens": "3000000", "output_tokens": 1}]})), "usage_unreadable"),
], ids=["no-design", "bad-design", "bad-usage", "no-estimate", "bad-cost-status", "string-tokens"])
def test_cli_reports_input_errors_as_json(edit, error, tmp_path: Path, capsys) -> None:
    run = _run_dir(tmp_path, MEASURED)
    edit(run)
    assert EST.main(["check", str(run)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == error
