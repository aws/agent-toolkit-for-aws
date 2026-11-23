"""Tests for bedrock-migration-assessment's Generate phase: the plan, the scaffolded artifacts, the generation-ai.json check, and the wiring."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
GENERATE_FIXTURES = ["bma-generate-same-model", "bma-generate-mixed", "bma-generate-tier-range"]
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")
DOC = (BMA / "references/phases/generate/generate-ai.md").read_text(encoding="utf-8")
RUN_ID = "5b0c3d1e-7a2f-4c6b-9e81-2d4f6a8b0c13"
DONE = {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed"}


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GEN = _module("bma_generate_ai", BMA / "scripts" / "generate-ai.py")
READY = _module("bma_generate_readiness_test", BMA / "scripts" / "readiness.py")


def _run(tmp_path: Path, fixture: str, generate: str = "in_progress", inputs_only: bool = False) -> Path:
    run = tmp_path / "bma-1116-1900"
    shutil.copytree(FIXTURES / fixture, run)
    if inputs_only:
        shutil.rmtree(run / "ai-migration")
        (run / "generation-ai.json").unlink()
    (run / ".phase-status.json").write_text(json.dumps({
        "migration_id": "bma-1116-1900", "run_id": RUN_ID, "last_updated": "2026-11-16T19:00:00Z", "current_phase": "generate",
        "run_mode": "decide_and_execute", "phases": {**DONE, "generate": generate}}))
    return run


def _codes(run: Path) -> set[str]:
    return {e["code"] for e in GEN.check(run).get("errors", [])}


def _edit(path: Path, change) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc, indent=2))


# --------------------------------------------------------------------------- copies and wiring

def test_loading_the_vendored_helpers_writes_no_bytecode_into_vendored() -> None:
    assert not list((BMA / "references/vendored").rglob("__pycache__"))


def test_contract_and_helper_copies_match_their_sources() -> None:
    assert (BMA / "references/contracts/generation-ai.schema.json").read_bytes() == \
        (PLUGIN_ROOT / "scripts/contracts/generation-ai.schema.json").read_bytes()
    for name in ("iam_policy.py", "model_catalog.py"):
        shared = (PLUGIN_ROOT / "skills/shared/ai" / name).read_bytes()
        assert (BMA / "references/vendored/ai" / name).read_bytes() == shared, name
        assert (PLUGIN_ROOT / "skills/llm-to-bedrock/scripts" / name).read_bytes() == shared, f"llm-to-bedrock {name} drifted from skills/shared/ai"


def test_vendored_model_catalog_finds_its_catalogs(monkeypatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    catalog = _module("bma_vendored_model_catalog", BMA / "references/vendored/ai/model_catalog.py")
    assert catalog.MODELS_DIR == BMA / "references/vendored/ai/models"
    assert catalog.catalog_models()
    llm = _module("llm_model_catalog_copy", PLUGIN_ROOT / "skills/llm-to-bedrock/scripts/model_catalog.py")
    assert llm.MODELS_DIR == PLUGIN_ROOT / "skills/llm-to-bedrock/references/vendored/ai/models"


def test_skill_wires_generate_as_an_opt_in_fifth_phase() -> None:
    assert "| Generate | Opt-in. Runs `references/phases/generate/generate-ai.md`" in SKILL
    step5 = SKILL.split("## Step 5: Generate", 1)[1]
    assert 'Only with `run_mode` `"decide_and_execute"`' in step5 and "scripts/generate-ai.py check" in step5
    assert 'set `phases.generate` to `"completed"` and `current_phase` to `"complete"`' in step5
    step4 = SKILL.split("## Step 4: Estimate", 1)[1].split("## Step 5", 1)[0]
    assert 'set `phases.estimate` to `"completed"` and `current_phase` to `"generate"`' in step4
    assert "--through discover|clarify|design|estimate|generate" in SKILL and "`generate_invalid`" in SKILL
    discover = (BMA / "references/phases/discover/discover.md").read_text()
    assert '"estimate": "pending", "generate": "pending" }' in discover
    assert "Generate is not in this skill" not in SKILL + (BMA / "references/phases/estimate/estimate-ai.md").read_text()


def test_every_reset_also_resets_generate() -> None:
    step0 = SKILL.split("## Step 0: Resume or start", 1)[1].split("## Step 1", 1)[0]
    assert 'Treat an absent `phases.generate` as `"pending"`' in step0
    rule7 = step0.split("7. ", 1)[1].split("\n8. ", 1)[0]
    for reset in ("Estimate again", "Design again", "Change answers"):
        line = next(x for x in rule7.splitlines() if x.strip().startswith(f"- {reset}:"))
        assert "`phases.generate` to `\"pending\"`" in line, reset
    generate = next(x for x in rule7.splitlines() if x.strip().startswith("- Generate again:"))
    assert '`phases.generate` to `"in_progress"`' in generate and '"pending"' not in generate
    for step in ("## Step 2: Clarify", "## Step 3: Design", "## Step 4: Estimate"):
        assert "`phases.generate` to `\"pending\"`" in SKILL.split(step, 1)[1].split("## Step", 1)[0], step


def test_generate_doc_runs_plan_scaffold_and_check_without_temporary_files() -> None:
    for command in ("generate-ai.py plan $MIGRATION_DIR", "generate-ai.py scaffold $MIGRATION_DIR", "generate-ai.py check $MIGRATION_DIR"):
        assert command in DOC, command
    assert "Do not redirect it to a file" in DOC and "write nothing outside `$MIGRATION_DIR`" in DOC
    assert "never edits the user's code" in DOC and "llm-to-bedrock" in DOC
    assert "never show a key, a `.env` file, or a dotenv loader" in DOC
    assert "one line with no dollar amounts" in DOC
    contracts = json.loads((PLUGIN_ROOT / "scripts/artifact-contracts.json").read_text())["skills"]["bedrock-migration-assessment"]
    assert contracts["generation-ai.json"] == {"json_schema": "scripts/contracts/generation-ai.schema.json"}


# --------------------------------------------------------------------------- fixtures

@pytest.mark.parametrize("fixture", GENERATE_FIXTURES)
def test_fixtures_pass_the_check(fixture, tmp_path: Path) -> None:
    run = _run(tmp_path, fixture)
    assert GEN.check(run) == {"ok": True, "routes": len(GEN.build_plan(run)["routes"]),
                              "files": sorted(p.relative_to(run).as_posix() for p in (run / "ai-migration").rglob("*") if p.is_file())}


@pytest.mark.parametrize("fixture", GENERATE_FIXTURES)
def test_scaffold_reproduces_the_fixture_files(fixture, tmp_path: Path) -> None:
    run = _run(tmp_path, fixture)
    keep = {n: (run / "ai-migration" / n).read_bytes() for n in GEN.AGENT_FILES}
    before = {p.relative_to(run): p.read_bytes() for p in (run / "ai-migration").rglob("*") if p.is_file()}
    GEN.scaffold(run, GEN.build_plan(run))
    for name, data in keep.items():
        (run / "ai-migration" / name).write_bytes(data)
    assert {p.relative_to(run): p.read_bytes() for p in (run / "ai-migration").rglob("*") if p.is_file()} == before
    assert os.access(run / "ai-migration/setup_bedrock.sh", os.X_OK)


def test_same_model_plan_matches_hand_values(tmp_path: Path) -> None:
    plan = GEN.build_plan(_run(tmp_path, "bma-generate-same-model"))
    (route,) = plan["routes"]
    assert route["route_id"] == "gpt-4o__runtime-openai-cris__chat-completions" and route["kind"] == "client_config"
    assert route["base_url"] == "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1" and route["credential"] == "bedrock_token"
    assert route["source_call"] is None, "a 1.0 profile records no sdk_method, so there is no source caller"
    assert plan["budget"] == {"monthly_usd": 30, "basis": "point", "projected": 19.8, "services": ["Amazon Bedrock"]}  # ceil(19.8 * 1.5)
    assert plan["fixed"]["step_by_step_guide"] == {"languages": [], "primary_pattern": "direct_sdk", "files_to_modify": []}
    (entry,) = plan["fixed"]["artifacts_by_source"]
    assert entry["models"][0]["generated_files"] == sorted([f"ai-migration/routes/{route['route_id']}.py", "ai-migration/test_comparison.py",
                                                            "ai-migration/setup_bedrock.sh", "ai-migration/iam-policy.json",
                                                            "ai-migration/README.md", "ai-migration/prompts.json"])
    resources = plan["iam_policy"]["Statement"][0]["Resource"]
    assert "arn:aws:bedrock:us-east-1:ACCOUNT_ID:project/default" in resources


def test_mixed_plan_keeps_each_row_on_its_own_endpoint_and_grant(tmp_path: Path) -> None:
    plan = GEN.build_plan(_run(tmp_path, "bma-generate-mixed"))
    by_api = {r["required_client_api"]: r for r in plan["routes"]}
    assert by_api["responses"]["base_url"] == "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
    assert by_api["responses"]["aws_model_id"] == "openai.gpt-5.5" and by_api["responses"]["mantle_selector"] == "web_search"
    assert by_api["chat_completions"]["base_url"] == "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
    assert by_api["invoke"]["kind"] == "provider_adapter" and by_api["invoke"]["credential"] == "sigv4" and by_api["invoke"]["titan_embedding"]
    sids = {s["Sid"]: s for s in plan["iam_policy"]["Statement"]}
    assert {"BedrockMantleInference", "BedrockMantleCallWithBearerToken", "BedrockWebSearch"} <= set(sids)
    assert "arn:aws:bedrock:us-east-1:ACCOUNT_ID:project/default" in sids["BedrockInvokeModelScoped"]["Resource"]
    assert plan["budget"]["monthly_usd"] is None and plan["budget"]["basis"] == "no_projection"
    assert any("external_web_access" in d for d in plan["disclosures"])


def test_tier_range_plan_budgets_the_high_bound_and_grants_no_project(tmp_path: Path) -> None:
    plan = GEN.build_plan(_run(tmp_path, "bma-generate-tier-range"))
    kinds = {r["migration_path"]: r["kind"] for r in plan["routes"]}
    assert kinds == {"runtime_messages": "client_config", "converse": "provider_adapter"}
    assert plan["budget"] == {"monthly_usd": 858, "basis": "range_high", "projected": 572.0, "services": None}  # ceil(572 * 1.5)
    assert {q["quota_risk"] for q in plan["quota_flags"]} == {"high"} and len(plan["quota_flags"]) == 2
    policy = json.dumps(plan["iam_policy"])
    assert "project/default" not in policy and "bedrock-mantle" not in policy
    assert {(e["provider"], e["source_service"]) for e in plan["fixed"]["artifacts_by_source"]} == {("anthropic", "anthropic_api"), ("google", "gemini_api")}
    gemini = next(e for e in plan["fixed"]["artifacts_by_source"] if e["provider"] == "google")["models"][0]["generated_files"]
    assert "ai-migration/routes/gemini-2.5-flash__converse__converse.py" in gemini
    assert not any("claude-sonnet-5" in f for f in gemini), "a model's files are only the routes that serve it"


# --------------------------------------------------------------------------- rules

@pytest.mark.parametrize(("figures", "want"), [
    ({"cost_comparison": {"projected_bedrock_monthly": 19.8}, "projected_bedrock_monthly_range": {"low": 19.8, "high": 19.8}}, (30, "point")),
    ({"cost_comparison": {"projected_bedrock_monthly": 2.0}, "projected_bedrock_monthly_range": {"low": 2.0, "high": 2.0}}, (10, "point")),
    ({"cost_comparison": {"projected_bedrock_monthly": None}, "projected_bedrock_monthly_range": {"low": 2.86, "high": 572.0}}, (858, "range_high")),
    ({"cost_comparison": {"projected_bedrock_monthly": None}, "projected_bedrock_monthly_range": {"low": 1144.0, "high": None}}, (1716, "range_low_open_band")),
    ({"cost_comparison": {"projected_bedrock_monthly": None}, "projected_bedrock_monthly_range": {"low": None, "high": None}}, (None, "no_projection")),
    ({"cost_comparison": {"projected_bedrock_monthly": 20.0}, "projected_bedrock_monthly_range": {"low": 20.0, "high": 20.0}}, (30, "point")),
])
def test_budget_rule(figures, want) -> None:
    got = GEN.budget(figures, [{"billing": "amazon_bedrock"}, {"billing": "unconfirmed"}])
    assert (got["monthly_usd"], got["basis"], got["services"]) == (*want, ["Amazon Bedrock"])
    assert GEN.budget(figures, [{"billing": "amazon_bedrock"}, {"billing": "marketplace"}])["services"] is None


def _expected_kind(api: str, gateways: tuple[str, ...], path: str | None) -> str:
    if not gateways:
        return "client_config" if api in ("responses", "chat_completions", "messages") else "provider_adapter"
    if any(g != "openrouter" for g in gateways):
        return "gateway_config"
    if path in ("litellm", "keep_openrouter"):
        return "gateway_config"
    return "client_config" if api in ("responses", "chat_completions", "messages") else "provider_adapter"


@pytest.mark.parametrize(("api", "gateways", "path"), list(itertools.product(
    ("responses", "chat_completions", "messages", "converse", "invoke"),
    ((), ("openrouter",), ("litellm",), ("litellm", "openrouter")),
    (None, "same_model_runtime", "same_model_mantle", "direct", "litellm", "keep_openrouter"))))
def test_route_kind_first_match_covers_every_input(api, gateways, path) -> None:
    assert GEN.route_kind(api, list(gateways), path) == _expected_kind(api, gateways, path)


def test_route_ids_are_unique_and_file_safe_for_hostile_and_escape_like_inputs() -> None:
    models = ["a:b", "a_3ab", "a_5f3ab", "A:B", ".hidden", "gpt-4o", "gpt-4o", "gpt-4o", "ft:gpt-4o:acme:x", "openai/gpt-4o", "café", "a__b", ""]
    keys = [(m, "runtime_openai_cris", "chat_completions", "") for m in models] + [("gpt-4o", "runtime_openai_cris", "chat_completions", "web_search")]
    ids = GEN.route_ids(keys)
    assert len(set(ids)) == len(ids)
    for rid in ids:
        assert re.fullmatch(r"[a-z0-9_][a-z0-9._-]*", rid) or rid.startswith("__"), rid
        assert "/" not in rid and not rid.startswith(".")
    assert ids[5] == "gpt-4o__runtime-openai-cris__chat-completions"
    assert ids[6].endswith("__2") and ids[7].endswith("__3")


def test_endpoint_rule() -> None:
    assert GEN.endpoint("runtime_openai_cris", "responses", "eu-west-1") == ("bedrock-runtime", "https://bedrock-runtime.eu-west-1.amazonaws.com/openai/v1", "bedrock_token")
    assert GEN.endpoint("mantle_openai_chat", "chat_completions", "us-east-1")[1] == "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
    assert GEN.endpoint("mantle_messages", "messages", "us-east-1")[1] == "https://bedrock-mantle.us-east-1.api.aws/anthropic"
    assert GEN.endpoint("runtime_messages", "messages", "us-east-1")[1] == "https://bedrock-runtime.us-east-1.amazonaws.com/anthropic"
    for path, api in (("converse", "converse"), ("direct", "invoke"), ("gpt-oss", "converse"), ("runtime_openai_cris", "converse")):
        assert GEN.endpoint(path, api, "us-east-1") == ("bedrock-runtime", None, "sigv4")


def test_mantle_messages_gets_mantle_statements_not_runtime_invoke() -> None:
    routes = [{"aws_model_id": "anthropic.claude-sonnet-5", "required_client_api": "messages", "migration_path": "mantle_messages", "mantle_selector": "workspaces"},
              {"aws_model_id": "us.anthropic.claude-haiku-5-5", "required_client_api": "converse", "migration_path": "converse", "mantle_selector": None}]
    policy = GEN._policy(routes, "us-east-1")
    sids = [s["Sid"] for s in policy["Statement"]]
    assert "BedrockMantleInference" in sids and "BedrockMantleCallWithBearerToken" in sids
    assert "foundation-model/anthropic.claude-sonnet-5" not in json.dumps(policy)
    only = GEN._policy(routes[:1], "us-east-1")
    assert [s["Sid"] for s in only["Statement"]] == ["BedrockMantleInference", "BedrockMantleCallWithBearerToken"]


# --------------------------------------------------------------------------- generated code

def _stubs(monkeypatch):
    calls = SimpleNamespace(openai=[], anthropic=[], boto=[])
    responses = Mock(side_effect=lambda **k: SimpleNamespace(output_text=f"ok: {k['input']}"))
    chat = Mock(side_effect=lambda **k: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"ok: {k['messages'][-1]['content']}"))]))
    embeddings = Mock(return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 4)]))
    messages = Mock(return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")]))
    converse = Mock(return_value={"output": {"message": {"content": [{"text": "ok"}]}}})
    body = MagicMock()
    body.read.return_value = json.dumps({"embedding": [0.0] * 1024}).encode()
    invoke = Mock(return_value={"body": body})

    def openai_client(**kwargs):
        calls.openai.append(kwargs)
        return SimpleNamespace(responses=SimpleNamespace(create=responses), chat=SimpleNamespace(completions=SimpleNamespace(create=chat)),
                               embeddings=SimpleNamespace(create=embeddings))

    def anthropic_client(**kwargs):
        calls.anthropic.append(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=messages))

    def boto_client(service, **kwargs):
        calls.boto.append((service, kwargs))
        return SimpleNamespace(converse=converse, invoke_model=invoke)

    class Omit:
        def __eq__(self, other):
            return isinstance(other, Omit)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=openai_client, Omit=Omit))
    calls.Omit = Omit
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=anthropic_client))
    monkeypatch.setitem(sys.modules, "aws_bedrock_token_generator", SimpleNamespace(provide_token=lambda **k: f"token-{k['region']}"))
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=boto_client))
    genai = SimpleNamespace(Client=lambda **k: SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(text="ok")))))
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=genai))
    calls.spies = {"responses": responses, "chat_completions": chat, "messages": messages, "converse": converse, "invoke": invoke}
    return calls


def _route(**over) -> dict:
    base = {"route_id": "r", "workload_ids": ["w"], "call_sites": [("app/a.py", 1)], "source_model_id": "src", "region": "us-west-2",
            "aws_model_id": "us.openai.gpt-5.6-terra", "migration_path": "runtime_openai_cris", "required_client_api": "chat_completions",
            "base_url": "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1", "endpoint_assumption": "x", "mantle_requirement": None,
            "titan_embedding": False, "source_call": None, "mantle_selector": None}
    return {**base, **over}


def _load_route(text: str, tmp_path: Path, name: str = "route"):
    path = tmp_path / f"{name}.py"
    path.write_text(text)
    return _module(f"bma_test_route_{name}_{abs(hash(text))}", path)


@pytest.mark.parametrize(("api", "path", "mid", "base"), [
    ("responses", "mantle_openai_responses", "openai.gpt-5.5", "https://bedrock-mantle.us-west-2.api.aws/openai/v1"),
    ("chat_completions", "runtime_openai_cris", "us.openai.gpt-5.6-terra", "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"),
    ("messages", "runtime_messages", "us.anthropic.claude-sonnet-5", "https://bedrock-runtime.us-west-2.amazonaws.com/anthropic"),
    ("converse", "converse", "us.anthropic.claude-haiku-5-5", None),
    ("invoke", "direct", "amazon.titan-embed-text-v2:0", None),
])
def test_each_route_calls_only_its_api_with_its_model_and_base_url(api, path, mid, base, monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    module = _load_route(GEN.render_route(_route(required_client_api=api, migration_path=path, aws_model_id=mid, base_url=base,
                                                 titan_embedding=api == "invoke")), tmp_path, api)
    assert module.call_bedrock("hi") in ("ok", "ok: hi", "embedding:1024")
    spy = calls.spies[api]
    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs.get("model", kwargs.get("modelId")) == mid
    for other, s in calls.spies.items():
        if other != api:
            s.assert_not_called()
    if base:
        client = (calls.anthropic if api == "messages" else calls.openai)[-1]
        assert client["base_url"] == base and client["api_key"] == "token-us-west-2"
        if api != "messages":
            # The real SDK (openai 2.54.0) sends OPENAI_ORG_ID / OPENAI_PROJECT_ID as headers unless they are omitted.
            assert client["default_headers"] == {"OpenAI-Organization": calls.Omit(), "OpenAI-Project": calls.Omit()}
    else:
        assert calls.boto == [("bedrock-runtime", {"region_name": "us-west-2"})]
    if api == "messages":
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}] and kwargs["max_tokens"] == GEN.MAX_TOKENS
    if api == "converse":
        assert kwargs["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    if api == "invoke":
        assert json.loads(kwargs["body"]) == {"inputText": "hi"}


@pytest.mark.parametrize("mid", ["stability.sd3-5-large-v1:0", "cohere.embed-english-v3"])
def test_invoke_without_a_known_body_fails_visibly(mid, monkeypatch, tmp_path: Path) -> None:
    _stubs(monkeypatch)
    module = _load_route(GEN.render_route(_route(required_client_api="invoke", migration_path="direct", aws_model_id=mid, base_url=None)), tmp_path)
    with pytest.raises(NotImplementedError):
        module.call_bedrock("a cat")


@pytest.mark.parametrize(("source", "spy"), [(("openai_api", "responses"), "responses"), (("openai_api", "chat_completions"), "chat_completions"),
                                             (("anthropic_api", "messages"), "messages")])
def test_source_caller_uses_the_source_sdk_defaults(source, spy, monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    module = _load_route(GEN.render_route(_route(source_call=source)), tmp_path)
    assert module.call_source("hi") in ("ok", "ok: hi")
    assert calls.spies[spy].call_args.kwargs["model"] == "src"
    assert (calls.anthropic if spy == "messages" else calls.openai)[-1] == {}, "the source SDK reads its own environment; no key is passed"


def test_feature_flag_routes_source_bedrock_and_shadow(monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    module = _load_route(GEN.render_route(_route()), tmp_path)
    source = Mock(return_value="from-source")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert module.generate("hi", source) == "from-source" and calls.spies["chat_completions"].call_count == 0
    monkeypatch.setenv("AI_PROVIDER", "bedrock")
    assert module.generate("hi", source) == "ok: hi" and source.call_count == 1
    monkeypatch.setenv("AI_PROVIDER", "shadow")
    calls.spies["chat_completions"].side_effect = RuntimeError("down")
    assert module.generate("hi", source) == "from-source", "a failing shadow call never fails the source call"
    monkeypatch.setenv("AI_PROVIDER", "vertex_ai")
    with pytest.raises(ValueError):
        module.generate("hi", source)


def test_harness_runs_every_route_of_a_scaffolded_plan(monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    run = _run(tmp_path, "bma-generate-mixed")
    harness = _module("bma_test_harness", run / "ai-migration/test_comparison.py")
    out = tmp_path / "results.json"
    assert harness.main(["--target-only", "--quick", "--output", str(out)]) == 0
    report = json.loads(out.read_text())
    assert set(report["routes"]) == {r["route_id"] for r in GEN.build_plan(run)["routes"]}
    assert all(e["summary"]["passed"] and e["summary"]["bedrock_errors"] == 0 for e in report["routes"].values())
    for api in ("responses", "chat_completions", "invoke"):
        assert calls.spies[api].call_count == 1, api
    assert harness.main(["--output", str(out)]) == 0, "the prompts.json comparison passes when answers carry the traits"
    calls.spies["chat_completions"].side_effect = lambda **k: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="no"))])
    assert harness.main(["--output", str(out)]) == 1, "an answer missing its expected traits fails the route"
    assert not (run / "ai-migration/routes/__pycache__").exists(), "the harness writes no bytecode next to the route files"


def test_harness_fails_a_route_that_errors(monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    calls.spies["converse"].side_effect = RuntimeError("AccessDeniedException")
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    run = _run(tmp_path, "bma-generate-tier-range")
    harness = _module("bma_test_harness_fail", run / "ai-migration/test_comparison.py")
    out = tmp_path / "results.json"
    assert harness.main(["--target-only", "--quick", "--output", str(out)]) == 1
    summaries = {k: v["summary"]["passed"] for k, v in json.loads(out.read_text())["routes"].items()}
    assert summaries == {"claude-sonnet-5__runtime-messages__messages": True, "gemini-2.5-flash__converse__converse": False}


HOSTILE = 'x.py", 1),)\nimport os\nos.system("touch pwned")\n#'


def test_untrusted_strings_stay_inside_literals_in_python(tmp_path: Path) -> None:
    route = _route(call_sites=[(HOSTILE, 3)], workload_ids=["w'\nimport os"], source_model_id='m"""\nraise SystemExit',
                   endpoint_assumption="No Mantle\n'''\nimport os")
    text = GEN.render_route(route)
    tree = ast.parse(text)
    names = {t.id for node in tree.body if isinstance(node, ast.Assign) for t in node.targets}
    calls = [node for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    assert not calls, "no top-level call statement may come from data"
    assert {"ROUTE_ID", "CALL_SITES", "WORKLOAD_IDS", "SOURCE_MODEL", "ENDPOINT_NOTE"} <= names
    sites = next(node.value for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "CALL_SITES")
    assert ast.literal_eval(sites) == ((HOSTILE, 3),)


def test_untrusted_strings_stay_quoted_in_the_shell_script(tmp_path: Path) -> None:
    plan = {"region": "us-east-1", "migration_id": "bma-1116-1900", "budget": {"monthly_usd": 10, "services": ["Amazon Bedrock"]}, "compliance": ["hipaa"],
            "quota_flags": [{"aws_model_id": "q$(touch pwned)"}],
            "routes": [{"aws_model_id": "m$(touch pwned)`touch pwned2`", "endpoint": "bedrock-runtime", "billing": "unconfirmed"},
                       {"aws_model_id": "anthropic.$(touch pwned)", "endpoint": "bedrock-runtime", "billing": "marketplace"}]}
    script = tmp_path / "setup_bedrock.sh"
    script.write_text(GEN.render_setup(plan))
    (tmp_path / "iam-policy.json").write_text("{}")
    (tmp_path / "test_comparison.py").write_text("")
    result = subprocess.run(["bash", str(script)], cwd=tmp_path, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "pwned").exists() and not (tmp_path / "pwned2").exists()
    assert "Dry run only" in result.stdout and "HIPAA" in result.stdout and "m$(touch pwned)`touch pwned2` is not confirmed" in result.stdout


@pytest.mark.parametrize("fixture", GENERATE_FIXTURES)
def test_setup_dry_run_calls_no_aws_command(fixture, tmp_path: Path) -> None:
    run = _run(tmp_path, fixture)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "aws.log"
    for tool in ("aws", "python3"):
        (bin_dir / tool).write_text(f"#!/bin/sh\necho {tool} \"$@\" >> {log}\n")
        (bin_dir / tool).chmod(0o755)
    result = subprocess.run(["bash", str(run / "ai-migration/setup_bedrock.sh")], capture_output=True, text=True,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    assert not log.exists(), log.read_text() if log.exists() else ""
    assert "[dry run] aws iam create-policy" in result.stdout and "[dry run] python3" in result.stdout
    money = GEN.build_plan(run)["budget"]
    assert ("aws budgets create-budget" in result.stdout) == (money["monthly_usd"] is not None and money["services"] is not None)
    rejected = subprocess.run(["bash", str(run / "ai-migration/setup_bedrock.sh"), "--alert-email", 'x"@y'], capture_output=True, text=True,
                              env={"PATH": f"{bin_dir}:/usr/bin:/bin"})
    assert rejected.returncode == 2


FAKE_AWS = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(sys.argv[0] + ".log", "a") as f:
    f.write(json.dumps(args) + "\\n")
if args[:2] in (["iam", "get-policy"], ["budgets", "describe-budget"]):
    sys.exit(0 if args[0] in os.environ.get("FAKE_EXISTS", "").split(",") else 254)
if args[:2] == ["sts", "get-caller-identity"]:
    print("123456789012")
elif args[:2] == ["ce", "get-anomaly-monitors"]:
    print("0")
elif args[:2] == ["ce", "create-anomaly-monitor"]:
    print("arn:aws:ce::123456789012:anomalymonitor/abc")
"""


def test_setup_execute_sends_valid_json_and_the_real_account(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(FAKE_AWS.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    (bin_dir / "python3").write_text("#!/bin/sh\nexit 0\n")
    for tool in ("aws", "python3"):
        (bin_dir / tool).chmod(0o755)
    result = subprocess.run(["bash", str(run / "ai-migration/setup_bedrock.sh"), "--execute", "--alert-email", "ops@example.com"],
                            capture_output=True, text=True, env={"PATH": f"{bin_dir}:/usr/bin:/bin", "BUDGET_SERVICES": "Amazon Bedrock"})
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (bin_dir / "aws.log").read_text().splitlines()]
    by = {tuple(c[:2]): c for c in calls}
    policy = json.loads(by[("iam", "create-policy")][by[("iam", "create-policy")].index("--policy-document") + 1])
    assert "ACCOUNT_ID" not in json.dumps(policy) and "123456789012" in json.dumps(policy)
    budget = by[("budgets", "create-budget")]
    doc = json.loads(budget[budget.index("--budget") + 1])
    assert doc["BudgetLimit"] == {"Amount": "858", "Unit": "USD"} and doc["CostFilters"] == {"Service": ["Amazon Bedrock"]}
    notes = json.loads(budget[budget.index("--notifications-with-subscribers") + 1])
    assert {n["Notification"]["NotificationType"] for n in notes} == {"ACTUAL", "FORECASTED"}
    sub = by[("ce", "create-anomaly-subscription")]
    sub_doc = json.loads(sub[sub.index("--anomaly-subscription") + 1])
    assert sub_doc["MonitorArnList"] == ["arn:aws:ce::123456789012:anomalymonitor/abc"]
    assert sub_doc["Subscribers"] == [{"Type": "EMAIL", "Address": "ops@example.com"}]
    assert {tuple(c[:2]) for c in calls} == {("sts", "get-caller-identity"), ("bedrock", "get-inference-profile"), ("iam", "get-policy"),
                                             ("iam", "create-policy"), ("service-quotas", "list-service-quotas"),
                                             ("budgets", "describe-budget"), ("budgets", "create-budget"),
                                             ("ce", "get-anomaly-monitors"), ("ce", "create-anomaly-monitor"), ("ce", "create-anomaly-subscription")}


@pytest.mark.parametrize("fixture", GENERATE_FIXTURES)
def test_generated_python_and_json_parse(fixture) -> None:
    root = FIXTURES / fixture / "ai-migration"
    for path in root.rglob("*.py"):
        ast.parse(path.read_text())
    for path in root.rglob("*.json"):
        json.loads(path.read_text())
    subprocess.run(["bash", "-n", str(root / "setup_bedrock.sh")], check=True)


# --------------------------------------------------------------------------- check rejects

def _drop_model(run):
    _edit(run / "generation-ai.json", lambda g: g["migration_plan"]["models_to_migrate"].pop())


def _swap_pair(run):
    def change(g):
        a, b = g["artifacts_by_source"]
        a["models"], b["models"] = b["models"], a["models"]
    _edit(run / "generation-ai.json", change)


def _openrouter(run):
    _edit(run / "generation-ai.json", lambda g: g["artifacts_by_source"][0].update(provider="openrouter"))


def _source_default(run):
    _edit(run / "generation-ai.json", lambda g: g["rollback_plan"].update(default_value="vertex_ai"))


def _confidence(run):
    _edit(run / "generation-ai.json", lambda g: g["recommendation"].update(confidence="high"))


def _stale(run):
    (run / "ai-migration/routes/old-model__converse__converse.py").write_text("")


def _modified(run):
    path = run / "ai-migration/setup_bedrock.sh"
    path.write_text(path.read_text().replace("EXECUTE=0", "EXECUTE=1", 1))


def _missing(run):
    (run / "ai-migration/prompts.json").unlink()


def _secret(run):
    with (run / "ai-migration/README.md").open("a") as f:
        f.write("\nOPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx\n")


def _dotenv(run):
    with (run / "ai-migration/README.md").open("a") as f:
        f.write("\n```python\nfrom dotenv import load_dotenv\nload_dotenv()\n```\n")


def _flag_value(run):
    with (run / "ai-migration/README.md").open("a") as f:
        f.write("\nSet AI_PROVIDER=vertex_ai to roll back.\n")


def _readme_model(run):
    path = run / "ai-migration/README.md"
    path.write_text(path.read_text().replace("us.anthropic.claude-haiku-5-5", "a Claude model"))


def _uncovered(run):
    path = run / "ai-migration/prompts.json"
    path.write_text(json.dumps([p for p in json.loads(path.read_text()) if p.get("route") == "claude-sonnet-5__runtime-messages__messages"]))


def _files(run):
    _edit(run / "generation-ai.json", lambda g: g["artifacts_by_source"][0]["models"][0]["generated_files"].pop())


def _phase_not_an_object(run):
    _edit(run / "generation-ai.json", lambda g: g["migration_plan"].update(phases=[42]))


def _phase_without_activities(run):
    _edit(run / "generation-ai.json", lambda g: g["migration_plan"]["phases"][0].pop("activities"))


def _no_dashboards(run):
    _edit(run / "generation-ai.json", lambda g: g["monitoring"].update(dashboards=[]))


def _other_dashboards(run):
    _edit(run / "generation-ai.json", lambda g: g["monitoring"].update(dashboards=g["monitoring"]["dashboards"][:-1] + ["Spend"]))


@pytest.mark.parametrize(("mutate", "code"), [
    (_drop_model, "models_to_migrate"), (_swap_pair, "artifacts_by_source"), (_openrouter, "schema_violation"),
    (_source_default, "rollback_plan"), (_confidence, "confidence"), (_stale, "artifact_unexpected"), (_modified, "artifact_modified"),
    (_missing, "artifact_missing"), (_secret, "secret_literal"), (_dotenv, "readme_dotenv"), (_flag_value, "readme_flag_value"),
    (_readme_model, "readme_incomplete"), (_uncovered, "prompts_uncovered"), (_files, "artifacts_by_source"),
    (_phase_not_an_object, "schema_violation"), (_phase_without_activities, "schema_violation"), (_no_dashboards, "dashboards"),
    (_other_dashboards, "dashboards"),
], ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_check_rejects(mutate, code, tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    mutate(run)
    assert code in _codes(run)


def test_check_rejects_a_placeholder_anywhere(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    _edit(run / "generation-ai.json", lambda g: g["recommendation"]["key_risks"].append("WRITE: each key risk"))
    assert _codes(run) == {"placeholder_left"}


def test_check_tolerates_harness_output_and_bytecode(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    (run / "ai-migration/comparison_results.json").write_text("{}")
    (run / "ai-migration/routes/__pycache__").mkdir()
    (run / "ai-migration/routes/__pycache__/x.pyc").write_bytes(b"")
    assert GEN.check(run)["ok"]


def test_scaffold_clears_stale_files_and_refuses_a_symlink(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    _stale(run)
    GEN.scaffold(run, GEN.build_plan(run))
    assert not (run / "ai-migration/routes/old-model__converse__converse.py").exists()
    shutil.rmtree(run / "ai-migration")
    (tmp_path / "elsewhere").mkdir()
    (run / "ai-migration").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(GEN.GenerateInputError) as err:
        GEN.scaffold(run, GEN.build_plan(run))
    assert err.value.code == "ai_migration_not_a_directory"


def test_plan_rejects_a_region_that_is_not_a_region_name(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-same-model", inputs_only=True)
    _edit(run / "preferences.json", lambda p: p["design_constraints"]["target_region"].update(value="us-east-1; touch pwned"))
    assert GEN.main(["plan", str(run)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "region_invalid"


def test_plan_refuses_a_design_with_no_bedrock_row(tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path, "bma-generate-same-model", inputs_only=True)
    real = GEN._read

    def speech_only(run_dir: Path, name: str):
        doc = real(run_dir, name)
        if name == "aws-design-ai.json":
            doc["ai_architecture"]["bedrock_models"] = []
            for block in doc["design_blocks"]:
                block.update(target_bedrock_model=None, target_aws_service="transcribe")
        return doc
    monkeypatch.setattr(GEN, "_read", speech_only)
    with pytest.raises(GEN.GenerateInputError) as err:
        GEN.build_plan(run)
    assert err.value.code == "no_bedrock_routes"


def test_plan_needs_a_completed_estimate(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-same-model", inputs_only=True)
    _edit(run / ".phase-status.json", lambda s: s["phases"].update(estimate="in_progress"))
    assert GEN.main(["plan", str(run)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "phase_incomplete"


def test_cli_scaffold_then_check(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-same-model", inputs_only=True)
    assert GEN.main(["scaffold", str(run)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["write_next"][:2] == ["ai-migration/README.md", "ai-migration/prompts.json"]
    skeleton = json.loads((run / "generation-ai.json").read_text())
    plan = GEN.build_plan(run)
    assert skeleton["artifacts_by_source"] == plan["fixed"]["artifacts_by_source"]
    assert skeleton["rollback_plan"] == plan["fixed"]["rollback_plan"] and skeleton["recommendation"]["confidence"] == plan["confidence_ceiling"]
    assert GEN.main(["check", str(run)]) == 1
    codes = {e["code"] for e in json.loads(capsys.readouterr().out)["errors"]}
    assert {"placeholder_left", "plan_phases_missing", "artifact_missing"} <= codes
    assert "schema_violation" not in codes, "the skeleton already satisfies the contract"
    (run / "generation-ai.json").unlink()
    assert GEN.main(["check", str(run)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "generation_not_found"


# --------------------------------------------------------------------------- readiness

def test_readiness_through_generate_hashes_every_generated_file(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-mixed", generate="completed")
    assert READY.main([str(run), "--through", "generate"]) == 0
    out = json.loads(capsys.readouterr().out)
    files = {p.relative_to(run).as_posix() for p in (run / "ai-migration").rglob("*") if p.is_file()}
    assert set(out["artifacts"]) == {"ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json", "generation-ai.json"} | files
    for name, entry in out["artifacts"].items():
        assert entry["sha256"] == hashlib.sha256((run / name).read_bytes()).hexdigest(), name


@pytest.mark.parametrize(("change", "reason"), [
    (lambda run: _edit(run / ".phase-status.json", lambda s: s["phases"].update(generate="in_progress")), "phase_incomplete"),
    (lambda run: _edit(run / ".phase-status.json", lambda s: s["phases"].pop("generate")), "phase_incomplete"),
    (_modified, "generate_invalid"),
    (lambda run: (run / "generation-ai.json").unlink(), "artifact_missing"),
])
def test_readiness_through_generate_refuses(change, reason, tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-mixed", generate="completed")
    change(run)
    assert READY.main([str(run), "--through", "generate"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == reason


def test_readiness_through_estimate_ignores_generate(tmp_path: Path, capsys) -> None:
    run = _run(tmp_path, "bma-generate-mixed", generate="pending")
    _modified(run)
    assert READY.main([str(run), "--through", "estimate"]) == 0


# --------------------------------------------------------------------------- setup script: budget coverage, overrides, re-runs

def _setup(run: Path, tmp_path: Path, *args: str, env: dict | None = None, exists: bool | str = False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "aws").write_text(FAKE_AWS.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    (bin_dir / "python3").write_text("#!/bin/sh\nexit 0\n")
    for tool in ("aws", "python3"):
        (bin_dir / tool).chmod(0o755)
    log = bin_dir / "aws.log"
    if log.exists():
        log.unlink()
    result = subprocess.run(["bash", str(run / "ai-migration/setup_bedrock.sh"), *args], capture_output=True, text=True,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", **({"FAKE_EXISTS": "iam,budgets" if exists is True else exists} if exists else {}),
                                 **(env or {})})
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def _budget_doc(calls: list) -> dict | None:
    budget = next((c for c in calls if c[:2] == ["budgets", "create-budget"]), None)
    return json.loads(budget[budget.index("--budget") + 1]) if budget else None


def test_claude_routes_get_no_budget_described_as_covering_them(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    plan = GEN.build_plan(run)
    assert {r["billing"] for r in plan["routes"]} == {"marketplace"}
    assert plan["budget"]["services"] is None
    assert any("AWS Marketplace" in d and "BUDGET_SERVICES" in d for d in plan["disclosures"])
    result, calls = _setup(run, tmp_path, "--execute")
    assert result.returncode == 0, result.stderr
    assert _budget_doc(calls) is None
    assert "us.anthropic.claude-sonnet-5" in result.stdout and "AWS Marketplace" in result.stdout and "BUDGET_SERVICES" in result.stdout
    assert ["ce", "create-anomaly-monitor"] == next(c[:2] for c in calls if c[:2] == ["ce", "create-anomaly-monitor"])


def test_budget_services_from_the_environment_cover_a_claude_route(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-tier-range")
    services = "Amazon Bedrock, Claude Sonnet 5 (Amazon Bedrock Edition)"
    result, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_SERVICES": services})
    assert result.returncode == 0, result.stderr
    doc = _budget_doc(calls)
    assert doc["CostFilters"] == {"Service": ["Amazon Bedrock", "Claude Sonnet 5 (Amazon Bedrock Edition)"]}
    assert doc["BudgetLimit"] == {"Amount": "858", "Unit": "USD"}
    bad, _ = _setup(run, tmp_path, env={"BUDGET_SERVICES": 'Amazon Bedrock"]}'})
    assert bad.returncode == 2 and "BUDGET_SERVICES" in bad.stderr
    assert GEN.check(run)["ok"], "the override changes no generated file"


@pytest.mark.parametrize(("fixture", "unconfirmed"), [("bma-generate-same-model", {"us.openai.gpt-5.6-terra"}),
                                                       ("bma-generate-mixed", {"openai.gpt-5.5", "us.openai.gpt-5.5"})])
def test_non_amazon_models_without_billing_evidence_are_named_as_unconfirmed(fixture, unconfirmed, tmp_path: Path) -> None:
    run = _run(tmp_path, fixture)
    plan = GEN.build_plan(run)
    assert {r["aws_model_id"] for r in plan["routes"] if r["billing"] == "unconfirmed"} == unconfirmed
    assert "marketplace" not in {r["billing"] for r in plan["routes"]}
    assert plan["budget"]["services"] == ["Amazon Bedrock"]
    result, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": "100"})
    assert result.returncode == 0, result.stderr
    assert _budget_doc(calls)["CostFilters"] == {"Service": ["Amazon Bedrock"]}
    assert all(m in result.stdout for m in unconfirmed) and "Cost Explorer" in result.stdout


@pytest.mark.parametrize(("mid", "billing"), [("amazon.titan-embed-text-v2:0", "amazon_bedrock"), ("us.amazon.nova-pro-v1:0", "amazon_bedrock"),
                                              ("us.anthropic.claude-sonnet-5", "marketplace"), ("anthropic.claude-haiku-5-5", "marketplace"),
                                              ("global.anthropic.claude-opus-5-5", "marketplace"), ("openai.gpt-5.5", "unconfirmed"),
                                              ("cohere.embed-english-v3", "unconfirmed"), ("amazonish.model", "unconfirmed")])
def test_billing_rule(mid, billing) -> None:
    assert GEN.billing(mid) == billing


def test_budget_amount_comes_from_the_environment_without_editing_the_script(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    result, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": "500"})
    assert result.returncode == 0, result.stderr
    assert _budget_doc(calls)["BudgetLimit"] == {"Amount": "500", "Unit": "USD"}
    dry, _ = _setup(run, tmp_path, env={"BUDGET_USD": "500"})
    assert dry.returncode == 0 and "500" in dry.stdout
    bad, _ = _setup(run, tmp_path, env={"BUDGET_USD": '5"}'})
    assert bad.returncode == 2 and "BUDGET_USD" in bad.stderr
    for zero in ("0", "00", "0.0", "0.00"):
        refused, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": zero})
        assert refused.returncode == 2 and "above zero" in refused.stderr and _budget_doc(calls) is None, zero
    small, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": "0.01"})
    assert small.returncode == 0 and _budget_doc(calls)["BudgetLimit"]["Amount"] == "0.01"
    assert "in this file" not in GEN.render_setup(GEN.build_plan(run))
    assert GEN.check(run)["ok"]
    assert READY.check(_complete(run), "generate")


def _complete(run: Path) -> Path:
    _edit(run / ".phase-status.json", lambda s: (s["phases"].update(generate="completed"), s.update(current_phase="complete")))
    return run


def test_setup_without_a_planned_budget_says_to_export_one(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    plan = GEN.build_plan(run)
    plan["budget"] = {**plan["budget"], "monthly_usd": None}
    text = GEN.render_setup(plan)
    assert "BUDGET_USD=\"${BUDGET_USD:-}\"" in text and "export BUDGET_USD=" in text and "in this file" not in text


def test_setup_execute_can_run_again_over_an_existing_policy_and_budget(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    result, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": "100"}, exists=True)
    assert result.returncode == 0, result.stderr
    kinds = {tuple(c[:2]) for c in calls}
    assert ("iam", "get-policy") in kinds and ("iam", "create-policy") not in kinds
    assert ("budgets", "describe-budget") in kinds and ("budgets", "create-budget") not in kinds
    assert "already exists" in result.stdout


def test_setup_uses_the_partition_of_its_region(tmp_path: Path) -> None:
    plan = GEN.build_plan(_run(tmp_path, "bma-generate-mixed"))
    assert 'PARTITION=aws\n' in GEN.render_setup(plan)
    for region, partition in (("us-gov-west-1", "aws-us-gov"), ("cn-north-1", "aws-cn")):
        text = GEN.render_setup({**plan, "region": region})
        assert f"PARTITION={partition}\n" in text and "arn:aws:iam" not in text


# --------------------------------------------------------------------------- invoke body owned by the user

def _invoke_plan(run: Path) -> dict:
    plan = GEN.build_plan(run)
    route = next(r for r in plan["routes"] if r["titan_embedding"])
    route.update(aws_model_id="cohere.embed-english-v3", titan_embedding=False, billing="unconfirmed")
    plan["manifest"]["user"] = [f"ai-migration/invoke/{route['route_id']}.py"]
    return plan, route


def test_invoke_route_loads_the_users_body_file_and_check_accepts_it(monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    run = _run(tmp_path, "bma-generate-mixed")
    plan, route = _invoke_plan(run)
    assert GEN.user_files(plan["routes"]) == plan["manifest"]["user"]
    gen = json.loads((run / "generation-ai.json").read_text())
    agent = {name: (run / "ai-migration" / name).read_text() for name in GEN.AGENT_FILES}
    GEN.scaffold(run, plan)
    for name, text in agent.items():
        (run / "ai-migration" / name).write_text(text)
    readme = run / "ai-migration/README.md"
    readme.write_text(readme.read_text() + "\ncohere.embed-english-v3\n")
    module = _module(f"bma_invoke_route_{route['route_id']}", run / route["files"][0])
    with pytest.raises(NotImplementedError, match=f"invoke/{route['route_id']}.py"):
        module.call_bedrock("hi")
    body = run / plan["manifest"]["user"][0]
    body.parent.mkdir()
    body.write_text("def invoke(client, model_id, prompt):\n    return f'{model_id}:{prompt}'\n")
    assert module.call_bedrock("hi") == "cohere.embed-english-v3:hi"
    assert calls.boto and calls.boto[-1][0] == "bedrock-runtime"
    assert GEN.check_generation(gen, plan, run)["ok"]
    (body.parent / "other.py").write_text("")
    assert "artifact_unexpected" in {e["code"] for e in GEN.check_generation(gen, plan, run)["errors"]}


def test_body_file_for_a_route_that_has_none_is_unexpected(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    plan = GEN.build_plan(run)
    assert plan["manifest"]["user"] == []
    (run / "ai-migration/invoke").mkdir()
    (run / f"ai-migration/invoke/{plan['routes'][0]['route_id']}.py").write_text("")
    assert "artifact_unexpected" in _codes(run)


def test_invoke_guidance_never_asks_for_an_edit_to_a_scaffolded_file() -> None:
    assert "write it before comparing" not in GEN.CALL_BEDROCK["invoke"]
    assert "ai-migration/invoke/<route_id>.py" in DOC


# --------------------------------------------------------------------------- state and helpers

def test_declining_generate_completes_the_run_in_decide_mode() -> None:
    step4 = SKILL.split("## Step 4: Estimate", 1)[1].split("## Step 5", 1)[0]
    assert 'On no, set `run_mode` to `"decide"` and `current_phase` to `"complete"`, leave `phases.generate` `"pending"`, and stop' in step4


def test_every_rule_7_choice_says_what_a_new_generate_replaces() -> None:
    rule7 = SKILL.split("## Step 0: Resume or start", 1)[1].split("\n7. ", 1)[1].split("\n8. ", 1)[0]
    offer = rule7.split("Each choice is one write:", 1)[0]
    assert "each choice replaces `ai-migration/`" in offer and "comparison_results.json" in offer


def test_scaffold_keeps_the_users_invoke_body_only_for_routes_that_still_need_one(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    plan, _ = _invoke_plan(run)
    body = run / plan["manifest"]["user"][0]
    body.parent.mkdir()
    body.write_text("def invoke(client, model_id, prompt):\n    return 'mine'\n")
    (body.parent / "old-route.py").write_text("")
    GEN.scaffold(run, plan)
    assert body.read_text().endswith("return 'mine'\n") and not (body.parent / "old-route.py").exists()
    GEN.scaffold(run, GEN.build_plan(run))
    assert not body.parent.exists(), "a route that no longer needs a body loses it"


def test_shared_ai_helpers_postpone_annotations_like_the_scripts_that_load_them() -> None:
    for name in ("iam_policy.py", "model_catalog.py"):
        tree = ast.parse((PLUGIN_ROOT / "skills/shared/ai" / name).read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
                   for n in tree.body), name


# --------------------------------------------------------------------------- capability, baseline, write boundary, partitions

MANTLE_RESPONSES = {"required_client_api": "responses", "migration_path": "mantle_openai_responses", "aws_model_id": "openai.gpt-5.5",
                    "base_url": "https://bedrock-mantle.us-west-2.api.aws/openai/v1"}


def test_web_search_route_sends_the_tool_without_external_web_access(monkeypatch, tmp_path: Path) -> None:
    calls = _stubs(monkeypatch)
    module = _load_route(GEN.render_route(_route(**MANTLE_RESPONSES, mantle_selector="web_search")), tmp_path, "web")
    module.call_bedrock("news today")
    assert calls.spies["responses"].call_args.kwargs == {"model": "openai.gpt-5.5", "input": "news today",
                                                          "tools": [{"type": "web_search", "external_web_access": False}]}
    plain = _load_route(GEN.render_route(_route(**MANTLE_RESPONSES, mantle_selector="projects")), tmp_path, "plain")
    plain.call_bedrock("hi")
    assert calls.spies["responses"].call_args.kwargs == {"model": "openai.gpt-5.5", "input": "hi"}


def test_mixed_fixture_web_search_route_file_sends_the_tool(tmp_path: Path) -> None:
    plan = GEN.build_plan(_run(tmp_path, "bma-generate-mixed"))
    web = [r for r in plan["routes"] if r["mantle_selector"] == "web_search"]
    assert len(web) == 1
    files = GEN.render_all(plan)
    for route in plan["routes"]:
        assert ('"external_web_access": False' in files[route["files"][0]]) == (route in web), route["route_id"]


@pytest.mark.parametrize("selector", ["background_inference", "server_side_tools"])
def test_a_capability_the_route_does_not_send_is_disclosed(selector, tmp_path: Path, monkeypatch) -> None:
    run = _run(tmp_path, "bma-generate-mixed", inputs_only=True)
    real = GEN._read

    def with_selector(run_dir: Path, name: str):
        doc = real(run_dir, name)
        if name == "aws-design-ai.json":
            next(r for r in doc["ai_architecture"]["bedrock_models"] if r.get("mantle_selector") == "web_search")["mantle_selector"] = selector
        return doc
    monkeypatch.setattr(GEN, "_read", with_selector)
    plan = GEN.build_plan(run)
    assert any(selector in d and "does not send" in d for d in plan["disclosures"])


def test_full_comparison_without_a_source_result_is_incomplete(monkeypatch, tmp_path: Path, capsys) -> None:
    _stubs(monkeypatch)
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    run = _run(tmp_path, "bma-generate-same-model")
    harness = _module("bma_test_harness_no_source", run / "ai-migration/test_comparison.py")
    out = tmp_path / "results.json"
    assert harness.main(["--quick", "--output", str(out)]) == 1
    summary = next(iter(json.loads(out.read_text())["routes"].values()))["summary"]
    assert summary["passed"] is False and summary["source_ok"] == 0 and "--target-only" in summary["incomplete"]
    assert "INCOMPLETE" in capsys.readouterr().out
    assert harness.main(["--target-only", "--quick", "--output", str(out)]) == 0, "--target-only stays the Bedrock-only mode"


def test_full_comparison_fails_only_the_route_whose_source_failed(monkeypatch, tmp_path: Path) -> None:
    _stubs(monkeypatch)
    anthropic = sys.modules["anthropic"]
    real = anthropic.Anthropic

    def no_source(**kwargs):
        if not kwargs:
            raise RuntimeError("401 from the source provider")
        return real(**kwargs)
    monkeypatch.setattr(anthropic, "Anthropic", no_source)
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    run = _run(tmp_path, "bma-generate-tier-range")
    harness = _module("bma_test_harness_one_source", run / "ai-migration/test_comparison.py")
    out = tmp_path / "results.json"
    assert harness.main(["--quick", "--output", str(out)]) == 1
    summaries = {k: v["summary"] for k, v in json.loads(out.read_text())["routes"].items()}
    claude, gemini = summaries["claude-sonnet-5__runtime-messages__messages"], summaries["gemini-2.5-flash__converse__converse"]
    assert claude["passed"] is False and "incomplete" in claude
    assert gemini["passed"] is True and gemini["source_ok"] == 1 and "incomplete" not in gemini


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_scaffold_and_check_refuse_a_generation_file_that_is_not_a_regular_file(kind, tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    plan = GEN.build_plan(run)
    target = tmp_path / "outside.json"
    target.write_text("keep")
    before = {p: p.read_bytes() for p in (run / "ai-migration").rglob("*") if p.is_file()}
    (run / "generation-ai.json").unlink()
    if kind == "symlink":
        (run / "generation-ai.json").symlink_to(target)
    else:
        (run / "generation-ai.json").mkdir()
    with pytest.raises(GEN.GenerateInputError) as err:
        GEN.scaffold(run, plan)
    assert err.value.code == "generation_not_a_file"
    assert target.read_text() == "keep"
    assert {p: p.read_bytes() for p in (run / "ai-migration").rglob("*") if p.is_file()} == before, "nothing is removed before the refusal"
    with pytest.raises(GEN.GenerateInputError) as err:
        GEN.check(run)
    assert err.value.code == "generation_not_a_file"


def test_setup_execute_resumes_after_a_run_that_stopped_after_the_policy(tmp_path: Path) -> None:
    run = _run(tmp_path, "bma-generate-mixed")
    result, calls = _setup(run, tmp_path, "--execute", env={"BUDGET_USD": "100"}, exists="iam")
    assert result.returncode == 0, result.stderr
    kinds = {tuple(c[:2]) for c in calls}
    assert ("iam", "create-policy") not in kinds and ("budgets", "create-budget") in kinds


SHARED_IAM = _module("bma_test_shared_iam_policy", PLUGIN_ROOT / "skills/shared/ai/iam_policy.py")
ACCOUNT = "123456789012"


@pytest.mark.parametrize(("partition", "region", "profile"), [
    ("aws", "us-east-1", "us.anthropic.claude-sonnet-5"),
    ("aws-us-gov", "us-gov-west-1", "us-gov.anthropic.claude-sonnet-5"),
    ("aws-cn", "cn-north-1", "apac.amazon.nova-pro-v1:0"),
])
def test_inference_profile_arns_keep_their_partition(partition, region, profile) -> None:
    arn = f"arn:{partition}:bedrock:{region}:{ACCOUNT}:inference-profile/{profile}"
    assert SHARED_IAM.is_inference_profile(arn)
    statements = {s["Sid"]: s for s in SHARED_IAM.generate_policy([arn], region, ACCOUNT)["Statement"]}
    base = profile.split(".", 1)[1]
    assert statements["BedrockInvokeModelScoped"]["Resource"] == sorted([arn, f"arn:{partition}:bedrock:*::foundation-model/{base}"])
    assert statements["BedrockGetInferenceProfile"]["Resource"] == [arn]


@pytest.mark.parametrize(("arn", "region", "account"), [
    (f"arn:aws:bedrock:us-gov-west-1:{ACCOUNT}:inference-profile/us-gov.anthropic.claude-sonnet-5", "us-gov-west-1", ACCOUNT),
    (f"arn:aws-us-gov:bedrock:us-gov-east-1:{ACCOUNT}:inference-profile/us-gov.anthropic.claude-sonnet-5", "us-gov-west-1", ACCOUNT),
    ("arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.anthropic.claude-sonnet-5", "us-east-1", ACCOUNT),
    (f"arn:aws:bedrock:us-east-1:{ACCOUNT}:application-inference-profile/abc123", "us-east-1", ACCOUNT),
    ("arn:aws-iso:bedrock:us-iso-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-5", "us-iso-east-1", ACCOUNT),
    (f"ARN:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/us.anthropic.claude-sonnet-5", "us-east-1", ACCOUNT),
])
def test_a_profile_arn_that_does_not_match_the_policy_fails_closed(arn, region, account) -> None:
    with pytest.raises(ValueError, match="inference-profile ARN"):
        SHARED_IAM.generate_policy([arn], region, account)


def test_an_account_placeholder_keeps_the_arns_own_account() -> None:
    arn = f"arn:aws-us-gov:bedrock:us-gov-west-1:{ACCOUNT}:inference-profile/us-gov.anthropic.claude-sonnet-5"
    resources = SHARED_IAM.generate_policy([arn], "us-gov-west-1", "ACCOUNT_ID")["Statement"][0]["Resource"]
    assert arn in resources


def test_iam_cli_names_the_arn_mismatch(tmp_path: Path) -> None:
    arn = f"arn:aws:bedrock:us-west-2:{ACCOUNT}:inference-profile/us.anthropic.claude-sonnet-5"
    result = subprocess.run([sys.executable, str(PLUGIN_ROOT / "skills/shared/ai/iam_policy.py"), "--models", arn, "--region", "us-east-1",
                             "--account-id", ACCOUNT], capture_output=True, text=True)
    assert result.returncode == 1 and json.loads(result.stdout)["reason"] == "inference_profile_arn_invalid"


def test_billing_reads_the_model_inside_a_profile_arn() -> None:
    assert GEN.billing(f"arn:aws-us-gov:bedrock:us-gov-west-1:{ACCOUNT}:inference-profile/us-gov.anthropic.claude-sonnet-5") == "marketplace"


def test_pricing_reads_the_model_inside_a_profile_arn_in_every_partition() -> None:
    pricing = _module("bma_test_l2b_pricing", PLUGIN_ROOT / "skills/llm-to-bedrock/scripts/bedrock_pricing.py")
    plain = pricing.lookup("us-east-1", "us.anthropic.claude-sonnet-5")
    for partition in ("aws", "aws-us-gov", "aws-cn"):
        arn = f"arn:{partition}:bedrock:us-east-1:{ACCOUNT}:inference-profile/us.anthropic.claude-sonnet-5"
        assert pricing.lookup("us-east-1", arn) == plain, partition


def test_generate_contract_names_bedrock_migration_assessment_as_its_producer() -> None:
    text = (PLUGIN_ROOT / "skills/shared/ai/schema-generate-ai.md").read_text()
    assert "no producer" not in text.lower() and "No producer has been repointed" not in text
    assert "`bedrock-migration-assessment`" in text and "scripts/generate-ai.py" in text
    status = text.split("## Status", 1)[1]
    assert "gcp-to-aws" in status and "azure-to-aws" in status and "deferred" in status
