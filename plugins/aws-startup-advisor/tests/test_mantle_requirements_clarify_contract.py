"""Guard: Clarify asks the Mantle-only requirements and persists them.

PR #585 made `bedrock-runtime` the default endpoint and defined the seven-value
`mantle_selector` enum that every `bedrock-mantle` design row must record, but
nothing populated it: Discover can only see five selectors in code, Terraform or
billing-only runs scan no code at all, and `in_region_processing` is never
code-detectable. Design therefore had no user-confirmed input to choose an
endpoint from. The fix adds one question block — full-flow `Q22b` (gcp-to-aws and
azure-to-aws `clarify-ai.md`) and AI-only `Q10.5` (gcp-to-aws, azure-to-aws and
bedrock-migration-assessment `clarify-ai-only.md`) — that prefills Discover's
`mantle_signals` for confirmation or asks outright, and writes the answer as the
wrapper constraint `ai_constraints.mantle_requirements`.

Public source for the one hard capability gap the question names:
`bedrock-runtime` rejects `background=true` with a 400
(https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
read 2026-11-07).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"

GCP_CLARIFY_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-ai.md"
GCP_CLARIFY_AI_ONLY = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-ai-only.md"
GCP_CLARIFY_ASSEMBLE = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-assemble.md"
AZURE_CLARIFY_AI = SKILLS / "azure-to-aws" / "references" / "phases" / "clarify" / "clarify-ai.md"
AZURE_CLARIFY_AI_ONLY = SKILLS / "azure-to-aws" / "references" / "phases" / "clarify" / "clarify-ai-only.md"
BMA_CLARIFY_AI_ONLY = SKILLS / "bedrock-migration-assessment" / "references" / "phases" / "clarify" / "clarify-ai-only.md"
GCP_PREFERENCES_SCHEMA = SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-preferences.md"
BMA_PREFERENCES_SCHEMA = SKILLS / "bedrock-migration-assessment" / "references" / "shared" / "schema-preferences.md"
BMA_RUN_FIXTURE = PLUGIN_ROOT / "fixtures" / "bma-ai-only-clarify" / "preferences.json"

CLARIFY_FILES = [GCP_CLARIFY_AI, GCP_CLARIFY_AI_ONLY, AZURE_CLARIFY_AI, AZURE_CLARIFY_AI_ONLY, BMA_CLARIFY_AI_ONLY]

CONSTRAINT = "ai_constraints.mantle_requirements"
ENTRY_KEYS = {"workload_id", "selector", "source", "evidence", "region"}
# The seven policy values (tests/test_endpoint_policy_contract.py) minus the one Design derives, plus the explicit "none".
CLARIFY_SELECTORS = {"background_inference", "server_side_tools", "web_search", "projects", "workspaces",
                     "in_region_processing", "none"}
SOURCES = {"detected", "user", "none"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _question_sections(path: Path) -> dict[str, str]:
    # Same slicing as tests/test_bedrock_migration_assessment_core.py so the parity rules apply unchanged.
    text = _read(path)
    parts = re.split(r"^## (Q[0-9.]+) — .*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    for qid, body in sections.items():
        sections[qid] = re.split(r"^(?:### Batch|## Step )", body, flags=re.M)[0]
    return sections


def _interpret_lines(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("Interpret →")]


def _table_rows(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("| ") and not line.startswith("| ---")]


def _check_entries(entries: list[dict]) -> None:
    assert entries, "mantle_requirements.value must carry at least one entry"
    for entry in entries:
        assert set(entry) <= ENTRY_KEYS, entry
        assert {"workload_id", "selector", "source"} <= set(entry), entry
        assert entry["selector"] in CLARIFY_SELECTORS, entry
        assert entry["source"] in SOURCES, entry
        assert ("region" in entry) == (entry["selector"] == "in_region_processing"), entry


# --------------------------------------------------------------------------- (a) every clarify file asks the block

@pytest.mark.parametrize("path", CLARIFY_FILES, ids=lambda p: f"{p.parts[-5]}/{p.name}")
def test_every_clarify_file_asks_the_mantle_only_requirements(path: Path) -> None:
    text = _read(path)
    assert re.search(r"Mantle-only requirements", text), path
    for word in ("asynchronous", "server-side", "Projects", "Workspaces", "Region"):
        assert word in text, (path, word)
    assert CONSTRAINT in text, path


# --------------------------------------------------------------------------- (b) gcp and BMA Q10.5 stay in parity

def test_q10_5_interpret_line_is_identical_and_names_the_full_vocabulary() -> None:
    gcp = _question_sections(GCP_CLARIFY_AI_ONLY)
    bma = _question_sections(BMA_CLARIFY_AI_ONLY)
    assert list(gcp) == list(bma)
    assert list(gcp).index("Q10.5") == list(gcp).index("Q10") + 1
    assert list(gcp).index("Q11") == list(gcp).index("Q10.5") + 1
    gcp_interpret = _interpret_lines(gcp["Q10.5"])
    assert gcp_interpret == _interpret_lines(bma["Q10.5"])
    assert len(gcp_interpret) == 1
    line = gcp_interpret[0]
    assert line.startswith(f"Interpret → `{CONSTRAINT}`")
    for selector in CLARIFY_SELECTORS:
        assert selector in line, selector
    assert "`detected | user | none`" in line
    assert _table_rows(gcp["Q10.5"]) == _table_rows(bma["Q10.5"])
    assert "_Skip when:_" not in bma["Q10.5"]
    assert "_Never skipped:_" in bma["Q10.5"]
    assert "mantle_signals_detected" in bma["Q10.5"]
    assert "workloads[].mantle_signals" in gcp["Q10.5"]


# --------------------------------------------------------------------------- (c) full flow wiring

def test_full_flow_files_wire_q22b() -> None:
    gcp = _read(GCP_CLARIFY_AI)
    assert re.search(r"^## Q22b — Mantle-only requirements", gcp, flags=re.M)
    assert gcp.index("## Q22 — ") < gcp.index("## Q22b — ") < gcp.index("## Category G")
    assert "**Mantle-only signals:**" in gcp
    assert f"## Preferences Output — `{CONSTRAINT}`" in gcp
    assert '"question_id": "Q22b"' in gcp
    assert "5 global questions (Q14, Q15, Q22b, framework, spend)" in gcp

    azure = _read(AZURE_CLARIFY_AI)
    assert "**Q22b — Mantle-only requirements.**" in azure
    assert '"mantle_requirements": { "disposition": "ESSENTIAL"' in azure
    assert f"| `{CONSTRAINT}`" in azure

    assemble = _read(GCP_CLARIFY_ASSEMBLE)
    assert "then AI/agentic (Q15, Q22b, Q23–Q25" in assemble
    assert "- Q22b (Mantle-only requirements) defaults to the single entry" in assemble
    assert '`source: "default:Q22b"`' in assemble
    assert "| Q22b — Mantle-only requirements |" in assemble


def test_ai_only_fast_paths_list_q10_5() -> None:
    gcp = _read(GCP_CLARIFY_AI_ONLY)
    assert "Present **only Q1.5, Q2, Q3, Q4, Q10.5, Q11**" in gcp
    assert "Q10.5 (Mantle-only requirements) and Q11 (Activate status) are never dropped" in gcp
    azure = _read(AZURE_CLARIFY_AI_ONLY)
    assert "present ONLY Q1.5, Q2, Q3, Q4, Q10.5, Q11" in azure
    assert "**Q10.5 — Mantle-only requirements**" in azure
    assert "`mantle_requirements` (Q10.5)" in azure


# --------------------------------------------------------------------------- (d) the preferences catalogs know the field

def test_preferences_catalogs_list_the_field_with_its_question_ids() -> None:
    bma = _read(BMA_PREFERENCES_SCHEMA)
    table = bma[bma.index("## Constraint catalog"):bma.index("## Validation")]
    catalog = {key: (section, qid) for key, section, qid in
               re.findall(r"^\| `([a-z_]+)`\s*\| `([a-z_]+)`\s*\| ([^|]+?)\s*\|", table, flags=re.M)}
    assert catalog["mantle_requirements"] == ("ai_constraints", "Q10.5")

    gcp = _read(GCP_PREFERENCES_SCHEMA)
    table = gcp[gcp.index("## Constraint catalog"):gcp.index("## Report consumption")]
    rows = dict(re.findall(r"^\| `([a-z_]+)`\s*\| ([^|]+?)\s*\|", table, flags=re.M))
    assert rows["mantle_requirements"] == "Q22b (AI-only: Q10.5)"
    assert "`ai_constraints.mantle_requirements`" in _read(GCP_CLARIFY_AI_ONLY)


# --------------------------------------------------------------------------- (e) the BMA run fixture records a valid answer

def test_bma_run_fixture_records_a_valid_mantle_requirements_answer() -> None:
    preferences = json.loads(_read(BMA_RUN_FIXTURE))
    row = preferences["ai_constraints"]["mantle_requirements"]
    _check_entries(row["value"])
    assert row["question_id"] == "Q10.5"
    assert row["chosen_by"] in {"user", "default"}
    assert row["chosen_by"] != "extracted"
    if row["chosen_by"] == "default":
        assert row["source"] == "default:Q10.5"
        assert "Mantle-only requirements were not confirmed by the user" in " ".join(
            preferences["metadata"].get("report_caveats", []))
        assert "Q10.5" in preferences["metadata"]["questions_defaulted"]
    else:
        assert "Q10.5" in preferences["metadata"]["questions_asked"]


# --------------------------------------------------------------------------- (f) the azure AI-only example documents the same entry shape

def _azure_ai_only_example() -> dict:
    # Same parse as tests/test_validate_artifacts.py::_ai_only_preferences_example (strip ` //` tails, json-load).
    doc = _read(AZURE_CLARIFY_AI_ONLY)
    m = re.search(r"## preferences\.json \(AI-only\)\s*```jsonc\n(.*?)\n```", doc, re.S)
    lines = []
    for line in m.group(1).split("\n"):
        idx = line.find(" //")
        lines.append(line[:idx] if idx != -1 else line)
    return json.loads("\n".join(lines))


def test_azure_ai_only_example_documents_the_entry_shape() -> None:
    row = _azure_ai_only_example()["ai_constraints"]["mantle_requirements"]
    _check_entries(row["value"])
    assert row["question_id"] == "Q10.5"
    selectors = {entry["selector"] for entry in row["value"]}
    assert "in_region_processing" in selectors, "the example must show the `region` key so the shape contract accepts it"


# --------------------------------------------------------------------------- (g) Clarify never writes the Design-derived selector

@pytest.mark.parametrize("path", CLARIFY_FILES, ids=lambda p: f"{p.parts[-5]}/{p.name}")
def test_clarify_leaves_mantle_only_model_or_api_to_design(path: Path) -> None:
    for line in _read(path).splitlines():
        if "mantle_only_model_or_api" in line:
            assert "Design" in line or "derive" in line, line
