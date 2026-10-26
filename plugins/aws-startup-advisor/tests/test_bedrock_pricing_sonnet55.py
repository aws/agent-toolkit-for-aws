"""Pins the Bedrock pricing rows and migration defaults verified on 2026-10-25.

Covers the Sonnet 5.5 Global and Geo rates (Amazon Bedrock pricing, Anthropic models,
US East (Ohio)), the Sonnet 5 cache-read row that must stay unchanged, the Stable Image Core
price and its US East (N. Virginia) source, the Gemini 3.1 Flash Image source row, the default
Claude recommendation, and byte-identity of the vendored AI copies.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CACHE = PLUGIN_ROOT / "skills" / "shared" / "ai" / "bedrock-pricing-cache.md"
ANTHROPIC_GUIDE = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-anthropic-to-bedrock.md"
BMA_CLARIFY = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment" / "references" / "phases" / "clarify" / "clarify-ai.md"
BMA_SOURCE_CACHE = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment" / "references" / "shared" / "pricing-cache.md"

# Multi-provider quick reference has 8 cells; batch and cache table has 6 cells.
QUICK_REF_COLS = 8
BATCH_CACHE_COLS = 6


def _rows(text: str, prefix: str, ncols: int) -> list[list[str]]:
    """Return table rows whose first cell starts with `prefix` and that have `ncols` cells."""
    out = []
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == ncols:
            out.append(cells)
    return out


def _one(text: str, prefix: str, ncols: int) -> list[str]:
    rows = _rows(text, prefix, ncols)
    assert len(rows) == 1, f"expected one {ncols}-cell row starting {prefix!r}, found {len(rows)}"
    return rows[0]


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


@pytest.fixture(scope="module")
def cache() -> str:
    return CACHE.read_text(encoding="utf-8")


def test_sonnet55_global_quick_reference_matches_verified_rates(cache: str) -> None:
    row = _one(cache, "| Claude Sonnet 5.5 (Global)", QUICK_REF_COLS)
    assert row[3] == "2.00"   # input $/1M
    assert row[4] == "10.00"  # output $/1M


def test_sonnet55_geo_quick_reference_matches_verified_rates(cache: str) -> None:
    row = _one(cache, "| Claude Sonnet 5.5 (US Geo)", QUICK_REF_COLS)
    assert row[3] == "2.20"
    assert row[4] == "11.00"


def test_sonnet55_global_cache_rates_match_verified_values(cache: str) -> None:
    row = _one(cache, "| Claude Sonnet 5.5 (Global)", BATCH_CACHE_COLS)
    assert row[1] == "N/A" and row[2] == "N/A"  # batch not listed
    assert row[3] == "2.50"   # 5m cache write
    assert row[4] == "4.00"   # 1h cache write
    assert row[5] == "0.10"   # cache read, reduced 50% from Oct 7, 2026


def test_sonnet55_geo_cache_rates_match_verified_values(cache: str) -> None:
    row = _one(cache, "| Claude Sonnet 5.5 (US Geo)", BATCH_CACHE_COLS)
    assert row[3] == "2.75"
    assert row[4] == "4.40"
    assert row[5] == "0.11"


def test_sonnet5_cache_read_is_not_overwritten_by_55_rate(cache: str) -> None:
    row = _one(cache, "| Claude Sonnet 5 ", BATCH_CACHE_COLS)
    assert row[5] == "0.20"


def test_stable_image_core_is_priced_with_n_virginia_source(cache: str) -> None:
    row = _one(cache, "| Stable Image Core", 6)
    assert row[2] == "$0.04"
    heading = next(line for line in cache.splitlines() if line.startswith("### Stability AI"))
    assert "US East (N. Virginia)" in heading
    section = _section(cache, "### Stability AI", "### Anthropic Claude — batch")
    assert "Stable Image Core source" in section
    assert "only" in section
    assert "unavailable" not in section.lower()
    assert "unverified" not in section.lower()


def test_gemini_31_flash_image_source_row_and_inferred_caveat_present() -> None:
    text = BMA_SOURCE_CACHE.read_text(encoding="utf-8")
    section = _section(text, "#### Gemini 3.1 Flash Image", "### OpenAI (Standard Tier)")
    for token in ("30.00", "0.0336", "0.0168", "inferred"):
        assert token in section, f"missing {token!r} in Gemini 3.1 Flash Image section"


def test_default_recommendation_is_sonnet55_and_old_hold_sentence_is_gone(cache: str) -> None:
    assert "Recommend defaults (new migrations):** Claude Sonnet 5.5" in cache
    assert "Keep the current Sonnet 5 default" not in cache
    assert "keep the current Sonnet 5 default" not in cache.lower()
    assert "Default new Bedrock targets to **Claude Sonnet 5.5**" in ANTHROPIC_GUIDE.read_text(encoding="utf-8")
    assert "| Complex  | Claude Sonnet 5.5 required" in BMA_CLARIFY.read_text(encoding="utf-8")


@pytest.mark.parametrize("skill", ["agent-advisor", "azure-to-aws", "bedrock-migration-assessment", "gcp-to-aws"])
@pytest.mark.parametrize("name", ["bedrock-pricing-cache.md", "ai-anthropic-to-bedrock.md", "ai-gemini-to-bedrock.md", "ai-openai-to-bedrock.md"])
def test_vendored_ai_copies_are_byte_identical_to_shared(skill: str, name: str) -> None:
    canonical = PLUGIN_ROOT / "skills" / "shared" / "ai" / name
    vendored = PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "ai" / name
    if not vendored.is_file():
        pytest.skip(f"{skill} does not vendor {name}")
    assert vendored.read_bytes() == canonical.read_bytes()
