"""gcp-to-aws runs its AI track in bedrock-migration-assessment: the handoff doc, the phase files that call it, and the inline callers."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
GCP = SKILLS / "gcp-to-aws"
BMA = SKILLS / "bedrock-migration-assessment"
HANDOFF_DOC = GCP / "references" / "shared" / "ai-handoff.md"
SCRIPT = GCP / "scripts" / "bma-handoff.py"
PHASES = GCP / "references" / "phases"
DELETED = ("clarify/clarify-ai.md", "clarify/clarify-ai-only.md", "design/design-ai.md", "estimate/estimate-ai.md",
           "generate/generate-ai.md", "generate/generate-artifacts-ai.md")


def _doc() -> str:
    return HANDOFF_DOC.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = re.search(r"^## ", rest, re.M)
    return text[start:start + len(heading) + (end.start() if end else len(rest))]


def _script():
    spec = importlib.util.spec_from_file_location("gcp_bma_handoff_doc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gcp_no_longer_ships_its_own_ai_phases() -> None:
    for rel in DELETED:
        assert not (PHASES / rel).exists(), rel
    assert not (GCP / "references" / "shared" / "schema-design-aws-ai.md").exists()


def test_no_gcp_file_names_a_deleted_ai_phase() -> None:
    names = [Path(rel).name for rel in DELETED] + ["schema-design-aws-ai.md"]
    for path in GCP.rglob("*.md"):
        if "vendored" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for name in names:
            for match in re.finditer(re.escape(name), text):
                before = text[max(0, match.start() - 120):match.start()]
                assert "<BMA_BASE>" in before or "bedrock-migration-assessment" in before, f"{path.relative_to(GCP)} names {name}"


# --------------------------------------------------------------------------- the route matrix

def _tree(tmp_path: Path, state: str) -> Path:
    root = tmp_path / "skills"
    (root / "gcp-to-aws" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "gcp-to-aws" / "scripts" / SCRIPT.name)
    if state != "absent":
        shutil.copytree(BMA, root / "bedrock-migration-assessment", ignore=shutil.ignore_patterns("__pycache__"))
    if state == "tampered":
        (root / "bedrock-migration-assessment" / "scripts" / "readiness.py").unlink()
    return root


def _route(tmp_path: Path, state: str, infra: bool, infra_only: bool) -> dict:
    root = _tree(tmp_path, state)
    run = tmp_path / ".migration" / "1119-2100"
    run.mkdir(parents=True)
    (run / "ai-workload-profile.json").write_text(json.dumps({"models": [{"model_id": "gemini-2.5-flash", "service": "vertex_ai_generative"}]}))
    if infra:
        (run / "gcp-resource-inventory.json").write_text(json.dumps({"resources": [{"type": "google_cloud_run_v2_service"}]}))
    args = [sys.executable, str(root / "gcp-to-aws" / "scripts" / SCRIPT.name), "route", str(run)] + (["--infra-only"] if infra_only else [])
    out = json.loads(subprocess.run(args, capture_output=True, text=True, timeout=120).stdout)
    return out


def _route_rows() -> dict[tuple[str, str], str]:
    table = _section(_doc(), "## Step 1: Route")
    rows = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`") and cells[0] != "`route`":
            key = (cells[0].strip("`"), cells[1].strip("`"))
            assert key not in rows, key
            rows[key] = cells[2]
    return rows


@pytest.mark.parametrize("state", ["present", "absent", "tampered"])
@pytest.mark.parametrize("infra", [True, False], ids=["infra", "ai-only"])
@pytest.mark.parametrize("infra_only", [False, True], ids=["default", "infra-only"])
def test_every_route_the_script_prints_has_exactly_one_row(state, infra, infra_only, tmp_path: Path) -> None:
    out = _route(tmp_path, state, infra, infra_only)
    rows = _route_rows()
    key = (out["route"], out.get("reason", "—"))
    assert key in rows, f"no row for {key}: {sorted(rows)}"
    action = rows[key]
    if out["route"] == "stop":
        assert "stop" in action.lower() and "`message`" in action
    if out["route"] == "defer":
        assert "deferred" in action and "`message`" in action and "Step 2" not in action
    if out["route"] == "delegate":
        assert "Step 2" in action


def test_the_route_table_has_no_row_the_script_cannot_print() -> None:
    rows = set(_route_rows())
    printable = {("no_ai", "—"), ("delegate", "—"), ("defer", "bma_absent"), ("defer", "bma_tampered"),
                 ("defer", "user_chose_infra_only"), ("stop", "bma_required"), ("stop", "bma_tampered")}
    assert rows == printable


def test_a_tampered_sibling_offers_infra_only_only_when_infrastructure_moves() -> None:
    row = _route_rows()[("stop", "bma_tampered")]
    assert "--infra-only" in row and "infrastructure" in row


# --------------------------------------------------------------------------- the handoff steps

def test_handoff_runs_the_script_commands_in_order() -> None:
    doc = _doc()
    order = ["handoff probe", "handoff route", "discover-app-code.md", "handoff convert", "<BMA_BASE>/SKILL.md",
             "handoff host-answers", "handoff accept"]
    positions = [doc.lower().index(step.lower()) for step in order]
    assert positions == sorted(positions), list(zip(order, positions))
    assert "--scan $MIGRATION_DIR/ai-workload-profile.scan.json" in doc
    assert "GCP_TO_AWS" in doc and "ai-workload-profile.neutral.json" in doc


def test_handoff_defines_both_bases_from_paths_that_survive_inline_runs() -> None:
    paths = _section(_doc(), "## Paths")
    assert "`<BMA_BASE>`" in paths and "`bma_base`" in paths and "absolute" in paths
    assert "`<GCP_BASE>`" in paths and "`$GCP_BASE`" in paths and "`$ASSESS_BASE`" in paths
    assert "`<SKILL_BASE>`" in paths and "never under `<GCP_BASE>`" in paths


def test_every_path_the_handoff_names_exists() -> None:
    doc = _doc()
    bma_paths = set(re.findall(r"<BMA_BASE>/([\w./-]+\.(?:md|py))", doc))
    gcp_paths = set(re.findall(r"<GCP_BASE>/([\w./-]+\.(?:md|py))", doc))
    assert bma_paths and gcp_paths
    for rel in bma_paths:
        assert (BMA / rel).is_file(), rel
    for rel in gcp_paths:
        assert (GCP / rel).is_file(), rel


def test_probe_checks_every_assessment_file_the_handoff_loads() -> None:
    loaded = set(re.findall(r"<BMA_BASE>/([\w./-]+\.(?:md|py))", _doc()))
    assert loaded <= set(_script().REQUIRED_FILES), loaded - set(_script().REQUIRED_FILES)


def test_handoff_names_one_stop_after_per_gcp_phase() -> None:
    table = _section(_doc(), "## Phase entry points")
    for phase in ("clarify", "design", "estimate", "generate"):
        assert re.search(rf"\| {phase.title()}\s*\| `{phase}`", table), phase
    assert "generation-ai.json" in table and "ai-migration/" in table


def test_handoff_error_table_covers_every_error_the_phase_commands_raise() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    raised = set(re.findall(r'HandoffError\("([a-z_]+)"', source))
    errors = _section(_doc(), "## Errors")
    named = set(re.findall(r"^\| `([a-z_]+)`", errors, re.M))
    assert raised <= named, raised - named


@pytest.mark.parametrize(("file", "phase"), [("clarify/clarify.md", "clarify"), ("design/design.md", "design"),
                                             ("estimate/estimate.md", "estimate"), ("generate/generate.md", "generate")])
def test_each_gcp_phase_calls_the_handoff_for_its_own_phase(file, phase) -> None:
    text = (PHASES / file).read_text(encoding="utf-8")
    assert "shared/ai-handoff.md" in text, file
    assert re.search(rf"`{phase}`", text) and "ai-handoff.json" in text, file


def test_generate_runs_the_ai_track_only_on_the_execute_path() -> None:
    entry = _section(_doc(), "## Phase entry points")
    assert "Generate is opt-in" in entry and "only then write `stop_after` `generate`" in entry


def test_gamma_packages_the_assessment_with_gcp() -> None:
    gamma = (PLUGIN_ROOT / "scripts" / "build-gamma-skillset.py").read_text(encoding="utf-8")
    deps = gamma[gamma.index("DEPENDENCIES"):]
    gcp_line = next(line for line in deps.splitlines() if '"gcp-to-aws"' in line)
    assert "bedrock-migration-assessment" in gcp_line


# --------------------------------------------------------------------------- inline callers

def test_agent_advisor_resolves_both_bases() -> None:
    plan = (SKILLS / "agent-advisor" / "references" / "phases" / "migration-plan" / "migration-plan.md").read_text(encoding="utf-8")
    table = plan[plan.index("relative path resolution table"):plan.index("## Step 0")]
    assert re.search(r"\| `<GCP_BASE>/\.\.\.`\s*\| `\$GCP_BASE/\.\.\.`", table)
    assert re.search(r"\| `<BMA_BASE>/\.\.\.`\s*\|[^|]*`bma_base`", table)


def test_llm_to_bedrock_resolves_both_bases() -> None:
    skill = (SKILLS / "llm-to-bedrock" / "SKILL.md").read_text(encoding="utf-8")
    rule = skill[skill.index("**Path resolution.**"):skill.index("### A1")]
    assert "`<GCP_BASE>`" in rule and "`$ASSESS_BASE`" in rule
    assert "`<BMA_BASE>`" in rule and "`bma_base`" in rule


def test_agent_advisor_checks_every_assessment_model_against_the_advisor() -> None:
    plan = (SKILLS / "agent-advisor" / "references" / "phases" / "migration-plan" / "migration-plan.md").read_text(encoding="utf-8")
    phase_c = plan[plan.index("### Phase C"):plan.index("### Step 3.5")]
    assert "`workload_id`" in phase_c and "`call_sites[].file`" in phase_c and "ai-workload-profile.neutral.json" in phase_c
    assert "source_paths" not in phase_c
    step = plan[plan.index("### Step 3.5"):plan.index("### Phase D")]
    assert "matched no unit" in step and "fails\nthis check under item 2" in step
    assert "(c) end here" in step and "§ Failure handling" in step
