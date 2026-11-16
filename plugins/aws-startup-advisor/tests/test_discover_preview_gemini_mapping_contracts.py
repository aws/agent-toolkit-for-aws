"""Text contract: Discover's preview maps every current Gemini id the same way Clarify does.

`discover-preview.md` Step 2A maps each observed source model with its own pattern table and
shows the per-token cost direction before Clarify runs. A current Gemini id that matches no
pattern falls through to the `Unknown / other` row (Nova Pro, $0.80 / $3.20), which for
`gemini-3.5-flash-lite` ($0.30 / $2.50) displays "higher" while Clarify Q19 and the shared
Gemini guide map it to Nova Lite ($0.06 / $0.24), "lower" on both rates. This test performs the
preview lookup for each current Gemini Flash id and pins that it (a) never hits the fallback and
(b) lands on the same primary target, with the same cost direction, as the Clarify Q19 row and
the shared guide's cost table.
"""
from __future__ import annotations

import re
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
GEMINI_GUIDE = SKILLS / "shared" / "ai" / "ai-gemini-to-bedrock.md"
GCP_REFS = SKILLS / "gcp-to-aws" / "references"
DISCOVER_PREVIEW = GCP_REFS / "phases" / "discover" / "discover-preview.md"
CLARIFY_AI = GCP_REFS / "phases" / "clarify" / "clarify-ai.md"

FALLBACK_SUBJECT = "Unknown / other"
PRICE = re.compile(r"\$(\d+(?:\.\d+)?)\s*/\s*\$(\d+(?:\.\d+)?)")

# (source id, product name as the Clarify Q19 / guide tables spell it, primary Bedrock target)
CURRENT_GEMINI = [
    ("gemini-3.5-flash", "Gemini 3.5 Flash (GA)", "Nova Lite"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "Nova Lite"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash", "Nova Pro"),
]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _section(text: str, start: str, end: str) -> str:
    idx = text.find(start)
    assert idx != -1, f"missing section anchor {start!r}"
    stop = text.find(end, idx)
    return text[idx:] if stop == -1 else text[idx:stop]


def _preview_rows() -> list[list[str]]:
    """Rows of the Step 2A alternatives table, in document order (lookup is first-match)."""
    text = DISCOVER_PREVIEW.read_text(encoding="utf-8")
    table = _section(text, "**Alternatives for sources with no Bedrock equivalent**", "**Haiku 5.5 preview:**")
    rows = [_cells(ln) for ln in table.splitlines() if ln.startswith("|")]
    rows = [r for r in rows if r[0] != "Source model pattern" and not set(r[0]) <= {"-"}]
    assert rows and rows[-1][0] == FALLBACK_SUBJECT, "the Unknown / other fallback must stay the last row"
    return rows


def _row_matches(pattern_cell: str, model_id: str) -> bool:
    """Apply one first-cell pattern list to a model id.

    Patterns are the backticked globs; a parenthesised `(not `-x`)` after a glob excludes ids
    carrying that suffix; `(retired ... — flag)` annotations and prose do not take part.
    """
    for glob, exclusion in re.findall(r"`([^`]+)`(\s*\(not `[^)]*\))?", pattern_cell):
        if glob.startswith("-"):
            continue  # an exclusion suffix captured on its own
        if not fnmatchcase(model_id, glob):
            continue
        excluded = re.findall(r"`(-[^`]+)`", exclusion)
        if any(model_id.endswith(suffix) for suffix in excluded):
            continue
        return True
    return False


def preview_lookup(model_id: str) -> list[str]:
    for row in _preview_rows():
        if row[0] == FALLBACK_SUBJECT or _row_matches(row[0], model_id):
            return row
    raise AssertionError("unreachable: fallback row is always last")


def _clarify_q19_row(product: str) -> list[str]:
    text = CLARIFY_AI.read_text(encoding="utf-8")
    rows = [_cells(ln) for ln in text.splitlines() if ln.startswith(f"| {product} ")]
    assert len(rows) == 1, f"expected exactly one Clarify Q19 row for {product!r}, found {len(rows)}"
    return rows[0]


def _guide_cost_rows(product: str, target: str) -> list[list[str]]:
    text = GEMINI_GUIDE.read_text(encoding="utf-8")
    live = _section(text, "### Gemini Pro Tier", "### Legacy/Specialized")
    # The guide marks GA rows "(GA)" where Clarify's Q19 table does not always; compare the bare name.
    bare = product.replace(" (GA)", "")
    return [
        r
        for r in (_cells(ln) for ln in live.splitlines() if ln.startswith("|"))
        if r[0].replace(" (GA)", "") == bare and r[2] == target
    ]


def _direction(source: tuple[float, float], target: tuple[float, float]) -> str:
    """Bedrock relative to source, the way Step 2A records `cost_direction`."""
    if target[0] <= source[0] and target[1] <= source[1]:
        return "lower"
    if target[0] >= source[0] and target[1] >= source[1]:
        return "higher"
    # Mixed per-token rates: decide on the blended 150M / 75M volume the guide's cost table uses.
    blended_source = source[0] * 150 + source[1] * 75
    blended_target = target[0] * 150 + target[1] * 75
    return "lower" if blended_target < blended_source else "higher"


def test_lookup_harness_resolves_the_existing_rows_the_way_a_reader_would() -> None:
    assert preview_lookup("gpt-5.4-mini")[1] == "Claude Haiku 5.5"
    assert preview_lookup("gemini-3.1-pro")[1] == "Claude Sonnet 5"
    assert preview_lookup("gemini-2.5-pro")[1] == "Claude Sonnet 5"
    # The `(not `-lite`)` exclusion keeps `gemini-3.5-flash` from swallowing `gemini-3.5-flash-lite`
    # regardless of row order.
    assert not _row_matches("`gemini-3.5-flash` (not `-lite`)", "gemini-3.5-flash-lite")
    assert _row_matches("`gemini-3.5-flash` (not `-lite`)", "gemini-3.5-flash")
    assert preview_lookup("gemini-2.0-flash-lite")[1] == "Amazon Nova Lite"
    assert preview_lookup("some-unknown-model")[0] == FALLBACK_SUBJECT


@pytest.mark.parametrize(("model_id", "product", "target"), CURRENT_GEMINI, ids=[m for m, _, _ in CURRENT_GEMINI])
def test_current_gemini_id_has_an_explicit_preview_row_matching_clarify(model_id: str, product: str, target: str) -> None:
    row = preview_lookup(model_id)
    # (a) the lookup never falls through to Nova Pro-by-default.
    assert row[0] != FALLBACK_SUBJECT, f"{model_id} falls through to the Unknown / other row — add an explicit preview mapping"
    # (b) the preview's primary target is the one Clarify Q19 and the shared guide name first.
    preview_primary = row[1].split(";")[0].replace("Amazon ", "").strip()
    assert preview_primary == target, f"preview maps {model_id} to {row[1]!r}, expected {target!r} first"
    clarify_row = _clarify_q19_row(product)
    clarify_primary = clarify_row[1].split(";")[0]
    assert clarify_primary.startswith(target), f"Clarify Q19 names {clarify_row[1]!r} first for {product}, preview says {target}"
    guide_rows = _guide_cost_rows(product, target)
    assert guide_rows, f"shared guide has no live-tier row {product!r} -> {target!r}"
    # The preview direction is the direction the guide's prices give — the reviewer's example was
    # the fallback showing "higher" for 3.5 Flash-Lite where Clarify shows "lower".
    source_price = tuple(map(float, PRICE.search(guide_rows[0][1]).groups()))
    target_price = tuple(map(float, PRICE.search(guide_rows[0][3]).groups()))
    assert _direction(source_price, target_price) == "lower", (product, target, source_price, target_price)
    assert "cheaper" in clarify_primary, f"Clarify Q19 does not call {target} cheaper for {product}: {clarify_primary!r}"
    preview = DISCOVER_PREVIEW.read_text(encoding="utf-8")
    note = _section(preview, "**Current Gemini preview:**", "For each mapped model pair")
    assert f"`{model_id}`" in note and f'"lower"' in note, f"preview note must state the recorded direction for {model_id}"
    # The target id in the preview row is the one the plugin uses elsewhere.
    expected_id = {"Nova Lite": "`amazon.nova-lite-v1:0`", "Nova Pro": "`amazon.nova-pro-v1:0`"}[target]
    assert row[2].split("/")[0].strip() == expected_id, row[2]


def test_fallback_row_is_not_how_a_current_gemini_flash_source_is_priced() -> None:
    """The fallback itself is unchanged (Nova Pro) — it must just never be what a current Gemini id resolves to."""
    rows = _preview_rows()
    assert rows[-1][1] == "Amazon Nova Pro" and rows[-1][2] == "`amazon.nova-pro-v1:0`"
    # Legacy 2.x rows and their flags are untouched by the current-Gemini rows.
    legacy = [r[0] for r in rows if "gemini-2." in r[0]]
    assert any("`gemini-2.5-pro` (retired Oct 20, 2026 — flag)" in c for c in legacy)
    assert any("`gemini-2.5-flash` (retired Oct 20, 2026 — flag)" in c and "`gemini-2.0-flash` (retired Jun 1, 2026 — flag)" in c for c in legacy)
    assert any("`gemini-2.0-flash-lite` (retired Jun 1, 2026 — flag)" in c for c in legacy)
