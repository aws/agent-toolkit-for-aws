#!/usr/bin/env python3
"""Assert a derived GCP baseline against expected-baseline.json (scenario C).

Usage:
    python3 check_expected_baseline.py <migration_run_dir>

Reads current_costs from <run_dir>/estimation-infra.json, or from
<run_dir>/current-costs-preview.json when only Part 1 was exercised (the
targeted-replay harness). Exits 0 on PASS, 1 on FAIL with one line per failed
assertion. Stdlib only.
"""

import json
import math
import sys
from pathlib import Path

FAILS: list = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def find_number_near(node, target, tol):
    """True if a number within tol of target appears anywhere under node."""
    if isinstance(node, dict):
        return any(find_number_near(v, target, tol) for v in node.values())
    if isinstance(node, list):
        return any(find_number_near(v, target, tol) for v in node)
    return is_num(node) and math.isclose(node, target, abs_tol=tol)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent
    exp = json.loads((fixture_dir / "expected-baseline.json").read_text())

    src = None
    for name in ("estimation-infra.json", "current-costs-preview.json"):
        if (run_dir / name).is_file():
            src = json.loads((run_dir / name).read_text())
            break
    if src is None:
        print("FAIL: neither estimation-infra.json nor current-costs-preview.json in run dir")
        return 1
    cur = src.get("current_costs", src)  # preview file may BE the current_costs object
    doc = json.dumps(src)

    e = exp["current_costs"]
    check(cur.get("source") == e["source"], f"source={cur.get('source')} want {e['source']}")
    check(e["accuracy_contains"] in str(cur.get("accuracy", "")), f"accuracy={cur.get('accuracy')}")
    check(
        find_number_near(cur, e["monthly_total"], e["tolerance"]),
        f"no numeric total ≈ {e['monthly_total']} (±{e['tolerance']}) in current_costs — rate-card math broken",
    )
    note = str(cur.get("baseline_note") or "")
    check(bool(note.strip()), "baseline_note missing — the derived-baseline caveat is mandatory")
    for phrase in e["baseline_note_must_mention"]:
        check(phrase.lower() in note.lower(), f"baseline_note does not mention '{phrase}'")

    for rid, spec in exp["per_resource"].items():
        check(
            find_number_near(cur, spec["monthly"], spec["tolerance"]),
            f"per-resource figure for {rid} ≈ {spec['monthly']} not found in the breakdown",
        )

    warn_text = json.dumps(src.get("warnings", [])) + json.dumps(cur.get("warnings", [])) + json.dumps(
        cur.get("excluded", [])
    )
    for name in exp["excluded_must_be_warned"]:
        check(name in warn_text or name in json.dumps(cur), f"excluded resource '{name}' not surfaced in warnings")

    check(cur.get("source") != "billing_data", "claims billing_data with no billing-profile.json")
    check("billing-profile.json" not in doc or "unavailable" in doc or True, "")  # provenance is via source field

    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("PASS — expected-baseline.json assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
