"""Execute the actual evaluator snippets and validate Astra handoff contracts."""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import image_input
import preflight_bedrock

PLUGIN = Path(__file__).resolve().parents[3]
EVALUATOR = PLUGIN / "agents/llm2bedrock-prompt-evaluator.md"


def snippet(section, end):
    text = EVALUATOR.read_text().split(section, 1)[1].split(end, 1)[0]
    return re.search(r"python - <<'PY'\n(.*?)\nPY\n", text, re.S).group(1)


def clients(monkeypatch):
    responses = Mock(return_value=SimpleNamespace(output_text="answer"))
    chat = Mock(return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content="answer"))]))
    runtime = Mock(return_value={"output": {"message": {"content": [{"text": "answer"}]}}})
    client = SimpleNamespace(responses=SimpleNamespace(create=responses),
                             chat=SimpleNamespace(completions=SimpleNamespace(create=chat)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(BedrockOpenAI=lambda **k: client))
    monkeypatch.setitem(sys.modules, "aws_bedrock_token_generator",
                        SimpleNamespace(provide_token=lambda **k: "test-token"))
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: SimpleNamespace(converse=runtime))
    return responses, chat, runtime


@pytest.mark.parametrize("surface", ["responses", "chat_completions"])
def test_astra_connectivity_uses_selected_mantle_api(surface, monkeypatch):
    responses, chat, runtime = clients(monkeypatch)
    code = snippet("# 6a. Mantle connectivity", "# 7. Load golden")
    code = code.replace("<TARGET_MODEL_ID>", "openai.gpt-6-astra").replace("<TARGET_API_SURFACE>", surface)
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed test fixture
    selected = chat if surface == "chat_completions" else responses
    assert selected.call_args.kwargs["model"] == "openai.gpt-6-astra"
    assert selected.call_count == 1
    runtime.assert_not_called()
    (responses if surface == "chat_completions" else chat).assert_not_called()


@pytest.mark.parametrize("mid,surface,endpoint", [
    ("openai.gpt-6-astra", "responses", "responses"),
    ("openai.gpt-6-astra", "chat_completions", "chat"),
    ("us.openai.gpt-6-astra", "responses", "runtime"),
    ("global.openai.gpt-6-astra", "responses", "runtime"),
    ("openai.gpt-5.6-sol", "responses", "responses"),
    ("us.openai.gpt-5.6-sol", "responses", "runtime"),
])
def test_golden_loop_preserves_endpoint_images_and_resume(mid, surface, endpoint, monkeypatch, tmp_path):
    responses, chat, runtime = clients(monkeypatch)
    calls = {"responses": responses, "chat": chat, "runtime": runtime}
    data = tmp_path / ".saws-migrate/golden-dataset"
    out = tmp_path / ".saws-migrate/eval-results"
    data.mkdir(parents=True)
    out.mkdir(parents=True)
    image = tmp_path / "case.jpg"
    image.write_bytes(b"image-bytes")
    (data / "prompts.jsonl").write_text(json.dumps({
        "id": "case-1", "user_prompt": "describe", "system_prompt": "be concise",
        "image_path": str(image), "assistant_response": "source answer"}) + "\n")
    code = snippet("# 10. Run golden prompt evaluation", "# 11. Score")
    code = (code.replace("<TARGET_MODEL_ID>", mid).replace("<TARGET_API_SURFACE>", surface)
            .replace("<scriptsDir>", str(Path(__file__).parent)).replace("<repo>", str(tmp_path)))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed test fixture
    result = json.loads((out / "raw_results.jsonl").read_text())
    assert result["status"] == "success" and result["bedrock_response"] == "answer"
    call = calls[endpoint].call_args.kwargs
    assert call.get("model", call.get("modelId")) == mid
    if endpoint == "responses":
        assert call["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        assert call["instructions"] == "be concise"
    elif endpoint == "chat":
        assert call["messages"][0] == {"role": "system", "content": "be concise"}
        assert call["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    else:
        assert call["messages"][0]["content"][0]["image"]["format"] == "jpeg"
    for name, spy in calls.items():
        assert spy.call_count == (1 if name == endpoint else 0)
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - exercise actual resume guard
    assert calls[endpoint].call_count == 1


def test_golden_mantle_throttle_returns_partial_without_scoring_error(monkeypatch, tmp_path):
    responses, _, runtime = clients(monkeypatch)
    error = RuntimeError("throttled")
    error.status_code = 429
    responses.side_effect = error
    import time
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    data = tmp_path / ".saws-migrate/golden-dataset"
    out = tmp_path / ".saws-migrate/eval-results"
    data.mkdir(parents=True)
    out.mkdir(parents=True)
    (data / "prompts.jsonl").write_text(json.dumps({"id": "p", "user_prompt": "ping"}) + "\n")
    code = snippet("# 10. Run golden prompt evaluation", "# 11. Score")
    code = (code.replace("<TARGET_MODEL_ID>", "openai.gpt-6-astra")
            .replace("<TARGET_API_SURFACE>", "responses")
            .replace("<scriptsDir>", str(Path(__file__).parent)).replace("<repo>", str(tmp_path)))
    ns = {}
    exec(compile(code, str(EVALUATOR), "exec"), ns)  # nosec B102 - committed test fixture
    assert ns["throttled_out"] is True
    assert responses.call_count == 6
    assert (out / "raw_results.jsonl").read_text() == ""
    runtime.assert_not_called()


def test_chat_image_helper_validates_missing_bytes():
    with pytest.raises(ValueError, match="raw image bytes"):
        image_input.chat_message("describe", "case.jpg")
    assert image_input.chat_message("text")["content"] == [{"type": "text", "text": "text"}]


@pytest.mark.parametrize("source,target,expected", [(60, 60, 0), (60, 66, 10), (120, 60, -50), (0, 60, None)])
@pytest.mark.parametrize("skill", ["gcp-to-aws", "azure-to-aws"])
def test_roi_executes_rate_derived_formula(source, target, expected, skill):
    text = (PLUGIN / "skills" / skill / "references/phases/estimate/estimate-ai.md").read_text()
    roi = text.split("## Part 5: ROI Analysis", 1)[1].split("## Part 6:", 1)[0]
    code = re.search(r"```python\n(.*?)\n```", roi, re.S).group(1)
    ns = {"source_monthly": source, "bedrock_monthly": target}
    exec(compile(code, "ROI formula", "exec"), ns)  # nosec B102 - committed formula
    assert ns["percentage_difference"] == expected
    assert ns["monthly_difference"] == target - source
    assert "mark the source comparison unavailable" in roi
    assert "projected cost is **about 10% higher**" not in roi


def test_api_handoff_paths_and_real_evaluator_classifier_are_consistent():
    helper = (PLUGIN / "skills/llm-to-bedrock/references/helpers/behavior-delta-detection/behavior-delta-detection.md").read_text()
    reference = (PLUGIN / "skills/llm-to-bedrock/references/helpers/behavior-delta-detection/references/openai-to-bedrock.md").read_text()
    assert "Same-vendor GPT endpoint and API deltas" in helper
    assert "## Same-vendor GPT endpoint and API deltas" in reference
    for rel in ["skills/llm-to-bedrock/SKILL.md", "skills/gcp-to-aws/references/phases/design/design-ai.md",
                "skills/gcp-to-aws/references/phases/generate/generate-ai.md",
                "skills/gcp-to-aws/references/vendored/ai/ai-openai-to-bedrock.md"]:
        assert "mantle_openai_chat" in (PLUGIN / rel).read_text(), rel
    assert preflight_bedrock.is_mantle_model("openai.gpt-6-astra")
    assert not preflight_bedrock.is_mantle_model("global.openai.gpt-6-astra")
    assert "from preflight_bedrock import is_mantle_model" in EVALUATOR.read_text()


@pytest.mark.parametrize("path,ids,expected", [
    (None, ["openai.gpt-6-astra"], "mantle_openai_responses"),
    ("", ["openai.gpt-5.6-sol"], "mantle_openai_responses"),
    (None, ["us.openai.gpt-6-astra"], "converse"),
    (None, ["global.openai.gpt-6-astra"], "converse"),
    ("mantle_openai_chat", ["openai.gpt-6-astra"], "mantle_openai_chat"),
    ("mantle_openai_responses", ["openai.gpt-6-astra"], "mantle_openai_responses"),
    ("runtime_openai_cris", ["us.openai.gpt-6-astra"], "runtime_openai_cris"),
    ("mantle_messages", ["anthropic.claude-sonnet-5"], "mantle_messages"),
])
def test_dispatch_and_resume_share_api_default(path, ids, expected):
    selected = preflight_bedrock.normalize_api_path(path, ids)
    assert selected == expected
    assert preflight_bedrock.normalize_api_path(path, ids) == selected


def test_mixed_or_empty_legacy_targets_require_resolution():
    with pytest.raises(ValueError, match="Mixed Mantle and runtime"):
        preflight_bedrock.normalize_api_path(None, ["openai.gpt-6-astra", "amazon.nova-lite-v1:0"])
    with pytest.raises(ValueError, match="No validated target"):
        preflight_bedrock.normalize_api_path(None, [])


def test_c3_and_c5_use_shared_normalization_instructions():
    skill = (PLUGIN / "skills/llm-to-bedrock/SKILL.md").read_text()
    before_dispatch = skill.split("### C0", 1)[0]
    gate = skill.split("**Gate (a.5)", 1)[1].split("**Gate (b)", 1)[0]
    assert "normalize_api_path" in before_dispatch
    assert "Target API path: <resolved_api_path" in before_dispatch
    assert "Reuse" in gate and "resolved_api_path" in gate
    assert 'field is\nabsent), set `rewrite_strategy = "converse"`' not in gate


@pytest.mark.parametrize("name", ["ai-openai-to-bedrock.md", "ai-model-lifecycle.md",
                                  "ai-migration-guardrails.md", "bedrock-quotas.md"])
def test_astra_shared_contract_survives_each_vendored_consumer(name):
    canonical = (PLUGIN / "skills/shared/ai" / name).read_bytes()
    assert b"Astra" in canonical
    for skill in ["gcp-to-aws", "azure-to-aws"]:
        assert (PLUGIN / "skills" / skill / "references/vendored/ai" / name).read_bytes() == canonical


@pytest.mark.parametrize("skill", ["gcp-to-aws", "azure-to-aws"])
def test_astra_policy_has_consumer_local_facts_and_prices(skill):
    refs = PLUGIN / "skills" / skill / "references/shared"
    facts = (refs / "openai-on-bedrock.md").read_text()
    prices = (refs / "pricing-cache.md").read_text()
    assert "openai.gpt-6-astra" in facts and "us-west-2" in facts
    assert "30m cache write" in prices and "GPT-6 Astra" in prices
    assert "Global CRIS" in prices and "82.50" in prices


def test_shared_astra_paths_reach_azure_schema_and_generator():
    refs = PLUGIN / "skills/azure-to-aws/references"
    for relative in ["phases/design/design-ai.md", "shared/schema-design-aws-ai.md",
                     "phases/generate/generate-artifacts-ai.md"]:
        text = (refs / relative).read_text()
        assert "mantle_openai_chat" in text, relative
        assert "runtime_openai_cris" in text, relative
    generator = (refs / "phases/generate/generate-artifacts-ai.md").read_text()
    row = next(line for line in generator.splitlines() if line.startswith("| `mantle_openai_responses`"))
    assert "mantle_openai_chat" in row and "migrate_to_mantle.sh" in row


@pytest.mark.parametrize("model_id,region,allowed", [
    ("us.openai.gpt-6-astra", "us-east-1", True),
    ("global.openai.gpt-6-astra", "eu-west-1", True),
    ("openai.gpt-6-astra", "us-east-1", False),
])
def test_azure_runtime_parent_gate_contract(model_id, region, allowed):
    """Check real catalog witnesses against the declared parent/fragment contract.

    This is a source-contract test, not execution of the natural-language DSL.
    """
    catalog = json.loads((PLUGIN / "skills/agent-advisor/references/models/openai-bedrock-2026-09-09.json").read_text())
    runtime = catalog["models"]["openai_gpt_6_astra"]["paths"]["runtime_converse"]
    witness = {"aws_model_id": model_id, "migration_path": "runtime_openai_cris", "model_change": False}
    assert (region in runtime["inference_profile_regions"].get(witness["aws_model_id"], [])) is allowed
    refs = PLUGIN / "skills/azure-to-aws/references"
    for parent in ["phases/design/design.md", "phases/generate/generate.md"]:
        text = (refs / parent).read_text().split("---", 2)[1]
        rule = next(line for line in text.splitlines() if "runtime_openai_cris accepts documented" in line)
        assert "bare proprietary openai.gpt-* IDs use Mantle only" in rule
        assert "Astra us./global." in rule and "caller-region checks" in rule
        assert "no proprietary openai.gpt-* model ID is paired" not in text
    schema = (refs / "shared/schema-design-aws-ai.md").read_text()
    assert "**`code_migration`** — `migration_path`" in schema


def test_azure_final_recommendation_uses_computed_roi():
    text = (PLUGIN / "skills/azure-to-aws/references/phases/estimate/estimate-ai.md").read_text()
    final = text.split("## Part 7: Migration Recommendation", 1)[1].split("## Output", 1)[0]
    assert "computed Part 5 result, not a fixed premium" in final
    assert "source comparison is unavailable" in final
    assert "~10% higher" not in final and "costs ~10% more" not in final
