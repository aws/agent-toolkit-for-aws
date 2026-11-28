"""Tests for the render-only migration report validator.

Structure, readability, accessibility, and the shared cost anchors are owned by
the plugin-root ``scripts/validate-migration-report.py``; these tests cover only
the render-specific checks this script retains, each with a passing and a
failing path.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404 - fixed local command, no shell
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("validate-render-migration-report.py")
SKILL_ROOT = Path(__file__).resolve().parents[1]
EXPECTED = SKILL_ROOT / "fixtures/expected"
GENERATED = EXPECTED / "generated"

RR_WEB_ROW = '<tr data-source-resource-id="rr-web" data-aws-service="ECS on Fargate">'
RR_DISK_ROW = '<tr data-source-resource-id="rr-disk" data-aws-service="Amazon EFS"><td>rr-disk</td><td>Persistent disk</td><td>Amazon EFS</td>'
DELTA_CELL = '<td class="savings" data-cost-key="delta">+$45</td>'
LIKE_FOR_LIKE_CELL = '<td data-cost-key="like_for_like_monthly">$358</td>'
CURRENT_CELL = '<td data-cost-key="current_monthly">$123</td>'


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


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _drop_toc_link(text: str, section_id: str) -> str:
    pattern = re.compile(rf'<li><a href="#{re.escape(section_id)}">[^<]*</a></li>\s*')
    assert len(pattern.findall(text)) == 1, section_id
    return pattern.sub("", text, count=1)


def _drop_section(text: str, section_id: str) -> str:
    pattern = re.compile(rf'<section id="{re.escape(section_id)}">.*?</section>\s*', re.DOTALL)
    assert len(pattern.findall(text)) == 1, section_id
    return _drop_toc_link(pattern.sub("", text, count=1), section_id)


def _drop_table_row(text: str, marker: str) -> str:
    pattern = re.compile(rf"<tr>(?:(?!</tr>).)*{re.escape(marker)}(?:(?!</tr>).)*</tr>\s*", re.DOTALL)
    assert len(pattern.findall(text)) == 1, marker
    return pattern.sub("", text, count=1)


def test_complete_report_passes_with_exact_status(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda text: _replace_once(text, RR_WEB_ROW, RR_WEB_ROW.replace("ECS on Fargate", "Amazon App Runner")), "TARGET_MAPPING_MISMATCH"),
        (lambda text: _replace_once(text, RR_DISK_ROW, RR_DISK_ROW.replace("<td>Amazon EFS</td>", "<td>Elastic file storage</td>")), "TARGET_VISIBLE_TEXT_MISMATCH"),
        (lambda text: _replace_once(text, RR_DISK_ROW, RR_DISK_ROW.replace(' data-aws-service="Amazon EFS"', "")), "TARGET_ROW_ATTRIBUTES_INCOMPLETE"),
        (lambda text: _replace_once(text, DELTA_CELL, DELTA_CELL.replace("+$45", "+$99")), "COST_DELTA_MISMATCH"),
        (lambda text: _replace_once(text, DELTA_CELL, DELTA_CELL.replace(' data-cost-key="delta"', "")), "COST_DELTA_MISSING"),
        (lambda text: _replace_once(text, LIKE_FOR_LIKE_CELL, LIKE_FOR_LIKE_CELL.replace("$358", "$999")), "COST_LIKE_FOR_LIKE_MONTHLY_MISMATCH"),
        (lambda text: _replace_once(text, LIKE_FOR_LIKE_CELL, LIKE_FOR_LIKE_CELL.replace("$358", "$359")), "COST_LIKE_FOR_LIKE_MONTHLY_MISMATCH"),
        (lambda text: _replace_once(text, LIKE_FOR_LIKE_CELL, LIKE_FOR_LIKE_CELL.replace(' data-cost-key="like_for_like_monthly"', "")), "COST_LIKE_FOR_LIKE_MONTHLY_MISSING"),
        (lambda text: _replace_once(text, LIKE_FOR_LIKE_CELL, LIKE_FOR_LIKE_CELL + LIKE_FOR_LIKE_CELL), "COST_LIKE_FOR_LIKE_MONTHLY_MISSING"),
        (lambda text: _replace_once(text, 'data-accounted-count="15"', 'data-accounted-count="14"'), "REPORT_ACCOUNTED_COUNT_MISMATCH"),
        (lambda text: text.replace("build-once", "single-build"), "CONTENT_EXEC_ARCHITECTURE_BUILD-ONCE"),
        (lambda text: text.replace("Database Migration Service", "replication tooling"), "CONTENT_MIGRATION_DATA_DATABASE_MIGRATION_SERVICE"),
        (lambda text: text.replace("pre-copy", "initial copy"), "CONTENT_MIGRATION_STORAGE_PRE-COPY"),
        (lambda text: text.replace("serving deploy", "live deploy"), "CONTENT_MIGRATION_DEPLOYMENT_SERVING_DEPLOY"),
        (lambda text: _replace_once(text, "establish writer quiescence, apply the final data deltas", "establish pause writes, apply the final data deltas"), "CONTENT_CUTOVER_WRITER_QUIESCENCE"),
        (lambda text: _replace_once(text, "honor\n         the source retention window", "honor\n         the source hold window"), "CONTENT_ROLLBACK_SOURCE_RETENTION"),
        (lambda text: _replace_once(text, "cache eviction and persistence behavior, disk", "eviction and persistence behavior, disk"), "CONTENT_VERIFICATION_CACHE"),
        (lambda text: _drop_section(text, "cutover"), "SECTION_CUTOVER_MISSING"),
        (lambda text: _drop_toc_link(text, "cutover"), "TOC_RENDER_SECTION_MISSING"),
        (lambda text: _drop_table_row(text, "aws_guardduty_detector.baseline"), "SECURITY_BASELINE_RESOURCE_MISSING"),
        (lambda text: _drop_section(text, "appendix-security"), "SECTION_APPENDIX_SECURITY_MISSING"),
        (lambda text: text.replace("deferred_shared_ai_engine", "AI later"), "AI_DEFERRED_STATE_MISSING"),
        (lambda text: text.replace("</footer>", " contact user@example.com</footer>"), "PRIVACY_EMAIL"),
        (lambda text: text.replace("</footer>", " rendered from /Users/dev/render</footer>"), "PRIVACY_LOCAL_PATH"),
    ],
)
def test_report_mutations_fail_closed(tmp_path: Path, mutation, expected: str) -> None:
    migration, report = prepared(tmp_path)
    report.write_text(mutation(report.read_text(encoding="utf-8")), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 1
    assert output.startswith("REPORT_FAIL |")
    assert expected in output


def test_report_without_baseline_tf_skips_the_security_check(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    (migration / "terraform" / "baseline.tf").unlink()
    report.write_text(_drop_section(report.read_text(encoding="utf-8"), "appendix-security"), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


def test_shared_validator_checks_are_not_duplicated_locally(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    html = report.read_text(encoding="utf-8")
    html = _replace_once(html, '<html lang="en">', "<html>")
    html = html.replace('scope="col"', "", 1)
    report.write_text(html, encoding="utf-8")
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


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


def test_unsupported_workflow_requires_deferred_surface_prose(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    ledger_path = migration / "generation-warnings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    workflow = next(row for row in ledger["generated"] if row["source_resource_id"] == "rr-workflow")
    ledger["generated"].remove(workflow)
    ledger["unsupported"].append({**workflow, "target_files": []})
    ledger["accounting"]["generated_count"] -= 1
    ledger["accounting"]["unsupported_count"] += 1
    ledger["warnings"].append({
        "code": "conditional_workflow_generation_unsupported",
        "subject": "rr-workflow",
        "detail": "The Workflow declares semantics outside the tested set and emits no Terraform.",
        "blocking": False,
    })
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert "conditional_workflow_generation_unsupported" not in report.read_text(encoding="utf-8")
    code, output = run(report, migration)
    assert code == 1
    assert "WORKFLOW_LIMIT_MISSING" in output
    assert "WORKFLOW_WARNING_MISSING" not in output


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


def _set_current_monthly_cell(report: Path, text: str) -> None:
    html = report.read_text(encoding="utf-8")
    report.write_text(_replace_once(html, CURRENT_CELL, CURRENT_CELL.replace("$123", text)), encoding="utf-8")


def test_unavailable_render_baseline_passes_with_literal_text(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "unavailable", None)
    _set_current_monthly_cell(report, "Unavailable")
    code, output = run(report, migration)
    assert code == 0, output
    assert output == "REPORT_OK\n"


def test_unavailable_render_baseline_rejects_numeric_cell(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "unavailable", None)
    _set_current_monthly_cell(report, "$0.00")
    code, output = run(report, migration)
    assert code == 1
    assert "COST_CURRENT_MONTHLY_UNAVAILABLE_TEXT_MISMATCH" in output


def test_null_baseline_with_other_source_is_still_missing(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_costs(migration, "user_stated", None)
    _set_current_monthly_cell(report, "unavailable")
    code, output = run(report, migration)
    assert code == 1
    assert "COST_CURRENT_MONTHLY_MISSING" in output
    assert "UNAVAILABLE_TEXT_MISMATCH" not in output


def test_numeric_baseline_dollars_are_owned_by_the_shared_validator(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_current_monthly_cell(report, "unavailable")
    code, output = run(report, migration)
    assert "COST_CURRENT_MONTHLY" not in output
    assert code == 0, output


def test_relative_report_path_is_rejected(tmp_path: Path) -> None:
    migration, _ = prepared(tmp_path)
    code, output = run(Path("migration-report.html"), migration)
    assert code == 1
    assert "PATHS_MUST_BE_ABSOLUTE" in output


def test_validator_is_skill_local() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.parent.name == "scripts"
    assert SCRIPT.parent.parent.name == "render-to-aws"
def _set_like_for_like(migration: Path, value: object) -> None:
    path = migration / "estimation-infra.json"
    estimate = json.loads(path.read_text(encoding="utf-8"))
    estimate["scenarios"]["like_for_like"]["known_cost_monthly_usd"] = value
    path.write_text(json.dumps(estimate), encoding="utf-8")
def test_like_for_like_anchor_must_equal_the_estimate_value(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path)
    _set_like_for_like(migration, 999)
    code, output = run(report, migration)
    assert code == 1
    assert "COST_LIKE_FOR_LIKE_MONTHLY_MISMATCH" in output
def test_like_for_like_anchor_uses_whole_dollar_half_even_rounding(tmp_path: Path) -> None:
    for value, shown, ok in ((358.5, "$358", True), (359.5, "$360", True), (359.5, "$359", False), (358.4, "$358", True), (358.6, "$358", False)):
        migration, report = prepared(tmp_path / f"{value}-{shown}")
        _set_like_for_like(migration, value)
        report.write_text(report.read_text(encoding="utf-8").replace(LIKE_FOR_LIKE_CELL, LIKE_FOR_LIKE_CELL.replace("$358", shown)), encoding="utf-8")
        code, output = run(report, migration)
        assert (code == 0) is ok, (value, shown, output)
def test_like_for_like_estimate_value_missing_or_invalid_fails(tmp_path: Path) -> None:
    migration, report = prepared(tmp_path / "invalid")
    _set_like_for_like(migration, "not-a-number")
    code, output = run(report, migration)
    assert code == 1 and "COST_LIKE_FOR_LIKE_MONTHLY_SOURCE_INVALID" in output
    migration, report = prepared(tmp_path / "missing")
    path = migration / "estimation-infra.json"
    estimate = json.loads(path.read_text(encoding="utf-8"))
    del estimate["scenarios"]["like_for_like"]
    path.write_text(json.dumps(estimate), encoding="utf-8")
    code, output = run(report, migration)
    assert code == 1 and "COST_LIKE_FOR_LIKE_MONTHLY_MISSING" in output
