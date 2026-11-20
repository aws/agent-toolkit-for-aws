"""Discover what a deployed AgentCore Gateway exposes and build the policy context from it.

Reads GetGateway, ListGatewayTargets and GetGatewayTarget (control plane, the session's
region), target schemas declared inline or in S3, and the Gateway's live MCP ``tools/list``
(SigV4 for AWS_IAM, the stored OAuth bearer token for CUSTOM_JWT). Everything is merged
per target with ``acp_schemas.merge_targets``. A listing failure keeps the control-plane
declarations and records a gap for every affected target.

The policy-engine association comes only from GetGateway ``policyEngineConfiguration``;
policy engines are never searched.

Environment variables read: none (credentials and region come from the boto3 session).
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import acp_common
import acp_mcp_client
import acp_oauth
import acp_schemas
from acp_common import SkillError

AUTH_TYPES = ("AWS_IAM", "CUSTOM_JWT", "NONE", "AUTHENTICATE_ONLY")
PRINCIPAL_TYPES = {
    "CUSTOM_JWT": "AgentCore::OAuthUser",
    "AWS_IAM": "AgentCore::IamEntity",
    "NONE": None,
    "AUTHENTICATE_ONLY": None,
}
PRINCIPAL_NOTES = {
    "CUSTOM_JWT": [
        "The principal id is the token's `sub` claim.",
        'Claims are String tags: read them with principal.getTag("<claim>") guarded by '
        'principal.hasTag("<claim>"); never use .contains on a tag.',
        "Before the first rule that reads a claim, ask the developer to give or confirm the exact "
        "claim names (names only, never a token) and record them with `claims set --names ...`; "
        "never read them from the identity provider or a token.",
    ],
    "AWS_IAM": [
        "IamEntity declares no tags; scope by the id (the caller's IAM user or role ARN).",
        "For an assumed-role caller the policy principal is the role, not the STS session ARN.",
    ],
    "NONE": [
        "Every caller is AgentCore::UnauthenticatedUser (no id, no tags), so policies cannot tell "
        "callers apart.",
        "Write only caller-independent rules (guardrails, input, time and temporal conditions) with "
        "a bare principal; route a rule that needs the caller's identity (a role, a claim, a named "
        "user, the same user in history) non-translatable: this Gateway does not identify callers.",
        "Never write AgentCore::UnauthenticatedUser in a policy.",
    ],
    "AUTHENTICATE_ONLY": [
        "Callers must sign with SigV4, but the identity is not passed to policies: every caller is "
        "AgentCore::UnauthenticatedUser (no id, no tags), so policies cannot tell callers apart.",
        "Write only caller-independent rules (guardrails, input, time and temporal conditions) with "
        "a bare principal; route a rule that needs the caller's identity (a role, a claim, a named "
        "user, the same user in history) non-translatable: this Gateway does not identify callers.",
        "Never write AgentCore::UnauthenticatedUser in a policy.",
    ],
}
NOT_ACCESSIBLE = (
    "this Gateway is not accessible with the current AWS profile; "
    "try it with another profile in another session"
)
GATEWAY_SCOPE = "(gateway)"
SIGNING_SERVICE = "bedrock-agentcore"
S3_MAX_BYTES = 8 * 1024 * 1024
MAX_TARGET_PAGES = 100
# Tools the Gateway itself adds (for example semantic search); they belong to no target.
SERVICE_TOOL_PREFIX = "x_amz_bedrock_agentcore_"
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")

Sign = Callable[[urllib.request.Request], None]


# ── AWS identity and request signing ─────────────────────────────────────


def verify_aws(sess: Any) -> dict:
    """STS GetCallerIdentity once; returns only the region (never the account or ARN)."""
    region = sess.region_name
    if not region:
        raise SkillError(
            "invalid_input",
            "no AWS region is configured; set AWS_REGION or a profile region and retry",
        )
    try:
        sess.client("sts").get_caller_identity()
    except Exception as exc:  # noqa: BLE001 - mapped to a SkillError without response bodies
        raise acp_common.aws_error(exc, "sts:GetCallerIdentity") from None
    return {"verified": True, "region": region}


def sign_iam(sess: Any, region: str) -> Sign:
    """A ``sign`` callable that adds a fresh SigV4 signature (service bedrock-agentcore)."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    def sign(req: urllib.request.Request) -> None:
        credentials = sess.get_credentials()
        if credentials is None:
            raise SkillError(
                "credentials",
                "no AWS credentials found; configure a profile (for example `aws sso login`)",
            )
        aws_req = AWSRequest(
            method=req.get_method(),
            url=req.full_url,
            data=req.data,
            headers=dict(req.header_items()),
        )
        SigV4Auth(credentials.get_frozen_credentials(), SIGNING_SERVICE, region).add_auth(aws_req)
        present = {name.lower() for name, _ in req.header_items()}
        for name, value in aws_req.headers.items():
            if name.lower() not in present or name.lower() == "authorization":
                req.add_header(name, value)

    return sign


def sign_bearer(token: str) -> Sign:
    """A ``sign`` callable that adds ``Authorization: Bearer <token>``."""

    def sign(req: urllib.request.Request) -> None:
        req.add_header("Authorization", f"Bearer {token}")

    return sign


def _sign_none(req: urllib.request.Request) -> None:
    return None


# ── control-plane reads ──────────────────────────────────────────────────


def _get_gateway(client: Any, gateway_id: str) -> dict:
    try:
        return client.get_gateway(gatewayIdentifier=gateway_id)
    except Exception as exc:  # noqa: BLE001
        mapped = acp_common.aws_error(exc, "GetGateway")
        if mapped.kind in ("access_denied", "not_found"):
            raise SkillError("not_accessible", NOT_ACCESSIBLE) from None
        raise mapped from None


def _list_targets(client: Any, gateway_id: str) -> list[dict]:
    items: list[dict] = []
    token: str | None = None
    for _ in range(MAX_TARGET_PAGES):
        kwargs: dict[str, Any] = {"gatewayIdentifier": gateway_id}
        if token:
            kwargs["nextToken"] = token
        try:
            page = client.list_gateway_targets(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise acp_common.aws_error(exc, "ListGatewayTargets") from None
        items.extend(page.get("items", []))
        token = page.get("nextToken")
        if not token:
            return items
    raise SkillError("aws_error", "ListGatewayTargets returned too many pages")


def _gap(target: str, reason: str, *, action: str | None = None, field: str | None = None) -> dict:
    return {"target": target, "action": action, "field": field, "reason": reason}


# ── target declarations ──────────────────────────────────────────────────


class _Unreadable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_s3(sess: Any, s3_cfg: dict) -> str:
    uri = s3_cfg.get("uri")
    owner = s3_cfg.get("bucketOwnerAccountId")
    if not isinstance(uri, str) or not uri.startswith("s3://") or "/" not in uri[5:]:
        raise _Unreadable("schema_source_unavailable")
    bucket, key = uri[5:].split("/", 1)
    if not _BUCKET.match(bucket) or not key or len(key) > 1024:
        raise _Unreadable("schema_source_unavailable")
    kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if isinstance(owner, str) and re.fullmatch(r"\d{12}", owner):
        kwargs["ExpectedBucketOwner"] = owner
    try:
        body = sess.client("s3").get_object(**kwargs)["Body"]
        data = body.read(S3_MAX_BYTES + 1)
    except Exception:  # noqa: BLE001 - reported as a gap, never with the response body
        raise _Unreadable("schema_source_unavailable") from None
    if len(data) > S3_MAX_BYTES:
        raise _Unreadable("schema_source_too_large")
    return data.decode("utf-8", "replace")


def _load_source(sess: Any, source: Any) -> Any:
    """The JSON value behind ``{"inlinePayload": ...}`` or ``{"s3": {...}}``."""
    if not isinstance(source, dict):
        raise _Unreadable("schema_source_unavailable")
    payload = source.get("inlinePayload")
    if payload is None and isinstance(source.get("s3"), dict):
        payload = _read_s3(sess, source["s3"])
    if payload is None:
        raise _Unreadable("schema_source_unavailable")
    if isinstance(payload, (list, dict)):
        return payload
    try:
        return acp_schemas.load_document(payload, label="schema")
    except SkillError as exc:
        if exc.kind == "missing_dependency":
            raise  # reported against the target as an unsupported schema, with the install line
        raise _Unreadable("schema_not_json") from None


def _tool_list(value: Any) -> list[dict] | None:
    if isinstance(value, dict):
        result = value.get("result")
        value = value.get("tools", result.get("tools") if isinstance(result, dict) else None)
    if isinstance(value, list) and all(isinstance(t, dict) for t in value):
        return value
    return None


def _part(target: str, protocol: str, kind: str) -> dict:
    return {
        "target": target,
        "protocol": protocol,
        "kind": kind,
        "actions": {},
        "gaps": [],
    }


def _declaration_part(sess: Any, name: str, target: dict) -> dict:
    """The part for one GetGatewayTarget response, using ``acp_schemas`` parsers."""
    config = target.get("targetConfiguration") or {}
    mcp = config.get("mcp")
    http = config.get("http")
    inference = config.get("inference")

    def failed(part: dict, reason: str, field: str | None = None) -> dict:
        part["gaps"].append(_gap(name, reason, field=field))
        return part

    try:
        if isinstance(mcp, dict):
            return _mcp_declaration(sess, name, mcp, failed)
        if isinstance(http, dict):
            return _http_declaration(sess, name, http, failed)
        if isinstance(inference, dict):
            provider = inference.get("provider")
            return acp_schemas.inference_target(name, provider if provider else inference)
    except _Unreadable as exc:
        protocol = "MCP" if mcp else "HTTP"
        return failed(_part(name, protocol, "other"), exc.reason, "targetConfiguration")
    except SkillError as exc:
        return failed(
            _part(name, "MCP" if mcp else "HTTP", "other"),
            f"unsupported_schema: {exc.message}",
            "targetConfiguration",
        )
    return failed(_part(name, "HTTP", "other"), "target_schema_not_visible", "targetConfiguration")


def _mcp_declaration(sess: Any, name: str, mcp: dict, failed: Callable[..., dict]) -> dict:
    lambda_cfg = mcp.get("lambda")
    server = mcp.get("mcpServer")
    if isinstance(lambda_cfg, dict) or isinstance(server, dict):
        if isinstance(lambda_cfg, dict):
            kind, source = "lambda", lambda_cfg.get("toolSchema")
        elif isinstance(server, dict):
            kind, source = "mcp", server.get("mcpToolSchema")
        if source is None:
            # No declared tools (for example a remote MCP server listed live only).
            return _part(name, "MCP", kind)
        tools = _tool_list(_load_source(sess, source))
        if tools is None:
            return failed(_part(name, "MCP", kind), "invalid_tool_manifest", "toolSchema")
        return acp_schemas.parse_mcp_tools(tools, name, strip_prefix=False, kind=kind)
    if isinstance(mcp.get("openApiSchema"), dict):
        doc = _load_source(sess, mcp["openApiSchema"])
        if not isinstance(doc, dict):
            part = _part(name, "MCP", "openapi")
            return failed(part, "unsupported_openapi_schema", "openApiSchema")
        return acp_schemas.parse_openapi(doc, name, protocol="MCP")
    if isinstance(mcp.get("smithyModel"), dict):
        doc = _load_source(sess, mcp["smithyModel"])
        if not isinstance(doc, dict):
            return failed(_part(name, "MCP", "smithy"), "unsupported_smithy_model", "smithyModel")
        return acp_schemas.parse_smithy(doc, name)
    # apiGateway / connector targets declare no schema; their tools come from tools/list.
    return _part(name, "MCP", "other")


def _http_declaration(sess: Any, name: str, http: dict, failed: Callable[..., dict]) -> dict:
    runtime = http.get("agentcoreRuntime")
    block = runtime if isinstance(runtime, dict) else http.get("passthrough")
    if not isinstance(block, dict):
        return failed(_part(name, "HTTP", "other"), "unsupported_connector_schema", "http")
    source = (block.get("schema") or {}).get("source")
    if source is None:
        if isinstance(runtime, dict):
            return acp_schemas.runtime_default_target(name)
        return failed(_part(name, "HTTP", "other"), "http_schema_not_visible", "schema")
    doc = _load_source(sess, source)
    if not isinstance(doc, dict):
        return failed(_part(name, "HTTP", "openapi"), "unsupported_openapi_schema", "schema")
    part = acp_schemas.parse_openapi(doc, name)
    if isinstance(runtime, dict) and not part.get("actions"):
        default = acp_schemas.runtime_default_target(name)
        default["gaps"] = list(part.get("gaps", [])) + list(default.get("gaps", []))
        return default
    return part


# ── live tools/list ──────────────────────────────────────────────────────


def _gateway_endpoint(url: Any) -> str | None:
    """The normalized MCP endpoint when ``url`` is an https amazonaws.com host."""
    if not isinstance(url, str):
        return None
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.hostname or ""
    if parts.scheme != "https" or not (host.endswith((".amazonaws.com", ".amazonaws.com.cn"))):
        return None
    try:
        return acp_mcp_client.normalize_url(url)
    except SkillError:
        return None


def _tools_by_owner(
    tools: list[dict], names: list[str]
) -> tuple[dict[str, list[dict]], list[dict]]:
    owned: dict[str, list[dict]] = {}
    gaps: list[dict] = []
    for tool in tools:
        tool_name = tool.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        if tool_name.startswith(SERVICE_TOOL_PREFIX):
            continue
        owners = [n for n in names if tool_name.startswith(f"{n}___")]
        if len(owners) == 1:
            owned.setdefault(owners[0], []).append(tool)
        else:
            reason = "ambiguous_mcp_tool_owner" if owners else "unowned_mcp_tool"
            gaps.append(_gap(GATEWAY_SCOPE, reason, action=tool_name))
    return owned, gaps


def _client_choice(auth: dict, client_id: str | None) -> dict | None:
    """An input_required result when the OAuth client cannot be decided, else None."""
    allowed = auth["allowed_clients"]
    if client_id is not None:
        if allowed and client_id not in allowed:
            return {
                "status": "input_required",
                "missing": [
                    {
                        "input": "client_id",
                        "choices": allowed,
                        "message": "client_id is not one of this Gateway's allowed clients; "
                        "choose one of them.",
                    }
                ],
            }
        return None
    if len(allowed) == 1:
        return None
    message = (
        "This Gateway allows several OAuth clients; which client_id should sign in?"
        if allowed
        else "This Gateway does not list an allowed client; which OAuth client_id should sign in?"
    )
    return {
        "status": "input_required",
        "missing": [{"input": "client_id", "choices": allowed, "message": message}],
    }


# ── public entry point ───────────────────────────────────────────────────


def fetch_from_gateway(
    sess: Any,
    gateway_arn: str,
    *,
    client_id: str | None = None,
    login_failed: bool = False,
) -> dict:
    """Build the policy context for a Gateway, or say what is needed first.

    Returns ``{"status": "ready", "context": {...}}`` (context without ``cedar_schema``,
    ``built_at`` and ``version``), ``{"status": "login_required", ...}`` or
    ``{"status": "input_required", "missing": [...]}``. Raises
    ``SkillError("not_accessible")`` when GetGateway is denied, not found, or the Gateway
    is in another region than the session.
    """
    arn = acp_common.parse_gateway_arn(gateway_arn)
    if sess.region_name and sess.region_name != arn.region:
        raise SkillError("not_accessible", NOT_ACCESSIBLE)
    client = acp_common.control_client(sess)
    gateway = _get_gateway(client, arn.gateway_id)

    auth_type = gateway.get("authorizerType")
    if auth_type not in AUTH_TYPES:
        raise SkillError(
            "unsupported",
            f"the Gateway's authorizerType is not one of {', '.join(AUTH_TYPES)}",
            authorizer_type=str(auth_type),
        )
    jwt = (gateway.get("authorizerConfiguration") or {}).get("customJWTAuthorizer") or {}
    is_jwt = auth_type == "CUSTOM_JWT"
    auth = {
        "type": auth_type,
        "discovery_url": jwt.get("discoveryUrl") if is_jwt else None,
        "allowed_clients": list(jwt.get("allowedClients") or []) if is_jwt else [],
        "allowed_audience": list(jwt.get("allowedAudience") or []) if is_jwt else [],
    }

    # CUSTOM_JWT needs a bearer token before anything is listed through the Gateway.
    token = None
    if auth_type == "CUSTOM_JWT":
        token = acp_oauth.get_token(arn.arn)
        if token is None and not login_failed:
            choice = _client_choice(auth, client_id)
            if choice is not None:
                return choice
            chosen = client_id or auth["allowed_clients"][0]
            return {
                "status": "login_required",
                "gateway_arn": arn.arn,
                "auth": auth,
                "client_id": chosen,
                "message": "This Gateway uses OAuth (CUSTOM_JWT). Sign in so the Gateway's "
                "tools can be listed, then prepare again.",
            }

    gaps: list[dict] = []
    parts: list[dict] = []
    target_names: list[str] = []
    for item in _list_targets(client, arn.gateway_id):
        name = item.get("name")
        target_id = item.get("targetId")
        if not isinstance(name, str) or not isinstance(target_id, str):
            continue
        target_names.append(name)
        try:
            full = client.get_gateway_target(gatewayIdentifier=arn.gateway_id, targetId=target_id)
        except Exception as exc:  # noqa: BLE001
            mapped = acp_common.aws_error(exc, "GetGatewayTarget")
            if mapped.kind == "credentials":
                raise mapped from None
            gaps.append(_gap(name, f"target_unreadable: {mapped.kind}"))
            continue
        parts.append(_declaration_part(sess, name, full))

    endpoint = _gateway_endpoint(gateway.get("gatewayUrl"))
    scope_targets = target_names or [GATEWAY_SCOPE]
    if auth_type == "CUSTOM_JWT" and token is None:
        gaps.extend(_gap(t, "mcp_login_failed") for t in scope_targets)
    elif endpoint is None:
        present = bool(gateway.get("gatewayUrl"))
        reason = "gateway_endpoint_invalid" if present else "gateway_endpoint_missing"
        gaps.extend(_gap(t, reason) for t in scope_targets)
    else:
        if auth_type == "CUSTOM_JWT":
            sign: Sign = sign_bearer(token)  # type: ignore[arg-type]
        elif auth_type in ("AWS_IAM", "AUTHENTICATE_ONLY"):
            sign = sign_iam(sess, arn.region)
        else:
            sign = _sign_none
        try:
            tools = acp_mcp_client.list_tools(endpoint, sign)
        except SkillError as exc:
            gaps.extend(_gap(t, f"mcp_tools_list_failed: {exc.message}") for t in scope_targets)
        else:
            owned, unowned = _tools_by_owner(tools, target_names)
            gaps.extend(unowned)
            for owner, owner_tools in owned.items():
                try:
                    parts.append(acp_schemas.parse_mcp_tools(owner_tools, owner, strip_prefix=True))
                except SkillError as exc:
                    gaps.append(_gap(owner, f"unsupported_schema: {exc.message}"))

    targets, merge_gaps = acp_schemas.merge_targets(parts)
    notes: list[dict] = []
    for part in parts:
        notes.extend(part.get("coverage_notes") or [])

    engine = gateway.get("policyEngineConfiguration")
    if not engine:
        policy_engine = {"association": "unlinked", "arn": None, "mode": None}
    elif engine.get("arn"):
        policy_engine = {
            "association": "linked",
            "arn": engine["arn"],
            "mode": engine.get("mode"),
        }
    else:
        policy_engine = {
            "association": "unknown",
            "arn": None,
            "mode": engine.get("mode"),
        }

    context = {
        "source": "gateway",
        "region": arn.region,
        "gateway_arn": arn.arn,
        "gateway_url": endpoint,
        "auth": auth,
        "principal": {
            "entity_type": PRINCIPAL_TYPES[auth_type],
            "notes": list(PRINCIPAL_NOTES[auth_type]),
        },
        "policy_engine": policy_engine,
        "targets": targets,
        "gaps": _dedupe(gaps + list(merge_gaps)),
        "coverage_notes": _dedupe(notes),
        "guardrail_providers": None,
    }
    return {"status": "ready", "context": context}


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = acp_common.canonical_json(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
