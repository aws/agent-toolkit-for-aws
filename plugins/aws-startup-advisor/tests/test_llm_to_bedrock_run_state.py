"""Guard: llm-to-bedrock's run-state/resume machine (PR #425 findings 10, 11, 15).

Finding 10 — Step 1.5's own text instructed an immediate write of
`$BEDROCK_RUN_DIR/usage-baseline.json`, but `$BEDROCK_RUN_DIR` is not set
until "### A3 — ..." runs, several steps later (after Phase A). Step 1.5
runs strictly BEFORE Phase A, so the write-instruction was a forward
reference to a variable that doesn't exist yet at that point in the
document. The fix defers the actual file write to A3, immediately after
`$BEDROCK_RUN_DIR` is established, while letting Step 1.5's own glob/pick/
compute logic (steps 1-6) keep running early so Phase A's fresh-Discover
fallback decision still short-circuits correctly. Separately, C6 (the
report-generator) is a fresh, stateless dispatch with no way to resolve
`$BEDROCK_RUN_DIR` or confirm `usage-baseline.json`'s existence on its own
— the fix adds a "Usage baseline path" line to the context block passed at
every C5/C6 dispatch, and updates the report-generator to read that line
instead of silently assuming `$BEDROCK_RUN_DIR`.

Finding 11 — `current-context.json` (built at the C0 run-context gate) and
its MISMATCH table never referenced `usage-baseline.json`'s identity at
all, so a changed or removed baseline between runs could never trigger a
scoped invalidation on resume. The fix adds `usage_baseline_sha256` to the
schema and a MISMATCH table row.

Finding 15 — Step 1.5's tiebreak logic claimed "lexicographic sort on
`<MMDD-HHMM>` IS chronological", which is false across a year boundary
(`1231-1200` sorts after `0102-1200` even when the January directory is
objectively newer). The fix makes `.phase-status.json`'s `last_updated`
(a full, year-qualified ISO-8601 timestamp) the primary sort key, falls
back to the `<MMDD-HHMM>` name only when `last_updated` is missing or
unparseable (with the same-year limitation stated explicitly), and surfaces
a genuine ambiguous/missing-timestamp tie to the user instead of guessing.

These are documentation-contract checks (string/shape/order assertions
against the markdown), matching the existing `test_decision_gate_wiring.py`
/ `test_azure_discover_ordering.py` pattern.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

SKILL_MD = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "SKILL.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"


def _section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


# ---------------------------------------------------------------------------
# Finding 10, part 1 — write deferred to after $BEDROCK_RUN_DIR exists
# ---------------------------------------------------------------------------


def test_step_1_5_defers_the_write_instead_of_writing_immediately() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_section = _section(text, "## Step 1.5", "## Phase A")

    assert "do not write them yet" in step15_section, (
        "Step 1.5 no longer explicitly defers the usage-baseline.json write "
        "— it must not instruct an immediate write before $BEDROCK_RUN_DIR "
        "exists"
    )
    assert "`$BEDROCK_RUN_DIR` does not exist" in step15_section, (
        "Step 1.5 must state that $BEDROCK_RUN_DIR is not yet assigned at "
        "the point Step 1.5 runs"
    )


def test_a3_heading_is_named_consistently_and_performs_the_write() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    heading = "A3 — Locate Assess output, then establish this skill's own run state"
    assert f"### {heading}" in text, (
        "the A3-equivalent heading is missing or no longer named consistently "
        "with its cross-references"
    )
    # Every cross-reference to this block elsewhere in the file must quote
    # "A3 — Locate Assess output" (the heading's stable prefix, tolerant of
    # the markdown source wrapping the rest of the long heading across a
    # line break), not an informal/undocumented alias like bare "Phase A3".
    assert text.count("A3 — Locate Assess output") >= 3, (
        "cross-references to the A3 block should consistently quote its "
        "heading rather than an informal alias"
    )

    a3_idx = text.index("### A3 — Locate Assess output, then establish this skill's own run state")
    b1_idx = text.index("## Phase B — Execute Prep")
    a3_section = text[a3_idx:b1_idx]
    assert "Write `usage-baseline.json`, now that `$BEDROCK_RUN_DIR` exists" in a3_section, (
        "A3 no longer contains the deferred usage-baseline.json write step"
    )


def test_usage_baseline_write_step_in_a3_comes_after_bedrock_run_dir_is_set() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    a3_idx = text.index(
        "### A3 — Locate Assess output, then establish this skill's own run state"
    )
    b1_idx = text.index("## Phase B — Execute Prep")
    a3_section = text[a3_idx:b1_idx]

    set_dir_idx = a3_section.index("Set `$BEDROCK_RUN_DIR`")
    write_idx = a3_section.index(
        "Write `usage-baseline.json`, now that `$BEDROCK_RUN_DIR` exists"
    )
    assert write_idx > set_dir_idx, (
        "the usage-baseline.json write instruction appears before "
        "$BEDROCK_RUN_DIR is set within A3 — the ordering bug has regressed"
    )


# ---------------------------------------------------------------------------
# Finding 10, part 2 — context-block line + report-generator reads it
# ---------------------------------------------------------------------------


def test_context_block_includes_usage_baseline_path_line() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    context_block_section = _section(
        text, "### The context block", "### C0 — Run-context gate"
    )
    assert "Usage baseline path:" in context_block_section, (
        "the context block section is missing a 'Usage baseline path' line "
        "for C5/C6 dispatches"
    )
    assert "C5/C6" in context_block_section.split("Usage baseline path:")[1][:120], (
        "the Usage baseline path line does not scope itself to C5/C6 "
        "dispatches"
    )


def test_report_generator_reads_passed_baseline_path_not_bare_bedrock_run_dir() -> None:
    text = REPORT_GENERATOR.read_text(encoding="utf-8")
    section = _section(text, "## 6.3", "The migration plan may map multiple")
    assert "Usage baseline path:" in section, (
        "report-generator §6.3 no longer reads the 'Usage baseline path' "
        "context-block line"
    )
    assert "do NOT derive or assume" in section or "do not derive or assume" in section.lower(), (
        "report-generator §6.3 no longer explicitly disclaims silently "
        "assuming $BEDROCK_RUN_DIR is available to it"
    )


# ---------------------------------------------------------------------------
# Finding 11 — usage_baseline_sha256 fingerprint + MISMATCH table row
# ---------------------------------------------------------------------------


def test_current_context_schema_includes_usage_baseline_sha256() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    c0_section = _section(text, "### C0 — Run-context gate", "### C1 — Analyzer")
    assert '"usage_baseline_sha256"' in c0_section, (
        "current-context.json's documented schema is missing "
        "usage_baseline_sha256"
    )


def test_mismatch_table_has_usage_baseline_sha256_row() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    c0_section = _section(text, "### C0 — Run-context gate", "### C1 — Analyzer")
    assert "usage_baseline_sha256" in c0_section.split("| Mismatched field(s)")[1], (
        "the MISMATCH table has no row for usage_baseline_sha256"
    )
    # Must archive at least REPORT (and ideally EVAL/REWRITE) and keep
    # ANALYSIS/INGESTION, matching the stated granularity of the sibling
    # source_key_sha256 row.
    mismatch_table_idx = c0_section.index("| Mismatched field(s)")
    row_idx = c0_section.index("usage_baseline_sha256", mismatch_table_idx)
    row_line = c0_section[row_idx: c0_section.index("\n", row_idx)]
    assert "REPORT" in row_line
    assert "ANALYSIS" in row_line or "INGESTION" in row_line


# ---------------------------------------------------------------------------
# Finding 15 — year-aware tiebreak, no unconditional lexicographic claim
# ---------------------------------------------------------------------------


def test_tiebreak_no_longer_claims_unconditional_lexicographic_chronology() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_section = _section(text, "## Step 1.5", "## Phase A")
    assert "IS chronological" not in step15_section, (
        "Step 1.5 still claims lexicographic sort on <MMDD-HHMM> IS "
        "chronological unconditionally — this is false across a year "
        "boundary (finding 15 regression)"
    )


def test_tiebreak_uses_last_updated_as_primary_sort_key() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_section = _section(text, "## Step 1.5", "## Phase A")
    assert "last_updated" in step15_section, (
        "Step 1.5's tiebreak no longer references last_updated at all"
    )
    assert "primary" in step15_section, (
        "Step 1.5's tiebreak no longer names last_updated as the primary "
        "sort key"
    )
    assert "same-year" in step15_section or "same calendar year" in step15_section, (
        "Step 1.5's <MMDD-HHMM> fallback no longer states its same-year "
        "limitation explicitly"
    )


def test_tiebreak_surfaces_genuine_ties_to_the_user_instead_of_guessing() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    step15_section = _section(text, "## Step 1.5", "## Phase A")
    assert "do NOT silently guess" in step15_section or "do not silently guess" in step15_section.lower(), (
        "Step 1.5's tiebreak no longer states that an ambiguous/missing-"
        "timestamp tie must be surfaced to the user rather than guessed"
    )
