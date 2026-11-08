# preflight_bedrock.py
"""Bedrock fail-fast preflight: authorization, region/model availability, quota.

Usage: python preflight_bedrock.py --region <r> --models <id,id,...> [--dataset-size N]
Prints a JSON verdict to stdout; exit 0 if all models pass, 1 otherwise.
Always prints JSON — including for missing credentials / bad region — so the
caller can parse the verdict instead of a traceback. On failure the top level
carries `reason`/`detail`/`failing_models` lifted from the first failing model.
Each model is probed on the API the plan selected (--runtime-api): `converse`
(the default when no API was selected), `responses` / `chat_completions` for the
runtime OpenAI-compatible APIs, or `messages` for the runtime Anthropic Messages
API. Embedding models (which don't speak Converse) go via InvokeModel with their
family's request body. Bare OpenAI proprietary GPT ids are the bedrock-mantle
form and are probed via the OpenAI Responses API on that endpoint; GPT-6 Astra
(us./global.) and GPT-5.6 (us./in./global.) CRIS ids are bedrock-runtime targets
and take the selected runtime API probe.
Probe output budgets and cost depend on the selected API.
"""
import argparse, json, sys


def classify_invoke_error(code: str, message: str) -> dict:
    """Pure: map a botocore error code to a structured preflight verdict."""
    if code in ("AccessDeniedException",):
        # Bedrock raises AccessDeniedException for two distinct problems:
        # (a) model access not enabled in the Bedrock console (message mentions
        #     model access / "use the model"), fixed in the console, not IAM;
        # (b) the IAM principal lacks bedrock:InvokeModel, fixed in IAM.
        # Sending the user to the wrong fix wastes their time — disambiguate
        # on the message text.
        lowered = message.lower()
        if ("model access" in lowered or "access to the model" in lowered
                or "use the model" in lowered or "model is not" in lowered):
            return {"ok": False, "reason": "model_access",
                    "detail": f"Bedrock model access not enabled for this model — {message}. "
                              f"Enable it in the Bedrock console (Model access page); "
                              f"this is separate from IAM."}
        return {"ok": False, "reason": "authz",
                "detail": f"IAM denies bedrock:InvokeModel — {message}. "
                          f"Grant bedrock:InvokeModel to this principal."}
    if code in ("ValidationException", "ResourceNotFoundException"):
        return {"ok": False, "reason": "model_unavailable",
                "detail": f"Model not available in this region — {message}. "
                          f"Try a cross-region inference profile (e.g. us.<model-id>)."}
    if code in ("ThrottlingException", "ServiceQuotaExceededException"):
        # We got far enough to be throttled => we are authorized.
        return {"ok": True, "reason": "throttled_ok",
                "detail": "Authorized (probe throttled, which still proves access)."}
    if code in ("UnrecognizedClientException", "InvalidSignatureException",
                "ExpiredTokenException", "ExpiredToken"):
        return {"ok": False, "reason": "credentials",
                "detail": f"AWS credentials invalid or expired — {message}. "
                          f"Run 'aws configure', refresh your SSO session, or set AWS_PROFILE."}
    return {"ok": False, "reason": "unknown", "detail": f"{code}: {message}"}


def is_embedding_model(model_id: str) -> bool:
    """Pure: embedding models don't speak the Converse API."""
    return "embed" in model_id.lower()


def is_mantle_model(model_id: str) -> bool:
    """Pure: ids that must be probed via the mantle Responses API rather than
    Converse/InvokeModel. Matches the BARE proprietary GPT ids (`openai.gpt-5*`,
    `openai.gpt-6*` — covers GPT-5.5/5.4/5.6 and GPT-6 Astra/Sol/Luna/6.1 Sol).
    The bare id is the bedrock-mantle form for every proprietary GPT model; none
    of them has a bedrock-runtime in-region form. Deliberately does NOT match:
    - gpt-oss ids (Converse-capable on bedrock-runtime), and
    - CRIS profile ids (`us.`/`in.`/`global.` prefixed) for any proprietary GPT
      model, GPT-5.5/5.4 included (their model cards list `us.`/`global.` ids on
      bedrock-runtime) — those are bedrock-runtime targets where Converse IS
      supported, so falling through to the standard Converse probe is the
      correct behavior, not an accident."""
    mid = model_id.lower()
    return (mid.startswith("openai.gpt-5") or mid.startswith("openai.gpt-6")) and "oss" not in mid



def normalize_api_path(plan_path: str | None, model_ids: list[str],
                       runtime_api: str | None = None) -> str:
    """Resolve a missing legacy path once for evaluator and rewriter dispatch.

    Explicit plans retain their chosen API. A `runtime_openai_cris` plan must
    name the source app's API (`responses` or `chat_completions`; `converse` only
    when the plan recorded it explicitly) — it fails closed rather than silently
    falling back to Converse. Legacy bare proprietary GPT targets use Mantle
    Responses; legacy runtime targets with no path at all retain Converse.
    A mixed legacy target set needs an explicit plan rather than an unsafe guess.
    """
    if plan_path == "mantle" and model_ids and all(is_mantle_model(mid) for mid in model_ids):
        return "mantle_openai_responses"
    if plan_path == "runtime_openai_cris":
        paths = {"converse": plan_path, "responses": "runtime_openai_responses",
                 "chat_completions": "runtime_openai_chat"}
        if runtime_api is None:
            raise ValueError(
                "runtime_openai_cris plan has no explicit API — record the source app's API "
                "(responses or chat_completions) as required_client_api; Converse is never "
                "the implicit default")
        if runtime_api not in paths:
            raise ValueError("Unknown runtime API; resolve the saved migration plan")
        return paths[runtime_api]
    if plan_path:
        return plan_path
    if not model_ids:
        raise ValueError("No validated target model IDs to resolve an API path")
    mantle = [is_mantle_model(mid) for mid in model_ids]
    if all(mantle):
        return "mantle_openai_responses"
    if any(mantle):
        raise ValueError("Mixed Mantle and runtime targets require an explicit migration plan")
    return "converse"


def create_openai_client(model_id: str, region: str, max_retries: int = 2):
    """Build the selected endpoint's client without changing the invocation ID."""
    from aws_bedrock_token_generator import provide_token
    if is_mantle_model(model_id):
        from openai import BedrockOpenAI
        return BedrockOpenAI(
            aws_region=region, bedrock_token_provider=lambda: provide_token(region=region),
            max_retries=max_retries,
        )
    from openai import OpenAI
    return OpenAI(
        base_url=f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1",
        api_key=lambda: provide_token(region=region), max_retries=max_retries,
    )


def probe_runtime_openai_model(model_id: str, region: str, api_surface: str) -> dict:
    """Probe the selected runtime Chat/Responses API, not a Converse substitute."""
    try:
        client = create_openai_client(model_id, region, max_retries=0)
        if api_surface == "chat_completions":
            client.chat.completions.create(
                model=model_id, messages=[{"role": "user", "content": "ping"}])
        else:
            client.responses.create(model=model_id, input="ping", max_output_tokens=16)
        return {"ok": True, "reason": "ok", "detail": f"Runtime {api_surface} API authorized."}
    except ImportError as e:
        return {"ok": False, "reason": "openai_deps_missing",
                "detail": f"Cannot verify the runtime OpenAI API: {e}. Re-sync scripts/pyproject.toml."}
    except Exception as e:
        code = {401: "UnrecognizedClientException", 403: "AccessDeniedException",
                 404: "ResourceNotFoundException", 429: "ThrottlingException"}.get(
                     getattr(e, "status_code", None), "unknown")
        return classify_invoke_error(code, str(e))


def create_messages_client(region: str, http_client=None, max_retries: int = 0):
    """Anthropic SDK client for the bedrock-runtime Messages endpoint.

    Public basis: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html
    (read 2026-11-07) — base_url `https://bedrock-runtime.{region}.amazonaws.com/anthropic`
    and a Bedrock bearer token passed as `api_key`. The pinned Anthropic SDK takes a
    STRING credential only, so the token is minted here, once per client, and never
    passed as a callable; callers create a client per request boundary and close it
    (`with create_messages_client(region) as client:`)."""
    import anthropic
    from aws_bedrock_token_generator import provide_token
    extra = {"http_client": http_client} if http_client is not None else {}
    return anthropic.Anthropic(
        base_url=f"https://bedrock-runtime.{region}.amazonaws.com/anthropic",
        api_key=provide_token(region=region), max_retries=max_retries, **extra,
    )


def probe_runtime_messages_model(model_id: str, region: str) -> dict:
    """Probe the runtime Anthropic Messages API for the exact validated profile.

    Fails CLOSED when the Anthropic SDK or the token generator is missing, for the
    same reason probe_mantle_model does: a missing dependency would otherwise turn
    the preflight into an unconditional pass with access never verified."""
    try:
        with create_messages_client(region) as client:
            client.messages.create(model=model_id, max_tokens=16,
                                   messages=[{"role": "user", "content": "ping"}])
        return {"ok": True, "reason": "ok", "detail": "Runtime Anthropic Messages API authorized."}
    except ImportError as e:
        return {"ok": False, "reason": "messages_deps_missing",
                "detail": f"Cannot verify the runtime Anthropic Messages API for {model_id}: {e}. "
                          f"This needs 'anthropic' and 'aws-bedrock-token-generator', both "
                          f"declared in scripts/pyproject.toml — re-sync the pinned environment "
                          f"(`uv sync --project <scripts dir>`). Access was NOT verified; "
                          f"preflight fails closed rather than assuming it works."}
    except Exception as e:  # noqa: BLE001 - SDK raises many types; status is what matters
        code = {401: "UnrecognizedClientException", 403: "AccessDeniedException",
                 404: "ResourceNotFoundException", 429: "ThrottlingException"}.get(
                     getattr(e, "status_code", None), "unknown")
        return classify_invoke_error(code, str(e))


def classify_mantle_error(status: int | None, message: str) -> dict:
    """Pure: map an OpenAI-SDK HTTP status from the mantle endpoint to a verdict.

    Mirrors classify_invoke_error's contract but for the mantle surface, where the
    remedies differ: IAM needs bedrock-mantle:* actions (not bedrock:InvokeModel),
    and mantle itself has no cross-region form — though for Astra / GPT-5.6 a
    bedrock-runtime CRIS id can cover the region instead."""
    if status in (401, 403):
        lowered = message.lower()
        if ("model access" in lowered or "access to the model" in lowered
                or "use the model" in lowered or "not authorized to use" in lowered):
            return {"ok": False, "reason": "model_access",
                    "detail": f"Bedrock model access not enabled for this model — {message}. "
                              f"Enable it in the Bedrock console (Model access page); "
                              f"this is separate from IAM."}
        return {"ok": False, "reason": "authz",
                "detail": f"IAM denies mantle inference — {message}. Grant bedrock-mantle "
                          f"actions (e.g. the AmazonBedrockMantleInferenceAccess managed "
                          f"policy); bedrock:InvokeModel does NOT authorize these models."}
    if status == 404:
        return {"ok": False, "reason": "model_unavailable",
                "detail": f"Model not available at this mantle endpoint/region — {message}. "
                          f"Mantle is in-region only; for GPT-5.6 try a bedrock-runtime CRIS "
                          f"id (us./in./global. prefixed); for GPT-6 Astra use us-east-1/us-west-2 "
                          f"mantle or a supported us./global. runtime CRIS path. "
                          f"For GPT-5.5/5.4 switch to a supported mantle region, a "
                          f"us./global. bedrock-runtime CRIS id, or a different model."}
    if status == 429:
        # Reaching a token-per-minute ceiling still proves we are authorized.
        return {"ok": True, "reason": "throttled_ok",
                "detail": "Authorized (probe throttled on a TPM quota, which still proves access)."}
    return {"ok": False, "reason": "unknown", "detail": f"{status}: {message}"}


def probe_mantle_model(model_id: str, region: str) -> dict:
    """Real minimal probe against the mantle Responses API.

    Fails CLOSED when the OpenAI SDK is missing. This deliberately does NOT follow
    the `embedding_unprobed` precedent: that one passes because an unrecognized
    embedding family is a rare edge case, whereas a missing SDK here would be the
    normal path for every run if the dependency were absent — returning ok=True
    would turn a fail-fast preflight into an unconditional green light and let the
    migration proceed with endpoint, model, and IAM access never checked. Both
    packages are declared in pyproject.toml, so reaching this branch means the
    pinned environment is broken and the operator needs to know."""
    try:
        from aws_bedrock_token_generator import provide_token
        from openai import BedrockOpenAI
    except ImportError as e:
        return {"ok": False, "reason": "mantle_deps_missing",
                "detail": f"Cannot probe mantle-only model {model_id}: {e}. This needs "
                          f"'openai>=2.45.0' and 'aws-bedrock-token-generator', both declared "
                          f"in scripts/pyproject.toml — re-sync the pinned environment "
                          f"(`uv sync --project <scripts dir>`). Access was NOT verified; "
                          f"preflight fails closed rather than assuming it works."}
    try:
        client = BedrockOpenAI(
            aws_region=region,
            bedrock_token_provider=lambda: provide_token(region=region),
            max_retries=0,
        )
        client.responses.create(model=model_id, input="ping", max_output_tokens=16, store=False)
        return {"ok": True, "reason": "ok", "detail": "Mantle Responses API authorized."}
    except Exception as e:  # noqa: BLE001 - SDK raises many types; status is what matters
        status = getattr(e, "status_code", None)
        if status is None:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
        if status is None:
            return {"ok": False, "reason": "credentials",
                    "detail": f"{type(e).__name__}: {e}. Check AWS credentials, the region "
                              f"name, and network access to the bedrock-mantle endpoint."}
        return classify_mantle_error(int(status), str(e))


def _embed_request_body(model_id: str) -> dict | None:
    """Pure: minimal valid request body per embedding-model family; None if unknown."""
    parts = model_id.split(".")
    vendor = parts[1] if parts[0] in ("us", "eu", "apac", "global") and len(parts) > 1 else parts[0]
    if vendor == "amazon":
        return {"inputText": "ping"}
    if vendor == "cohere":
        return {"texts": ["ping"], "input_type": "search_document"}
    return None


def probe_model(client, model_id: str) -> dict:
    """Real minimal probe: Converse for chat models, InvokeModel for embeddings."""
    region = getattr(getattr(client, "meta", None), "region_name", None)
    if model_id == "anthropic.claude-opus-5-5" and region != "eu-west-2":
        return {"ok": False, "reason": "inference_profile_required",
                "detail": "Opus 5.5 runtime in-region access is documented only in eu-west-2 "
                          "(verified 2026-10-03). Elsewhere, use a supported Geo/Global "
                          "profile for Converse, or verify a supported Mantle Messages path separately."}
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        if is_embedding_model(model_id):
            body = _embed_request_body(model_id)
            if body is None:
                # Unknown embedding family — probing with a wrong body would
                # produce a ValidationException indistinguishable from a real
                # availability problem. Pass with an explicit caveat instead.
                return {"ok": True, "reason": "embedding_unprobed",
                        "detail": "Embedding model from an unrecognized family — access not "
                                  "verified by preflight; confirm in the Bedrock console."}
            client.invoke_model(modelId=model_id, body=json.dumps(body),
                                contentType="application/json", accept="application/json")
            return {"ok": True, "reason": "ok", "detail": "InvokeModel (embedding) authorized."}
        client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            inferenceConfig={"maxTokens": 1},
        )
        return {"ok": True, "reason": "ok", "detail": "InvokeModel authorized."}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        return classify_invoke_error(code, msg)
    except BotoCoreError as e:
        # NoCredentialsError, EndpointConnectionError, SSO token errors, etc.
        # These are config problems on the caller's machine, not Bedrock verdicts.
        return {"ok": False, "reason": "credentials",
                "detail": f"{type(e).__name__}: {e}. "
                          f"Run 'aws configure', refresh your SSO session, or check the region name."}


def aggregate_failure(results: list) -> dict:
    """Pure: lift the first failing model's reason/detail to the top level so the
    orchestrator can branch on a single top-level `reason` (its documented contract)."""
    failing = [r for r in results if not r["ok"]]
    if not failing:
        return {}
    return {"reason": failing[0]["reason"], "detail": failing[0]["detail"],
            "failing_models": [r["model_id"] for r in failing]}


def quota_rpm(quotas: list, model_id: str) -> int | None:
    """Best-effort on-demand requests-per-minute quota for this model from a
    pre-fetched quota list; None if no match. Quota names follow the form
    'On-demand model inference requests per minute for <Model Display Name>',
    so we match per-minute inference quotas whose name shares a token with the
    model id (e.g. 'claude', 'nova', 'titan')."""
    tokens = [t for t in model_id.lower().replace(":", ".").split(".") if t]
    name_tokens = set()
    for t in tokens:
        name_tokens.update(p for p in t.split("-") if p and not p.isdigit())
    lowest = None
    for q in quotas:
        name = q.get("QuotaName", "").lower()
        if "per minute" not in name or "request" not in name:
            continue
        if not any(tok in name for tok in name_tokens):
            continue
        v = int(q.get("Value", 0))
        lowest = v if lowest is None else min(lowest, v)
    return lowest


def fetch_bedrock_quotas(region: str) -> list:
    """Fetch all Bedrock service quotas once; empty list on any failure."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        sq = boto3.client("service-quotas", region_name=region)
        quotas = []
        for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode="bedrock"):
            quotas.extend(page.get("Quotas", []))
        return quotas
    except (BotoCoreError, ClientError):
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--models", required=True, help="comma-separated model ids")
    ap.add_argument("--dataset-size", type=int, default=0)
    ap.add_argument("--runtime-api",
                    choices=["converse", "responses", "chat_completions", "messages"],
                    default="converse")
    args = ap.parse_args(argv)

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_ids:
        print(json.dumps({"ok": False, "region": args.region, "models": [],
                          "reason": "no_models",
                          "detail": "--models resolved to an empty list; nothing to probe."},
                         indent=2))
        return 1

    import boto3
    from botocore.exceptions import BotoCoreError
    try:
        client = boto3.client("bedrock-runtime", region_name=args.region)
    except BotoCoreError as e:
        print(json.dumps({"ok": False, "region": args.region, "models": [],
                          "reason": "credentials",
                          "detail": f"{type(e).__name__}: {e}"}, indent=2))
        return 1

    quotas = fetch_bedrock_quotas(args.region)
    results = []
    all_ok = True
    for model_id in model_ids:
        if is_mantle_model(model_id):
            verdict = probe_mantle_model(model_id, args.region)
            verdict["model_id"] = model_id
            # Mantle enforces per-model input/output TPM quotas and has no RPM
            # quota, so an RPM-derived pacing warning would be meaningless here.
            verdict["rpm_quota"] = None
            verdict["quota_note"] = (
                "Mantle quotas are per-model input/output tokens per minute; there is no RPM "
                "quota. Pace on token throughput, and note that prompt-cached input tokens are "
                "exempt from the input-TPM quota.")
            if model_id.lower() == "openai.gpt-6-astra":
                verdict["quota_note"] = (
                    f"Verify Astra's mantle quotas in the target account and {args.region}. "
                    "Do not assume GPT-5.6's cached-input quota exemption or RPM rules "
                    "apply; Astra's documented 10x output burndown is runtime-specific.")
        else:
            if args.runtime_api == "messages":
                verdict = probe_runtime_messages_model(model_id, args.region)
            elif (args.runtime_api != "converse" and ".openai.gpt-" in model_id
                    and "gpt-oss" not in model_id):
                verdict = probe_runtime_openai_model(model_id, args.region, args.runtime_api)
            else:
                verdict = probe_model(client, model_id)
            rpm = quota_rpm(quotas, model_id)
            verdict["model_id"] = model_id
            verdict["rpm_quota"] = rpm
            if model_id.rsplit("/", 1)[-1] in ("us.openai.gpt-6-astra", "global.openai.gpt-6-astra"):
                verdict["quota_note"] = (
                    "Astra runtime TPM usage = input tokens + 10 * output tokens. "
                    "Check the selected CRIS profile's token quota; an RPM check alone "
                    "does not establish throughput capacity.")
            if rpm is not None and args.dataset_size > rpm:
                verdict["quota_warning"] = (
                    f"Dataset ({args.dataset_size}) exceeds ~{rpm} RPM quota — "
                    f"Eval will pace with backoff and may be slow.")
        all_ok = all_ok and verdict["ok"]
        results.append(verdict)

    out = {"ok": all_ok, "region": args.region,
           "probe_cost_note": "Minimal model/API permission probes; output budgets and cost vary by API.",
           "models": results}
    out.update(aggregate_failure(results))
    print(json.dumps(out, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
