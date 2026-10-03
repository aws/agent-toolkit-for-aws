"""Execute the actual evaluator snippets and validate Astra handoff contracts."""
import json
import re
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
])
def test_gcp_generated_mantle_target_uses_real_sdk_wire_contract(region, api_path, endpoint, monkeypatch):
    """Execute the actual generation template with the real SDK and offline HTTP."""
    import httpx
    import openai
    import aws_bedrock_token_generator

    path = PLUGIN / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-ai.md"
    section = path.read_text().split("## Step 2: Generate Test Comparison Harness", 1)[1].split(
        "## Step 3:", 1)[0]
    code = textwrap.dedent(re.search(r"  ```python\n(.*?)\n  ```", section, re.S).group(1))
    code = (code.replace("{target_region}", region)
            .replace("{aws_model_id}", "openai.gpt-6-astra")
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

    real_client = openai.BedrockOpenAI
    with httpx.Client(transport=httpx.MockTransport(transport)) as http_client:
        monkeypatch.setattr(aws_bedrock_token_generator, "provide_token",
                            lambda **kwargs: "fixture-token")
        monkeypatch.setattr(openai, "BedrockOpenAI",
                            lambda **kwargs: real_client(http_client=http_client, **kwargs))
        ns = {}
        exec(compile(code, str(path), "exec"), ns)  # nosec B102 - committed generator template
        assert ns["call_bedrock"]("ping") == "answer"
    assert len(requests) == 1
    assert str(requests[0].url) == f"https://bedrock-mantle.{region}.api.aws/openai/v1/{endpoint}"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "openai.gpt-6-astra"
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
