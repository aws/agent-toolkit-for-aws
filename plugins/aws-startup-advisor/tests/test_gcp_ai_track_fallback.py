"""Missing-sibling AI-track fallback (PR #483 thread 4384076100, option 2).

Behavioral: the classifier first pass and ``scripts/resolve-ai-track.py`` run as
subprocesses against a temp skills tree where the ``bedrock-migration-assessment``
directory is genuinely absent (not a mocked flag). A GCP repo with AI evidence AND
infrastructure input proceeds with the AI track deferred and recorded; an AI-only
repo stops naming the missing skill; a present sibling keeps today's second pass;
a tampered sibling still fails closed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
GCP = PLUGIN / "skills/gcp-to-aws"
BMA = PLUGIN / "skills/bedrock-migration-assessment"
VALIDATOR = PLUGIN / "scripts/validate-migration-report.py"
ARTIFACT_VALIDATOR = PLUGIN / "scripts/validate-artifacts.py"
ENV = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
INSTALL_HINT = "npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills --skill bedrock-migration-assessment"
PHASE_DOCS = [
    "references/phases/discover/discover.md",
    "references/phases/clarify/clarify.md",
    "references/phases/clarify/clarify-assemble.md",
    "references/phases/design/design.md",
    "references/phases/estimate/estimate.md",
    "references/phases/generate/generate.md",
    "references/phases/generate/generate-artifacts-docs.md",
    "references/phases/generate/generate-artifacts-report.md",
    "references/shared/report-decision-core.md",
    "SKILL.md",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    value = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            value.update(path.relative_to(root).as_posix().encode())
            value.update(path.read_bytes())
    return value.hexdigest()


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", *argv], text=True, capture_output=True, env=ENV)


@pytest.fixture
def skills_tree(tmp_path: Path) -> dict[str, Path]:
    """A copied gcp-to-aws skill with NO bedrock-migration-assessment sibling, plus projects."""
    gcp = tmp_path / "skills/gcp-to-aws"
    shutil.copytree(GCP, gcp, ignore=shutil.ignore_patterns("__pycache__"))
    assert not (tmp_path / "skills/bedrock-migration-assessment").exists()
    infra = tmp_path / "project_infra"; infra.mkdir()
    (infra / "main.tf").write_text('resource "google_cloud_run_service" "x" {}\n')
    (infra / "app.py").write_text("import openai\n")
    ai_only = tmp_path / "project_ai_only"; ai_only.mkdir()
    (ai_only / "app.py").write_text("import openai\n")
    run_dir = tmp_path / "migration"; run_dir.mkdir()
    return {"gcp": gcp, "skills": tmp_path / "skills", "project_infra": infra, "project_ai_only": ai_only, "run_dir": run_dir}


def classify(gcp: Path, project: Path, bma: Path | None = None) -> tuple[subprocess.CompletedProcess, dict]:
    """First (or, with ``bma``, second) classifier pass from the COPIED skill, like test_bma_bootstrap.invoke."""
    manifest = gcp / "references/runtime/bma-bootstrap-manifest.json"
    argv = [str(gcp / "scripts/bma-route-classifier.py"), "classify", "--project-root", str(project),
            "--patterns", str(gcp / "references/runtime/bma-input-patterns.json"), "--bootstrap-manifest", str(manifest),
            "--expected-bootstrap-manifest-sha256", sha(manifest), "--provider-intent", "none"]
    if bma is not None:
        argv += ["--bma-base", str(bma)]
    completed = _run(argv)
    return completed, json.loads(completed.stdout)


def classification_file(gcp: Path, project: Path) -> Path:
    completed, value = classify(gcp, project)
    assert completed.returncode == 0, completed.stderr
    out = project.parent / f"{project.name}-classification.json"
    out.write_text(completed.stdout)
    return out


def resolve(gcp: Path, classification: Path, write_run_dir: Path | None = None) -> subprocess.CompletedProcess:
    argv = [str(gcp / "scripts/resolve-ai-track.py"), "--skill-base", str(gcp), "--classification", str(classification)]
    if write_run_dir is not None:
        argv += ["--write-run-dir", str(write_run_dir)]
    return _run(argv)


def test_sibling_missing_infra_repo_defers_ai_track_and_writes_record(skills_tree: dict[str, Path]) -> None:
    gcp, run_dir = skills_tree["gcp"], skills_tree["run_dir"]
    before = tree_hash(gcp)
    classification = classification_file(gcp, skills_tree["project_infra"])
    assert json.loads(classification.read_text())["AI_CANDIDATE"] is True

    completed = resolve(gcp, classification)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("\n") == 1 and completed.stderr == ""
    value = json.loads(completed.stdout)
    assert value["ai_track"] == "deferred"
    assert value["reason"] == "bedrock_migration_assessment_missing"
    assert value["missing_skill"] == "bedrock-migration-assessment"
    assert "terraform" in value["infrastructure_evidence"]
    assert value["warning_code"] == "deferred_shared_ai_engine"
    assert value["install_hint"] == INSTALL_HINT
    assert value["ai_signal_files"] == ["app.py"]
    assert completed.stdout == json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    assert not (run_dir / "ai-track.json").exists()

    written = resolve(gcp, classification, write_run_dir=run_dir)
    assert written.returncode == 0, written.stderr
    record = run_dir / "ai-track.json"
    assert record.is_file()
    assert record.read_text() == json.dumps(value, sort_keys=True, indent=2) + "\n"
    assert sorted(p.name for p in run_dir.iterdir()) == ["ai-track.json"]

    contract = _run([str(ARTIFACT_VALIDATOR), "--run-dir", str(run_dir), "--skill", "gcp-to-aws"])
    assert contract.returncode == 0, contract.stdout + contract.stderr
    assert "NO_CONTRACT" not in contract.stdout
    assert tree_hash(gcp) == before


def test_sibling_missing_ai_only_repo_fails_naming_the_skill(skills_tree: dict[str, Path]) -> None:
    gcp, run_dir = skills_tree["gcp"], skills_tree["run_dir"]
    before = tree_hash(gcp)
    classification = classification_file(gcp, skills_tree["project_ai_only"])
    value = json.loads(classification.read_text())
    assert value["AI_CANDIDATE"] is True and value["inventory"]["terraform"] == [] and value["inventory"]["billing"] == []

    completed = resolve(gcp, classification, write_run_dir=run_dir)
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.startswith("AI_TRACK_FAIL | code=bedrock_migration_assessment_missing_ai_only | missing_skill=bedrock-migration-assessment | detail=")
    assert "bedrock-migration-assessment" in completed.stderr and INSTALL_HINT in completed.stderr
    assert not (run_dir / "ai-track.json").exists()
    assert tree_hash(gcp) == before


def test_sibling_present_resolves_active_and_second_pass_is_unchanged(skills_tree: dict[str, Path]) -> None:
    gcp = skills_tree["gcp"]
    bma = skills_tree["skills"] / "bedrock-migration-assessment"
    shutil.copytree(BMA, bma, ignore=shutil.ignore_patterns("__pycache__"))
    classification = classification_file(gcp, skills_tree["project_infra"])

    completed = resolve(gcp, classification)
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert value == {"schema_version": 1, "ai_track": "active", "reason": "bedrock_migration_assessment_present",
                     "bma_base": str(bma.resolve())}

    before = {"gcp": tree_hash(gcp), "bma": tree_hash(bma)}
    second, second_value = classify(gcp, skills_tree["project_infra"], bma=bma)
    assert second.returncode == 0, second.stderr
    assert second_value["ok"] is True and second_value["closure_entries"] == 66
    assert second_value["closure_audit_complete"] is True and second_value["mutation_count"] == 0
    assert second_value["exact_sibling"] == str(bma.resolve())
    assert {"gcp": tree_hash(gcp), "bma": tree_hash(bma)} == before


def test_no_ai_evidence_is_not_applicable_and_never_stats_sibling(skills_tree: dict[str, Path]) -> None:
    gcp, run_dir = skills_tree["gcp"], skills_tree["run_dir"]
    project = skills_tree["project_infra"]
    (project / "app.py").unlink()
    # A sibling path that is a broken symlink: any stat/read of SKILL.md would see a
    # dangling link, and a non-symlink-aware check would raise or misclassify.
    sibling = skills_tree["skills"] / "bedrock-migration-assessment"
    sibling.symlink_to(skills_tree["skills"] / "does-not-exist", target_is_directory=True)
    classification = classification_file(gcp, project)
    assert json.loads(classification.read_text())["AI_CANDIDATE"] is False

    argv = [str(gcp / "scripts/resolve-ai-track.py"), "--skill-base", str(gcp), "--classification", str(classification),
            "--write-run-dir", str(run_dir)]
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        # Deny every read under the sibling path: a stat would fail the run.
        profile = f'(version 1)(allow default)(deny file-read* (subpath "{sibling}"))(deny file-read* (literal "{sibling}"))'
        completed = subprocess.run(["sandbox-exec", "-p", profile, sys.executable, "-B", *argv], text=True, capture_output=True, env=ENV)
    else:
        completed = _run(argv)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"schema_version": 1, "ai_track": "not_applicable", "reason": "no_ai_evidence"}
    assert json.loads((run_dir / "ai-track.json").read_text())["ai_track"] == "not_applicable"


def test_tampered_sibling_is_not_deferred(skills_tree: dict[str, Path]) -> None:
    gcp = skills_tree["gcp"]
    bma = skills_tree["skills"] / "bedrock-migration-assessment"
    shutil.copytree(BMA, bma, ignore=shutil.ignore_patterns("__pycache__"))
    closure = bma / "references/runtime/closure.json"
    closure.write_text(closure.read_text().replace('"schema_version"', '"schema_versio"', 1))
    classification = classification_file(gcp, skills_tree["project_infra"])

    completed = resolve(gcp, classification)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ai_track"] == "active"

    second, second_value = classify(gcp, skills_tree["project_infra"], bma=bma)
    assert second.returncode == 2
    assert second_value["ok"] is False and second_value["reason"] == "BMA_STANDALONE_CLOSURE_INVALID"


def _validator_module():
    spec = importlib.util.spec_from_file_location("validate_migration_report_fallback", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DEFERRED_SECTION = (
    '<section id="deferred-surfaces"><h2>Deferred surfaces</h2><p class="callout-warning">'
    "<strong>deferred_shared_ai_engine:</strong> AI workloads were detected in <code>app.py</code> but the "
    "bedrock-migration-assessment skill is not installed beside gcp-to-aws, so Bedrock model design, estimate and "
    f"generation are deferred and were not produced. Install it (<code>{INSTALL_HINT}</code>) and rerun to add the AI track."
    "</p></section>"
)


def _minimal_full_report(extra: str = "") -> str:
    rows = "".join(f"<tr><td>row {i}</td><td>$1</td></tr>" for i in range(3))
    table = f"<table><tbody>{rows}</tbody></table>"
    sections = {
        "decision-summary": "<h2>Decision</h2><p>Migrate.</p>",
        "exec-assumptions": "<h2>Assumptions</h2><p>None.</p>",
        "exec-services": "<h2>Services</h2><p>ECS.</p>",
        "exec-costs": "<h2>Costs</h2><p>$10/mo</p>",
        "exec-timeline": "<h2>Timeline</h2><p>Phases.</p>",
        "exec-risks": "<h2>Risks</h2><table><tbody><tr><td>r</td></tr></tbody></table>",
        "appendix-services": f"<h2>A</h2>{table}",
        "appendix-costs": f"<h2>B</h2>{table}",
        "appendix-steps": f"<h2>C</h2>{table}",
        "appendix-artifacts": "<h2>E</h2><p>files</p>",
    }
    body = "".join(f'<section id="{k}">{v}</section>' for k, v in sections.items())
    return ("<!DOCTYPE html><html lang='en'><head><title>Report</title></head><body><h1>Report</h1>"
            f"{body}{extra}<footer>draft for review</footer></body></html>")


def test_report_validator_requires_deferred_surfaces_when_track_deferred(tmp_path: Path) -> None:
    validator = _validator_module()
    run_dir = tmp_path / "0101-0101"; run_dir.mkdir()
    deferred = {"schema_version": 1, "ai_track": "deferred", "reason": "bedrock_migration_assessment_missing",
                "missing_skill": "bedrock-migration-assessment", "infrastructure_evidence": ["terraform"],
                "warning_code": "deferred_shared_ai_engine", "install_hint": INSTALL_HINT, "ai_signal_files": ["app.py"]}
    (run_dir / "ai-track.json").write_text(json.dumps(deferred, sort_keys=True, indent=2) + "\n")
    kwargs = {"require_toc": False, "check_readability": False, "migration_dir": run_dir}

    # 1. deferred record, section missing -> AI_DEFERRED_STATE_MISSING
    errors = validator.validate_report(_minimal_full_report(), None, None, None, **kwargs)
    assert any(e.startswith("AI_DEFERRED_STATE_MISSING") for e in errors), errors

    # 2. deferred record, section present -> no AI_DEFERRED error at all
    errors = validator.validate_report(_minimal_full_report(DEFERRED_SECTION), None, None, None, **kwargs)
    assert not any("AI_DEFERRED" in e for e in errors), errors
    assert errors == [], errors
    # ... but an AI appendix alongside a deferred track is a contradiction
    errors = validator.validate_report(
        _minimal_full_report(DEFERRED_SECTION + '<section id="appendix-ai"><h2>AI</h2><p>x</p></section>'), None, None, None, **kwargs)
    assert any(e.startswith("AI_DEFERRED_BUT_AI_SECTIONS_PRESENT") for e in errors), errors
    # ... and an AI-only report cannot carry a deferred track
    errors = validator.validate_report(_minimal_full_report(DEFERRED_SECTION), None, None, None, mode="ai_only", **kwargs)
    assert any(e.startswith("AI_DEFERRED_IN_AI_ONLY_MODE") for e in errors), errors

    # 3. no ai-track.json, code present -> AI_DEFERRED_WARNING_UNEXPECTED
    (run_dir / "ai-track.json").unlink()
    errors = validator.validate_report(_minimal_full_report(DEFERRED_SECTION), None, None, None, **kwargs)
    assert any(e.startswith("AI_DEFERRED_WARNING_UNEXPECTED") for e in errors), errors
    # and a clean infrastructure report without the record stays clean
    assert validator.validate_report(_minimal_full_report(), None, None, None, **kwargs) == []

    # The CLI and the BMA copy agree with the in-process result.
    report = run_dir / "migration-report.html"; report.write_text(_minimal_full_report(DEFERRED_SECTION))
    (run_dir / "ai-track.json").write_text(json.dumps(deferred, sort_keys=True) + "\n")
    for script in (VALIDATOR, BMA / "scripts/validate-migration-report.py"):
        ok = _run([str(script), str(report), "--migration-dir", str(run_dir), "--no-require-toc", "--no-readability"])
        assert ok.returncode == 0, ok.stderr
        assert "optional=deferred-surfaces" in ok.stdout
    report.write_text(_minimal_full_report())
    fail = _run([str(VALIDATOR), str(report), "--migration-dir", str(run_dir), "--no-require-toc", "--no-readability"])
    assert fail.returncode == 1 and "AI_DEFERRED_STATE_MISSING" in fail.stderr
    assert VALIDATOR.read_bytes() == (BMA / "scripts/validate-migration-report.py").read_bytes()


def test_phase_docs_branch_on_ai_track() -> None:
    for relative in PHASE_DOCS:
        text = (GCP / relative).read_text(encoding="utf-8")
        assert "ai-track.json" in text, relative
        assert "deferred" in text, relative
    report = (GCP / "references/phases/generate/generate-artifacts-report.md").read_text(encoding="utf-8")
    assert 'id="deferred-surfaces"' in report and "deferred_shared_ai_engine" in report
    skill = (GCP / "SKILL.md").read_text(encoding="utf-8")
    prerequisites = skill[skill.index("## Prerequisites"):skill.index("### Session tooling check")]
    assert "bedrock-migration-assessment" in prerequisites and "deferred_shared_ai_engine" in prerequisites
    assert "Both classifier passes use the same selected resume argument" in skill
    assert "pure source-free infrastructure performs zero BMA operations" in skill
    assert "GCP remains the only outer state, telemetry" in skill
    assert "BMA_STANDALONE_CLOSURE_INVALID" in skill
    clarify = (GCP / "references/phases/clarify/clarify-assemble.md").read_text(encoding="utf-8")
    assert "AI track" in clarify and "bedrock-migration-assessment not installed" in clarify
    assert "without" in clarify and "`ai_constraints`" in clarify


def test_llm_to_bedrock_names_missing_bma_skill_and_keeps_stop() -> None:
    text = (PLUGIN / "skills/llm-to-bedrock/SKILL.md").read_text(encoding="utf-8")
    assert "performed by the `bedrock-migration-assessment` skill, which is not installed beside `gcp-to-aws` — stop here" in text
    assert INSTALL_HINT in text
    assert "stop here" in text
    assert "immediately after GCP selection" in text and "MUST NOT fall through to Azure" in text
    assert "Azure convergence is issue #389 stage 3d" in text
    advisor = (PLUGIN / "skills/agent-advisor/references/phases/migration-plan/migration-plan.md").read_text(encoding="utf-8")
    assert "scripts/resolve-ai-track.py" in advisor and "AI_TRACK_FAIL" in advisor
    assert "Idea-only, declined, and `engine_absent` routes never inspect BMA" in advisor


def test_resolver_is_referenced_from_discover_and_skill() -> None:
    assert (GCP / "scripts/resolve-ai-track.py").is_file()
    assert os.access(GCP / "scripts/resolve-ai-track.py", os.X_OK)
    for relative in ("SKILL.md", "references/phases/discover/discover.md"):
        text = (GCP / relative).read_text(encoding="utf-8")
        assert "scripts/resolve-ai-track.py" in text, relative
        assert "references/shared/schema-ai-track.md" in text, relative
    discover = (GCP / "references/phases/discover/discover.md").read_text(encoding="utf-8")
    assert '--write-run-dir "$MIGRATION_DIR"' in discover
    assert "AI_TRACK_FAIL | code=bedrock_migration_assessment_missing_ai_only" in discover
