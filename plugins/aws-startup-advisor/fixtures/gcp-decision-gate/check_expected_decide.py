#!/usr/bin/env python3
"""Assert a Decision-gate choice-A run landed in the decide-complete state.

Locks the decide-mode terminal semantics (current_phase complete + run_mode decide +
generate pending) and the decision-pack artifacts (decision-report.html passes
the validator in --mode decision; DECISION.md exists; no Generate artifacts).

Usage: check_expected_decide.py <run_dir>
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 — fixture asserter; runs only the committed validator via sys.executable
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
ESTIMATION_INFRA = Path(__file__).resolve().parent / "after-decide-complete" / "estimation-infra.json"
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

    # Decision pack exists; execution artifacts do not.
    report = run / "decision-report.html"
    check(report.exists(), "missing decision-report.html")
    check((run / "DECISION.md").exists(), "missing DECISION.md")
    check(not (run / "terraform").exists(), "terraform/ must not exist on a decide run")
    check(
        not any(run.glob("generation-*.json")),
        "generation-*.json must not exist on a decide run",
    )

    # The decision report passes the validator in decision mode, WITH the
    # estimation artifact supplied — otherwise the cost-figure anchor gate
    # (P1-C) is silently skipped (fail-open on absence) and this asserter
    # would not catch a decision-mode report missing its required anchors.
    # No --no-require-toc: this is a real golden fixture (it has a genuine
    # <nav class="toc">, verified separately below), not a deliberately
    # minimal unit fixture — that flag also sets require_anchors=False in
    # _validate_cost_figures, which was silently defeating the mandatory
    # data-cost-key="aws_monthly_balanced" anchor gate this asserter exists
    # to enforce (a stripped anchor still returned PASS through this exact
    # asserter until this flag was removed).
    if report.exists():
        result = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
            [sys.executable, str(VALIDATOR), str(report), "--mode", "decision",
             "--estimation-infra", str(ESTIMATION_INFRA)],
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"decision-report.html fails --mode decision:\n{result.stdout}{result.stderr}",
        )
        # Content locks (beyond structure): verdict typography and the
        # not-comparable baseline rule must survive refactors, and the
        # timeline must read as a band, not a committed schedule.
        html = report.read_text()
        check('class="verdict-headline"' in html, "missing verdict-headline element (verdict typography)")
        check("not directly comparable" in html, "missing not-comparable baseline sentence")
        check("if you execute" in html, 'timeline must be labeled "if you execute" (band, not schedule)')

    if FAILS:
        print("FAIL")
        [print(" -", f) for f in FAILS]
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
