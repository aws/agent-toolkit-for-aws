from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path

import pytest

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


# Review PR #483, thread PRRT_kwDOSKiaLs6wWifL (vagmur-aws): BMA's documented delegated writes of the
# .bma-input/ profile (discover-app-code.md Step 8, usage-API Step 4) must pass the writer table.
BMA_INPUT_PROFILE = {
    "schema_version": "1.0", "gateways": [],
    "ai_sources": [{
        "provider": "openai", "source_service": "openai_api", "model_families": ["gpt"], "model_evidence": "observed",
        "models": ["gpt-4o"],
        "model_observations": [{"normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
                                "evidence": [{"provenance": "code", "confidence": "high", "detail": "src/ai.py:9"}]}],
    }],
}
BMA_INPUT_SIDECAR = {"schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": []}


def _delegated_discover_request(run: Path, writes: list[dict]) -> dict:
    return {
        "schema_version": 1, "mode": "delegated", "scenario": "delegated-discover", "run_dir": str(run),
        "delegated_route": "combined", "state": {"phases": {}}, "writes": writes,
    }


def _bma_write(path: str, payload: dict, expected_sha256: str | None = None) -> dict:
    row = {"phase": "discover", "path": path, "payload": payload, "logical_owner": "bedrock-migration-assessment"}
    if expected_sha256 is not None:
        row["expected_sha256"] = expected_sha256
    return row


def test_delegated_bma_discover_write_of_bma_input_profile_and_sidecar_passes(tmp_path: Path) -> None:
    runtime = load_runtime()
    run = tmp_path / "run"
    run.mkdir()
    profile_path = run / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = run / ".bma-input" / "ai-workload-sidecar.json"
    # Step 8: discover-app-code writes both files.
    result = runtime.execute_contract(_delegated_discover_request(run, [
        _bma_write(".bma-input/ai-workload-profile.json", BMA_INPUT_PROFILE),
        _bma_write(".bma-input/ai-workload-sidecar.json", BMA_INPUT_SIDECAR),
    ]))
    assert profile_path.exists() and sidecar_path.exists()
    assert [(op["path"], op["logical_owner"]) for op in result["operations"]] == [
        (".bma-input/ai-workload-profile.json", "bedrock-migration-assessment"),
        (".bma-input/ai-workload-sidecar.json", "bedrock-migration-assessment"),
    ]
    # Step 4 (usage API): adds a usage-only model and observed_costs, with the SHA-256 of the prior bytes.
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    source = profile["ai_sources"][0]
    source["models"].append("gpt-4o-mini")
    source["model_observations"].append({"normalized_model": "gpt-4o-mini", "raw_model": "gpt-4o-mini", "model_family": "gpt",
                                         "evidence": [{"provenance": "usage_api", "confidence": "high"}]})
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["observed_costs"] = {"monthly_ai_spend": 105, "source": "openai_usage_api", "services_detected": ["OpenAI chat"]}
    second = runtime.execute_contract(_delegated_discover_request(run, [
        _bma_write(".bma-input/ai-workload-profile.json", profile, hashlib.sha256(profile_path.read_bytes()).hexdigest()),
        _bma_write(".bma-input/ai-workload-sidecar.json", sidecar, hashlib.sha256(sidecar_path.read_bytes()).hexdigest()),
    ]))
    assert len(second["operations"]) == 2
    assert json.loads(profile_path.read_text(encoding="utf-8"))["ai_sources"][0]["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["observed_costs"]["monthly_ai_spend"] == 105
    # A rewrite that does not name the prior bytes is still rejected.
    with pytest.raises(ValueError, match="expected_prior_hash_required"):
        runtime.execute_contract(_delegated_discover_request(run, [
            _bma_write(".bma-input/ai-workload-profile.json", profile),
        ]))


def test_delegated_bma_write_to_public_profile_fails_writer_owner_invalid(tmp_path: Path) -> None:
    runtime = load_runtime()
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(ValueError, match="writer_owner_invalid"):
        runtime.execute_contract(_delegated_discover_request(run, [
            _bma_write("ai-workload-profile.json", BMA_INPUT_PROFILE),
        ]))
    assert not (run / "ai-workload-profile.json").exists()
    assert list(run.iterdir()) == []
