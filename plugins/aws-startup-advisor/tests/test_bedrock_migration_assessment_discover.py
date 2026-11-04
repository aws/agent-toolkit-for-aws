"""Contract tests for bedrock-migration-assessment Discover: the code-scan rules and the route controller."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
DISCOVER = BMA / "references" / "phases" / "discover"
SCAN_FIXTURES = sorted(PLUGIN_ROOT.glob("fixtures/bma-scan-*"))

spec = importlib.util.spec_from_file_location("bma_discover_validator", BMA / "scripts" / "validate-ai-profile.py")
VALIDATOR = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = VALIDATOR
spec.loader.exec_module(VALIDATOR)

SCAN = (DISCOVER / "discover-app-code.md").read_text(encoding="utf-8")
CONTROLLER = (DISCOVER / "discover.md").read_text(encoding="utf-8")
GCP = (PLUGIN_ROOT / "skills/gcp-to-aws/references/phases/discover/discover-app-code.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start: end if end != -1 else len(text)]


def _rows(section: str) -> list[str]:
    return [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| ---")]


def _signal_rows(text: str, heading: str) -> dict[str, str]:
    rows = {}
    for row in _rows(_section(text, heading))[1:]:
        cells = re.sub(r"^\| \d+\.\d+ ", "| ", row).split("|")
        rows[cells[1].strip()] = re.sub(r"\s+", " ", "|".join(cells[2:]))
    return rows


def test_kept_rules_match_gcp() -> None:
    secrets = lambda t: [l for l in _section(t, "**Secret file exclusion").splitlines() if l.startswith("- ")][:4]
    assert secrets(SCAN) == secrets(GCP)
    assert _rows(_section(SCAN, "## Step 0.5")) == _rows(_section(GCP, "## Step 0.5"))
    gcp, bma = _signal_rows(GCP, "## Step 3: Flag AI Signals"), _signal_rows(SCAN, "## Step 1: Flag AI Signals")
    for label in ("Google AI Platform SDK", "LLM SDKs (Gemini)", "LLM SDKs (OpenAI)", "LLM SDKs (Other)"):
        assert bma[label] == gcp[label], label
    assert "confidence < 70%" in GCP and "If overall AI confidence < 70%" in SCAN


@pytest.mark.parametrize("pattern", [
    "`client.chat.completions.create(model=\"gpt-4o\")`",
    "`gpt-*`, `o1*`, `o3*`, `o4*`, `text-embedding-*`, `dall-e-*`, `gpt-image-*`, `whisper-*`, `tts-*`",
    "`claude-3-*`, `claude-sonnet-*`, `claude-haiku-*`, `claude-opus-*`",
    "`gemini-pro`, `gemini-1.5-*`, `gemini-2.0-*`, `gemini-2.5-*`, `gemini-3-*`, `gemini-3.1-*`",
])
def test_model_patterns_are_carried_over_from_gcp(pattern: str) -> None:
    assert pattern in GCP and pattern in SCAN


@pytest.mark.parametrize("gcp_only", [
    "Infer Resources from Code", "Graviton", "WebSocket", "Terraform", "gcloud", "iac_vertex", "summary.ai_source", "model_id",
])
def test_scan_drops_gcp_only_steps_and_fields(gcp_only: str) -> None:
    assert gcp_only not in SCAN


def test_scan_output_rules() -> None:
    assert VALIDATOR.validate_profile(json.loads(re.findall(r"```json\n(.*?)```", SCAN, re.S)[-1]))["ok"] is True
    step3 = _section(SCAN, "## Step 3")
    assert "**OpenRouter is a gateway, never a source.**" in step3
    assert "`openrouter`" not in [row.split("|")[2].strip() for row in _rows(step3)[1:]]
    assert "never open `.env*` files, even to look for variable names" in step3
    assert "never run code from the repository" in SCAN


@pytest.mark.parametrize("fixture", SCAN_FIXTURES, ids=lambda p: p.name)
def test_expected_profiles_are_valid_and_cite_real_lines(fixture: Path) -> None:
    profile = json.loads((fixture / "ai-workload-profile.json").read_text())
    assert VALIDATOR.validate_profile(profile)["ok"] is True
    for source in profile["ai_sources"]:
        for obs in source["model_observations"]:
            for entry in obs["evidence"]:
                path, line = entry["detail"].split()[0].split(":")
                assert entry["provenance"] == "code"
                assert obs["raw_model"] in (fixture / "repo" / path).read_text().splitlines()[int(line) - 1], entry["detail"]
    assert "Ignore previous instructions" not in json.dumps(profile)


def test_controller_wiring() -> None:
    assert "references/phases/discover/discover.md" in (BMA / "SKILL.md").read_text()
    assert "references/phases/discover/discover-app-code.md" in CONTROLLER
    assert "Never pass a profile that fails validation to Clarify." in CONTROLLER
    assert CONTROLLER.index("validate-ai-profile.py $MIGRATION_DIR") < CONTROLLER.index('set `phases.discover` to `"completed"`')
    description = (BMA / "SKILL.md").read_text().split("\n")[2]
    assert "does not scan code" not in description and "llm-to-bedrock" in description


def test_google_genai_mode_and_distinct_gemini_models() -> None:
    table, models = _section(SCAN, "## Step 3"), _section(SCAN, "## Step 4")
    for rule in ("for each `genai.Client(...)` call site separately",
                 "A value set for a different image, service, job, or module does not apply.",
                 "Never open `.env*` or other secret files for this."):
        assert rule in table, rule
    assert "anywhere you may read" not in table and "Normalize all `gemini-2.5-flash-*`" not in models
    for kept in ("`gemini-2.5-flash-lite` stays `\"gemini-2.5-flash-lite\"`", "`-lite`, `-thinking`", "keep the full string"):
        assert kept in models, kept


@pytest.mark.parametrize(("fixture", "expected"), [
    ("bma-scan-vertex-env-flash-lite", [("vertex_ai", "gemini-2.5-flash-lite")]),
    ("bma-scan-genai-two-runtimes", [("gemini_api", "gemini-2.5-flash"), ("vertex_ai", "gemini-2.5-pro")]),
])
def test_google_identities_survive_the_summary(fixture: str, expected: list) -> None:
    summary = VALIDATOR.validate_profile(json.loads((PLUGIN_ROOT / "fixtures" / fixture / "ai-workload-profile.json").read_text()))
    assert sorted((s["source_service"], s["models"][0]["model"]) for s in summary["ai_sources"]) == expected
