# test_preflight_bedrock.py
import preflight_bedrock as p


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


def test_mantle_authz_error_points_at_mantle_actions_not_invoke_model():
    # Regression: sending the user to bedrock:InvokeModel is a dead end for these
    # models — mantle inference needs bedrock-mantle:* actions.
    v = p.classify_mantle_error(403, "User is not authorized to perform bedrock-mantle:CreateInference")
    assert v["ok"] is False
    assert v["reason"] == "authz"
    assert "bedrock-mantle" in v["detail"]
    assert "does NOT authorize" in v["detail"]


def test_mantle_model_unavailable_remedy_is_family_split():
    # Verified 2026-08-21: mantle itself is in-region only, but GPT-5.6 now has a
    # bedrock-runtime CRIS path — so the 404 remedy must offer the CRIS form for
    # 5.6 while making clear 5.5/5.4 have no prefixed form. An earlier version of
    # this test asserted the opposite (never suggest a prefix), which matched the
    # pre-2026-08-21 docs.
    v = p.classify_mantle_error(404, "model not found")
    assert v["ok"] is False
    assert v["reason"] == "model_unavailable"
    assert "in-region only" in v["detail"]
    assert "CRIS" in v["detail"] and "us./in./global." in v["detail"]
    assert "GPT-5.5/5.4" in v["detail"]

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
