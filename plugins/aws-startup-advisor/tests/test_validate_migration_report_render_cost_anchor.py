"""The shared report validator must hold the `current_monthly` anchor to the Render
current-spend figure, after the GCP and Azure ones.
render-to-aws records current spend as `current_costs.render_monthly`; without that
candidate in the anchor table a Render report's current-spend dollars were never
asserted and a wrong figure passed REPORT_OK. These tests pin the Render key path
through `_validate_cost_figures` (anchors present + matching pass; anchor present +
mismatched fails; required anchor missing from exec-costs fails; an absent value is
skipped) and that the GCP and Azure key paths are unchanged.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
def _load():
    spec = importlib.util.spec_from_file_location("validate_migration_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module
def _exec_costs(
    current: str,
    balanced: str = '<strong data-cost-key="aws_monthly_balanced">$314</strong>',
    optimized: str = '<strong data-cost-key="aws_monthly_optimized">$278</strong>',
) -> str:
    return (
        '<section id="exec-costs"><h2>Infrastructure Cost Comparison</h2>'
        f"<p>Current Render spend: {current}</p><p>Balanced: {balanced}</p>"
        f"<p>Optimized: {optimized}</p></section>"
    )
RENDER_ESTIMATE = {
    "current_costs": {"source": "user_stated", "render_monthly": 123.45},
    "projected_costs": {
        "aws_monthly_balanced": 313.5,
        "aws_monthly_optimized": 277.8,
        "aws_monthly_premium": 313.5,
    },
}
GCP_ESTIMATE = {
    "current_costs": {"gcp_monthly": 165},
    "projected_costs": {"aws_monthly_balanced": 112},
}
AZURE_ESTIMATE = {
    "current_costs": {"azure_monthly": 4200, "source": "user_stated"},
    "projected_costs": {"aws_monthly_balanced": 460.13},
}
def test_render_anchors_matching_pass() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$123/mo</span>')
    assert validator._validate_cost_figures(html, RENDER_ESTIMATE) == []
def test_render_current_monthly_anchor_mismatch_fails() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$120/mo</span>')
    errors = validator._validate_cost_figures(html, RENDER_ESTIMATE)
    assert len(errors) == 1, errors
    assert "cost figure mismatch" in errors[0]
    assert 'data-cost-key="current_monthly"' in errors[0]
    assert "current_costs.render_monthly = $123" in errors[0]
def test_render_optimized_anchor_mismatch_fails() -> None:
    validator = _load()
    html = _exec_costs(
        '<span data-cost-key="current_monthly">$123/mo</span>',
        optimized='<strong data-cost-key="aws_monthly_optimized">$300</strong>',
    )
    errors = validator._validate_cost_figures(html, RENDER_ESTIMATE)
    assert len(errors) == 1, errors
    assert "projected_costs.aws_monthly_optimized = $278" in errors[0]
def test_render_current_monthly_anchor_missing_in_exec_costs_fails() -> None:
    validator = _load()
    html = _exec_costs("$123/mo")  # figure rendered but not anchored
    errors = validator._validate_cost_figures(html, RENDER_ESTIMATE)
    assert len(errors) == 1, errors
    assert 'missing data-cost-key="current_monthly" anchor' in errors[0]
    assert "current_costs.render_monthly" in errors[0]
def test_gcp_and_azure_current_monthly_paths_unchanged() -> None:
    validator = _load()
    gcp_bad = _exec_costs(
        '<span data-cost-key="current_monthly">$160/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$112</strong>',
        "",
    )
    errors = validator._validate_cost_figures(gcp_bad, GCP_ESTIMATE)
    assert len(errors) == 1 and "current_costs.gcp_monthly = $165" in errors[0], errors
    azure_bad = _exec_costs(
        '<span data-cost-key="current_monthly">$3,900/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$460</strong>',
        "",
    )
    errors = validator._validate_cost_figures(azure_bad, AZURE_ESTIMATE)
    assert len(errors) == 1 and "current_costs.azure_monthly = $4200" in errors[0], errors
def test_render_current_monthly_skipped_when_value_unavailable() -> None:
    validator = _load()
    estimate = {
        "current_costs": {"source": "unavailable", "render_monthly": None},
        "projected_costs": RENDER_ESTIMATE["projected_costs"],
    }
    html = _exec_costs("no anchored current figure")
    assert validator._validate_cost_figures(html, estimate) == []
