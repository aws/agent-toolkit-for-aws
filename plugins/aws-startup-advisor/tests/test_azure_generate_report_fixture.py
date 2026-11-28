"""The azure-iac-terraform Generate golden (after-generate/migration-report.html) stays green,
and the oracle that checks it still bites.

`fixtures/azure-iac-terraform/check_expected_generate.py` runs the shared report validator
with the corpus's own estimate and design, then pins the Azure-specific facts
(both cost anchors inside exec-costs, stable appendix lettering, Appendices C/G/H/I, the
accounting split). This test runs it in CI the way the Clarify goldens are run, and proves
the negative path: a report whose current-spend figure disagrees with
current_costs.azure_monthly must fail with a cost-figure-mismatch line — that is the gap
the current_monthly fallback in validate-migration-report.py closed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform"
ASSERTER = FIXTURE / "check_expected_generate.py"
GOLDEN = FIXTURE / "after-generate"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
ESTIMATE = FIXTURE / "after-estimate" / "estimation-infra.json"
DESIGN = FIXTURE / "after-design" / "aws-design.json"

GOLDEN_ANCHOR = '<span data-cost-key="current_monthly">$4,200/mo</span>'
ALTERED_ANCHOR = '<span data-cost-key="current_monthly">$3,900/mo</span>'


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — list args, no shell, committed script paths only
        [sys.executable, *args], capture_output=True, text=True, check=False
    )


def test_generate_golden_passes_its_oracle(tmp_path: Path) -> None:
    run_dir = tmp_path / "after-generate"
    shutil.copytree(GOLDEN, run_dir)
    result = _run(str(ASSERTER), str(run_dir))
    assert result.returncode == 0, f"check_expected_generate.py failed:\n{result.stdout}{result.stderr}"


def test_generate_golden_passes_shared_validator_directly() -> None:
    result = _run(
        str(VALIDATOR), str(GOLDEN / "migration-report.html"),
        "--estimation-infra", str(ESTIMATE), "--aws-design", str(DESIGN), "--migration-dir", str(GOLDEN),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("REPORT_OK"), result.stdout


def test_altered_current_spend_figure_fails_validator_and_oracle(tmp_path: Path) -> None:
    html = (GOLDEN / "migration-report.html").read_text(encoding="utf-8")
    assert html.count(GOLDEN_ANCHOR) == 1, "fixture no longer carries the single exec-costs current_monthly anchor"
    run_dir = tmp_path / "altered"
    run_dir.mkdir()
    (run_dir / "migration-report.html").write_text(html.replace(GOLDEN_ANCHOR, ALTERED_ANCHOR), encoding="utf-8")

    validator = _run(
        str(VALIDATOR), str(run_dir / "migration-report.html"),
        "--estimation-infra", str(ESTIMATE), "--aws-design", str(DESIGN), "--migration-dir", str(run_dir),
    )
    assert validator.returncode == 1, validator.stdout + validator.stderr
    assert 'cost figure mismatch: data-cost-key="current_monthly"' in validator.stderr, validator.stderr
    assert "current_costs.azure_monthly = $4200" in validator.stderr, validator.stderr

    oracle = _run(str(ASSERTER), str(run_dir))
    assert oracle.returncode == 1, oracle.stdout + oracle.stderr
    assert "current_monthly renders '$3,900/mo'" in oracle.stdout, oracle.stdout

PRECHECK = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
REPORT_FRAGMENT = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-report.md"
)
def _assemble_run_dir(tmp_path: Path, *stages: str) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    for stage in stages:
        shutil.copytree(FIXTURE / stage, run_dir, dirs_exist_ok=True)
    return run_dir
def test_generate_precheck_passes_on_the_assembled_golden_run(tmp_path: Path) -> None:
    # generate.md step 2 runs this exact command (no baseline in --run-dir mode) and stops the
    # phase on exit 1. The artifacts the Clarify/Design phases write must satisfy the contracts.
    for stages in (
        ("after-discover", "after-clarify-complete", "after-design", "after-estimate"),
        ("after-discover", "after-clarify", "after-design", "after-estimate"),
    ):
        run_dir = _assemble_run_dir(tmp_path / stages[1], *stages)
        result = _run(str(PRECHECK), "--run-dir", str(run_dir), "--skill", "azure-to-aws")
        assert result.returncode == 0, f"{stages[1]}:\n{result.stdout}{result.stderr}"
def test_report_fragment_does_not_read_validation_report_for_a_status() -> None:
    # validation-report.json is written by the main window AFTER the report (generate.md step 5).
    text = REPORT_FRAGMENT.read_text(encoding="utf-8")
    section = text.split("**Terraform validation:**", 1)[1].split("**Design and generation warnings:**", 1)[0]
    assert "do NOT read `validation-report.json`" in section
    source_line = text.split("Source: `estimation-infra.json`", 1)[1].split("\n## ", 1)[0]
    assert "validation-report.json" not in source_line.split("\n\n", 1)[0]
