"""Text contract: the Gemini 2.0 and 2.5 generations are retired SOURCE models, not live baselines.

Google retired `gemini-2.5-pro`, `gemini-2.5-flash`, and `gemini-2.5-flash-lite` on Vertex AI
on 2026-10-20; on the Gemini Developer API, 2.5 Pro and 2.5 Flash shut down 2026-12-01 and
2.5 Flash-Lite is not deprecated. `gemini-2.0-flash` and `gemini-2.0-flash-lite` shut down on
both Vertex AI and the Developer API on 2026-06-01 (all pages read 2026-11-08). Two kinds of
reference exist in this plugin and they are treated differently:

A. Recognition must be PRESERVED. Scanners, fixtures, discovery docs, and their tests keep
   matching `gemini-2.0-*` and `gemini-2.5-*` ids because customer code still contains them.
B. Lifecycle status, pricing baselines, and target mappings must be CORRECTED. No pricing or
   mapping table may present a 2.0 or 2.5 model as a current (non-legacy) comparison baseline;
   it may appear only in a row that is marked Legacy / retired / excluded.

This test pins B without touching A: every markdown table row outside the discovery docs that
mentions a Gemini 2.0 or 2.5 model must carry a legacy marker, the Q19 source-model menu must
flag both generations as retired, the lifecycle SSOT must carry the dated retirement section,
and the detection patterns and fixtures must still name the retired ids.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
LIFECYCLE = SKILLS / "shared" / "ai" / "ai-model-lifecycle.md"
GEMINI_GUIDE = SKILLS / "shared" / "ai" / "ai-gemini-to-bedrock.md"
CLARIFY_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-ai.md"
GCP_PRICING_CACHE = SKILLS / "gcp-to-aws" / "references" / "shared" / "pricing-cache.md"

# Any way a doc names a retired generation: an id (`gemini-2.5-flash`, `gemini-2.0-flash-lite`),
# a product name ("Gemini 2.5 Pro", "Gemini 2.0 Flash Lite"), or the shorthand used inside
# comparison cells ("old 2.5 Flash", "2.0 Flash").
GEMINI_RETIRED = re.compile(r"(?i)gemini[- _]2\.[05]|\b2\.[05][- ](?:pro|flash)")
# The markers the plugin already uses for a non-current row (Gemini 1.5 rows use "Legacy — EOL").
LEGACY_MARKER = re.compile(r"(?i)\blegacy\b|\bretired\b|\bEOL\b|\bexcluded\b")

# Detection docs describe what the scanner must RECOGNIZE in customer code; a retired id there
# is a pattern to match, not a recommendation, so they are out of scope for the table check.
DISCOVERY_PATH_PART = f"{Path('references') / 'phases' / 'discover'}"


def _table_rows_mentioning_retired_gemini():
    for path in sorted(SKILLS.rglob("*.md")):
        rel = path.relative_to(PLUGIN_ROOT)
        if DISCOVERY_PATH_PART in str(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("|"):
                continue
            if GEMINI_RETIRED.search(line):
                yield rel, lineno, line


def test_no_pricing_or_mapping_table_presents_retired_gemini_as_a_current_baseline() -> None:
    offenders = [
        f"{rel}:{lineno}: {line.strip()[:140]}"
        for rel, lineno, line in _table_rows_mentioning_retired_gemini()
        if not LEGACY_MARKER.search(line)
    ]
    assert not offenders, (
        "Gemini 2.5 Pro / Flash / Flash-Lite are retired (Vertex AI 2026-10-20; Developer API "
        "shutdown 2026-12-01 for Pro and Flash) and Gemini 2.0 Flash / Flash-Lite shut down on both "
        "2026-06-01. A table row that names one must mark it Legacy / retired / EOL / excluded, or "
        "move the live baseline to a current model:\n  "
        + "\n  ".join(offenders)
    )


def test_retired_gemini_still_has_legacy_mapping_rows_in_the_guide() -> None:
    """Customers still on 2.0 / 2.5 need a Bedrock mapping — the rows move to Legacy, they do not vanish."""
    text = GEMINI_GUIDE.read_text(encoding="utf-8")
    legacy_section = text[text.find("### Legacy/Specialized") :]
    for model, date in (
        ("Gemini 2.5 Pro", "Oct 20, 2026"),
        ("Gemini 2.5 Flash", "Oct 20, 2026"),
        ("Gemini 2.5 Flash-Lite", "Oct 20, 2026"),
        ("Gemini 2.0 Flash", "Jun 1, 2026"),
        ("Gemini 2.0 Flash-Lite", "Jun 1, 2026"),
    ):
        rows = [ln for ln in legacy_section.splitlines() if ln.startswith("|") and model in ln]
        assert rows, f"{GEMINI_GUIDE.relative_to(PLUGIN_ROOT)}: no Legacy/Specialized row for {model}"
        assert all("Legacy" in r and date in r for r in rows), rows
    # The 2.0 rows keep their historical price (May 2026 read) rather than a refreshed one.
    assert "Was $0.10 / $0.40." in [ln for ln in legacy_section.splitlines() if ln.startswith("| Gemini 2.0 Flash ")][0]
    assert "Was $0.075 / $0.30." in [ln for ln in legacy_section.splitlines() if ln.startswith("| Gemini 2.0 Flash-Lite")][0]
    # The live tiers and the cost-comparison table no longer carry 2.0 or 2.5 rows at all.
    live = text[text.find("### Gemini Pro Tier") : text.find("### Legacy/Specialized")]
    assert not [ln for ln in live.splitlines() if ln.startswith("|") and re.search(r"Gemini 2\.[05] \w", ln)], (
        "a Gemini 2.0 / 2.5 row is still in a live tier table"
    )
    cost = text[text.find("## Cost Comparison Table") : text.find("## Prompt Caching")]
    assert not [ln for ln in cost.splitlines() if ln.startswith("|") and re.search(r"Gemini 2\.[05]", ln)], (
        "a Gemini 2.0 / 2.5 row is still in the cost-comparison table"
    )
    # The replacements Google names are priced from the public pricing page, read 2026-11-08.
    assert "| Gemini 3.8 Flash (GA)     | $0.75 / $3.75" in text
    assert "| Gemini 3.5 Flash-Lite     | $0.30 / $2.50" in text
    assert "https://aistudio.google.com/docs/pricing" in text


def test_q19_source_model_menu_flags_retired_gemini() -> None:
    text = CLARIFY_AI.read_text(encoding="utf-8")
    menu = [ln for ln in text.splitlines() if re.match(r"^> \d+\. ", ln) and GEMINI_RETIRED.search(ln)]
    assert menu, "Q19 menu lost its Gemini 2.0 / 2.5 entries — a user still on one must be able to pick it"
    seen = set()
    for ln in menu:
        # A replacement option may name 2.5 ("replacement for 2.5 Pro"); the retired option itself
        # must be flagged the way the 1.5 options already are.
        if re.search(r"^> \d+\. Gemini 2\.5", ln):
            assert "retired" in ln and "Oct 20, 2026" in ln, ln
            seen.add("2.5")
        if re.search(r"^> \d+\. Gemini 2\.0", ln):
            assert "retired" in ln and "Jun 1, 2026" in ln, ln
            seen.add("2.0")
    assert seen == {"2.0", "2.5"}, f"Q19 menu is missing a flagged option for {sorted({'2.0', '2.5'} - seen)}"


def test_lifecycle_ssot_records_the_gemini_retirements() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    idx = text.find("## Source-Model Retirements — Gemini 2.0 and 2.5")
    assert idx != -1, "ai-model-lifecycle.md is missing the Gemini 2.0 / 2.5 source-model retirement section"
    section = text[idx : text.find("## Integration Points", idx)]
    for needle in (
        "`gemini-2.5-pro`",
        "`gemini-2.5-flash`",
        "`gemini-2.5-flash-lite`",
        "`gemini-2.0-flash`",
        "`gemini-2.0-flash-lite`",
        "2026-10-20",
        "2026-12-01",
        "2026-06-01",
        "`excluded (EOL 2026-12-01)`",
        "`excluded (EOL 2026-06-01)`",
        "Not deprecated",
        "`gemini-3.6-flash`",
        "`gemini-3.1-flash-lite`",
        "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions",
        "https://aistudio.google.com/docs/deprecations",
        "2026-11-08",
    ):
        assert needle in section, f"lifecycle SSOT section is missing {needle!r}"
    # model-id-lint bans backticked ids it finds in the SECOND cell of any row containing
    # "excluded"; the source-model table must keep its ids out of that cell so retired Gemini
    # ids stay recognizable in scanners and fixtures.
    for row in section.splitlines():
        if row.startswith("|") and "excluded" in row.lower():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            assert "`" not in cells[1], f"source-model id leaked into model-id-lint's Model ID column: {row[:100]}"


def test_gcp_pricing_cache_marks_retired_gemini_rows_and_prices_replacements() -> None:
    text = GCP_PRICING_CACHE.read_text(encoding="utf-8")
    gemini = text[text.find("### Gemini (Standard Tier)") : text.find("### OpenAI (Standard Tier)")]
    for model in ("Gemini 2.5 Pro ", "Gemini 2.5 Flash ", "Gemini 2.5 Flash-Lite", "Gemini 2.0 Flash ", "Gemini 2.0 Flash Lite"):
        rows = [ln for ln in gemini.splitlines() if ln.startswith("|") and model in ln]
        assert rows and all("retired" in r for r in rows), f"{model.strip()} row is not marked retired: {rows}"
    # The 2.0 rows keep their May 2026 prices as historical figures; nothing was re-priced.
    assert re.search(r"^\| Gemini 2\.0 Flash\s+\| 0\.10\s+\| 0\.40\s+\|", gemini, re.M), "Gemini 2.0 Flash historical price changed"
    assert re.search(r"^\| Gemini 2\.0 Flash Lite\s+\| 0\.075\s+\| 0\.30\s+\|", gemini, re.M), "Gemini 2.0 Flash Lite historical price changed"
    assert re.search(r"^\| Gemini 3\.8 Flash\s+\| 0\.75\s+\| 3\.75\s+\|", gemini, re.M), "Gemini 3.8 Flash row missing or mispriced"
    assert re.search(r"^\| Gemini 3\.5 Flash-Lite\s+\| 0\.30\s+\| 2\.50\s+\|", gemini, re.M), "Gemini 3.5 Flash-Lite row missing or mispriced"


def test_detection_of_retired_gemini_ids_is_preserved() -> None:
    """Kind A: the scanner contract and fixtures must keep naming the retired ids."""
    for rel in (
        "skills/bedrock-migration-assessment/references/phases/discover/discover-app-code.md",
        "skills/gcp-to-aws/references/phases/discover/discover-app-code.md",
    ):
        text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
        assert "`gemini-2.5-*`" in text, f"{rel} dropped the gemini-2.5-* detection pattern"
        assert "`gemini-2.0-*`" in text, f"{rel} dropped the gemini-2.0-* detection pattern"
    fixtures = PLUGIN_ROOT / "fixtures"
    assert "gemini-2.5-pro" in (fixtures / "bma-scan-genai-env-in-code" / "ai-workload-profile.json").read_text(encoding="utf-8")
    assert "gemini-2.5-flash-lite" in (fixtures / "bma-scan-vertex-env-flash-lite" / "ai-workload-profile.json").read_text(encoding="utf-8")
    # The discover-preview pattern table keeps both 2.0 ids as source patterns (flagged, not dropped).
    preview = (SKILLS / "gcp-to-aws" / "references" / "phases" / "discover" / "discover-preview.md").read_text(encoding="utf-8")
    assert "`gemini-2.0-flash` (retired Jun 1, 2026 — flag)" in preview
    assert "`gemini-2.0-flash-lite` (retired Jun 1, 2026 — flag)" in preview
