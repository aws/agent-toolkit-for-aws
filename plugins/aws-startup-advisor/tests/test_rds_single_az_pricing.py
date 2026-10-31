"""Guard: single-AZ RDS PostgreSQL designs are priced from published single-AZ rates, not Multi-AZ ones."""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
PRICING = json.loads((SKILLS / "shared" / "pricing" / "aws-infra-pricing.json").read_text(encoding="utf-8"))
RDS = PRICING["rds_postgresql"]
GCP_CACHE = (SKILLS / "gcp-to-aws" / "references" / "shared" / "pricing-cache.md").read_text(encoding="utf-8")


def _md_rate_table(text: str, heading: str) -> dict[str, float]:
    section = text.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]
    return {m[0]: float(m[1]) for m in re.findall(r"^\|\s*(db\.[a-z0-9.]+)\s*\|\s*([0-9.]+)\s*\|", section, re.M)}


def _md_storage_rate(text: str, heading: str) -> float:
    section = text.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]
    return float(re.search(r"^\|\s*Per GB-month\s*\|\s*\$([0-9.]+)\s*\|", section, re.M)[1])


def test_every_multi_az_class_has_a_single_az_rate() -> None:
    assert set(RDS["instances_single_az"]) == set(RDS["instances"])


def test_single_az_rates_are_about_half_of_multi_az() -> None:
    for cls, multi in RDS["instances"].items():
        ratio = RDS["instances_single_az"][cls] / multi
        assert 0.45 <= ratio <= 0.55, f"{cls}: single-AZ/multi-AZ ratio {ratio:.3f} is outside the published ~0.5"
    assert RDS["storage_per_gb_month_single_az"] < RDS["storage_per_gb_month"]


def test_gcp_cache_tables_match_the_shared_rates() -> None:
    multi = _md_rate_table(GCP_CACHE, "RDS PostgreSQL (On-Demand, Multi-AZ)")
    single = _md_rate_table(GCP_CACHE, "RDS PostgreSQL (On-Demand, Single-AZ)")
    assert multi and set(single) == set(multi)
    for cls in multi:
        assert multi[cls] == RDS["instances"][cls], f"gcp Multi-AZ {cls} drifted from aws-infra-pricing.json"
        assert single[cls] == RDS["instances_single_az"][cls], f"gcp Single-AZ {cls} drifted from aws-infra-pricing.json"
    assert _md_storage_rate(GCP_CACHE, "RDS PostgreSQL (On-Demand, Multi-AZ)") == RDS["storage_per_gb_month"]
    assert _md_storage_rate(GCP_CACHE, "RDS PostgreSQL (On-Demand, Single-AZ)") == RDS["storage_per_gb_month_single_az"]


def test_heroku_formula_selects_the_table_by_multi_az() -> None:
    engine = (SKILLS / "heroku-to-aws" / "references" / "phases" / "estimate" / "estimate-cost-engine.md").read_text(encoding="utf-8")
    row = next(line for line in engine.splitlines() if line.startswith("| **RDS PostgreSQL**"))
    for token in ("instances_single_az", "storage_per_gb_month_single_az", "`multi_az` false", "`multi_az` true"):
        assert token in row, f"heroku RDS formula row is missing {token!r}: {row}"


def test_gcp_formula_selects_the_table_by_multi_az() -> None:
    infra = (SKILLS / "gcp-to-aws" / "references" / "phases" / "estimate" / "estimate-infra.md").read_text(encoding="utf-8")
    row = next(line for line in infra.splitlines() if line.startswith("| Database (RDS)"))
    assert "Single-AZ" in row and "Multi-AZ" in row and "`multi_az`" in row, row
