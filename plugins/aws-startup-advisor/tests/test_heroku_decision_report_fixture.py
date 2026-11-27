"""Both heroku decision-report goldens pass the two-command report gate, and each
half of the gate still bites.

heroku-to-aws validates its reports with two commands: the shared validator
(`scripts/validate-migration-report.py --profile heroku`) for the structure / content
standard, then the heroku add-on (`skills/heroku-to-aws/scripts/validate-heroku-
migration-report.py`) for the heroku-only rules. This test runs both on
`fixtures/heroku-decision-gate/*/decision-report.html` in decision mode, runs the
fixtures' own oracles (`check_expected_decide*.py`) on scratch copies, and proves the
negative paths: an altered Balanced figure, a bare week range, a dropped
`developer-workflow` section and a dropped "What would flip this" list fail the shared
validator with named lines; a `.phase-status.json` that says Generate completed fails the
add-on with its named line.

The full-mode golden (`fixtures/heroku-generate/after-generate/migration-report.html`) is
covered by test_heroku_generate_report_fixture.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 — test-only, list args, no shell, committed script paths
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "heroku-decision-gate"
FIXTURES = ("after-decide-complete", "retained-execution-pack")
SHARED = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
LOCAL = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "validate-heroku-migration-report.py"
ORACLE = FIXTURE_ROOT / "check_expected_decide.py"
ORACLE_RETAINED = FIXTURE_ROOT / "check_expected_decide_with_retained_pack.py"

GOLDEN_BALANCED = '<strong data-cost-key="aws_monthly_balanced">Est. $210/mo</strong>'
ALTERED_BALANCED = '<strong data-cost-key="aws_monthly_balanced">Est. $215/mo</strong>'
FLIP_ITEM = "<li>What would flip this: a confirmed always-on traffic pattern would raise the AWS compute estimate materially.</li>"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — list args, no shell, committed script paths only
        [sys.executable, *args], capture_output=True, text=True, check=False
    )


def _shared(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(SHARED), str(run_dir / "decision-report.html"),
        "--profile", "heroku", "--mode", "decision",
        "--estimation-infra", str(run_dir / "estimation-infra.json"),
        "--migration-dir", str(run_dir),
    )


def _local(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        str(LOCAL), str(run_dir / "decision-report.html"),
        "--mode", "decision", "--migration-dir", str(run_dir),
    )


def _copy(tmp_path: Path, name: str) -> Path:
    run_dir = tmp_path / name
    shutil.copytree(FIXTURE_ROOT / name, run_dir)
    return run_dir


@pytest.mark.parametrize("name", FIXTURES)
def test_golden_passes_both_validators(name: str) -> None:
    run_dir = FIXTURE_ROOT / name
    shared = _shared(run_dir)
    assert shared.returncode == 0, shared.stdout + shared.stderr
    assert shared.stdout.startswith("REPORT_OK"), shared.stdout
    assert "profile=heroku" in shared.stdout
    local = _local(run_dir)
    assert local.returncode == 0, local.stdout + local.stderr
    assert local.stdout.startswith("REPORT_OK"), local.stdout


def test_goldens_pass_their_oracles(tmp_path: Path) -> None:
    result = _run(str(ORACLE), str(_copy(tmp_path, "after-decide-complete")))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
    result = _run(str(ORACLE_RETAINED), str(_copy(tmp_path, "retained-execution-pack")))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def _mutate(run_dir: Path, old: str, new: str) -> None:
    report = run_dir / "decision-report.html"
    html = report.read_text(encoding="utf-8")
    assert html.count(old) == 1, f"fixture no longer carries exactly one {old!r}"
    report.write_text(html.replace(old, new), encoding="utf-8")


def test_altered_balanced_figure_fails_shared_validator(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path, "after-decide-complete")
    _mutate(run_dir, GOLDEN_BALANCED, ALTERED_BALANCED)
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'cost figure mismatch: data-cost-key="aws_monthly_balanced"' in result.stderr, result.stderr
    assert "projected_costs.aws_monthly_balanced = $210" in result.stderr
    oracle = _run(str(ORACLE), str(run_dir))
    assert oracle.returncode == 1, oracle.stdout
    assert "fails the shared validator" in oracle.stdout


def test_bare_week_range_fails_shared_validator(tmp_path: Path) -> None:
    """Regression guard for the removed planning band: a quoted week range in the
    timeline is a readability failure under the heroku profile."""
    run_dir = _copy(tmp_path, "after-decide-complete")
    _mutate(run_dir, "<p>Shape: Full cutover: one migration window.", "<p>Shape: Full cutover: one migration window, about 2-6 weeks.")
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "readability: bare week-range estimate" in result.stderr, result.stderr


def test_missing_developer_workflow_fails_shared_validator(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path, "after-decide-complete")
    html = (run_dir / "decision-report.html").read_text(encoding="utf-8")
    start = html.index('<section id="developer-workflow">')
    end = html.index("</section>", start) + len("</section>")
    html = html[:start] + html[end:]
    html = html.replace('    <li><a href="#developer-workflow">Developer workflow</a></li>\n', "")
    (run_dir / "decision-report.html").write_text(html, encoding="utf-8")
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'missing required <section id="developer-workflow">' in result.stderr, result.stderr


def test_dropped_flip_condition_fails_shared_validator(tmp_path: Path) -> None:
    run_dir = _copy(tmp_path, "after-decide-complete")
    _mutate(run_dir, FLIP_ITEM, "")
    result = _shared(run_dir)
    assert result.returncode == 1, result.stdout + result.stderr
    assert '"What would flip this" list' in result.stderr, result.stderr


def test_completed_generate_fails_heroku_addon(tmp_path: Path) -> None:
    """The heroku-only pre-execution rule: a decide-complete cycle whose own
    .phase-status.json says Generate already ran is not a decision report."""
    run_dir = _copy(tmp_path, "after-decide-complete")
    status_path = run_dir / ".phase-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["phases"]["generate"] = "completed"
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    shared = _shared(run_dir)
    assert shared.returncode == 0, shared.stdout + shared.stderr  # not the shared validator's rule
    local = _local(run_dir)
    assert local.returncode == 1, local.stdout + local.stderr
    assert "decision mode: .phase-status.json phases.generate is 'completed'" in local.stderr, local.stderr
