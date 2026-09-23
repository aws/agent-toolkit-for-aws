#!/usr/bin/env python3
"""Assert a decide-complete run is still valid when a PRIOR cycle's execution
pack is retained on disk (the workshop-reprice re-entry case).

Reuses check_expected_decide.py's exact assertions unchanged (same terminal
phase-status shape, same decision-pack existence, same validator invocation)
against a sibling fixture that additionally contains terraform/ +
generation-*.json left over from before the reprice — covering the case
check_expected_decide.py's own docstring calls out: this validator's
pre-execution check is phases.generate-based, not file-absence-based, so a
retained pack (including customer-edited baseline.tf/variables.tf and
hand-authored terraform.tfvars/state) must NOT fail the decision CLI.

Usage: check_expected_decide_with_retained_pack.py <run_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# Do not write a __pycache__/ into fixtures/ for the sibling import below —
# fixtures/ is committed reference data, and an import-triggered bytecode cache
# would leave a gitignored directory sitting in the working tree on any
# interpreter that doesn't redirect sys.pycache_prefix elsewhere.
sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_expected_decide import main as _shared_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(_shared_main())
