"""The shared report validator gates heroku-to-aws through an explicit opt-in.

Two pieces, both pinned here:

- `_COST_ANCHORS["current_monthly"]` gains heroku's current-spend path,
  `cost_comparison.heroku_monthly_baseline` (heroku's `current_costs` object carries
  provenance metadata, never a dollar total). Anchor present + matching passes;
  mismatched fails with a line naming the path; figure rendered but unanchored fails;
  the gcp and azure paths are unchanged.
- `--profile heroku` (`SKILL_PROFILES`) swaps in heroku's required-section set per mode
  (the default decision set plus `exec-share` and `developer-workflow`; the full set adds
  the always-rendered optimization pair, `appendix-artifacts` and `appendix-glossary`),
  declares exactly three PaaS omissions (`appendix-steps`, `appendix-security-gap`,
  `appendix-ai`) and skips nothing: the "Stay entirely if" heading, the optimization
  section IDs, the appendix-config provenance columns, the glossary table and the
  bare-week-range readability rule all fire under the profile. Without `--profile`
  nothing changes.
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


HEROKU_DECISION_IDS = [
    "decision-summary", "exec-share", "exec-services", "exec-costs", "developer-workflow",
    "exec-timeline", "exec-risks", "exec-assumptions", "decision-cta",
]
HEROKU_FULL_IDS = [
    "decision-summary", "exec-share", "exec-services", "exec-costs", "exec-optimization",
    "developer-workflow", "exec-timeline", "exec-risks", "exec-assumptions",
    "appendix-services", "appendix-costs", "appendix-optimization", "appendix-artifacts",
    "appendix-config", "appendix-security", "appendix-assumptions", "appendix-glossary",
]
RISK_TABLE = (
    "<table><caption>Top risks</caption><thead><tr><th scope='col'>Risk</th><th scope='col'>Impact</th>"
    "<th scope='col'>Likelihood</th><th scope='col'>Mitigation</th></tr></thead>"
    "<tbody><tr><td>r</td><td>High</td><td>Low</td><td>m</td></tr></tbody></table>"
)


def _heroku_decision_html(*, drop: str | None = None, timeline: str = "Phased migration.", summary_extra: str = "") -> str:
    ids = HEROKU_DECISION_IDS
    bodies = {
        "decision-summary": f'<p class="verdict-headline">Go</p>{summary_extra}',
        "exec-timeline": f"<p>{timeline}</p>",
        "exec-risks": RISK_TABLE,
    }
    parts = [_section(sid, bodies.get(sid, "<p>x</p>")) for sid in ids if sid != drop]
    return "<html lang='en'><body>" + "".join(parts) + "<footer>draft for review</footer></body></html>"


def test_profile_swaps_required_sections_for_decision_mode() -> None:
    validator = _load()
    html = _heroku_decision_html()
    # The default decision contract does not know heroku's add-on sections, but it does
    # not demand anything heroku lacks either: the heroku decision set is a superset.
    default_errors = validator.validate_report(html, mode="decision", require_toc=False)
    assert not any("missing required" in e for e in default_errors), default_errors
    profile_errors = validator.validate_report(html, mode="decision", require_toc=False, profile="heroku")
    assert not any("missing required" in e for e in profile_errors), profile_errors
    assert validator.SKILL_PROFILES["heroku"]["required_sections"]["decision"] == HEROKU_DECISION_IDS
    assert set(validator.DECISION_REQUIRED_SECTION_IDS) <= set(HEROKU_DECISION_IDS)


def test_profile_decision_mode_requires_the_shared_exec_sections() -> None:
    validator = _load()
    for sid in ("exec-assumptions", "exec-services", "exec-risks"):
        errors = validator.validate_report(
            _heroku_decision_html(drop=sid), mode="decision", require_toc=False, profile="heroku"
        )
        assert f'missing required <section id="{sid}">' in errors, (sid, errors)


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
    profile = validator.SKILL_PROFILES["heroku"]
    ids = profile["required_sections"]["full"]
    assert ids == HEROKU_FULL_IDS
    for sid in (
        "exec-assumptions", "exec-services", "exec-risks", "exec-optimization",
        "appendix-optimization", "appendix-artifacts", "appendix-glossary", "developer-workflow",
        "appendix-services", "appendix-costs", "appendix-config", "appendix-security", "appendix-assumptions",
    ):
        assert sid in ids, sid
    for sid in ("appendix-steps", "appendix-security-gap", "appendix-ai", "cost-optimization", "next-steps", "decision-cta"):
        assert sid not in ids, sid
    # Every PaaS-justified omission is declared with a reason, and nothing else is.
    assert set(profile["not_required"]) == {"appendix-steps", "appendix-security-gap", "appendix-ai"}
    for reason in profile["not_required"].values():
        assert reason
    # Every vocabulary skip was converged: the default checks run in full.
    assert profile["skip"] == {}


def test_profile_not_required_never_overlaps_required_sections() -> None:
    """`not_required` is documentary; a later edit must not list an ID in both maps."""
    validator = _load()
    profile = validator.SKILL_PROFILES["heroku"]
    not_required = set(profile["not_required"])
    for mode, ids in profile["required_sections"].items():
        overlap = not_required & set(ids)
        assert not overlap, f"{mode}: declared not_required but also required: {sorted(overlap)}"


def test_profile_does_not_exempt_week_range_readability() -> None:
    validator = _load()
    errors = validator.validate_report(
        _heroku_decision_html(timeline="Planning band: about 2-6 weeks."),
        mode="decision", require_toc=False, profile="heroku",
    )
    assert any("readability: bare week-range estimate" in e for e in errors), errors


def test_profile_enforces_stay_entirely_if_heading_and_badge_ban() -> None:
    validator = _load()
    estimate = {"recommendation": {"stay_if": ["need Heroku DX indefinitely"], "outcome": "go"}}
    html = _heroku_decision_html(summary_extra='<span class="badge-verdict-go">Go</span>')
    profile_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False, profile="heroku")
    assert any('"Stay entirely if" heading' in e for e in profile_errors), profile_errors
    assert any("badge-verdict-* pills" in e for e in profile_errors), profile_errors
    fixed = _heroku_decision_html(
        summary_extra='<h3>Migrate if</h3><ul class="compact"><li>a</li></ul>'
        '<h3>Stay entirely if</h3><ul class="compact"><li>need Heroku DX indefinitely</li></ul>'
    )
    fixed_errors = validator.validate_report(fixed, estimate, mode="decision", require_toc=False, profile="heroku")
    assert not any("Stay" in e for e in fixed_errors), fixed_errors
    bare = _heroku_decision_html(summary_extra='<h3>Stay if</h3><ul class="compact"><li>x</li></ul>')
    bare_errors = validator.validate_report(bare, estimate, mode="decision", require_toc=False, profile="heroku")
    assert any('"Stay entirely if" heading' in e for e in bare_errors), bare_errors


def test_profile_demands_exec_optimization_when_opportunities_exist() -> None:
    validator = _load()
    estimate = {
        "projected_costs": {"aws_monthly_balanced": 210},
        "optimization_opportunities": [{"opportunity": "Database Savings Plans", "type": "database_savings_plan", "target_services": ["RDS PostgreSQL"], "savings_monthly": 19}],
    }
    html = _heroku_decision_html()
    profile_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False, profile="heroku")
    assert any('no <section id="exec-optimization">' in e for e in profile_errors), profile_errors
    default_errors = validator.validate_report(html, estimate, mode="decision", require_toc=False)
    assert [e for e in profile_errors if "exec-optimization" in e] == [e for e in default_errors if "exec-optimization" in e]


def _heroku_full_html(config_table: str) -> str:
    glossary = (
        "<table class='glossary-table'><caption>Glossary</caption><thead><tr><th scope='col'>Term</th><th scope='col'>Meaning</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr><tr><td>e</td><td>f</td></tr></tbody></table>"
    )
    bodies = {
        "exec-risks": RISK_TABLE,
        "exec-optimization": "<p>Balanced on-demand: no 1-year/3-year commitment product applies to this architecture.</p>",
        "appendix-config": config_table,
        "appendix-glossary": glossary,
    }
    return (
        "<html lang='en'><body>"
        + "".join(_section(sid, bodies.get(sid, "<p>x</p>")) for sid in HEROKU_FULL_IDS)
        + "<footer>draft for review</footer></body></html>"
    )


OLD_CONFIG_COLUMNS = (
    "<table><thead><tr><th scope='col'>Choice</th><th scope='col'>Your answer</th><th scope='col'>What it changes</th></tr></thead>"
    "<tbody><tr><td>Region</td><td>us-east-1</td><td>Pricing</td></tr><tr><td>HA</td><td>Multi-AZ</td><td>Cost</td></tr></tbody></table>"
)
NEW_CONFIG_COLUMNS = (
    "<table><thead><tr><th scope='col'>Question</th><th scope='col'>Your choice</th><th scope='col'>Source</th><th scope='col'>Design consequence</th></tr></thead>"
    "<tbody><tr><td>Which AWS region?</td><td>us-east-1</td><td>User answer</td><td>Pricing</td></tr>"
    "<tr><td>Availability?</td><td>Multi-AZ</td><td>User answer</td><td>RDS Multi-AZ</td></tr></tbody></table>"
)


def test_profile_enforces_appendix_config_columns() -> None:
    validator = _load()
    old_errors = validator.validate_report(_heroku_full_html(OLD_CONFIG_COLUMNS), mode="full", require_toc=False, profile="heroku")
    assert any("appendix-config" in e and "column" in e.lower() for e in old_errors), old_errors
    new_errors = validator.validate_report(_heroku_full_html(NEW_CONFIG_COLUMNS), mode="full", require_toc=False, profile="heroku")
    assert not any("appendix-config" in e for e in new_errors), new_errors
    assert not any("missing required" in e for e in new_errors), new_errors


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
# --- section gate follows rendered structure, not raw source ----------------------
def _decision_cta_missing_errors(validator, replacement: str) -> list[str]:
    html = _heroku_decision_html(drop="decision-cta").replace("<footer>", replacement + "<footer>")
    return validator.validate_report(html, mode="decision", require_toc=False, profile="heroku")
@pytest.mark.parametrize(
    "replacement",
    [
        '<!-- <section id="decision-cta"><h2>cta</h2><p>x</p></section> -->',
        '<template><section id="decision-cta"><h2>cta</h2><p>x</p></section></template>',
        '<script type="text/html"><section id="decision-cta"></section></script>',
        '<section data-id="decision-cta"><h2>cta</h2><p>x</p></section>',
    ],
    ids=["comment", "template", "script", "data-id"],
)
def test_profile_required_section_only_in_comment_inert_or_data_id_is_missing(replacement: str) -> None:
    errors = _decision_cta_missing_errors(_load(), replacement)
    assert 'missing required <section id="decision-cta">' in errors, errors
@pytest.mark.parametrize(
    "replacement",
    [
        '<section id=decision-cta><h2>cta</h2><p>x</p></section>',
        "<section id = 'decision-cta'><h2>cta</h2><p>x</p></section>",
    ],
    ids=["unquoted", "spaced-single-quoted"],
)
def test_profile_required_section_with_legal_id_spelling_is_counted(replacement: str) -> None:
    errors = _decision_cta_missing_errors(_load(), replacement)
    assert not any("decision-cta" in e and "missing required" in e for e in errors), errors
def test_section_id_counts_ignore_commented_duplicate_and_count_real_one() -> None:
    validator = _load()
    html = '<!-- <section id="exec-tco"> --><section id="exec-tco"></section>'
    assert validator._section_id_counts(html) == {"exec-tco": 1}
def test_commented_what_if_placeholder_does_not_satisfy_two_scenario_check(tmp_path: Path) -> None:
    validator = _load()
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "index.json").write_text(
        '{"scenarios": [{"id": "a"}, {"id": "b"}]}', encoding="utf-8"
    )
    html = _heroku_decision_html().replace(
        "<footer>", '<!-- <section id="what-if-scenarios"><h2>w</h2></section> --><footer>'
    )
    errors = validator.validate_report(
        html, mode="decision", require_toc=False, profile="heroku", migration_dir=tmp_path
    )
    assert any("what-if-scenarios" in e for e in errors), errors
