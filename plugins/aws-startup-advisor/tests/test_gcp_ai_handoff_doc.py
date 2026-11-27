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


@pytest.mark.parametrize("file", ["design/design.md", "estimate/estimate.md", "generate/generate.md"])
def test_a_run_without_a_handoff_record_is_routed_before_the_ai_gate(file) -> None:
    text = (PHASES / file).read_text(encoding="utf-8")
    entry_lines = [line for line in text.splitlines() if line.startswith("IF ") and "ai-handoff.json" in line]
    missing = next(line for line in entry_lines if "`ai-handoff.json` does not exist" in line)
    assert "`ai-workload-profile.json` exists" in missing and "Runs without a handoff record" in missing, missing
    active = next(line for line in entry_lines if "other than `deferred`" in line)
    assert "`ai-workload-profile.json` exists" in active and entry_lines.index(missing) < entry_lines.index(active), active
    gate = next(line for line in text.splitlines() if line.lstrip().startswith("- ") and "is not `deferred`" in line)
    assert "`ai-workload-profile.json` exists and `ai-handoff.json` exists" in gate, gate
    legacy = _section(_doc(), "## Runs without a handoff record")
    for name in ("aws-design-ai.json", "estimation-ai.json", "generation-ai.json", "ai-migration/", "Step 1", "`clarify`", "confirm"):
        assert name in legacy, name
    entry = _section(_doc(), "## Phase entry points")
    assert "with no `ai-handoff.json` or a deferred one, they skip" not in entry


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


# --------------------------------------------------------------------------- report cost guardrails

REPORT_DOCS = ("phases/generate/generate-artifacts-report.md", "shared/report-decision-core.md", "shared/validate-artifacts.md")
GUARDRAIL_STEP = "== 6. Bedrock budget and cost anomaly monitor"


def test_gcp_report_keys_cost_guardrails_on_the_assessment_setup_script() -> None:
    for rel in REPORT_DOCS:
        text = (GCP / "references" / rel).read_text(encoding="utf-8")
        assert "bedrock_monitoring.tf" not in text, rel
        assert rel == "shared/report-decision-core.md" or "ai-migration/setup_bedrock.sh" in text, rel
    report = (GCP / "references" / REPORT_DOCS[0]).read_text(encoding="utf-8")
    guard = report.split("**Cost guardrails", 1)[1].split("**What the baseline", 1)[0]
    assert f"`{GUARDRAIL_STEP}`" in guard
    assert "`BUDGET_USD`" in guard and "`BUDGET_SERVICES`" in guard and "no budget" in guard
    assert "--execute" in guard and "Never add an Inference profiles row" in guard


CANONICAL_REPORT = GCP / "references" / "vendored" / "report"


def _guardrail_conditions() -> dict[str, str]:
    core = (CANONICAL_REPORT / "report-decision-core.md").read_text(encoding="utf-8")
    skeleton = (CANONICAL_REPORT / "report-appendix-skeleton.md").read_text(encoding="utf-8")
    return {
        "decision core fourth row": next(line for line in core.splitlines() if "The fourth row is **conditional**" in line),
        "skeleton cost guardrails": skeleton.split("**Cost guardrails**", 1)[1].split("These are detective controls", 1)[0],
        "skeleton check 3": skeleton.split("3. **Conditional sections**", 1)[1].split("\n4. ", 1)[0],
    }


@pytest.mark.parametrize("place", ["decision core fourth row", "skeleton cost guardrails", "skeleton check 3"])
def test_the_canonical_report_keys_cost_guardrails_on_both_generators(place: str) -> None:
    text = " ".join(_guardrail_conditions()[place].split())
    assert "bedrock_monitoring.tf" in text and GUARDRAIL_STEP in text, place
    assert "setup_bedrock.sh" in text or "setup script" in text, place


def test_the_canonical_report_ties_profile_attribution_to_the_terraform_file() -> None:
    text = " ".join(_guardrail_conditions()["skeleton cost guardrails"].split())
    profiles = text.split("**Inference profiles (tagged)**", 1)[1]
    assert "bedrock_monitoring.tf" in profiles and "never from the setup script" in profiles


@pytest.mark.parametrize("layer, canonical", [
    ("shared/report-decision-core.md", "report-decision-core.md"),
    ("phases/generate/generate-artifacts-report.md", "report-appendix-skeleton.md")])
def test_the_gcp_report_layer_does_not_restate_the_canonical(layer: str, canonical: str) -> None:
    shared = {line.strip() for line in (CANONICAL_REPORT / canonical).read_text(encoding="utf-8").splitlines()}
    repeated = [line.strip() for line in (GCP / "references" / layer).read_text(encoding="utf-8").splitlines()
                if len(line.strip()) > 80 and line.strip() in shared]
    assert not repeated, repeated[:3]


@pytest.mark.parametrize("fixture, usd_empty, services_empty", [
    ("bma-generate-same-model", False, False), ("bma-generate-mixed", True, False), ("bma-generate-tier-range", False, True)])
def test_the_assessment_setup_script_carries_what_the_report_reads(fixture: str, usd_empty: bool, services_empty: bool) -> None:
    setup = (PLUGIN_ROOT / "fixtures" / fixture / "ai-migration" / "setup_bedrock.sh").read_text(encoding="utf-8")
    assert GUARDRAIL_STEP in setup
    usd = re.search(r'^BUDGET_USD="\$\{BUDGET_USD:-([0-9.]*)\}"$', setup, re.M)
    services = re.search(r'^BUDGET_SERVICES="\$\{BUDGET_SERVICES:-([^"]*)\}"$', setup, re.M)
    assert usd and services
    assert (usd.group(1) == "") is usd_empty and (services.group(1) == "") is services_empty
    assert "create-anomaly-monitor" in setup and "create-inference-profile" not in setup


def test_clarify_runs_the_handoff_once_from_the_assembler_gate() -> None:
    clarify = (PHASES / "clarify" / "clarify.md").read_text(encoding="utf-8")
    step2 = clarify[clarify.index("## Step 2: Run the Fragments"):clarify.index("## Step 3: AI Handoff")]
    item3 = next(line for line in step2.splitlines() if line.startswith("3. "))
    assert "once" in item3 and "Completion Handoff Gate" in item3, item3
    assemble = (PHASES / "clarify" / "clarify-assemble.md").read_text(encoding="utf-8")
    assert "**On PASS:** run `clarify.md` § Step 3" in assemble


def test_a_deferred_clarify_handoff_still_completes_the_phase() -> None:
    clarify = (PHASES / "clarify" / "clarify.md").read_text(encoding="utf-8")
    step3 = clarify[clarify.index("## Step 3: AI Handoff"):]
    item1 = step3[step3.index("1. Load"):step3.index("2. After")]
    defer = item1[item1.index("a `defer` route"):]
    assert "item 3" in defer and "rest of this step" not in defer, defer


def test_agent_advisor_ends_at_once_for_a_block_no_unit_matched() -> None:
    plan = (SKILLS / "agent-advisor" / "references" / "phases" / "migration-plan" / "migration-plan.md").read_text(encoding="utf-8")
    step = plan[plan.index("### Step 3.5"):plan.index("### Phase D")]
    item2 = step[step.index("2. If model, API"):step.index("3. A live probe")]
    assert "`\"advisor_unit\": null`" in item2 and "offer only (c)" in item2, item2
