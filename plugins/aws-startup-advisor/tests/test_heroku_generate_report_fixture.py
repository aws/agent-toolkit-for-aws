"""The heroku full-mode report golden (fixtures/heroku-generate/after-generate/
migration-report.html) passes the two-command report gate and its oracle, and each half
of the gate still bites.

heroku-to-aws validates `migration-report.html` with two commands: the shared validator
(`scripts/validate-migration-report.py --profile heroku --mode full`) for the structure /
content standard, then the heroku add-on (`skills/heroku-to-aws/scripts/validate-heroku-
migration-report.py --mode full`) for the heroku-only rules. This test runs both on the
golden, runs the fixture's own oracle (`check_expected_generate.py`) on a scratch copy, and
proves the negative paths on scratch copies: a dropped `exec-risks` section, a bare "Stay if"
heading, a dropped `appendix-optimization` (Appendix B.1), an altered Balanced figure and a
decision-summary whose only verdict-ish class is `verdict-headline` each fail the shared
validator with a named line, while a compound `class="verdict callout"` still carries the
`verdict` token and passes. Each mutation first asserts its target string
occurs exactly once in the golden, so a silent fixture edit cannot turn a negative into a
no-op.

The decision-mode goldens are covered by test_heroku_decision_report_fixture.py.
"""
from __future__ import annotations

import shutil
import subprocess  # nosec B404 — test-only, list args, no shell, committed script paths
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "heroku-generate"
GOLDEN = FIXTURE_ROOT / "after-generate"
SHARED = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
LOCAL = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "validate-heroku-migration-report.py"
ORACLE = FIXTURE_ROOT / "check_expected_generate.py"

GOLDEN_BALANCED = '<span data-cost-key="aws_monthly_balanced">Est. $210/mo</span>'
ALTERED_BALANCED = '<span data-cost-key="aws_monthly_balanced">Est. $215/mo</span>'
STAY_HEADING = "<h3>Stay entirely if</h3>"
RISKS_TOC_LINE = '    <li><a href="#exec-risks">Top risks</a></li>\n'
VERDICT_CALLOUT_OPEN = '<div class="verdict">'
VERDICT_MESSAGE = "recommendation block exists but decision-summary has no verdict banner"
B1_TOC_LINE = '    <li><a href="#appendix-optimization">Appendix B.1 — Savings Plans and Reserved Instances</a></li>\n'


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — list args, no shell, committed script paths only
        [sys.executable, *args], capture_output=True, text=True, check=False
    )


def _shared(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(SHARED), str(run_dir / "migration-report.html"),
        "--profile", "heroku", "--mode", "full",
        "--estimation-infra", str(run_dir / "estimation-infra.json"),
        "--migration-dir", str(run_dir),
    )


def _local(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(LOCAL), str(run_dir / "migration-report.html"),
        "--mode", "full", "--migration-dir", str(run_dir),
    )


def _copy(tmp_path: Path) -> Path:
    run_dir = tmp_path / "after-generate"
    shutil.copytree(GOLDEN, run_dir)
    return run_dir


def _mutate(run_dir: Path, old: str, new: str) -> None:
    report = run_dir / "migration-report.html"
    html = report.read_text(encoding="utf-8")
    assert html.count(old) == 1, f"fixture no longer carries exactly one {old!r}"
    report.write_text(html.replace(old, new), encoding="utf-8")


def _drop_section(run_dir: Path, section_id: str, toc_line: str) -> None:
    report = run_dir / "migration-report.html"
    html = report.read_text(encoding="utf-8")
    opener = f'<section id="{section_id}">'
    assert html.count(opener) == 1, f"fixture no longer carries exactly one {opener!r}"
    assert html.count(toc_line) == 1, f"fixture no longer carries exactly one {toc_line!r}"
    start = html.index(opener)
    end = html.index("</section>", start) + len("</section>\n")
    html = html[:start] + html[end:]
    report.write_text(html.replace(toc_line, ""), encoding="utf-8")


def test_golden_passes_both_validators() -> None:
    shared = _shared(GOLDEN)
    assert shared.returncode == 0, shared.stdout + shared.stderr
    assert shared.stdout.startswith("REPORT_OK"), shared.stdout
    assert "profile=heroku" in shared.stdout
    local = _local(GOLDEN)
    assert local.returncode == 0, local.stdout + local.stderr
    assert local.stdout.startswith("REPORT_OK"), local.stdout


def test_golden_passes_its_oracle(tmp_path: Path) -> None:
    result = _run(str(ORACLE), str(_copy(tmp_path)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("PASS"), result.stdout


def test_missing_exec_risks_fails_shared_validator(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path)
    _drop_section(run_dir, "exec-risks", RISKS_TOC_LINE)
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'missing required <section id="exec-risks">' in result.stderr, result.stderr


def test_bare_stay_if_heading_fails_shared_validator(tmp_path: Path) -> None:
    """The stay-if heading rule is no longer skipped under --profile heroku."""
    run_dir = _copy(tmp_path)
    _mutate(run_dir, STAY_HEADING, "<h3>Stay if</h3>")
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert '"Stay entirely if" heading' in result.stderr, result.stderr


def test_missing_appendix_optimization_fails_shared_validator(tmp_path: Path) -> None:
    """Appendix B.1 is in the heroku full set and the estimate carries Savings Plan rows."""
    run_dir = _copy(tmp_path)
    _drop_section(run_dir, "appendix-optimization", B1_TOC_LINE)
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'missing required <section id="appendix-optimization">' in result.stderr, result.stderr
    assert "no Savings Plans data row" in result.stderr, result.stderr


def test_altered_balanced_figure_fails_shared_validator_and_oracle(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path)
    _mutate(run_dir, GOLDEN_BALANCED, ALTERED_BALANCED)
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="aws_monthly_balanced"' in result.stderr, result.stderr
    assert "projected_costs.aws_monthly_balanced = $210" in result.stderr
    oracle = _run(str(ORACLE), str(run_dir))
    assert oracle.returncode == 1, oracle.stdout
    assert "fails the shared validator" in oracle.stdout
    assert "aws_monthly_balanced renders 'Est. $215/mo'" in oracle.stdout, oracle.stdout


def test_verdict_headline_alone_fails_shared_validator(tmp_path: Path) -> None:
    """The verdict rule wants the `verdict` class TOKEN. `verdict-headline` on the headline
    is not the one-sentence recommendation callout (decision core item 1a) and must not
    satisfy it — the old word-boundary regex treated the hyphen as a word boundary and did."""
    run_dir = _copy(tmp_path)
    _mutate(run_dir, VERDICT_CALLOUT_OPEN, '<div class="verdict-headline">')
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert VERDICT_MESSAGE in result.stderr, result.stderr


def test_compound_verdict_class_passes_shared_validator(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path)
    _mutate(run_dir, VERDICT_CALLOUT_OPEN, '<div class="verdict callout">')
    result = _shared(run_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("REPORT_OK"), result.stdout
