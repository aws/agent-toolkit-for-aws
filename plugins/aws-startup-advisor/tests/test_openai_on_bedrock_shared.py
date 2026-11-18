"""The OpenAI-on-Bedrock fact base is one shared, vendored file (A4a-1, #566).

gcp-to-aws, azure-to-aws and bedrock-migration-assessment used to carry their own copies of
references/shared/openai-on-bedrock.md, and the azure copy had drifted (it called Codex a GA
Bedrock model). These tests pin the single source, its vendored copies, and the facts the merge
corrected against the model registry.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
CANONICAL = SKILLS / "shared" / "ai" / "openai-on-bedrock.md"
CONSUMERS = ("gcp-to-aws", "azure-to-aws", "bedrock-migration-assessment", "agent-advisor")
REGISTRY = SKILLS / "shared" / "ai" / "models" / "bedrock-model-registry.json"


def _text() -> str:
    return " ".join(CANONICAL.read_text().split())


@pytest.mark.parametrize("skill", CONSUMERS)
def test_each_consumer_vendors_the_shared_guide_and_keeps_no_private_copy(skill):
    vendored = SKILLS / skill / "references" / "vendored" / "ai" / "openai-on-bedrock.md"
    assert vendored.read_bytes() == CANONICAL.read_bytes()
    assert not (SKILLS / skill / "references" / "shared" / "openai-on-bedrock.md").exists()
    manifest = (SKILLS / skill / "references" / "vendored" / "README.md").read_text()
    assert "| `ai/openai-on-bedrock.md`" in manifest


def test_codex_is_described_as_the_agent_on_gpt_5_6_not_a_bedrock_model():
    text = _text()
    note = text[text.index("**Codex on Bedrock: the agent, not a model.**"):]
    note = note[:note.index("Never attach a Codex rate to an estimate.")]
    assert "openai-codex-on-amazon-bedrock" in note
    assert "There is no separate Codex model on Bedrock" in note
    assert "priced at the GPT-5.6 model it calls" in note
    assert not re.search(r"Codex on Bedrock is GA", text)


def test_in_and_us_gov_prefixes_are_scoped_to_the_models_the_registry_gives_them():
    models = json.loads(REGISTRY.read_text())["models"]
    with_in = {k for k, m in models.items() if "in" in m.get("inference_profiles", {})}
    with_gov = {k for k, m in models.items() if "us-gov" in m.get("inference_profiles", {})}
    assert with_in == with_gov == {"openai_gpt_5_6_terra", "openai_gpt_5_6_luna"}, \
        "registry changed: update the prefix wording in openai-on-bedrock.md and this test"
    text = _text()
    assert "Terra/Luna also `in.`, `us-gov.`" in text
    assert "Terra and Luna also have `in.` for India Regions and `us-gov.` for GovCloud" in text
    # The old wording gave `in.` to every GPT-5.6 model.
    assert "(or `in.` in India Regions)" not in text
    assert "(`us.` / `in.` / `global.` prefixed)" not in text


def test_gpt_5_6_runtime_caching_matches_the_registry():
    text = _text()
    assert "implicit prompt caching applies on all four APIs and explicit caching is Responses-only" in text
    assert "prompt caching is Responses-only on runtime" not in text
    catalog = (SKILLS / "shared" / "ai" / "models" / "openai-bedrock.json").read_text()
    assert ("implicit prompt caching applies on Responses/Chat Completions/Invoke/Converse "
            "and explicit caching is Responses-only") in catalog


def test_feature_table_codex_row_matches_the_guide():
    # Logan's review on #672: the feature table is read before the guide, so its Codex row
    # must give the same verdict.
    table = (SKILLS / "shared" / "ai" / "ai-openai-to-bedrock.md").read_text()
    row = next(line for line in table.splitlines() if line.startswith("| Codex "))
    assert "Not verified on Bedrock" not in row and "Do not price" not in row
    assert "coding agent on GPT-5.6" in row and "Price the GPT-5.6 model it calls" in row


def test_no_shared_file_points_at_the_deleted_private_copies():
    # The private copies are gone; a shared file vendored into a skill must name the vendored
    # path. (check-skill-refs skips shared/vendored files, so it cannot catch this.)
    for f in (SKILLS / "shared").rglob("*.md"):
        text = f.read_text()
        assert not re.search(r"(?<![/\w])(references/)?shared/openai-on-bedrock\.md", text), f
