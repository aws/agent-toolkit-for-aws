from __future__ import annotations

import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GCP = ROOT / "skills/gcp-to-aws"
SHIMS = [
    "references/phases/discover/discover-app-code.md", "references/phases/discover/discover-openai-api.md",
    "references/phases/discover/discover-anthropic-api.md", "references/phases/discover/discover-openrouter-api.md",
    "references/phases/clarify/clarify-ai-only.md", "references/phases/clarify/clarify-ai.md",
    "references/phases/design/design-ai.md", "references/phases/estimate/estimate-ai.md",
    "references/phases/generate/generate-ai.md", "references/phases/generate/generate-artifacts-ai.md",
]


PR369_MARKERS = ("gpt-6-astra", "mantle_openai_chat", "10×", "required_client_api", "call_bedrock", "BedrockOpenAI")
def load_runtime():
    path = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"
    module = types.ModuleType("bma_runtime_delegation")
    module.__dict__["__file__"] = str(path)  # the runtime reads the lifecycle registry beside its own path
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def test_exact_ten_restricted_shims_have_one_canonical_load() -> None:
    forbidden = ("## Q", "https://api.", "Cost formula", "Write `$MIGRATION_DIR", "Phase Status Update", "fallback engine")
    for relative in SHIMS:
        text = (GCP / relative).read_text()
        assert text.count("$BMA_BASE/references/") == 1, relative
        assert "Compatibility shim" in text and "Removal: issue #389" in text
        assert not any(token in text for token in forbidden), (relative, text)
        # Second-active-copy guard: PR #369 behavior lives only in the BMA-owned files.
        assert not any(token in text for token in PR369_MARKERS), (relative, text)


def test_one_writer_per_neutral_artifact() -> None:
    runtime = load_runtime()
    neutral = ["preferences.json", "aws-design-ai.json", "estimation-ai.json", "generation-ai.json", "MIGRATION_GUIDE.md", "README.md", "decision-report.html", "migration-report.html"]
    for mode in ("direct", "delegated"):
        selected = [runtime.writer(mode, artifact) for artifact in neutral]
        assert len(selected) == len(neutral)
        assert all(owner in {"bedrock-migration-assessment", "gcp-to-aws"} for owner in selected)
    assert runtime.writer("delegated", "preferences.json") == "gcp-to-aws"
    assert runtime.writer("delegated", "preferences.json", "combined") == "gcp-to-aws"
    assert runtime.writer("delegated", "preferences.json", "ai_only") == "bedrock-migration-assessment"
    assert runtime.writer("delegated", "aws-design-ai.json") == "bedrock-migration-assessment"


def test_outer_controllers_preserve_gcp_ownership() -> None:
    discover = (GCP / "references/phases/discover/discover.md").read_text()
    assert "precedes migration-directory creation" in discover
    assert discover.index("Before classification or Step 0 mutation") < discover.index("## Step 0: Initialize Migration State")
    assert discover.index("ask the Step 0 Resume/Fresh/Cancel question now") < discover.index("Invoke `scripts/bma-route-classifier.py classify`")
    assert "--resume-dir \"$SELECTED_RESUME_DIR\"" in discover
    assert "Both classifier passes use the same selected resume argument" in (GCP / "SKILL.md").read_text()
    assert "Do not ask the Resume/Fresh/Cancel question again" in discover
    assert "GCP IaC/Vertex seed → BMA app scan → GCP billing/live → BMA OpenAI/OpenRouter/Anthropic → GCP preview" in discover
    assert "Source-containing input below" in discover
    skill = (GCP / "SKILL.md").read_text()
    assert "pure source-free infrastructure performs zero BMA operations" in skill
    assert "GCP remains the only outer state, telemetry" in skill


def test_route_sensitive_consumers() -> None:
    llm = (ROOT / "skills/llm-to-bedrock/SKILL.md").read_text()
    advisor = (ROOT / "skills/agent-advisor/references/phases/migration-plan/migration-plan.md").read_text()
    assert "immediately after GCP selection" in llm and "MUST NOT fall through to Azure" in llm
    assert "Azure convergence is issue #389 stage 3d" in llm
    assert "Idea-only, declined, and `engine_absent` routes never inspect BMA" in advisor
    assert advisor.index("Step -0.5 — Route-sensitive BMA preflight") < advisor.index("Step 0 — Update agent-advisor state immediately")
