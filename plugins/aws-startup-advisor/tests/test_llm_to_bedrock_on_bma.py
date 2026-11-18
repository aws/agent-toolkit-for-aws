"""llm-to-bedrock runs its Assess phase with bedrock-migration-assessment (issue #389, stage 3b).

Three contracts:

(a) llm-to-bedrock requires bedrock-migration-assessment, and no longer resolves gcp-to-aws or
    azure-to-aws as its Assess skill.
(b) It consumes the assessment only through that skill's readiness handshake
    (`scripts/readiness.py ... --through estimate`), never reads the assessment run's
    `.phase-status.json` for its own decisions, and never writes into that run.
(c) End to end: a bedrock-migration-assessment fixture run passes readiness, and every field
    llm-to-bedrock's Phase B and its analyzer and report agents say they read exists in that
    run's artifacts, in the shape bedrock-migration-assessment's contracts declare.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
L2B = SKILLS / "llm-to-bedrock"
BMA = SKILLS / "bedrock-migration-assessment"
SKILL_MD = L2B / "SKILL.md"
ANALYZER = PLUGIN_ROOT / "agents" / "llm2bedrock-code-analyzer.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"
FIXTURES = PLUGIN_ROOT / "fixtures"
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"

TEXT = SKILL_MD.read_text(encoding="utf-8")
FLAT = " ".join(TEXT.split())


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.:])\s+(?=[A-Z*`(-])", _flat(text)) if s]


# --------------------------------------------------------------------------- (a) BMA is the Assess skill

def test_description_and_intro_require_bedrock_migration_assessment() -> None:
    description = re.search(r'^description: "(.*)"$', TEXT, re.MULTILINE).group(1)
    assert "REQUIRES bedrock-migration-assessment installed alongside this skill" in description
    assert "gcp-to-aws" not in description and "azure-to-aws" not in description
    intro = _flat(_section(TEXT, "# Migrate to Bedrock", "## Optional usage telemetry"))
    assert "Requires the `bedrock-migration-assessment` skill installed alongside this one." in intro
    assert "`$BMA_BASE` = `<SKILL_BASE>/../bedrock-migration-assessment`" in intro


def test_step_0b_checks_for_bedrock_migration_assessment_and_stops_without_it() -> None:
    step = _flat(_section(TEXT, "### 0b.", "## Step 1 — Collect source code path"))
    assert '[ -f "<SKILL_BASE>/../bedrock-migration-assessment/SKILL.md" ]' in step
    assert '[ -f "<SKILL_BASE>/../bedrock-migration-assessment/scripts/readiness.py" ]' in step
    assert "BMA_MISSING" in step and "**stop here. Do not proceed.**" in step
    assert "--skill llm-to-bedrock --skill bedrock-migration-assessment" in step
    assert "gcp-to-aws" not in step and "azure-to-aws" not in step


def test_no_assess_sibling_variables_remain() -> None:
    files = [SKILL_MD, ANALYZER, REPORT_GENERATOR, *sorted((L2B / "references" / "helpers").rglob("*.md"))]
    files += sorted((PLUGIN_ROOT / "agents").glob("llm2bedrock-*.md"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in ("$ASSESS_SKILL", "$ASSESS_BASE", "ASSESS_SIBLING_MISSING", "gcp-to-aws/references",
                      "azure-to-aws/references"):
            assert token not in text, f"{path.relative_to(PLUGIN_ROOT)} still names {token}"


# Each remaining mention of gcp-to-aws / azure-to-aws in llm-to-bedrock's instructions, with why
# it stays. Anything else is the old Assess coupling coming back.
ALLOWED_INFRA_SKILL_MENTIONS = {
    # A1: a run another skill created is not reused; the user reruns Assess with BMA.
    "A run directory made by another skill (a gcp-to-aws or azure-to-aws assessment, for example) is not reused",
}


def test_gcp_and_azure_are_never_named_as_the_assess_path() -> None:
    files = [SKILL_MD, *sorted((L2B / "references" / "helpers").rglob("*.md")),
             *sorted((PLUGIN_ROOT / "agents").glob("llm2bedrock-*.md"))]
    for path in files:
        for sentence in _sentences(path.read_text(encoding="utf-8")):
            if re.search(r"\b(gcp|azure)-to-aws\b", sentence):
                assert any(ok in sentence for ok in ALLOWED_INFRA_SKILL_MENTIONS), (
                    f"{path.relative_to(PLUGIN_ROOT)} names an infrastructure skill: {sentence[:200]}")


def test_phase_a_executes_bedrock_migration_assessment_files() -> None:
    a1 = _flat(_section(TEXT, "### A1 — Run Discover, Clarify, Design, and Estimate", "### A2"))
    assert "**Load `$BMA_BASE/SKILL.md`**" in a1 and '"Step 0: Resume or start"' in a1
    for rel in ("references/phases/discover/discover.md", "references/phases/clarify/clarify-ai-only.md",
                "references/phases/design/design-ai.md", "references/phases/estimate/estimate-ai.md"):
        assert f"`$BMA_BASE/{rel}`" in a1, rel
        assert (BMA / rel).is_file(), rel
    assert "**Stop after Estimate.**" in a1


def test_guide_and_endpoint_pointers_name_the_assessment_skills_copies() -> None:
    assert "`$BMA_BASE/references/vendored/ai/bedrock-endpoint-policy.md`" in TEXT
    assert "`$BMA_BASE/references/shared/openai-on-bedrock.md`" in TEXT
    assert (BMA / "references/vendored/ai/bedrock-endpoint-policy.md").is_file()
    assert (BMA / "references/shared/openai-on-bedrock.md").is_file()
    resolver = (L2B / "references/helpers/resolve-bedrock-model-id/resolve-bedrock-model-id.md").read_text(encoding="utf-8")
    assert resolver.count("`skills/bedrock-migration-assessment/references/shared/openai-on-bedrock.md`") == 3


# --------------------------------------------------------------------------- (b) readiness handshake only

READINESS = 'python3 "$BMA_BASE/scripts/readiness.py" "$MIGRATION_DIR" --through estimate'
# The heading itself, at the start of a line: Step 1.5 quotes the heading text in prose.
A3_HEADING = "\n### A3 — Locate Assess output"


def _readiness_reasons() -> set[str]:
    """Every reason readiness.py can return: the first argument of each NotReady(...) and the
    missing/unreadable reasons passed to _json(...)."""
    import ast
    tree = ast.parse((BMA / "scripts" / "readiness.py").read_text(encoding="utf-8"))
    reasons = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if node.func.id == "NotReady":
                reasons.update(args[:1])
            elif node.func.id == "_json":
                reasons.update(args)
    return reasons


def test_a2_runs_readiness_through_estimate_and_stops_on_any_non_ready_answer() -> None:
    a2 = _flat(_section(TEXT, "### A2 — Confirm Assess is complete (readiness handshake)", "### A3"))
    assert READINESS in a2
    assert '"Readiness for other skills"' in a2
    assert '**Exit 0, `"ready": true`** → continue to A3.' in a2
    assert "`artifacts.<file>.sha256`" in a2
    assert '**Exit 1, `"ready": false`**' in a2 and "→ **stop.**" in a2
    assert "tell them to resume the run with bedrock-migration-assessment" in a2
    # every reason the script can return is named, so none is treated as ready
    reasons = _readiness_reasons()
    assert {"status_not_found", "status_unreadable", "artifact_missing", "not_this_skill"} <= reasons, reasons
    assert len(reasons) == 12, reasons
    for reason in reasons:
        assert f"`{reason}`" in a2, reason
    assert "**Re-check before every later re-read.**" in a2 and "compare each printed `sha256`" in a2


def test_readiness_answer_and_hashes_are_recorded_in_this_skills_own_run() -> None:
    a3 = _flat(_section(TEXT, A3_HEADING, "## Phase B — Execute Prep"))
    assert "Write A2's readiness JSON, exactly as printed, to `$BEDROCK_RUN_DIR/assessment-readiness.json`" in a3
    assert "`migration_id`, `run_id`, and each artifact's `path` and `sha256`" in a3
    b1 = _flat(_section(TEXT, "### B1 — Read Assess outputs", "### B2"))
    assert b1.index("Run A2's readiness re-check first") < b1.index("Read `$MIGRATION_DIR/aws-design-ai.json`")


def test_the_assessment_runs_state_file_is_never_read_or_written_by_this_skill() -> None:
    for gone in ("State Validation", "phases.workshop", "Workshop guard", "$MIGRATION_DIR/.phase-status.json",
                 "HANDOFF_OK", "GATE_FAIL"):
        assert gone not in TEXT, gone
    # Outside A3 (which creates $BEDROCK_RUN_DIR/.phase-status.json), every sentence naming a
    # state file is one of these: a prohibition, this skill's own file, or
    # bedrock-migration-assessment's own updates while its phase files run.
    allowed = (
        "Never read a candidate's `.phase-status.json` yourself.",
        "its readiness check returns `not_this_skill` for any run whose `.phase-status.json` carries `owning_skill`.",
        "This skill also never reads that run's `.phase-status.json` to make its own decisions:",
        "including each step's own `.phase-status.json` updates.",
        "(read-merge-write on `$BEDROCK_RUN_DIR/.phase-status.json`):",
    )
    a3 = _section(TEXT, A3_HEADING, "## Phase B — Execute Prep")
    seen = set()
    for sentence in _sentences(TEXT.replace(a3, "")):
        if ".phase-status.json" in sentence:
            hits = [ok for ok in allowed if ok in sentence]
            assert hits, sentence[:200]
            seen.update(hits)
    assert seen == set(allowed), set(allowed) - seen


def test_nothing_is_written_into_the_assessment_run() -> None:
    phase_a = _flat(_section(TEXT, "## Phase A — Assess", "### A1"))
    assert ("So this skill never writes anything into `$MIGRATION_DIR` itself: no `owning_skill`, no `initiated_by`, "
            "no other field and no other file.") in phase_a
    assert '"initiated_by"' not in TEXT
    assert TEXT.count('"owning_skill"') == 1
    a3 = _section(TEXT, A3_HEADING, "## Phase B — Execute Prep")
    assert a3.index("Set `$BEDROCK_RUN_DIR`") < a3.index('"owning_skill": "LLM_TO_BEDROCK"')
    assert '"migration_id": ".bedrock-<id>"' in a3 and ".bedrock-bma-0910-1100" in a3


def test_step_1_5_identifies_prior_runs_with_readiness_not_their_state_file() -> None:
    step = _section(TEXT, "## Step 1.5", "## Phase A")
    assert '"*/.migration/bma-*/${p}-usage-profile.json"' in step
    assert 'python3 "$BMA_BASE/scripts/readiness.py" "<candidate run dir>" --through design' in step
    assert "Never read a candidate's `.phase-status.json` yourself." in _flat(step)
    assert "last_updated" not in step and "current_phase" not in step


# --------------------------------------------------------------------------- (c) end to end on a BMA run

# Every field llm-to-bedrock says it reads from a bedrock-migration-assessment run, by file.
# SKILL.md Phase B (B1, B4, C0, C5) and the analyzer (§6) read the design rows and the profile;
# the report generator (§6.4) reads the rows and the Mantle requirements in preferences.json.
DESIGN_ROW_FIELDS = ("source_model_id", "aws_model_id", "migration_path", "required_client_api")
DESIGN_RUNTIME_ROW_FIELDS = ("endpoint_assumption",)
DESIGN_MANTLE_ROW_FIELDS = ("mantle_selector", "mantle_requirement")
PROFILE_SOURCE_FIELDS = ("provider", "source_service", "models")
PROFILE_INTEGRATION_FIELDS = ("pattern", "frameworks", "capabilities_summary")
CAPABILITY_FLAGS = ("streaming", "function_calling", "embeddings", "vision")
MANTLE_REQUIREMENT_FIELDS = ("selector", "source")

READ_BY = {
    SKILL_MD: ["`source_model_id`", "`aws_model_id`", "`migration_path`", "`required_client_api`",
               "`endpoint_assumption`", "`mantle_selector`", "`mantle_requirement`", "`ai_sources[].provider`",
               "`ai_sources[].source_service`", "`design_constraints.target_region.value`"],
    ANALYZER: ['"source_model_id"', '"aws_model_id"', '"migration_path"', '"required_client_api"',
               "`ai_sources[].provider`", "`ai_sources[].source_service`", "`integration.pattern`",
               "`integration.frameworks[]`", "`integration.capabilities_summary`"],
    REPORT_GENERATOR: ["`source_model_id`", "`required_client_api`", "`mantle_selector`",
                       "`ai_constraints.mantle_requirements.value[]`"],
}


def test_the_documented_reads_are_the_fields_this_test_checks() -> None:
    for path, tokens in READ_BY.items():
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            assert token in text, f"{path.name} no longer says it reads {token}"
    analyzer = _flat(_section(ANALYZER.read_text(encoding="utf-8"), "# 6. Read the Assess output", "## 6.3"))
    assert "The source model is `source_model_id`" in analyzer and "read `source_model_id`, else `source_model`" in analyzer
    assert '"source_model":' not in analyzer and '"use_case":' not in analyzer, "the analyzer's example row is the BMA shape"
    assert "There is no `summary.ai_source`" in analyzer
    assert "`direct_sdk`, `framework`, `rest_api`, or `mixed`" in analyzer
    assert "`summary.ai_source` → source provider" not in TEXT


def test_the_fields_are_declared_by_the_assessment_contracts() -> None:
    spec_path = BMA / "scripts" / "design-ai.py"
    source = spec_path.read_text(encoding="utf-8")
    row_keys = re.search(r"ROW_KEYS = \((.*?)\)\n", source, re.S).group(1)
    for field in DESIGN_ROW_FIELDS:
        assert f'"{field}"' in row_keys, field
    for field in DESIGN_RUNTIME_ROW_FIELDS + DESIGN_MANTLE_ROW_FIELDS:
        assert f'"{field}"' in source, field
    profile = json.loads((BMA / "references/contracts/ai-workload-profile.schema.json").read_text(encoding="utf-8"))
    defs = profile["definitions"]
    assert set(PROFILE_SOURCE_FIELDS) <= set(defs["aiSource"]["properties"])
    assert set(PROFILE_INTEGRATION_FIELDS) <= set(defs["integration"]["properties"])
    assert defs["integration"]["properties"]["pattern"]["enum"] == ["direct_sdk", "framework", "rest_api", "mixed"]
    assert set(CAPABILITY_FLAGS) <= set(defs["integration"]["properties"]["capabilities_summary"]["properties"])
    assert "summary" not in profile["properties"], "the profile has no summary.ai_source"


def _run(tmp_path: Path, fixture: str) -> Path:
    run = tmp_path / ".migration" / "bma-1116-1900"
    run.mkdir(parents=True)
    for f in (FIXTURES / fixture).iterdir():
        if f.is_file():
            shutil.copy(f, run / f.name)
    # The state file bedrock-migration-assessment itself writes (discover.md Step 4): no owning_skill.
    (run / ".phase-status.json").write_text(json.dumps({
        "migration_id": "bma-1116-1900", "run_id": RUN_ID, "last_updated": "2026-11-16T19:00:00Z",
        "current_phase": "complete",
        "phases": {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed"}}))
    return run


def _readiness(run: Path, through: str = "estimate") -> tuple[int, dict]:
    # Exactly as SKILL.md runs it: the sibling skill's script, from $BMA_BASE.
    script = L2B / ".." / "bedrock-migration-assessment" / "scripts" / "readiness.py"
    out = subprocess.run([sys.executable, str(script), str(run), "--through", through],
                         cwd=run.parent.parent, capture_output=True, text=True, check=False)
    return out.returncode, json.loads(out.stdout)


FIXTURE_RUNS = ["bma-estimate-measured", "bma-estimate-price-unavailable", "bma-estimate-tier-high-volume"]


@pytest.mark.parametrize("fixture", FIXTURE_RUNS)
def test_a_bma_run_passes_readiness_and_has_every_field_llm_to_bedrock_reads(fixture, tmp_path: Path) -> None:
    code, ready = _readiness(_run(tmp_path, fixture))
    assert code == 0 and ready["ready"] is True and ready["run_id"] == RUN_ID, ready
    paths = {name: Path(entry["path"]) for name, entry in ready["artifacts"].items()}
    assert set(paths) == {"ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json"}

    design = json.loads(paths["aws-design-ai.json"].read_text())
    rows = design["ai_architecture"]["bedrock_models"]
    assert rows, "B1 stops on an empty bedrock_models[]"
    for row in rows:
        for field in DESIGN_ROW_FIELDS:
            assert field in row, (fixture, field)
        assert "source_model" not in row and "use_case" not in row
        if str(row["migration_path"]).startswith("mantle_"):
            for field in DESIGN_MANTLE_ROW_FIELDS:
                assert field in row, (fixture, field)
        else:
            for field in DESIGN_RUNTIME_ROW_FIELDS:
                assert field in row, (fixture, field)
    migration = design["ai_architecture"]["code_migration"]
    assert "migration_path" not in migration and "runtime_api" not in migration

    profile = json.loads(paths["ai-workload-profile.json"].read_text())
    assert "summary" not in profile
    assert profile["ai_sources"] and isinstance(profile["gateways"], list)
    for source in profile["ai_sources"]:
        for field in PROFILE_SOURCE_FIELDS:
            assert field in source, (fixture, field)
    # B1's source provider: the ai_sources[] entry whose models[] holds the primary chat row's model.
    primary = next(r for r in rows if r["required_client_api"] != "invoke")
    assert any(primary["source_model_id"] in s["models"] for s in profile["ai_sources"]), fixture
    if "integration" in profile:
        for field in PROFILE_INTEGRATION_FIELDS:
            assert field in profile["integration"], (fixture, field)
        assert profile["integration"]["pattern"] in {"direct_sdk", "framework", "rest_api", "mixed"}
        for flag in CAPABILITY_FLAGS:
            assert isinstance(profile["integration"]["capabilities_summary"][flag], bool)

    prefs = json.loads(paths["preferences.json"].read_text())
    region = prefs["design_constraints"]["target_region"]
    assert isinstance(region, dict) and isinstance(region["value"], str), "B1 reads target_region.value"
    for entry in prefs["ai_constraints"].get("mantle_requirements", {}).get("value", []):
        for field in MANTLE_REQUIREMENT_FIELDS:
            assert field in entry, (fixture, field)


def test_the_fixture_runs_cover_mantle_invoke_and_integration_shapes(tmp_path: Path) -> None:
    rows, integrations = [], []
    for fixture in FIXTURE_RUNS:
        rows += json.loads((FIXTURES / fixture / "aws-design-ai.json").read_text())["ai_architecture"]["bedrock_models"]
        integrations.append("integration" in json.loads((FIXTURES / fixture / "ai-workload-profile.json").read_text()))
    paths = {r["migration_path"] for r in rows}
    assert any(p.startswith("mantle_") for p in paths) and "runtime_openai_cris" in paths
    assert any(r["required_client_api"] == "invoke" for r in rows)
    assert any(integrations) and not all(integrations)


def test_lane_gate_and_resume_gate_accept_a_bma_design(tmp_path: Path) -> None:
    sys.path.insert(0, str(L2B / "scripts"))
    try:
        import preflight_bedrock
    finally:
        sys.path.pop(0)
    run = _run(tmp_path, "bma-estimate-measured")
    rows = json.loads((run / "aws-design-ai.json").read_text())["ai_architecture"]["bedrock_models"]
    assert preflight_bedrock.unsupported_lane_stop(rows) is None
    assert preflight_bedrock.design_row_identity(rows) == [("gpt-4o", "us.openai.gpt-5.6-terra")]


def test_a_run_another_skill_created_is_not_ready(tmp_path: Path) -> None:
    # If llm-to-bedrock wrote its old owning_skill / initiated_by attribution into the run,
    # readiness would refuse it: the reason the old instruction is gone.
    run = _run(tmp_path, "bma-estimate-measured")
    status = json.loads((run / ".phase-status.json").read_text())
    (run / ".phase-status.json").write_text(json.dumps({**status, "owning_skill": "LLM_TO_BEDROCK"}))
    code, out = _readiness(run)
    assert code == 1 and out["reason"] == "not_this_skill"


# --------------------------------------------------------------------------- chat-row choice and row role

def _chat_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not (r["migration_path"] == "direct" and r["required_client_api"] == "invoke")]


@pytest.mark.parametrize("fixture", ["bma-estimate-price-unavailable", "bma-design-openai-mantle-and-runtime"])
def test_one_source_model_with_two_chat_rows_makes_b1_ask_not_pick_the_first(fixture) -> None:
    rows = json.loads((FIXTURES / fixture / "aws-design-ai.json").read_text())["ai_architecture"]["bedrock_models"]
    chat = [r for r in _chat_rows(rows) if r["source_model_id"] == "gpt-5.5"]
    # The rows disagree: "first chat row" would move a Chat Completions workload onto Mantle Responses.
    assert {(r["migration_path"], r["required_client_api"]) for r in chat} == {
        ("mantle_openai_responses", "responses"), ("runtime_openai_cris", "chat_completions")}
    assert chat[0]["migration_path"] == "mantle_openai_responses"
    b1 = _flat(_section(TEXT, "### B1 — Read Assess outputs", "### B2"))
    assert "the first chat row is the primary chat row" not in b1
    assert 'Never take "the first chat row".' in b1
    assert ("If every chat row has the same `migration_path` and `required_client_api`, use them all; "
            "the first one is the primary chat row.") in b1
    assert "Otherwise **stop and AskUserQuestion** before B2." in b1
    for field in ("`source_model_id`", "`aws_model_id`", "`migration_path`", "`required_client_api`",
                  "`endpoint_assumption`", "`mantle_requirement.workload_id`"):
        assert field in b1.split("Otherwise **stop and AskUserQuestion**", 1)[1][:600], field
    assert "`$BEDROCK_RUN_DIR/chat-row-choice.json`" in b1
    c5 = _flat(_section(TEXT, "### C5 — Rewriter", "### C7"))
    assert "a source model appears exactly once; never list a second target for it" in c5
    # Review on #694: the code analyzer (C1) reads the whole design, so it must apply the same
    # row-role and chosen-row rules, or iam_policy.py grants the unchosen target.
    analyzer = _flat((PLUGIN_ROOT / "agents" / "llm2bedrock-code-analyzer.md").read_text(encoding="utf-8"))
    assert ("A row is an embedding or image row only when `migration_path` is `direct` and "
            "`required_client_api` is `invoke`") in analyzer
    assert "use only the row whose `required_client_api` equals the context's `Target API surface`" in analyzer
    assert "a row whose `required_client_api` is `invoke` is an embedding or image row" not in analyzer
    assert "except the unchosen second chat row for one source model" in analyzer


def test_a_row_is_embedding_or_image_only_on_direct_invoke_with_a_matching_capability() -> None:
    source = (BMA / "scripts" / "design-ai.py").read_text(encoding="utf-8")
    paths = re.search(r"PATH_CLIENT_APIS = \{(.*?)\n\}", source, re.S).group(1)
    # invoke is legal on two paths, so the API alone cannot mark a row as embedding/image.
    assert sorted(re.findall(r'"([a-z_-]+)": \{[^}]*"invoke"', paths)) == ["direct", "gpt-oss"]
    b1 = _flat(_section(TEXT, "### B1 — Read Assess outputs", "### B2"))
    assert ("A row is an embedding or image row only when `migration_path` is `direct` AND "
            "`required_client_api` is `invoke`") in b1
    assert "an embedding or image row lists `embedding` or `image_generation`" in b1
    assert "When the two signals disagree" in b1 and "stop and AskUserQuestion which role the row has" in b1
    for fixture in FIXTURE_RUNS:
        for row in json.loads((FIXTURES / fixture / "aws-design-ai.json").read_text())["ai_architecture"]["bedrock_models"]:
            direct_invoke = row["migration_path"] == "direct" and row["required_client_api"] == "invoke"
            capability = bool({"embedding", "image_generation"} & set(row["capabilities_matched"]))
            assert direct_invoke == capability, (fixture, row["aws_model_id"])
