#!/usr/bin/env python3
"""Assert a Heroku Decision-gate choice-A run landed in the decide-complete state.

Locks the choice-A terminal semantics (current_phase complete + run_mode decide +
generate pending) and the decision-pack artifacts (decision-report.html passes
the validator in --mode decision; DECISION.md exists). Pre-execution is
asserted via phases.generate, not raw file absence — see
heroku-decision-gate/retained-execution-pack for the sibling fixture covering
a decide-complete run where a prior cycle's execution pack is still present.
Mirrors ../gcp-decision-gate/check_expected_decide.py
for heroku-to-aws's thinner report shape (decision-cta instead of GCP's
appendix-based decision core).

Usage: check_expected_decide.py <run_dir>
"""
from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 — fixture asserter; runs only committed scripts via sys.executable
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "validate-heroku-migration-report.py"
)
WRITER = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "emit-plan-json.py"
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1])

    # Terminal state: decide-complete, not failure, not in-flight.
    ph_path = run / ".phase-status.json"
    check(ph_path.exists(), "missing .phase-status.json")
    if not ph_path.exists():
        print("FAIL")
        [print(" -", f) for f in FAILS]
        return 1
    ph = json.loads(ph_path.read_text())
    phases = ph.get("phases") or {}
    check(ph.get("current_phase") == "complete", f"current_phase={ph.get('current_phase')}")
    check(ph.get("run_mode") == "decide", f"run_mode={ph.get('run_mode')}")
    check(phases.get("generate") == "pending", f"generate={phases.get('generate')}")
    check(phases.get("estimate") == "completed", f"estimate={phases.get('estimate')}")
    check(phases.get("workshop") == "completed", f"workshop={phases.get('workshop')}")

    # Decision pack exists. Pre-execution is a STATE fact (phases.generate
    # above, already asserted), not raw file absence — a prior cycle's
    # execution pack may legitimately remain on disk after a workshop
    # reprice (workshop.md § Entry never deletes it), so this fixture does
    # NOT assert terraform/ or generation-*.json are absent; see
    # heroku-decision-gate/retained-execution-pack for the case where they
    # deliberately ARE present alongside a valid decide-complete state.
    report = run / "decision-report.html"
    check(report.exists(), "missing decision-report.html")
    check((run / "DECISION.md").exists(), "missing DECISION.md")

    # The decision report passes the validator in decision mode, including the
    # cross-artifact disk checks (terraform/, generation-*.json absence).
    if report.exists():
        result = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
            [sys.executable, str(VALIDATOR), str(report), "--mode", "decision",
             "--migration-dir", str(run)],
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"decision-report.html fails --mode decision:\n{result.stdout}{result.stderr}",
        )
        # Content locks (beyond structure): typography-first verdict and the
        # "if you execute" timeline-band label must survive refactors — these
        # are the same rules generate-report.md already enforces for the full
        # report; report-decision-core.md reuses them for decision mode.
        html = report.read_text()
        check('class="verdict-headline"' in html, "missing verdict-headline element")
        check("if you execute" in html, 'timeline must be labeled "if you execute" (band, not schedule)')

    # The decision-only exit writes the web-handoff plan.json from the run's
    # estimate artifacts. Run the writer against a scratch copy (so the golden
    # dir stays clean) and assert it EMITS a schema-shaped file, not a skip.
    with tempfile.TemporaryDirectory() as scratch:
        scratch_run = Path(scratch) / "run"
        shutil.copytree(run, scratch_run)
        wr = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
            [sys.executable, str(WRITER), "--migration-dir", str(scratch_run),
             "--plugin-json", str(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")],
            capture_output=True,
            text=True,
        )
        plan = scratch_run / "plan.json"
        check(wr.returncode == 0, f"emit-plan-json.py exited {wr.returncode}: {wr.stderr.strip()}")
        check(plan.exists(), f"decision-only exit did not write plan.json (writer: {wr.stdout.strip()})")
        if plan.exists():
            data = json.loads(plan.read_text())
            cost = data.get("cost") or {}
            check(data.get("sourcePlatform") == "HEROKU", f"sourcePlatform={data.get('sourcePlatform')}")
            check(data.get("scope") == "INFRA_ONLY", f"scope={data.get('scope')}")
            check(cost.get("awsMonthlyBasis") == "BALANCED", f"awsMonthlyBasis={cost.get('awsMonthlyBasis')}")
            check(isinstance(cost.get("awsMonthly"), (int, float)), "cost.awsMonthly missing/not a number")
            check(bool(data.get("producerVersion")), "producerVersion missing — plugin.json was not read")

    if FAILS:
        print("FAIL")
        [print(" -", f) for f in FAILS]
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
