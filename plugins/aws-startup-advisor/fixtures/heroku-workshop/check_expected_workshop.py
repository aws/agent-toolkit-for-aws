#!/usr/bin/env python3
"""Assert a Heroku what-if workshop run against expected-workshop.json.

Usage:
    python3 check_expected_workshop.py <migration_run_dir> [<seed_dir>]

Defaults: compares <migration_run_dir> to the fixture's seed/ sibling for
inventory byte-stability. Exits 0 on PASS, 1 on FAIL. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2

    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent
    seed_dir = Path(sys.argv[2]) if len(sys.argv) == 3 else fixture_dir / "seed"
    exp = json.loads((fixture_dir / "expected-workshop.json").read_text())

    inv_run = run_dir / "heroku-resource-inventory.json"
    inv_seed = seed_dir / "heroku-resource-inventory.json"
    check(inv_run.exists(), "missing heroku-resource-inventory.json in run dir")
    check(inv_seed.exists(), "missing seed inventory")
    if inv_run.exists() and inv_seed.exists() and exp.get("inventory_must_match_seed_bytes"):
        check(
            inv_run.read_bytes() == inv_seed.read_bytes(),
            "inventory bytes changed — workshop must freeze discovery",
        )

    index_path = run_dir / "scenarios" / "index.json"
    check(index_path.exists(), "missing scenarios/index.json")
    if not index_path.exists():
        _print_fails()
        return 1

    index = json.loads(index_path.read_text())
    scenarios = index.get("scenarios") or []
    check(len(scenarios) >= exp["min_scenarios"], f"scenario count {len(scenarios)} < {exp['min_scenarios']}")
    check(len(scenarios) <= exp["max_scenarios"], f"scenario count {len(scenarios)} > max {exp['max_scenarios']}")
    check(index.get("baseline_scenario_id") == exp["baseline_scenario_id"], "baseline_scenario_id mismatch")
    check(index.get("active_scenario_id") == exp["active_scenario_id"], "active_scenario_id mismatch")

    prefs = json.loads((run_dir / "preferences.json").read_text())
    workshop = prefs.get("workshop") or {}
    check(workshop.get("cpu_architecture") == exp["active_cpu_architecture"], "active cpu_architecture mismatch")
    check(workshop.get("active_scenario_id") == exp["active_scenario_id"], "prefs workshop.active_scenario_id mismatch")

    design = json.loads((run_dir / "aws-design.json").read_text())
    eb = next(
        (s for s in design.get("services", []) if s.get("aws_service") == "Elastic Beanstalk"),
        None,
    )
    check(eb is not None, "no Elastic Beanstalk service in active design")
    if eb is not None:
        check(
            eb.get("aws_config", {}).get("instance_type") == exp["active_eb_instance_type"],
            f"EB instance_type={eb.get('aws_config', {}).get('instance_type')} want {exp['active_eb_instance_type']}",
        )
        check(
            eb.get("aws_config", {}).get("cpu_architecture") == exp["active_cpu_architecture"],
            "EB cpu_architecture mismatch",
        )

    base_design_path = run_dir / "scenarios" / f"{exp['baseline_scenario_id']}.aws-design.json"
    if base_design_path.exists() and exp.get("design_must_differ_from_baseline"):
        base_design = json.loads(base_design_path.read_text())
        base_eb = next(
            (s for s in base_design.get("services", []) if s.get("aws_service") == "Elastic Beanstalk"),
            None,
        )
        check(base_eb is not None, "no Elastic Beanstalk in baseline design snapshot")
        if base_eb is not None and eb is not None:
            base_type = base_eb.get("aws_config", {}).get("instance_type")
            act_type = eb.get("aws_config", {}).get("instance_type")
            check(act_type != base_type, f"design instance_type unchanged ({act_type}) vs baseline ({base_type})")
            if exp.get("baseline_eb_instance_type"):
                check(
                    base_type == exp["baseline_eb_instance_type"],
                    f"baseline EB instance_type={base_type} want {exp['baseline_eb_instance_type']}",
                )

    est = json.loads((run_dir / "estimation-infra.json").read_text())
    base_manifest = run_dir / "scenarios" / f"{exp['baseline_scenario_id']}.json"
    check(base_manifest.exists(), "missing baseline scenario manifest")
    if base_manifest.exists() and exp.get("balanced_must_differ_from_baseline"):
        base = json.loads(base_manifest.read_text())
        base_bal = base["estimation_summary"]["aws_monthly_balanced"]
        act_bal = est["projected_costs"]["aws_monthly_balanced"]
        check(act_bal != base_bal, f"balanced total unchanged ({act_bal}) vs baseline ({base_bal})")

    phase_path = run_dir / ".phase-status.json"
    if phase_path.exists():
        phase = json.loads(phase_path.read_text())
        phases = phase.get("phases", {})
        if exp.get("generate_must_not_be_completed"):
            check(phases.get("generate") != "completed", "generate must not auto-complete during workshop")
        if exp.get("current_phase_must_be"):
            check(
                phase.get("current_phase") == exp["current_phase_must_be"],
                f"current_phase={phase.get('current_phase')} want {exp['current_phase_must_be']}",
            )
        if exp.get("workshop_phase_must_be"):
            check(
                phases.get("workshop") == exp["workshop_phase_must_be"],
                f"phases.workshop={phases.get('workshop')} want {exp['workshop_phase_must_be']}",
            )

    # Secret hygiene: no token-looking material
    blob = (run_dir / "preferences.json").read_text() + (run_dir / "aws-design.json").read_text()
    for bad in ("HEROKU_API_KEY", "Bearer ", "sk_live"):
        check(bad not in blob, f"possible secret material: {bad}")

    if FAILS:
        _print_fails()
        return 1
    print("PASS — expected-workshop.json assertions hold")
    return 0


def _print_fails() -> None:
    print(f"FAIL ({len(FAILS)}):")
    for f in FAILS:
        print(f"  - {f}")


if __name__ == "__main__":
    sys.exit(main())
