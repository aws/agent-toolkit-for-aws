from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"
BMA_VALIDATOR = ROOT / "skills/bedrock-migration-assessment/scripts/validate-migration-report.py"
PLUGIN_VALIDATOR = ROOT / "scripts/validate-migration-report.py"
AI_ONLY_BODY = ROOT / "fixtures/bedrock-migration-assessment/report-documents/ai-only-migration-report-body.html"
REFERENCE = ROOT / "fixtures/migration-report-reference.html"
ESTIMATION_AI = ROOT / "fixtures/estimation-ai-reference.json"
ESTIMATION_INFRA = ROOT / "fixtures/estimation-infra-reference.json"
ANCHOR = "<!-- bma-contributions:ai-notes -->"
DECISION_SUMMARY = '<section id="decision-summary">'

runtime = types.ModuleType("bma_runtime_documents")
runtime.__dict__["__file__"] = str(PATH)  # the runtime reads the lifecycle registry beside its own path
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)


def contribution(target: str = "migration-report.html") -> dict:
    return {
        "id": "ai.callout", "bucket": 100, "source_order": 1,
        "target": target, "kind": "callout", "section": "ai-notes",
        "content": {
            "text": "Validated direct AI-only callout.", "links": [],
            "traceability": {
                "provider": "openai", "source_service": "openai_api", "model": "gpt-4o",
                "call_sites": [{"file": "src/app.py", "line": 7}],
            },
        },
    }


def with_anchor(document: str) -> str:
    """Place the contribution anchor as the first child of the decision summary."""
    assert document.count(DECISION_SUMMARY) == 1
    return document.replace(DECISION_SUMMARY, f"{DECISION_SUMMARY}\n{ANCHOR}", 1)


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def request(run: Path, mode: str, assembly: dict) -> dict:
    return {
        "schema_version": 1, "mode": mode, "scenario": "documents", "run_dir": str(run),
        "state": {}, "consent": [], "writes": [], "assemblies": [assembly],
    }


def run_validator(script: Path, report: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), str(report), *args], capture_output=True, text=True, check=False,
    )


def test_direct_ai_only_report_passes_real_validator(tmp_path: Path) -> None:
    run = tmp_path / "direct"
    run.mkdir()
    shutil.copy(ESTIMATION_AI, run / "estimation-ai.json")
    assembly = {
        "phase": "generate", "target": "migration-report.html", "report_mode": "ai_only",
        "document": with_anchor(AI_ONLY_BODY.read_text(encoding="utf-8")),
        "contributions": [contribution()],
    }
    result = runtime.execute_contract(request(run, "direct", assembly))
    report = run / "migration-report.html"
    assert result["operations"][0]["path"] == "migration-report.html"
    assert '<p class="callout">Validated direct AI-only callout.</p>' in report.read_text(encoding="utf-8")
    proc = run_validator(BMA_VALIDATOR, report, "--mode", "ai_only", "--estimation-ai", str(run / "estimation-ai.json"))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_combined_report_passes_plugin_validator(tmp_path: Path) -> None:
    run = tmp_path / "combined"
    run.mkdir()
    shutil.copy(ESTIMATION_AI, run / "estimation-ai.json")
    shutil.copy(ESTIMATION_INFRA, run / "estimation-infra.json")
    assembly = {
        "phase": "generate", "target": "migration-report.html", "report_mode": "full",
        "document": with_anchor(REFERENCE.read_text(encoding="utf-8")),
        "contributions": [contribution()],
    }
    runtime.execute_contract({**request(run, "delegated", assembly), "scenario": "combined"})
    report = run / "migration-report.html"
    proc = run_validator(
        PLUGIN_VALIDATOR, report,
        "--estimation-infra", str(run / "estimation-infra.json"),
        "--estimation-ai", str(run / "estimation-ai.json"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(("case", "error", "mutate"), [
    ("bare-contribution", "document_required", None),
    ("missing-anchor", "contribution_anchor_missing", lambda body: body.replace(ANCHOR, "")),
    ("missing-h1", "document_structure_invalid", lambda body: body.replace("<h1>", "<h2>").replace("</h1>", "</h2>")),
    ("missing-report-mode", "report_mode_invalid", "drop-mode"),
    ("script-contribution", "contribution_content_invalid", "script"),
])
def test_document_contract_rejects_before_any_write(tmp_path: Path, case: str, error: str, mutate) -> None:
    run = tmp_path / case
    run.mkdir()
    (run / ".phase-status.json").write_text('{"stable":true}\n')
    before = tree_bytes(run)
    body = with_anchor(AI_ONLY_BODY.read_text(encoding="utf-8"))
    value = contribution()
    assembly = {
        "phase": "generate", "target": "migration-report.html", "report_mode": "ai_only",
        "document": body, "contributions": [value],
    }
    if case == "bare-contribution":
        del assembly["document"]
    elif case == "script-contribution":
        value["content"]["text"] = "<script>alert(1)</script>"
    elif mutate == "drop-mode":
        del assembly["report_mode"]
    else:
        assembly["document"] = mutate(body)
    with pytest.raises(ValueError, match=error):
        runtime.execute_contract(request(run, "direct", assembly))
    assert tree_bytes(run) == before
    assert not (run / "migration-report.html").exists()
