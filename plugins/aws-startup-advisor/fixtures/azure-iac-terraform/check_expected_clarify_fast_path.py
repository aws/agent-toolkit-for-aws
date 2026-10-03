#!/usr/bin/env python3
"""Assert the ELIGIBLE fast-path clarify branch.

A thin wrapper around `check_expected_clarify.py`, which takes an optional second argument
selecting its expectation set. The two Terraform-corpus goldens (`after-clarify/`,
`after-clarify-complete/`) are both wizard runs over an estate that is ineligible for the
`clarify.md` § Step 0.5 fast path by design (VMs, ZoneRedundant Postgres, five clusters).
Nothing in them can exercise the fast-path provenance contract:

- `after-clarify-fast-path/` + `expected-clarify-fast-path.json` — a hand-authored eligible
  estate (one Linux plan hosting two apps, one Postgres server with NO measured size). The
  fast path asks the two ESSENTIAL rows, applies every other default, lists each defaulted
  PROPOSED row in `metadata.questions_defaulted[]` (array rows under index keys such as
  `app_service_plans[0].isolation_split`), lists the deferred `db_cutover` row ONLY in
  `metadata.deferred_to_generate[]`, and takes Q-D2's unknown-size fallback. The handoff
  gate must pass with the isolation default recorded, not asked.

This exists as a separate file only so each branch has an asserter that runs with no
arguments beyond the run directory. The logic lives in one place.

Usage:
    python3 check_expected_clarify_fast_path.py <migration_run_dir>

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
            "expected-clarify-fast-path.json",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
