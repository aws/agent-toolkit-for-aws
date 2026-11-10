"""Text contract: Legacy and restricted Bedrock models never appear as recommended targets.

The pricing cache's `Status` column is the only lifecycle signal the mapping guides carry
inline, and `ai-model-lifecycle.md` Rule 3 says Legacy models are annotated but never
recommended as primary. This test pins the 2026-11-09 re-verification against the AWS legacy
lifecycle page and model cards:

- Gemma 3 (4B/12B/27B) and MiniMax M2/M2.1 are Legacy (EOL 2027-03-30), not `active`.
- Nova 2 Pro is a gated preview (Nova Forge early access, no Bedrock model card) and is
  `restricted`; it is never a "Best Bedrock Match" or a cross-family target.
- No Legacy or restricted model sits in the target column of a live-tier mapping row in the
  OpenAI or Gemini guides.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SHARED_AI = PLUGIN_ROOT / "skills" / "shared" / "ai"
PRICING_CACHE = SHARED_AI / "bedrock-pricing-cache.md"
LIFECYCLE = SHARED_AI / "ai-model-lifecycle.md"
OPENAI_GUIDE = SHARED_AI / "ai-openai-to-bedrock.md"
GEMINI_GUIDE = SHARED_AI / "ai-gemini-to-bedrock.md"

LEGACY_IDS = {
    "google.gemma-3-4b-it",
    "google.gemma-3-12b-it",
    "google.gemma-3-27b-it",
    "minimax.minimax-m2",
    "minimax.minimax-m2.1",
}
NOT_A_TARGET = re.compile(
    r"Nova 2 Pro|Llama 4 (?:Maverick|Scout)|Llama 3\.3|DeepSeek-R1|Jamba|Claude Opus 4\.1|Claude Sonnet 4\.5"
)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _status_by_id() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in PRICING_CACHE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) >= 8 and "." in cells[1]:
            out.setdefault(cells[1], cells[-1])
    return out


def test_pricing_cache_marks_gemma3_and_minimax_m2_legacy() -> None:
    status = _status_by_id()
    for model_id in sorted(LEGACY_IDS):
        assert model_id in status, f"{model_id} missing from the pricing cache"
        assert status[model_id].startswith("legacy (EOL Mar 30, 2027)"), f"{model_id}: {status[model_id]!r}"


def test_pricing_cache_marks_nova_2_pro_restricted() -> None:
    status = _status_by_id()
    assert status["amazon.nova-2-pro-v1:0"].startswith("restricted ("), status["amazon.nova-2-pro-v1:0"]


def test_lifecycle_table_lists_gemma3_and_minimax_m2() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    start = text.index("## Legacy / EOL Models")
    stop = text.index("**Removed (past EOL", start)
    table = text[start:stop]
    for model_id in sorted(LEGACY_IDS):
        assert f"`{model_id}`" in table, f"{model_id} is not in the Legacy/EOL table"
    assert "Nova 2 Pro" not in table, "Nova 2 Pro must not be named as an Active replacement"


def _live_rows(path: Path, start: str, end: str) -> list[list[str]]:
    text = path.read_text(encoding="utf-8")
    idx = text.index(start)
    stop = text.find(end, idx)
    live = text[idx:] if stop == -1 else text[idx:stop]
    rows = [_cells(ln) for ln in live.splitlines() if ln.startswith("|")]
    return [r for r in rows if len(r) >= 3 and not set(r[0]) <= {"-", " "}]


def test_openai_cross_family_targets_are_active_models() -> None:
    rows = _live_rows(OPENAI_GUIDE, "### Sources with no Bedrock equivalent", "### Open-weight gpt-oss")
    bad = [r for r in rows if NOT_A_TARGET.search(r[2])]
    assert not bad, f"Legacy/restricted targets in the OpenAI cross-family table: {[r[2] for r in bad]}"
    pro_rows = [r for r in rows if r[0] in {"GPT-5.5 Pro", "GPT-5.4 Pro", "o3-pro", "o1-pro"}]
    assert pro_rows and all(r[2] == "Claude Opus 5.5 (Global)" for r in pro_rows), pro_rows


def test_gemini_live_tier_targets_are_active_models() -> None:
    rows = _live_rows(GEMINI_GUIDE, "### Gemini Pro Tier", "### Legacy/Specialized")
    bad = [r for r in rows if NOT_A_TARGET.search(r[2])]
    assert not bad, f"Legacy/restricted targets in the Gemini live tiers: {[r[2] for r in bad]}"
    assert not any(r[0].startswith("Gemini 3 Pro") for r in rows), "gemini-3-pro-preview was shut down 2026-03-09"
    assert any(r[0].startswith("Gemini 4 Argon") for r in rows), "Gemini 4 Argon (Oct 13, 2026) must have a Pro-tier row"


def test_gemini_guide_names_3_8_flash_as_the_flash_successor() -> None:
    text = GEMINI_GUIDE.read_text(encoding="utf-8")
    assert "Migrate to Gemini 3.5 Flash" not in text
    assert "Migrate to Gemini 3.8 Flash" in text
    assert "auto-route to `gemini-3.6-flash`" in text


# --- regressions for the surfaces the first version of this file did not cover ----------------

import datetime as _dt

SKILLS = PLUGIN_ROOT / "skills"
STATUS_CELL = re.compile(r"`(legacy|excluded) \(EOL (\d{4}-\d{2}-\d{2})\)`")
# OpenAI ids whose access ended before this file's date (deprecations page, 2026-04-22 notice),
# keyed to the first-cell label the cross-family table uses.
OPENAI_SHUT_DOWN = {
    "o1": "o1",
    "o1-pro": "o1-pro",
    "o3-mini": "o4-mini / o3-mini / o1-mini",
    "gpt-4": "GPT-4",
    "gpt-4-turbo": "GPT-4 Turbo",
    "gpt-4.1-nano": "GPT-4.1 Nano",
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
}


def _last_updated() -> _dt.date:
    m = re.search(r"\*\*Last updated:\*\* (\d{4}-\d{2}-\d{2})", LIFECYCLE.read_text(encoding="utf-8"))
    assert m, "lifecycle file has no Last updated line"
    return _dt.date.fromisoformat(m.group(1))


def test_lifecycle_status_buckets_agree_with_days_to_eol() -> None:
    """(a) `legacy` means >90 days to EOL and `excluded` means <=90, measured from Last updated."""
    today = _last_updated()
    problems = []
    for line in LIFECYCLE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        for status, eol in STATUS_CELL.findall(line):
            days = (_dt.date.fromisoformat(eol) - today).days
            if (status == "legacy" and days <= 90) or (status == "excluded" and days > 90):
                problems.append((status, eol, days, line[:70]))
    assert not problems, problems


def test_nova_2_pro_only_appears_as_restricted_or_not_a_target() -> None:
    """(b) Nova 2 Pro is never offered as a recommendation; every mention carries the gated/restricted annotation."""
    allowed = re.compile(r"restricted|gated preview|never a (?:recommended )?target|not a target|is not a target", re.I)
    offenders = []
    for path in sorted(SKILLS.rglob("*.md")) + sorted(SKILLS.rglob("*.json")):
        if "vendored" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"Nova 2 Pro|nova-2-pro", line) and not allowed.search(line):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}")
    assert not offenders, offenders


def test_openai_rows_for_shut_down_sources_carry_the_marker() -> None:
    """(c) Every cross-family row whose OpenAI source shut down on 2026-10-23 says so and quotes no live delta."""
    rows = _live_rows(OPENAI_GUIDE, "### Sources with no Bedrock equivalent", "### Open-weight gpt-oss")
    by_label = {r[0]: r for r in rows}
    for model_id, label in OPENAI_SHUT_DOWN.items():
        assert label in by_label, f"no cross-family row {label!r} for {model_id}"
        delta = by_label[label][4]
        assert "Shut down" in delta and "2026-10-23" in delta, f"{model_id}: {delta[:80]!r}"
        assert not re.search(r"Bedrock \d+% cheaper", delta), f"{model_id} still quotes a live delta"


def test_gcp_clarify_rows_for_shut_down_sources_quote_no_live_saving() -> None:
    """(d) gcp-to-aws Clarify Q19 and confirmation-sheet rows for shut-down OpenAI sources say so and quote no live %."""
    clarify = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify"
    rows = []
    for name in ("clarify-ai.md", "clarify-assemble.md"):
        for line in (clarify / name).read_text(encoding="utf-8").splitlines():
            first = line.strip().strip("|").split("|")[0].strip() if line.startswith("|") else ""
            if first.startswith(("GPT-3.5 Turbo", "GPT-4 / GPT-4 Turbo", "GPT-4 Turbo migration", "o-series")):
                rows.append((name, first, line))
    assert len(rows) >= 4, [r[:2] for r in rows]
    for name, first, line in rows:
        assert re.search(r"[Ss]hut down", line), f"{name}: {first!r} has no shut-down marker"
        # o3 is still live until 2026-12-11, so its "source 14% cheaper" figure is allowed; shut-down ids may not carry a saving.
        assert not re.search(r"(?<!source )\b\d+(?:\.\d+)?% cheaper", line), f"{name}: {first!r} still quotes a live saving"
