#!/usr/bin/env python3
"""Assert a Discover run's output against expected-drift.json (scenario B).

Usage:
    python3 check_expected_drift.py <migration_run_dir>

Where <migration_run_dir> contains gcp-resource-inventory.json and
gcp-resource-clusters.json produced by a replay of this fixture's scenario B
(live-capture/ + workspace-terraform/main.tf). Exits 0 on PASS, 1 on FAIL with
one line per failed assertion. Stdlib only.
"""

import json
import sys
from pathlib import Path

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def get_conflict_fields(inv: dict) -> list[str]:
    drift = inv.get("live_metadata", {}).get("drift", {})
    return [c.get("field", "") for c in drift.get("config_conflicts", [])]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    fixture_dir = Path(__file__).resolve().parent

    inv_path = run_dir / "gcp-resource-inventory.json"
    clusters_path = run_dir / "gcp-resource-clusters.json"
    if not inv_path.exists() or not clusters_path.exists():
        print("FAIL (1):\n  - missing gcp-resource-inventory.json or gcp-resource-clusters.json in run dir")
        return 1
    inv = json.loads(inv_path.read_text())
    clusters = json.loads(clusters_path.read_text())
    exp = json.loads((fixture_dir / "expected-drift.json").read_text())

    # Metadata
    meta = inv["metadata"]
    for s in exp["metadata"]["discovery_sources_must_include"]:
        check(s in meta.get("discovery_sources", []), f"discovery_sources missing {s}")
    check(
        meta.get("clustering_mode") in exp["metadata"]["clustering_mode_one_of"],
        f"clustering_mode {meta.get('clustering_mode')} not in {exp['metadata']['clustering_mode_one_of']}",
    )

    # Resources
    res = {r["address"]: r for r in inv["resources"]}
    for addr, e in exp["resources"].items():
        r = res.get(addr)
        if r is None:
            # Address synthesis can differ for live-only names; try name-suffix match
            candidates = [v for k, v in res.items() if k.split(".")[0] == addr.split(".")[0] and addr.split(".")[1] in k]
            if len(candidates) == 1:
                r = candidates[0]
            else:
                check(False, f"missing resource {addr}")
                continue
        if "source" in e:
            check(r.get("source") == e["source"], f"{addr} source={r.get('source')} want {e['source']}")
        if "classification" in e:
            check(r.get("classification") == e["classification"], f"{addr} classification")
        if e.get("not_found_live"):
            check(r.get("not_found_live") is True, f"{addr} not_found_live missing")
        if e.get("unmanaged_by_terraform"):
            check(r.get("unmanaged_by_terraform") is True, f"{addr} unmanaged_by_terraform missing")
        for flag in e.get("must_not_have", []):
            check(flag not in r or r.get(flag) is not True, f"{addr} must not have {flag}")
        if "config_must_include" in e:
            cfg_text = json.dumps(r.get("config", {}))
            for v in e["config_must_include"].values():
                check(v in cfg_text, f"{addr} config missing value {v}")

    # Edges
    all_edges = [edge for c in clusters["clusters"] for edge in c.get("edges", [])]
    for ee in exp["edges_must_include"]:
        found = any(
            ee["from_contains"] in edge.get("from", "")
            and ee["to_contains"] in edge.get("to", "")
            and edge.get("relationship_type") == ee["relationship_type"]
            and (
                "evidence_contains" not in ee
                or ee["evidence_contains"] in json.dumps(edge.get("evidence", {}))
            )
            for edge in all_edges
        )
        check(found, f"edge missing: {ee['from_contains']} -> {ee['to_contains']} ({ee['relationship_type']})")

    # Cluster coverage
    clustered = {a for c in clusters["clusters"] for a in c["primary_resources"] + c["secondary_resources"]}
    check(set(res) == clustered, f"cluster coverage mismatch: {sorted(set(res) ^ clustered)}")
    check(
        any(c["creation_order_depth"] == 0 and "networking" in c["cluster_id"] for c in clusters["clusters"]),
        "no networking cluster at depth 0",
    )

    # AI detection
    check(inv["ai_detection"]["has_ai_workload"] is exp["ai_detection"]["has_ai_workload"], "ai_detection mismatch")

    # live_metadata + drift
    lm = inv["live_metadata"]
    check(lm.get("method") == exp["live_metadata"]["method"], "live method")
    check(lm.get("project") == exp["live_metadata"]["project"], "live project")
    warns = json.dumps(lm.get("capture_warnings", [])).lower()
    for w in exp["live_metadata"]["capture_warnings_must_mention"]:
        check(w in warns, f"capture_warnings missing mention of {w}")
    drift = lm.get("drift", {})
    check(
        drift.get("resources_terraform_only", 99) <= exp["live_metadata"]["drift"]["resources_terraform_only_max"],
        f"resources_terraform_only={drift.get('resources_terraform_only')}",
    )
    check(
        drift.get("resources_live_only", 0) >= exp["live_metadata"]["drift"]["resources_live_only_min"],
        f"resources_live_only={drift.get('resources_live_only')}",
    )
    conflict_fields = get_conflict_fields(inv)
    for f in exp["live_metadata"]["drift"]["config_conflict_fields_must_include"]:
        check(f in conflict_fields, f"config_conflicts missing field {f}")

    # Safety: no fixture env names paired with values, no AWS names
    doc = json.dumps(inv)
    check("aws_" not in doc.lower().replace("aws-design", ""), "possible AWS naming in discover artifact")

    # Secret hygiene: no env entry anywhere may carry a value payload, and env
    # data must appear only as name lists (env_var_names), never env objects.
    def walk(node, path="$"):
        if isinstance(node, dict):
            if "name" in node and ("value" in node or "valueFrom" in node):
                check(False, f"env-like object with a value payload at {path}")
            for k, v in node.items():
                if k == "env":
                    check(False, f"raw 'env' key at {path} — spec requires env_var_names (names only)")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(inv)
    for env_name in ("STRIPE_SECRET_KEY", "DATABASE_URL", "REDIS_URL"):
        check(f'"{env_name}": ' not in doc, f"fixture env name {env_name} appears as a KEY (value paired) — names must be list items only")

    if FAILS:
        print(f"FAIL ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("PASS — expected-drift.json assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
