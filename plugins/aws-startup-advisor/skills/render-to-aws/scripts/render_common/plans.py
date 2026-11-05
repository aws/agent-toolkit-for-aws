"""Resolve published Render plan spellings to the canonical ids used by the knowledge tables."""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

ALIAS_TABLE = Path(__file__).resolve().parents[2] / "references/shared/render-plan-aliases.json"
SURFACES = ("service_compute", "key_value", "workflow")
_SEPARATOR_RUN = re.compile(r"[\s_-]+")


def normalize_token(raw: str) -> str:
    """Apply the alias table's normalization rule to one plan spelling."""
    return _SEPARATOR_RUN.sub("_", raw.strip().lower())


@functools.cache
def _lookup(surface: str) -> dict[str, str]:
    table = json.loads(ALIAS_TABLE.read_text(encoding="utf-8"))
    entry = table["surfaces"][surface]
    lookup: dict[str, str] = {}
    for canonical in entry["canonical"]:
        lookup[normalize_token(canonical)] = canonical
    for alias, canonical in entry["aliases"].items():
        if canonical not in entry["canonical"]:
            raise ValueError("plan_alias_target_unknown")
        lookup[normalize_token(alias)] = canonical
    return lookup


def plan_surface(kind: str) -> str:
    """Map a normalized resource kind to the alias-table surface its plan belongs to."""
    if kind == "render.key_value":
        return "key_value"
    if kind == "render.workflow":
        return "workflow"
    return "service_compute"


def normalize_plan(surface: str, raw: object) -> str | None:
    """Return the canonical plan id for ``raw`` on ``surface`` or None when unknown or unpriced.

    Resolution is exact after normalization; a plan that is not a canonical id or a listed
    alias stays None so Design and Estimate report it unavailable instead of borrowing a
    nearby plan.
    """
    if surface not in SURFACES:
        raise ValueError("plan_surface_unknown")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _lookup(surface).get(normalize_token(raw))
