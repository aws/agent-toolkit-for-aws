"""The shared report validator must hold the `current_monthly` anchor to the Azure
current-spend figure, not only the GCP one.

azure-to-aws records current spend as `current_costs.azure_monthly`; before the
anchor table became a fallback list the validator only knew `current_costs.gcp_monthly`,
so an Azure report's current-spend dollars were never asserted and a wrong figure
passed REPORT_OK. These tests pin the Azure key path through `_validate_cost_figures`
(anchor present + matching passes; anchor present + mismatched fails; required anchor
missing from exec-costs fails) and that the GCP key path is unchanged.
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


def _exec_costs(current: str, balanced: str = '<strong data-cost-key="aws_monthly_balanced">$460</strong>') -> str:
    return (
        '<section id="exec-costs"><h2>Infrastructure Cost Comparison</h2>'
        f"<p>Current Azure spend: {current}</p><p>Balanced: {balanced}</p></section>"
    )


AZURE_ESTIMATE = {
    "current_costs": {"azure_monthly": 4200, "source": "user_stated"},
    "projected_costs": {"aws_monthly_balanced": 460.13},
}

GCP_ESTIMATE = {
    "current_costs": {"gcp_monthly": 165},
    "projected_costs": {"aws_monthly_balanced": 112},
}


def test_azure_current_monthly_anchor_matching_passes() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$4,200/mo</span>')
    assert validator._validate_cost_figures(html, AZURE_ESTIMATE) == []


def test_azure_current_monthly_anchor_mismatch_fails() -> None:
    validator = _load()
    html = _exec_costs('<span data-cost-key="current_monthly">$3,900/mo</span>')
    errors = validator._validate_cost_figures(html, AZURE_ESTIMATE)
    assert len(errors) == 1, errors
    assert "cost figure mismatch" in errors[0]
    assert 'data-cost-key="current_monthly"' in errors[0]
    assert "current_costs.azure_monthly = $4200" in errors[0]


def test_azure_current_monthly_anchor_missing_in_exec_costs_fails() -> None:
    validator = _load()
    html = _exec_costs("$4,200/mo")  # figure rendered but not anchored
    errors = validator._validate_cost_figures(html, AZURE_ESTIMATE)
    assert len(errors) == 1, errors
    assert 'missing data-cost-key="current_monthly" anchor' in errors[0]
    assert "current_costs.azure_monthly" in errors[0]


def test_gcp_current_monthly_anchor_path_unchanged() -> None:
    validator = _load()
    ok = _exec_costs(
        '<span data-cost-key="current_monthly">$165/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$112</strong>',
    )
    assert validator._validate_cost_figures(ok, GCP_ESTIMATE) == []
    bad = _exec_costs(
        '<span data-cost-key="current_monthly">$160/mo</span>',
        '<strong data-cost-key="aws_monthly_balanced">$112</strong>',
    )
    errors = validator._validate_cost_figures(bad, GCP_ESTIMATE)
    assert len(errors) == 1 and "current_costs.gcp_monthly = $165" in errors[0], errors


def test_current_monthly_skipped_when_neither_source_key_present() -> None:
    validator = _load()
    estimate = {"projected_costs": {"aws_monthly_balanced": 460.13}}
    html = _exec_costs("no anchored current figure")
    assert validator._validate_cost_figures(html, estimate) == []
