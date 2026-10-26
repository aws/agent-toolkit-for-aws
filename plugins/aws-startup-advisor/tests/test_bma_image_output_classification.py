"""P1: calls that produce image output are image_generation workloads, never text models.

The Step 5B.2-5B.4 rule runs in scripts/bma-runtime.py (`classify-ai-call`). It reads the call
at the reported source line of a real fixture file, so these tests exercise the classifier
rather than a copy of it. The design target for image_generation is computed by
scripts/bma-runtime.py (`design-target`), and the design doc must route through it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills/bedrock-migration-assessment"
RUNTIME = SKILL / "scripts/bma-runtime.py"
CAPABILITY_MAP = SKILL / "references/vendored/ai/sdk-capability-map.json"
DESIGN_DOC = SKILL / "references/phases/design/design-ai.md"  # gcp-to-aws copy is a shim that points here
FIXTURES = ROOT / "tests/fixtures/bma-image-output/lib"
IMAGE_SOURCE = FIXTURES / "imagen.ts"  # generateContent, responseModalities IMAGE, call at line 4
TEXT_SOURCE = FIXTURES / "chat.ts"  # generateContent, plain text, call at line 4
GENERATE = "ai.models.generateContent"

runtime = types.ModuleType("bma_runtime")
runtime.__dict__["__file__"] = str(RUNTIME)  # the runtime reads the lifecycle registry beside its own path
exec(compile(RUNTIME.read_text(encoding="utf-8"), str(RUNTIME), "exec"), runtime.__dict__)


def _classify(source: Path, model_id: str, line: int = 4) -> dict:
    return runtime.classify_ai_call(source, line, model_id, GENERATE, CAPABILITY_MAP)


def _design_row_from(text: str, capability: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"   | `{capability}`"):
            return line
    raise AssertionError(f"design-ai.md has no routing row for {capability}")


def test_image_output_call_is_image_generation() -> None:
    assert _classify(IMAGE_SOURCE, "gemini-3.1-flash-image") == {
        "capability": "image_generation",
        "capability_confidence": "high",
        "structured_output": False,
    }


def test_text_call_stays_text_generation() -> None:
    assert _classify(TEXT_SOURCE, "gemini-2.5-flash") == {
        "capability": "text_generation",
        "capability_confidence": "medium",
        "structured_output": False,
    }


def test_image_output_model_id_is_image_generation_without_modality_argument() -> None:
    assert _classify(TEXT_SOURCE, "gemini-3.1-flash-image")["capability"] == "image_generation"


def _design_target(capability: str, priority: str = "balanced") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), "design-target", "--capability", capability, "--priority", priority],
        capture_output=True, text=True, check=False,
    )


def test_image_workload_routes_to_image_model_not_text_model() -> None:
    capability = _classify(IMAGE_SOURCE, "gemini-3.1-flash-image")["capability"]
    result = _design_target(capability)
    assert result.returncode == 0, result.stderr
    target = json.loads(result.stdout)
    assert target == {
        "capability": "image_generation",
        "target_aws_service": None,
        "target_bedrock_model": "stability.stable-image-core-v1:0",
    }


def test_image_generation_design_target_is_quality_ultra_only_when_requested() -> None:
    assert json.loads(_design_target("image_generation", "quality").stdout)["target_bedrock_model"] == (
        "stability.stable-image-ultra-v1:0"
    )


def test_design_doc_routes_image_generation_through_design_target() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "design-target --capability image_generation" in text
    assert "Claude" not in _design_row_from(text, "image_generation")


def test_cli_classifies_image_call_for_discover_step() -> None:
    result = subprocess.run(
        [
            sys.executable, str(RUNTIME), "classify-ai-call",
            "--source", str(IMAGE_SOURCE), "--line", "4",
            "--model", "gemini-3.1-flash-image", "--method", GENERATE,
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["capability"] == "image_generation"
