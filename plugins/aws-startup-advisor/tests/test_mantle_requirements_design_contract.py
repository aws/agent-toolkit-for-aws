"""Guard: Design derives mantle_selector from Clarify's answer and discloses the runtime assumption.

PR #585 made `bedrock-runtime` the default endpoint and defined the `mantle_selector` enum, but
nothing told Design where a selector comes from: a plugin reading Terraform or no source code at
all cannot see whether an app needs background inference (`bedrock-runtime` rejects
`background=true` with a 400 — https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
read 2026-11-07), provider-run tools, Projects/Workspaces or single-Region processing. Discover
now records code-visible signals, Clarify confirms them or asks (Q22b / Q10.5) and writes
`preferences.json → ai_constraints.mantle_requirements`, and Design derives every
`bedrock_models[].mantle_selector` from that field alone (plus the catalog for
`mantle_only_model_or_api`), citing the entry in `mantle_requirement` and writing the verbatim
`endpoint_assumption` sentence on every runtime row. These checks pin the Design/Generate/report
text, the three schema docs and their vendored copies, and the neutral design fixtures.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"

DESIGN_AI_FILES = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md",
}
SCHEMA_DOCS = {
    "shared": SKILLS / "shared" / "ai" / "schema-design-aws-ai.md",
    "gcp-shadow": SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-design-aws-ai.md",
    "azure-shadow": SKILLS / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md",
    "gcp-vendored": SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
    "azure-vendored": SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
}
GENERATE_FILES = {
    "gcp-artifacts": SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md",
    "azure-artifacts": SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md",
    "gcp-guide": SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md",
}
LLM_TO_BEDROCK_SKILL = SKILLS / "llm-to-bedrock" / "SKILL.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"
DESIGN_FIXTURES = sorted((PLUGIN_ROOT / "fixtures" / "aws-design-ai").glob("*/aws-design-ai.json"))

SELECTOR_ENUM = [
    "background_inference",
    "server_side_tools",
    "web_search",
    "projects",
    "workspaces",
    "mantle_only_model_or_api",
    "in_region_processing",
]
ASSUMPTION_PREFIX = "No Mantle-only requirement was recorded for "
ASSUMPTION_SUFFIX = "re-run Clarify."
REQUIREMENT_SOURCES = {"detected", "user", "catalog"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


# --------------------------------------------------------------------------- (a) design-ai.md


@pytest.mark.parametrize("skill", sorted(DESIGN_AI_FILES))
def test_design_ai_derives_the_selector_from_clarify_and_discloses_the_runtime_assumption(skill: str) -> None:
    text = _read(DESIGN_AI_FILES[skill])
    assert "Step 0.8" in text, f"{skill}: design-ai.md has no Step 0.8 endpoint-selection step"
    for token in (
        "ai_constraints.mantle_requirements",
        "mantle_requirement",
        "endpoint_assumption",
        ASSUMPTION_PREFIX.strip(),
        "re-run Clarify",
    ):
        assert token in text, f"{skill}: design-ai.md lacks {token!r}"
    step08 = _section(text, "Step 0.8", "## Part 1")
    assert "mantle_only_model_or_api" in step08 and "catalog" in step08, (
        f"{skill}: Step 0.8 must say mantle_only_model_or_api is catalog-derived"
    )
    assert "in_region_processing" in step08 and "ai-openai-to-bedrock.md" in step08, (
        f"{skill}: Step 0.8 must keep in_region_processing on the CRIS-only gate"
    )


# --------------------------------------------------------------------------- (b) schema docs


@pytest.mark.parametrize("doc", sorted(SCHEMA_DOCS))
def test_schema_docs_document_mantle_requirement_and_endpoint_assumption(doc: str) -> None:
    text = _read(SCHEMA_DOCS[doc])
    assert "mantle_requirement" in text, f"{doc}: schema doc lacks mantle_requirement"
    assert "endpoint_assumption" in text, f"{doc}: schema doc lacks endpoint_assumption"
    assert re.search(r"detected\s*\|\s*user\s*\|\s*catalog", text), (
        f"{doc}: schema doc lacks the mantle_requirement.source vocabulary detected | user | catalog"
    )
    for value in SELECTOR_ENUM:
        assert value in text, f"{doc}: mantle_selector enum value {value} missing"


def test_vendored_schema_docs_are_byte_identical_to_the_canonical() -> None:
    canonical = SCHEMA_DOCS["shared"].read_bytes()
    for key in ("gcp-vendored", "azure-vendored"):
        assert SCHEMA_DOCS[key].read_bytes() == canonical, f"{key} drifted — run tools/sync-vendored.py"


# --------------------------------------------------------------------------- (c) generate


@pytest.mark.parametrize("doc", sorted(GENERATE_FILES))
def test_generate_echoes_the_requirement_or_the_assumption(doc: str) -> None:
    text = _read(GENERATE_FILES[doc])
    assert "endpoint_assumption" in text, f"{doc}: generate file does not echo endpoint_assumption"
    assert "mantle_requirement" in text, f"{doc}: generate file does not echo mantle_requirement"


# --------------------------------------------------------------------------- (d) llm-to-bedrock


def test_llm_to_bedrock_skill_explains_how_a_mantle_requirement_is_learned() -> None:
    text = _read(LLM_TO_BEDROCK_SKILL)
    policy = _section(text, "## Endpoint policy (bedrock-runtime default)", "## Phase A")
    for token in ("ai_constraints.mantle_requirements", "Q22b", "Q10.5", "mantle_signals", "mantle_requirement", "endpoint_assumption"):
        assert token in policy, f"llm-to-bedrock Endpoint policy lacks {token!r}"
    context = _section(text, "### The context block", "### C0 — Run-context gate")
    assert "Endpoint basis:" in context, "context block has no 'Endpoint basis:' line"
    assert "C6" in context.split("Endpoint basis:")[1][:400], "Endpoint basis line must scope itself to the C6 dispatch"
    b1 = _section(text, "### B1 — Read Assess outputs", "### B2")
    assert "mantle_requirement" in b1 and "endpoint_assumption" in b1, "B1 must extract both fields from bedrock_models[]"


def test_report_generator_renders_the_endpoint_and_reads_the_endpoint_basis_line() -> None:
    text = _read(REPORT_GENERATOR)
    assert "**Endpoint:**" in text, "report Executive Summary has no Endpoint line"
    assert "Endpoint basis:" in text, "report generator does not read the Endpoint basis: context line"
    assert "endpoint_assumption" in text and "mantle_requirement" in text
    limitations = _section(text, "## Limitations", "### Evaluation methodology disclosure")
    assert "inference-responses-api.html" in limitations and re.search(r"read 20\d\d-\d\d-\d\d", limitations), (
        "Limitations must cite the public Responses API page with a read date"
    )


# --------------------------------------------------------------------------- (e) fixtures


def _workloads_for(design: dict, source_model_id: str) -> set[str]:
    return {b["workload_id"] for b in design["design_blocks"] if b["model_id"] == source_model_id}


@pytest.mark.parametrize("fixture", DESIGN_FIXTURES, ids=lambda p: p.parent.name)
def test_fixture_rows_carry_a_requirement_or_the_assumption(fixture: Path) -> None:
    design = json.loads(_read(fixture))
    workload_ids = {b["workload_id"] for b in design["design_blocks"]}
    rows = design["ai_architecture"]["bedrock_models"]
    assert rows, f"{fixture}: no bedrock_models rows"
    for row in rows:
        label = f"{fixture.parent.name}:{row['aws_model_id']}"
        if row["migration_path"].startswith("mantle_"):
            assert "endpoint_assumption" not in row, f"{label}: mantle row must not carry endpoint_assumption"
            req = row.get("mantle_requirement")
            assert isinstance(req, dict), f"{label}: mantle row lacks mantle_requirement"
            assert set(req) <= {"workload_id", "selector", "source", "evidence", "region"}, f"{label}: unknown key in mantle_requirement"
            assert req["selector"] == row["mantle_selector"], f"{label}: mantle_requirement.selector != mantle_selector"
            assert req["source"] in REQUIREMENT_SOURCES, f"{label}: bad mantle_requirement.source"
            assert req["workload_id"] in workload_ids | {"*"}, f"{label}: mantle_requirement.workload_id is not a design_blocks id"
            if req["source"] in {"detected", "catalog"}:
                assert req.get("evidence"), f"{label}: {req['source']} requirement needs evidence"
            assert ("region" in req) == (req["selector"] == "in_region_processing"), (
                f"{label}: region must be present iff selector is in_region_processing"
            )
            assert (req["source"] == "catalog") == (req["selector"] == "mantle_only_model_or_api"), (
                f"{label}: source catalog iff selector mantle_only_model_or_api"
            )
        else:
            assert "mantle_requirement" not in row, f"{label}: runtime row must not carry mantle_requirement"
            sentence = row.get("endpoint_assumption")
            assert isinstance(sentence, str), f"{label}: runtime row lacks endpoint_assumption"
            assert sentence.startswith(ASSUMPTION_PREFIX), f"{label}: endpoint_assumption has the wrong prefix"
            assert sentence.endswith(ASSUMPTION_SUFFIX), f"{label}: endpoint_assumption has the wrong suffix"
            named = sentence[len(ASSUMPTION_PREFIX):].split(";", 1)[0]
            named_ids = {w.strip() for w in named.split(",")}
            expected = _workloads_for(design, row["source_model_id"])
            assert named_ids and named_ids <= expected, (
                f"{label}: endpoint_assumption names {named_ids}, not a workload whose model_id is {row['source_model_id']!r}"
            )


# --------------------------------------------------------------------------- (f) corpus coverage


def test_fixture_corpus_covers_a_detected_web_search_row_and_a_runtime_only_design() -> None:
    detected_web_search = False
    runtime_only = False
    for fixture in DESIGN_FIXTURES:
        rows = json.loads(_read(fixture))["ai_architecture"]["bedrock_models"]
        for row in rows:
            req = row.get("mantle_requirement") or {}
            if (
                row["migration_path"] == "mantle_openai_responses"
                and row.get("mantle_selector") == "web_search"
                and req.get("source") == "detected"
            ):
                detected_web_search = True
        if rows and not any(r["migration_path"].startswith("mantle_") for r in rows):
            runtime_only = True
    assert detected_web_search, "no fixture row is mantle_openai_responses + web_search + source detected"
    assert runtime_only, "no fixture has only runtime rows (runtime-default-no-requirement)"
