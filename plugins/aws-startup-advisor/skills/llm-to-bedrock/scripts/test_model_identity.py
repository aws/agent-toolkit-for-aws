"""Identity checks that gate Track 2 baseline and adaptation shortcuts."""

import json
from pathlib import Path
# The CLI test invokes the committed sibling script with fixed argv and no shell.
import subprocess  # nosec B404
import sys

import pytest

from model_identity import same_model, same_model_family


@pytest.mark.parametrize("provider,source,target,expected", [
    ("anthropic", "claude-opus-4-8", "global.anthropic.claude-opus-5-5", False),
    ("anthropic", "claude-opus-5", "us.anthropic.claude-opus-5-5", False),
    ("anthropic", "claude-opus-5-5", "global.anthropic.claude-opus-5-5", True),
    ("anthropic", "claude-haiku-4-5-20251001", "us.anthropic.claude-haiku-4-5-20251001-v1:0", True),
    ("anthropic", "claude-haiku-4-5-20251001", "us.anthropic.claude-haiku-4-5-20251002-v1:0", False),
    ("anthropic", "claude-opus-5-5", "us.anthropic.claude-sonnet-5", False),
    ("anthropic", "claude-opus-latest", "anthropic.claude-opus-latest", False),
    ("anthropic", "claude-opus-4-*", "anthropic.claude-opus-5-5", False),
    ("anthropic", "claude-opus-5-5", "arn:aws:bedrock:us-east-1:123:application-inference-profile/test", False),
    ("anthropic", None, "anthropic.claude-opus-5-5", False),
    ("openai", "gpt-5.6-sol", "openai.gpt-5.6-sol", True),
    ("openai", "gpt-5.6-sol", "us.openapi.gpt-5.6-sol", False),
    ("openai", "gpt-5.5", "openai.gpt-5.6-sol", False),
    ("openai", "gpt-oss-120b", "openai.gpt-oss-120b", False),
    ("custom", "claude-opus-5-5", "anthropic.claude-opus-5-5", False),
])
def test_only_equal_resolved_identities_qualify(provider, source, target, expected):
    assert same_model(provider, source, target) is expected


def test_project_shortcut_requires_every_nonempty_mapping_to_match():
    same = {"source_model": "claude-opus-5-5", "aws_model_id": "global.anthropic.claude-opus-5-5"}
    changed = {"source_model": "claude-opus-4-8", "aws_model_id": "global.anthropic.claude-opus-5-5"}
    assert same_model_family("anthropic", [same])
    assert not same_model_family("anthropic", [same, changed])
    assert not same_model_family("anthropic", [])
    assert not same_model_family("anthropic", [{}])


def test_analyzer_cli_and_downstream_consumers_use_the_identity_gate():
    script = Path(__file__).with_name("model_identity.py")
    result = subprocess.run(  # nosec B603
        [sys.executable, str(script), "--provider", "anthropic",
         "--source", "claude-opus-4-8", "--target", "global.anthropic.claude-opus-5-5"],
        check=True, text=True, capture_output=True,
    )
    assert json.loads(result.stdout) == {"same_model": False}
    plugin = script.parents[3]
    for name in ["code-analyzer", "code-rewriter", "prompt-evaluator", "report-generator"]:
        assert "model_identity.py" in (plugin / "agents" / f"llm2bedrock-{name}.md").read_text()
    helper = script.parents[1] / "references/helpers/behavior-delta-detection"
    for path in [helper / "behavior-delta-detection.md",
                 plugin / "agents/llm2bedrock-code-analyzer.md",
                 plugin / "agents/llm2bedrock-code-rewriter.md"]:
        assert "references/anthropic-to-bedrock.md" in path.read_text()
    recipes = (helper / "references/anthropic-to-bedrock.md").read_text()
    for contract in ["sampling-parameters-removed", "adaptive-thinking-required",
                     "prefill-and-forced-tool-choice", "typed-response-and-history"]:
        assert f"## {contract}" in recipes
