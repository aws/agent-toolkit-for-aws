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

GOLDEN_OPTIMIZED = '<td data-cost-key="aws_monthly_optimized">$244</td>'
GOLDEN_CURRENT = '<td data-cost-key="current_monthly">$123</td>'
RR_WEB_ROW_RE = re.compile(r'<tr data-source-resource-id="rr-web" [^>]*>.*?</tr>\s*', re.DOTALL)
APPENDIX_LABELS = (
    "Appendix A —",
    "Appendix A.1 —",
    "Appendix B —",
    "Appendix B.1 —",
    "Appendix C —",
    "Appendix E —",
    "Appendix F —",
    "Appendix G —",
    "Appendix H —",
    "Appendix I —",
    "Appendix J —",
)
# Executive add-ons rendered after exec-costs (decision core § Cost Optimization, § What-if,
# and the render-declared security teaser). Each is present exactly once and TOC-linked.
EXEC_SECTIONS = ("exec-optimization", "what-if-scenarios", "exec-security-teaser")
ACCOUNTING_SPLIT = "15 design rows · 13 generated · 2 consumed topology · 0 deferred · 0 unsupported"
SHARED_ANCHORS = ("current_monthly", "aws_monthly_premium", "aws_monthly_balanced", "aws_monthly_optimized")
BASELINE_TF = GOLDEN / "terraform" / "baseline.tf"
WORKSHOP_INDEX = EXPECTED / "scenarios" / "index.json"
BASELINE_RESOURCE_RE = re.compile(r'resource "([a-z0-9_]+)" "([a-z0-9_]+)"')
# Appendix F's questions table header; the shared validator reads the FIRST <thead> of
# appendix-config, so this exact string is what the "Source" negative mutates.
CONFIG_THEAD = (
    '<thead><tr><th scope="col">Question / assumption</th><th scope="col">Your choice</th>'
    '<th scope="col">Source</th><th scope="col">Design consequence</th></tr></thead>'
)


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


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Copy fixtures/expected (artifacts, scenarios/index.json and generated/) to tmp."""
    root = tmp_path / "expected"
    shutil.copytree(EXPECTED, root, ignore=shutil.ignore_patterns("generated-variants", "workflow-contracts", ".terraform*"))
    return root, root / "generated" / "migration-report.html"


def _altered_copy(tmp_path: Path, old: str, new: str) -> tuple[Path, Path]:
    """Copy fixtures/expected to tmp and replace `old` (exactly one occurrence) in the report."""
    root, report = _copy_fixture(tmp_path)
    html = report.read_text(encoding="utf-8")
    assert html.count(old) == 1, f"fixture no longer carries exactly one {old!r}"
    report.write_text(html.replace(old, new), encoding="utf-8")
    return root, report


def _drop_toc_link(text: str, section_id: str) -> str:
    pattern = re.compile(rf'<li><a href="#{re.escape(section_id)}">[^<]*</a></li>\s*')
    assert len(pattern.findall(text)) == 1, section_id
    return pattern.sub("", text, count=1)


def _drop_section(text: str, section_id: str) -> str:
    """Remove a whole <section id=…> and its TOC link (same shape as the render-local tests)."""
    pattern = re.compile(rf'<section id="{re.escape(section_id)}">.*?</section>\s*', re.DOTALL)
    assert len(pattern.findall(text)) == 1, section_id
    return _drop_toc_link(pattern.sub("", text, count=1), section_id)


def _dropped_section_copy(tmp_path: Path, section_id: str) -> tuple[Path, Path]:
    root, report = _copy_fixture(tmp_path)
    report.write_text(_drop_section(report.read_text(encoding="utf-8"), section_id), encoding="utf-8")
    return root, report


def _section(html: str, section_id: str) -> str:
    match = re.search(rf'<section id="{re.escape(section_id)}">(.*?)</section>', html, re.DOTALL)
    assert match is not None, section_id
    return match.group(1)


def _tbody_rows(fragment: str) -> list[str]:
    tbody = re.search(r"<tbody>(.*?)</tbody>", fragment, re.DOTALL)
    assert tbody is not None
    return re.findall(r"<tr\b[^>]*>.*?</tr>", tbody.group(1), re.DOTALL)


def _first_cell_text(row: str) -> str:
    cell = re.search(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.DOTALL)
    assert cell is not None
    return re.sub(r"<[^>]+>", "", cell.group(1)).strip()


def test_generate_golden_passes_shared_validator() -> None:
    result = _shared(REPORT, EXPECTED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("REPORT_OK"), result.stdout
    for section_id in EXEC_SECTIONS + ("appendix-optimization", "appendix-config", "appendix-security", "appendix-security-gap"):
        assert section_id in result.stdout, f"{section_id} not reported in the validator's optional= list"


def test_generate_golden_passes_local_validator() -> None:
    result = _local(REPORT, EXPECTED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "REPORT_OK\n", result.stdout


def test_altered_optimized_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_OPTIMIZED, GOLDEN_OPTIMIZED.replace("$244", "$230"))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="aws_monthly_optimized"' in result.stderr, result.stderr
    assert "projected_costs.aws_monthly_optimized = $244" in result.stderr, result.stderr


def test_altered_current_spend_figure_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "$120"))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="current_monthly"' in result.stderr, result.stderr
    assert "current_costs.render_monthly = $123" in result.stderr, result.stderr


def test_numeric_baseline_rendered_as_unavailable_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, GOLDEN_CURRENT, GOLDEN_CURRENT.replace("$123", "unavailable"))
    result = _shared(report, root)
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
    for section_id in EXEC_SECTIONS:
        assert html.count(f'<section id="{section_id}">') == 1, section_id
        assert f'href="#{section_id}"' in toc.group(1), section_id
    # Executive order: exec-costs → exec-optimization → what-if-scenarios → exec-security-teaser → exec-timeline.
    order = ["exec-costs", *EXEC_SECTIONS, "exec-timeline"]
    positions = [html.index(f'<section id="{section_id}">') for section_id in order]
    assert positions == sorted(positions), order


def test_golden_pins_new_section_content() -> None:
    html = REPORT.read_text(encoding="utf-8")

    # Appendix B.1: exactly the two commitment rows the estimate emits, and the Optimized caveat.
    optimization = _section(html, "appendix-optimization")
    assert "not additive" in optimization
    assert [_first_cell_text(row) for row in _tbody_rows(optimization)] == ["Compute Savings Plans", "Database Savings Plans"]
    assert "not additive" in _section(html, "exec-optimization")

    # Appendix G: every resource address of the generated baseline.tf appears in the section.
    addresses = {f"{kind}.{name}" for kind, name in BASELINE_RESOURCE_RE.findall(BASELINE_TF.read_text(encoding="utf-8"))}
    assert len(addresses) == 22, sorted(addresses)
    security = _section(html, "appendix-security")
    missing = sorted(address for address in addresses if address not in security)
    assert not missing, missing

    # Appendix H: the skeleton's six minimum rows plus render's extra rows, with the four columns.
    gap = _section(html, "appendix-security-gap")
    gap_thead = re.search(r"<thead>(.*?)</thead>", gap, re.DOTALL)
    assert gap_thead is not None
    for column in ("Capability", "Render (detected)", "AWS (generated)", "Gap / action"):
        assert column in gap_thead.group(1), column
    assert len(_tbody_rows(gap)) >= 6

    # What-if: one row per scenario in scenarios/index.json, exactly one of them active.
    index = json.loads(WORKSHOP_INDEX.read_text(encoding="utf-8"))
    what_if_rows = _tbody_rows(_section(html, "what-if-scenarios"))
    assert len(what_if_rows) == len(index["scenarios"]) == 2
    assert sum('class="active-scenario"' in row for row in what_if_rows) == 1

    # Appendix I: the pricing-confidence table replaces the prose paragraph.
    assumptions = _section(html, "appendix-assumptions")
    pricing = re.search(r"<table>\s*<caption>Pricing confidence.*?</table>", assumptions, re.DOTALL)
    assert pricing is not None
    assert len(_tbody_rows(pricing.group(0))) >= 3

    # Appendix F: validator columns, one row per preferences.json question, defaulted rows flagged.
    config = _section(html, "appendix-config")
    assert CONFIG_THEAD in config
    questions = json.loads((EXPECTED / "preferences.json").read_text(encoding="utf-8"))["questions"]
    config_rows = _tbody_rows(config)
    assert len(config_rows) == len(questions) >= 30
    defaulted = sum(1 for question in questions if question["disposition"] == "defaulted")
    assert sum('class="assumption"' in row for row in config_rows) == defaulted


def test_removed_appendix_optimization_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "appendix-optimization")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'optimization_opportunities exist but no <section id="appendix-optimization">' in result.stdout + result.stderr


def test_removed_exec_optimization_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "exec-optimization")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'no <section id="exec-optimization">' in result.stdout + result.stderr


def test_removed_what_if_table_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _dropped_section_copy(tmp_path, "what-if-scenarios")
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'scenarios/index.json has ≥2 scenarios but no <section id="what-if-scenarios">' in result.stdout + result.stderr


def test_appendix_config_without_source_column_fails_shared_validator(tmp_path: Path) -> None:
    root, report = _altered_copy(tmp_path, CONFIG_THEAD, CONFIG_THEAD.replace('<th scope="col">Source</th>', '<th scope="col">Origin</th>'))
    result = _shared(report, root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'appendix-config table must include a "Source" column' in result.stdout + result.stderr
