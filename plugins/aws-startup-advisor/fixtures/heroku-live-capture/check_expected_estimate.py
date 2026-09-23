#!/usr/bin/env python3
"""Assert an Estimate run's output against expected-estimate.json (scenario C).

Usage:
    python3 check_expected_estimate.py <migration_run_dir>

Where <migration_run_dir> contains the estimation-infra.json produced by a
replay seeded from seed-estimate/ (live-discovered inventory, NO billing data).
Verifies the live_prices_plus_cache baseline: exact add-on prices + cache dyno
rates = 352.0/month, honest derived-baseline caveat, comparison and migration
considerations unlocked for the derived source. Exits 0 on PASS, 1 on FAIL with
one line per failed assertion. Stdlib only.
"""

import json
import math
import sys
from pathlib import Path

FAILS: list[str] = []
TOL = 0.01  # exact math expected; tolerance only for float representation


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def close(a, b) -> bool:
    return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isclose(a, b, abs_tol=TOL)


def find_number(node, target):
    """True if `target` appears as a numeric value anywhere under node."""
    if isinstance(node, dict):
        return any(find_number(v, target) for v in node.values())
    if isinstance(node, list):
        return any(find_number(v, target) for v in node)
    return close(node, target)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent

    est_path = run_dir / "estimation-infra.json"
    if not est_path.exists():
        print("FAIL (1):\n  - missing estimation-infra.json in run dir")
        return 1
    est = json.loads(est_path.read_text())
    exp = json.loads((fixture_dir / "expected-estimate.json").read_text())
    doc = json.dumps(est)

    # --- Baseline (Part 1, rung 2: live prices + dyno cache) ---
    b = exp["baseline"]
    cur = est.get("current_costs", {})
    check(cur.get("source") == b["source"], f"current_costs.source={cur.get('source')} want {b['source']}")
    check(
        find_number(cur, b["monthly_total"]),
        f"current_costs has no numeric total == {b['monthly_total']} (exact add-on + cache dyno math)",
    )
    note = str(cur.get("baseline_note") or "")
    check(bool(note.strip()), "baseline_note missing/empty — the derived-baseline caveat is mandatory")
    for word in b["baseline_note_must_mention"]:
        check(word.lower() in note.lower(), f"baseline_note does not mention '{word}'")
    if b.get("must_not_fabricate_billing"):
        check(cur.get("source") != "billing_data", "source claims billing_data with no billing_profile in inventory")
        bp = est.get("billing_profile")
        check(not bp, "estimation-infra.json fabricated a billing_profile")

    # --- Cost comparison (Part 3 — must run for the derived source) ---
    c = exp["cost_comparison"]
    comp = est.get("cost_comparison")
    check(isinstance(comp, dict) and bool(comp), "cost_comparison absent — comparison must run for ANY baseline source")
    if isinstance(comp, dict):
        check(
            close(comp.get("heroku_monthly_baseline"), c["heroku_monthly_baseline"]),
            f"cost_comparison.heroku_monthly_baseline={comp.get('heroku_monthly_baseline')} want {c['heroku_monthly_baseline']}",
        )
        check(
            comp.get("baseline_source") == c["baseline_source"],
            f"cost_comparison.baseline_source={comp.get('baseline_source')}",
        )
        for opt in c["required_options"]:
            o = comp.get(opt)
            if not isinstance(o, dict):
                check(False, f"cost_comparison.{opt} missing")
                continue
            for f in c["required_option_fields"]:
                check(f in o, f"cost_comparison.{opt}.{f} missing")
            aws = o.get("aws_monthly")
            diff = o.get("monthly_difference")
            if isinstance(aws, (int, float)) and isinstance(diff, (int, float)):
                check(
                    close(diff, aws - c["heroku_monthly_baseline"]),
                    f"cost_comparison.{opt} monthly_difference {diff} != {aws} - {c['heroku_monthly_baseline']}",
                )
            ann = o.get("annual_difference")
            if isinstance(diff, (int, float)) and isinstance(ann, (int, float)):
                check(close(ann, diff * 12), f"cost_comparison.{opt} annual_difference {ann} != 12 x {diff}")

    # --- Migration cost considerations (Part 4 — keyed off baseline presence) ---
    m = exp["migration_cost_considerations"]
    mig = est.get("migration_cost_considerations", {})
    check(
        mig.get("baseline_available") is m["baseline_available"],
        f"migration_cost_considerations.baseline_available={mig.get('baseline_available')}",
    )
    check(
        mig.get("baseline_source") == m["baseline_source"],
        f"migration_cost_considerations.baseline_source={mig.get('baseline_source')}",
    )
    check(
        len(mig.get("categories", [])) >= m["categories_min"],
        "migration_cost_considerations.categories empty — dual-run cost must be priced from the derived baseline",
    )

    # --- Projected costs (Property-16 invariant + design coverage) ---
    proj = est.get("projected_costs", {})
    balanced = proj.get("aws_monthly_balanced")
    check(
        isinstance(balanced, (int, float)) and balanced > 0,
        f"projected_costs.aws_monthly_balanced={balanced} not a positive number",
    )
    breakdown = proj.get("breakdown", {})
    if exp["projected_costs"]["balanced_equals_breakdown_sum"] and isinstance(breakdown, dict) and breakdown:

        def entry_cost(v):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
            if isinstance(v, dict):
                for k in ("balanced", "mid", "monthly", "monthly_cost", "cost"):
                    if isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool):
                        return v[k]
            return None

        costs = [entry_cost(v) for v in breakdown.values()]
        if all(c is not None for c in costs) and isinstance(balanced, (int, float)):
            total = sum(costs)
            check(
                math.isclose(total, balanced, abs_tol=max(0.02 * balanced, 1.0)),
                f"balanced total {balanced} != breakdown sum {round(total, 2)} (Property-16)",
            )
        else:
            check(False, "breakdown entries lack a recognizable balanced/monthly cost field")

    if exp["projected_costs"]["every_design_service_priced_or_warned"]:
        design = json.loads((run_dir / "aws-design.json").read_text())
        warnings_txt = json.dumps(est.get("warnings", [])) + json.dumps(est.get("pricing_source", {}))
        for svc in design.get("services", []):
            sid = svc.get("service_id", "")
            name = svc.get("aws_service", "")
            covered = sid in doc or name in doc or sid in warnings_txt
            check(covered, f"design service {sid} neither in the cost breakdown nor warned as unpriced")

    # --- Warnings hygiene ---
    warn_doc = json.dumps(est.get("warnings", []))
    for bad in exp["warnings_must_not_contain"]:
        check(bad not in warn_doc, f"warnings contain '{bad}' — everything in this scenario is priceable")

    # --- Must-not-exist / secret hygiene ---
    check('"billing_period"' not in doc, "billing_period present — no invoice data exists in this scenario")
    for bad in ("sk_live", "postgres://", "rediss://", "AKIA", "Bearer "):
        check(bad not in doc, f"possible secret value: {bad}")

    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("PASS — expected-estimate.json assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
