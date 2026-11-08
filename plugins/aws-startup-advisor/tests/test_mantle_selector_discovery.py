"""Guard: Discover detects the code-visible Mantle-only selectors and records them as mantle_signals.

Amazon Bedrock serves Responses `background=true` only on `bedrock-mantle`; `bedrock-runtime`
rejects it with a 400 (https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
read 2026-11-07). The same is true of server-side tools, Web Search, Projects and Workspaces, and
those five are the only selectors a code scan can see. These checks pin: the scanner steps in the
three app-code discovery files, the usage-API merges, the profile contracts (legacy per-workload
`workloads[].mantle_signals[]` and the provider-neutral top-level `mantle_signals[]`), the policy
file's "How a selector is learned" section, the validator's cross-check and summary, and the
bma-scan-openai-mantle-signals fixture whose negatives must never be cited.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
BMA = SKILLS / "bedrock-migration-assessment"

SCANNERS = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "phases" / "discover" / "discover-app-code.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "phases" / "discover" / "discover-app-code.md",
    "bma": BMA / "references" / "phases" / "discover" / "discover-app-code.md",
}
USAGE_API_SIGNALS = [
    ("discover-openai-api.md", ["`projects`", "project_filter"]),
    ("discover-anthropic-api.md", ["`workspaces`", "workspace_ids"]),
    ("discover-openrouter-api.md", ["`:online`", "`web_search`", "NOT a `workspaces` signal"]),
]
POLICY_CANONICAL = SKILLS / "shared" / "ai" / "bedrock-endpoint-policy.md"
POLICY_VENDORED = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "bedrock-endpoint-policy.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "bedrock-endpoint-policy.md",
]
CANONICAL_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "ai-workload-profile.schema.json"
BMA_SCHEMA = BMA / "references" / "contracts" / "ai-workload-profile.schema.json"
LEGACY_SCHEMA_DOCS = [
    SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-discover-ai.md",
    SKILLS / "azure-to-aws" / "references" / "shared" / "schema-discover-ai.md",
]
FIXTURE = PLUGIN_ROOT / "fixtures" / "bma-scan-openai-mantle-signals"
NEGATIVE_FIXTURE = PLUGIN_ROOT / "fixtures" / "bma-scan-openai-direct"

DETECTABLE = ["background_inference", "web_search", "server_side_tools", "projects", "workspaces"]
NEVER_DETECTED = ["mantle_only_model_or_api", "in_region_processing"]
POSITIVE_CONSTRUCTS = ["web_search", "web_search_preview", '"type": "mcp"', "OpenAI-Project", "anthropic-workspace-id"]
NEGATIVE_CONSTRUCTS = ['"type": "function"', "store="]

spec = importlib.util.spec_from_file_location("bma_mantle_validator", BMA / "scripts" / "validate-ai-profile.py")
VALIDATOR = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = VALIDATOR
spec.loader.exec_module(VALIDATOR)


def _load_fixture() -> dict:
    return json.loads((FIXTURE / "ai-workload-profile.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- (a) scanners
@pytest.mark.parametrize("name", sorted(SCANNERS), ids=str)
def test_scanner_has_a_mantle_selector_step(name: str) -> None:
    text = SCANNERS[name].read_text(encoding="utf-8")
    assert re.search(r"^## Step [0-9.A-Z]+: Mantle-[Oo]nly [Ss]elector [Ss]ignals", text, re.M), f"{name}: no Mantle selector step heading"
    for selector in DETECTABLE:
        assert f"`{selector}`" in text, f"{name}: detectable selector {selector} missing"
    assert "background=True" in text or "background: true" in text, f"{name}: background construct missing"
    for construct in POSITIVE_CONSTRUCTS:
        assert construct in text, f"{name}: positive construct {construct!r} missing"
    for construct in NEGATIVE_CONSTRUCTS:
        assert construct in text, f"{name}: negative construct {construct!r} missing"
    assert "`in_region_processing` is never code-detectable" in text, f"{name}: must say in_region_processing is never detected"
    assert "`mantle_only_model_or_api`" in text, f"{name}: must say mantle_only_model_or_api is not a scanner output"
    assert "mantle_signals" in text, f"{name}: output key mantle_signals missing"


def test_legacy_scanners_write_per_workload_signals_and_bma_writes_top_level() -> None:
    for name in ("gcp", "azure"):
        assert "workloads[]" in SCANNERS[name].read_text(encoding="utf-8")
    bma = SCANNERS["bma"].read_text(encoding="utf-8")
    assert "a top-level `mantle_signals` array" in bma
    assert "model_id" not in bma and "Terraform" not in bma and "gcloud" not in bma


# --------------------------------------------------------------------------- (b) usage-API merges
@pytest.mark.parametrize("skill", ["gcp-to-aws", "azure-to-aws"])
@pytest.mark.parametrize(("filename", "needles"), USAGE_API_SIGNALS, ids=lambda v: v if isinstance(v, str) else "")
def test_usage_api_merges_name_their_signal(skill: str, filename: str, needles: list[str]) -> None:
    path = SKILLS / skill / "references" / "phases" / "discover" / filename
    text = path.read_text(encoding="utf-8")
    step4 = re.sub(r"\s+", " ", text[text.index("## Step 4: Merge"):])
    assert "mantle_signals" in step4, f"{path}: Step 4 does not append to mantle_signals"
    assert '"<usage_api>", "line": 0' in step4, f"{path}: usage-API signal must use the <usage_api>/line 0 sentinel"
    for needle in needles:
        assert needle in step4, f"{path}: {needle!r} missing from Step 4"


# --------------------------------------------------------------------------- (c) schema
def test_schema_copies_are_byte_identical_and_define_mantle_signal() -> None:
    assert CANONICAL_SCHEMA.read_bytes() == BMA_SCHEMA.read_bytes(), "BMA schema copy drifted from the canonical"
    schema = json.loads(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["mantle_signals"]["items"] == {"$ref": "#/definitions/mantleSignal"}
    assert "mantle_signals" not in schema["required"]
    signal = schema["definitions"]["mantleSignal"]
    assert signal["properties"]["selector"]["enum"] == DETECTABLE
    assert signal["required"] == ["selector", "provider", "source_service", "model", "evidence"]
    assert signal["additionalProperties"] is False
    assert "mantle_signals" not in VALIDATOR.V11_FIELDS
    for doc in LEGACY_SCHEMA_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "mantle_signals" in text, f"{doc}: legacy per-workload mantle_signals missing"
        for selector in DETECTABLE:
            assert selector in text, f"{doc}: selector {selector} missing"


# --------------------------------------------------------------------------- (d) policy
def test_policy_explains_how_each_selector_is_learned() -> None:
    for path in [POLICY_CANONICAL, *POLICY_VENDORED]:
        text = path.read_text(encoding="utf-8")
        assert "## How a selector is learned" in text, f"{path}: section missing"
        section = text[text.index("## How a selector is learned"):text.index("## Public comparison")]
        for selector in DETECTABLE + NEVER_DETECTED:
            assert f"`{selector}`" in section, f"{path}: {selector} not covered"
        assert "inference-responses-api.html" in section
        assert "never code-detectable" in section
        assert "workloads[].mantle_signals[]" in section and "top-level `mantle_signals[]`" in section


# --------------------------------------------------------------------------- (e) fixture
def test_fixture_validates_and_cites_only_positive_lines() -> None:
    profile = _load_fixture()
    assert VALIDATOR.validate_profile(profile)["ok"] is True
    source = (FIXTURE / "repo" / "app" / "llm.py").read_text(encoding="utf-8").splitlines()
    joined = "\n".join(source)
    for negative in ('"type": "function"', "store=True"):
        assert negative in joined, f"fixture must contain the negative {negative!r}"
    assert "Ignore previous instructions" not in json.dumps(profile) and "Ignore previous instructions" not in joined
    selectors = []
    for signal in profile["mantle_signals"]:
        selectors.append(signal["selector"])
        for entry in signal["evidence"]:
            location, construct = entry["detail"].split(" ", 1)
            path, line = location.split(":")
            cited = (FIXTURE / "repo" / path).read_text(encoding="utf-8").splitlines()[int(line) - 1]
            assert construct in cited, f"{entry['detail']}: cited line does not contain the construct"
            for negative in ('"type": "function"', "store=True"):
                assert negative not in cited, f"{entry['detail']}: cites a negative line"
    assert sorted(selectors) == ["background_inference", "projects", "server_side_tools", "web_search"]


# --------------------------------------------------------------------------- (f) validator rejects
def test_validator_rejects_a_signal_on_an_unobserved_model() -> None:
    profile = copy.deepcopy(_load_fixture())
    profile["mantle_signals"][0]["model"] = "gpt-4.1"
    with pytest.raises(VALIDATOR.ProfileRejected) as excinfo:
        VALIDATOR.validate_profile(profile)
    assert excinfo.value.code == "unmatched_mantle_signal"
    profile = copy.deepcopy(_load_fixture())
    profile["mantle_signals"][0]["source_service"] = "azure_openai"
    with pytest.raises(VALIDATOR.ProfileRejected) as excinfo:
        VALIDATOR.validate_profile(profile)
    assert excinfo.value.code == "unmatched_mantle_signal"
    profile = copy.deepcopy(_load_fixture())
    profile["mantle_signals"][0]["selector"] = "in_region_processing"
    with pytest.raises(VALIDATOR.ProfileRejected) as excinfo:
        VALIDATOR.validate_profile(profile)
    assert excinfo.value.code == "schema_violation"


# --------------------------------------------------------------------------- (g) summary
def test_summary_lists_detected_signals() -> None:
    detected = VALIDATOR.validate_profile(_load_fixture())["mantle_signals_detected"]
    assert sorted(d["selector"] for d in detected) == ["background_inference", "projects", "server_side_tools", "web_search"]
    for item in detected:
        assert set(item) == {"selector", "provider", "source_service", "model", "detail"}
        assert (item["provider"], item["source_service"], item["model"]) == ("openai", "openai_api", "gpt-4o")
        assert item["detail"].startswith("app/llm.py:")
    negative = json.loads((NEGATIVE_FIXTURE / "ai-workload-profile.json").read_text(encoding="utf-8"))
    assert VALIDATOR.validate_profile(negative)["mantle_signals_detected"] == []
