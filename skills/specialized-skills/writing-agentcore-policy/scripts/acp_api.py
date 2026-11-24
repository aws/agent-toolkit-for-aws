"""Allowlisted ``bedrock-agentcore-control`` operations with preview/approve writes.

Reads run immediately and follow every ``nextToken``. Writes are two-step:

1. Without ``approve`` nothing is written to AWS. The exact boto3 calls are built, hashed
   (sha256 of the canonical JSON, with the generated ``clientToken`` excluded) and stored under
   ``<state>/previews/<token>.json`` together with the clientToken. The result is
   ``{"status": "approval_required", "approval_token", "requests", "impact"}``.
2. With ``approve=<token>`` the same request is rebuilt from the same params and must hash to
   the token and match the stored preview, otherwise the call is refused. The stored clientToken
   is reused so a retry of the approved call is idempotent. The preview file is removed once the
   write was accepted by AWS.
   The hash also covers the engine's state at preview time (engine id, whether the context
   Gateway links it, enforcement mode, read with GetGateway). A link or mode change between
   preview and approve, or a preview older than 30 minutes, is refused as ``approval_stale``.

After a write the resource is awaited (<= 5 minutes) and a Get call ALWAYS finishes the
operation, also when the waiter fails or times out. The result is data, not an exception:
``{"status": <terminal or last status>, "statusReasons": [...], "resource": {...}, "outcome":
"succeeded" | "failed" | "timed_out"}``. A resource that ended in ``CREATE_FAILED`` etc. is
returned with its ``statusReasons`` so the agent can revise; only API errors raise
``SkillError``. Deletes report ``status: "DELETED"`` once Get answers NotFound.

``validate_on_service`` checks one statement on the AgentCore Policy service when local checks
cannot (no Dogwood CLI). There is no dry-run API, so after approval it creates a temporary
policy engine that is not linked to any Gateway, creates the policy in it (``LOG_ONLY``), reads
the result, and always deletes both. It is offered only for a context prepared from a Gateway
ARN. The temporary resource ids are recorded under ``<state>/service_checks/`` until deleted,
so a failed cleanup is visible and its resources can be named to the developer.

Environment variables read: none (boto3 reads AWS_PROFILE / AWS_REGION itself).
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from acp_common import (
    SkillError,
    aws_error,
    canonical_json,
    control_client,
    parse_gateway_arn,
    read_json,
    sha256_hex,
    write_json,
)

READ_OPERATIONS = (
    "get_gateway",
    "list_gateway_targets",
    "get_gateway_target",
    "get_policy_engine",
    "get_policy",
    "list_policies",
)
WRITE_OPERATIONS = (
    "create_policy_engine",
    "update_policy_engine",
    "create_policy",
    "update_policy",
    "delete_policy",
    "delete_policy_engine",
    "teardown_policy_engine",
    "validate_on_service",
)

# Allowed snake_case parameters per operation (required first); mapped to API member names.
_PARAMS: dict[str, dict[str, str]] = {
    "get_gateway": {"gateway_identifier": "gatewayIdentifier"},
    "list_gateway_targets": {"gateway_identifier": "gatewayIdentifier"},
    "get_gateway_target": {
        "gateway_identifier": "gatewayIdentifier",
        "target_id": "targetId",
    },
    "get_policy_engine": {"policy_engine_id": "policyEngineId"},
    "get_policy": {"policy_engine_id": "policyEngineId", "policy_id": "policyId"},
    "list_policies": {
        "policy_engine_id": "policyEngineId",
        "target_resource_scope": "targetResourceScope",
    },
    "create_policy_engine": {
        "name": "name",
        "description": "description",
        "encryption_key_arn": "encryptionKeyArn",
        "tags": "tags",
    },
    "update_policy_engine": {
        "policy_engine_id": "policyEngineId",
        "description": "description",
    },
    "create_policy": {
        "policy_engine_id": "policyEngineId",
        "name": "name",
        "statement": "",
        "description": "description",
        "enforcement_mode": "enforcementMode",
        "validation_mode": "validationMode",
    },
    "update_policy": {
        "policy_engine_id": "policyEngineId",
        "policy_id": "policyId",
        "statement": "",
        "description": "description",
        "enforcement_mode": "enforcementMode",
        "validation_mode": "validationMode",
    },
    "delete_policy": {"policy_engine_id": "policyEngineId", "policy_id": "policyId"},
    "delete_policy_engine": {"policy_engine_id": "policyEngineId"},
    "teardown_policy_engine": {"policy_engine_id": "policyEngineId"},
    "validate_on_service": {"statement": ""},
}
_REQUIRED: dict[str, tuple[str, ...]] = {
    "get_gateway": ("gateway_identifier",),
    "list_gateway_targets": ("gateway_identifier",),
    "get_gateway_target": ("gateway_identifier", "target_id"),
    "get_policy_engine": ("policy_engine_id",),
    "get_policy": ("policy_engine_id", "policy_id"),
    "list_policies": ("policy_engine_id",),
    "create_policy_engine": ("name",),
    "update_policy_engine": ("policy_engine_id", "description"),
    "create_policy": ("policy_engine_id", "name", "statement"),
    "update_policy": ("policy_engine_id", "policy_id"),
    "delete_policy": ("policy_engine_id", "policy_id"),
    "delete_policy_engine": ("policy_engine_id",),
    "teardown_policy_engine": ("policy_engine_id",),
    "validate_on_service": ("statement",),
}

# list operation -> (response key holding the items, key used in the merged result)
_LIST_KEYS = {
    "list_gateway_targets": "items",
    "list_policy_engines": "policyEngines",
    "list_policies": "policies",
}
MAX_PAGES = 200

# Waiter pacing: 5 minutes at most per wait (botocore waiter Delay / MaxAttempts).
WAIT_DELAY = {"active": 5, "deleted": 2}
WAIT_MAX_ATTEMPTS = {"active": 60, "deleted": 150}

_IDENT = re.compile(r"^[A-Za-z0-9_.:/@][A-Za-z0-9_\-.:/@]{0,511}$")
_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_VALIDATION_MODES = ("FAIL_ON_ANY_FINDINGS", "IGNORE_ALL_FINDINGS")
_ENFORCEMENT_MODES = ("ACTIVE", "LOG_ONLY")
_STRICT = "FAIL_ON_ANY_FINDINGS"
PREVIEW_TTL = datetime.timedelta(minutes=30)


def _validation() -> Any:
    import acp_validation as validation

    return validation


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------


def run(
    sess: Any,
    operation: str,
    params: dict[str, Any] | None,
    *,
    approve: str | None = None,
    state: Path,
    context: dict[str, Any] | None = None,
    current_statement: str | None = None,
) -> dict[str, Any]:
    """Run one allowlisted operation. See the module docstring for the write protocol."""
    if operation not in READ_OPERATIONS and operation not in WRITE_OPERATIONS:
        raise SkillError(
            "invalid_input",
            f"unknown operation '{operation}'",
            input="operation",
            allowed=list(READ_OPERATIONS + WRITE_OPERATIONS),
        )
    params = dict(params or {})
    unknown = sorted(set(params) - set(_PARAMS[operation]))
    if unknown:
        raise SkillError(
            "invalid_input",
            f"unknown parameter(s) for {operation}: {', '.join(unknown)}",
            input="params",
            allowed=sorted(_PARAMS[operation]),
        )
    missing = [k for k in _REQUIRED.get(operation, ()) if params.get(k) is None]
    if missing:
        raise SkillError(
            "invalid_input",
            f"{operation} needs: {', '.join(missing)}",
            input="params",
            missing=missing,
        )
    client = control_client(sess)
    if operation in READ_OPERATIONS:
        if approve:
            raise SkillError("invalid_input", f"{operation} is a read; --approve does not apply")
        return _read(client, operation, params)
    state = Path(state)
    if operation == "teardown_policy_engine":
        _check_teardown_allowed(state, _ident(params, "policy_engine_id"))
    if operation == "validate_on_service":
        requests, impact = _build_service_check(params, context)
    else:
        requests, impact = _build(client, operation, params, context)
    if current_statement is not None and operation == "update_policy":
        # The stored statement that an enforcement-mode switch starts enforcing; read again on
        # approve and covered by the token, so a statement changed in between is approval_stale.
        impact["statement_to_enforce"] = current_statement
    stored: dict[str, Any] | None = None
    if approve and operation == "validate_on_service":
        # The temporary engine and policy names are per-attempt ids generated at preview time.
        # Reuse the previewed ones; they stay inside the hash, so approval covers exactly
        # those resources.
        stored = _load_preview(state, approve)
        previewed_requests = stored.get("requests") or []
        for index in (0, 1):
            if index >= len(previewed_requests):
                break
            previewed = previewed_requests[index].get("params", {}).get("name")
            if isinstance(previewed, str) and previewed.startswith(SERVICE_CHECK_PREFIX):
                requests[index]["params"]["name"] = previewed
    token = sha256_hex(canonical_json(_approved_data(requests, impact)))
    if not approve:
        return _preview(state, token, operation, requests, impact)
    if stored is None:
        stored = _load_preview(state, approve)
    if approve != token or stored.get("operation") != operation:
        _drop_preview(state, approve)
        extra = {}
        previewed_state = (stored.get("impact") or {}).get("engine_state")
        if stored.get("operation") == operation and previewed_state != impact.get("engine_state"):
            extra["hint"] = (
                "the engine's link to the Gateway or its enforcement mode changed since the "
                "preview; preview again"
            )
        elif operation == "teardown_policy_engine":
            extra["hint"] = "the engine's policy set changed since the preview; preview again"
        raise SkillError(
            "approval_stale",
            "the approval token does not match the request rebuilt from these parameters "
            "(parameters or remote state changed); preview again and ask for a new approval",
            operation=operation,
            **extra,
        )
    # Reuse the clientToken generated for the preview: a retried approval is idempotent.
    _apply_tokens(requests, stored["requests"])
    if canonical_json(_hashable(stored["requests"])) != canonical_json(_hashable(requests)):
        _drop_preview(state, approve)
        raise SkillError(
            "approval_stale", "stored preview does not match the request; preview again"
        )
    if operation == "validate_on_service":
        _drop_preview(state, approve)
        result = _run_service_check(client, requests, state, token)
        result["operation"] = operation
        return result
    result = _execute(client, operation, requests)
    _drop_preview(state, approve)
    if operation == "create_policy_engine" and result.get("created_id"):
        _remember_engine(state, result["created_id"], "create_policy_engine")
    elif operation == "teardown_policy_engine" and result.get("outcome") == "succeeded":
        _forget_engine(state, requests[-1]["params"]["policyEngineId"])
    result["operation"] = operation
    return result


# --------------------------------------------------------------------------------------
# engines created by this skill (the only ones teardown may remove)
# --------------------------------------------------------------------------------------

CREATED_ENGINES_FILE = "created_engines.json"


def _created_engines(state: Path) -> dict[str, Any]:
    data = read_json(state / CREATED_ENGINES_FILE, {})
    return data if isinstance(data, dict) else {}


def _remember_engine(state: Path, engine_id: str, origin: str) -> None:
    """Record an engine id returned by this skill's own create call."""
    data = _created_engines(state)
    data[engine_id] = {
        "origin": origin,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    write_json(state / CREATED_ENGINES_FILE, data)


def _forget_engine(state: Path, engine_id: str) -> None:
    data = _created_engines(state)
    if data.pop(engine_id, None) is not None:
        write_json(state / CREATED_ENGINES_FILE, data)


def _check_teardown_allowed(state: Path, engine_id: str) -> None:
    """Teardown removes only a brand-new engine that this skill created, never an existing one."""
    if engine_id not in _created_engines(state):
        raise SkillError(
            "teardown_not_allowed",
            f"teardown refused: engine {engine_id} was not created by this skill in this "
            "working directory. Teardown only removes a new engine created here with "
            "`api create_policy_engine`; it never deletes an existing engine or its policies",
            policy_engine_id=engine_id,
        )


# --------------------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------------------


def _read(client: Any, operation: str, params: dict[str, Any]) -> dict[str, Any]:
    kwargs = _api_params(operation, params)
    method = getattr(client, operation)
    try:
        if operation in _LIST_KEYS:
            return _list_all(method, operation, kwargs)
        return {"operation": operation, "resource": _clean(method(**kwargs))}
    except SkillError:
        raise
    except Exception as exc:  # botocore errors only carry through aws_error
        raise aws_error(exc, operation) from exc


def _list_all(method: Callable[..., Any], operation: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    items: list[Any] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        page = method(**kwargs, **({"nextToken": token} if token else {}))
        items.extend(page.get(_list_item_key(operation, page), []))
        token = page.get("nextToken")
        if not token:
            return {
                "operation": operation,
                _LIST_KEYS[operation]: _clean(items),
                "count": len(items),
            }
    raise SkillError(
        "too_many_pages",
        f"{operation} returned more than {MAX_PAGES} pages; narrow the request",
        operation=operation,
    )


def _list_item_key(operation: str, page: dict[str, Any]) -> str:
    """The response member holding the items (``items`` for the Gateway target list)."""
    if operation == "list_gateway_targets":
        return "items"
    return _LIST_KEYS[operation]


# --------------------------------------------------------------------------------------
# parameter checks and request building
# --------------------------------------------------------------------------------------


def _text(params: dict[str, Any], key: str) -> str:
    value = params[key]
    if not isinstance(value, str):
        raise SkillError("invalid_input", f"parameter '{key}' must be a string", input=key)
    return value


def _ident(params: dict[str, Any], key: str) -> str:
    value = _text(params, key)
    if not _IDENT.match(value):
        raise SkillError("invalid_input", f"parameter '{key}' is not a valid identifier", input=key)
    return value


def _api_params(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, api_name in _PARAMS[operation].items():
        if key not in params or params[key] is None:
            continue
        if key == "target_resource_scope":
            value = _text(params, key)
            if not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
                raise SkillError("invalid_input", f"parameter '{key}' is not valid", input=key)
            out[api_name] = value
        else:
            out[api_name] = _ident(params, key)
    return out


def _description(value: Any) -> str:
    if not isinstance(value, str):
        raise SkillError("invalid_input", "description must be a string", input="description")
    if len(value) > 4096:
        raise SkillError(
            "invalid_input",
            "description must be at most 4096 characters",
            input="description",
        )
    return value


def _choice(key: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise SkillError(
            "invalid_input",
            f"parameter '{key}' must be one of {', '.join(allowed)}",
            input=key,
        )
    return value


def _enforcement_mode(value: Any) -> str:
    if value == "ENFORCE":
        raise SkillError(
            "invalid_input",
            "enforcement_mode on a policy must be ACTIVE or LOG_ONLY. ENFORCE is only valid for "
            "a Gateway's policy engine configuration, a separate setting this skill does not "
            "change; use ACTIVE to make this policy enforce.",
            input="enforcement_mode",
        )
    return _choice("enforcement_mode", value, _ENFORCEMENT_MODES)


def _resolve_validation_mode(statement: str, requested: Any) -> tuple[str, str]:
    """Return (mode, reason). The mode follows from the statement and cannot be overridden:
    guardrail statements need IGNORE_ALL_FINDINGS, every other statement FAIL_ON_ANY_FINDINGS,
    so a caller cannot suppress the service's analysis findings on an ordinary policy."""
    required = _validation().required_validation_mode(statement)
    guardrail = required == "IGNORE_ALL_FINDINGS"
    if (
        requested is not None
        and _choice("validation_mode", requested, _VALIDATION_MODES) != required
    ):
        if guardrail:
            raise SkillError(
                "invalid_input",
                f"this statement invokes a guardrail, which requires validation_mode='{required}': "
                "the default FAIL_ON_ANY_FINDINGS rejects it on findings a correct guardrail policy "
                f"necessarily produces. Pass validation_mode='{required}' and review the returned "
                "findings; this setting neither requires nor authorizes adding a broader permit.",
                input="validation_mode",
            )
        raise SkillError(
            "invalid_input",
            f"this statement does not invoke a guardrail, so it is submitted with "
            f"validation_mode='{required}': the service's findings (for example Overly "
            "Permissive or Overly Restrictive) must be fixed in the statement, not suppressed.",
            input="validation_mode",
        )
    if guardrail:
        return required, (
            "the statement invokes a guardrail; the default FAIL_ON_ANY_FINDINGS rejects "
            "correct guardrail policies because they necessarily produce findings. "
            "Review the returned findings; this mode does not authorize a broader permit."
        )
    return required, "default: reject the policy if the service reports any finding"


def _statement(params: dict[str, Any]) -> str:
    statement = _text(params, "statement")
    _validation().check_statement_limits(statement)
    return statement


def _description_update(value: Any) -> dict[str, Any]:
    text = _description(value)
    return {"optionalValue": text} if text else {}


# --------------------------------------------------------------------------------------
# service-side validation (temporary engine)
# --------------------------------------------------------------------------------------

SERVICE_CHECK_PREFIX = "acp_check_"
SERVICE_CHECK_DESCRIPTION = (
    "Temporary engine created by the writing-agentcore-policy skill to validate one policy on "
    "the service; safe to delete."
)
_ENGINE_PLACEHOLDER = "<temporary engine id>"
_POLICY_PLACEHOLDER = "<temporary policy id>"


def _build_service_check(
    params: dict[str, Any], context: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not context or context.get("source") != "gateway" or not context.get("gateway_arn"):
        raise SkillError(
            "invalid_input",
            "service-side validation needs a context prepared from a Gateway ARN "
            "(`prepare gateway`); it is not available for schema files",
            input="context",
        )
    statement = _statement(params)
    mode, reason = _resolve_validation_mode(statement, None)
    # A unique id per attempt, so recovery by name can only ever match this attempt's engine.
    # The policy name is unique too: policy names are unique per account and Region, so a fixed
    # name would collide with a policy an earlier, incomplete cleanup left behind.
    engine_name = f"{SERVICE_CHECK_PREFIX}{uuid.uuid4().hex[:16]}"
    policy_name = f"{SERVICE_CHECK_PREFIX}policy_{uuid.uuid4().hex[:16]}"
    requests = [
        _request(
            "create_policy_engine",
            {
                "name": engine_name,
                "description": SERVICE_CHECK_DESCRIPTION,
                "clientToken": str(uuid.uuid4()),
            },
        ),
        _request(
            "create_policy",
            {
                "policyEngineId": _ENGINE_PLACEHOLDER,
                "name": policy_name,
                "definition": _validation().definition_for(statement),
                "validationMode": mode,
                "enforcementMode": "LOG_ONLY",
                "clientToken": str(uuid.uuid4()),
            },
        ),
        _request(
            "delete_policy",
            {"policyEngineId": _ENGINE_PLACEHOLDER, "policyId": _POLICY_PLACEHOLDER},
        ),
        _request("delete_policy_engine", {"policyEngineId": _ENGINE_PLACEHOLDER}),
    ]
    impact = {
        "summary": "creates a temporary policy engine and one policy in it, reads the service's "
        "validation result, then deletes the policy and the engine",
        "gateway": context["gateway_arn"],
        "temporary_engine_name": engine_name,
        "existing_engines_touched": False,
        "live_authorization_change": False,
        "live_note": "the policy is created only in the temporary engine, which nothing uses, "
        "and both are deleted after the verdict",
        "validation_mode": mode,
        "validation_mode_reason": reason,
        "cleanup": "deletes every policy found in the temporary engine (normally just this "
        "one), then the engine; ids are filled in after creation",
        "resources_left_on_failure": "if a delete fails, the engine id is reported and kept in "
        "the session state until deleted",
        "permissions_needed": [
            "bedrock-agentcore:CreatePolicyEngine",
            "bedrock-agentcore:CreatePolicy",
            "bedrock-agentcore:GetPolicyEngine",
            "bedrock-agentcore:GetPolicy",
            "bedrock-agentcore:DeletePolicy",
            "bedrock-agentcore:DeletePolicyEngine",
            "bedrock-agentcore:ListPolicies",
            "bedrock-agentcore:ListPolicyEngines",
        ],
    }
    if mode == "IGNORE_ALL_FINDINGS":
        impact["coverage_note"] = (
            "guardrail statements must use IGNORE_ALL_FINDINGS, so the service reports parse and "
            "schema problems but skips its own analysis findings"
        )
    return requests, impact


def _record_path(state: Path, token: str) -> Path:
    return state / "service_checks" / f"{token}.json"


def _run_service_check(
    client: Any, requests: list[dict[str, Any]], state: Path, token: str
) -> dict[str, Any]:
    """Create the temporary engine and policy, read the verdict, always clean up.

    The engine name is recorded before any write, so an engine whose create call failed
    after it was accepted can still be found by name and deleted. Cleanup never replaces the
    verdict or the original error; it is reported next to them.
    """
    create_engine, create_policy, _, _ = (dict(r["params"]) for r in requests)
    record_file = _record_path(state, token)
    name = create_engine["name"]
    write_json(record_file, {"engine_name": name, "policy_engine_id": None})
    engine_id: str | None = None
    error: SkillError | None = None
    result: dict[str, Any] = {}
    try:
        engine = _step(client, _request("create_policy_engine", create_engine))
        engine_id = engine.get("created_id")
        write_json(record_file, {"engine_name": name, "policy_engine_id": engine_id})
        if engine["outcome"] != "succeeded":
            result = {
                "service_validation": "unavailable",
                "reason": f"the temporary engine did not become ACTIVE ({engine['status']})",
                "statusReasons": engine["statusReasons"],
            }
        else:
            create_policy["policyEngineId"] = engine_id
            try:
                policy = _step(client, _request("create_policy", create_policy))
            except SkillError as exc:
                if exc.kind != "validation":
                    raise
                # CreatePolicy rejected the statement synchronously.
                result = {
                    "service_validation": "rejected",
                    "status": None,
                    "statusReasons": [exc.message],
                }
            else:
                verdict = {"succeeded": "passed", "failed": "rejected"}.get(
                    policy["outcome"], "unknown"
                )
                result = {
                    "service_validation": verdict,
                    "status": policy["status"],
                    "statusReasons": policy["statusReasons"],
                }
    except SkillError as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 - reported with the cleanup outcome
        error = SkillError("aws_error", f"service check failed: {type(exc).__name__}")
    if engine_id is None:
        engine_id = _find_engine_by_name(client, name)
    if engine_id is None and error is not None:
        # The create call failed; whether an engine exists could not be confirmed.
        cleanup: dict[str, Any] = {
            "complete": False,
            "steps": [],
            "left_behind": {"engine_name": name},
            "next": f"a temporary engine named {name} (description: "
            f"{SERVICE_CHECK_DESCRIPTION!r}) may remain in the account. Tell the developer its "
            "name and description so they can find it; once its id is known it can be deleted "
            "with `api delete_policy_engine` (preview and approval)",
        }
    else:
        cleanup = _cleanup_service_check(client, engine_id)
    if cleanup["complete"]:
        record_file.unlink(missing_ok=True)
    else:
        write_json(record_file, {"engine_name": name, "policy_engine_id": engine_id})
    if error is not None:
        raise SkillError(error.kind, error.message, **error.details, cleanup=cleanup)
    result["cleanup"] = cleanup
    return result


def _find_engine_by_name(client: Any, name: str) -> str | None:
    """The id of this attempt's engine: exactly one engine with this name and our description.

    Anything else (no match, several matches, a foreign description, a failed lookup) returns
    None, and the caller keeps the record instead of deleting anything.
    """
    try:
        listed = _list_all(client.list_policy_engines, "list_policy_engines", {})
    except Exception:  # noqa: BLE001 - lookup failure is reported as unknown cleanup
        return None
    matches = [e for e in listed.get("policyEngines", []) if e.get("name") == name]
    if len(matches) != 1 or matches[0].get("description") != SERVICE_CHECK_DESCRIPTION:
        return None
    return matches[0].get("policyEngineId")


def _cleanup_service_check(client: Any, engine_id: str | None) -> dict[str, Any]:
    """Delete every policy in the temporary engine, then the engine. Never raises."""
    steps: list[dict[str, Any]] = []
    if not engine_id:
        return {
            "complete": True,
            "steps": steps,
            "note": "no temporary engine was created",
        }
    complete = False
    try:
        listed = _list_all(client.list_policies, "list_policies", {"policyEngineId": engine_id})
        for summary in listed.get("policies", []):
            step = _step(
                client,
                _request(
                    "delete_policy",
                    {"policyEngineId": engine_id, "policyId": summary["policyId"]},
                ),
            )
            steps.append({"method": "delete_policy", "status": step["status"]})
        step = _step(client, _request("delete_policy_engine", {"policyEngineId": engine_id}))
        steps.append({"method": "delete_policy_engine", "status": step["status"]})
        complete = all(s["status"] == "DELETED" for s in steps)
    except SkillError as exc:
        steps.append({"error": exc.kind, "message": exc.message})
    except Exception as exc:  # noqa: BLE001 - never mask the verdict
        steps.append({"error": "aws_error", "message": type(exc).__name__})
    out: dict[str, Any] = {"complete": complete, "steps": steps}
    if not complete:
        out["left_behind"] = {"policy_engine_id": engine_id}
        out["next"] = (
            "tell the developer the temporary engine was not fully deleted and give its id; "
            "remove its policies with `api delete_policy`, then the engine with "
            "`api delete_policy_engine` (each with preview and approval)"
        )
    return out


def _build(
    client: Any, operation: str, params: dict[str, Any], context: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (exact boto3 calls, impact block) for a write. Teardown lists policies (read)."""
    impact: dict[str, Any] = {}
    if operation == "create_policy_engine":
        _validation().check_name(_text(params, "name"))
        call: dict[str, Any] = {"name": params["name"]}
        if params.get("description"):
            call["description"] = _description(params["description"])
        if params.get("encryption_key_arn"):
            arn = _text(params, "encryption_key_arn")
            if not arn.startswith("arn:") or len(arn) > 2048 or re.search(r"[\s\x00-\x1f]", arn):
                raise SkillError("invalid_input", "encryption_key_arn is not a valid ARN")
            call["encryptionKeyArn"] = arn
        if params.get("tags") is not None:
            tags = params["tags"]
            if (
                not isinstance(tags, dict)
                or len(tags) > 50
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items())
            ):
                raise SkillError(
                    "invalid_input",
                    "tags must be an object of at most 50 string values",
                )
            call["tags"] = tags
        call["clientToken"] = str(uuid.uuid4())
        impact = {
            "summary": "creates an empty policy engine; it enforces nothing until linked to a "
            "Gateway (a separate step this skill does not perform)",
            "live_authorization_change": False,
        }
        return [_request("create_policy_engine", call)], impact

    # Every other write targets an existing engine; required params were checked by the caller.
    engine_id = _ident(params, "policy_engine_id")
    link = _read_link(client, context)

    if operation == "update_policy_engine":
        call = {
            "policyEngineId": engine_id,
            "description": _description_update(params["description"]),
        }
        impact = _engine_impact(engine_id, context, link)
        impact["summary"] = "changes the engine description only"
        impact["live_authorization_change"] = False
        return [_request("update_policy_engine", call)], impact

    if operation in ("create_policy", "update_policy"):
        return _build_policy_write(operation, params, engine_id, context, link)

    if operation == "delete_policy":
        call = {"policyEngineId": engine_id, "policyId": _ident(params, "policy_id")}
        impact = _engine_impact(engine_id, context, link)
        impact["summary"] = "deletes the policy; its permit/forbid no longer applies"
        impact["live_authorization_change"] = impact["engine_linked_enforcing"] is not False
        impact["live_note"] = _live_note(impact, "deleting a policy")
        return [_request("delete_policy", call)], impact

    if operation == "delete_policy_engine":
        impact = _engine_impact(engine_id, context, link)
        impact["summary"] = (
            "deletes the engine; the service refuses while the engine still has policies "
            "(use teardown_policy_engine to remove them first) or is linked to a Gateway"
        )
        impact["live_authorization_change"] = impact["engine_linked_enforcing"] is not False
        return [_request("delete_policy_engine", {"policyEngineId": engine_id})], impact

    # teardown_policy_engine: the caller already checked the engine was created by this skill.
    # The context Gateway was just read (also again at approve time): if it uses this engine,
    # or the read could not tell, stop before anything is deleted.
    engine_link = _engine_state(engine_id, link)["link"]
    if engine_link == "linked":
        raise SkillError(
            "engine_attached",
            f"Policy engine {engine_id} seems to be associated with a gateway, skipping teardown.",
            policy_engine_id=engine_id,
            gateway=link.get("gateway"),
        )
    if engine_link == "unknown":
        raise SkillError(
            "engine_link_unknown",
            f"Could not confirm that the Gateway does not use policy engine {engine_id} "
            f"({link['reason']}), skipping teardown.",
            policy_engine_id=engine_id,
        )
    try:
        policies = _list_all(client.list_policies, "list_policies", {"policyEngineId": engine_id})[
            "policies"
        ]
    except SkillError:
        raise
    except Exception as exc:
        raise aws_error(exc, "list_policies") from exc
    requests = [
        _request("delete_policy", {"policyEngineId": engine_id, "policyId": p["policyId"]})
        for p in policies
    ]
    requests.append(_request("delete_policy_engine", {"policyEngineId": engine_id}))
    impact = _engine_impact(engine_id, context, link)
    impact["policies_to_delete"] = [
        {"policyId": p["policyId"], "name": p.get("name")} for p in policies
    ]
    impact["summary"] = (
        f"deletes the {len(policies)} policies one by one first, then the engine itself last; "
        "irreversible"
    )
    impact["live_authorization_change"] = impact["engine_linked_enforcing"] is not False
    impact["live_note"] = _live_note(impact, "tearing down this engine")
    return requests, impact


def _build_policy_write(
    operation: str,
    params: dict[str, Any],
    engine_id: str,
    context: dict[str, Any] | None,
    link: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    call: dict[str, Any] = {"policyEngineId": engine_id}
    impact = _engine_impact(engine_id, context, link)
    creating = operation == "create_policy"
    if creating:
        _validation().check_name(_text(params, "name"))
        call["name"] = params["name"]
    else:
        call["policyId"] = _ident(params, "policy_id")
    changed = creating
    reason = None
    if params.get("statement") is not None:
        statement = _statement(params)
        call["definition"] = _validation().definition_for(statement)
        mode, reason = _resolve_validation_mode(statement, params.get("validation_mode"))
        call["validationMode"] = mode
        changed = True
    elif params.get("validation_mode") is not None:
        raise SkillError(
            "invalid_input",
            "validation_mode only applies together with a statement",
            input="validation_mode",
        )
    if "description" in params and params["description"] is not None:
        if creating:
            if _description(params["description"]):
                call["description"] = params["description"]
        else:
            call["description"] = _description_update(params["description"])
            changed = True
    if params.get("enforcement_mode") is not None:
        call["enforcementMode"] = _enforcement_mode(params["enforcement_mode"])
        changed = True
    if not changed:
        raise SkillError(
            "invalid_input",
            "nothing to update; pass statement, description or enforcement_mode",
            input="params",
        )
    if creating:
        call["clientToken"] = str(uuid.uuid4())
    impact["enforcement_mode"] = call.get("enforcementMode", "service default (ACTIVE)")
    if "validationMode" in call:
        impact["validation_mode"] = call["validationMode"]
        impact["validation_mode_reason"] = reason
    enforcing = impact["enforcement_mode"] != "LOG_ONLY"
    impact["live_authorization_change"] = bool(
        enforcing and impact["engine_linked_enforcing"] is not False
    )
    impact["summary"] = (
        "creates a policy" if creating else "updates the policy (definition replaced if given)"
    )
    impact["live_note"] = _live_note(impact, "accepting this policy", enforcing=enforcing)
    return [_request(operation, call)], impact


def _read_link(client: Any, context: dict[str, Any] | None) -> dict[str, Any]:
    """Read the context Gateway's policy engine link now (GetGateway, the allowed Gateway read).

    ``read`` is False, with a ``reason``, when there is no Gateway in the context or the
    read failed: the link is then unknown, never assumed absent.
    """
    arn = (context or {}).get("gateway_arn")
    if not arn:
        return {"read": False, "reason": "the context has no Gateway"}
    try:
        gateway_id = parse_gateway_arn(arn).gateway_id
    except SkillError:
        return {"read": False, "reason": "the context's Gateway ARN is invalid"}
    try:
        gateway = client.get_gateway(gatewayIdentifier=gateway_id)
    except Exception as exc:  # noqa: BLE001 - reported as an unknown link
        kind = aws_error(exc, "get_gateway").kind
        return {"read": False, "reason": f"GetGateway failed ({kind})"}
    config = gateway.get("policyEngineConfiguration") or {}
    if config and not config.get("arn"):
        return {
            "read": False,
            "reason": "GetGateway returned a policy engine configuration without an engine ARN",
        }
    return {
        "read": True,
        "gateway": gateway_id,
        "arn": config.get("arn"),
        "mode": config.get("mode"),
    }


def _engine_state(engine_id: str, link: dict[str, Any]) -> dict[str, Any]:
    """The engine's state as covered by the approval hash: id, link state, enforcement mode."""
    if not link["read"]:
        return {"engine_id": engine_id, "link": "unknown"}
    arn = link["arn"]
    if arn and arn.rsplit("/", 1)[-1] == engine_id:
        return {
            "engine_id": engine_id,
            "gateway": link["gateway"],
            "link": "linked",
            "linked_engine_arn": arn,
            "mode": link["mode"],
        }
    return {"engine_id": engine_id, "gateway": link["gateway"], "link": "not_linked"}


def _engine_impact(
    engine_id: str, context: dict[str, Any] | None, link: dict[str, Any]
) -> dict[str, Any]:
    """Relate the destination engine to the context Gateway's policy engine association.

    The live GetGateway read decides when it succeeded. Otherwise the prepare-time context is
    only a hint: it can name this engine as linked, but it can never prove another engine
    (or none) is linked now, so that case is reported as unknown.
    """
    state = _engine_state(engine_id, link)
    linked: bool | None
    if state["link"] == "linked":
        linked, mode = True, state["mode"]
    elif state["link"] == "not_linked":
        linked, mode = False, None
    else:
        engine = (context or {}).get("policy_engine") or {}
        arn = engine.get("arn")
        if arn and arn.rsplit("/", 1)[-1] == engine_id:
            linked, mode = True, engine.get("mode")
        else:
            linked, mode = None, None
    out: dict[str, Any] = {
        "destination_engine": engine_id,
        "engine_linked_to_context_gateway": linked,
        "gateway_policy_engine_mode": mode,
        # True: enforcing now; False: provably not; None: unknown
        "engine_linked_enforcing": (
            (mode == "ENFORCE") if linked else (False if linked is False else None)
        ),
        "engine_state": state,
        "link_source": (
            "GetGateway read at preview time"
            if link["read"]
            else f"not re-read ({link['reason']}); prepare-time context only"
        ),
    }
    return out


def _live_note(impact: dict[str, Any], what: str, *, enforcing: bool = True) -> str:
    linked = impact["engine_linked_enforcing"]
    if not enforcing:
        return "enforcement_mode LOG_ONLY: decisions are logged, not enforced"
    if linked is True:
        return f"the engine is linked to the Gateway in ENFORCE: {what} changes live authorization immediately"
    if linked is False:
        return "the engine is not enforcing for the context Gateway (not linked or LOG_ONLY)"
    return (
        f"unknown whether the engine is linked to a Gateway in ENFORCE; if it is, {what} "
        "changes live authorization immediately"
    )


def _request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"method": method, "params": params}


def _hashable(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The requests as hashed: the generated clientToken is excluded."""
    return [
        {
            "method": r["method"],
            "params": {k: v for k, v in r["params"].items() if k != "clientToken"},
        }
        for r in requests
    ]


def _apply_tokens(requests: list[dict[str, Any]], stored: list[dict[str, Any]]) -> None:
    for fresh, old in zip(requests, stored):
        if "clientToken" in fresh["params"] and "clientToken" in old.get("params", {}):
            fresh["params"]["clientToken"] = old["params"]["clientToken"]


# --------------------------------------------------------------------------------------
# preview storage
# --------------------------------------------------------------------------------------


def _preview_path(state: Path, token: str) -> Path:
    if not isinstance(token, str) or not _TOKEN.match(token):
        raise SkillError(
            "approval_invalid",
            "approval token is not a valid token; preview the write first",
        )
    return state / "previews" / f"{token}.json"


def _preview(
    state: Path,
    token: str,
    operation: str,
    requests: list[dict[str, Any]],
    impact: dict[str, Any],
) -> dict[str, Any]:
    _sweep_expired_previews(state)
    write_json(
        _preview_path(state, token),
        {
            "approval_token": token,
            "operation": operation,
            "requests": requests,
            "impact": impact,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )
    return {
        "status": "approval_required",
        "operation": operation,
        "approval_token": token,
        "requests": requests,
        "impact": impact,
        "next": "show the requests and impact to the customer; after explicit approval repeat "
        "the identical command with --approve <approval_token>",
    }


def _load_preview(state: Path, token: str) -> dict[str, Any]:
    stored = read_json(_preview_path(state, token), None)
    if not isinstance(stored, dict) or stored.get("approval_token") != token:
        raise SkillError(
            "approval_invalid",
            "no stored preview matches this approval token; run the command without --approve "
            "first and use the token it returns",
        )
    if _preview_expired(stored.get("created_at")):
        _drop_preview(state, token)
        raise SkillError(
            "approval_stale",
            "the preview is older than 30 minutes; preview again and ask for a new approval",
            operation=stored.get("operation"),
        )
    return stored


def _preview_expired(created_at: Any) -> bool:
    try:
        created = datetime.datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return True
    if created.tzinfo is None:
        return True
    return datetime.datetime.now(datetime.timezone.utc) - created > PREVIEW_TTL


def _approved_data(requests: list[dict[str, Any]], impact: dict[str, Any]) -> dict[str, Any]:
    """What the approval token covers: the requests and the engine state (None if no engine)."""
    return {
        "requests": _hashable(requests),
        "engine_state": impact.get("engine_state"),
        "statement_to_enforce": impact.get("statement_to_enforce"),
    }


def _drop_preview(state: Path, token: str) -> None:
    try:
        _preview_path(state, token).unlink(missing_ok=True)
    except SkillError:
        pass


def _sweep_expired_previews(state: Path) -> None:
    """Delete previews past PREVIEW_TTL, so declined previews (every service-check preview has a
    unique engine name, so a unique token) do not pile up. Unreadable files go too: no approval
    could use them."""
    directory = state / "previews"
    if not directory.is_dir():
        return
    for path in directory.glob("*.json"):
        try:
            stored = read_json(path, None)
        except (SkillError, OSError):
            stored = None
        created = stored.get("created_at") if isinstance(stored, dict) else None
        if _preview_expired(created):
            path.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# execution and waiting
# --------------------------------------------------------------------------------------

# method -> (waiter, kind, Get method, id params for Get, response member holding the new id)
_AFTER = {
    "create_policy_engine": ("policy_engine_active", "active", "get_policy_engine"),
    "update_policy_engine": ("policy_engine_active", "active", "get_policy_engine"),
    "create_policy": ("policy_active", "active", "get_policy"),
    "update_policy": ("policy_active", "active", "get_policy"),
    "delete_policy": ("policy_deleted", "deleted", "get_policy"),
    "delete_policy_engine": ("policy_engine_deleted", "deleted", "get_policy_engine"),
}


def _label(request: dict[str, Any]) -> dict[str, Any]:
    return {"method": request["method"], "policyId": request["params"].get("policyId")}


def _execute(client: Any, operation: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    if operation != "teardown_policy_engine":
        return _step(client, requests[0])
    steps: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        try:
            step = _step(client, request)
        except SkillError as exc:
            # Keep the error kind; do not lose what already happened.
            raise SkillError(
                exc.kind,
                exc.message,
                **{
                    **exc.details,
                    "completed_steps": steps,
                    "failed_step": _label(request),
                    "not_run": [_label(r) for r in requests[index + 1 :]],
                },
            ) from exc
        steps.append(
            {
                "method": request["method"],
                "policyId": request["params"].get("policyId"),
                "status": step["status"],
                "statusReasons": step["statusReasons"],
                "outcome": step["outcome"],
            }
        )
        if step["outcome"] != "succeeded":
            not_run = [_label(r) for r in requests[index + 1 :]]
            return {
                "status": step["status"],
                "statusReasons": step["statusReasons"],
                "outcome": step["outcome"],
                "resource": step["resource"],
                "steps": steps,
                "skipped_steps": len(not_run),
                "not_run": not_run,
                "message": f"teardown stopped at {request['method']}; {len(not_run)} step(s) not run",
            }
    return {
        "status": "DELETED",
        "statusReasons": [],
        "outcome": "succeeded",
        "resource": None,
        "steps": steps,
    }


def _step(client: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Issue one write, wait for it to settle, and finish with a Get."""
    method = request["method"]
    params = request["params"]
    waiter_name, kind, getter = _AFTER[method]
    try:
        response = getattr(client, method)(**params)
    except Exception as exc:
        raise aws_error(exc, method) from exc
    engine_id = params.get("policyEngineId") or response.get("policyEngineId")
    if getter == "get_policy_engine":
        get_params = {"policyEngineId": engine_id}
    else:
        get_params = {
            "policyEngineId": engine_id,
            "policyId": params.get("policyId") or response.get("policyId"),
        }
    waiter_error: str | None = None
    try:
        client.get_waiter(waiter_name).wait(
            **get_params,
            WaiterConfig={
                "Delay": WAIT_DELAY[kind],
                "MaxAttempts": WAIT_MAX_ATTEMPTS[kind],
            },
        )
    except Exception as exc:
        from botocore.exceptions import WaiterError

        if not isinstance(exc, WaiterError):
            raise aws_error(exc, waiter_name) from exc
        waiter_error = exc.last_response.get("Error", {}).get("Code") or exc.kwargs.get("reason")
    result = _final_get(client, getter, get_params, deleted=kind == "deleted")
    if (
        waiter_error is not None
        and result["outcome"] == "succeeded"
        and result["status"] != "DELETED"
    ):
        # The waiter gave up but the resource is fine now (race at the boundary). A final Get
        # that finds the resource gone is definitive, so a delete stays succeeded: teardown
        # must not stop on a step that did delete its resource.
        result["outcome"] = "timed_out"
    result["created_id"] = (
        (get_params.get("policyId") or engine_id) if method.startswith("create") else None
    )
    if result["created_id"] is None:
        del result["created_id"]
    return result


def _final_get(
    client: Any, getter: str, get_params: dict[str, Any], *, deleted: bool
) -> dict[str, Any]:
    try:
        resource = _clean(getattr(client, getter)(**get_params))
    except Exception as exc:
        err = aws_error(exc, getter)
        if deleted and err.kind == "not_found":
            return {
                "status": "DELETED",
                "statusReasons": [],
                "outcome": "succeeded",
                "resource": None,
            }
        raise err from exc
    status = resource.get("status")
    if deleted:
        outcome = "failed" if status and status.endswith("_FAILED") else "timed_out"
    elif status == "ACTIVE":
        outcome = "succeeded"
    elif status and status.endswith("_FAILED"):
        outcome = "failed"
    else:
        outcome = "timed_out"
    return {
        "status": status,
        "statusReasons": resource.get("statusReasons") or [],
        "outcome": outcome,
        "resource": resource,
    }


# --------------------------------------------------------------------------------------
# output cleanup
# --------------------------------------------------------------------------------------


def _clean(value: Any) -> Any:
    """JSON-safe copy: datetimes become ISO strings, ResponseMetadata is dropped."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k != "ResponseMetadata"}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value
