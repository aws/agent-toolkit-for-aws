#!/usr/bin/env python3
"""Assert a Heroku Design run against expected-nonweb-scaling.json.

Covers the Horizontal Non-Web Capacity Guard (design-mapping.md): a persistent
non-web formation with quantity > 1 is routed off Elastic Beanstalk onto Fargate,
so the Fargate table must carry every dyno tier the EB table carries. When it does
not, the formation is silently dropped from the design with only a warning.

Also checks the three dyno sizing tables directly (independent of the run dir):
tier-set agreement across EB/Fargate/EKS, and every Fargate row against the
documented Fargate CPU/memory matrix.

Usage:
    python3 check_expected_nonweb_scaling.py <migration_run_dir>

Exits 0 on PASS, 1 on FAIL. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FAILS: list[str] = []
NOTES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def load(path: Path) -> dict | None:
    if not path.exists():
        FAILS.append(f"missing {path.name} in {path.parent}")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        FAILS.append(f"{path.name} is not valid JSON: {e}")
        return None


def memory_allowed(spec: dict, memory: int) -> bool:
    if "values" in spec:
        return memory in spec["values"]
    lo, hi, step = spec["min"], spec["max"], spec["step"]
    return lo <= memory <= hi and (memory - lo) % step == 0


def check_sizing_tables(plugin_root: Path, exp: dict) -> None:
    spec = exp["sizing_tables"]
    tables: dict[str, dict] = {}
    for name in ("eb", "fargate", "eks"):
        data = load(plugin_root / spec[name])
        if data is None:
            return
        tables[name] = data.get("rows") or {}

    for tier in spec["required_tiers_in_every_table"]:
        for name, rows in tables.items():
            check(tier in rows, f"{name} sizing table has no '{tier}' row")

    if spec.get("fargate_and_eks_tiers_must_be_identical"):
        only_fargate = sorted(set(tables["fargate"]) - set(tables["eks"]))
        only_eks = sorted(set(tables["eks"]) - set(tables["fargate"]))
        check(not only_fargate, f"tiers in the Fargate table but not EKS: {only_fargate}")
        check(not only_eks, f"tiers in the EKS table but not Fargate: {only_eks}")

    if spec.get("eb_tiers_must_cover_fargate_tiers"):
        missing = sorted(set(tables["fargate"]) - set(tables["eb"]))
        check(not missing, f"tiers in the Fargate table but not EB: {missing}")

    matrix = exp["fargate_cpu_memory_matrix"]
    exempt = set(exp.get("fargate_matrix_baseline", {}).get("exempt_rows", []))
    for tier, row in tables["fargate"].items():
        if tier in exempt:
            NOTES.append(f"fargate matrix check skipped for baselined row '{tier}'")
            continue
        cpu, memory = row.get("fargate_cpu"), row.get("fargate_memory")
        spec_for_cpu = matrix.get(str(cpu))
        if spec_for_cpu is None:
            FAILS.append(f"fargate row '{tier}': fargate_cpu={cpu} is not a valid Fargate task CPU value")
            continue
        check(
            memory_allowed(spec_for_cpu, memory),
            f"fargate row '{tier}': cpu={cpu} with memory={memory} MiB is not a valid Fargate pairing",
        )


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent
    plugin_root = fixture_dir.parent.parent  # fixtures/<set>/ -> aws-startup-advisor/
    exp = json.loads((fixture_dir / "expected-nonweb-scaling.json").read_text())

    check_sizing_tables(plugin_root, exp)

    inventory = load(run_dir / "heroku-resource-inventory.json")
    design = load(run_dir / "aws-design.json")
    if inventory is None or design is None:
        _report()
        return 1

    services = design.get("services") or []
    by_source: dict[str, list[dict]] = {}
    for svc in services:
        by_source.setdefault(str(svc.get("source_resource_id")), []).append(svc)

    formations = [
        r for r in inventory.get("resources", [])
        if r.get("resource_type") == "formation" and (r.get("config") or {}).get("process_type") != "release"
    ]
    check(bool(formations), "inventory has no non-release formation resources to check")

    for f in formations:
        rid = str(f.get("resource_id"))
        cfg = f.get("config") or {}
        mapped = by_source.get(rid, [])
        if exp.get("every_formation_must_map"):
            check(bool(mapped), f"formation {rid} ({cfg.get('dyno_type')}) has no service in the design — silently dropped")
        if not mapped:
            continue
        # Horizontal Non-Web Capacity Guard
        if cfg.get("process_type") != "web" and int(cfg.get("quantity", 0)) > 1:
            check(
                any(s.get("aws_service") == "Fargate" for s in mapped),
                f"formation {rid} is non-web with quantity={cfg.get('quantity')} but was not routed to Fargate "
                f"(got {[s.get('aws_service') for s in mapped]})",
            )

    for want in exp.get("expected_services", []):
        rid = want["source_resource_id"]
        mapped = [s for s in by_source.get(rid, []) if s.get("aws_service") == want["aws_service"]]
        check(bool(mapped), f"no {want['aws_service']} service for {rid}")
        if not mapped:
            continue
        cfg = mapped[0].get("aws_config") or {}
        for key, value in (want.get("aws_config") or {}).items():
            check(cfg.get(key) == value, f"{rid}: aws_config.{key}={cfg.get(key)!r} want {value!r}")

    warnings = " | ".join(str(w) for w in design.get("warnings") or [])
    for sub in exp.get("required_warning_substrings", []):
        check(sub in warnings, f"missing expected warning substring: {sub!r}")
    for sub in exp.get("forbidden_warning_substrings", []):
        check(sub not in warnings, f"design carries a forbidden warning substring: {sub!r}")

    if FAILS:
        _report()
        return 1
    _print_notes()
    print("PASS — expected-nonweb-scaling.json assertions hold")
    return 0


def _print_notes() -> None:
    for n in NOTES:
        print(f"note: {n}")


def _report() -> None:
    _print_notes()
    print(f"FAIL ({len(FAILS)}):")
    for f in FAILS:
        print(f"  - {f}")


if __name__ == "__main__":
    sys.exit(main())
