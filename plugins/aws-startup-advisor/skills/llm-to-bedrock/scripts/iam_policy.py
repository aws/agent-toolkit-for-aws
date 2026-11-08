"""Generate a least-privilege IAM policy for Bedrock model invocation.

Pure module: takes model IDs, region, and account ID — returns a policy dict.
Handles the dual-ARN pattern (foundation-model + inference-profile) required
when cross-region inference profile IDs (including au. and jp.) are in use.
"""
import json
import re
import sys

_GEO_PREFIX = re.compile(r"^(us|eu|apac|au|jp|in|us-gov|global)\.")

# The runtime APIs a plan can select (bedrock_models[].required_client_api). The
# OpenAI-compatible pair is what the default-project grant keys on.
RUNTIME_APIS = frozenset({"converse", "responses", "chat_completions", "messages"})
_OPENAI_COMPATIBLE_APIS = frozenset({"responses", "chat_completions"})
# A per-row `--target ID=API` spec may also say `invoke` for an embedding row (the
# value preflight accepts for those rows); it never selects the OpenAI-compatible path.
TARGET_APIS = RUNTIME_APIS | {"invoke"}

# Stored-response operations a source app may RETAIN after the rewrite, and the action
# each one authorizes on the default project. Creating a response authorizes
# `bedrock:InvokeModel` on the inference target and the project; retrieving, canceling
# and deleting a stored response authorize these three, each on the project
# (https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
# "Permissions", read 2026-11-08). They exist only on the runtime Responses API:
# Converse, Anthropic Messages and Chat Completions rows never get them.
STORED_RESPONSE_OPS = {
    "retrieve": "bedrock:GetInvoke",
    "cancel": "bedrock:CancelInvoke",
    "delete": "bedrock:DeleteInvoke",
}

# Execution lanes this helper refuses to authorize. `mantle_messages` (Anthropic SDK
# on the bedrock-mantle `/anthropic` endpoint, selected by the `workspaces` mantle
# selector) is deferred: llm-to-bedrock has no preflight, evaluation or rewrite route
# for it, so emitting runtime `bedrock:InvokeModel*` for its bare Claude id would
# authorize the wrong endpoint. Callers stop before dispatch instead.
UNSUPPORTED_LANES = frozenset({"mantle_messages"})


def is_inference_profile(model_id: str) -> bool:
    """True when the model ID uses a geo-prefix (cross-region inference profile)."""
    return bool(_GEO_PREFIX.match(model_id) or re.fullmatch(
        r"arn:aws:bedrock:[^:]+:[0-9]{12}:inference-profile/[^/]+", model_id
    ))


def is_mantle_model(model_id: str, region: str = "") -> bool:
    """True for bare proprietary GPT-5/GPT-6 IDs and the bare Opus 5.5 ID, which use
    bedrock-mantle (Responses/Chat Completions and Messages respectively). They need
    `bedrock-mantle:*` actions — a policy
    granting only `bedrock:InvokeModel` against a foundation-model ARN cannot
    authorize these bare IDs. Opus 5.5 in eu-west-2 is a runtime in-region
    target (model card verified 2026-10-03); its other bare-ID regions use Mantle.
    The `us.`/`in.`/`global.` prefixed forms use bedrock-runtime instead — for every
    proprietary GPT model, GPT-5.5/5.4 included (their model cards list `us.`/`global.`
    CRIS ids; none has a runtime in-region form), so a prefixed id must NOT match.
    The open-weight gpt-oss models DO use bedrock-runtime and must not match."""
    mid = model_id.lower()
    return ((mid.startswith("openai.gpt-5") or mid.startswith("openai.gpt-6")) and "oss" not in mid) or (
        mid == "anthropic.claude-opus-5-5" and region != "eu-west-2"
    )


def _partition(region: str) -> str:
    return "aws-us-gov" if region.startswith("us-gov-") else "aws-cn" if region.startswith("cn-") else "aws"


def mantle_project_arn(region: str, account_id: str) -> str:
    """ARN scope for mantle inference. Mantle authorizes at project granularity,
    not per model, so this cannot be narrowed to specific model IDs — use a
    service control policy to restrict the model set."""
    return f"arn:{_partition(region)}:bedrock-mantle:{region}:{account_id}:project/*"


def foundation_model_arn(model_id: str, region: str = "") -> str:
    """ARN for a plain foundation-model ID (no geo prefix)."""
    return f"arn:{_partition(region)}:bedrock:*::foundation-model/{model_id}"


def inference_profile_arn(model_id: str, region: str, account_id: str) -> str:
    """ARN for a cross-region inference profile."""
    if model_id.startswith("arn:"):
        return model_id
    return f"arn:{_partition(region)}:bedrock:{region}:{account_id}:inference-profile/{model_id}"


def default_project_arn(region: str, account_id: str) -> str:
    """ARN for the default Bedrock project, scoped to the account/region.

    A Responses request on bedrock-runtime authorizes `bedrock:InvokeModel` on the
    inference target AND on this ARN
    (https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
    "Permissions", read 2026-11-07). Every proprietary GPT model card — GPT-5.6 Sol /
    Terra / Luna, GPT-6, GPT-5.5, GPT-5.4 (read 2026-11-07) — repeats it for its
    runtime CRIS ids: the identity "also needs bedrock:InvokeModel on your account's
    default project ... in addition to the inference profile"."""
    return f"arn:{_partition(region)}:bedrock:{region}:{account_id}:project/default"


def is_gpt6_cris_model(model_id: str) -> bool:
    """True for a geo-prefixed (CRIS) GPT-6 id, e.g. `us.openai.gpt-6-astra` or
    `global.openai.gpt-6.1-sol`. A bare `openai.gpt-6-*` id (mantle) does NOT
    match — that path is covered by `is_mantle_model`, not this predicate."""
    if not is_inference_profile(model_id):
        return False
    base_id = _GEO_PREFIX.sub("", model_id.rsplit("/", 1)[-1]).lower()
    return base_id.startswith("openai.gpt-6")


# The exact bedrock-runtime ids the GPT-5.4 / GPT-5.5 model cards list (read
# 2026-11-07: us. and global. only — no in. or in-region form). Both cards say the
# identity "also needs bedrock:InvokeModel on your account's default project
# (arn:aws:bedrock:{region}:{account-id}:project/default) in addition to the
# inference profile".
_GPT54_55_CRIS_IDS = frozenset({
    "us.openai.gpt-5.4",
    "global.openai.gpt-5.4",
    "us.openai.gpt-5.5",
    "global.openai.gpt-5.5",
})


def is_gpt54_55_cris_model(model_id: str) -> bool:
    """True for exactly `us.`/`global.openai.gpt-5.4` / `-5.5`, as a short id or as
    an `arn:...:inference-profile/<id>` ARN. The bare `openai.gpt-5.4` / `-5.5` ids
    (mantle) and every other model, GPT-5.6 CRIS ids included, do NOT match. This
    is a model-family predicate (the exact ids those two cards publish); the
    default-project grant itself is decided by `requires_default_project_grant`."""
    if not is_inference_profile(model_id):
        return False
    return model_id.rsplit("/", 1)[-1].lower() in _GPT54_55_CRIS_IDS


def is_runtime_openai_cris_model(model_id: str) -> bool:
    """True for every proprietary GPT id in its bedrock-runtime CRIS form: a
    `us.` / `in.` / `us-gov.` / `global.` prefixed `openai.gpt-*` id (GPT-5.6 Sol,
    Terra and Luna, the GPT-6 family, GPT-5.5, GPT-5.4) or its
    `arn:...:inference-profile/<id>` ARN. Bare ids (mantle), the open-weight
    gpt-oss models and every non-OpenAI id do NOT match — classification is by id
    form, not by model family."""
    if not is_inference_profile(model_id):
        return False
    base_id = _GEO_PREFIX.sub("", model_id.rsplit("/", 1)[-1]).lower()
    return base_id.startswith("openai.gpt-") and "oss" not in base_id


def requires_default_project_grant(model_id: str, runtime_api: str | None = None) -> bool:
    """True when the policy must grant `bedrock:InvokeModel` on the default project
    ARN alongside the inference-profile ARN for this target.

    The grant belongs to the runtime OpenAI-compatible path, not to a model
    family: a Responses request on bedrock-runtime authorizes the default project
    separately from the inference target (inference-responses-api.html,
    "Permissions", read 2026-11-07), and every proprietary GPT card — GPT-5.6 Sol /
    Terra / Luna, GPT-6, GPT-5.5, GPT-5.4 — attaches the same requirement to its
    runtime CRIS ids for both the Responses and the Chat tab of its sample code.
    Decided by the SELECTED API when the pipeline knows it:
    - `responses` / `chat_completions` → grant for every runtime GPT CRIS target
    - `converse` / `messages`         → no grant (inference-prereq.html lists only
      `bedrock:InvokeModel*` + `bedrock:GetInferenceProfile` for Converse through a
      profile; Anthropic Messages targets are not OpenAI-compatible)
    - None (id-only caller)           → grant for every runtime GPT CRIS target, the
      conservative reading of the cards when the path is unknown
    Bare mantle ids, gpt-oss and every non-OpenAI id never get it."""
    if not is_runtime_openai_cris_model(model_id):
        return False
    if runtime_api is None:
        return True
    return runtime_api in _OPENAI_COMPATIBLE_APIS


def parse_targets(specs: list[str]) -> list[tuple[str, str]]:
    """Pure: parse repeatable `--target ID=API` specs (comma-joined items allowed)
    into (model_id, api) pairs, one per `bedrock_models[]` row.

    Fails CLOSED: a spec without `=API`, or with an API outside TARGET_APIS, raises
    `ValueError` before any policy is built, so a row whose API the plan does not
    record is never granted (or denied) the default project on a guess."""
    pairs: list[tuple[str, str]] = []
    bad: list[str] = []
    for spec in specs:
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            model_id, sep, api = item.rpartition("=")
            model_id, api = model_id.strip(), api.strip()
            if not sep or not model_id or api not in TARGET_APIS:
                bad.append(item if sep else f"{item}=<missing>")
                continue
            pairs.append((model_id, api))
    if bad:
        raise ValueError(
            "Every --target must be <aws_model_id>=<required_client_api> with the API from that "
            f"row ({' | '.join(sorted(TARGET_APIS))}). Unknown or missing: {', '.join(bad)}. "
            "Resolve the row's API in the saved plan instead of guessing it.")
    return pairs


def target_apis_by_id(pairs: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Pure: group parsed `(model_id, api)` pairs into EVERY API each id is called on.

    One Bedrock id may sit in two `bedrock_models[]` rows with different APIs — a
    `converse` row for a Guardrails / application-inference-profile call site and a
    `chat_completions` / `responses` row for a second source model mapped to the same
    target. `dict(pairs)` would keep only the last row, so the grant would depend on
    row order; the set keeps every row and the grant is any-row-wins."""
    by_id: dict[str, set[str]] = {}
    for model_id, api in pairs:
        by_id.setdefault(model_id, set()).add(api)
    return by_id


def parse_stored_response_ops(specs: list[str]) -> list[str]:
    """Pure: parse repeatable `--stored-response-ops OP[,OP]` specs into an ordered,
    de-duplicated list of `retrieve` / `cancel` / `delete`. Fails CLOSED on any other
    value so an action is never granted on a guess."""
    ops: list[str] = []
    bad: list[str] = []
    for spec in specs:
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            if item not in STORED_RESPONSE_OPS:
                bad.append(item)
            elif item not in ops:
                ops.append(item)
    if bad:
        raise ValueError(
            "Every --stored-response-ops value must be one of "
            f"{' | '.join(STORED_RESPONSE_OPS)} (the client.responses.<op>(id) calls the source "
            f"app RETAINS). Unknown: {', '.join(bad)}.")
    return ops


def validated_target_pairs(rows: list[dict], validated_mapping: list[str] | dict[str, str],
                           primary_model_id: str | None = None,
                           primary_api: str | None = None) -> list[tuple[str, str]]:
    """Pure: build the `--target ID=API` pairs for the report's IAM recipe by JOINING
    each `bedrock_models[]` row to the FINAL validated source→target mapping.

    The id comes from `validated_mapping` — the validated analysis `target_models`
    entries (`"<source-model> -> <bedrock-model>"`, one per row, re-emitted after every
    C4 `resolved_model_overrides` change) or an equivalent `{source: target}` dict —
    never from the row's own `aws_model_id`, which `aws-design-ai.json` keeps as the
    ORIGINAL design id after the user changes the target in C4 (a Sol → Terra change
    must emit Terra's profile, not Sol's). The API comes from the row
    (`required_client_api`, older plans `runtime_api`); the ONE row whose validated
    target is `primary_model_id` may fall back to `primary_api` (B4's resolved surface)
    when it records none. Fails CLOSED: a row with no validated mapping entry, or a
    row with no API, raises `ValueError` instead of granting on the design's stale id."""
    if isinstance(validated_mapping, dict):
        mapping = dict(validated_mapping)
    else:
        mapping = {}
        for entry in validated_mapping:
            source, sep, target = entry.partition("->")
            if not sep or not source.strip() or not target.strip():
                raise ValueError(
                    f"validated mapping entry {entry!r} is not '<source-model> -> <bedrock-model>'")
            mapping[source.strip()] = target.strip()
    pairs: list[tuple[str, str]] = []
    for row in rows:
        source = row.get("source_model") or row.get("source_model_id") or ""
        if source not in mapping:
            raise ValueError(
                f"bedrock_models[] row for source {source!r} (design id "
                f"{row.get('aws_model_id')!r}) has no entry in the validated target mapping; "
                "re-run C1 so analysis.target_models covers every row — never grant the "
                "design's original id on a guess.")
        target = mapping[source]
        api = row.get("required_client_api") or row.get("runtime_api")
        if not api and primary_api and target == primary_model_id:
            api = primary_api
        if not api:
            raise ValueError(
                f"bedrock_models[] row for source {source!r} → {target!r} records no "
                "required_client_api; resolve it in the saved plan instead of guessing it.")
        pairs.append((target, api))
    return pairs


def generate_policy(model_ids: list[str], region: str, account_id: str,
                    runtime_api: str | None = None,
                    migration_path: str | None = None,
                    target_apis: dict[str, str | set[str]] | None = None,
                    stored_response_ops: list[str] | None = None) -> dict:
    """Build a scoped IAM policy covering exactly the given model IDs.

    `runtime_api` is the plan's selected API (`responses`, `chat_completions`,
    `converse`, `messages`); it decides the default-project grant (see
    `requires_default_project_grant`). None keeps the id-only behaviour.
    `target_apis` maps a model id to ITS OWN row's API — a single API, or the set
    of APIs from every row that names the id (see `target_apis_by_id`) — and takes
    precedence over `runtime_api` for that id, so a mixed plan (Claude Messages
    primary + GPT Chat secondary) grants the default project to the GPT row and not
    to the Claude row. When one id carries several APIs, ANY row on `responses` /
    `chat_completions` grants it, regardless of row order.
    `migration_path` is the plan's `code_migration.migration_path`; an
    UNSUPPORTED lane (`mantle_messages`) raises `ValueError` instead of emitting
    runtime `bedrock:InvokeModel*` for a bare Claude id that the lane would never
    send to bedrock-runtime.
    `stored_response_ops` lists the stored-response operations the source app
    RETAINS (`retrieve` / `cancel` / `delete`, see STORED_RESPONSE_OPS). Each adds
    its action — `bedrock:GetInvoke` / `CancelInvoke` / `DeleteInvoke` — on the
    default project, which is what retrieving, canceling or deleting a stored
    response authorizes (inference-responses-api.html, "Permissions", read
    2026-11-08). Only a runtime GPT CRIS row on `responses` can carry stored
    responses, so declaring ops when no such row exists raises `ValueError`: a
    Converse, Anthropic Messages or Chat Completions plan never gets these grants.

    Emits up to five statements, depending on which endpoints the targets use:
    - `bedrock:InvokeModel*` scoped to foundation-model ARNs (plain IDs) and
      inference-profile ARNs (geo-prefixed IDs), for bedrock-runtime targets
    - `bedrock:GetInferenceProfile` scoped to the inference-profile ARNs, when any
      runtime target is a cross-region inference profile — the documented
      prerequisite for invoking through a profile
      (https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html,
      read 2026-11-07)
    - `bedrock:GetInvoke` / `CancelInvoke` / `DeleteInvoke` (only the retained ones)
      on the default project ARN, for a runtime Responses row with stored responses
    - `bedrock-mantle:CreateInference` / `Get*` / `List*` scoped to the account's
      mantle projects, for mantle-only targets (SigV4 auth)
    - `bedrock-mantle:CallWithBearerToken` on `*`, for Bedrock API-key auth

    A statement is omitted entirely when no target needs it — notably, an
    all-mantle run must not emit an InvokeModel statement with an empty Resource
    list, which is an invalid policy.
    """
    if migration_path in UNSUPPORTED_LANES:
        raise ValueError(
            f"migration_path {migration_path!r} is a deferred execution lane (Anthropic SDK on "
            f"the bedrock-mantle /anthropic endpoint, selected by the `workspaces` mantle "
            f"selector); llm-to-bedrock has no preflight, evaluation or rewrite route for it "
            f"and this helper emits no runtime permissions for its bare Claude id")
    if runtime_api is not None and runtime_api not in RUNTIME_APIS:
        raise ValueError(f"Unknown runtime API {runtime_api!r}; expected one of "
                         f"{sorted(RUNTIME_APIS)}")
    target_apis = {mid: {apis} if isinstance(apis, str) else set(apis)
                   for mid, apis in (target_apis or {}).items()}
    for mid, apis in target_apis.items():
        for api in sorted(apis):
            if api not in TARGET_APIS:
                raise ValueError(f"Unknown runtime API {api!r} for target {mid!r}; expected one of "
                                 f"{sorted(TARGET_APIS)}")
    stored_response_ops = list(stored_response_ops or [])
    for op in stored_response_ops:
        if op not in STORED_RESPONSE_OPS:
            raise ValueError(f"Unknown stored-response op {op!r}; expected one of "
                             f"{sorted(STORED_RESPONSE_OPS)}")
    runtime_ids = [m for m in model_ids if not is_mantle_model(m, region)]
    mantle_ids = [m for m in model_ids if is_mantle_model(m, region)]

    statements = []

    resources = []
    for mid in sorted(set(runtime_ids)):
        if is_inference_profile(mid):
            resources.append(inference_profile_arn(mid, region, account_id))
            base_id = _GEO_PREFIX.sub("", mid.rsplit("/", 1)[-1])
            resources.append(foundation_model_arn(base_id, region))
            # A runtime Responses / Chat Completions target (any proprietary GPT
            # CRIS id — GPT-5.6, GPT-6, GPT-5.5, GPT-5.4 — by id form) needs
            # InvokeModel on the inference-profile ARN AND the default project
            # ARN; both are required, neither replaces the other. Converse-only
            # routes, Anthropic ids and every other runtime target keep the
            # 2-ARN shape above. The row's own API wins over the plan-wide one,
            # and when the id sits in several rows ANY Responses / Chat row grants
            # it (never last-row-wins, so row order cannot drop the grant).
            row_apis = target_apis.get(mid) or {runtime_api}
            if any(requires_default_project_grant(mid, api) for api in row_apis):
                resources.append(default_project_arn(region, account_id))
        else:
            resources.append(foundation_model_arn(mid, region))

    # Emit unless the ONLY reason there are no resources is that every target is
    # mantle-only. A genuinely empty model list keeps the legacy shape (a statement
    # with an empty Resource) so existing callers and tests see no behaviour change.
    if resources or not mantle_ids:
        statements.append({
            "Sid": "BedrockInvokeModelScoped",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            "Resource": sorted(set(resources)),
        })

    profile_arns = [inference_profile_arn(mid, region, account_id)
                    for mid in runtime_ids if is_inference_profile(mid)]
    if profile_arns:
        statements.append({
            "Sid": "BedrockGetInferenceProfile",
            "Effect": "Allow",
            "Action": ["bedrock:GetInferenceProfile"],
            "Resource": sorted(set(profile_arns)),
        })

    if stored_response_ops:
        # Stored responses exist only on the runtime Responses API, so the grant is
        # keyed on a row that is BOTH a runtime GPT CRIS target AND on `responses`
        # (the same rows that get the default-project InvokeModel grant for
        # creation). A Converse / Messages / Chat Completions plan, or a legacy
        # id-only call with no API, fails closed instead of receiving GetInvoke.
        responses_rows = [
            mid for mid in runtime_ids
            if "responses" in (target_apis.get(mid) or {runtime_api})
            and requires_default_project_grant(mid, "responses")]
        if not responses_rows:
            raise ValueError(
                f"stored-response ops {stored_response_ops} declared but no --target row is a "
                "runtime GPT CRIS id on the `responses` API; retrieving / canceling / deleting a "
                "stored response exists only there, so a converse / messages / chat_completions "
                "plan never gets bedrock:GetInvoke / CancelInvoke / DeleteInvoke")
        statements.append({
            "Sid": "BedrockStoredResponseOps",
            "Effect": "Allow",
            "Action": sorted(STORED_RESPONSE_OPS[op] for op in stored_response_ops),
            "Resource": [default_project_arn(region, account_id)],
        })

    if mantle_ids:
        statements.append({
            "Sid": "BedrockMantleInference",
            "Effect": "Allow",
            "Action": [
                "bedrock-mantle:CreateInference",
                "bedrock-mantle:Get*",
                "bedrock-mantle:List*",
            ],
            "Resource": mantle_project_arn(region, account_id),
        })
        # CallWithBearerToken must be scoped to "*" — AWS does not support
        # narrowing it. Required for Bedrock API-key (bearer token) auth, which is
        # how the rewriter's generated client authenticates. Omit only if the app
        # uses SigV4 exclusively.
        statements.append({
            "Sid": "BedrockMantleCallWithBearerToken",
            "Effect": "Allow",
            "Action": ["bedrock-mantle:CallWithBearerToken"],
            "Resource": "*",
        })

    return {"Version": "2012-10-17", "Statement": statements}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate scoped Bedrock IAM policy")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--models", help="Comma-separated model IDs (legacy single-API form)")
    group.add_argument("--target", action="append", default=[],
                       help="<aws_model_id>=<required_client_api>; repeat once per "
                            "bedrock_models[] row. Each row's API decides its own "
                            "default-project grant (responses/chat_completions add it for a "
                            "runtime GPT CRIS id; converse/messages/invoke do not). An unknown "
                            "or missing API exits 1 with reason unknown_runtime_api.")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument("--account-id", required=True, help="AWS account ID")
    parser.add_argument("--output", help="Output file (default: stdout)")
    parser.add_argument("--runtime-api", choices=sorted(RUNTIME_APIS),
                        help="Selected runtime API applied to every --models id "
                             "(ignored with --target); responses/chat_completions add the "
                             "default-project grant for runtime GPT CRIS ids, converse/messages "
                             "do not. Omit for the id-only behaviour.")
    parser.add_argument("--migration-path",
                        help="Plan's code_migration.migration_path; an unsupported lane "
                             "(mantle_messages) exits 1 with a JSON reason instead of a policy.")
    parser.add_argument("--stored-response-ops", action="append", default=[],
                        help="retrieve | cancel | delete (comma-joined or repeated): the "
                             "client.responses.<op>(id) calls the source app RETAINS. Adds "
                             "bedrock:GetInvoke / CancelInvoke / DeleteInvoke on project/default "
                             "for a runtime GPT CRIS row on `responses`; exits 1 with reason "
                             "stored_response_ops_no_responses_row when no such row exists.")
    args = parser.parse_args()

    def _fail(reason: str, detail: str) -> None:
        print(json.dumps({"ok": False, "reason": reason, "lane": args.migration_path,
                          "detail": detail}, indent=2))
        sys.exit(1)

    if args.migration_path in UNSUPPORTED_LANES:
        # The lane stop wins over every other check: nothing on this path is authorized.
        try:
            generate_policy([], args.region, args.account_id, migration_path=args.migration_path)
        except ValueError as e:
            _fail("unsupported_lane", str(e))
    target_apis = None
    if args.target:
        try:
            targets = parse_targets(args.target)
        except ValueError as e:
            _fail("unknown_runtime_api", str(e))
        model_ids = [m for m, _ in targets]
        target_apis = target_apis_by_id(targets)
    else:
        model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        stored_response_ops = parse_stored_response_ops(args.stored_response_ops)
    except ValueError as e:
        _fail("unknown_stored_response_op", str(e))
    try:
        policy = generate_policy(model_ids, args.region, args.account_id,
                                 runtime_api=args.runtime_api if not args.target else None,
                                 migration_path=args.migration_path, target_apis=target_apis,
                                 stored_response_ops=stored_response_ops)
    except ValueError as e:
        _fail("stored_response_ops_no_responses_row" if "stored-response ops" in str(e)
              else "unknown_runtime_api", str(e))

    output = json.dumps(policy, indent=2) + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Policy written to {args.output}", file=sys.stderr)
    else:
        print(output)
