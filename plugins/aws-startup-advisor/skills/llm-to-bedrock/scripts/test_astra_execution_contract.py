"""Execute the actual evaluator snippets and validate Astra handoff contracts."""
import base64
import json
import re
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

import image_input
import preflight_bedrock
import bedrock_pricing
import iam_policy

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
    messages = Mock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type="text", text="answer")], stop_reason="end_turn"))
    client = SimpleNamespace(responses=SimpleNamespace(create=responses),
                             chat=SimpleNamespace(completions=SimpleNamespace(create=chat)))
    # The Messages client is used as a context manager (`with create_messages_client(...)`).
    anth = MagicMock()
    anth.__enter__.return_value = anth
    anth.messages.create = messages
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        BedrockOpenAI=lambda **k: client, OpenAI=lambda **k: client))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **k: anth))
    monkeypatch.setitem(sys.modules, "aws_bedrock_token_generator",
                        SimpleNamespace(provide_token=lambda **k: "test-token"))
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: SimpleNamespace(converse=runtime))
    return responses, chat, runtime, messages


@pytest.mark.parametrize("surface", ["responses", "chat_completions"])
@pytest.mark.parametrize("mid", ["openai.gpt-6-astra", "us.openai.gpt-6-astra",
                                "global.openai.gpt-6-astra"])
def test_astra_connectivity_uses_selected_openai_api(surface, mid, monkeypatch):
    responses, chat, runtime, messages = clients(monkeypatch)
    code = snippet("# 6a. OpenAI-compatible connectivity", "# 7. Load golden")
    code = code.replace("<TARGET_MODEL_ID>", mid).replace("<TARGET_API_SURFACE>", surface)
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed test fixture
    selected = chat if surface == "chat_completions" else responses
    assert selected.call_args.kwargs["model"] == mid
    assert selected.call_count == 1
    runtime.assert_not_called()
    messages.assert_not_called()
    (responses if surface == "chat_completions" else chat).assert_not_called()


@pytest.mark.parametrize("mid", ["global.anthropic.claude-sonnet-5", "us.anthropic.claude-opus-5.5"])
def test_runtime_messages_connectivity_snippet_uses_the_messages_client(mid, monkeypatch, capsys):
    # §6b is the Messages counterpart of §6a; execute the committed heredoc so a typo
    # in the evaluator prose cannot ship unnoticed.
    responses, chat, runtime, messages = clients(monkeypatch)
    code = snippet("# 6b. Runtime Anthropic Messages connectivity", "# 7. Load golden")
    code = code.replace("<TARGET_MODEL_ID>", mid).replace("<scriptsDir>", str(Path(__file__).parent))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed test fixture
    assert messages.call_count == 1
    assert messages.call_args.kwargs["model"] == mid
    assert messages.call_args.kwargs["messages"] == [{"role": "user", "content": "ping"}]
    assert "OK: answer" in capsys.readouterr().out
    responses.assert_not_called()
    chat.assert_not_called()
    runtime.assert_not_called()


def test_runtime_messages_vision_snippet_sends_a_base64_source_block(monkeypatch, capsys):
    import io
    import urllib.request
    responses, chat, runtime, messages = clients(monkeypatch)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"test-image"))
    code = snippet("# 9.5b Runtime Anthropic Messages vision", "# 10. Run golden")
    code = code.replace("<TARGET_MODEL_ID>", "global.anthropic.claude-sonnet-5")
    code = code.replace("<scriptsDir>", str(Path(__file__).parent))
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed smoke snippet
    call = messages.call_args.kwargs
    assert call["model"] == "global.anthropic.claude-sonnet-5"
    image_block, text_block = call["messages"][0]["content"]
    assert image_block["type"] == "image"
    assert image_block["source"] == {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(b"test-image").decode()}
    assert text_block == {"type": "text", "text": "Describe this image briefly."}
    assert "VISION_OK: answer" in capsys.readouterr().out
    responses.assert_not_called()
    chat.assert_not_called()
    runtime.assert_not_called()


@pytest.mark.parametrize("mid,surface,endpoint", [
    ("openai.gpt-6-astra", "responses", "responses"),
    ("openai.gpt-6-astra", "chat_completions", "chat"),
    ("us.openai.gpt-6-astra", "converse", "runtime"),
    ("global.openai.gpt-6-astra", "converse", "runtime"),
    ("us.openai.gpt-6-astra", "responses", "responses"),
    ("global.openai.gpt-6-astra", "chat_completions", "chat"),
    ("openai.gpt-5.6-sol", "responses", "responses"),
    ("openai.gpt-6-astra", "legacy_mantle", "responses"),
    ("openai.gpt-5.6-sol", "legacy_mantle", "responses"),
    ("us.openai.gpt-5.6-sol", "converse", "runtime"),
    ("global.anthropic.claude-sonnet-5", "messages", "messages"),
])
def test_golden_loop_preserves_endpoint_images_and_resume(mid, surface, endpoint, monkeypatch, tmp_path):
    responses, chat, runtime, messages = clients(monkeypatch)
    if surface == "legacy_mantle":
        path = preflight_bedrock.normalize_api_path("mantle", [mid])
        surface = ("chat_completions" if path.endswith("_openai_chat") else
                   "responses" if path.endswith("_openai_responses") else "converse")
    calls = {"responses": responses, "chat": chat, "runtime": runtime, "messages": messages}
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
    elif endpoint == "messages":
        # Anthropic Messages shape: base64 `source` block (not a data URL), top-level `system`.
        image_block = call["messages"][0]["content"][0]
        assert image_block["type"] == "image"
        assert image_block["source"]["media_type"] == "image/jpeg"
        assert image_block["source"]["type"] == "base64"
        assert call["messages"][0]["content"][1] == {"type": "text", "text": "describe"}
        assert call["system"] == "be concise"
    else:
        assert call["messages"][0]["content"][0]["image"]["format"] == "jpeg"
    for name, spy in calls.items():
        assert spy.call_count == (1 if name == endpoint else 0)
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - exercise actual resume guard
    assert calls[endpoint].call_count == 1


@pytest.mark.parametrize("mid", ["openai.gpt-6-astra", "global.openai.gpt-6-astra"])
@pytest.mark.parametrize("surface", ["responses", "chat_completions"])
def test_golden_openai_throttle_returns_partial_without_scoring_error(mid, surface, monkeypatch, tmp_path):
    responses, chat, runtime, messages = clients(monkeypatch)
    selected = chat if surface == "chat_completions" else responses
    error = RuntimeError("throttled")
    error.status_code = 429
    selected.side_effect = error
    import time
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    data = tmp_path / ".saws-migrate/golden-dataset"
    out = tmp_path / ".saws-migrate/eval-results"
    data.mkdir(parents=True)
    out.mkdir(parents=True)
    (data / "prompts.jsonl").write_text(json.dumps({"id": "p", "user_prompt": "ping"}) + "\n")
    code = snippet("# 10. Run golden prompt evaluation", "# 11. Score")
    code = (code.replace("<TARGET_MODEL_ID>", mid)
            .replace("<TARGET_API_SURFACE>", surface)
            .replace("<scriptsDir>", str(Path(__file__).parent)).replace("<repo>", str(tmp_path)))
    ns = {}
    exec(compile(code, str(EVALUATOR), "exec"), ns)  # nosec B102 - committed test fixture
    assert ns["throttled_out"] is True
    assert selected.call_count == 6
    assert (out / "raw_results.jsonl").read_text() == ""
    runtime.assert_not_called()


@pytest.mark.parametrize("surface,path", [
    ("converse", "runtime_openai_cris"),
    ("responses", "runtime_openai_responses"), ("chat_completions", "runtime_openai_chat"),
])
def test_explicit_runtime_api_survives_normalization(surface, path):
    assert preflight_bedrock.normalize_api_path(
        "runtime_openai_cris", ["global.openai.gpt-6-astra"], surface) == path
    with pytest.raises(ValueError, match="Unknown runtime API"):
        preflight_bedrock.normalize_api_path("runtime_openai_cris", [], "unknown")


def test_runtime_openai_cris_without_api_fails_closed():
    """A runtime_openai_cris plan with no recorded API must never resolve to Converse."""
    with pytest.raises(ValueError, match="never the implicit default"):
        preflight_bedrock.normalize_api_path("runtime_openai_cris", ["us.openai.gpt-6-astra"], None)
    # The same rule holds for the snippet SKILL.md tells the orchestrator to run.
    skill = (PLUGIN / "skills/llm-to-bedrock/SKILL.md").read_text()
    block = skill.split("### The context block", 1)[1]
    code = re.search(r"```python\n(.*?)\n```", block, re.S).group(1)
    code = code.replace("<absolute path to $SCRIPTS>", str(Path(__file__).parent))
    ns = {"plan_migration_path": "runtime_openai_cris",
          "validated_target_model_ids": ["us.openai.gpt-6-astra"], "plan_runtime_api": None}
    with pytest.raises(ValueError, match="never the implicit default"):
        exec(compile(code, "SKILL.md context block", "exec"), ns)  # nosec B102 - committed snippet
    ns["plan_runtime_api"] = "responses"
    exec(compile(code, "SKILL.md context block", "exec"), ns)  # nosec B102 - committed snippet
    assert ns["resolved_api_path"] == "runtime_openai_responses"
    assert "retains the Converse default otherwise" not in skill


@pytest.mark.parametrize("surface,mid", [
    ("responses", "global.openai.gpt-6-astra"),
    ("chat_completions", "global.openai.gpt-6-astra"),
    ("messages", "global.anthropic.claude-sonnet-5"),
])
def test_runtime_preflight_uses_selected_api(surface, mid, monkeypatch, capsys):
    responses, chat, runtime, messages = clients(monkeypatch)
    monkeypatch.setattr(preflight_bedrock, "fetch_bedrock_quotas", lambda region: [])
    assert preflight_bedrock.main(
        ["--region", "us-west-2", "--models", mid, "--runtime-api", surface]) == 0
    selected = {"responses": responses, "chat_completions": chat, "messages": messages}[surface]
    assert selected.call_args.kwargs["model"] == mid
    assert selected.call_count == 1
    for spy in (responses, chat, runtime, messages):
        if spy is not selected:
            spy.assert_not_called()
    assert json.loads(capsys.readouterr().out)["ok"]


def test_runtime_messages_client_uses_real_sdk_wire_contract(monkeypatch):
    """Real Anthropic SDK + offline HTTP: the probe POSTs to the runtime /anthropic endpoint
    with the minted token as a plain `x-api-key` string."""
    import httpx
    import aws_bedrock_token_generator
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "msg_fixture", "type": "message", "role": "assistant",
            "model": "global.anthropic.claude-sonnet-5",
            "content": [{"type": "text", "text": "answer"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}})

    real_factory = preflight_bedrock.create_messages_client
    monkeypatch.setattr(aws_bedrock_token_generator, "provide_token", lambda **k: "fixture-token")
    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        monkeypatch.setattr(
            preflight_bedrock, "create_messages_client",
            lambda region, max_retries=0: real_factory(
                region, http_client=http_client, max_retries=max_retries))
        assert preflight_bedrock.probe_runtime_messages_model(
            "global.anthropic.claude-sonnet-5", "us-west-2")["ok"]
    assert len(requests) == 1
    assert str(requests[0].url) == "https://bedrock-runtime.us-west-2.amazonaws.com/anthropic/v1/messages"
    assert requests[0].headers["x-api-key"] == "fixture-token"
    assert "anthropic-version" in requests[0].headers
    body = json.loads(requests[0].content)
    assert body["model"] == "global.anthropic.claude-sonnet-5"
    assert body["messages"] == [{"role": "user", "content": "ping"}]


def test_runtime_messages_token_is_minted_per_client(monkeypatch):
    """The pinned Anthropic SDK takes a string credential: each client gets a fresh token
    string from provide_token, never a callable."""
    ctor = Mock(return_value=MagicMock())
    provide_token = Mock(side_effect=["token-1", "token-2"])
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=ctor))
    monkeypatch.setitem(sys.modules, "aws_bedrock_token_generator",
                        SimpleNamespace(provide_token=provide_token))
    preflight_bedrock.create_messages_client("us-west-2")
    preflight_bedrock.create_messages_client("us-west-2")
    keys = [call.kwargs["api_key"] for call in ctor.call_args_list]
    assert keys == ["token-1", "token-2"]
    assert all(isinstance(key, str) for key in keys)
    assert provide_token.call_args_list[0].kwargs == {"region": "us-west-2"}
    for call in ctor.call_args_list:
        assert call.kwargs["base_url"] == "https://bedrock-runtime.us-west-2.amazonaws.com/anthropic"
        assert call.kwargs["max_retries"] == 0
        assert "http_client" not in call.kwargs


@pytest.mark.parametrize("surface", ["responses", "chat_completions"])
@pytest.mark.parametrize("mid", ["openai.gpt-6-astra", "global.openai.gpt-6-astra"])
def test_vision_smoke_preserves_openai_endpoint_and_surface(surface, mid, monkeypatch):
    import io
    import urllib.request
    responses, chat, runtime, messages = clients(monkeypatch)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"test-image"))
    code = snippet("# 9.5a OpenAI-compatible vision", "# 10. Run golden")
    code = code.replace("<TARGET_MODEL_ID>", mid).replace("<TARGET_API_SURFACE>", surface)
    exec(compile(code, str(EVALUATOR), "exec"), {})  # nosec B102 - committed smoke snippet
    selected = chat if surface == "chat_completions" else responses
    call = selected.call_args.kwargs
    assert call["model"] == mid
    if surface == "responses":
        assert call["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    else:
        assert call["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    runtime.assert_not_called()


@pytest.mark.parametrize("surface,endpoint", [
    ("responses", "responses"), ("chat_completions", "chat/completions"),
])
def test_runtime_openai_client_uses_real_sdk_wire_contract(surface, endpoint, monkeypatch):
    import httpx
    import openai
    import aws_bedrock_token_generator
    requests = []

    def transport(request):
        requests.append(request)
        if surface == "chat_completions":
            result = {"id": "chat-fixture", "object": "chat.completion", "created": 0,
                      "model": "global.openai.gpt-6-astra", "choices": [{
                          "index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": "answer"}}]}
        else:
            result = {"id": "response-fixture", "object": "response", "created_at": 0,
                      "model": "global.openai.gpt-6-astra", "status": "completed", "output": [{
                          "id": "message-fixture", "type": "message", "role": "assistant",
                          "status": "completed", "content": [{
                              "type": "output_text", "text": "answer", "annotations": []}]}]}
        return httpx.Response(200, json=result)

    real_client = openai.OpenAI
    monkeypatch.setattr(aws_bedrock_token_generator, "provide_token", lambda **k: "fixture-token")
    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        monkeypatch.setattr(openai, "OpenAI",
                            lambda **kwargs: real_client(http_client=http_client, **kwargs))
        assert preflight_bedrock.probe_runtime_openai_model(
            "global.openai.gpt-6-astra", "us-west-2", surface)["ok"]
    assert len(requests) == 1
    assert str(requests[0].url) == f"https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1/{endpoint}"
    assert requests[0].headers["Authorization"] == "Bearer fixture-token"
    body = json.loads(requests[0].content)
    assert body["model"] == "global.openai.gpt-6-astra"
    assert ("messages" in body) is (surface == "chat_completions")


def test_dispatch_and_rewriter_preserve_runtime_openai_strategy():
    skill = (PLUGIN / "skills/llm-to-bedrock/SKILL.md").read_text()
    rewriter = (PLUGIN / "agents/llm2bedrock-code-rewriter.md").read_text()
    assert "validated_target_model_ids, plan_runtime_api" in skill
    assert 'set `rewrite_strategy = "runtime_openai"`' in skill
    assert 'set `rewrite_strategy = "runtime_messages"`' in skill
    assert "messages for runtime_messages" in skill
    assert "Target API surface:" in skill
    lane = rewriter.split("### Runtime OpenAI lane", 1)[1].split(
        "### Runtime Anthropic Messages lane", 1)[0]
    assert "bedrock-runtime.{region}.amazonaws.com/openai/v1" in lane
    assert "chat.completions.create" in lane and "responses.create" in lane
    assert "OpenAI-to-boto3 dependency replacement" in lane
    messages_lane = rewriter.split("### Runtime Anthropic Messages lane", 1)[1].split(
        "### Mantle express lane", 1)[0]
    assert "bedrock-runtime.{region}.amazonaws.com/anthropic" in messages_lane
    assert 'base_url=f"https://bedrock-runtime.{REGION}.amazonaws.com/anthropic"' in messages_lane
    assert "provide_token(region=" in messages_lane
    assert "with bedrock_anthropic() as client" in messages_lane
    assert "messages.stream(" in messages_lane
    assert "bedrock:GetInferenceProfile" in messages_lane
    assert "api_key=lambda" not in messages_lane and "auth_token=lambda" not in messages_lane
    # Mantle is selector-gated now; the old 'default and smallest change' claim is gone.
    assert "remains the default and smallest change" not in rewriter
    assert "### Converse rewrite (default)" not in rewriter
    assert "### Converse rewrite (explicit `converse` plans)" in rewriter


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
    ("runtime_messages", ["global.anthropic.claude-sonnet-5"], "runtime_messages"),
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
    prices = (refs.parent / "vendored/ai/bedrock-pricing-cache.md").read_text()
    assert "openai.gpt-6-astra" in facts and "us-west-2" in facts
    assert "30-minute cache-write" in facts and "GPT-6 Astra" in prices
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
    catalog = json.loads((PLUGIN / "skills/shared/ai/models/openai-bedrock.json").read_text())
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


@pytest.mark.parametrize("skill", ["gcp-to-aws", "azure-to-aws"])
def test_final_recommendation_uses_computed_roi(skill):
    text = (PLUGIN / "skills" / skill / "references/phases/estimate/estimate-ai.md").read_text()
    final = text.split("## Part 7: Migration Recommendation", 1)[1].split("## Output", 1)[0]
    assert "computed Part 5 result, not a fixed premium" in final
    assert "source comparison is unavailable" in final
    assert "~10% higher" not in final and "costs ~10% more" not in final


@pytest.mark.parametrize("region", ["us-east-1", "us-west-2"])
@pytest.mark.parametrize("api_path,endpoint", [
    ("mantle_openai_chat", "chat/completions"),
    ("mantle_openai_responses", "responses"),
    ("runtime_openai_cris", "chat/completions"),
    ("runtime_openai_cris", "responses"),
])
def test_gcp_generated_target_uses_real_sdk_wire_contract(region, api_path, endpoint, monkeypatch):
    """Execute the actual generation template with the real SDK and offline HTTP."""
    import httpx
    import openai
    import aws_bedrock_token_generator

    path = PLUGIN / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-ai.md"
    section = path.read_text().split("## Step 2: Generate Test Comparison Harness", 1)[1].split(
        "## Step 3:", 1)[0]
    code = textwrap.dedent(re.search(r"  ```python\n(.*?)\n  ```", section, re.S).group(1))
    model_id = "global.openai.gpt-6-astra" if api_path == "runtime_openai_cris" else "openai.gpt-6-astra"
    code = (code.replace("{target_region}", region)
            .replace("{aws_model_id}", model_id)
            .replace("{required_client_api}", "chat_completions" if endpoint == "chat/completions" else "responses")
            .replace("{migration_path}", api_path))
    requests = []

    def transport(request):
        requests.append(request)
        if endpoint == "chat/completions":
            body = {"id": "chatcmpl-fixture", "object": "chat.completion", "created": 0,
                    "model": "openai.gpt-6-astra", "choices": [{
                        "index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "answer"}}]}
        else:
            body = {"id": "resp_fixture", "object": "response", "created_at": 0,
                    "model": "openai.gpt-6-astra", "status": "completed", "output": [{
                        "id": "msg_fixture", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{
                            "type": "output_text", "text": "answer", "annotations": []}]}]}
        return httpx.Response(200, json=body)

    client_name = "OpenAI" if api_path == "runtime_openai_cris" else "BedrockOpenAI"
    real_client = getattr(openai, client_name)
    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        monkeypatch.setattr(aws_bedrock_token_generator, "provide_token",
                            lambda **kwargs: "fixture-token")
        monkeypatch.setattr(openai, client_name,
                            lambda **kwargs: real_client(http_client=http_client, **kwargs))
        ns = {}
        exec(compile(code, str(path), "exec"), ns)  # nosec B102 - committed generator template
        assert ns["call_bedrock"]("ping") == "answer"
    assert len(requests) == 1
    host = f"bedrock-runtime.{region}.amazonaws.com" if api_path == "runtime_openai_cris" else f"bedrock-mantle.{region}.api.aws"
    assert str(requests[0].url) == f"https://{host}/openai/v1/{endpoint}"
    payload = json.loads(requests[0].content)
    assert payload["model"] == model_id
    assert ("messages" in payload) is (endpoint == "chat/completions")
    assert ("input" in payload) is (endpoint == "responses")
    assert "provider_adapter" not in code


def test_gcp_stage_two_artifacts_follow_mantle_and_runtime_contracts():
    path = PLUGIN / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-ai.md"
    text = path.read_text()
    route = text.split("## Step 0:", 1)[1].split("## Step 1M:", 1)[0]
    for api_path in ("mantle_openai_chat", "mantle_openai_responses", "runtime_openai_cris"):
        assert api_path in route
    assert 'starts with `"mantle"`' in route
    setup = text.split("## Step 3: Generate Bedrock Setup Script", 1)[1].split("## Step 3B", 1)[0]
    assert "bedrock-mantle:CreateInference" in setup
    assert "bedrock-mantle:CallWithBearerToken" in setup
    assert "test_comparison.py --target-only --quick" in setup
    assert "A Mantle selection must never run a Converse probe" in setup
    assert "also authorize that exact `application-inference-profile/" in setup
    assert "effective invocation target and IAM remain aligned" in setup
    monitoring = text.split("## Step 3F:", 1)[1]
    assert "omit the profile resource and its output for Mantle targets" in monitoring
    assert 'copy_from = "{verified_model_source_arn}"' in monitoring
    assert 'prefixed with "us." for US regions' not in monitoring
    assert "Astra supports application inference profiles only on runtime Converse" in monitoring


def test_gcp_report_lists_only_generated_profile_attribution():
    path = PLUGIN / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-report.md"
    text = path.read_text()
    controls = text.split("**Cost guardrails", 1)[1].split("**What the baseline", 1)[0]
    unconditional_rows = [line for line in controls.splitlines() if line.startswith("|")]
    assert any("Bedrock budget" in line for line in unconditional_rows)
    assert any("Cost anomaly detection" in line for line in unconditional_rows)
    assert not any("Inference profiles" in line for line in unconditional_rows)
    assert "actual generated `bedrock_monitoring.tf`" in controls
    assert "enabled `aws_bedrock_inference_profile` resource" in controls
    assert "`bedrock_inference_profile_arns` output" in controls
    assert "add profile attribution only when an eligible profile was generated" in text


def advisor_comparator():
    path = PLUGIN / "skills/agent-advisor/references/phases/migration-plan/migration-plan.md"
    section = path.read_text().split("### Step 3.5", 1)[1].split("### Phase D", 1)[0]
    code = re.search(r"```python\n(.*?)\n```", section, re.S).group(1)
    ns = {}
    exec(compile(code, str(path), "exec"), ns)  # nosec B102 - committed handoff algorithm
    return ns["matches_advisor_model"]


@pytest.mark.parametrize("prefix", ["us", "global"])
@pytest.mark.parametrize("as_arn", [False, True])
@pytest.mark.parametrize("unit_count", [1, 2])
def test_advisor_handoff_preserves_per_unit_runtime_profiles(prefix, as_arn, unit_count):
    matches = advisor_comparator()
    invocation = f"{prefix}.openai.gpt-6-astra"
    if as_arn:
        invocation = f"arn:aws:bedrock:us-west-2:111122223333:inference-profile/{invocation}"
    advisor = {"model": "openai.gpt-6-astra", "api_path": "runtime_converse",
               "invocation_model_id": invocation}
    units = [advisor]
    if unit_count == 2:
        units.append({"model": "openai.gpt-6-astra", "api_path": "mantle_openai_chat",
                      "invocation_model_id": "openai.gpt-6-astra"})
    plans = [(invocation, "runtime_openai_cris", "converse")]
    if unit_count == 2:
        plans.append(("openai.gpt-6-astra", "mantle_openai_chat", None))
    assert all(matches(unit, *plan) for unit, plan in zip(units, plans))
    assert matches(advisor, invocation, "runtime_openai_cris", None)
    for wrong_model, wrong_path, wrong_api in [
        ("us.openai.gpt-5.6-sol", "runtime_openai_cris", "converse"),
        ("openai.gpt-6-astra", "runtime_openai_cris", "converse"),
        (invocation, "mantle_openai_chat", "converse"),
        (invocation, "runtime_openai_cris", "responses"),
        (invocation, "runtime_openai_cris", "chat_completions"),
    ]:
        assert not matches(advisor, wrong_model, wrong_path, wrong_api)
    other_profile = "global.openai.gpt-6-astra" if prefix == "us" else "us.openai.gpt-6-astra"
    assert not matches(advisor, other_profile, "runtime_openai_cris", "converse")
    assert not matches({**advisor, "invocation_model_id": None},
                       invocation, "runtime_openai_cris", "converse")


def test_gcp_design_producer_uses_current_cost_and_quota_contract():
    text = (PLUGIN / "skills/gcp-to-aws/references/phases/design/design-ai.md").read_text()
    assessment = text.split("**Stay-or-migrate assessment per model:**", 1)[1].split(
        "**Model comparison table**", 1)[0]
    assert "verified source" in assessment and "unavailable" in assessment
    assert "report a modest cost increase rather than parity" not in assessment
    quota = text.split("**Quota risk assessment**", 1)[1].split("## Part 1B:", 1)[0]
    rows = [[cell.strip().strip('`"') for cell in line.strip("|").split("|")]
            for line in quota.splitlines() if line.startswith("|")]
    astra = next(row for row in rows if "Astra runtime" in row[1])
    assert astra[0] == "medium" and astra[2] == "medium" and "10" in astra[1]
    assert not any("other (1× burndown)" in row[1] for row in rows)


@pytest.mark.parametrize("model,path", [
    ("openai.gpt-6-astra", "mantle_openai_chat"),
    ("openai.gpt-oss-120b-1:0", "runtime_converse"),
    ("anthropic.claude-sonnet-5", "mantle_messages"),
])
def test_advisor_handoff_retains_exact_comparison_for_other_paths(model, path):
    matches = advisor_comparator()
    advisor = {"model": model, "api_path": path, "invocation_model_id": model}
    assert matches(advisor, model, path)
    assert not matches(advisor, model, "runtime_openai_cris")


@pytest.mark.parametrize("prefix,input_rate,output_rate", [
    ("us", .011, .055), ("global", .010, .050),
])
def test_astra_system_profile_arn_keeps_invocation_price_and_permissions(
        prefix, input_rate, output_rate, monkeypatch, capsys):
    arn = f"arn:aws:bedrock:us-west-2:111122223333:inference-profile/{prefix}.openai.gpt-6-astra"
    policy = iam_policy.generate_policy([arn], "us-west-2", "111122223333")
    assert policy["Statement"][0]["Resource"] == sorted([
        arn, "arn:aws:bedrock:*::foundation-model/openai.gpt-6-astra",
        "arn:aws:bedrock:us-west-2:111122223333:project/default",
    ])
    price = bedrock_pricing.lookup("us-west-2", arn)
    assert price["input_per_1k_usd"] == input_rate
    assert price["output_per_1k_usd"] == output_rate
    import boto3
    runtime = Mock()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(preflight_bedrock, "fetch_bedrock_quotas", lambda region: [])
    assert preflight_bedrock.main(["--region", "us-west-2", "--models", arn]) == 0
    assert runtime.converse.call_args.kwargs["modelId"] == arn
    verdict = json.loads(capsys.readouterr().out)
    assert "input tokens + 10 * output tokens" in verdict["models"][0]["quota_note"]
