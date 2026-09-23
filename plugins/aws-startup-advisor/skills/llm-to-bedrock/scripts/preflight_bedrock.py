# preflight_bedrock.py
"""Bedrock fail-fast preflight: authorization, region/model availability, quota.

Usage: python preflight_bedrock.py --region <r> --models <id,id,...> [--dataset-size N]
Prints a JSON verdict to stdout; exit 0 if all models pass, 1 otherwise.
Always prints JSON — including for missing credentials / bad region — so the
caller can parse the verdict instead of a traceback. On failure the top level
carries `reason`/`detail`/`failing_models` lifted from the first failing model.
Chat models are probed via Converse; embedding models (which don't speak
Converse) via InvokeModel with their family's request body. Bare OpenAI
proprietary GPT ids are mantle-served and probed via the OpenAI Responses API;
GPT-5.6 CRIS profile ids (us./in./global. prefixed) are bedrock-runtime targets
and take the normal Converse probe.
The 1-token probe costs a fraction of a cent (noted in output).
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
    Converse/InvokeModel. Matches the BARE proprietary GPT ids (`openai.gpt-5*`),
    which are mantle-served. Deliberately does NOT match:
    - gpt-oss ids (Converse-capable on bedrock-runtime), and
    - GPT-5.6 CRIS profile ids (`us.`/`in.`/`global.` prefixed) — those are
      bedrock-runtime targets where Converse IS supported, so falling through to
      the standard Converse probe is the correct behavior, not an accident."""
    mid = model_id.lower()
    return mid.startswith("openai.gpt-5") and "oss" not in mid


def classify_mantle_error(status: int | None, message: str) -> dict:
    """Pure: map an OpenAI-SDK HTTP status from the mantle endpoint to a verdict.

    Mirrors classify_invoke_error's contract but for the mantle surface, where the
    remedies differ: IAM needs bedrock-mantle:* actions (not bedrock:InvokeModel),
    and mantle itself has no cross-region form — though for GPT-5.6 a
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
                          f"id (us./in./global. prefixed) instead, for GPT-5.5/5.4 switch to "
                          f"a supported region or a different model."}
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
        else:
            verdict = probe_model(client, model_id)
            rpm = quota_rpm(quotas, model_id)
            verdict["model_id"] = model_id
            verdict["rpm_quota"] = rpm
            if rpm is not None and args.dataset_size > rpm:
                verdict["quota_warning"] = (
                    f"Dataset ({args.dataset_size}) exceeds ~{rpm} RPM quota — "
                    f"Eval will pace with backoff and may be slow.")
        all_ok = all_ok and verdict["ok"]
        results.append(verdict)

    out = {"ok": all_ok, "region": args.region,
           "probe_cost_note": "1-token InvokeModel probe per model (~$0.00001 each)",
           "models": results}
    out.update(aggregate_failure(results))
    print(json.dumps(out, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
