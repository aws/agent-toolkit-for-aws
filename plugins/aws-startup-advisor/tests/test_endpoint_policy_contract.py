"""Guard: the canonical Bedrock endpoint policy and its consumers.

Amazon Bedrock documents `bedrock-runtime` as the recommended endpoint for most
new applications and `bedrock-mantle` for capabilities available only there
(https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html, read
2026-11-07). The plugin states that rule once, in
`skills/shared/ai/bedrock-endpoint-policy.md`, vendors it into gcp-to-aws and
azure-to-aws, and requires every `mantle_*` design row to record a
`mantle_selector`. These checks pin the policy file's contract and the design
files and the llm-to-bedrock orchestrator that must point at it.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

POLICY_CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "ai" / "bedrock-endpoint-policy.md"
POLICY_VENDORED = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "vendored" / "ai" / "bedrock-endpoint-policy.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "vendored" / "ai" / "bedrock-endpoint-policy.md",
]

ANTHROPIC_GUIDE = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-anthropic-to-bedrock.md"
LLM_TO_BEDROCK_SKILL = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "SKILL.md"

DESIGN_AI_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md",
]

SCHEMA_FILES = [
    PLUGIN_ROOT / "skills" / "shared" / "ai" / "schema-design-aws-ai.md",
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "shared" / "schema-design-aws-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md",
]

MANTLE_SELECTOR_ENUM = [
    "background_inference",
    "server_side_tools",
    "web_search",
    "projects",
    "workspaces",
    "mantle_only_model_or_api",
    "in_region_processing",
]

ENDPOINTS_URL = "https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html"

# Claims the public pages do not make and the policy must not add.
FORBIDDEN_WORDING = ["not deprecated", "guarantee", "roadmap"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_policy_file_exists_and_vendored_copies_are_byte_identical() -> None:
    assert POLICY_CANONICAL.is_file(), "skills/shared/ai/bedrock-endpoint-policy.md is missing"
    canonical = POLICY_CANONICAL.read_bytes()
    for vendored in POLICY_VENDORED:
        assert vendored.is_file(), f"{vendored} missing — add the README row and run tools/sync-vendored.py"
        assert vendored.read_bytes() == canonical, f"{vendored} drifted from the canonical policy"


def test_policy_states_the_runtime_default_and_selector_rule() -> None:
    text = _norm(POLICY_CANONICAL.read_text(encoding="utf-8"))
    assert "Use `bedrock-runtime` for new applications" in text
    assert "API continuity alone never selects Mantle" in text
    assert "Pricing never selects an endpoint" in text
    assert "identical on both" not in text
    assert "do not use the In-Region rate in its place" in text
    assert "model-card-openai-gpt-54.html" in text
    assert "model-card-openai-gpt-55.html" in text
    for value in MANTLE_SELECTOR_ENUM:
        assert f"`{value}`" in text, f"mantle_selector enum value {value} missing from the policy"
    assert ENDPOINTS_URL in text, "policy must cite the public endpoints.html page"
    assert re.search(r"read 20\d\d-\d\d-\d\d", text), "policy must carry a 'read <date>' token"


def test_policy_avoids_lifecycle_and_roadmap_claims() -> None:
    text = POLICY_CANONICAL.read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN_WORDING:
        assert phrase not in text, f"policy must not claim '{phrase}'"
    assert "continue to be fully supported and do not need to change" in text


def test_design_ai_files_reference_the_policy() -> None:
    for f in DESIGN_AI_FILES:
        text = f.read_text(encoding="utf-8")
        assert "bedrock-endpoint-policy.md" in text, f"{f}: does not point at the endpoint policy"
        assert "mantle_selector" in text, f"{f}: does not require mantle_selector on mantle_* rows"


def test_llm_to_bedrock_skill_references_the_policy_and_defaults_to_runtime() -> None:
    text = LLM_TO_BEDROCK_SKILL.read_text(encoding="utf-8")
    assert "bedrock-endpoint-policy.md" in text, "llm-to-bedrock SKILL.md does not point at the endpoint policy"
    assert "## Endpoint policy (bedrock-runtime default)" in text
    assert "API continuity alone never selects Mantle" in _norm(text)
    assert "retains the Converse default otherwise" not in text
    assert "never the implicit default" in _norm(text)


def test_schema_docs_carry_the_runtime_default_vocabulary() -> None:
    for f in SCHEMA_FILES:
        text = f.read_text(encoding="utf-8")
        assert "bedrock-endpoint-policy.md" in text, f"{f}: does not point at the endpoint policy"
        assert "runtime_messages" in text, f"{f}: migration_path vocabulary missing runtime_messages"
        assert "same_model_runtime" in text, f"{f}: openrouter_path vocabulary missing same_model_runtime"
        for value in MANTLE_SELECTOR_ENUM:
            assert value in text, f"{f}: mantle_selector enum value {value} missing"


def test_anthropic_guide_defaults_to_runtime_messages_with_a_string_token() -> None:
    """The Anthropic guide keeps the SDK on bedrock-runtime /anthropic by default.

    https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html
    (read 2026-11-07) passes the Bedrock token as a plain string `api_key`; the
    pinned Anthropic SDK accepts no callable there, so the guide must never show
    `api_key=lambda` / `auth_token=lambda`. Converse stays an explicit alternative.
    """
    text = ANTHROPIC_GUIDE.read_text(encoding="utf-8")
    assert "runtime_messages" in text, "Anthropic guide does not name runtime_messages"
    assert '"converse"' in text, "Anthropic guide lost the explicit Converse alternative"
    assert text.index("runtime_messages") < text.index('"converse"'), (
        "Anthropic guide must present runtime_messages before the converse alternative"
    )
    assert "bedrock-runtime.{region}.amazonaws.com/anthropic" in text
    assert 'required_client_api: "messages"' in text
    assert "auth_token=lambda" not in text
    assert "api_key=lambda" not in text
    for f in DESIGN_AI_FILES:
        assert "runtime_messages" in f.read_text(encoding="utf-8"), (
            f"{f}: Anthropic design line does not record migration_path runtime_messages"
        )


def test_fixtures_record_a_selector_on_every_mantle_row() -> None:
    import json

    for fixture in (PLUGIN_ROOT / "fixtures" / "aws-design-ai").glob("*/aws-design-ai.json"):
        design = json.loads(fixture.read_text(encoding="utf-8"))
        for row in design.get("ai_architecture", {}).get("bedrock_models", []):
            path = row.get("migration_path", "")
            if path.startswith("mantle"):
                assert row.get("mantle_selector") in MANTLE_SELECTOR_ENUM, (
                    f"{fixture}: mantle row {row.get('aws_model_id')} lacks a valid mantle_selector"
                )
            else:
                assert "mantle_selector" not in row, (
                    f"{fixture}: non-mantle row {row.get('aws_model_id')} must not carry mantle_selector"
                )
