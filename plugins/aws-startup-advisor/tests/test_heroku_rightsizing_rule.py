"""Guards for the Q6d right-sizing rule's units and tie-break (PR #611 review).

The rule reads the Storage column of the Heroku pricing cache, which mixes GB and TB
cells. It must say how a TB cell converts, and how two plans with the same Storage are
ordered, so two agents compute the same `utilization_pct` and `fitting_plan`.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "heroku-to-aws"
INTERVIEW = (SKILL / "references" / "phases" / "clarify" / "clarify-interview.md").read_text()
CACHE = (SKILL / "references" / "shared" / "heroku-pricing-cache.md").read_text()

ROW = re.compile(
    r"^\|\s*((?:essential|standard|premium|private|shield|hobby)-[\w-]+)\s*\|\s*([\d,.]+)\s*\|"
    r"(?:[^|]*\|)?\s*([\d.]+)\s*(GB|TB)\s*\|"
)


def _postgres_classic_section() -> str:
    start = CACHE.index("## Heroku Postgres")
    end = CACHE.index("### Advanced Tier", start)  # Advanced is usage-billed, not assessed
    return CACHE[start:end]


def _plan_rows():
    for line in _postgres_classic_section().splitlines():
        m = ROW.match(line)
        if m:
            name, price, size, unit = m.groups()
            gb = float(size) * (1024 if unit == "TB" else 1)
            yield name, float(price.replace(",", "")), gb


def test_rule_states_the_tb_conversion() -> None:
    assert "1 TB = 1024 GB" in INTERVIEW
    for example in ("`1 TB` = 1024", "`1.5 TB` = 1536", "`2 TB` = 2048"):
        assert example in INTERVIEW


def test_rule_states_the_tie_break() -> None:
    assert "same Storage" in INTERVIEW
    assert "lower `$/month`" in INTERVIEW


def test_tb_cells_convert_to_whole_gb() -> None:
    rows = list(_plan_rows())
    assert rows, "no plan rows parsed from the pricing cache"
    for name, _price, gb in rows:
        assert gb == int(gb), f"{name} converts to a fractional GB value"
def test_equal_storage_plans_have_distinct_prices_so_the_tie_break_decides() -> None:
    # The cache lists plans out of Storage order and has equal-Storage plans in the same
    # family (for example premium-l-6 and premium-7, both 2 TB). The rule picks the smallest
    # Storage that fits, then the lower $/month, so every tie must be separable by price.
    seen = defaultdict(list)
    for name, price, gb in _plan_rows():
        seen[(name.split("-")[0], gb)].append((name, price))
    ties = {key: plans for key, plans in seen.items() if len(plans) > 1}
    assert ties, "expected equal-Storage plans in the cache; update the rule text if they are gone"
    for key, plans in ties.items():
        prices = [price for _name, price in plans]
        assert len(set(prices)) == len(prices), f"equal-Storage plans {key} also tie on price: {plans}"
