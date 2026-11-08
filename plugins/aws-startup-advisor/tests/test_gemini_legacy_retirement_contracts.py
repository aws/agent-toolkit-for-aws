"""Text contract: the Gemini 2.0 and 2.5 generations are retired SOURCE models, priced by serving API.

Google retired `gemini-2.5-pro`, `gemini-2.5-flash`, and `gemini-2.5-flash-lite` on Vertex AI
on 2026-10-20; on the Gemini Developer API, 2.5 Pro and 2.5 Flash shut down 2026-12-01 (then
auto-route to 3.8 Flash / 3.5 Flash-Lite and are billed at those rates) and 2.5 Flash-Lite is
not deprecated. `gemini-2.0-flash` and `gemini-2.0-flash-lite` shut down on both Vertex AI and
the Developer API on 2026-06-01 (all pages read 2026-11-08). Three kinds of reference exist in
this plugin and they are treated differently:

A. Recognition must be PRESERVED. Scanners, fixtures, discovery docs, and their tests keep
   matching `gemini-2.0-*` and `gemini-2.5-*` ids because customer code still contains them.
B. Target eligibility / current-recommendation tables: no 2.0 or 2.5 model appears as a current
   model. A table row whose subject is a 2.x model is a legacy-source mapping row and must be
   marked Legacy / retired / EOL / excluded.
C. SOURCE baseline pricing is what the customer pays today, qualified by serving API and date,
   and is NOT a universal ban on 2.x prices: a Developer API `gemini-2.5-flash-lite` workload
   keeps its $0.10 / $0.40 baseline with no cutoff; Developer API 2.5 Pro / 2.5 Flash use their
   current rates before 2026-12-01 and the routed model's rates on or after; Vertex AI 2.5 and
   all 2.0 workloads are past shutdown and are priced against the replacement; a measured bill
   always wins. The 3.8 Flash 2027-01-01 price step stays explicit wherever 3.8 Flash is priced.

This test pins B and C without touching A.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
LIFECYCLE = SKILLS / "shared" / "ai" / "ai-model-lifecycle.md"
GEMINI_GUIDE = SKILLS / "shared" / "ai" / "ai-gemini-to-bedrock.md"
GCP_REFS = SKILLS / "gcp-to-aws" / "references"
CLARIFY_AI = GCP_REFS / "phases" / "clarify" / "clarify-ai.md"
CLARIFY_AI_ONLY = GCP_REFS / "phases" / "clarify" / "clarify-ai-only.md"
ESTIMATE_AI = GCP_REFS / "phases" / "estimate" / "estimate-ai.md"
SCHEMA_PREFERENCES = GCP_REFS / "shared" / "schema-preferences.md"
GCP_PRICING_CACHE = GCP_REFS / "shared" / "pricing-cache.md"

# Any way a doc names a retired generation: an id (`gemini-2.5-flash`, `gemini-2.0-flash-lite`),
# a product name ("Gemini 2.5 Pro", "Gemini 2.0 Flash Lite"), or the shorthand used inside
# comparison cells ("old 2.5 Flash", "2.0 Flash").
GEMINI_RETIRED = re.compile(r"(?i)gemini[- _]2\.[05]|\b2\.[05][- ](?:pro|flash)")
# The markers the plugin already uses for a non-current row (Gemini 1.5 rows use "Legacy — EOL").
LEGACY_MARKER = re.compile(r"(?i)\blegacy\b|\bretired\b|\bEOL\b|\bexcluded\b")

# Detection docs describe what the scanner must RECOGNIZE in customer code; a retired id there
# is a pattern to match, not a recommendation, so they are out of scope for the table check.
DISCOVERY_PATH_PART = f"{Path('references') / 'phases' / 'discover'}"


def _first_cell(line: str) -> str:
    return line.strip().strip("|").split("|")[0].strip()


def _table_rows_about_retired_gemini():
    """Rows whose SUBJECT (first cell) is a retired Gemini model.

    A 2.x mention elsewhere in a row ("Google's replacement for 2.5 Pro", "5x the retired 2.5
    Flash price") describes a current model and is not a 2.x row.
    """
    for path in sorted(SKILLS.rglob("*.md")):
        rel = path.relative_to(PLUGIN_ROOT)
        if DISCOVERY_PATH_PART in str(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("|"):
                continue
            if GEMINI_RETIRED.search(_first_cell(line)):
                yield rel, lineno, line


def _section(text: str, start: str, end: str) -> str:
    idx = text.find(start)
    assert idx != -1, f"missing section anchor {start!r}"
    stop = text.find(end, idx)
    return text[idx:] if stop == -1 else text[idx:stop]


# --- B: target eligibility / current-recommendation tables ---------------------------------


def test_rows_whose_subject_is_a_retired_gemini_model_are_marked_legacy() -> None:
    offenders = [
        f"{rel}:{lineno}: {line.strip()[:140]}"
        for rel, lineno, line in _table_rows_about_retired_gemini()
        if not LEGACY_MARKER.search(line)
    ]
    assert not offenders, (
        "A table row about a Gemini 2.0 / 2.5 model is a legacy-source mapping row and must say so "
        "(Legacy / retired / EOL / excluded); current-recommendation rows use current models:\n  "
        + "\n  ".join(offenders)
    )


def test_gemini_guide_current_tables_have_no_2x_rows_and_legacy_rows_keep_the_mapping() -> None:
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
    # The live tiers and the cost-comparison table carry no 2.0 or 2.5 rows at all (target /
    # current-recommendation rule) — the source-baseline rule lives in prose and legacy rows.
    live = text[text.find("### Gemini Pro Tier") : text.find("### Legacy/Specialized")]
    assert not [ln for ln in live.splitlines() if ln.startswith("|") and re.search(r"Gemini 2\.[05] \w", ln)], (
        "a Gemini 2.0 / 2.5 row is still in a live tier table"
    )
    cost = _section(text, "## Cost Comparison Table", "## Prompt Caching")
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
            assert "Q19b" in ln, "the 2.5 option must route to Q19b so the serving API is captured"
            seen.add("2.5")
        if re.search(r"^> \d+\. Gemini 2\.0", ln):
            assert "retired" in ln and "Jun 1, 2026" in ln, ln
            seen.add("2.0")
    assert seen == {"2.0", "2.5"}, f"Q19 menu is missing a flagged option for {sorted({'2.0', '2.5'} - seen)}"


def test_lifecycle_ssot_records_the_gemini_retirements() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    section = _section(text, "## Source-Model Retirements — Gemini 2.0 and 2.5", "## Integration Points")
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


# --- C: source baseline pricing is API/date-specific, not a universal 2.x ban ----------------


def test_lifecycle_ssot_prices_the_source_baseline_by_serving_api_and_date() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    section = _section(text, "## Source-Model Retirements — Gemini 2.0 and 2.5", "## Integration Points")
    # The two concepts are separated: target eligibility vs. what the customer pays today.
    assert "Target eligibility and current-recommendation tables" in section
    assert "Source baseline by serving API" in section
    # The universal-ban sentences the review objected to are gone.
    assert "not a current baseline for a new comparison table" not in section
    assert "estimate against the replacement's price, not the retired price" not in section
    # Developer API Flash-Lite keeps its real baseline, with no forced cutoff.
    flash_lite = next(ln for ln in section.splitlines() if ln.startswith("- **Gemini Developer API, `gemini-2.5-flash-lite`"))
    assert "$0.10 / $0.40" in flash_lite and "no forced cutoff" in flash_lite, flash_lite
    assert "$45" in flash_lite and "$232.50" in flash_lite, "reviewer's 150M/75M arithmetic must be stated"
    # Developer API Pro / Flash: current rates before 2026-12-01, routed rates on or after.
    before = next(ln for ln in section.splitlines() if "`gemini-2.5-pro` and `gemini-2.5-flash`, before 2026-12-01" in ln)
    assert "$1.25 / $10.00" in before and "$0.30 / $2.50" in before and "$937.50" in before and "$393.75" in before, before
    after = next(ln for ln in section.splitlines() if "`gemini-2.5-pro` and `gemini-2.5-flash`, on or after 2026-12-01" in ln)
    assert "Gemini 3.8 Flash" in after and "Gemini 3.5 Flash-Lite" in after, after
    assert "$0.75 / $3.75 through 2026-12-31" in after and "$1.50 / $7.50 from 2027-01-01" in after, (
        "the 3.8 Flash Jan 1, 2027 price step must stay explicit"
    )
    # Vertex AI 2.5 and all 2.0 workloads price against the replacement; measured spend wins.
    assert next(ln for ln in section.splitlines() if ln.startswith("- **Vertex AI, any 2.5 model:**")).count("replacement") >= 1
    assert next(ln for ln in section.splitlines() if ln.startswith("- **Any 2.0 model, either API:**")).count("replacement") >= 1
    assert "measured bill" in section and "authoritative" in section
    assert "https://aistudio.google.com/docs/pricing" in section
    # The consumer that needs the serving API is named, and so is the Clarify field that carries it.
    assert "ai_source_serving_api" in section and "Q19b" in section
    # Discover's `vertex_ai_generative` is the Gemini category, not proof of Vertex AI serving.
    assert "only for Vertex AI evidence" not in section
    assert "regardless of SDK" in section and "not a serving-API signal" in section
    assert "`detected_via` evidence (`terraform`, `monitoring`) establishes Vertex AI" in section


def test_gemini_guide_legacy_rows_and_cost_note_carry_the_api_date_baselines() -> None:
    text = GEMINI_GUIDE.read_text(encoding="utf-8")
    legacy = text[text.find("### Legacy/Specialized") :]
    pro = next(ln for ln in legacy.splitlines() if ln.startswith("| Gemini 2.5 Pro "))
    assert "$1.25 / $10.00 until Dec 1, 2026" in pro and "Nova Pro 62% cheaper" in pro, pro
    assert "$0.75 / $3.75" in pro and "$1.50 / $7.50 from Jan 1, 2027" in pro, "3.8 Flash step missing from the 2.5 Pro row"
    flash = next(ln for ln in legacy.splitlines() if ln.startswith("| Gemini 2.5 Flash / 2.5 Flash Thinking"))
    assert "$0.30 / $2.50 until Dec 1, 2026" in flash and "3.5 Flash-Lite" in flash, flash
    flash_lite = next(ln for ln in legacy.splitlines() if ln.startswith("| Gemini 2.5 Flash-Lite "))
    assert "$0.10 / $0.40, no cutoff" in flash_lite and "no forced cutoff" in flash_lite, flash_lite
    assert "Nova Micro 65% cheaper" in flash_lite and "do not substitute 3.5 Flash-Lite" in flash_lite, flash_lite
    assert "Vertex AI: past EOL" in flash_lite, flash_lite
    # The cost-comparison note states the Developer API figures at the table's 150M/75M volume.
    cost = _section(text, "## Cost Comparison Table", "## Prompt Caching")
    for needle in ("$45", "$938", "$360", "$394", "$788", "measured bill", "Dec 1, 2026", "Jan 1, 2027"):
        assert needle in cost, f"cost-comparison note is missing {needle!r}"
    # The headline bullet separates the two rules.
    assert "Source baseline is what the customer pays today, by serving API and date" in text
    assert "never appear as current rows" in text


def test_gcp_pricing_cache_marks_retired_rows_and_selects_the_baseline_by_api_and_date() -> None:
    text = GCP_PRICING_CACHE.read_text(encoding="utf-8")
    gemini = _section(text, "### Gemini (Standard Tier)", "### OpenAI (Standard Tier)")
    for model in ("Gemini 2.5 Pro ", "Gemini 2.5 Flash ", "Gemini 2.5 Flash-Lite", "Gemini 2.0 Flash ", "Gemini 2.0 Flash Lite"):
        rows = [ln for ln in gemini.splitlines() if ln.startswith("|") and model in ln]
        assert rows and all("retired" in r for r in rows), f"{model.strip()} row is not marked retired: {rows}"
    # Historical and current prices are kept with their sources; nothing was re-priced or invented.
    assert re.search(r"^\| Gemini 2\.5 Pro\s+\| 1\.25\s+\| 10\.00\s+\|", gemini, re.M), "Gemini 2.5 Pro price changed"
    assert re.search(r"^\| Gemini 2\.5 Flash\s+\| 0\.30\s+\| 2\.50\s+\|", gemini, re.M), "Gemini 2.5 Flash price changed"
    assert re.search(r"^\| Gemini 2\.5 Flash-Lite\s+\| 0\.10\s+\| 0\.40\s+\|", gemini, re.M), "Gemini 2.5 Flash-Lite price changed"
    assert re.search(r"^\| Gemini 2\.0 Flash\s+\| 0\.10\s+\| 0\.40\s+\|", gemini, re.M), "Gemini 2.0 Flash historical price changed"
    assert re.search(r"^\| Gemini 2\.0 Flash Lite\s+\| 0\.075\s+\| 0\.30\s+\|", gemini, re.M), "Gemini 2.0 Flash Lite historical price changed"
    assert re.search(r"^\| Gemini 3\.8 Flash\s+\| 0\.75\s+\| 3\.75\s+\|", gemini, re.M), "Gemini 3.8 Flash row missing or mispriced"
    assert re.search(r"^\| Gemini 3\.5 Flash-Lite\s+\| 0\.30\s+\| 2\.50\s+\|", gemini, re.M), "Gemini 3.5 Flash-Lite row missing or mispriced"
    note = next(ln for ln in gemini.splitlines() if ln.startswith("> **Gemini 2.5 retirement"))
    # No universal ban on the 2.5 rows; the rule is API- and date-specific.
    assert "Never use a 2.5 row" not in note
    assert "serving API" in note and "measured bill" in note
    assert "`vertex_ai_generative`" in note and "ai_source_serving_api" in note
    assert "`ai_constraints.ai_source_serving_api` first" in note
    assert "`detected_via` includes `terraform` or `monitoring`" in note
    assert "not a Vertex AI serving signal" in note and "(`vertex_ai_generative` = Vertex AI)" not in note
    assert "**Vertex AI**" in note and "named replacement" in note
    assert "`gemini-2.5-flash-lite` is not deprecated" in note and "0.10 / 0.40 row is the correct baseline" in note
    assert "$45" in note and "$232.50" in note
    assert "until Dec 1, 2026" in note and "$937.50" in note and "$393.75" in note
    assert "on or after Dec 1, 2026" in note and "0.75 / 3.75 through 2026-12-31; 1.50 / 7.50 from 2027-01-01" in note
    assert "https://aistudio.google.com/docs/pricing" in note
    # 2.0 is past shutdown on both APIs — still priced against the replacement.
    note_20 = next(ln for ln in gemini.splitlines() if ln.startswith("> **Gemini 2.0 retirement"))
    assert "both APIs" in note_20 and "replacement's rate" in note_20 and "Never use a 2.0 row" in note_20


def test_clarify_captures_the_serving_api_and_estimate_reads_it() -> None:
    clarify = CLARIFY_AI.read_text(encoding="utf-8")
    q19b = _section(clarify, "## Q19b — Which Google API serves that Gemini model", "## Q20 —")
    assert "`ai_source_serving_api`" in q19b or "ai_source_serving_api" in q19b
    for value in ('"vertex_ai"', '"gemini_developer_api"', '"unknown"'):
        assert value in q19b, f"Q19b is missing the {value} answer"
    # Discover only knows Vertex AI (`models[].service: vertex_ai_generative`); the Developer API
    # is asked, not guessed, and GCP-hosting alone never implies Vertex AI.
    assert "`vertex_ai_generative`" in q19b and "no Developer API value" in q19b
    # `vertex_ai_generative` is the Gemini category Discover assigns to every Gemini SDK (code scan
    # pattern 2.3 lumps google.generativeai with vertexai.generative_models); only `detected_via`
    # evidence establishes Vertex AI, so the value alone never resolves Q19b.
    assert "not a Vertex AI signal" in q19b
    assert "**with** `terraform` or `monitoring` in `detected_via`" in q19b
    assert "`[\"code\"]` only is unresolved" in q19b
    assert "never infer `vertex_ai` from the fact that the project is on GCP" in q19b
    assert "$0.10/$0.40 with no cutoff" in q19b and "Dec 1, 2026" in q19b and "Jan 1, 2027" in q19b
    # The 2.5 row of the Q19 table routes to Q19b and prices by API/date instead of banning 2.5 prices.
    row = next(ln for ln in clarify.splitlines() if ln.startswith("| Gemini 2.5 Pro / Flash / Flash-Lite"))
    assert "Ask Q19b" in row and "never use a 2.5 price" not in row, row
    # The row's skip condition requires terraform/monitoring evidence, not the service value alone.
    assert "`models[].service: vertex_ai_generative` **with** `terraform` or `monitoring`" in row, row
    assert "unless Discover already shows `models[].service: vertex_ai_generative`" not in row, row
    assert "2.5 Flash-Lite $0.10/$0.40 with no cutoff" in row and "until Dec 1, 2026" in row and "measured bill always wins" in row, row
    # The AI-only flow asks the same question for a 2.5 baseline.
    assert "Q19b" in CLARIFY_AI_ONLY.read_text(encoding="utf-8")
    # The preferences schema carries the field.
    assert "| `ai_source_serving_api`     | Q19b " in SCHEMA_PREFERENCES.read_text(encoding="utf-8")
    # Estimate Part 1 level 3 picks the cache row by serving API + date, and only when no measured bill exists.
    estimate = ESTIMATE_AI.read_text(encoding="utf-8")
    part1 = _section(estimate, "## Part 1: Establish Current AI Costs", "## Part 2:")
    assert "pick the row by serving API and date" in part1
    assert "`vertex_ai_generative`" in part1 and "`ai_constraints.ai_source_serving_api`" in part1
    # Clarify's answer wins; the Vertex branch needs terraform/monitoring evidence, never the
    # `vertex_ai_generative` value alone (that would price code-scanned Developer API workloads
    # at the replacement, e.g. 2.5 Flash-Lite $45 -> 3.5 Flash-Lite $232.50 at 150M / 75M).
    assert "read `ai_constraints.ai_source_serving_api` from `preferences.json` first" in part1
    assert "`detected_via` includes `terraform` or `monitoring`" in part1
    assert "not a Vertex AI serving signal" in part1 and "a code-only row is `unknown`" in part1
    assert "(`vertex_ai_generative` = Vertex AI)" not in part1
    assert "`gemini-2.5-flash-lite` uses its own 0.10 / 0.40 row with no cutoff" in part1
    assert "before 2026-12-01" in part1 and "on or after" in part1 and "2027-01-01" in part1
    assert "Gemini 2.0 rows are never a baseline on either API" in part1
    assert "a measured bill is always the baseline when it exists" in part1


# --- A: recognition is preserved -------------------------------------------------------------


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
