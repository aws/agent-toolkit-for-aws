"""Contract tests for the bedrock-migration-assessment scan's 1.1 output: workloads, integration, agents, and tools."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
SCAN = (BMA / "references/phases/discover/discover-app-code.md").read_text(encoding="utf-8")
CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
FIXTURES = sorted(PLUGIN_ROOT.glob("fixtures/bma-scan-*"))

spec = importlib.util.spec_from_file_location("bma_scan_v11_validator", BMA / "scripts" / "validate-ai-profile.py")
VALIDATOR = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = VALIDATOR
spec.loader.exec_module(VALIDATOR)


def _section(heading: str) -> str:
    start = SCAN.index(heading)
    return SCAN[start:SCAN.find("\n## ", start + len(heading))]


def _profile(fixture: Path) -> dict:
    return json.loads((fixture / "ai-workload-profile.json").read_text())


def _model_id(model: str) -> str:
    return "".join({"_": "_5f", ":": "_3a", "/": "_2f"}.get(c, c) for c in model)


def _line(fixture: Path, file: str, line: int) -> str:
    return (fixture / "repo" / file).read_text().splitlines()[line - 1]


def test_rules_are_first_match_lists_tied_to_real_sdk_behavior() -> None:
    sources = _section("## Step 3")
    for rule in ("in Python so does `1` (the JavaScript SDK reads `1` as false)", "so that client reads its own environment as in google-genai step 2",
                 "Before Python `google-genai` 1.74.0 or JavaScript `@google/genai` 1.51.0",
                 "`load_dotenv()` (python-dotenv)", "the class rejects credentials for the Gemini API", "for `ChatOpenAI`, `OPENAI_API_BASE` first",
                 "a `set_default_openai_client(...)` client's `base_url=` counts as the argument"):
        assert rule in sources, rule
    assert "`true` or `1`, in any case, means Vertex AI" not in sources
    workloads = _section("## Step 4.5")
    for rule in ("A method that is not in it gets no workload", "use the lowest", "`_` with `_5f`, `:` with `_3a`, and `/` with `_2f`", "the `model` string of its `run_config=` (a `RunConfig(…)` or a dict", "reaches through `handoffs=` or `.as_tool(…)`", "`<source_service>.<model>.<sdk_method>.<structured or plain>`"):
        assert rule in workloads, rule
    agents = _section("## Step 4.7")
    assert "Record an agent only when its model is an observed model" in agents and "Do not open MCP config files" in agents
    assert "leading and trailing `_`, `.`, and `-` removed" in agents and "Otherwise (framework calls, alone or with gateway calls): `framework`" in SCAN
    assert "finding no image or audio input does not prove the app sends only text" in CLARIFY


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_scan_fixtures_follow_the_1_1_rules(fixture: Path) -> None:
    profile = _profile(fixture)
    assert profile["schema_version"] == "1.1" and VALIDATOR.validate_profile(profile)["ok"] is True
    seen = set()
    for w in profile["workloads"]:
        key = (w["provider"], w["source_service"], w["model"], w["sdk_method"], w["structured_output"])
        assert key not in seen and w["workload_id"] == f"{w['source_service']}.{_model_id(w['model'])}.{w['sdk_method']}.{'structured' if w['structured_output'] else 'plain'}".lower()
        seen.add(key)
        assert (w["capability"] == "structured_output") == w["structured_output"]
        sites = [(s["file"], s["line"]) for s in w["call_sites"]]
        assert sites == sorted(sites)
        for file, line in sites:
            assert w["sdk_method"].rsplit(".", 1)[1] in _line(fixture, file, line), (file, line)
    for agent in profile.get("agentic_profile", {}).get("agents", []):
        assert agent["agent_id"] in _line(fixture, agent["file"], agent["line"]).lower()
    for tool in profile.get("tool_manifest", []):
        name, _, where = tool["name"].partition("@")
        assert name in _line(fixture, tool["file"], tool["line"]) and where in ("", tool["file"])


@pytest.mark.parametrize(("fixture", "framework", "vision"), [
    ("bma-scan-workloads-mixed", ["direct"], "vision"),
    ("bma-scan-openrouter-gemini", ["direct", "llm_router"], None),
    ("bma-scan-openrouter-google-pinned", ["llm_router"], None),
    ("bma-scan-agents-langgraph", None, None),
    ("bma-scan-agents-openai", None, None),
    ("bma-scan-framework-gateway", ["framework", "llm_router"], None),
    ("bma-scan-agents-independent", None, None),
])
def test_clarify_extracts_only_what_the_scan_shows(fixture: str, framework, vision) -> None:
    summary = VALIDATOR.validate_profile(_profile(PLUGIN_ROOT / "fixtures" / fixture))
    assert (summary["ai_framework_detected"], summary["ai_vision_detected"]) == (framework, vision)


def test_mixed_fixture_keeps_each_workload_apart() -> None:
    profile = _profile(PLUGIN_ROOT / "fixtures" / "bma-scan-workloads-mixed")
    got = {(w["model"], w["sdk_method"], w["capability"], w["capability_confidence"]) for w in profile["workloads"]}
    assert ("gpt-4o", "openai.chat.completions.create", "structured_output", "high") in got
    assert ("gpt-4o", "openai.chat.completions.create", "text_generation", "medium") in got
    assert ("text-embedding-004", "genai.models.embed_content", "embedding", "high") in got
    assert not any("assistants" in w["sdk_method"] for w in profile["workloads"])
    assert "ft:gpt-4o-mini-2024-07-18:acme:triage:a1b2" in {w["model"] for w in profile["workloads"]}
    pair = [{**profile["workloads"][0], "model": m, "workload_id": f"openai_api.{_model_id(m)}.openai.chat.completions.create.plain"} for m in ("ft:x:y", "ft:x_3ay")]
    for w, m in zip(pair, ("ft:x:y", "ft:x_3ay")):
        profile["ai_sources"][2]["models"].append(m)
        profile["ai_sources"][2]["model_observations"].append({**profile["ai_sources"][2]["model_observations"][0], "normalized_model": m, "raw_model": m})
    profile["workloads"] += pair
    assert pair[0]["workload_id"] != pair[1]["workload_id"] and VALIDATOR.validate_profile(profile)["ok"] is True


def test_agents_only_with_observed_models_and_no_secret_copies() -> None:
    langgraph = _profile(PLUGIN_ROOT / "fixtures" / "bma-scan-agents-langgraph")
    assert {s["source_service"] for s in langgraph["ai_sources"]} == {"anthropic_api", "vertex_ai"}
    assert "gpt-4o-mini" not in json.dumps(langgraph)
    openai_agents = _profile(PLUGIN_ROOT / "fixtures" / "bma-scan-agents-openai")["agentic_profile"]
    assert (openai_agents["orchestration_pattern"], [a["agent_id"] for a in openai_agents["agents"]]) == ("hierarchical", ["billing", "triage"])
    independent = _profile(PLUGIN_ROOT / "fixtures" / "bma-scan-agents-independent")["agentic_profile"]
    assert (independent["orchestration_pattern"], [a["agent_id"] for a in independent["agents"]]) == ("unknown", ["billing", "support", "sales"])
    for fixture in FIXTURES:
        assert not re.search(r"sk-[A-Za-z0-9]|eval-canary", json.dumps(_profile(fixture)))
