#!/usr/bin/env python3
"""Size EC2 instance types and RDS classes from the `utilization` blocks discover-live.md attached to the inventory.

Design (design-refs/compute.md and database.md § Measured sizing) runs this once per inventory and copies
each decision onto the matching aws-design.json entry. Every number comes from
knowledge/design/instance-catalog.json and knowledge/estimate/rightsizing-thresholds.json; nothing is
computed from prose. Stdlib only, like summarize-monitoring.py.

  python3 size-from-utilization.py --inventory gcp-resource-inventory.json \
      [--preferences preferences.json] [--cost-optimization balanced|aggressive|conservative] \
      [--cpu-architecture graviton|x86] [--project <id>] [--output sizing-decisions.json]
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any
SKILL_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = SKILL_ROOT / "knowledge" / "design" / "instance-catalog.json"
THRESHOLDS_PATH = SKILL_ROOT / "knowledge" / "estimate" / "rightsizing-thresholds.json"
GIB = 1024 ** 3
COST_LEVELS = ("conservative", "balanced", "aggressive")
DECLARED_REASONS = ("insufficient", "memory_unavailable", "idle", "skipped_group_member", "user_exempt", "conservative")
_CUSTOM_RE = re.compile(r"^(?P<family>(?:[a-z0-9]+-)?custom)-(?P<vcpu>\d+)-(?P<mb>\d+)(?:-ext)?$")
_SIZED_RE = re.compile(r"^(?P<family>[a-z0-9]+-[a-z]+)-(?P<n>\d+)$")
_DB_CUSTOM_RE = re.compile(r"^db-custom-(?P<vcpu>\d+)-(?P<mb>\d+)$")
_DB_LEGACY_RE = re.compile(r"^(?P<family>db-n1-(?:standard|highmem))-(?P<n>\d+)$")
# Fields an x86_64 mapping takes from x86_equivalent instead of the Graviton decision.
X86_EQUIVALENT_KEYS = ("instance_type", "aws_family", "architecture", "like_for_like", "sizing_provenance",
                       "declared_reason", "sized_from", "sizing_note", "warnings")
def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
def last_segment(value: Any) -> str:
    return str(value).rstrip("/").rsplit("/", 1)[-1] if value is not None else ""
def is_numeric_block(block: Any) -> bool:
    return isinstance(block, dict) and isinstance(block.get("p95"), (int, float))
def round2(value: float) -> float:
    return round(value + 0.0, 2)
# ---------------------------------------------------------------- catalog lookups
class Catalog:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.aws_families = data["aws_families"]
        self.gce = data["gce"]
        self.rds = data["rds"]
    def sizes(self, family: str) -> list[dict[str, Any]]:
        return self.aws_families[family]["sizes"]
    def is_burstable(self, family: str) -> bool:
        return bool(self.aws_families[family].get("burstable"))
    def x86_fallback(self, family: str) -> str:
        return self.aws_families[family]["x86_fallback"]
    def burst_family(self, architecture: str) -> str:
        return "t4g" if architecture == "graviton" else "t3"
    def gce_spec(self, machine_type: str) -> dict[str, Any] | None:
        """Declared vcpu / memory_gib / reserved_vcpu / aws_family for a GCE machine type name."""
        shared = self.gce["shared_core"]["types"].get(machine_type)
        if shared:
            return {"machine_type": machine_type, "vcpu": shared["vcpu"], "reserved_vcpu": shared.get("reserved_vcpu"),
                    "memory_gib": shared["memory_gib"], "aws_family": shared["aws_family"]}
        custom = _CUSTOM_RE.match(machine_type)
        if custom:
            family = self.gce["families"].get(custom.group("family"))
            if not family:
                return None
            return {"machine_type": machine_type, "vcpu": int(custom.group("vcpu")), "reserved_vcpu": None,
                    "memory_gib": int(custom.group("mb")) / 1024, "aws_family": family["aws_family"]}
        sized = _SIZED_RE.match(machine_type)
        if sized:
            family = self.gce["families"].get(sized.group("family"))
            if not family or "gib_per_vcpu" not in family:
                return None
            n = int(sized.group("n"))
            return {"machine_type": machine_type, "vcpu": n, "reserved_vcpu": None,
                    "memory_gib": n * family["gib_per_vcpu"], "aws_family": family["aws_family"]}
        return None
    def rds_classes(self, family: str) -> list[dict[str, Any]]:
        return self.rds["families"][family]["classes"]
    def cloudsql_spec(self, tier: str) -> dict[str, Any] | None:
        sql = self.rds["cloudsql"]
        shared = sql["shared_core"].get(tier)
        if shared:
            return {"tier": tier, "vcpu": shared["vcpu"], "reserved_vcpu": shared.get("reserved_vcpu"),
                    "memory_gib": shared["memory_gib"], "rds_family": shared["rds_family"]}
        custom = _DB_CUSTOM_RE.match(tier)
        if custom:
            vcpu, memory_gib = int(custom.group("vcpu")), int(custom.group("mb")) / 1024
            highmem = memory_gib / vcpu > sql["custom_highmem_gib_per_vcpu_above"]
            return {"tier": tier, "vcpu": vcpu, "reserved_vcpu": None, "memory_gib": memory_gib,
                    "rds_family": "db.r7g" if highmem else "db.m7g"}
        legacy = _DB_LEGACY_RE.match(tier)
        if legacy:
            family = sql["legacy_families"][legacy.group("family")]
            n = int(legacy.group("n"))
            return {"tier": tier, "vcpu": n, "reserved_vcpu": None, "memory_gib": n * family["gib_per_vcpu"],
                    "rds_family": family["rds_family"]}
        return None
    def db_instance_class_memory(self, memory_gib: float) -> float:
        """RDS DBInstanceClassMemory in bytes: the advertised class memory less what RDS reserves for the OS and
        its management processes (catalog rds.max_connections.reserved_memory, fitted to the CHAP_Limits anchors)."""
        reserved = self.rds["max_connections"]["reserved_memory"]
        usable_gib = max(memory_gib - reserved["fixed_gib"] - reserved["fraction"] * memory_gib, 0.0)
        return usable_gib * GIB

    def max_connections(self, engine: str, memory_gib: float) -> int | None:
        rule = self.rds["max_connections"].get(engine)
        if not rule or not rule.get("divisor"):
            return None
        value = math.floor(self.db_instance_class_memory(memory_gib) / rule["divisor"])
        cap = rule.get("cap")
        return min(value, cap) if cap else value
def engine_of(database_version: str) -> str:
    version = (database_version or "").upper()
    if version.startswith("POSTGRES"):
        return "postgresql"
    if version.startswith("MYSQL"):
        return "mysql"
    if version.startswith("SQLSERVER"):
        return "sqlserver"
    if version.startswith("MARIADB"):
        return "mariadb"
    return "unknown"
def anchor_index(sizes: list[dict[str, Any]], vcpu: float, memory_gib: float) -> int | None:
    """Like-for-like anchor: the smallest size whose vcpu AND memory_gib are both >= the declared values."""
    for index, size in enumerate(sizes):
        if size["vcpu"] >= vcpu and size["memory_gib"] >= memory_gib:
            return index
    return None
def baseline_ok(size: dict[str, Any], load_vcpu: float) -> bool:
    """burstable_caution: load in vCPU must fit under the target's baseline (target_vcpu × baseline_cpu_fraction)."""
    fraction = size.get("baseline_cpu_fraction")
    if fraction is None:
        return True
    return load_vcpu <= size["vcpu"] * fraction + 1e-9
def first_fit(sizes: list[dict[str, Any]], upper: int, required_vcpu: float, required_memory_gib: float,
              load_vcpu: float | None = None, check_baseline: bool = False) -> int | None:
    for index in range(0, upper + 1):
        size = sizes[index]
        if size["vcpu"] + 1e-9 < required_vcpu or size["memory_gib"] + 1e-9 < required_memory_gib:
            continue
        if check_baseline and load_vcpu is not None and not baseline_ok(size, load_vcpu):
            continue
        return index
    return None
def apply_step_cap(uncapped: int, anchor: int, step_cap: int | None) -> int:
    """The cap is a floor on how far below the anchor the pick may go; it never pushes below the requirement."""
    if step_cap is None:
        return uncapped
    return max(uncapped, anchor - step_cap)
# ---------------------------------------------------------------- shared declared-path helpers
def declared_decision(reason: str, detail: str, anchor_name: str | None) -> dict[str, Any]:
    if reason not in DECLARED_REASONS:
        raise ValueError(reason)
    return {"sizing_provenance": "declared", "declared_reason": reason, "declared_detail": detail,
            "like_for_like": anchor_name}
def gate_reason(util: dict[str, Any] | None, cost_optimization: str, exempt: bool,
                check_idle_and_mig: bool) -> tuple[str, str] | None:
    """Return (declared_reason, detail) when the measured rule must not run, else None."""
    if cost_optimization == "conservative":
        return "conservative", "cost_optimization is conservative: like-for-like capacity, no right-sizing"
    if exempt:
        return "user_exempt", "named in preferences.sizing_exemptions (known upcoming load change)"
    if not util:
        return "insufficient", "no utilization block on the inventory entry (IaC-only run, consent declined, or no summary match)"
    if check_idle_and_mig and util.get("mig_member"):
        return "skipped_group_member", "managed-instance-group member: right-size the group template in a follow-up, not one member"
    coverage = util.get("coverage")
    if coverage != "sufficient":
        cpu = util.get("cpu") or {}
        present, expected = cpu.get("samples_present"), cpu.get("samples_expected")
        if coverage == "insufficient" and expected:
            missing = expected - (present or 0)
            return "insufficient", f"cpu coverage {present}/{expected} hourly samples ({missing} missing hours); below coverage_min"
        return "insufficient", f"cpu coverage is {coverage or 'absent'}: the monitoring row was skipped or returned no series"
    if not is_numeric_block(util.get("memory")):
        status = (util.get("memory") or {}).get("status", "absent")
        return "memory_unavailable", f"memory is {status}: CPU alone cannot change the size inside a fixed-ratio family; install the Ops Agent to unlock measured sizing"
    if check_idle_and_mig and util.get("idle"):
        return "idle", f"cpu p95 {util['cpu']['p95']} with memory p95 {util['memory']['p95']}: decommission candidate, kept at declared size"
    return None
# ---------------------------------------------------------------- GCE
def size_vm(spec: dict[str, Any], util: dict[str, Any] | None, catalog: Catalog, thresholds: dict[str, Any],
            cost_optimization: str, architecture: str, exempt: bool) -> dict[str, Any]:
    family = spec["aws_family"] if architecture == "graviton" else catalog.x86_fallback(spec["aws_family"])
    sizes = catalog.sizes(family)
    anchor = anchor_index(sizes, spec["vcpu"], spec["memory_gib"])
    warnings: list[str] = []
    if anchor is None:
        anchor = len(sizes) - 1
        warnings.append(f"{spec['machine_type']} exceeds the largest {family} size in the catalog; anchored to {sizes[anchor]['name']}")
    anchor_name = sizes[anchor]["name"]
    out: dict[str, Any] = {"aws_family": family, "architecture": catalog.aws_families[family]["architecture"],
                           "declared": {"vcpu": spec["vcpu"], "reserved_vcpu": spec["reserved_vcpu"], "memory_gib": spec["memory_gib"]}}
    reason = gate_reason(util, cost_optimization, exempt, check_idle_and_mig=True)
    if reason:
        out.update(declared_decision(reason[0], reason[1], anchor_name))
        out["instance_type"] = anchor_name
        if util and util.get("burst"):
            warnings.append("burst: true was recorded but the VM stayed declared; a burstable target was not evaluated")
        out["warnings"] = warnings
        return out
    assert util is not None
    headroom = thresholds["headroom_factor"]
    step_cap = thresholds["step_cap"][cost_optimization]
    cpu_p95, memory_p95 = util["cpu"]["p95"], util["memory"]["p95"]
    load_vcpu = (spec["reserved_vcpu"] or spec["vcpu"]) * cpu_p95
    required_vcpu = load_vcpu * headroom
    required_memory_gib = spec["memory_gib"] * memory_p95 * headroom
    sized_from: dict[str, Any] = {"cpu_p95": cpu_p95, "memory_p95": memory_p95, "window_days": util.get("window_days"),
                                  "required_vcpu": round2(required_vcpu), "required_memory_gib": round2(required_memory_gib),
                                  "like_for_like": anchor_name, "step_cap": step_cap}
    note: str | None = None
    pick_sizes, pick_anchor = sizes, anchor
    if util.get("burst"):
        burst_family = catalog.burst_family(architecture)
        burst_sizes = catalog.sizes(burst_family)
        burst_anchor = anchor_index(burst_sizes, spec["vcpu"], spec["memory_gib"])
        fit = None
        if burst_anchor is not None:
            fit = first_fit(burst_sizes, burst_anchor, required_vcpu, required_memory_gib, load_vcpu, check_baseline=True)
        if fit is not None:
            pick_sizes, pick_anchor = burst_sizes, burst_anchor
            uncapped = fit
            sized_from["burst_family"] = burst_family
            note = "burst"
            warnings.append(f"burst pattern: sized onto burstable {burst_family} where {load_vcpu:.2f} vCPU of sustained load fits under the baseline")
        else:
            uncapped = first_fit(sizes, anchor, required_vcpu, required_memory_gib)
            note = "burst_no_burstable_fit"
            warnings.append(f"burst pattern but no {burst_family} size at or below the anchor carries {load_vcpu:.2f} vCPU under its baseline; fixed size with an Auto Scaling note")
            if uncapped is None:
                uncapped = anchor
    else:
        uncapped = first_fit(sizes, anchor, required_vcpu, required_memory_gib, load_vcpu,
                             check_baseline=catalog.is_burstable(family))
    if uncapped is None:
        # Nothing at or below the anchor meets the requirement: measured sizing never picks above like-for-like.
        uncapped = anchor
        top = pick_sizes[anchor]
        if required_memory_gib > top["memory_gib"] + 1e-9:
            note = "memory_bound"
            warnings.append(f"memory p95 {memory_p95} needs {required_memory_gib:.1f} GiB with headroom; {anchor_name} is the smallest {family} size that holds it")
        elif required_vcpu > top["vcpu"] + 1e-9:
            note = "cpu_bound"
            warnings.append(f"cpu p95 {cpu_p95} needs {required_vcpu:.2f} vCPU with headroom; kept at like-for-like {anchor_name}")
        else:
            note = "burstable_baseline_exceeded"
            warnings.append(f"sustained {load_vcpu:.2f} vCPU exceeds every {family} baseline at or below {anchor_name} "
                            f"({top['vcpu'] * top.get('baseline_cpu_fraction', 1):.2f} vCPU); kept at like-for-like, expect throttling or Unlimited-mode charges")
    elif note is None and uncapped == anchor:
        vcpu_only = first_fit(pick_sizes, anchor, required_vcpu, 0.0)
        if vcpu_only is not None and vcpu_only < uncapped:
            note = "memory_bound"
            warnings.append(f"memory p95 {memory_p95} keeps the VM at like-for-like {anchor_name}; CPU alone would allow {pick_sizes[vcpu_only]['name']}")
    capped = apply_step_cap(uncapped, pick_anchor, step_cap)
    sized_from["uncapped"] = pick_sizes[uncapped]["name"]
    sized_from["capped"] = pick_sizes[capped]["name"]
    out.update({"sizing_provenance": "measured", "instance_type": pick_sizes[capped]["name"],
                "like_for_like": anchor_name, "sized_from": sized_from})
    if note:
        out["sizing_note"] = note
    out["warnings"] = warnings
    return out
# ---------------------------------------------------------------- Cloud SQL
def storage_decision(util: dict[str, Any] | None, config: dict[str, Any], catalog: Catalog,
                     thresholds: dict[str, Any], measured_allowed: bool) -> tuple[dict[str, Any], list[str]]:
    """Allocated storage: measured from disk_bytes_used when the class gate passed, else the provisioned disk."""
    gp3 = catalog.rds["storage"]["gp3"]
    rules = thresholds["storage"]
    warnings: list[str] = []
    disk = (util or {}).get("disk_bytes_used") if measured_allowed else None
    # Live capture writes settings.dataDiskSizeGb; the IaC inventory's canonical key is config.disk_size_gb
    # (schema-discover-iac.md "Canonical config keys"); raw Terraform settings.disk_size is the last resort.
    declared_gib = None
    for candidate in (config.get("disk_size_gb"), config.get("settings.dataDiskSizeGb"),
                      (config.get("settings") or {}).get("dataDiskSizeGb"), config.get("disk_size"),
                      (config.get("settings") or {}).get("disk_size")):
        if candidate is not None:
            declared_gib = candidate
            break
    storage = {"storage_type": "gp3", "iops": rules["gp3_iops"], "throughput_mbps": rules["gp3_throughput_mbps"]}
    if isinstance(disk, dict) and isinstance(disk.get("max"), (int, float)):
        raw_gib = disk["max"] * rules["bytes_used_factor"] / GIB
        step = rules["round_up_gib"]
        allocated = max(math.ceil(raw_gib / step) * step, gp3["min_allocated_gib"])
        storage.update({"allocated_gib": allocated, "basis": "measured",
                        "calculation": f"disk_bytes_used.max {disk['max']} × {rules['bytes_used_factor']} = {raw_gib:.2f} GiB → next {step} GiB, min {gp3['min_allocated_gib']}"})
        warnings.append("IOPS were not measured in v1: gp3 baseline 3000 IOPS / 125 MB/s assumed; a large PD-SSD may have been buying more IOPS than this")
    else:
        try:
            allocated = max(int(float(declared_gib)), gp3["min_allocated_gib"]) if declared_gib is not None else None
        except (TypeError, ValueError):
            allocated = None
        if allocated is None:
            calculation = "no provisioned disk size in the inventory (disk_size_gb / settings.dataDiskSizeGb absent) and disk_bytes_used not captured: size storage by hand"
        else:
            calculation = f"provisioned Cloud SQL disk {declared_gib} GB (upper bound), min {gp3['min_allocated_gib']}: the class stayed declared or disk_bytes_used was not captured"
        storage.update({"allocated_gib": allocated, "basis": "declared", "calculation": calculation})
    return storage, warnings
def size_database(spec: dict[str, Any], engine: str, util: dict[str, Any] | None, config: dict[str, Any], catalog: Catalog,
                  thresholds: dict[str, Any], cost_optimization: str, exempt: bool) -> dict[str, Any]:
    family = spec["rds_family"]
    classes = catalog.rds_classes(family)
    anchor = anchor_index(classes, spec["vcpu"], spec["memory_gib"])
    warnings: list[str] = []
    if anchor is None:
        anchor = len(classes) - 1
        warnings.append(f"{spec['tier']} exceeds the largest {family} class in the catalog; anchored to {classes[anchor]['name']}")
    anchor_name = classes[anchor]["name"]
    out: dict[str, Any] = {"rds_family": family, "engine": engine,
                           "declared": {"vcpu": spec["vcpu"], "reserved_vcpu": spec["reserved_vcpu"], "memory_gib": spec["memory_gib"]}}
    reason = gate_reason(util, cost_optimization, exempt, check_idle_and_mig=False)
    storage, storage_warnings = storage_decision(util, config, catalog, thresholds, measured_allowed=reason is None)
    if reason:
        out.update(declared_decision(reason[0], reason[1], anchor_name))
        pick = anchor
    else:
        assert util is not None
        headroom = thresholds["headroom_factor"]
        step_cap = thresholds["step_cap"][cost_optimization]
        cpu_p95, memory_p95 = util["cpu"]["p95"], util["memory"]["p95"]
        load_vcpu = (spec["reserved_vcpu"] or spec["vcpu"]) * cpu_p95
        required_vcpu = load_vcpu * headroom
        note: str | None = None
        if memory_p95 >= thresholds["memory_saturated_p95_min"]:
            required_memory_gib = spec["memory_gib"]
            uncapped = anchor
            note = "memory_saturated"
            warnings.append(f"memory p95 {memory_p95} is at saturation (Cloud SQL counts page cache); the declared class is the floor, not evidence of need")
        else:
            required_memory_gib = spec["memory_gib"] * memory_p95 * headroom
            uncapped = first_fit(classes, anchor, required_vcpu, required_memory_gib)
            if uncapped is None:
                uncapped = anchor
                if required_memory_gib > classes[anchor]["memory_gib"] + 1e-9:
                    note = "memory_bound"
                else:
                    note = "cpu_bound"
                warnings.append(f"measured requirement exceeds like-for-like {anchor_name}; kept at like-for-like (measured sizing never picks above it)")
            elif uncapped == anchor:
                vcpu_only = first_fit(classes, anchor, required_vcpu, 0.0)
                if vcpu_only is not None and vcpu_only < uncapped:
                    note = "memory_bound"
        capped = apply_step_cap(uncapped, anchor, step_cap)
        pick = capped
        sized_from = {"cpu_p95": cpu_p95, "memory_p95": memory_p95, "window_days": util.get("window_days"),
                      "required_vcpu": round2(required_vcpu), "required_memory_gib": round2(required_memory_gib),
                      "like_for_like": anchor_name, "uncapped": classes[uncapped]["name"], "capped": classes[capped]["name"],
                      "step_cap": step_cap}
        # Connections are compared with the class picked from CPU + memory, never the other way round.
        connections = util.get("connections")
        proxy_rule = thresholds["rds_proxy"]
        rds_proxy = False
        max_conn = catalog.max_connections(engine, classes[pick]["memory_gib"])
        if is_numeric_block(connections) and max_conn is not None:
            conn_p95 = connections["p95"]
            near_limit = proxy_rule.get("near_limit_fraction")
            if conn_p95 <= max_conn and near_limit and conn_p95 >= max_conn * near_limit:
                warnings.append(f"connections p95 {conn_p95} is within {round((1 - near_limit) * 100)}% of {classes[pick]['name']} max_connections {max_conn} (modeled from DBInstanceClassMemory, which RDS computes per class): confirm with SHOW GLOBAL VARIABLES LIKE 'max_connections' after migration or add RDS Proxy")
            if conn_p95 > max_conn:
                if cpu_p95 <= proxy_rule["cpu_p95_max"]:
                    rds_proxy = True
                    warnings.append(f"connections p95 {conn_p95} exceeds {classes[pick]['name']} max_connections {max_conn} with cpu p95 {cpu_p95} <= {proxy_rule['cpu_p95_max']}: add RDS Proxy")
                else:
                    # cpu p95 above the proxy ceiling already puts the pick at like-for-like (× 1.3 headroom on more than
                    # half the vCPU), and measured sizing never goes above it: this is a finding, not a proxy.
                    note = note or "connections_bound"
                    warnings.append(f"connections p95 {conn_p95} exceeds {classes[pick]['name']} max_connections {max_conn} with cpu p95 {cpu_p95} > {proxy_rule['cpu_p95_max']}: a busy database needs a larger class than like-for-like, not a proxy; review by hand")
            sized_from["connections_p95"] = conn_p95
        elif not is_numeric_block(connections):
            warnings.append("connections metric has no data: the RDS Proxy decision was skipped")
        sized_from["max_connections"] = max_conn
        out.update({"sizing_provenance": "measured", "like_for_like": anchor_name, "sized_from": sized_from, "rds_proxy": rds_proxy})
        if note:
            out["sizing_note"] = note
    out["instance_class"] = classes[pick]["name"]
    out["storage"] = storage
    out["warnings"] = warnings + storage_warnings
    return out
# ---------------------------------------------------------------- inventory walk
def resource_key(resource: dict[str, Any], project: str | None) -> tuple[str, str] | None:
    config = resource.get("config") or {}
    rtype = resource.get("type")
    if rtype == "google_compute_instance":
        iid = config.get("id")
        util = resource.get("utilization") or {}
        iid = iid if iid is not None else util.get("instance_id")
        return ("gce_instance", str(iid)) if iid is not None else None
    if rtype == "google_sql_database_instance":
        util = resource.get("utilization") or {}
        if util.get("database_id"):
            return ("cloudsql_database", util["database_id"])
        name = config.get("name")
        if project and name:
            return ("cloudsql_database", f"{project}:{name}")
    return None
def machine_type_of(config: dict[str, Any]) -> str:
    return last_segment(config.get("machineType") or config.get("machine_type") or "")
def tier_of(config: dict[str, Any]) -> str:
    settings = config.get("settings") or {}
    return str(config.get("settings.tier") or settings.get("tier") or config.get("tier") or "")
def version_of(config: dict[str, Any]) -> str:
    return str(config.get("databaseVersion") or config.get("database_version") or "")
def _constraint_value(constraints: dict[str, Any], key: str) -> Any:
    entry = constraints.get(key)
    return entry.get("value") if isinstance(entry, dict) else entry


def read_preferences(path: Path | None) -> tuple[str | None, str | None, list[str]]:
    """cost_optimization, cpu_architecture and sizing_exemptions from preferences.json.

    Clarify Q-E2 "No — match current capacity" writes right_sizing: false AND cost_optimization: conservative
    (clarify-assemble.md § Q-E2), so cost_optimization alone governs. A preferences file written before that
    rule — right_sizing explicitly false beside a non-conservative appetite — is honoured the same way here:
    an explicit "match current capacity" answer always yields declared sizes.
    """
    if path is None:
        return None, None, []
    prefs = load_json(path)
    constraints = prefs.get("design_constraints") or {}
    cost = _constraint_value(constraints, "cost_optimization")
    if _constraint_value(constraints, "right_sizing") is False:
        cost = "conservative"
    arch = _constraint_value(constraints, "cpu_architecture")
    exemptions = [str(x) for x in (prefs.get("sizing_exemptions") or [])]
    return cost, arch, exemptions
def size_inventory(inventory: dict[str, Any], catalog: Catalog, thresholds: dict[str, Any], cost_optimization: str,
                   architecture: str, exemptions: list[str], project: str | None = None) -> dict[str, Any]:
    project = project or (inventory.get("metadata") or {}).get("project")
    exempt_set = set(exemptions)
    decisions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for resource in inventory.get("resources") or []:
        key = resource_key(resource, project)
        rtype = resource.get("type")
        if rtype not in ("google_compute_instance", "google_sql_database_instance"):
            continue
        config = resource.get("config") or {}
        util = resource.get("utilization")
        base = {"address": resource.get("address"), "resource_type": key[0] if key else None, "key": key[1] if key else None}
        exempt = bool(key and key[1] in exempt_set)
        if rtype == "google_compute_instance":
            machine_type = machine_type_of(config)
            spec = catalog.gce_spec(machine_type)
            if spec is None:
                skipped.append({**base, "reason": f"machine type {machine_type!r} is not in instance-catalog.json; size by hand"})
                continue
            decision = size_vm(spec, util, catalog, thresholds, cost_optimization, architecture, exempt)
            decision["source_machine_type"] = machine_type
            if architecture == "graviton":
                x86 = size_vm(spec, util, catalog, thresholds, cost_optimization, "x86", exempt)
                # The full x86 decision: an x86_64 mapping (Graviton-incompatible tier) takes every sizing field
                # from here so its like_for_like and sized_from name x86 sizes, not the Graviton ones above.
                decision["x86_equivalent"] = {k: x86[k] for k in X86_EQUIVALENT_KEYS if k in x86}
        else:
            tier = tier_of(config)
            spec = catalog.cloudsql_spec(tier)
            if spec is None:
                skipped.append({**base, "reason": f"Cloud SQL tier {tier!r} is not in instance-catalog.json; size by hand"})
                continue
            decision = size_database(spec, engine_of(version_of(config)), util, config, catalog, thresholds, cost_optimization, exempt)
            decision["source_tier"] = tier
        decisions.append({**base, **decision})
    measured = sum(1 for d in decisions if d["sizing_provenance"] == "measured")
    return {
        "_what_this_is": "Output of skills/gcp-to-aws/scripts/size-from-utilization.py: one sizing decision per Compute Engine VM and Cloud SQL instance, copied onto aws-design.json entries by design-refs/compute.md and database.md § Measured sizing.",
        "cost_optimization": cost_optimization,
        "cpu_architecture": architecture,
        "sizing_exemptions": sorted(exempt_set),
        "thresholds": {"headroom_factor": thresholds["headroom_factor"], "step_cap": thresholds["step_cap"].get(cost_optimization),
                       "coverage_min": thresholds["coverage_min"]},
        "measured_resources": measured,
        "declared_resources": len(decisions) - measured,
        "resources": decisions,
        "skipped": skipped,
    }
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--preferences", type=Path, help="preferences.json: cost_optimization, cpu_architecture, sizing_exemptions")
    parser.add_argument("--cost-optimization", choices=COST_LEVELS, help="override preferences; default balanced")
    parser.add_argument("--cpu-architecture", choices=("graviton", "x86"), help="override preferences; default graviton")
    parser.add_argument("--project", help="GCP project id for Cloud SQL keys when the inventory metadata lacks it")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument("--output", type=Path, help="write JSON here (default: stdout)")
    args = parser.parse_args(argv)
    if not args.inventory.is_file():
        print(f"inventory not found: {args.inventory}", file=sys.stderr)
        return 2
    pref_cost, pref_arch, exemptions = read_preferences(args.preferences)
    cost_optimization = args.cost_optimization or pref_cost or "balanced"
    if cost_optimization not in COST_LEVELS:
        print(f"unknown cost_optimization {cost_optimization!r}; using balanced", file=sys.stderr)
        cost_optimization = "balanced"
    architecture = args.cpu_architecture or ("x86" if pref_arch == "x86" else "graviton")
    catalog = Catalog(load_json(args.catalog))
    thresholds = load_json(args.thresholds)
    result = size_inventory(load_json(args.inventory), catalog, thresholds, cost_optimization, architecture, exemptions, args.project)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0
if __name__ == "__main__":
    sys.exit(main())
