# test_preflight_bedrock.py
import preflight_bedrock as p
import pytest


@pytest.mark.parametrize("model_id,mantle", [
    ("openai.gpt-6-astra", True),
    ("us.openai.gpt-6-astra", False),
    ("global.openai.gpt-6-astra", False),
])
def test_astra_preflight_dispatch_preserves_id_and_endpoint(model_id, mantle, monkeypatch, capsys):
    import boto3
    import json
    calls = []
    client = object()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: client)
    monkeypatch.setattr(p, "fetch_bedrock_quotas", lambda region: [])

    def probe_mantle(mid, region):
        calls.append(("mantle", mid, region))
        return {"ok": True, "reason": "ok"}

    def probe_runtime(actual_client, mid):
        assert actual_client is client
        calls.append(("runtime", mid, "us-west-2"))
        return {"ok": True, "reason": "ok"}

    monkeypatch.setattr(p, "probe_mantle_model", probe_mantle)
    monkeypatch.setattr(p, "probe_model", probe_runtime)
    assert p.is_mantle_model(model_id) is mantle
    assert p.main(["--region", "us-west-2", "--models", model_id]) == 0
    out = json.loads(capsys.readouterr().out)
    assert calls == [("mantle" if mantle else "runtime", model_id, "us-west-2")]
    assert out["models"][0]["model_id"] == model_id
    note = out["models"][0]["quota_note"]
    if mantle:
        assert "Do not assume GPT-5.6" in note
    else:
        assert "input tokens + 10 * output tokens" in note


def test_classify_access_denied_maps_to_authz_failure():
    # The pure classifier turns a botocore error code into a structured verdict.
    v = p.classify_invoke_error("AccessDeniedException", "not authorized to perform bedrock:InvokeModel")
    assert v["ok"] is False
    assert v["reason"] == "authz"
    assert "bedrock:InvokeModel" in v["detail"]


def test_classify_model_not_available_suggests_cross_region_profile():
    v = p.classify_invoke_error("ValidationException", "model identifier is invalid")
    assert v["ok"] is False
    assert v["reason"] == "model_unavailable"


def test_classify_throttle_is_ok_for_preflight():
    # A throttle on the 1-token probe means we ARE authorized — treat as pass.
    v = p.classify_invoke_error("ThrottlingException", "rate exceeded")
    assert v["ok"] is True


def test_classify_expired_token_maps_to_credentials():
    v = p.classify_invoke_error("ExpiredTokenException", "The security token included in the request is expired")
    assert v["ok"] is False
    assert v["reason"] == "credentials"


def test_probe_model_botocore_error_returns_json_verdict_not_traceback():
    # Regression: NoCredentialsError used to escape as an unhandled traceback,
    # so the orchestrator's JSON parse failed exactly when guidance was needed.
    from botocore.exceptions import NoCredentialsError

    class NoCredsClient:
        def converse(self, **kwargs):
            raise NoCredentialsError()

    v = p.probe_model(NoCredsClient(), "any.model-v1:0")
    assert v["ok"] is False
    assert v["reason"] == "credentials"
    assert "NoCredentialsError" in v["detail"]


def test_quota_rpm_matches_model_name_token():
    quotas = [
        {"QuotaName": "On-demand model inference requests per minute for Anthropic Claude Haiku 4.5", "Value": 50.0},
        {"QuotaName": "On-demand model inference requests per minute for Amazon Nova Lite", "Value": 1000.0},
        {"QuotaName": "Cross-region model inference tokens per day for Anthropic Claude", "Value": 9.9e9},
    ]
    rpm = p.quota_rpm(quotas, "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert rpm == 50  # the Nova quota and the per-day quota must not match


def test_quota_rpm_no_match_returns_none():
    quotas = [{"QuotaName": "On-demand model inference requests per minute for Amazon Nova Lite", "Value": 1000.0}]
    assert p.quota_rpm(quotas, "us.anthropic.claude-haiku-4-5-20251001-v1:0") is None


def test_main_empty_models_is_a_failure_not_a_vacuous_pass(capsys):
    # Regression: `--models ""` used to exit 0 with all_ok=True.
    import json
    rc = p.main(["--region", "us-east-1", "--models", " , "])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["reason"] == "no_models"


def test_embedding_model_detection():
    assert p.is_embedding_model("amazon.titan-embed-text-v2:0") is True
    assert p.is_embedding_model("cohere.embed-english-v3") is True
    assert p.is_embedding_model("us.anthropic.claude-haiku-4-5-20251001-v1:0") is False


def test_probe_routes_embedding_models_to_invoke_model_not_converse():
    # Regression: titan-embed probed via converse() got ValidationException and
    # was misreported as model_unavailable, blocking valid embeddings migrations.
    class Recorder:
        called = None
        def converse(self, **kwargs):
            Recorder.called = "converse"
            return {}
        def invoke_model(self, **kwargs):
            Recorder.called = "invoke_model"
            assert kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
            import json as j
            assert "inputText" in j.loads(kwargs["body"])
            return {}

    v = p.probe_model(Recorder(), "amazon.titan-embed-text-v2:0")
    assert Recorder.called == "invoke_model"
    assert v["ok"] is True


def test_probe_unknown_embedding_family_passes_with_caveat():
    class Boom:
        def converse(self, **kwargs):
            raise AssertionError("must not call converse for embeddings")
        def invoke_model(self, **kwargs):
            raise AssertionError("must not probe an unknown embedding family")

    v = p.probe_model(Boom(), "somevendor.embed-x-v1:0")
    assert v["ok"] is True
    assert v["reason"] == "embedding_unprobed"


def test_aggregate_failure_lifts_first_failing_reason_to_top_level():
    # Regression: per-model failures left no top-level reason, so the
    # orchestrator's documented `ok==false + reason` branches never matched.
    results = [
        {"ok": True, "reason": "ok", "detail": "fine", "model_id": "m1"},
        {"ok": False, "reason": "model_unavailable", "detail": "nope", "model_id": "m2"},
        {"ok": False, "reason": "authz", "detail": "denied", "model_id": "m3"},
    ]
    agg = p.aggregate_failure(results)
    assert agg["reason"] == "model_unavailable"
    assert agg["failing_models"] == ["m2", "m3"]


def test_aggregate_failure_empty_when_all_ok():
    assert p.aggregate_failure([{"ok": True, "reason": "ok", "detail": "", "model_id": "m"}]) == {}


def test_access_denied_model_access_variant_routes_to_console_fix():
    # Bedrock's "model access not enabled" also surfaces as AccessDeniedException;
    # sending the user to IAM for it is the wrong fix.
    v = p.classify_invoke_error(
        "AccessDeniedException",
        "You don't have access to the model with the specified model ID. "
        "Enable model access in the Amazon Bedrock console.")
    assert v["ok"] is False
    assert v["reason"] == "model_access"
    assert "console" in v["detail"].lower()


def test_access_denied_iam_variant_still_routes_to_authz():
    v = p.classify_invoke_error(
        "AccessDeniedException",
        "User: arn:aws:iam::123:user/x is not authorized to perform: "
        "bedrock:InvokeModel on resource ...")
    assert v["reason"] == "authz"
    assert "bedrock:InvokeModel" in v["detail"]


def test_mantle_model_detection_excludes_gpt_oss_and_cris_forms():
    # Bare proprietary GPT ids are mantle-served; gpt-oss speaks Converse; and
    # GPT-5.6 CRIS profile ids (us./in./global.) are bedrock-runtime targets that
    # MUST take the Converse probe — Converse is supported there (2026-08-21).
    assert p.is_mantle_model("openai.gpt-5.6-terra") is True
    assert p.is_mantle_model("openai.gpt-5.6-sol") is True
    assert p.is_mantle_model("openai.gpt-5.5") is True
    assert p.is_mantle_model("openai.gpt-5.4") is True
    assert p.is_mantle_model("openai.gpt-oss-120b-1:0") is False
    assert p.is_mantle_model("us.openai.gpt-5.6-sol") is False
    assert p.is_mantle_model("in.openai.gpt-5.6-luna") is False
    assert p.is_mantle_model("global.openai.gpt-5.6-terra") is False
    assert p.is_mantle_model("anthropic.claude-sonnet-4-6") is False
    assert p.is_mantle_model("amazon.nova-lite-v1:0") is False


def test_is_mantle_model_gpt54_55_cris_ids_are_runtime_not_mantle():
    # GPT-5.4 / GPT-5.5 model cards (read 2026-11-06) list us./global. CRIS ids on
    # bedrock-runtime. The ID-form rule already classifies them: bare id -> mantle
    # probe, CRIS-prefixed id -> Converse probe. Lock that in for these two models.
    assert p.is_mantle_model("openai.gpt-5.4") is True
    assert p.is_mantle_model("openai.gpt-5.5") is True
    assert p.is_mantle_model("us.openai.gpt-5.4") is False
    assert p.is_mantle_model("global.openai.gpt-5.4") is False
    assert p.is_mantle_model("us.openai.gpt-5.5") is False
    assert p.is_mantle_model("global.openai.gpt-5.5") is False


def test_is_mantle_model_matches_bare_gpt6_ids():
    # Bare GPT-6 ids (Astra, Sol, Luna, 6.1 Sol) are mantle-served, same as the
    # bare GPT-5.x ids above. Their CRIS forms (us./global. prefixed) stay on the
    # standard Converse/runtime path, unchanged.
    assert p.is_mantle_model("openai.gpt-6-astra") is True
    assert p.is_mantle_model("openai.gpt-6-sol") is True
    assert p.is_mantle_model("openai.gpt-6-luna") is True
    assert p.is_mantle_model("openai.gpt-6.1-sol") is True
    assert p.is_mantle_model("us.openai.gpt-6-sol") is False
    assert p.is_mantle_model("global.openai.gpt-6.1-sol") is False
    assert p.is_mantle_model("openai.gpt-oss-120b-1:0") is False


def test_mantle_authz_error_points_at_mantle_actions_not_invoke_model():
    # Regression: sending the user to bedrock:InvokeModel is a dead end for these
    # models — mantle inference needs bedrock-mantle:* actions.
    v = p.classify_mantle_error(403, "User is not authorized to perform bedrock-mantle:CreateInference")
    assert v["ok"] is False
    assert v["reason"] == "authz"
    assert "bedrock-mantle" in v["detail"]
    assert "does NOT authorize" in v["detail"]


def test_mantle_model_unavailable_remedy_is_family_split():
    # Mantle itself is in-region only, but every proprietary GPT model has a
    # bedrock-runtime CRIS path — GPT-5.6 (us./in./global., verified 2026-08-21)
    # and GPT-5.5/5.4 (us./global., model cards read 2026-11-06). The 404 remedy
    # must offer the CRIS form for all of them. An earlier version of this test
    # asserted that 5.5/5.4 have no prefixed form, which matched the pre-2026-11-06
    # model cards.
    v = p.classify_mantle_error(404, "model not found")
    assert v["ok"] is False
    assert v["reason"] == "model_unavailable"
    assert "in-region only" in v["detail"]
    assert "CRIS" in v["detail"] and "us./in./global." in v["detail"]
    assert "GPT-5.5/5.4" in v["detail"]
    assert "us./global. bedrock-runtime CRIS id" in v["detail"]
    assert "different model" in v["detail"]

def test_mantle_throttle_is_ok_for_preflight():
    v = p.classify_mantle_error(429, "too many tokens per minute")
    assert v["ok"] is True
    assert v["reason"] == "throttled_ok"


def test_mantle_model_access_variant_routes_to_console_fix():
    v = p.classify_mantle_error(403, "You do not have access to the model with the specified model ID")
    assert v["ok"] is False
    assert v["reason"] == "model_access"
    assert "console" in v["detail"].lower()


def test_main_probes_mantle_models_without_bedrock_runtime(monkeypatch, capsys):
    # Regression: mantle-only models were probed with bedrock-runtime Converse,
    # which always fails, so preflight blocked every GPT-5.x migration.
    import json
    calls = {}

    def fake_probe_mantle(model_id, region):
        calls["mantle"] = (model_id, region)
        return {"ok": True, "reason": "ok", "detail": "Mantle Responses API authorized."}

    def fake_probe_model(client, model_id):
        raise AssertionError("must not probe a mantle-only model via bedrock-runtime")

    monkeypatch.setattr(p, "probe_mantle_model", fake_probe_mantle)
    monkeypatch.setattr(p, "probe_model", fake_probe_model)
    monkeypatch.setattr(p, "fetch_bedrock_quotas", lambda region: [])

    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())

    rc = p.main(["--region", "us-east-1", "--models", "openai.gpt-5.6-terra", "--dataset-size", "9999"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert calls["mantle"] == ("openai.gpt-5.6-terra", "us-east-1")
    entry = out["models"][0]
    assert entry["ok"] is True
    assert entry["rpm_quota"] is None
    # A dataset larger than any RPM number must not produce an RPM pacing warning
    # for a model that has no RPM quota.
    assert "quota_warning" not in entry
    assert "no RPM quota" in entry["quota_note"]


def test_mantle_missing_deps_fails_closed(monkeypatch):
    # Regression: this returned ok=True with a caveat, mirroring the rare
    # `embedding_unprobed` case. But a missing SDK is the NORMAL path if the
    # dependency is absent, so passing turned a fail-fast preflight into an
    # unconditional green light — endpoint, model and IAM access never checked.
    import builtins
    real_import = builtins.__import__

    def no_openai(name, *a, **k):
        if name in ("openai", "aws_bedrock_token_generator"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_openai)
    v = p.probe_mantle_model("openai.gpt-5.6-terra", "us-east-1")
    assert v["ok"] is False
    assert v["reason"] == "mantle_deps_missing"
    assert "NOT verified" in v["detail"]


def test_mantle_deps_are_declared_in_pinned_env():
    # The fail-closed path above must never trigger in a correctly synced env,
    # so the pinned toolchain has to declare both packages.
    import pathlib
    toml = (pathlib.Path(__file__).resolve().parent / "pyproject.toml").read_text()
    assert "openai>=2.45.0" in toml
    assert "aws-bedrock-token-generator" in toml
    assert "anthropic>=" in toml


def test_messages_missing_deps_fails_closed(monkeypatch):
    # Same contract as the mantle probe: a missing Anthropic SDK must not turn the
    # runtime Messages preflight into an unconditional pass.
    import builtins
    real_import = builtins.__import__

    def no_anthropic(name, *a, **k):
        if name in ("anthropic", "aws_bedrock_token_generator"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    v = p.probe_runtime_messages_model("global.anthropic.claude-sonnet-5", "us-west-2")
    assert v["ok"] is False
    assert v["reason"] == "messages_deps_missing"
    assert "NOT verified" in v["detail"]


def test_runtime_openai_cris_plan_without_api_fails_closed():
    # Regression: a runtime_openai_cris plan with no recorded API used to resolve to
    # Converse silently; the source app's API must be recorded (or explicit converse).
    with pytest.raises(ValueError, match="never the implicit default"):
        p.normalize_api_path("runtime_openai_cris", ["us.openai.gpt-5.5"], None)
    assert p.normalize_api_path("runtime_openai_cris", ["us.openai.gpt-5.5"], "converse") == "runtime_openai_cris"
    assert p.normalize_api_path("runtime_messages", ["global.anthropic.claude-sonnet-5"]) == "runtime_messages"


def test_main_routes_messages_api_to_the_messages_probe(monkeypatch, capsys):
    import boto3
    import json
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())
    monkeypatch.setattr(p, "fetch_bedrock_quotas", lambda region: [])
    monkeypatch.setattr(p, "probe_runtime_messages_model",
                        lambda mid, region: calls.append(("messages", mid, region)) or
                        {"ok": True, "reason": "ok", "detail": "ok"})
    monkeypatch.setattr(p, "probe_model",
                        lambda client, mid: (_ for _ in ()).throw(AssertionError("Converse probe must not run")))
    monkeypatch.setattr(p, "probe_runtime_openai_model",
                        lambda *a: (_ for _ in ()).throw(AssertionError("OpenAI probe must not run")))
    rc = p.main(["--region", "us-west-2", "--models", "global.anthropic.claude-sonnet-5",
                 "--runtime-api", "messages"])
    assert rc == 0
    assert calls == [("messages", "global.anthropic.claude-sonnet-5", "us-west-2")]
    assert json.loads(capsys.readouterr().out)["ok"] is True


class _FakeRuntimeClient:
    """Offline stand-in for boto3's bedrock-runtime client."""

    def __init__(self):
        self.calls = []
        self.meta = type("Meta", (), {"region_name": "us-west-2"})()

    def converse(self, **kwargs):
        self.calls.append(("converse", kwargs["modelId"]))
        return {}

    def invoke_model(self, **kwargs):
        self.calls.append(("invoke_model", kwargs["modelId"]))
        return {}


class _FakeMessagesClient:
    """Offline stand-in for anthropic.Anthropic at the runtime /anthropic base URL."""
    calls = []

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        _FakeMessagesClient.calls.append(("messages", kwargs["model"]))
        return {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpenAIClient:
    """Offline stand-in for openai.OpenAI at the runtime /openai/v1 base URL."""
    calls = []

    def __init__(self):
        self.chat = type("Chat", (), {"completions": self})()
        self.responses = self

    def create(self, **kwargs):
        surface = "chat_completions" if "messages" in kwargs else "responses"
        _FakeOpenAIClient.calls.append((surface, kwargs["model"]))
        return {}


@pytest.fixture
def offline_clients(monkeypatch):
    """Route every real probe function at offline fake SDK clients and collect calls."""
    import boto3
    runtime = _FakeRuntimeClient()
    _FakeMessagesClient.calls = []
    _FakeOpenAIClient.calls = []
    monkeypatch.setattr(boto3, "client", lambda *a, **k: runtime)
    monkeypatch.setattr(p, "fetch_bedrock_quotas", lambda region: [])
    monkeypatch.setattr(p, "create_messages_client", lambda region, **k: _FakeMessagesClient())
    monkeypatch.setattr(p, "create_openai_client", lambda mid, region, **k: _FakeOpenAIClient())
    monkeypatch.setattr(p, "probe_mantle_model",
                        lambda *a: (_ for _ in ()).throw(AssertionError("Mantle probe must not run")))

    def all_calls():
        return runtime.calls + _FakeMessagesClient.calls + _FakeOpenAIClient.calls
    return all_calls


def test_mixed_claude_messages_and_gpt_chat_each_reach_their_own_probe(offline_clients, capsys):
    # PR 585 review, finding 2: B1 collected every aws_model_id and B4 passed one
    # --runtime-api, so a Claude Messages primary + GPT Chat secondary POSTed both to
    # /anthropic/v1/messages. Each --target row now carries its own API.
    import json
    rc = p.main(["--region", "us-west-2",
                 "--target", "global.anthropic.claude-sonnet-5=messages",
                 "--target", "us.openai.gpt-5.6-sol=chat_completions"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert sorted(offline_clients()) == sorted([
        ("messages", "global.anthropic.claude-sonnet-5"),
        ("chat_completions", "us.openai.gpt-5.6-sol"),
    ])
    assert [(m["model_id"], m["selected_api"]) for m in out["models"]] == [
        ("global.anthropic.claude-sonnet-5", "messages"),
        ("us.openai.gpt-5.6-sol", "chat_completions"),
    ]


def test_mixed_claude_messages_nova_converse_and_embeddings_each_reach_their_own_probe(
        offline_clients, capsys):
    import json
    rc = p.main(["--region", "us-west-2",
                 "--target", "global.anthropic.claude-sonnet-5=messages",
                 "--target", "us.amazon.nova-lite-v1:0=converse",
                 "--target", "amazon.titan-embed-text-v2:0=invoke"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert sorted(offline_clients()) == sorted([
        ("messages", "global.anthropic.claude-sonnet-5"),
        ("converse", "us.amazon.nova-lite-v1:0"),
        ("invoke_model", "amazon.titan-embed-text-v2:0"),
    ])


def test_gpt_responses_row_reaches_the_responses_probe_not_chat(offline_clients, capsys):
    import json
    rc = p.main(["--region", "us-west-2",
                 "--target", "global.openai.gpt-6-astra=responses",
                 "--target", "in.openai.gpt-5.6-terra=chat_completions"])
    assert rc == 0
    assert sorted(offline_clients()) == sorted([
        ("responses", "global.openai.gpt-6-astra"),
        ("chat_completions", "in.openai.gpt-5.6-terra"),
    ])
    out = json.loads(capsys.readouterr().out)
    assert "input tokens + 10 * output tokens" in out["models"][0]["quota_note"]


@pytest.mark.parametrize("spec", [
    "global.anthropic.claude-sonnet-5",            # no =API
    "global.anthropic.claude-sonnet-5=mantle_messages",  # a path, not an API
    "us.openai.gpt-5.6-sol=invoke",                 # invoke is not a chat lane
    "us.amazon.nova-lite-v1:0=",                    # empty API
])
def test_target_with_unknown_api_fails_closed_before_any_probe(spec, offline_clients, capsys):
    import json
    rc = p.main(["--region", "us-west-2",
                 "--target", "global.anthropic.claude-sonnet-5=messages", "--target", spec])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False
    assert out["reason"] == "unknown_runtime_api"
    assert out["models"] == []
    assert offline_clients() == []  # nothing probed on a guessed endpoint


def test_parse_targets_is_pure_and_fails_closed():
    pairs, failure = p.parse_targets(["a.model=converse,b.embed-v1=invoke", "c.model=messages"])
    assert failure is None
    assert pairs == [("a.model", "converse"), ("b.embed-v1", "invoke"), ("c.model", "messages")]
    pairs, failure = p.parse_targets(["a.model=converse", "d.model=responses_v2"])
    assert pairs == [] and failure["reason"] == "unknown_runtime_api"
    assert failure["failing_models"] == ["d.model"]


def test_legacy_models_flag_still_applies_one_api_to_every_id(offline_clients, capsys):
    # The single-API form is unchanged for callers that have one row.
    rc = p.main(["--region", "us-west-2", "--models", "global.anthropic.claude-sonnet-5",
                 "--runtime-api", "messages"])
    assert rc == 0
    assert offline_clients() == [("messages", "global.anthropic.claude-sonnet-5")]


# --- PR 585 review, finding 3: stop a mantle_messages plan before B4 / Phase C ---

def _design(rows, plan_path="runtime_messages"):
    return {"ai_architecture": {"bedrock_models": rows,
                                "code_migration": {"migration_path": plan_path}}}


def test_unsupported_lane_stop_names_the_deferred_lane_and_workspaces_selector():
    rows = [{"source_model": "claude-sonnet-4-5", "aws_model_id": "anthropic.claude-sonnet-5",
             "use_case": "chat", "migration_path": "mantle_messages", "mantle_selector": "workspaces"}]
    stop = p.unsupported_lane_stop(rows, "mantle_messages")
    assert stop["ok"] is False
    assert stop["reason"] == "unsupported_lane"
    assert stop["lane"] == "mantle_messages"
    assert stop["lane_status"] == "deferred"
    assert stop["mantle_selector"] == "workspaces"
    assert stop["failing_models"] == ["anthropic.claude-sonnet-5"]
    assert "bedrock-mantle.{region}.api.aws/anthropic" in stop["lane_description"]
    assert "do not run the B4 preflight" in stop["detail"]
    assert "runtime_messages" in stop["detail"]


@pytest.mark.parametrize("rows,plan_path", [
    ([{"aws_model_id": "global.anthropic.claude-sonnet-5", "migration_path": "runtime_messages",
       "required_client_api": "messages"}], "runtime_messages"),
    ([{"aws_model_id": "us.openai.gpt-5.6-sol", "migration_path": "runtime_openai_cris",
       "required_client_api": "responses"},
      {"aws_model_id": "amazon.titan-embed-text-v2:0"}], "runtime_openai_cris"),
    ([{"aws_model_id": "openai.gpt-6-astra", "migration_path": "mantle_openai_chat",
       "mantle_selector": "server_side_tools"}], "mantle_openai_chat"),
])
def test_supported_lanes_do_not_stop(rows, plan_path):
    assert p.unsupported_lane_stop(rows, plan_path) is None


def test_check_lanes_cli_stops_on_mantle_messages_and_passes_runtime_messages(tmp_path, capsys):
    import json
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_design(
        [{"aws_model_id": "anthropic.claude-sonnet-5", "migration_path": "mantle_messages",
          "mantle_selector": "workspaces"}], "mantle_messages")))
    assert p.main(["--check-lanes", str(bad)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "unsupported_lane" and out["mantle_selector"] == "workspaces"

    good = tmp_path / "good.json"
    good.write_text(json.dumps(_design(
        [{"aws_model_id": "global.anthropic.claude-sonnet-5", "migration_path": "runtime_messages",
          "required_client_api": "messages"}])))
    assert p.main(["--check-lanes", str(good)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["reason"] == "lanes_supported"


def test_check_lanes_uses_plan_level_path_when_rows_omit_it(tmp_path, capsys):
    import json
    design = tmp_path / "design.json"
    design.write_text(json.dumps(_design(
        [{"aws_model_id": "anthropic.claude-sonnet-5"}], "mantle_messages")))
    assert p.main(["--check-lanes", str(design)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "unsupported_lane"
    assert out["failing_models"] == ["anthropic.claude-sonnet-5"]


def test_main_messages_plan_probes_embedding_ids_via_invoke_model(monkeypatch, capsys):
    # Regression: B1 collects every bedrock_models[].aws_model_id into $TARGET_MODELS and
    # B4 passes the whole list with one --runtime-api. A runtime_messages plan with a
    # Claude profile plus an embedding id POSTed the embedding id to /anthropic/v1/messages
    # and failed preflight spuriously; embeddings must still go via InvokeModel.
    import boto3
    import json
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())
    monkeypatch.setattr(p, "fetch_bedrock_quotas", lambda region: [])
    monkeypatch.setattr(p, "probe_runtime_messages_model",
                        lambda mid, region: calls.append(("messages", mid)) or
                        {"ok": True, "reason": "ok", "detail": "ok"})
    monkeypatch.setattr(p, "probe_model",
                        lambda client, mid: calls.append(("invoke_model", mid)) or
                        {"ok": True, "reason": "ok", "detail": "ok"})
    monkeypatch.setattr(p, "probe_runtime_openai_model",
                        lambda *a: (_ for _ in ()).throw(AssertionError("OpenAI probe must not run")))
    rc = p.main(["--region", "us-west-2",
                 "--models", "global.anthropic.claude-sonnet-5,amazon.titan-embed-text-v2:0",
                 "--runtime-api", "messages"])
    assert rc == 0
    assert calls == [("messages", "global.anthropic.claude-sonnet-5"),
                     ("invoke_model", "amazon.titan-embed-text-v2:0")]
    assert json.loads(capsys.readouterr().out)["ok"] is True
