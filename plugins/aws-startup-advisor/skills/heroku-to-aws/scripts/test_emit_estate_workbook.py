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
        {"resource_id": "addon:shop-prod-api:heroku-postgresql:standard-2", "resource_type": "addon",
         "heroku_app": "shop-prod-api",
         "config": {"addon_service": "heroku-postgresql", "plan": "standard-2", "provider": "heroku",
                    "connection_pooling": True, "data_size_gb": 40.5, "pg_role": "leader", "pg_leader": None,
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
    "cost_comparison": {"heroku_monthly_baseline": 700, "baseline_source": "live_prices_plus_cache"},
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
        assert out.startswith("ESTATE_OK | path=") and "apps=3" in out and "resources=6" in out
        wb = sheets(tmp / "heroku-estate.xlsx")
        assert list(wb) == ["Read Me", "Summary", "Apps", "Formations", "Postgres", "Redis", "Kafka",
                            "Other add-ons", "Shared data stores", "Cost estimate"]
        assert "db.m6g.large Multi-AZ" in wb["Postgres"]
        assert "Deferred - Not found in Fast_Path_Table" in wb["Other add-ons"]
        assert "t3.small 1-2 instances" in wb["Formations"]
        assert "C1" in wb["Shared data stores"] and "shop-prod-worker" in wb["Shared data stores"]
        # follower is listed with its role but excluded from the leaders-only data total (40.5, not 81)
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


def test_out_override():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        (tmp / "heroku-resource-inventory.json").write_text(json.dumps(INVENTORY))
        code, out = run(tmp, "--out", str(tmp / "custom.xlsx"))
        assert code == 0 and "path=" + str(tmp / "custom.xlsx") in out
        assert (tmp / "custom.xlsx").exists()
