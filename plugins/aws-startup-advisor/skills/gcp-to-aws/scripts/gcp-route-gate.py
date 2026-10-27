#!/usr/bin/env python3
"""Deterministic Discover route output gate for the Graviton (ARM64) sub-discovery.

Route rule (discover-preview.md Route Detection): the AI-only route is
``gcp-resource-inventory.json`` absent AND ``ai-workload-profile.json`` present.
Every other route is the infrastructure route.

Output is one line on stdout:
  GATE_NA   ... route=ai_only              exit 0 (gate not applicable)
  GATE_PASS ... file=... location=...      exit 0 (graviton_profile array present)
  GATE_PASS ... reason=not_yet_known       exit 0 (no profile yet; Clarify Q11b asks)
  ROUTE_GATE_FAIL ... reason=unreadable    exit 1 (file is not a JSON object; STOP)
  ROUTE_GATE_FAIL ... reason=malformed     exit 1 (graviton_profile not an array; STOP)
Usage errors exit 2.

A missing profile is not a failure: billing-only Discover writes no inventory and
discover-app-graviton.md may not have emitted yet, so the gate reports "not yet
known" and clarify-compute.md Q11b asks for the architecture. The canonical
location is top-level ``graviton_profile`` in either file; ``metadata.graviton_profile``
is also accepted.
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

    # Infrastructure route: graviton_profile lives at the top level of the GCP discovery
    # output (gcp-resource-inventory.json) or next to the AI profile on hybrid runs.
    # metadata.graviton_profile is accepted as a non-canonical location.
    for name in (INVENTORY, AI_PROFILE):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            payload = _load(path)
        except (OSError, ValueError) as exc:
            return 1, f"ROUTE_GATE_FAIL | {PHASE_GATE} | field=graviton_profile | reason=unreadable | file={name} | detail={exc}"
        metadata = payload.get("metadata")
        candidates = (
            ("top_level", payload.get("graviton_profile")),
            ("metadata", metadata.get("graviton_profile") if isinstance(metadata, dict) else None),
        )
        for location, profile in candidates:
            if profile is None:
                continue
            if not isinstance(profile, list):
                return 1, (
                    f"ROUTE_GATE_FAIL | {PHASE_GATE} | field=graviton_profile | reason=malformed"
                    f" | file={name} | location={location} | detail=not an array"
                )
            return 0, f"GATE_PASS | {PHASE_GATE} | field=graviton_profile | file={name} | location={location}"

    # No file carries the profile yet (billing-only Discover, or the scan has not emitted).
    # Not a failure: clarify-compute.md Q11b asks for the architecture.
    return 0, f"GATE_PASS | {PHASE_GATE} | field=graviton_profile | reason=not_yet_known | note=clarify_q11b_asks_architecture"


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
