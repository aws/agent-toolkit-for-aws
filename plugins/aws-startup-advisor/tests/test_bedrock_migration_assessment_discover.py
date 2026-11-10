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
    cells = [re.sub(r"^\| \d+\.\d+ ", "| ", row).split("|") for row in _rows(_section(text, heading))[1:]]
    return {c[1].strip(): re.sub(r"\s+", " ", "|".join(c[2:])) for c in cells}


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
    assert VALIDATOR.validate_profile(json.loads(re.findall(r"```json\n(.*?)```", SCAN, re.S)[-1]))["ok"] is True and "never run code from the repository" in SCAN
    step3 = _section(SCAN, "## Step 3")
    assert "`openrouter`" not in [row.split("|")[2].strip() for row in _rows(step3)[1:]]
    for rule in ("**OpenRouter is a gateway, never a source.**", "never open `.env*` files, even to look for variable names",
                 "A `google/` prefix by itself does not make the gateway observed",
                 "Anthropic and OpenAI AI sources from the first bullet remain, and routed `google/` models keep their source.", "another prefix such as `mistralai/` or LiteLLM's `vertex_ai/`, or a string with no prefix"):
        assert rule in step3, rule
    assert 'set `upstream_evidence: "observed"`. Add one upstream per prefix' not in step3 and "When no model string carries" not in step3


@pytest.mark.parametrize("fixture", SCAN_FIXTURES, ids=lambda p: p.name)
def test_expected_profiles_are_valid_and_cite_real_lines(fixture: Path) -> None:
    profile = json.loads((fixture / "ai-workload-profile.json").read_text())
    assert VALIDATOR.validate_profile(profile)["ok"] is True
    for source in profile["ai_sources"]:
        for obs in source["model_observations"]:
            for entry in obs["evidence"]:
                path, line = entry["detail"].split()[0].split(":")
                assert entry["provenance"] == "code" and obs["raw_model"] in (fixture / "repo" / path).read_text().splitlines()[int(line) - 1], entry["detail"]
    assert "Ignore previous instructions" not in json.dumps(profile)


def test_controller_wiring() -> None:
    assert "references/phases/discover/discover.md" in (BMA / "SKILL.md").read_text()
    assert all(t in CONTROLLER for t in ("references/phases/discover/discover-app-code.md", "Never pass a profile that fails validation to Clarify."))
    assert CONTROLLER.index("validate-ai-profile.py $MIGRATION_DIR") < CONTROLLER.index('set `phases.discover` to `"completed"`')
    description = (BMA / "SKILL.md").read_text().split("\n")[2]
    assert "does not scan code" not in description and "llm-to-bedrock" in description


def test_google_genai_mode_and_distinct_gemini_models() -> None:
    table, models = _section(SCAN, "## Step 3"), _section(SCAN, "## Step 4")
    for rule in ("for each `genai.Client(...)` call site separately", "A value set for a different image, service, job, or process is not bound.", "each entry point that imports that module",
                 "Do not open `.env*` or other secret files to look for this setting", "the constructor raises: record it as not confirmed", "`genai.Client(enterprise=True)`",
                 "an in-code assignment is a bound value but not a runtime config", "Use the first line that matches:", "At least one value is bound, and every bound value is true", "The call passes `project=` or `location=`, which the Gemini API rejects: not confirmed."):
        assert rule in table, rule
    assert not any(old in table for old in ("anywhere you may read", "`GOOGLE_GENAI_USE_VERTEXAI` set to true", "If every value that applies")) and "Normalize all `gemini-2.5-flash-*`" not in models
    for kept in ("`gemini-2.5-flash-lite` stays `\"gemini-2.5-flash-lite\"`", "`-lite`, `-thinking`", "keep the full string"):
        assert kept in models, kept


@pytest.mark.parametrize(("fixture", "expected", "gateway"), [
    ("bma-scan-vertex-env-flash-lite", [("gemini-2.5-flash-lite", "vertex_ai")], []),
    ("bma-scan-genai-two-runtimes", [("gemini-2.5-flash", "gemini_api"), ("gemini-2.5-pro", "vertex_ai")], []),
    ("bma-scan-genai-env-in-code", [("gemini-2.5-pro", "vertex_ai")], []),
    ("bma-scan-openrouter-gemini", [("claude-3.5-sonnet", "anthropic_api"), ("gemini-2.5-flash", "gemini_api")], ["unresolved"]),
    ("bma-scan-openrouter-google-pinned", [("claude-3.5-sonnet", "anthropic_api"), ("gemini-2.5-flash", "vertex_ai")], ["observed"]),
])
def test_google_identities_survive_the_summary(fixture: str, expected: list, gateway: list) -> None:
    summary = VALIDATOR.validate_profile(json.loads((PLUGIN_ROOT / "fixtures" / fixture / "ai-workload-profile.json").read_text()))
    assert (sorted((s["models"][0]["model"], s["source_service"]) for s in summary["ai_sources"]), [g["upstream_evidence"] for g in summary["gateways"]]) == (expected, gateway)
