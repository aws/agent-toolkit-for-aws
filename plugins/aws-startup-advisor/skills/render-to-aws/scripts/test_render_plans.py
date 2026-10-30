"""Tests for the shared Render plan alias resolution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from render_common.plans import ALIAS_TABLE, normalize_plan, plan_surface  # noqa: E402


@pytest.mark.parametrize(
    ("surface", "raw", "expected"),
    [
        ("service_compute", "1c-2g", "1c-2gb"),
        ("service_compute", "1c-2gb", "1c-2gb"),
        ("service_compute", "pro plus", "4c-8gb"),
        ("service_compute", "Pro Plus", "4c-8gb"),
        ("service_compute", "pro_plus", "4c-8gb"),
        ("service_compute", "pro-plus", "4c-8gb"),
        ("service_compute", "  pro   ultra ", "8c-32gb"),
        ("service_compute", "starter", "0.5c-512mb"),
        ("service_compute", "4c-32g", "4c-32gb"),
        ("key_value", "pro ultra", "40g"),
        ("key_value", "free", "free"),
        ("key_value", "256mb", "256mb"),
        ("workflow", "pro", "2c-4g"),
        ("workflow", "standard", "flex"),
    ],
)
def test_published_spellings_resolve_to_canonical_ids(surface: str, raw: str, expected: str) -> None:
    assert normalize_plan(surface, raw) == expected


@pytest.mark.parametrize(
    ("surface", "raw"),
    [
        ("service_compute", "2c-16g"),
        ("service_compute", "8c-64g"),
        ("service_compute", "free"),
        ("service_compute", "9c-99g"),
        ("service_compute", ""),
        ("service_compute", None),
        ("service_compute", 4),
        ("key_value", "pro maxx"),
        ("key_value", "2c-4g"),
        ("workflow", "1c-2gb"),
    ],
)
def test_unpriced_and_unknown_plans_stay_none(surface: str, raw: object) -> None:
    assert normalize_plan(surface, raw) is None


def test_unknown_surface_raises() -> None:
    with pytest.raises(ValueError, match="plan_surface_unknown"):
        normalize_plan("postgres", "pro")


def test_plan_surface_maps_kinds() -> None:
    assert plan_surface("render.key_value") == "key_value"
    assert plan_surface("render.workflow") == "workflow"
    assert plan_surface("render.web_service") == "service_compute"
    assert plan_surface("render.cron_job") == "service_compute"


def test_alias_table_is_internally_consistent() -> None:
    table = json.loads(ALIAS_TABLE.read_text(encoding="utf-8"))
    assert table["schema_version"] == "1.0"
    assert set(table["surfaces"]) == {"service_compute", "key_value", "workflow"}
    for surface, entry in table["surfaces"].items():
        canonical = set(entry["canonical"])
        assert len(canonical) == len(entry["canonical"])
        assert set(entry["aliases"].values()) <= canonical
        assert not (set(entry["unpriced"]) & canonical)
        for alias in entry["aliases"]:
            assert normalize_plan(surface, alias) == entry["aliases"][alias]
        for plan in entry["canonical"]:
            assert normalize_plan(surface, plan) == plan
        for plan in entry["unpriced"]:
            assert normalize_plan(surface, plan) is None
