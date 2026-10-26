#!/usr/bin/env python3
"""Deterministic Discover route output gate for the Graviton (ARM64) sub-discovery.

Route rule (discover-preview.md Route Detection): the AI-only route is
``gcp-resource-inventory.json`` absent AND ``ai-workload-profile.json`` present.
Every other route is the infrastructure route.

Output is one line on stdout:
  GATE_NA   ... route=ai_only              exit 0 (gate not applicable)
  GATE_PASS ...                            exit 0 (graviton_profile present)
  ROUTE_GATE_FAIL ... reason=missing       exit 1 (caller must STOP the run)
Usage errors exit 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INVENTORY = "gcp-resource-inventory.json"
AI_PROFILE = "ai-workload-profile.json"
PHASE_GATE = "phase=discover | gate=discover-app-graviton"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} top level is not an object")
    return data


def route_for(run_dir: Path) -> str:
    if not (run_dir / INVENTORY).exists() and (run_dir / AI_PROFILE).exists():
        return "ai_only"
    return "infra"


def graviton_gate(run_dir: Path) -> tuple[int, str]:
    """Return (exit_code, single-line verdict) for the graviton route gate."""
    if route_for(run_dir) == "ai_only":
        return 0, f"GATE_NA | {PHASE_GATE} | route=ai_only"

    # Infrastructure route: graviton_profile may live in the GCP discovery metadata
    # (gcp-resource-inventory.json) or next to the AI profile on hybrid runs.
    for name in (INVENTORY, AI_PROFILE):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            payload = _load(path)
        except (OSError, ValueError) as exc:
            return 1, f"ROUTE_GATE_FAIL | {PHASE_GATE} | field=graviton_profile | reason=unreadable | file={name} | detail={exc}"
        if isinstance(payload.get("graviton_profile"), list):
            return 0, f"GATE_PASS | {PHASE_GATE} | field=graviton_profile | file={name}"

    return 1, f"ROUTE_GATE_FAIL | {PHASE_GATE} | field=graviton_profile | reason=missing"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--gate", required=True, choices=["graviton"])
    args = parser.parse_args(argv)

    if not args.run_dir.is_dir():
        print(f"ROUTE_GATE_FAIL | {PHASE_GATE} | field=graviton_profile | reason=run_dir_missing", file=sys.stdout)
        return 2

    code, line = graviton_gate(args.run_dir)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
