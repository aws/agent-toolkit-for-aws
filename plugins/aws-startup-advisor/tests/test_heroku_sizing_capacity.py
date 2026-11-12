"""Capacity and alias guards for the heroku-to-aws sizing tables.

Review findings (leon1418, PR #608):
- Redis: a node must hold the plan's dataset AFTER ElastiCache's default 25% reserved memory.
- Aurora: a single writer/reader instance must have at least the source plan's RAM; writer
  and reader do not pool their caches.
- Every instance/node class a sizing table can emit must have a rate row in the vendored
  pricing file (the two files are a pair).
- Fast-path aliases are applied AFTER `heroku-` prefix stripping, so `heroku-connect`,
  `Heroku Connect` and `herokuconnect` must all reach the `herokuconnect` row.
- Cache <-> sizing parity: every Classic Postgres / Redis plan priced in
  `heroku-pricing-cache.md` has a sizing row whose RAM / memory_limit matches the cache, and
  every RDS / Aurora class a Postgres row emits has at least the plan's RAM (this is the check
  that would have caught a 512 GiB class on a 768 GB plan).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
K = PLUGIN_ROOT / "skills/heroku-to-aws/knowledge/design"
PRICING = PLUGIN_ROOT / "skills/heroku-to-aws/references/vendored/pricing/aws-infra-pricing.json"
CACHE = PLUGIN_ROOT / "skills/heroku-to-aws/references/shared/heroku-pricing-cache.md"

# Advertised memory per node (GiB), AWS ElastiCache supported node types page.
NODE_GIB = {
    "cache.t4g.micro": 0.5, "cache.t4g.small": 1.37, "cache.t4g.medium": 3.09,
    "cache.m6g.large": 6.38, "cache.m6g.xlarge": 12.93, "cache.m6g.2xlarge": 26.04,
    "cache.m6g.4xlarge": 52.26, "cache.m6g.8xlarge": 103.68, "cache.m6g.12xlarge": 157.12,
    "cache.m6g.16xlarge": 209.55,
}
RESERVED = 0.25  # reserved-memory-percent default

# RAM per Aurora PostgreSQL class (GiB).
AURORA_GIB = {
    "db.t4g.medium": 4, "db.t4g.large": 8, "db.r6g.large": 16, "db.r6g.xlarge": 32, "db.r6g.2xlarge": 64,
    "db.r6g.4xlarge": 128, "db.r6g.8xlarge": 256, "db.r6g.16xlarge": 512, "db.x2g.16xlarge": 1024,
}

# RAM per RDS PostgreSQL class (GiB); Aurora classes are valid on RDS too.
RDS_GIB = {
    **AURORA_GIB,
    "db.t4g.micro": 1, "db.m6g.large": 8, "db.m6g.xlarge": 16, "db.m6g.2xlarge": 32,
    "db.m6g.4xlarge": 64, "db.m6g.8xlarge": 128, "db.m6g.16xlarge": 256,
}


def _load(name: str) -> dict:
    return json.loads((K / name).read_text(encoding="utf-8"))


def _to_gib(text: str) -> float:
    m = re.match(r"([\d.]+)\s*(MB|GB|TB)", text)
    assert m, text
    n, unit = float(m.group(1)), m.group(2)
    gb = n / 1024 if unit == "MB" else n * (1024 if unit == "TB" else 1)
    return gb * (1000 ** 3) / (1024 ** 3)  # decimal GB -> GiB


# ---------------------------------------------------------------- Redis
_REDIS_ROWS = _load("redis-elasticache-sizing.json")["rows"]


@pytest.mark.parametrize("plan", list(_REDIS_ROWS))
def test_redis_node_holds_plan_after_reserved_memory(plan: str):
    # Every row, not a filtered subset: the file's _reserved_memory_note claims every row clears
    # the 25% reserve, and the legacy rows (premium-8/13, private-2/6) once did not.
    row = _REDIS_ROWS[plan]
    usable = NODE_GIB[row["node_type"]] * (1 - RESERVED)
    need = _to_gib(row["memory_limit"])
    assert usable >= need, f"{plan}: {row['node_type']} usable {usable:.2f} GiB < plan {need:.2f} GiB"


_NODE_MEMORY = _load("redis-elasticache-sizing.json")["node_memory_gib"]


def _redis_cloud_node(plan_mb: float) -> str | None:
    """design-mapping.md Step 4b: the smallest node whose usable memory covers the plan."""
    need = plan_mb * 1_000_000 / 1_073_741_824
    for node, gib in sorted(_NODE_MEMORY.items(), key=lambda kv: kv[1]):
        if gib * (1 - RESERVED) >= need:
            return node
    return None


def test_redis_cloud_node_table_matches_the_aws_node_table_and_has_rates():
    assert _NODE_MEMORY == NODE_GIB
    pricing = json.loads(PRICING.read_text(encoding="utf-8"))
    assert set(_NODE_MEMORY) <= set(pricing["elasticache"]["nodes"])


def test_redis_cloud_sizing_picks_the_smallest_sufficient_node_regardless_of_row_order():
    # The Heroku plan rows are not ordered by memory (premium-8 is 15 GB, premium-9 is 10 GB), so
    # "first row in table order" picked an undersized node for these sizes.
    assert _redis_cloud_node(12000) == "cache.m6g.2xlarge"
    assert _redis_cloud_node(2500) == "cache.m6g.large"
    assert _redis_cloud_node(500) == "cache.t4g.small"
    assert _redis_cloud_node(170_000) is None  # exceeds the largest node: Specialist Gate


@pytest.mark.parametrize("plan_mb", [30, 100, 250, 500, 1000, 2500, 5000, 7500, 10_000, 12_000, 25_000, 50_000, 75_000, 100_000, 150_000])
def test_redis_cloud_pick_covers_the_plan_and_no_smaller_node_does(plan_mb: int):
    node = _redis_cloud_node(plan_mb)
    need = plan_mb * 1_000_000 / 1_073_741_824
    assert node is not None
    assert _NODE_MEMORY[node] * (1 - RESERVED) >= need
    assert all(g * (1 - RESERVED) < need for n, g in _NODE_MEMORY.items() if g < _NODE_MEMORY[node])


def test_report_phase_names_only_files_a_phase_writes():
    # generate-report.md once read `discover-heroku.json` and `design.json`, which no phase writes,
    # so the estate-tier and follower lines silently never rendered. Discover writes
    # heroku-resource-inventory.json and Design writes aws-design.json.
    text = (PLUGIN_ROOT / "skills/heroku-to-aws/references/phases/generate/generate-report.md").read_text(encoding="utf-8")
    assert "discover-heroku.json" not in text
    assert not re.search(r"(?<![-\w/])design\.json", text)


def test_redis_large_plans_not_under_sized():
    # The nine rows the review named: 25/50/100 GB sources.
    for tier in ("premium", "private", "shield"):
        assert _REDIS_ROWS[f"{tier}-10"]["node_type"] == "cache.m6g.4xlarge"
        assert _REDIS_ROWS[f"{tier}-12"]["node_type"] == "cache.m6g.8xlarge"
        assert _REDIS_ROWS[f"{tier}-14"]["node_type"] == "cache.m6g.12xlarge"


# ---------------------------------------------------------------- Postgres / Aurora
_PG_ROWS = _load("postgres-rds-sizing.json")["rows"]


@pytest.mark.parametrize("plan", [k for k in _PG_ROWS if re.search(r"-(8|9|l-9|xl-9|10)$", k)])
def test_aurora_instance_ram_covers_source_plan(plan: str):
    row = _PG_ROWS[plan]
    need = _to_gib(row["ram"])
    have = AURORA_GIB[row["aurora_instance_class"]]
    assert have >= need * 0.95, f"{plan}: {row['aurora_instance_class']} {have} GiB < source {need:.0f} GiB"


def test_every_sizing_class_has_a_rate_row():
    pricing = json.loads(PRICING.read_text(encoding="utf-8"))
    rds = set(pricing["rds_postgresql"]["instances"])
    aurora = set(pricing["aurora_postgresql"]["instances"])
    nodes = set(pricing["elasticache"]["nodes"])
    missing = []
    for k, r in _PG_ROWS.items():
        if r["rds_instance_class"] not in rds:
            missing.append(f"rds:{k}:{r['rds_instance_class']}")
        if r["aurora_instance_class"] not in aurora:
            missing.append(f"aurora:{k}:{r['aurora_instance_class']}")
    for k, r in _REDIS_ROWS.items():
        if r["node_type"] not in nodes:
            missing.append(f"redis:{k}:{r['node_type']}")
    assert not missing, missing


# ---------------------------------------------------------------- Cache <-> sizing parity
def _cache_tables(heading: str, next_heading: str) -> dict[str, list[str]]:
    """Rows of every markdown table between two `##` headings, keyed by first cell."""
    text = CACHE.read_text(encoding="utf-8")
    section = text[text.index(heading):text.index(next_heading)]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("Plan", "Plan Level (`--level`)"):
            continue
        rows[cells[0]] = cells
    return rows


_CACHE_PG = {
    k: v for k, v in _cache_tables("## Heroku Postgres", "## Heroku Key-Value Store").items()
    if re.match(r"(standard|premium|private|shield)-", k)
}
_CACHE_REDIS = _cache_tables("## Heroku Key-Value Store", "## Apache Kafka on Heroku")


def test_cache_covers_classic_postgres_plans():
    assert len(_CACHE_PG) >= 50 and "standard-0" in _CACHE_PG and "shield-xl-9" in _CACHE_PG


@pytest.mark.parametrize("plan", sorted(_CACHE_PG))
def test_every_classic_postgres_cache_plan_has_matching_sizing_row(plan: str):
    assert plan in _PG_ROWS, f"{plan} is priced in heroku-pricing-cache.md but has no sizing row"
    cache_ram = _CACHE_PG[plan][2]
    assert _PG_ROWS[plan]["ram"] == cache_ram, f"{plan}: sizing ram {_PG_ROWS[plan]['ram']} != cache RAM {cache_ram}"


@pytest.mark.parametrize("plan", sorted(_CACHE_REDIS))
def test_every_classic_redis_cache_plan_has_matching_sizing_row(plan: str):
    assert plan in _REDIS_ROWS, f"{plan} is priced in heroku-pricing-cache.md but has no sizing row"
    cache_ram = _CACHE_REDIS[plan][2]
    assert _REDIS_ROWS[plan]["memory_limit"] == cache_ram, (
        f"{plan}: sizing memory_limit {_REDIS_ROWS[plan]['memory_limit']} != cache RAM {cache_ram}"
    )


@pytest.mark.parametrize("plan", [k for k in _PG_ROWS if not _PG_ROWS[k]["ram"].startswith("0 MB")])
def test_postgres_class_ram_covers_plan_ram(plan: str):
    # Heroku publishes decimal GB; instance classes are GiB. No slack: the class must hold
    # the whole plan RAM (db.r6g.16xlarge at 512 GiB on a 768 GB plan fails here).
    need = _to_gib(_PG_ROWS[plan]["ram"])
    for col, table in (("rds_instance_class", RDS_GIB), ("aurora_instance_class", AURORA_GIB)):
        cls = _PG_ROWS[plan][col]
        assert cls in table, f"{plan}: add {cls} to the GiB map"
        assert table[cls] >= need, f"{plan}: {col} {cls} {table[cls]} GiB < plan {need:.1f} GiB"


# ---------------------------------------------------------------- Fast-path normalization
_FP = _load("fast-path-addons.json")


def test_scheduler_row_present():
    # Heroku Scheduler's CLI slug is plain `scheduler`; the row must exist under that key.
    assert "scheduler" in _FP["rows"]
    assert _FP["_prefix_aliases"]["heroku scheduler"] == "scheduler"


def _normalize(addon_service: str) -> str:
    """The documented rule: strip leading `heroku-`, hyphens -> spaces, lowercase, THEN aliases."""
    s = addon_service.lower()
    if s.startswith("heroku-"):
        s = s[len("heroku-"):]
    s = s.replace("-", " ")
    return _FP["_prefix_aliases"].get(s, s)


@pytest.mark.parametrize("spelling", ["herokuconnect", "heroku-connect", "Heroku Connect"])
def test_connect_spellings_reach_one_row(spelling: str):
    key = _normalize(spelling)
    assert key == "herokuconnect" and key in _FP["rows"]


@pytest.mark.parametrize("spelling,expected", [
    ("scheduler", "scheduler"), ("heroku-scheduler", "scheduler"), ("Heroku Scheduler", "scheduler"),
    ("advanced-scheduler", "advanced scheduler"), ("heroku-inference", "inference"),
    ("jawsdb-maria", "jawsdb maria"), ("bonsai", "bonsai elasticsearch"), ("newrelic", "new relic"),
])
def test_other_aliases_still_resolve(spelling: str, expected: str):
    key = _normalize(spelling)
    assert key == expected and key in _FP["rows"]


def test_exact_match_only_no_prefix_leak():
    assert _normalize("paper") not in _FP["rows"]
    assert _normalize("Papertrail Pro") not in _FP["rows"]
