"""Text contract: the Gemini 2.5 generation is a retired SOURCE model, not a live baseline.

Google retired `gemini-2.5-pro`, `gemini-2.5-flash`, and `gemini-2.5-flash-lite` on Vertex AI
on 2026-10-20; on the Gemini Developer API, 2.5 Pro and 2.5 Flash shut down 2026-12-01 and
2.5 Flash-Lite is not deprecated (both pages read 2026-11-08). Two kinds of reference exist in
this plugin and they are treated differently:

A. Recognition must be PRESERVED. Scanners, fixtures, discovery docs, and their tests keep
   matching `gemini-2.5-*` ids because customer code still contains them.
B. Lifecycle status, pricing baselines, and target mappings must be CORRECTED. No pricing or
   mapping table may present a 2.5 model as a current (non-legacy) comparison baseline; it may
   appear only in a row that is marked Legacy / retired / excluded.

This test pins B without touching A: every markdown table row outside the discovery docs that
mentions a Gemini 2.5 model must carry a legacy marker, the Q19 source-model menu must flag 2.5
as retired, the lifecycle SSOT must carry the dated retirement section, and the detection
patterns and fixtures must still name the 2.5 ids.
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

# Any way a doc names the retired generation: an id (`gemini-2.5-flash`), a product name
# ("Gemini 2.5 Pro"), or the shorthand used inside comparison cells ("old 2.5 Flash").
GEMINI_25 = re.compile(r"(?i)gemini[- _]2\.5|\b2\.5[- ](?:pro|flash)")
# The markers the plugin already uses for a non-current row (Gemini 1.5 rows use "Legacy — EOL").
LEGACY_MARKER = re.compile(r"(?i)\blegacy\b|\bretired\b|\bEOL\b|\bexcluded\b")

# Detection docs describe what the scanner must RECOGNIZE in customer code; a 2.5 id there is a
# pattern to match, not a recommendation, so they are out of scope for the table check.
DISCOVERY_PATH_PART = f"{Path('references') / 'phases' / 'discover'}"


def _table_rows_mentioning_gemini_25():
    for path in sorted(SKILLS.rglob("*.md")):
        rel = path.relative_to(PLUGIN_ROOT)
        if DISCOVERY_PATH_PART in str(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("|"):
                continue
            if GEMINI_25.search(line):
                yield rel, lineno, line


def test_no_pricing_or_mapping_table_presents_gemini_25_as_a_current_baseline() -> None:
    offenders = [
        f"{rel}:{lineno}: {line.strip()[:140]}"
        for rel, lineno, line in _table_rows_mentioning_gemini_25()
        if not LEGACY_MARKER.search(line)
    ]
    assert not offenders, (
        "Gemini 2.5 Pro / Flash / Flash-Lite are retired (Vertex AI 2026-10-20; Developer API "
        "shutdown 2026-12-01 for Pro and Flash). A table row that names a 2.5 model must mark it "
        "Legacy / retired / EOL / excluded, or move the live baseline to a current model:\n  "
        + "\n  ".join(offenders)
    )


def test_gemini_25_still_has_legacy_mapping_rows_in_the_guide() -> None:
    """Customers still on 2.5 need a Bedrock mapping — the rows move to Legacy, they do not vanish."""
    text = GEMINI_GUIDE.read_text(encoding="utf-8")
    legacy_section = text[text.find("### Legacy/Specialized") :]
    for model in ("Gemini 2.5 Pro", "Gemini 2.5 Flash", "Gemini 2.5 Flash-Lite"):
        rows = [ln for ln in legacy_section.splitlines() if ln.startswith("|") and model in ln]
        assert rows, f"{GEMINI_GUIDE.relative_to(PLUGIN_ROOT)}: no Legacy/Specialized row for {model}"
        assert all("Legacy" in r and "Oct 20, 2026" in r for r in rows), rows
    # The live tiers and the cost-comparison table no longer carry 2.5 rows at all.
    live = text[text.find("### Gemini Pro Tier") : text.find("### Legacy/Specialized")]
    assert not [ln for ln in live.splitlines() if ln.startswith("|") and re.search(r"Gemini 2\.5 \w", ln)], (
        "a Gemini 2.5 row is still in a live tier table"
    )
    cost = text[text.find("## Cost Comparison Table") : text.find("## Prompt Caching")]
    assert not [ln for ln in cost.splitlines() if ln.startswith("|") and "Gemini 2.5" in ln], (
        "a Gemini 2.5 row is still in the cost-comparison table"
    )
    # The replacements Google names are priced from the public pricing page, read 2026-11-08.
    assert "| Gemini 3.8 Flash (GA)     | $0.75 / $3.75" in text
    assert "| Gemini 3.5 Flash-Lite     | $0.30 / $2.50" in text
    assert "https://aistudio.google.com/docs/pricing" in text


def test_q19_source_model_menu_flags_gemini_25_as_retired() -> None:
    text = CLARIFY_AI.read_text(encoding="utf-8")
    menu = [ln for ln in text.splitlines() if re.match(r"^> \d+\. ", ln) and GEMINI_25.search(ln)]
    assert menu, "Q19 menu lost its Gemini 2.5 entry — a user still on 2.5 must be able to pick it"
    for ln in menu:
        # A replacement option may name 2.5 ("replacement for 2.5 Pro"); the 2.5 option itself
        # must be flagged the way the 1.5 options already are.
        if re.search(r"^> \d+\. Gemini 2\.5", ln):
            assert "retired" in ln and "Oct 20, 2026" in ln, ln


def test_lifecycle_ssot_records_the_gemini_25_retirement() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    idx = text.find("## Source-Model Retirements — Gemini 2.5")
    assert idx != -1, "ai-model-lifecycle.md is missing the Gemini 2.5 source-model retirement section"
    section = text[idx : text.find("## Integration Points", idx)]
    for needle in (
        "`gemini-2.5-pro`",
        "`gemini-2.5-flash`",
        "`gemini-2.5-flash-lite`",
        "2026-10-20",
        "2026-12-01",
        "`excluded (EOL 2026-12-01)`",
        "Not deprecated",
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


def test_gcp_pricing_cache_marks_gemini_25_rows_retired_and_prices_replacements() -> None:
    text = GCP_PRICING_CACHE.read_text(encoding="utf-8")
    gemini = text[text.find("### Gemini (Standard Tier)") : text.find("### OpenAI (Standard Tier)")]
    for model in ("Gemini 2.5 Pro ", "Gemini 2.5 Flash ", "Gemini 2.5 Flash-Lite"):
        rows = [ln for ln in gemini.splitlines() if ln.startswith("|") and model in ln]
        assert rows and all("retired" in r for r in rows), f"{model.strip()} row is not marked retired: {rows}"
    assert re.search(r"^\| Gemini 3\.8 Flash\s+\| 0\.75\s+\| 3\.75\s+\|", gemini, re.M), "Gemini 3.8 Flash row missing or mispriced"
    assert re.search(r"^\| Gemini 3\.5 Flash-Lite\s+\| 0\.30\s+\| 2\.50\s+\|", gemini, re.M), "Gemini 3.5 Flash-Lite row missing or mispriced"


def test_detection_of_retired_gemini_25_ids_is_preserved() -> None:
    """Kind A: the scanner contract and fixtures must keep naming 2.5 ids."""
    for rel in (
        "skills/bedrock-migration-assessment/references/phases/discover/discover-app-code.md",
        "skills/gcp-to-aws/references/phases/discover/discover-app-code.md",
    ):
        assert "`gemini-2.5-*`" in (PLUGIN_ROOT / rel).read_text(encoding="utf-8"), f"{rel} dropped the gemini-2.5-* detection pattern"
    fixtures = PLUGIN_ROOT / "fixtures"
    assert "gemini-2.5-pro" in (fixtures / "bma-scan-genai-env-in-code" / "ai-workload-profile.json").read_text(encoding="utf-8")
    assert "gemini-2.5-flash-lite" in (fixtures / "bma-scan-vertex-env-flash-lite" / "ai-workload-profile.json").read_text(encoding="utf-8")
