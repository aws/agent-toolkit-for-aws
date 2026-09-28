#!/usr/bin/env python3
"""Assert the COMPLETING clarify branch.

A thin wrapper around `check_expected_clarify.py`, which takes an optional second argument
selecting its expectation set. Two branches of the same phase are both real states and both
need a golden:

- `after-clarify/` + `expected-clarify.json` — the scripted user DECLINES to state Azure
  spend, so an ESSENTIAL row is null and the phase must GATE. That branch proves
  `ESSENTIAL` + `value: null` is the completion gate (decision 13.5b).
- `after-clarify-complete/` + `expected-clarify-complete.json` — spend is answered, so the
  phase must COMPLETE. This branch is what makes Design reachable, and it additionally pins
  the conflicting-answer rule: `vm_cutover: mgn` against the Azure-Edition hard blocker is
  recorded AS GIVEN with a `conflict` key and does NOT gate.

This exists as a separate file only so each branch has an asserter that runs with no
arguments beyond the run directory. The logic lives in one place.

Usage:
    python3 check_expected_clarify_complete.py <migration_run_dir>

Exits 0 on PASS, 1 on FAIL. Stdlib only.
"""

from __future__ import annotations

import subprocess  # nosec B404 — fixture asserter; runs only the committed validator via sys.executable
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(__file__).name} <migration_run_dir>", file=sys.stderr)
        return 2
    return subprocess.run(  # nosec B603 — list args, no shell, committed script path only
        [
            sys.executable,
            str(HERE / "check_expected_clarify.py"),
            sys.argv[1],
            "expected-clarify-complete.json",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
