"""Guard: the azure-to-aws Clarify fast path keeps its gate and provenance contracts.

The fast path (clarify.md § Step 0.5) lets a PROPOSED row take its default without being
asked. Five contracts make that safe, and each lives in prose that a benign rewording could
silently drop:

1. The Clarify handoff gates are MODE-AWARE — a fast-path run passes with the default
   recorded in `metadata.questions_defaulted[]`, not by asserting the row "was asked".
2. `db_cutover` has a documented default when NO database size was measured
   (`size_coverage: "unknown"`), so the assembler checklist is satisfiable on every path.
3. A workshop-sheet correction updates the default index the same way a direct
   decision-gate correction does.
4. Step 3b clears EVERY piece of deferral state (row flag + both lists) and reprices
   Part 4, not Part 7.
5. A gate-side preference write after scenarios exist reconciles the active scenario
   (`workshop-invariants.md` § 4).

These anchor on stable substrings (key names, section titles, enum values) rather than
sentence wording. The last two tests give the contracts mechanical teeth: the Q-D2 rule
function at the 100/101 GiB boundary, and the three clarify goldens through their asserters.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess  # nosec B404 — runs only the committed fixture asserters via sys.executable
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "azure-to-aws"
REF = SKILL / "references"
FIXTURE = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform"

CLARIFY = REF / "phases" / "clarify" / "clarify.md"
CLARIFY_ASSEMBLE = REF / "phases" / "clarify" / "clarify-assemble.md"
CLARIFY_DATABASE = REF / "phases" / "clarify" / "clarify-database.md"
DISCOVER_ASSEMBLE = REF / "phases" / "discover" / "discover-assemble.md"
ESTIMATE_ASSEMBLE = REF / "phases" / "estimate" / "estimate-assemble.md"
ESTIMATE_INFRA = REF / "phases" / "estimate" / "estimate-infra.md"
GENERATE = REF / "phases" / "generate" / "generate.md"
WORKSHOP_REFRESH = REF / "phases" / "workshop" / "workshop-refresh.md"
WORKSHOP_SHEET = REF / "phases" / "workshop" / "workshop-sheet.md"
WORKSHOP_COMPARE = REF / "phases" / "workshop" / "workshop-compare.md"
SCHEMA_PREFS = REF / "shared" / "schema-preferences.md"
SCHEMA_SCENARIOS = REF / "shared" / "schema-workshop-scenarios.md"
REPORT_CORE = REF / "shared" / "report-decision-core.md"
ASSERTER = FIXTURE / "check_expected_clarify.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "file has no YAML frontmatter"
    return m.group(1)


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def test_clarify_gates_are_mode_aware() -> None:
    fm = _frontmatter(_read(CLARIFY))
    # The wizard-only assertion that failed every eligible shared-plan handoff is gone.
    assert "isolation question was asked and its answer recorded" not in fm, (
        "clarify.md: the isolation postcondition still asserts the question WAS ASKED; "
        "a fast-path run that recorded the default cannot pass it"
    )
    for anchor in ("isolation_split", "pattern_id"):
        line = next(ln for ln in fm.splitlines() if "_assert" in ln and anchor in ln)
        assert "fast_path" in line and "questions_defaulted" in line, (
            f"clarify.md: the {anchor} postcondition has no fast-path branch keyed on "
            f"metadata.clarify_mode / metadata.questions_defaulted"
        )
    # The "every PROPOSED row ... questions_defaulted[]" postcondition must carve out the
    # deferred row, or the fast-path golden (db_cutover only in deferred_to_generate[])
    # fails it on a literal reading.
    every_row = next(
        ln for ln in fm.splitlines() if "_assert" in ln and "every PROPOSED row" in ln
    )
    assert "deferred_to_generate" in every_row, (
        "clarify.md: the 'every PROPOSED row ... questions_defaulted[]' postcondition does "
        "not exempt rows carrying deferred_to_generate: true (the lists are disjoint)"
    )
    checklist = _section(_read(CLARIFY_ASSEMBLE), "## Validation Checklist", "## Status")
    assert "size_coverage" in checklist, (
        "clarify-assemble.md checklist no longer requires size_coverage on deferred rows"
    )
    assert re.search(r"questions_defaulted\[\]`? and `?deferred_to_generate\[\]`? share no key", checklist), (
        "clarify-assemble.md checklist dropped the disjointness line"
    )
    assert "app_service_plans[n].isolation_split" in checklist, (
        "clarify-assemble.md checklist no longer names the fast-path isolation list entry"
    )


def test_db_cutover_unknown_size_branch() -> None:
    for f in (CLARIFY_DATABASE, SCHEMA_PREFS):
        text = _read(f)
        assert "size_coverage" in text and "largest_relational_db_gib" in text, (
            f"{f.name}: the unknown/partial-size db_cutover branch (size_coverage, "
            f"largest_relational_db_gib) is gone"
        )
        assert '"unknown"' in text, f"{f.name}: size_coverage no longer documents the unknown value"
    qd2 = _section(_read(CLARIFY_DATABASE), "### Q-D2", "### Q-D3")
    assert "100 GiB" in qd2 and "inclusive" in qd2, (
        "clarify-database.md Q-D2 no longer states the inclusive 100 GiB boundary"
    )
    assert "database cutover when a relational database is present" not in _read(DISCOVER_ASSEMBLE), (
        "discover-assemble.md still lists database cutover among the ESSENTIAL rows the "
        "fast path asks; it is PROPOSED-and-deferred"
    )


def test_workshop_patch_updates_default_index() -> None:
    patch = _section(_read(WORKSHOP_REFRESH), "### 3. Patch preferences", "### 4")
    assert "questions_defaulted" in patch and "user_corrected" in patch, (
        "workshop-refresh.md § 3 no longer applies the correction provenance "
        "(source: user_corrected + removal from metadata.questions_defaulted)"
    )
    sheet = _read(WORKSHOP_SHEET)
    assert "questions_defaulted" in sheet, (
        "workshop-sheet.md no longer reads metadata.questions_defaulted for provenance"
    )
    # The default label is keyed on the Clarify mode (wizard runs list rows the user
    # confirmed on the sheet), and a gate/sidebar correction is not a "Clarify answer".
    assert "clarify_mode" in sheet and "user_corrected" in sheet, (
        "workshop-sheet.md provenance column no longer keys the default label on "
        "metadata.clarify_mode or no longer distinguishes source: user_corrected"
    )
    step2 = _section(_read(ESTIMATE_ASSEMBLE), "## Step 2", "## Step 3")
    assert "workshop-refresh.md" in step2 and "user_corrected" in step2, (
        "estimate-assemble.md Step 2 no longer cites the sidebar's provenance contract"
    )
    # Correcting the deferred row from the assumptions block is its confirmation: the
    # direct route must apply the Step 3b write, not leave deferred_to_generate: true.
    assert "user_confirmed_at_generate" in step2 and "deferred_to_generate: false" in step2, (
        "estimate-assemble.md Step 2 direct-correction route leaves a deferred row flagged "
        "deferred (Part 4 would label the user's answer 'assumed' and Step 3b re-ask it)"
    )


def test_step3b_clears_all_deferral_state() -> None:
    text = _read(ESTIMATE_ASSEMBLE)
    step3b = _section(text, "### Step 3b", "### Scenario reconciliation")
    assert "deferred_to_generate: false" in step3b, (
        "estimate-assemble.md Step 3b no longer clears the row flag"
    )
    assert "questions_defaulted" in step3b, (
        "estimate-assemble.md Step 3b no longer removes the key from questions_defaulted"
    )
    assert "Part 4" in step3b and "Part 7 one-off" not in step3b, (
        "estimate-assemble.md Step 3b reprices the wrong section (Part 7 is complexity tier; "
        "the migration-cost line is Part 4)"
    )
    assert "user_stated_size_gib" in step3b and '"unknown"' in step3b, (
        "estimate-assemble.md Step 3b lost the unknown-size prompt variant"
    )
    part4 = _section(_read(ESTIMATE_INFRA), "## Part 4", "## Part 5")
    assert "user_confirmed_at_generate" in part4 and "deferred_to_generate: false" in part4, (
        "estimate-infra.md Part 4 no longer labels a confirmed cutover answer differently "
        "from the assumed default"
    )
    fm = _frontmatter(_read(GENERATE))
    assert "deferred_to_generate: true" in fm, (
        "generate.md precondition no longer checks the row flag alongside the metadata list"
    )


def test_gate_mutations_reconcile_scenarios() -> None:
    text = _read(ESTIMATE_ASSEMBLE)
    assert "### Scenario reconciliation" in text, (
        "estimate-assemble.md has no Scenario reconciliation section"
    )
    recon = _section(text, "### Scenario reconciliation", "### Step 3a")
    for anchor in ("active_scenario_id", "stale: true", "stale_reason", "corrected_at_gate"):
        assert anchor in recon, f"estimate-assemble.md § Scenario reconciliation lost `{anchor}`"
    step2 = _section(text, "## Step 2", "## Step 3")
    assert "Scenario reconciliation" in step2, (
        "estimate-assemble.md: the direct-correction route no longer triggers reconciliation"
    )
    # Step 3b rewrites provenance and the Part 4 label on every confirmation, so § 4 needs
    # reconciliation on every write — not only when the answer changed the estimate.
    step3b = _section(text, "### Step 3b", "### Scenario reconciliation")
    assert "Scenario reconciliation" in step3b and "answer changed the estimate" not in step3b, (
        "estimate-assemble.md Step 3b triggers reconciliation only when the answer changed "
        "the estimate; an unchanged answer still drifts the active snapshot"
    )
    for f in (WORKSHOP_COMPARE, SCHEMA_SCENARIOS, REPORT_CORE):
        assert "stale" in _read(f), f"{f.name} no longer renders/documents the stale marker"
    assert "stale" in _read(WORKSHOP_REFRESH), (
        "workshop-refresh.md no longer documents the manifest fields written outside the sidebar"
    )


def _load_asserter():
    spec = importlib.util.spec_from_file_location("check_expected_clarify", ASSERTER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("sizes_mb", "expected"),
    [
        ([102400], ("dump_restore", "complete")),  # exactly 100 GiB: inclusive
        ([102401], ("dms", "complete")),  # one MB over: dms
        ([65536], ("dump_restore", "complete")),
        ([None], ("dump_restore", "unknown")),
        ([], ("dump_restore", "unknown")),
        ([65536, None], ("dump_restore", "partial")),
        ([204800, None], ("dms", "partial")),
    ],
)
def test_db_cutover_rule_boundary(sizes_mb: list[int | None], expected: tuple[str, str]) -> None:
    mod = _load_asserter()
    assert mod.expected_db_cutover_default(sizes_mb) == expected


@pytest.mark.parametrize(
    ("golden", "spec"),
    [
        ("after-clarify", "expected-clarify.json"),
        ("after-clarify-complete", "expected-clarify-complete.json"),
        ("after-clarify-fast-path", "expected-clarify-fast-path.json"),
    ],
)
def test_clarify_goldens_pass(tmp_path: Path, golden: str, spec: str) -> None:
    # The asserter reads <run_dir>/preferences.json (and the inventory/clusters from the
    # run dir when present, else the Terraform corpus golden), so copy the golden dir.
    run_dir = tmp_path / golden
    shutil.copytree(FIXTURE / golden, run_dir)
    result = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
        [sys.executable, str(ASSERTER), str(run_dir), spec],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{spec} failed against {golden}:\n{result.stdout}{result.stderr}"
