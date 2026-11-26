"""The render-to-aws Generate golden (fixtures/expected/generated/migration-report.html) stays
green under BOTH report validators, and each validator still bites on its own contract.

The shared validator (scripts/validate-migration-report.py) owns structure, readability,
accessibility, and the shared cost anchors; the render-local validator
(skills/render-to-aws/scripts/validate-render-migration-report.py) owns the render-only
checks (mapping rows, accounting, ledger, required phrases). This test runs both on the
golden, proves the negative paths each one is responsible for, and pins the render fixture
facts later steps rely on (stable appendix lettering, the accounting split, and the four
shared anchors inside exec-costs).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PLUGIN_ROOT / "skills" / "render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures" / "expected"
GOLDEN = EXPECTED / "generated"
REPORT = GOLDEN / "migration-report.html"
SHARED_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
LOCAL_VALIDATOR = SKILL_ROOT / "scripts" / "validate-render-migration-report.py"
ESTIMATE = EXPECTED / "estimation-infra.json"
DESIGN = EXPECTED / "aws-design.json"

GOLDEN_OPTIMIZED = '<td data-cost-key="aws_monthly_optimized">$296</td>'
GOLDEN_CURRENT = '<td data-cost-key="current_monthly">$123</td>'
RR_WEB_ROW_RE = re.compile(r'<tr data-source-resource-id="rr-web" [^>]*>.*?</tr>\s*', re.DOTALL)
APPENDIX_LABELS = (
    "Appendix A —",
    "Appendix A.1 —",
    "Appendix B —",
    "Appendix C —",
    "Appendix E —",
    "Appendix I —",
    "Appendix J —",
)
ACCOUNTING_SPLIT = "15 design rows · 13 generated · 2 consumed topology · 0 deferred · 0 unsupported"
SHARED_ANCHORS = ("current_monthly", "aws_monthly_premium", "aws_monthly_balanced", "aws_monthly_optimized")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — list args, no shell, committed script paths only
        [sys.executable, *args], capture_output=True, text=True, check=False
    )


def _shared(report: Path, migration_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(SHARED_VALIDATOR), str(report),
        "--estimation-infra", str(ESTIMATE), "--aws-design", str(DESIGN), "--migration-dir", str(migration_dir),
    )


def _local(report: Path, migration_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(str(LOCAL_VALIDATOR), str(report), "--migration-dir", str(migration_dir))


def _altered_copy(tmp_path: Path, old: str, new: str) -> tuple[Path, Path]:
    """Copy fixtures/expected to tmp and replace `old` (exactly one occurrence) in the report."""
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    report = root / "generated" / "migration-report.html"
    html = report.read_text(encoding="utf-8")
    assert html.count(old) == 1, f"fixture no longer carries exactly one {old!r}"
    report.write_text(html.replace(old, new), encoding="utf-8")
    return root, report


def test_generate_golden_passes_shared_validator() -> None:
    result = _shared(REPORT, GOLDEN)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("REPORT_OK"), result.stdout


def test_generate_golden_passes_local_validator() -> None:
    result = _local(REPORT, EXPECTED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "REPORT_OK\n", result.stdout


def test_altered_optimized_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_OPTIMIZED, GOLDEN_OPTIMIZED.replace("$296", "$300"))
    result = _shared(report, root / "generated")
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="aws_monthly_optimized"' in result.stderr, result.stderr
    assert "projected_costs.aws_monthly_optimized = $296" in result.stderr, result.stderr


def test_altered_current_spend_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "$120"))
    result = _shared(report, root / "generated")
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="current_monthly"' in result.stderr, result.stderr
    assert "current_costs.render_monthly = $123" in result.stderr, result.stderr


def test_numeric_baseline_rendered_as_unavailable_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "unavailable"))
    result = _shared(report, root / "generated")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "renders no dollar amount" in result.stderr, result.stderr


def test_deleted_target_row_fails_local_validator(tmp_path: Path) -> None:
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    report = root / "generated" / "migration-report.html"
    html = report.read_text(encoding="utf-8")
    assert len(RR_WEB_ROW_RE.findall(html)) == 1
    report.write_text(RR_WEB_ROW_RE.sub("", html, count=1), encoding="utf-8")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TARGET_MAPPING_MISMATCH" in result.stdout + result.stderr


GOLDEN_PREMIUM = '<td data-cost-key="aws_monthly_premium">$394</td>'
def test_removed_optimized_anchor_fails_local_validator(tmp_path: Path) -> None:
    # The shared pass treats optimized as optional; the render pass requires it (at base: COST_RIGHT_SIZED_MISSING).
    root, report = _altered_copy(tmp_path, GOLDEN_OPTIMIZED, "<td>$999</td>")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_OPTIMIZED_MISSING" in result.stdout + result.stderr
def test_removed_premium_anchor_fails_local_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_PREMIUM, "<td>$888</td>")
    result = _local(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_PREMIUM_MISSING" in result.stdout + result.stderr
def test_projected_costs_that_disagree_with_scenarios_fail_local_validator(tmp_path: Path) -> None:
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    estimate_path = root / "estimation-infra.json"
    estimate = json.loads(estimate_path.read_text(encoding="utf-8"))
    estimate["projected_costs"]["aws_monthly_balanced"] = 410
    estimate["projected_costs"]["aws_monthly_optimized"] = 330
    estimate_path.write_text(json.dumps(estimate), encoding="utf-8")
    result = _local(root / "generated" / "migration-report.html", root)
    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "COST_AWS_MONTHLY_BALANCED_SCENARIO_MISMATCH" in output
    assert "COST_AWS_MONTHLY_OPTIMIZED_SCENARIO_MISMATCH" in output
def test_golden_pins_lettering_accounting_and_anchor_placement() -> None:
    html = REPORT.read_text(encoding="utf-8")
    headings = re.findall(r"<h2>([^<]*)", html)
    toc = re.search(r'<nav class="toc"[^>]*>(.*?)</nav>', html, re.DOTALL)
    assert toc is not None
    for label in APPENDIX_LABELS:
        assert any(heading.startswith(label) for heading in headings), label
        assert label in toc.group(1), label
    assert html.count('data-accounted-count="15"') == 1
    assert ACCOUNTING_SPLIT in html
    exec_costs = re.search(r'<section id="exec-costs">(.*?)</section>', html, re.DOTALL)
    assert exec_costs is not None
    for key in SHARED_ANCHORS:
        anchor = f'data-cost-key="{key}"'
        assert html.count(anchor) == 1, key
        assert anchor in exec_costs.group(1), key
    assert "0611-0606" not in html
