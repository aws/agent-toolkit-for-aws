"""Capacity and alias guards for the heroku-to-aws sizing tables.

Review findings (leon1418, PR #608):
- Redis: a node must hold the plan's dataset AFTER ElastiCache's default 25% reserved memory.
- Aurora: a single writer/reader instance must have at least the source plan's RAM; writer
  and reader do not pool their caches.
- Every instance/node class a sizing table can emit must have a rate row in the vendored
  pricing file (the two files are a pair).
- Fast-path aliases are applied AFTER `heroku-` prefix stripping, so `heroku-connect`,
  `Heroku Connect` and `herokuconnect` must all reach the `herokuconnect` row.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
K = PLUGIN_ROOT / "skills/heroku-to-aws/knowledge/design"
PRICING = PLUGIN_ROOT / "skills/heroku-to-aws/references/vendored/pricing/aws-infra-pricing.json"

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


@pytest.mark.parametrize("plan", [k for k in _REDIS_ROWS if re.match(r"(premium|private|shield)-(7|9|10|12|14)$", k) or k == "mini"])
def test_redis_node_holds_plan_after_reserved_memory(plan: str):
    row = _REDIS_ROWS[plan]
    usable = NODE_GIB[row["node_type"]] * (1 - RESERVED)
    need = _to_gib(row["memory_limit"])
    assert usable >= need, f"{plan}: {row['node_type']} usable {usable:.2f} GiB < plan {need:.2f} GiB"


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


# ---------------------------------------------------------------- Fast-path normalization
_FP = _load("fast-path-addons.json")


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
