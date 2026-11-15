"""Tests for the Render migration report validator."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - fixed local command, no shell
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("validate-render-migration-report.py")
SKILL_ROOT = Path(__file__).resolve().parents[1]
EXPECTED = SKILL_ROOT / "fixtures/expected"
GENERATED = EXPECTED / "generated"


def prepared(tmp_path: Path) -> tuple[Path, Path]:
    migration = tmp_path / "migration"
    shutil.copytree(GENERATED, migration)
    for name in ("aws-design.json", "estimation-infra.json"):
        shutil.copy2(EXPECTED / name, migration / name)
    return migration, migration / "migration-report.html"


def run(report: Path, migration: Path) -> tuple[int, str]:
    result = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), str(report), "--migration-dir", str(migration)],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def test_complete_report_passes_with_exact_status(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda text: text.replace("ECS on Fargate", "Amazon App Runner", 1), "TARGET_MAPPING_MISMATCH"),
        (lambda text: text.replace('<td data-cost-key="capacity_preserving">$352</td>', '<td data-cost-key="capacity_preserving">$999</td>'), "COST_CAPACITY_PRESERVING_MISMATCH"),
        (lambda text: text.replace('data-accounted-count="15"', 'data-accounted-count="14"'), "REPORT_ACCOUNTED_COUNT_MISMATCH"),
        (lambda text: text.replace("establish writer quiescence, apply", "establish pause writes, apply"), "CONTENT_CUTOVER_WRITER_QUIESCENCE"),
        (lambda text: text.replace("honor the source retention window", "honor the source hold window"), "CONTENT_ROLLBACK_SOURCE_RETENTION"),
        (lambda text: text.replace('scope="col"', "", 1), "ACCESSIBILITY"),
        (lambda text: text.replace("deferred_shared_ai_engine", "AI later"), "AI_DEFERRED_STATE_MISSING"),
        (lambda text: text.replace("draft for review", "final report"), "DRAFT_FOOTER_MISSING"),
        (lambda text: text.replace("</footer>", " contact user@example.com</footer>"), "PRIVACY_EMAIL"),
    ],
)
def test_report_mutations_fail_closed(tmp_path: Path, mutation, expected: str) -> None:
    migration, report = prepared(tmp_path)
    report.write_text(mutation(report.read_text(encoding="utf-8")), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 1
    assert output.startswith("REPORT_FAIL |")
    assert expected in output


def test_ledger_duplicate_and_missing_warning_fail(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    ledger_path = migration / "generation-warnings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["unsupported"].append(dict(ledger["generated"][0]))
    ledger["warnings"] = [row for row in ledger["warnings"] if row["code"] != "conditional_workflow_generation_unsupported"]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 1
    assert "ACCOUNTING_DUPLICATE_SOURCE" in output
    assert "WORKFLOW_WARNING_MISSING" in output


AI_DEFERRED_PARAGRAPH = (
    '<p class="warning"><strong>deferred_shared_ai_engine:</strong> infrastructure can proceed, but AI model, '
    "adapter, estimate, and generation remain deferred and resume from the provider-neutral profile.</p>"
)


def _no_ai_design(migration: Path) -> None:
    design_path = migration / "aws-design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    design["ai_track"] = None
    design_path.write_text(json.dumps(design), encoding="utf-8")


def _drop_ai_ledger_warning(migration: Path) -> None:
    ledger_path = migration / "generation-warnings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["warnings"] = [row for row in ledger["warnings"] if row["code"] != "deferred_shared_ai_engine"]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")


def test_no_ai_report_passes_when_ai_track_is_null(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _no_ai_design(migration)
    _drop_ai_ledger_warning(migration)
    html = report.read_text(encoding="utf-8")
    assert AI_DEFERRED_PARAGRAPH in html
    report.write_text(html.replace(AI_DEFERRED_PARAGRAPH, ""), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


def test_no_ai_report_rejects_stale_ai_deferral_text(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _no_ai_design(migration)
    # Ledger still carries the AI warning and the report still names the deferral.
    code, output = run(report, migration)
    assert code == 1
    assert "AI_DEFERRED_WARNING_UNEXPECTED" in output
    assert "AI_DEFERRED_WARNING_MISSING" not in output
    # Clean ledger but stale report prose is still rejected.
    _drop_ai_ledger_warning(migration)
    code, output = run(report, migration)
    assert code == 1
    assert "AI_DEFERRED_WARNING_UNEXPECTED" in output


def test_deferred_ai_track_still_requires_warning_and_prose(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _drop_ai_ledger_warning(migration)
    code, output = run(report, migration)
    assert code == 1
    assert "AI_DEFERRED_WARNING_MISSING" in output


def _set_current_costs(migration: Path, source: str, render_monthly) -> None:
    estimate_path = migration / "estimation-infra.json"
    estimate = json.loads(estimate_path.read_text(encoding="utf-8"))
    estimate["current_costs"] = {"source": source, "render_monthly": render_monthly, "baseline_note": "no invoice, export, or user-stated amount", "breakdown": {}}
    estimate_path.write_text(json.dumps(estimate), encoding="utf-8")


def _set_current_render_cell(report: Path, text: str) -> None:
    html = report.read_text(encoding="utf-8")
    cell = '<td data-cost-key="current_render">$123.45</td>'
    assert cell in html
    report.write_text(html.replace(cell, f'<td data-cost-key="current_render">{text}</td>'), encoding="utf-8")


def test_unavailable_render_baseline_passes_with_literal_text(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "unavailable", None)
    _set_current_render_cell(report, "Unavailable")
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


def test_unavailable_render_baseline_rejects_numeric_cell(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "unavailable", None)
    _set_current_render_cell(report, "$0.00")
    code, output = run(report, migration)
    assert code == 1
    assert "COST_CURRENT_RENDER_UNAVAILABLE_TEXT_MISMATCH" in output


def test_null_baseline_with_other_source_is_still_missing(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "user_stated", None)
    _set_current_render_cell(report, "unavailable")
    code, output = run(report, migration)
    assert code == 1
    assert "COST_CURRENT_RENDER_MISSING" in output
    assert "UNAVAILABLE_TEXT_MISMATCH" not in output


def test_present_baseline_keeps_exact_check(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_render_cell(report, "unavailable")
    code, output = run(report, migration)
    assert code == 1
    assert "COST_CURRENT_RENDER_MISMATCH" in output


def test_relative_report_path_is_rejected(tmp_path: Path) -> None:
    migration, _ = prepared(tmp_path)
    code, output = run(Path("migration-report.html"), migration)
    assert code == 1
    assert "PATHS_MUST_BE_ABSOLUTE" in output


def test_validator_is_skill_local() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.parent.name == "scripts"
    assert SCRIPT.parent.parent.name == "render-to-aws"
