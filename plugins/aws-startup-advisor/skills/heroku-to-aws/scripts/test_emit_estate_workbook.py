"""Tests for scripts/emit-estate-workbook.py (the estate spreadsheet writer).

Same convention as the sibling validator tests: invoke the committed script as a
subprocess against a temporary $MIGRATION_DIR, assert the machine status line and
the written file. The writer copies values only and fails open (exit 0, no file)
on any missing or unusable input. The .xlsx is inspected with zipfile + the XML
it contains, so the tests need no spreadsheet library either.
"""
from __future__ import annotations

import json
import re
# Tests invoke only the committed script using list arguments without a shell.
import subprocess  # nosec B404
import sys
import tempfile
import xml.etree.ElementTree as ET  # nosec B405 — parses only XML this test suite just wrote
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "emit-estate-workbook.py"

INVENTORY = {
    "metadata": {"discovery_timestamp": "2026-01-01T00:00:00Z", "discovery_sources": ["live"], "confidence": "full"},
    "apps": [
        {"app_name": "shop-prod-api", "app_id": "11111111-1111-4111-8111-111111111111", "heroku_generation": "cedar",
         "space": None, "environment_tier": "prod", "environment_tier_source": "name-heuristic"},
        {"app_name": "shop-prod-worker", "app_id": "22222222-2222-4222-8222-222222222222", "heroku_generation": "cedar",
         "space": None, "environment_tier": "prod", "environment_tier_source": "name-heuristic"},
        {"app_name": "shop-dev-api", "app_id": "33333333-3333-4333-8333-333333333333", "heroku_generation": "cedar",
         "space": None, "environment_tier": "dev", "environment_tier_source": "pipeline"},
    ],
    "resources": [
        {"resource_id": "formation:shop-prod-api:web", "resource_type": "formation", "heroku_app": "shop-prod-api",
         "config": {"process_type": "web", "dyno_type": "standard-2x", "quantity": 2}},
        {"resource_id": "formation:shop-prod-worker:worker", "resource_type": "formation", "heroku_app": "shop-prod-worker",
         "config": {"process_type": "worker", "dyno_type": "standard-1x", "quantity": 3}},
        {"resource_id": "formation:shop-dev-api:web", "resource_type": "formation", "heroku_app": "shop-dev-api",
         "config": {"process_type": "web", "dyno_type": "standard-1x", "quantity": 1}},
        {"resource_id": "addon:shop-prod-api:heroku-postgresql:standard-2", "resource_type": "addon",
         "heroku_app": "shop-prod-api",
         "config": {"addon_service": "heroku-postgresql", "plan": "standard-2", "provider": "heroku",
                    "connection_pooling": True, "data_size_gb": 40.5, "pg_role": "leader", "pg_leader": None,
                    "pg_attachment_names": ["HEROKU_POSTGRESQL_TEAL", "DATABASE"],
                    "attached_apps": ["shop-prod-worker"], "monthly_price_usd": 200}},
        {"resource_id": "addon:shop-prod-api:heroku-postgresql:standard-2:follower", "resource_type": "addon",
         "heroku_app": "shop-prod-api",
         "config": {"addon_service": "heroku-postgresql", "plan": "standard-2", "provider": "heroku",
                    "connection_pooling": False, "data_size_gb": 40.5, "pg_role": "follower",
                    "pg_leader": "HEROKU_POSTGRESQL_TEAL", "attached_apps": [], "monthly_price_usd": 200}},
        {"resource_id": "addon:shop-dev-api:scheduler:standard", "resource_type": "addon", "heroku_app": "shop-dev-api",
         "config": {"addon_service": "scheduler", "plan": "standard", "provider": "scheduler"}},
        {"resource_id": "config:shop-prod-api", "resource_type": "config", "heroku_app": "shop-prod-api",
         "config": {"config_var_keys": ["DATABASE_URL", "SECRET_KEY_BASE", "STRIPE_KEY"]}},
        {"resource_id": "domain:shop-prod-api:www.example-shop.test", "resource_type": "domain",
         "heroku_app": "shop-prod-api", "config": {"hostname": "www.example-shop.test", "sni_endpoint": None}},
    ],
    "shared_data_stores": {
        "cohorts": [{"cohort_id": "C1", "apps": ["shop-prod-api", "shop-prod-worker"],
                     "shared_stores": ["addon:shop-prod-api:heroku-postgresql:standard-2"]}],
        "apps_in_cohorts": 2,
    },
}

DESIGN = {
    "services": [
        {"service_id": "fargate:shop-prod-worker:worker", "source_resource_id": "formation:shop-prod-worker:worker",
         "heroku_app": "shop-prod-worker", "aws_service": "Fargate",
         "aws_config": {"task_cpu": 1024, "task_memory": 2048, "desired_count": 3, "load_balancer": False}},
        {"service_id": "fargate:shop-dev-api:web", "source_resource_id": "formation:shop-dev-api:web",
         "heroku_app": "shop-dev-api", "aws_service": "Fargate",
         "aws_config": {"task_cpu": 512, "task_memory": 1024, "desired_count": 1, "load_balancer": True}},
        {"service_id": "alb:shop-dev-api:web", "source_resource_id": "formation:shop-dev-api:web",
         "heroku_app": "shop-dev-api", "aws_service": "ALB", "aws_config": {"load_balancer": True}},
        {"service_id": "rds:shop-prod-api:postgres", "source_resource_id": "addon:shop-prod-api:heroku-postgresql:standard-2",
         "heroku_app": "shop-prod-api", "aws_service": "RDS PostgreSQL",
         "aws_config": {"instance_class": "db.m6g.large", "multi_az": True}},
        {"service_id": "eb:shop-prod-api:web", "source_resource_id": "formation:shop-prod-api:web",
         "heroku_app": "shop-prod-api", "aws_service": "Elastic Beanstalk",
         "aws_config": {"instance_type": "t3.small", "min_instances": 1, "max_instances": 2}},
    ],
    "deferred": [{"addon_name": "scheduler", "addon_plan": "standard", "provider": "scheduler",
                  "reason": "Not found in Fast_Path_Table", "recommendation": "Engage AWS account team"}],
}

ESTIMATE = {
    "current_costs": {"source": "live_prices_plus_cache", "baseline_note": "Derived, not an invoice.",
                      "contract": {"term_start": "2026-01-01", "term_end": "2027-12-31", "monthly_run_rate": 1000,
                                   "discovered_monthly": 700, "gap_monthly": 300,
                                   "gap_explanation": "Support and credits are not visible to discovery.",
                                   "lines": [{"category": "support", "monthly_usd": 100, "note": "24-month line"}]}},
    "projected_costs": {"aws_monthly_premium": 500, "aws_monthly_balanced": 400, "aws_monthly_optimized": 300},
    "cost_comparison": {"heroku_monthly_baseline": 700, "baseline_source": "live_prices_plus_cache",
                        "heroku_monthly_like_for_like": 140,
                        "like_for_like_comparison": {"aws_monthly_balanced": 400, "heroku_monthly_like_for_like": 140,
                                                     "monthly_difference": 260, "difference_pct": 1.857,
                                                     "deferred_contribution_monthly": 560,
                                                     "unattributed_deferred_services": [],
                                                     "attribution": "complete",
                                                     "note": "Scope-matched."}},
}


def run(tmp: Path, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), "--migration-dir", str(tmp), *extra],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stdout.strip()


def sheets(path: Path) -> dict[str, str]:
    """sheet name -> raw worksheet XML (inline strings are readable as text)."""
    with zipfile.ZipFile(path) as z:
        names = re.findall(r'<sheet name="([^"]+)" sheetId="(\d+)"', z.read("xl/workbook.xml").decode())
        return {n: z.read(f"xl/worksheets/sheet{i}.xml").decode() for n, i in names}


def test_writes_workbook_with_all_tabs_and_mapping_status():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        (tmp / "aws-design.json").write_text(json.dumps(DESIGN))
        (tmp / "estimation-infra.json").write_text(json.dumps(ESTIMATE))
        code, out = run(tmp)
        assert code == 0
        assert out.startswith("ESTATE_OK | path=") and "apps=3" in out and "resources=8" in out
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert list(wb) == ["Read Me", "Summary", "Apps", "Formations", "Postgres", "Redis", "Kafka",
                            "Other add-ons", "Shared data stores", "Cost estimate"]
        assert "db.m6g.large Multi-AZ" in wb["Postgres"]
        assert "Deferred - Not found in Fast_Path_Table" in wb["Other add-ons"]
        assert "t3.small 1-2 instances" in wb["Formations"]
        # one source -> many services: the compute entry stays the target, the ALB is listed as associated
        assert "512 CPU / 1024 MiB x1" in wb["Formations"] and "ALB" in wb["Formations"]
        assert "1024 CPU / 2048 MiB x3" in wb["Formations"]
        # scope-matched comparison rows are copied through
        assert "Scope-matched comparison" in wb["Cost estimate"] and "<v>140</v>" in wb["Cost estimate"]
        assert "<v>260</v>" in wb["Cost estimate"]
        assert "C1" in wb["Shared data stores"] and "shop-prod-worker" in wb["Shared data stores"]
        # follower whose leader resolves is a proven copy: listed with its role, excluded from the total (40.5, not 81)
        assert "follower" in wb["Postgres"] and "HEROKU_POSTGRESQL_TEAL" in wb["Postgres"]
        assert "<v>40.5</v>" in wb["Summary"] and "<v>81" not in wb["Summary"]
        # contract reconciliation block present
        assert "Contract reconciliation" in wb["Cost estimate"] and "<v>300</v>" in wb["Cost estimate"]


def test_never_leaks_excluded_data():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        run(tmp)
        blob = "\n".join(sheets(tmp / "heroku-estate.xlsx").values())
        for secret in ("SECRET_KEY_BASE", "STRIPE_KEY", "DATABASE_URL", "www.example-shop.test",
                       "11111111-1111-4111-8111-111111111111"):
            assert secret not in blob, secret
        # ...but the counts are there
        assert "Config vars (count only)" in blob and "Custom domains (count)" in blob


def test_design_and_estimate_are_optional():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert "Cost estimate" not in wb
        assert "Design not run" in wb["Formations"]


def _write_estimate_with_lfl(tmp: Path, lfl: dict) -> None:
    est = json.loads(json.dumps(ESTIMATE))
    est["cost_comparison"]["like_for_like_comparison"] = lfl
    est["cost_comparison"]["heroku_monthly_like_for_like"] = lfl["heroku_monthly_like_for_like"]
    (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
    (tmp / "estimation-infra.json").write_text(json.dumps(est))


def test_complete_attribution_is_labelled_decision_grade():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        (tmp / "estimation-infra.json").write_text(json.dumps(ESTIMATE))
        assert run(tmp)[0] == 0
        sheet = sheets(tmp / "heroku-estate.xlsx")["Cost estimate"]
        assert "Scope-matched comparison (decision-grade)" in sheet
        assert "provisional" not in sheet
        assert "185.7%" in sheet


def test_incomplete_attribution_is_labelled_provisional_not_decision_grade():
    # $150 invoice baseline, $100 AWS, nothing attributable to remove, one deferred database the
    # invoice could not itemize: the $50 "saving" still has that database on the Heroku side only.
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _write_estimate_with_lfl(tmp, {
            "aws_monthly_balanced": 100, "heroku_monthly_like_for_like": 150, "monthly_difference": -50,
            "difference_pct": -0.333, "deferred_contribution_monthly": 0,
            "unattributed_deferred_services": ["heroku-postgresql:premium-0"], "attribution": "incomplete",
            "note": "Scope-matched (provisional)."})
        assert run(tmp)[0] == 0
        sheet = sheets(tmp / "heroku-estate.xlsx")["Cost estimate"]
        assert "Scope-matched comparison (provisional" in sheet
        assert "1 deferred add-on(s) could not be attributed and remain in the Heroku figure: heroku-postgresql:premium-0" in sheet
        assert "decision-grade" not in sheet
        assert "Both sides exclude" not in sheet
        assert "<v>150</v>" in sheet and "<v>-50</v>" in sheet


def test_zero_matched_baseline_renders_pct_note_and_keeps_dollar_difference():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _write_estimate_with_lfl(tmp, {
            "aws_monthly_balanced": 40, "heroku_monthly_like_for_like": 0, "monthly_difference": 40,
            "difference_pct": None, "pct_note": "percentage not applicable: matched Heroku baseline is $0",
            "deferred_contribution_monthly": 600, "unattributed_deferred_services": [],
            "attribution": "complete", "note": "Scope-matched."})
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        _parse_every_worksheet(tmp / "heroku-estate.xlsx")
        sheet = sheets(tmp / "heroku-estate.xlsx")["Cost estimate"]
        assert "percentage not applicable: matched Heroku baseline is $0" in sheet
        assert "<v>40</v>" in sheet and "<v>0</v>" in sheet
        assert "%" not in sheet


def test_fail_open_on_missing_or_broken_inventory():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        code, out = run(tmp)
        assert code == 0 and out == "ESTATE_SKIP | reason=heroku-resource-inventory.json missing"
        assert not (tmp / "heroku-estate.xlsx").exists()
        (tmp / "heroku-resource-inventory.json").write_text("{not json")
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_SKIP | reason=inventory unreadable")
        assert not (tmp / "heroku-estate.xlsx").exists()
    code, out = run(Path("/definitely/not/here"))
    assert code == 0 and out.startswith("ESTATE_SKIP | reason=migration dir not found")


def test_stale_downstream_artifacts_excluded_after_rediscovery():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        (tmp / "aws-design.json").write_text(json.dumps(DESIGN))
        (tmp / "estimation-infra.json").write_text(json.dumps(ESTIMATE))
        # Discover re-entry: downstream phases reset to pending, their files retained
        (tmp / ".phase-status.json").write_text(json.dumps(
            {"phases": {"discover": "completed", "clarify": "pending", "design": "pending", "estimate": "pending"}}))
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert "Cost estimate" not in wb and "Right-sizing" not in wb
        assert "Design not run" in wb["Formations"] and "Mapped" not in wb["Formations"]
        # ...and with the phases completed the same files are used
        (tmp / ".phase-status.json").write_text(json.dumps(
            {"phases": {"discover": "completed", "design": "completed", "estimate": "completed"}}))
        run(tmp)
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert "Cost estimate" in wb and "Mapped" in wb["Formations"]


def test_fail_open_on_undecodable_inputs():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_bytes(b"\xff\xfe not utf-8 {")
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_SKIP | reason=inventory unreadable")
        assert not (tmp / "heroku-estate.xlsx").exists()
        # an undecodable OPTIONAL design must not block a usable inventory
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        (tmp / "aws-design.json").write_bytes(b"\xff\xfe")
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        assert "Design not run" in sheets(tmp / "heroku-estate.xlsx")["Formations"]


def _parse_every_worksheet(path: Path) -> None:
    """Every worksheet part must be well-formed XML, or spreadsheet readers reject the file."""
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert parts
        for n in parts:
            ET.fromstring(z.read(n))


def test_xml_illegal_characters_are_stripped_and_every_sheet_parses():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        inv = json.loads(json.dumps(INVENTORY))
        inv["metadata"]["confidence_note"] = "bad\x01char\x0bhere"
        inv["apps"][0]["app_name"] = "shop-prod-api\ud800"  # lone surrogate: json.load accepts the \ud800 escape
        inv["resources"][6]["config"]["plan"] = "standard\x1f"
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(inv))
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        _parse_every_worksheet(tmp / "heroku-estate.xlsx")
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert "badcharhere" in wb["Summary"]
        assert "shop-prod-api" in wb["Apps"] and "\ud800" not in wb["Apps"]
        assert "standard" in wb["Other add-ons"] and "\x1f" not in wb["Other add-ons"]
        assert not (tmp / "heroku-estate.xlsx.tmp").exists()


def test_non_finite_numbers_become_empty_cells():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        inv = json.loads(json.dumps(INVENTORY))
        inv["resources"][3]["config"]["monthly_price_usd"] = float("nan")
        inv["resources"][4]["config"]["data_size_gb"] = float("inf")
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(inv))  # json emits NaN / Infinity tokens
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK")
        _parse_every_worksheet(tmp / "heroku-estate.xlsx")
        blob = "\n".join(sheets(tmp / "heroku-estate.xlsx").values())
        assert "<v>nan</v>" not in blob and "<v>inf</v>" not in blob
        # the leaders-only total still sums the finite leader value
        assert "<v>40.5</v>" in sheets(tmp / "heroku-estate.xlsx")["Summary"]


def test_tmp_file_removed_when_write_fails():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        # the zip is written to <out>.tmp, then renamed over <out>; a non-empty directory at
        # <out> makes that rename raise after the .tmp exists
        blocker = tmp / "blocked.xlsx"
        blocker.mkdir()
        (blocker / "keep").write_text("x")
        code, out = run(tmp, "--out", str(blocker))
        assert code == 0 and out.startswith("ESTATE_SKIP | reason=")
        assert not (tmp / "blocked.xlsx.tmp").exists()
        assert blocker.is_dir()


def test_out_override():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        code, out = run(tmp, "--out", str(tmp / "custom.xlsx"))
        assert code == 0 and "path=" + str(tmp / "custom.xlsx") in out
        assert (tmp / "custom.xlsx").exists()


def _pg(rid: str, app: str, **cfg) -> dict:
    base = {"addon_service": "heroku-postgresql", "plan": "standard-0", "provider": "heroku"}
    return {"resource_id": rid, "resource_type": "addon", "heroku_app": app, "config": {**base, **cfg}}


def _inventory_with(resources: list) -> dict:
    inv = json.loads(json.dumps(INVENTORY))
    inv["resources"] = resources
    inv["apps"] = [{"app_name": a, "heroku_generation": "cedar", "space": None}
                   for a in sorted({r["heroku_app"] for r in resources})]
    return inv


def _build(inv: dict, design: dict | None = None) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(inv))
        if design is not None:
            (tmp / "aws-design.json").write_text(json.dumps(design))
        code, out = run(tmp)
        assert code == 0 and out.startswith("ESTATE_OK"), out
        return sheets(tmp / "heroku-estate.xlsx")


def test_deferral_is_matched_by_resource_not_by_service_and_plan():
    # App a's follower is deferred; app b's same-plan follower was collapsed by Design onto its
    # leader, so it is in neither services[] nor deferred[]. It must not borrow a's reason.
    a = _pg("addon:a:heroku-postgresql:standard-0", "a", pg_role="follower", pg_leader="X", data_size_gb=5)
    b = _pg("addon:b:heroku-postgresql:standard-0", "b", pg_role="follower", pg_leader="HEROKU_POSTGRESQL_B", data_size_gb=5)
    b_leader = _pg("addon:b:heroku-postgresql:standard-2", "b", pg_role="leader", plan="standard-2",
                   pg_attachment_names=["HEROKU_POSTGRESQL_B"], data_size_gb=5)
    design = {"services": [{"service_id": "rds:b", "source_resource_id": b_leader["resource_id"], "heroku_app": "b",
                            "aws_service": "RDS PostgreSQL", "aws_config": {"instance_class": "db.m6g.large"}}],
              "deferred": [{"addon_name": "heroku-postgresql", "addon_plan": "standard-0", "provider": "heroku",
                            "resource_id": a["resource_id"], "reason": "Follower of unresolved leader X"}],
              "metadata": {"postgres_followers_collapsed": [{"resource_id": b["resource_id"]}]}}
    wb = _build(_inventory_with([a, b, b_leader]), design)
    assert wb["Postgres"].count("Follower of unresolved leader X") == 1
    # one deferred add-on, not two
    assert re.search(r"add-ons deferred.*?<v>1</v>", wb["Summary"], re.S)


def test_deferral_without_resource_id_falls_back_to_service_and_plan():
    a = _pg("addon:a:heroku-postgresql:standard-0", "a", data_size_gb=5)
    design = {"services": [{"service_id": "x", "source_resource_id": "other", "aws_service": "ALB"}],
              "deferred": [{"addon_name": "heroku-postgresql", "addon_plan": "standard-0",
                            "reason": "Legacy entry without a resource id"}]}
    assert "Legacy entry without a resource id" in _build(_inventory_with([a]), design)["Postgres"]


def test_unresolved_follower_keeps_its_size_in_the_total():
    leader = _pg("addon:a:heroku-postgresql:standard-2", "a", plan="standard-2", pg_role="leader", data_size_gb=40.5,
                 pg_attachment_names=["DATABASE"])
    # points at an attachment name no add-on on the app has: unresolved, not a proven copy
    follower = _pg("addon:a:heroku-postgresql:standard-2:f", "a", plan="standard-2", pg_role="follower",
                   pg_leader="HEROKU_POSTGRESQL_GONE", data_size_gb=10.25)
    summary = _build(_inventory_with([leader, follower]))["Summary"]
    assert "<v>50.75</v>" in summary and "<v>40.5</v>" not in summary


def test_design_collapsed_list_is_authoritative_for_the_total():
    # the inventory alone cannot resolve this follower (no pg_attachment_names), so only
    # Design's list decides whether its bytes count
    leader = _pg("addon:a:heroku-postgresql:standard-2", "a", plan="standard-2", pg_role="leader", data_size_gb=40.5)
    follower = _pg("addon:a:heroku-postgresql:standard-2:f", "a", plan="standard-2", pg_role="follower",
                   pg_leader="DATABASE", data_size_gb=10.25)
    inv = _inventory_with([leader, follower])
    collapsed = {"services": [], "deferred": [], "metadata": {"postgres_followers_collapsed": [
        {"resource_id": follower["resource_id"], "leader_resource_id": leader["resource_id"]}]}}
    not_collapsed = {"services": [], "deferred": [], "metadata": {"postgres_followers_collapsed": []}}
    assert "<v>40.5</v>" in _build(inv, collapsed)["Summary"]
    assert "<v>50.75</v>" in _build(inv, not_collapsed)["Summary"]


def test_unmeasured_database_is_counted_not_summed_as_zero():
    measured = _pg("addon:a:heroku-postgresql:standard-2", "a", plan="standard-2", pg_role="leader", data_size_gb=12.5)
    unmeasured = _pg("addon:b:heroku-postgresql:standard-0", "b", pg_role="leader")  # no data_size_gb
    summary = _build(_inventory_with([measured, unmeasured]))["Summary"]
    assert "databases without a measured size" in summary
    assert re.search(r"databases without a measured size.*?<v>1</v>", summary, re.S)
    assert "<v>12.5</v>" in summary
