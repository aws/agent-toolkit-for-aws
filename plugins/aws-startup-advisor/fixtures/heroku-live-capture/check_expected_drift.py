#!/usr/bin/env python3
"""Assert a Discover run's output against expected-drift.json (scenario B).

Usage:
    python3 check_expected_drift.py <migration_run_dir>

Where <migration_run_dir> contains the heroku-resource-inventory.json produced
by a replay of this fixture's scenario B (live-capture/ + workspace-terraform/
heroku.tf). Exits 0 on PASS, 1 on FAIL with one line per failed assertion.
Stdlib only. (Same pattern as the gcp-live-capture asserter.)
"""

import json
import sys
from pathlib import Path

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent

    inv_path = run_dir / "heroku-resource-inventory.json"
    if not inv_path.exists():
        print("FAIL (1):\n  - missing heroku-resource-inventory.json in run dir")
        return 1
    inv = json.loads(inv_path.read_text())
    exp = json.loads((fixture_dir / "expected-drift.json").read_text())

    # Metadata
    meta = inv["metadata"]
    check(meta["total_apps_discovered"] == exp["metadata"]["total_apps_discovered"], "total_apps_discovered")
    for s in exp["metadata"]["discovery_sources_must_include"]:
        check(s in meta.get("discovery_sources", []), f"discovery_sources missing {s}")
    check(meta.get("confidence") == exp["metadata"]["confidence"], f"confidence={meta.get('confidence')}")

    # Apps
    apps = {a["app_name"]: a for a in inv["apps"]}
    for name, e in exp["apps"].items():
        a = apps.get(name)
        if a is None:
            check(False, f"missing app {name}")
            continue
        for k in ("discovery_status", "heroku_generation", "app_id"):
            if k in e:
                check(a.get(k) == e[k], f"app {name} {k}={a.get(k)} want {e[k]}")
        if "failure_reason_contains" in e:
            check(e["failure_reason_contains"] in (a.get("failure_reason") or ""), f"app {name} failure_reason")

    # Resources
    res = {r["resource_id"]: r for r in inv["resources"]}
    for rid, e in exp["merged_resources"].items():
        r = res.get(rid)
        if r is None:
            check(False, f"missing resource {rid}")
            continue
        if "source" in e:
            check(r.get("source") == e["source"], f"{rid} source={r.get('source')} want {e['source']}")
        if e.get("unmanaged_by_terraform"):
            check(r.get("unmanaged_by_terraform") is True, f"{rid} unmanaged flag")
        if e.get("not_found_live"):
            check(r.get("not_found_live") is True, f"{rid} not_found_live flag")
        for flag in e.get("must_not_have", []):
            check(r.get(flag) is not True, f"{rid} must not have {flag}")
        for k, v in e.get("config", {}).items():
            if k == "config_var_keys_count":
                check(len(r["config"].get("config_var_keys", [])) == v, f"{rid} key count")
            elif k == "stages":
                check(r["config"].get("stages") == v, f"{rid} stages")
            else:
                check(r["config"].get(k) == v, f"{rid} config.{k}={r['config'].get(k)} want {v}")
        if "expected_config_conflicts" in e:
            conflict_fields = [
                c["field"] for c in inv.get("live_metadata", {}).get("drift", {}).get("config_conflicts", [])
                if c.get("resource_id") == rid
            ]
            for f in e["expected_config_conflicts"]:
                check(f in conflict_fields, f"{rid} missing config conflict on {f}")

    # live_metadata + drift
    lm = inv["live_metadata"]
    check(lm.get("apps_captured") == exp["live_metadata"]["apps_captured"], "apps_captured")
    check(lm.get("apps_failed") == exp["live_metadata"]["apps_failed"], "apps_failed")
    lim = json.dumps(lm.get("limitations", []))
    check(exp["live_metadata"]["limitations_must_include"] in lim, "limitations missing scaled-to-zero note")
    drift = lm.get("drift", {})
    check(
        drift.get("resources_live_only", 0) >= exp["live_metadata"]["drift"]["resources_live_only_min"],
        f"resources_live_only={drift.get('resources_live_only')}",
    )
    check(
        drift.get("resources_terraform_only") == exp["live_metadata"]["drift"]["resources_terraform_only"],
        f"resources_terraform_only={drift.get('resources_terraform_only')}",
    )
    conflict_fields = sorted(c["field"] for c in drift.get("config_conflicts", []))
    check(
        conflict_fields == sorted(exp["live_metadata"]["drift"]["config_conflicts_expected_fields"]),
        f"conflict fields {conflict_fields}",
    )

    # Must-not-exist / secret hygiene
    doc = json.dumps(inv)
    check("domain:acme-web:acme-web-1a2b3c4d5e6f" not in doc, "default herokuapp domain leaked as resource")
    for bad in ("cluster_id", "creation_order_depth", "must_migrate_together", '"edges"', '"dependencies"'):
        check(bad not in doc, f"forbidden clustering field {bad}")
    for bad in ("sk_live", "postgres://", "rediss://", "AKIA", "Bearer "):
        check(bad not in doc, f"possible secret value: {bad}")

    def walk(node, path="$"):
        if isinstance(node, dict):
            if "name" in node and ("value" in node or "valueFrom" in node):
                check(False, f"env-like object with a value payload at {path}")
            for k, v in node.items():
                if k == "config_vars":
                    check(False, f"raw config_vars at {path} — only config_var_keys (names) allowed")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(inv)
    for key_name in ("STRIPE_SECRET_KEY", "DATABASE_URL", "SESSION_SECRET"):
        check(f'"{key_name}": ' not in doc, f"config var name {key_name} appears as a KEY (value paired)")

    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("PASS — expected-drift.json assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
