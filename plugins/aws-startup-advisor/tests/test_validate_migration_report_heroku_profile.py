"""The shared report validator gates heroku-to-aws through an explicit opt-in.

Two pieces, both pinned here:

- `_COST_ANCHORS["current_monthly"]` gains heroku's current-spend path,
  `cost_comparison.heroku_monthly_baseline` (heroku's `current_costs` object carries
  provenance metadata, never a dollar total). Anchor present + matching passes;
  mismatched fails with a line naming the path; figure rendered but unanchored fails;
  the gcp and azure paths are unchanged.
- `--profile heroku` (`SKILL_PROFILES`) swaps in heroku's required-section set per mode
  and switches off exactly the vocabulary-only checks the profile names (stay-if
  heading, optimization section IDs, appendix-config columns, glossary). It does NOT
  exempt the bare-week-range readability rule. Without `--profile` nothing changes.
"""
from __future__ import annotations

import importlib.util
import subprocess  # nosec B404 — test-only, list args, no shell, committed script path
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
REFERENCE_HTML = PLUGIN_ROOT / "fixtures" / "migration-report-reference.html"


def _load():
    spec = importlib.util.spec_from_file_location("validate_migration_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# --- cost anchor -----------------------------------------------------------------


def _exec_costs(current: str, balanced: str = '<strong data-cost-key="aws_monthly_balanced">$210</strong>') -> str:
    return (
        '<section id="exec-costs"><h2>Cost Comparison</h2>'
        f"<p>Heroku baseline: {current}</p><p>Balanced: {balanced}</p></section>"
    )


HEROKU_ESTIMATE = {
    "current_costs": {"source": "invoice", "baseline_note": "from your Heroku invoice"},
    "cost_comparison": {"heroku_monthly_baseline": 340, "heroku_monthly_like_for_like": 300},
    "projected_costs": {"aws_monthly_balanced": 210},
}
AZURE_ESTIMATE = {
    "current_costs": {"azure_monthly": 4200, "source": "user_stated"},
    "projected_costs": {"aws_monthly_balanced": 460.13},
}
GCP_ESTIMATE = {
    "current_costs": {"gcp_monthly": 165},
    "projected_costs": {"aws_monthly_balanced": 112},
}


def test_heroku_current_monthly_anchor_matching_passes() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$340/mo</span>')
    assert validator._validate_cost_figures(html, HEROKU_ESTIMATE) == []


def test_heroku_current_monthly_anchor_mismatch_fails() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$300/mo</span>')
    errors = validator._validate_cost_figures(html, HEROKU_ESTIMATE)
    assert len(errors) == 1, errors
    assert "cost figure mismatch" in errors[0]
    assert 'data-cost-key="current_monthly"' in errors[0]
    assert "cost_comparison.heroku_monthly_baseline = $340" in errors[0]


def test_heroku_current_monthly_anchor_missing_in_exec_costs_fails() -> None:
    validator = _load()
    html = _exec_costs("$340/mo")  # figure rendered but not anchored
    errors = validator._validate_cost_figures(html, HEROKU_ESTIMATE)
    assert len(errors) == 1, errors
    assert 'missing data-cost-key="current_monthly" anchor' in errors[0]
    assert "cost_comparison.heroku_monthly_baseline" in errors[0]


def test_heroku_like_for_like_anchor_is_not_a_shared_rule() -> None:
    # The scope-matched figure stays a heroku add-on anchor: the shared validator
    # skips the unknown key rather than asserting it.
    validator = _load()
    html = _exec_costs(
        '<span data-cost-key="current_monthly">$340/mo</span>'
        '<span data-cost-key="heroku_monthly_like_for_like">$999/mo</span>'
    )
    assert validator._validate_cost_figures(html, HEROKU_ESTIMATE) == []


def test_gcp_and_azure_current_monthly_paths_unchanged() -> None:
    validator = _load()
    gcp_ok = _exec_costs(
        '<span data-cost-key="current_monthly">$165/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$112</strong>',
    )
    assert validator._validate_cost_figures(gcp_ok, GCP_ESTIMATE) == []
    gcp_bad = _exec_costs(
        '<span data-cost-key="current_monthly">$160/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$112</strong>',
    )
    errors = validator._validate_cost_figures(gcp_bad, GCP_ESTIMATE)
    assert len(errors) == 1 and "current_costs.gcp_monthly = $165" in errors[0], errors
    azure_bad = _exec_costs(
        '<span data-cost-key="current_monthly">$3,900/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$460</strong>',
    )
    errors = validator._validate_cost_figures(azure_bad, AZURE_ESTIMATE)
    assert len(errors) == 1 and "current_costs.azure_monthly = $4200" in errors[0], errors


def test_current_monthly_skipped_when_no_source_key_present() -> None:
    validator = _load()
    estimate = {"projected_costs": {"aws_monthly_balanced": 210}}
    html = _exec_costs("no anchored current figure")
    assert validator._validate_cost_figures(html, estimate) == []


# --- --profile heroku ------------------------------------------------------------


def _section(sid: str, body: str = "<p>x</p>") -> str:
    return f'<section id="{sid}"><h2>{sid}</h2>{body}</section>'


def _heroku_decision_html(*, drop: str | None = None, timeline: str = "Phased migration.", summary_extra: str = "") -> str:
    ids = ["decision-summary", "exec-share", "exec-costs", "developer-workflow", "exec-timeline", "decision-cta"]
    bodies = {
        "decision-summary": f'<p class="verdict-headline">Go</p>{summary_extra}',
        "exec-timeline": f"<p>{timeline}</p>",
    }
    parts = [_section(sid, bodies.get(sid, "<p>x</p>")) for sid in ids if sid != drop]
    return "<html lang='en'><body>" + "".join(parts) + "<footer>draft for review</footer></body></html>"


def test_profile_swaps_required_sections_for_decision_mode() -> None:
    validator = _load()
    html = _heroku_decision_html()
    default_errors = validator.validate_report(html, mode="decision", require_toc=False)
    assert 'missing required <section id="exec-assumptions">' in default_errors
    assert 'missing required <section id="exec-services">' in default_errors
    assert 'missing required <section id="exec-risks">' in default_errors
    profile_errors = validator.validate_report(html, mode="decision", require_toc=False, profile="heroku")
    assert not any("missing required" in e for e in profile_errors), profile_errors


def test_profile_still_requires_heroku_sections() -> None:
    validator = _load()
    errors = validator.validate_report(
        _heroku_decision_html(drop="exec-share"), mode="decision", require_toc=False, profile="heroku"
    )
    assert 'missing required <section id="exec-share">' in errors
    errors = validator.validate_report(
        _heroku_decision_html(drop="developer-workflow"), mode="decision", require_toc=False, profile="heroku"
    )
    assert 'missing required <section id="developer-workflow">' in errors


def test_profile_full_mode_required_set() -> None:
    validator = _load()
    ids = validator.SKILL_PROFILES["heroku"]["required_sections"]["full"]
    assert "cost-optimization" in ids and "next-steps" in ids and "developer-workflow" in ids
    for sid in ("appendix-services", "appendix-costs", "appendix-config", "appendix-security", "appendix-assumptions"):
        assert sid in ids
    for sid in ("appendix-steps", "appendix-artifacts", "appendix-glossary", "exec-assumptions", "exec-risks"):
        assert sid not in ids
    # Every PaaS-justified omission is declared with a reason.
    for sid in ("appendix-steps", "appendix-security-gap", "appendix-ai", "appendix-glossary"):
        assert validator.SKILL_PROFILES["heroku"]["not_required"][sid]


def test_profile_does_not_exempt_week_range_readability() -> None:
    validator = _load()
    errors = validator.validate_report(
        _heroku_decision_html(timeline="Planning band: about 2-6 weeks."),
        mode="decision", require_toc=False, profile="heroku",
    )
    assert any("readability: bare week-range estimate" in e for e in errors), errors


def test_profile_skips_stay_if_heading_but_keeps_badge_ban() -> None:
    validator = _load()
    estimate = {"recommendation": {"stay_if": ["need Heroku DX indefinitely"], "outcome": "go"}}
    html = _heroku_decision_html(summary_extra='<span class="badge-verdict-go">Go</span>')
    default_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False)
    assert any('"Stay entirely if" heading' in e for e in default_errors), default_errors
    profile_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False, profile="heroku")
    assert not any('"Stay entirely if" heading' in e for e in profile_errors), profile_errors
    assert any("badge-verdict-* pills" in e for e in profile_errors), profile_errors


def test_profile_skips_optimization_section_ids() -> None:
    validator = _load()
    estimate = {
        "projected_costs": {"aws_monthly_balanced": 210},
        "optimization_opportunities": [{"service": "RDS", "type": "reserved_instance", "savings": 20}],
    }
    html = _heroku_decision_html()
    default_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False)
    assert any("exec-optimization" in e for e in default_errors), default_errors
    profile_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False, profile="heroku")
    assert not any("exec-optimization" in e for e in profile_errors), profile_errors


def test_profile_skips_appendix_config_columns() -> None:
    validator = _load()
    html = (
        "<html lang='en'><body>"
        + "".join(_section(s) for s in ("decision-summary", "exec-share", "exec-costs", "developer-workflow", "exec-timeline", "cost-optimization", "next-steps"))
        + _section("appendix-config", "<table><thead><tr><th scope='col'>Choice</th><th scope='col'>Your answer</th><th scope='col'>What it changes</th></tr></thead><tbody><tr><td>Region</td><td>us-east-1</td><td>Pricing</td></tr><tr><td>HA</td><td>single-AZ</td><td>Cost</td></tr></tbody></table>")
        + "".join(_section(s) for s in ("appendix-services", "appendix-costs", "appendix-security", "appendix-assumptions"))
        + "<footer>draft for review</footer></body></html>"
    )
    default_errors = validator.validate_report(html, mode="full", require_toc=False)
    assert any("appendix-config" in e and "column" in e.lower() for e in default_errors), default_errors
    profile_errors = validator.validate_report(html, mode="full", require_toc=False, profile="heroku")
    assert not any("appendix-config" in e for e in profile_errors), profile_errors
    assert not any("appendix-glossary" in e for e in profile_errors), profile_errors


def test_default_behaviour_unchanged_without_profile() -> None:
    validator = _load()
    html = REFERENCE_HTML.read_text(encoding="utf-8")
    assert validator.validate_report(html) == validator.validate_report(html, profile=None)
    assert validator._required_ids_for("full", None) is validator.REQUIRED_SECTION_IDS
    assert validator._required_ids_for("decision", None) is validator.DECISION_REQUIRED_SECTION_IDS
    assert validator._required_ids_for("ai_only", None) is validator.AI_ONLY_REQUIRED_SECTION_IDS


def test_profile_without_mode_entry_raises() -> None:
    validator = _load()
    with pytest.raises(ValueError, match="no required-section set for mode 'ai_only'"):
        validator.validate_report("<html></html>", mode="ai_only", require_toc=False, profile="heroku")


def test_unknown_profile_is_rejected_by_argparse(tmp_path: Path) -> None:
    report = tmp_path / "r.html"
    report.write_text("<html></html>", encoding="utf-8")
    result = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), str(report), "--profile", "render"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "invalid choice: 'render'" in result.stderr


def test_profile_mode_combination_is_rejected_by_argparse(tmp_path: Path) -> None:
    report = tmp_path / "r.html"
    report.write_text("<html></html>", encoding="utf-8")
    result = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), str(report), "--profile", "heroku", "--mode", "ai_only"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "--profile heroku does not define --mode ai_only" in result.stderr
