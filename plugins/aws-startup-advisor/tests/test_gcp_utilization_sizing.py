"""Design tests for skills/gcp-to-aws/scripts/size-from-utilization.py and the sizing contracts around it.

Every fixture resource in fixtures/gcp-utilization-capture must land on the size, provenance,
`declared_reason` or `sizing_note` its README documents; the catalog and the thresholds file are
the only sources of numbers; graviton.md's explicit rows agree with the like-for-like anchor rule;
Clarify, Estimate and the report carry the fields Design writes.
"""
from __future__ import annotations
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
import pytest
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "gcp-to-aws"
SCRIPT = SKILL / "scripts" / "size-from-utilization.py"
SUMMARIZE = SKILL / "scripts" / "summarize-monitoring.py"
CATALOG_PATH = SKILL / "knowledge" / "design" / "instance-catalog.json"
THRESHOLDS_PATH = SKILL / "knowledge" / "estimate" / "rightsizing-thresholds.json"
REFS = SKILL / "references"
FIXTURE = PLUGIN_ROOT / "fixtures" / "gcp-utilization-capture"
INVENTORY = FIXTURE / "after-discover" / "gcp-resource-inventory.json"
PREFERENCES = FIXTURE / "after-clarify" / "preferences.json"
EXPECTED = FIXTURE / "after-design" / "sizing-decisions.json"
def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
sizer = _load(SCRIPT, "size_from_utilization")
summarizer = _load(SUMMARIZE, "summarize_monitoring")
CATALOG = sizer.Catalog(json.loads(CATALOG_PATH.read_text()))
THRESHOLDS = json.loads(THRESHOLDS_PATH.read_text())
INVENTORY_DATA = json.loads(INVENTORY.read_text())
def run(cost: str = "balanced", exemptions: list[str] | None = None, architecture: str = "graviton",
        inventory: dict | None = None) -> dict[str, dict]:
    result = sizer.size_inventory(inventory or INVENTORY_DATA, CATALOG, THRESHOLDS, cost, architecture, exemptions or [])
    return {r["address"].split(".", 1)[1]: r for r in result["resources"]}
def vm_entry(address: str) -> dict:
    return next(r for r in INVENTORY_DATA["resources"] if r["address"].endswith(address))
# --------------------------------------------------------------------------- golden
def test_cli_reproduces_the_after_design_golden_byte_for_byte(tmp_path):
    out = tmp_path / "sizing-decisions.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--inventory", str(INVENTORY), "--output", str(out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == EXPECTED.read_bytes()
def test_cli_exits_two_on_missing_inventory(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--inventory", str(tmp_path / "nope.json")], capture_output=True, text=True)
    assert result.returncode == 2
# --------------------------------------------------------------------------- the documented cases
BALANCED_CASES = {
    # address suffix: (pick, provenance, declared_reason, sizing_note, like_for_like)
    "web_steady": ("m7g.large", "measured", None, None, "m7g.2xlarge"),
    "api_lowload": ("m7g.large", "measured", None, None, "m7g.2xlarge"),
    "cache_heavy": ("m7g.2xlarge", "measured", None, "memory_bound", "m7g.2xlarge"),
    "batch_bursty": ("m7g.2xlarge", "declared", "memory_unavailable", None, "m7g.2xlarge"),
    "new_vm": ("m7g.large", "declared", "insufficient", None, "m7g.large"),
    "idle_vm": ("m7g.large", "declared", "idle", None, "m7g.large"),
    "web_mig_7f3k": ("t4g.medium", "declared", "skipped_group_member", None, "t4g.medium"),
    "ops_small": ("t4g.small", "measured", None, "burstable_baseline_exceeded", "t4g.small"),
    "jobs_bursty": ("t4g.xlarge", "measured", None, "burst", "m7g.2xlarge"),
    "orders_db": ("db.t4g.micro", "measured", None, "memory_saturated", "db.t4g.micro"),
    "reports_db": ("db.m7g.large", "measured", None, None, "db.m7g.large"),
}
@pytest.mark.parametrize("name,expected", sorted(BALANCED_CASES.items()))
def test_every_fixture_resource_lands_where_the_readme_says(name, expected):
    golden = {r["address"].split(".", 1)[1]: r for r in json.loads(EXPECTED.read_text())["resources"]}
    decision = golden[name]
    pick, provenance, reason, note, anchor = expected
    assert (decision.get("instance_type") or decision.get("instance_class")) == pick
    assert decision["sizing_provenance"] == provenance
    assert decision.get("declared_reason") == reason
    assert decision.get("sizing_note") == note
    assert decision["like_for_like"] == anchor
    if provenance == "measured":
        sized = decision["sized_from"]
        assert set(sized) >= {"cpu_p95", "memory_p95", "window_days", "required_vcpu", "required_memory_gib",
                              "like_for_like", "uncapped", "capped", "step_cap"}
        assert sized["like_for_like"] == anchor and sized["step_cap"] == 2
        assert "declared_reason" not in decision
    else:
        assert reason in sizer.DECLARED_REASONS
        assert "sized_from" not in decision
        assert (decision.get("instance_type") or decision.get("instance_class")) == anchor
def test_golden_counts_match_the_provenance_split():
    golden = json.loads(EXPECTED.read_text())
    assert golden["measured_resources"] == 7 and golden["declared_resources"] == 4 and golden["skipped"] == []
    assert golden["cost_optimization"] == "balanced" and golden["thresholds"]["step_cap"] == 2
def test_twelve_percent_cpu_low_memory_is_exactly_two_steps_so_balanced_and_aggressive_agree():
    balanced, aggressive = run("balanced")["web_steady"], run("aggressive")["web_steady"]
    assert balanced["sized_from"]["uncapped"] == balanced["sized_from"]["capped"] == "m7g.large"
    assert aggressive["instance_type"] == "m7g.large" and aggressive["sized_from"]["step_cap"] is None
    sizes = [s["name"] for s in CATALOG.sizes("m7g")]
    assert sizes.index("m7g.2xlarge") - sizes.index("m7g.large") == 2
    assert balanced["sized_from"]["required_vcpu"] == round(8 * 0.1214 * 1.3, 2)
    assert balanced["sized_from"]["required_memory_gib"] == round(32 * 0.1512 * 1.3, 2)
def test_low_load_vm_is_capped_under_balanced_and_uncapped_under_aggressive():
    balanced, aggressive = run("balanced")["api_lowload"], run("aggressive")["api_lowload"]
    assert balanced["sized_from"]["uncapped"] == "m7g.medium" and balanced["instance_type"] == "m7g.large"
    assert aggressive["instance_type"] == aggressive["sized_from"]["uncapped"] == "m7g.medium"
    assert vm_entry("api_lowload")["utilization"]["cpu"]["p95"] > THRESHOLDS["idle"]["cpu_p95_max"]
def test_memory_bound_vm_is_measured_and_stays_at_the_anchor():
    decision = run()["cache_heavy"]
    assert decision["sizing_provenance"] == "measured" and decision["sizing_note"] == "memory_bound"
    assert decision["instance_type"] == decision["like_for_like"] == "m7g.2xlarge"
    assert decision["sized_from"]["required_memory_gib"] > 16  # m7g.xlarge cannot hold it
    assert decision["sized_from"]["required_vcpu"] < 2  # CPU alone would have allowed m7g.large
def test_bursty_vm_passes_the_vcpu_baseline_at_t4g_xlarge_and_fails_at_t4g_large():
    decision = run()["jobs_bursty"]
    util = vm_entry("jobs_bursty")["utilization"]
    assert util["burst"] is True
    load_vcpu = 8 * util["cpu"]["p95"]
    t4g = {s["name"]: s for s in CATALOG.sizes("t4g")}
    assert not sizer.baseline_ok(t4g["t4g.large"], load_vcpu)  # 2 × 0.30 = 0.60 < 0.82
    assert sizer.baseline_ok(t4g["t4g.xlarge"], load_vcpu)  # 4 × 0.40 = 1.6
    assert decision["instance_type"] == "t4g.xlarge" and decision["sized_from"]["burst_family"] == "t4g"
    assert decision["like_for_like"] == "m7g.2xlarge"  # the like-for-like band is still the fixed family
    # x86_equivalent is the full x86 decision: an x86_64 mapping must not pair t3 with the m7g anchor.
    x86 = decision["x86_equivalent"]
    assert x86["instance_type"] == "t3.xlarge" and x86["like_for_like"] == "m6i.2xlarge"
    assert x86["sizing_provenance"] == "measured" and x86["architecture"] == "x86_64"
    assert x86["sized_from"]["like_for_like"] == "m6i.2xlarge" and x86["sized_from"]["burst_family"] == "t3"
    assert x86["sized_from"]["capped"].startswith(("m6i.", "t3."))
    assert x86["sized_from"]["uncapped"].startswith(("m6i.", "t3."))
    assert not any(name.startswith("m7g.") for name in (x86["sized_from"]["uncapped"], x86["sized_from"]["capped"]))
def test_bursty_vm_without_memory_stays_declared_memory_unavailable():
    decision = run()["batch_bursty"]
    assert decision["declared_reason"] == "memory_unavailable"
    assert "install the Ops Agent" in decision["declared_detail"]
def test_short_history_is_insufficient_with_the_missing_hours_named():
    decision = run()["new_vm"]
    assert decision["declared_reason"] == "insufficient"
    assert "100/168" in decision["declared_detail"] and "68 missing hours" in decision["declared_detail"]
def test_idle_vm_keeps_declared_size_and_is_flagged():
    decision = run()["idle_vm"]
    assert decision["declared_reason"] == "idle" and decision["instance_type"] == "m7g.large"
def test_mig_member_is_skipped_group_member():
    assert run()["web_mig_7f3k"]["declared_reason"] == "skipped_group_member"
def test_e2_small_is_sized_from_half_a_reserved_vcpu_with_p95_above_one():
    decision = run()["ops_small"]
    util = vm_entry("ops_small")["utilization"]
    assert util["cpu"]["p95"] > 1.0
    assert decision["declared"] == {"vcpu": 2, "reserved_vcpu": 0.5, "memory_gib": 2}
    assert decision["sized_from"]["required_vcpu"] == round(0.5 * util["cpu"]["p95"] * 1.3, 2)
    # 0.61 vCPU of sustained load beats every t4g baseline at or below the t4g.small anchor.
    assert decision["sizing_note"] == "burstable_baseline_exceeded" and decision["instance_type"] == "t4g.small"
    assert decision["sizing_provenance"] == "measured"
def test_user_exemption_from_preferences_keeps_the_vm_declared():
    prefs_cost, prefs_arch, exemptions = sizer.read_preferences(PREFERENCES)
    assert prefs_cost == "aggressive" and prefs_arch == "graviton" and exemptions == ["1000000000000000001"]
    decisions = run(prefs_cost, exemptions)
    exempt = decisions["web_steady"]
    assert exempt["sizing_provenance"] == "declared" and exempt["declared_reason"] == "user_exempt"
    assert exempt["instance_type"] == exempt["like_for_like"] == "m7g.2xlarge"
    assert decisions["api_lowload"]["instance_type"] == "m7g.medium"  # aggressive still applies to the rest
    db_exempt = run("balanced", ["acme-prod:orders-db"])["orders_db"]
    assert db_exempt["declared_reason"] == "user_exempt" and db_exempt["instance_class"] == "db.t4g.micro"
    assert db_exempt["storage"]["basis"] == "declared" and db_exempt["storage"]["allocated_gib"] == 20  # provisioned 10 GiB → gp3 minimum
def test_conservative_keeps_every_resource_declared_at_like_for_like():
    for name, decision in run("conservative").items():
        assert decision["sizing_provenance"] == "declared" and decision["declared_reason"] == "conservative", name
        assert (decision.get("instance_type") or decision.get("instance_class")) == decision["like_for_like"]
def test_the_like_for_like_band_can_be_rebuilt_from_sized_from_alone():
    for name, decision in run().items():
        if decision["sizing_provenance"] != "measured":
            continue
        sized = decision["sized_from"]
        if decision["resource_type"] == "gce_instance":
            spec = CATALOG.gce_spec(decision["source_machine_type"])
            sizes = CATALOG.sizes(decision["aws_family"])
        else:
            spec = CATALOG.cloudsql_spec(decision["source_tier"])
            sizes = CATALOG.rds_classes(decision["rds_family"])
        anchor = sizes[sizer.anchor_index(sizes, spec["vcpu"], spec["memory_gib"])]["name"]
        assert sized["like_for_like"] == anchor == decision["like_for_like"], name
        assert sized["uncapped"] != "" and sized["capped"] != ""
        # the capped pick is never below the uncapped one and never above the anchor
        names = [s["name"] for s in (CATALOG.sizes(sized.get("burst_family")) if sized.get("burst_family") else sizes)]
        assert names.index(sized["uncapped"]) <= names.index(sized["capped"])
        if not sized.get("burst_family"):
            assert names.index(sized["capped"]) <= names.index(anchor)
# --------------------------------------------------------------------------- Cloud SQL
def test_cloud_sql_picks_class_from_cpu_and_memory_then_checks_connections():
    orders = run()["orders_db"]
    assert orders["instance_class"] == "db.t4g.micro" and orders["sizing_note"] == "memory_saturated"
    assert orders["sized_from"]["connections_p95"] == 5.0  # four num_backends series summed, system databases included
    # DBInstanceClassMemory, not the advertised 1 GiB: (1 − 0.25 − 0.045) GiB / 9531392 = 79 (the naive 1 GiB / 9531392 would be 112)
    assert orders["sized_from"]["max_connections"] == 79 == int(CATALOG.db_instance_class_memory(1) // 9531392) < 112
    assert orders["rds_proxy"] is False
    assert orders["storage"] == {"storage_type": "gp3", "iops": 3000, "throughput_mbps": 125, "allocated_gib": 20,
                                 "basis": "measured", "calculation": orders["storage"]["calculation"]}
    assert any("IOPS were not measured" in w for w in orders["warnings"])
    reports = run()["reports_db"]
    assert reports["engine"] == "mysql" and reports["instance_class"] == "db.m7g.large"
    assert reports["sized_from"]["max_connections"] == 630 == int(CATALOG.db_instance_class_memory(8) // 12582880)  # AWS documents about 630 for db.m7g.large MySQL
    assert reports["rds_proxy"] is False and "sizing_note" not in reports
    assert reports["storage"]["allocated_gib"] == 20  # 12 GiB × 1.5 = 18 → 20
def _synthetic_db(cpu_p95: float, memory_p95: float, connections_p95: float, tier: str = "db-custom-4-16384",
                  version: str = "POSTGRES_15", disk_max: int = 40 * 1024 ** 3) -> dict:
    block = lambda p95: {"p95": p95, "mean": p95, "max": p95, "samples_present": 720, "samples_expected": 720}
    return {"metadata": {"project": "acme-prod"}, "resources": [{
        "address": "google_sql_database_instance.synthetic", "type": "google_sql_database_instance",
        "config": {"name": "synthetic", "databaseVersion": version, "settings.tier": tier, "settings.dataDiskSizeGb": "100"},
        "utilization": {"resource_type": "cloudsql_database", "database_id": "acme-prod:synthetic", "window_days": 30,
                        "coverage": "sufficient", "cpu": block(cpu_p95), "memory": block(memory_p95),
                        "connections": block(connections_p95), "disk_bytes_used": block(disk_max)}}]}
def test_rds_proxy_only_when_connections_exceed_the_formula_and_cpu_is_at_or_below_half():
    # db-custom-4-16384 PostgreSQL → anchor db.m7g.xlarge (4 vCPU / 16 GiB); low CPU and memory → db.m7g.large (8 GiB, 832 conns)
    quiet = run(inventory=_synthetic_db(0.10, 0.20, 1200))["synthetic"]
    assert quiet["instance_class"] == "db.m7g.large" and quiet["sized_from"]["max_connections"] == 832
    assert quiet["rds_proxy"] is True
    under = run(inventory=_synthetic_db(0.10, 0.20, 500))["synthetic"]
    assert under["rds_proxy"] is False and under["instance_class"] == "db.m7g.large"
    busy = run(inventory=_synthetic_db(0.60, 0.20, 2500))["synthetic"]
    assert busy["rds_proxy"] is False and busy["instance_class"] == "db.m7g.xlarge"  # like-for-like; never above it
    assert busy["sizing_note"] == "connections_bound" and busy["sized_from"]["max_connections"] == 1693
    storage = quiet["storage"]
    assert storage["allocated_gib"] == 60 and storage["basis"] == "measured"  # 40 GiB × 1.5 = 60
def test_measured_database_never_picks_above_like_for_like():
    hot = run(inventory=_synthetic_db(0.95, 0.50, 10))["synthetic"]
    assert hot["instance_class"] == hot["like_for_like"] == "db.m7g.xlarge" and hot["sizing_note"] == "cpu_bound"
    saturated = run(inventory=_synthetic_db(0.10, 0.95, 10))["synthetic"]
    assert saturated["instance_class"] == "db.m7g.xlarge" and saturated["sizing_note"] == "memory_saturated"
# --------------------------------------------------------------------------- catalog and thresholds
def test_catalog_anchor_rule_resolves_unlisted_types_and_agrees_with_graviton_md():
    spec = CATALOG.gce_spec("n2-standard-16")
    assert spec == {"machine_type": "n2-standard-16", "vcpu": 16, "reserved_vcpu": None, "memory_gib": 64, "aws_family": "m7g"}
    sizes = CATALOG.sizes("m7g")
    assert sizes[sizer.anchor_index(sizes, 16, 64)]["name"] == "m7g.4xlarge"
    graviton = (REFS / "shared" / "graviton.md").read_text()
    table = graviton[graviton.index("## GCP → Graviton instance mapping") :]
    rows = [line for line in table.splitlines() if line.startswith("| ") and "machine type" not in line and "---" not in line]
    checked = 0
    for line in rows:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            break
        gcp_types = [c.strip() for c in cells[0].split("/")]
        x86_targets = [c.strip() for c in cells[1].split("/")]
        arm_targets = [c.strip() for c in cells[2].split("/")]
        for index, machine_type in enumerate(gcp_types):
            spec = CATALOG.gce_spec(machine_type)
            assert spec, machine_type
            arm_sizes = CATALOG.sizes(spec["aws_family"])
            arm_pick = arm_sizes[sizer.anchor_index(arm_sizes, spec["vcpu"], spec["memory_gib"])]["name"]
            expected_arm = arm_targets[index] if len(arm_targets) == len(gcp_types) else arm_targets[0]
            assert arm_pick == expected_arm, (machine_type, arm_pick, expected_arm)
            x86_family = CATALOG.x86_fallback(spec["aws_family"])
            x86_sizes = CATALOG.sizes(x86_family)
            x86_pick = x86_sizes[sizer.anchor_index(x86_sizes, spec["vcpu"], spec["memory_gib"])]["name"]
            in_family = [x for x in x86_targets if x.split(".")[0] == x86_family]
            expected_x86 = in_family[index] if len(in_family) == len(gcp_types) else in_family[0]
            assert x86_pick == expected_x86, (machine_type, x86_pick, expected_x86)
            checked += 1
    assert checked == 9
def test_catalog_parses_custom_shared_core_and_cloud_sql_tiers():
    assert CATALOG.gce_spec("n2-custom-4-8192") == {"machine_type": "n2-custom-4-8192", "vcpu": 4, "reserved_vcpu": None, "memory_gib": 8.0, "aws_family": "m7g"}
    assert CATALOG.gce_spec("custom-2-5120")["memory_gib"] == 5.0
    assert CATALOG.gce_spec("e2-small") == {"machine_type": "e2-small", "vcpu": 2, "reserved_vcpu": 0.5, "memory_gib": 2, "aws_family": "t4g"}
    assert CATALOG.gce_spec("c2-standard-8")["aws_family"] == "c7g"
    assert CATALOG.gce_spec("a2-highgpu-1g") is None
    assert CATALOG.cloudsql_spec("db-f1-micro") == {"tier": "db-f1-micro", "vcpu": 1, "reserved_vcpu": 0.2, "memory_gib": 0.6, "rds_family": "db.t4g"}
    assert CATALOG.cloudsql_spec("db-custom-2-7680")["rds_family"] == "db.m7g"
    assert CATALOG.cloudsql_spec("db-custom-2-16384")["rds_family"] == "db.r7g"
    assert CATALOG.cloudsql_spec("db-n1-highmem-4") == {"tier": "db-n1-highmem-4", "vcpu": 4, "reserved_vcpu": None, "memory_gib": 26.0, "rds_family": "db.r7g"}
    assert CATALOG.max_connections("sqlserver", 8) is None
def test_catalog_sizes_are_ordered_and_sourced():
    data = json.loads(CATALOG_PATH.read_text())
    for family, body in data["aws_families"].items():
        assert body["source"].startswith("https://"), family
        keys = [(s["vcpu"], s["memory_gib"]) for s in body["sizes"]]
        assert keys == sorted(keys), family
        if body.get("burstable"):
            assert all("baseline_cpu_fraction" in s for s in body["sizes"]), family
            assert body["baseline_source"].startswith("https://docs.aws.amazon.com/")
        else:
            assert not any("baseline_cpu_fraction" in s for s in body["sizes"]), family
    for family, body in data["rds"]["families"].items():
        keys = [(c["vcpu"], c["memory_gib"]) for c in body["classes"]]
        assert keys == sorted(keys), family
    assert data["rds"]["max_connections"]["mysql"]["divisor"] == 12582880
    assert data["rds"]["max_connections"]["postgresql"] == {"formula": "min(floor(DBInstanceClassMemory / 9531392), 5000)", "divisor": 9531392, "cap": 5000}
    assert data["rds"]["max_connections"]["source"].startswith("https://docs.aws.amazon.com/AmazonRDS/")
    assert data["rds"]["storage"]["gp3"]["min_allocated_gib"] == 20
    for family, body in data["gce"]["families"].items():
        assert body["source"].startswith("https://cloud.google.com/"), family
        assert body["aws_family"] in data["aws_families"], family
def test_both_scripts_read_the_same_thresholds_file():
    assert summarizer.THRESHOLDS_PATH == THRESHOLDS_PATH == sizer.THRESHOLDS_PATH
    assert summarizer.COVERAGE_MIN == THRESHOLDS["coverage_min"] == 0.8
    assert summarizer.IDLE_CPU_P95_MAX == THRESHOLDS["idle"]["cpu_p95_max"] == 0.05
    assert summarizer.IDLE_MEMORY_P95_MAX == THRESHOLDS["idle"]["memory_p95_max"] == 0.2
    assert (summarizer.BURST_CPU_P95_MAX, summarizer.BURST_SPIKE_MULTIPLE, summarizer.BURST_CONSECUTIVE_HOURS) == (0.3, 2, 2)
    assert THRESHOLDS["headroom_factor"] == 1.3
    assert THRESHOLDS["step_cap"] == {"balanced": 2, "aggressive": None}
    assert THRESHOLDS["rds_proxy"] == {"connections_over_limit": True, "cpu_p95_max": 0.5, "near_limit_fraction": 0.9}
    assert THRESHOLDS["storage"] == {"bytes_used_factor": 1.5, "gp3_iops": 3000, "gp3_throughput_mbps": 125, "round_up_gib": 10}
    assert THRESHOLDS["memory_saturated_p95_min"] == 0.9
    for key in ("headroom_factor", "step_cap", "coverage_min", "idle", "burst", "rds_proxy", "memory_saturated", "storage"):
        assert f"_{key}_why" in THRESHOLDS or key == "burstable_caution", key
    assert "_why" in THRESHOLDS["burstable_caution"]
# --------------------------------------------------------------------------- phase-file contracts
def test_graviton_md_scopes_never_counted_to_the_uplift_and_counts_measured_right_sizing():
    text = (REFS / "shared" / "graviton.md").read_text()
    table = text[text.index("## Savings model") : text.index("## Compatibility tiers")]
    rows = [line for line in table.splitlines() if line.startswith("| **")]
    assert len(rows) == 3
    uplift = next(r for r in rows if "Performance uplift" in r)
    measured = next(r for r in rows if "Measured right-sizing" in r)
    assert "**No**" in uplift and "the uplift is never counted" in uplift
    assert "**Yes**" in measured and "sized_from.like_for_like" in measured and "Part 2D" in measured
    assert "this is the only savings counted" not in table
    assert "c7g.4xlarge" in text and "n2-standard-16" in text and "like-for-like anchor" in text
def test_compute_md_measured_sizing_section_names_script_catalog_and_rule():
    text = (REFS / "design-refs" / "compute.md").read_text()
    section = text[text.index("## Measured sizing") : text.index("## 6-Criteria Rubric")]
    for needle in (
        'python3 "$PLUGIN_ROOT/skills/gcp-to-aws/scripts/size-from-utilization.py"',
        "knowledge/design/instance-catalog.json",
        "knowledge/estimate/rightsizing-thresholds.json",
        "`required_vcpu = (reserved_vcpu or vcpu) × cpu.p95 × headroom_factor`",
        "never picks above the anchor",
        "`capped = max(uncapped, anchor − step_cap)`",
        "(reserved_vcpu or vcpu) × cpu.p95 <= target_vcpu × baseline_cpu_fraction",
        "`sizing_note: \"memory_bound\"`",
        "`sized_from: {cpu_p95, memory_p95, window_days, required_vcpu, required_memory_gib, like_for_like, uncapped, capped, step_cap}`",
        "`conservative`, `user_exempt`, `skipped_group_member`, `insufficient`",
        "`memory_unavailable`, `idle`",
    ):
        assert needle in section, needle
    assert '"sizing_provenance": "measured"' in text and '"sizing_provenance": "declared"' in text
def test_database_md_measured_sizing_section_orders_class_then_connections_then_storage():
    text = (REFS / "design-refs" / "database.md").read_text()
    section = text[text.index("## Measured sizing") : text.index("## Output Schema")]
    assert section.index("Class from CPU and memory first") < section.index("Then connections") < section.index("**Storage.**")
    for needle in (
        "`memory_bytes / 12582880`", "`min(memory_bytes / 9531392, 5000)`", "never a stored integer",
        "`cpu.p95 <= 0.50`", "`sizing_note: \"memory_saturated\"`", "never picks a class above like-for-like",
        "disk_bytes_used.max × 1.5", "20 GiB", "3000 IOPS / 125 MB/s", "did not measure IOPS", "No `db.t4g` switch in v1",
        "`num_backends` summed over every `database` label", "`config.disk_size_gb`", "`aws_config.allocated_storage`",
    ):
        assert needle in section, needle
    assert '"rds_proxy": false' in text and '"max_connections": 79' in text
    assert "DBInstanceClassMemory" in section and "about 630" in section and "is **not** the advertised class memory" in section
    assert '"allocated_storage": 20' in text and '"allocated_gib": 20' not in text  # one aws_config storage key
def test_design_infra_finalizes_measured_sizing_on_every_ec2_and_rds_mapping():
    text = (REFS / "phases" / "design" / "design-infra.md").read_text()
    section = text[text.index("### Finalize measured sizing") : text.index("### Finalize `ecs_mode`")]
    assert "size-from-utilization.py" in section and "`sizing_provenance`" in section
    assert "never changes `aws_service`, `confidence`, or the Q6 topology" in section
def test_clarify_assemble_carries_the_sheet_row_the_q_e2_impact_row_and_exemption_resolution():
    text = (REFS / "phases" / "clarify" / "clarify-assemble.md").read_text()
    veto = "name any resource with a known upcoming load change and the design will keep its declared size"
    q_e0 = text[text.index("### Q-E0") : text.index("### Q-E1")]
    assert "references/vendored/clarify/clarify-cost-appetite.md" in q_e0 and "**not edited here**" in q_e0
    assert "Sized from 30 days of Cloud Monitoring data" in q_e0 and veto in q_e0
    assert "changes nothing" in q_e0
    assert "`sizing_exemptions[]`" in q_e0 and "`config.id` **as a string**" in q_e0 and '`"<project>:" + config.name`' in q_e0
    assert '`declared_reason: "user_exempt"`' in q_e0
    q_e2 = text[text.index("### Q-E2") : text.index("## Gate 2")]
    assert "Recommendation Impact" in q_e2 and veto in q_e2 and "Changes nothing when no utilization data" in q_e2
    sheet = text[text.index("**Assumed (documented defaults") : text.index("AI rows and AWS Activate credits")]
    assert "| Right-sizing appetite | Balanced |" in sheet
    assert "| Q-E0 — Right-sizing appetite | B (balanced)" in text
def test_shared_cost_appetite_file_is_untouched_and_preferences_schema_carries_the_new_fields():
    vendored = REFS / "vendored" / "clarify" / "clarify-cost-appetite.md"
    canonical = PLUGIN_ROOT / "skills" / "shared" / "clarify" / "clarify-cost-appetite.md"
    assert vendored.read_bytes() == canonical.read_bytes()
    assert "sizing_exemptions" not in vendored.read_text() and "Cloud Monitoring" not in vendored.read_text()
    schema = (REFS / "shared" / "schema-preferences.md").read_text()
    assert '"sizing_exemptions": ["1000000000000000001", "acme-prod:orders-db"]' in schema
    assert "| `cost_optimization`" in schema and "Q-E0" in schema
    prefs = json.loads(PREFERENCES.read_text())
    assert prefs["design_constraints"]["cost_optimization"]["value"] == "aggressive"
    assert prefs["sizing_exemptions"] == ["1000000000000000001"]
def test_estimate_emits_two_bands_rebuilt_from_like_for_like():
    text = (REFS / "phases" / "estimate" / "estimate-infra.md").read_text()
    part = text[text.index("## Part 2D") : text.index("## Part 3")]
    assert 'at least one `aws-design.json` mapping carries `sizing_provenance: "measured"`' in part
    assert "`projected_costs.sizing_bands.like_for_like_monthly`" in part and "`projected_costs.sizing_bands.right_sized_monthly`" in part
    assert "Rebuild each measured row from `sized_from.like_for_like` (**not** from `uncapped` or `capped`" in part
    assert "`sizing_basis`" in part and "`pricing_source` is unchanged" in part
    assert "not** a fourth pricing tier" in part
    schema = (REFS / "shared" / "schema-estimate-infra.md").read_text()
    assert '"sizing_bands": {' in schema and "`projected_costs.sizing_bands` (optional)" in schema
def test_report_and_guide_carry_the_sizing_basis_column():
    report = (REFS / "phases" / "generate" / "generate-artifacts-report.md").read_text()
    assert "Monthly Cost (Balanced), Sizing basis, Calculation/Notes" in report
    assert "**Sizing basis column:**" in report and "`projected_costs.sizing_bands`" in report
    guide = (REFS / "phases" / "generate" / "generate-artifacts-docs.md").read_text()
    assert "**Sizing basis subsection**" in guide and "install the Ops Agent" in guide
def test_skill_knowledge_paths_referenced_in_docs_exist():
    for rel in ("knowledge/design/instance-catalog.json", "knowledge/estimate/rightsizing-thresholds.json",
                "scripts/size-from-utilization.py", "scripts/summarize-monitoring.py"):
        assert (SKILL / rel).is_file(), rel
    docs = "".join(p.read_text() for p in (REFS / "design-refs" / "compute.md", REFS / "design-refs" / "database.md",
                                           REFS / "shared" / "graviton.md", REFS / "phases" / "estimate" / "estimate-infra.md"))
    assert "knowledge/design/instance-catalog.json" in docs and "knowledge/estimate/rightsizing-thresholds.json" in docs


# --------------------------------------------------------------------------- review round 1 (F1–F3)

def test_max_connections_uses_db_instance_class_memory_and_matches_the_aws_anchors():
    # CHAP_Limits: about 630 for MySQL on db.m7g.large (8 GiB), about 60 on db.t3.micro (1 GiB); naive total-memory maths gives 683 and 85
    assert CATALOG.max_connections("mysql", 8) == 630
    assert CATALOG.max_connections("mysql", 1) == 60
    assert CATALOG.max_connections("postgresql", 1) == 79 < 112
    assert CATALOG.max_connections("postgresql", 64) == 5000  # cap still applies
    assert CATALOG.max_connections("sqlserver", 8) is None
    doc = json.loads(CATALOG_PATH.read_text())["rds"]["max_connections"]
    assert "NOT the advertised class memory" in doc["_what_this_is"] and "memory_gib × 1073741824" not in doc["_what_this_is"]
    assert doc["reserved_memory"] == {"fixed_gib": 0.25, "fraction": 0.045, "_anchors": doc["reserved_memory"]["_anchors"]}


def _mysql_m7g_large(connections_p95: float, cpu_p95: float = 0.20) -> dict:
    # db-custom-2-8192 MySQL anchors at db.m7g.large (2 vCPU / 8 GiB), the family minimum, so the pick is always db.m7g.large
    return _synthetic_db(cpu_p95, 0.50, connections_p95, tier="db-custom-2-8192", version="MYSQL_8_0")


def test_six_hundred_fifty_connections_on_m7g_large_mysql_gets_rds_proxy_not_a_silent_pass():
    over = run(inventory=_mysql_m7g_large(650))["synthetic"]
    assert over["instance_class"] == "db.m7g.large" and over["sized_from"]["max_connections"] == 630
    assert over["rds_proxy"] is True
    assert any("exceeds db.m7g.large max_connections 630" in w for w in over["warnings"])


def test_connections_within_ten_percent_of_the_modeled_limit_warn_without_a_proxy():
    near = run(inventory=_mysql_m7g_large(600))["synthetic"]  # 600 >= 0.9 × 630 = 567, not over
    assert near["rds_proxy"] is False
    assert any("within 10% of db.m7g.large max_connections 630" in w and "SHOW GLOBAL VARIABLES" in w for w in near["warnings"])
    clear = run(inventory=_mysql_m7g_large(500))["synthetic"]
    assert clear["rds_proxy"] is False and not any("max_connections" in w for w in clear["warnings"])
    assert THRESHOLDS["rds_proxy"]["near_limit_fraction"] == 0.9


def _declared_db(config_extra: dict) -> dict:
    """An IaC-only Cloud SQL entry (no utilization) so storage falls back to the provisioned disk."""
    return {"metadata": {"project": "acme-prod"}, "resources": [{
        "address": "google_sql_database_instance.iac", "type": "google_sql_database_instance",
        "config": {"name": "iac", "database_version": "POSTGRES_15", "tier": "db-custom-2-8192", **config_extra}}]}


def test_declared_storage_reads_the_canonical_iac_disk_size_gb_key():
    canonical = run(inventory=_declared_db({"disk_size_gb": 500}))["iac"]
    assert canonical["sizing_provenance"] == "declared" and canonical["declared_reason"] == "insufficient"
    assert canonical["storage"]["allocated_gib"] == 500 and canonical["storage"]["basis"] == "declared"
    assert "500 GB" in canonical["storage"]["calculation"]
    small = run(inventory=_declared_db({"disk_size_gb": 5}))["iac"]
    assert small["storage"]["allocated_gib"] == 20  # max(N, gp3 minimum)
    live_key = run(inventory=_declared_db({"settings.dataDiskSizeGb": "120"}))["iac"]
    assert live_key["storage"]["allocated_gib"] == 120
    none = run(inventory=_declared_db({}))["iac"]
    assert none["storage"]["allocated_gib"] is None and "size storage by hand" in none["storage"]["calculation"]
    assert "upper bound" not in none["storage"]["calculation"]


def test_design_and_estimate_price_the_same_rds_storage_key():
    design_infra = (REFS / "phases" / "design" / "design-infra.md").read_text()
    estimate = (REFS / "phases" / "estimate" / "estimate-infra.md").read_text()
    database = (REFS / "design-refs" / "database.md").read_text()
    assert "`aws_config.allocated_storage`" in estimate and "allocated_gib" not in estimate
    assert "`allocated_storage`" in design_infra and "`allocated_gib`, `iops`" not in design_infra
    assert '"allocated_storage": 20' in database and '"allocated_gib": 20' not in database
    assert "`config.disk_size_gb`" in database  # the canonical IaC key the fallback reads


def _prefs(tmp_path: Path, cost: str | None, right_sizing: bool | None) -> Path:
    constraints: dict = {}
    if cost is not None:
        constraints["cost_optimization"] = {"value": cost, "chosen_by": "default", "question_id": "Q-E0"}
    if right_sizing is not None:
        constraints["right_sizing"] = {"value": right_sizing, "chosen_by": "user", "question_id": "Q-E2"}
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"design_constraints": constraints}))
    return path


def test_q_e2_no_yields_declared_decisions_for_every_resource(tmp_path):
    cost, _arch, _ex = sizer.read_preferences(_prefs(tmp_path, "balanced", False))
    assert cost == "conservative"
    decisions = run(cost)
    assert all(d["sizing_provenance"] == "declared" and d["declared_reason"] == "conservative" for d in decisions.values())
    assert sizer.read_preferences(_prefs(tmp_path, "balanced", True))[0] == "balanced"  # yes keeps the appetite
    assert sizer.read_preferences(_prefs(tmp_path, "aggressive", None))[0] == "aggressive"  # not asked: Q-E0 governs
    assert sizer.read_preferences(_prefs(tmp_path, None, None))[0] is None  # defaulted → balanced in main()


def test_q_e2_no_through_the_cli_matches_conservative(tmp_path):
    out = tmp_path / "out.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--inventory", str(INVENTORY), "--preferences",
                             str(_prefs(tmp_path, "balanced", False)), "--output", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["cost_optimization"] == "conservative" and data["measured_resources"] == 0


def test_clarify_makes_cost_optimization_the_single_authoritative_sizing_field():
    text = (REFS / "phases" / "clarify" / "clarify-assemble.md").read_text()
    q_e2 = text[text.index("### Q-E2") : text.index("## Gate 2")]
    assert "`cost_optimization` is the only field Design reads" in q_e2
    assert "`conservative`" in q_e2 and '`question_id: "Q-E2"`' in q_e2
    assert "not asked → omit `right_sizing`" in q_e2
    assert "writes `cost_optimization: conservative`" in q_e2  # the 2 (no) impact row
    category_e = text[text.index("_Default behavior when disabled:_") : text.index("### Q-E0")]
    assert "follows the Right-sizing\nappetite row (Q-E0, default `balanced`)" in category_e
    assert "no HA upgrades, no\nright-sizing" not in text
    assert "`right_sizing: false`)" not in text  # the Category E default no longer forces it
    assert "`right_sizing` omitted; `cost_optimization` (Q-E0) governs" in text
    prompt = text[text.index("Would you also like HA upgrade") : text.index("If user opts in, present Q-E1")]
    assert "match current capacity" not in prompt and "conservative defaults" not in prompt
    assert "instance sizing follows the\n> Right-sizing appetite" in prompt
    assert 'source: "user:Q-E2"' not in q_e2  # schema-preferences.md: no source on user answers


# --------------------------------------------------------------------------- self-review follow-ups

EXPECTED_WITH_PREFS = FIXTURE / "after-design" / "sizing-decisions.with-preferences.json"


def test_cli_with_the_fixture_preferences_reproduces_the_second_golden(tmp_path):
    """after-clarify/preferences.json (aggressive + web_steady exempt) -> after-design/sizing-decisions.with-preferences.json."""
    out = tmp_path / "with-prefs.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--inventory", str(INVENTORY), "--preferences", str(PREFERENCES),
                             "--output", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == EXPECTED_WITH_PREFS.read_bytes()
    data = json.loads(out.read_text())
    assert data["cost_optimization"] == "aggressive" and data["sizing_exemptions"] == ["1000000000000000001"]
    web = next(r for r in data["resources"] if r["key"] == "1000000000000000001")
    assert web["sizing_provenance"] == "declared" and web["declared_reason"] == "user_exempt"


def test_rds_proxy_is_disclosed_but_neither_priced_nor_generated():
    """Estimate, Design, the report and the guide agree: rds_proxy is a recommendation only (no rate, no aws_db_proxy)."""
    estimate = (REFS / "phases" / "estimate" / "estimate-infra.md").read_text()
    database = (REFS / "design-refs" / "database.md").read_text()
    report = (REFS / "phases" / "generate" / "generate-artifacts-report.md").read_text()
    guide = (REFS / "phases" / "generate" / "generate-artifacts-docs.md").read_text()
    generate_infra = (REFS / "phases" / "generate" / "generate-artifacts-infra.md").read_text()
    assert "`aws_config.rds_proxy: true` is not priced" in estimate
    assert "RDS Proxy where `aws_config.rds_proxy` is true" not in estimate
    assert "`rds_proxy: true` is a recommendation only in this version" in database
    assert "one line per `rds_proxy: true` database" in report and "not in the generated Terraform" in report
    assert "`rds_proxy: true` database saying the proxy is recommended but not priced or generated" in guide
    # If someone later adds an emitter or a rate, revisit this test together with the wording above.
    assert "aws_db_proxy" not in generate_infra and "rds_proxy" not in generate_infra


def test_guide_known_limitations_enumerate_the_same_reasons_as_the_report():
    guide = (REFS / "phases" / "generate" / "generate-artifacts-docs.md").read_text()
    report = (REFS / "phases" / "generate" / "generate-artifacts-report.md").read_text()
    start = report.index("- (i) at least one resource carries `utilization`")
    end = report.index("- (ii) every `utilization.coverage`")
    branch_i = report[start:end]
    for name in ("insufficient", "memory_unavailable", "burst", "idle", "skipped_group_member", "user_exempt",
                 "conservative", "memory_bound", "memory_saturated", "burstable_baseline_exceeded"):
        assert name in branch_i, name
        assert f"`{name}`" in guide, name
