#!/usr/bin/env python3
"""CLI for the writing-agentcore-policy skill.

Usage:
    python3 scripts/agentcore_policy.py [--state-dir DIR] [--region REGION] <command> ...

Every command prints one JSON object to stdout and exits 0, or prints
{"error": {...}} to stderr and exits 2 (expected failure) or 1 (unexpected failure).

Environment variables read (by name only):
    AGENTCORE_POLICY_DOGWOOD   path to the optional `dogwood` CLI (doctor only; see acp_validation)
    AGENTCORE_POLICY_STATE_DIR, AGENTCORE_POLICY_HOME (see acp_common)
boto3 reads AWS_PROFILE, AWS_REGION and AWS_DEFAULT_REGION itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

# The acp_* modules are imported from the skill's own scripts directory; never write
# __pycache__ there (it would end up inside the installed or packaged skill).
sys.dont_write_bytecode = True

MIN_PYTHON = (3, 10)
PINNED = {
    "cedarpy": "4.12.2",
    "cedar-policy-mcp-schema-generator": "0.6.1",
    "PyYAML": "6.0.3",
}
OPTIONAL_PACKAGES = frozenset({"PyYAML"})  # only needed to read YAML schema files
NEEDED_FOR = {
    "boto3": "to call AWS (Gateway discovery and policy submission)",
    "botocore": "to call AWS (installed with boto3)",
    "cedarpy": "to check the generated Cedar schema and validate Cedar statements locally",
    "cedar-policy-mcp-schema-generator": "to generate the Gateway's Cedar schema",
    "PyYAML": "only to read YAML schema files (converting them to JSON also works)",
}


def _emit(obj: Any, *, stream: Any = None) -> None:
    print(
        json.dumps(obj, indent=2, sort_keys=False, default=str),
        file=stream or sys.stdout,
    )


# --------------------------------------------------------------------------- helpers


def _session_for(args: argparse.Namespace, *, fallback_region: str | None = None) -> Any:
    import acp_common as common

    region = args.region
    if region is None:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region is None:
        region = fallback_region
    if region is None:
        manager = _manager(args)
        if manager.has_context():
            region = manager.get_context().get("region")
    return common.session(region)


def _manager(args: argparse.Namespace) -> Any:
    import acp_common as common
    import acp_context

    return acp_context.ContextManager(common.state_dir(args.state_dir))


def _parse_file_spec(spec: str) -> dict[str, str | None]:
    """PATH[:PROTOCOL[:TARGET]] — empty parts mean 'not answered yet'."""
    parts = spec.rsplit(":", 2) if spec.count(":") >= 2 else spec.split(":")
    path = parts[0]
    protocol = parts[1] if len(parts) > 1 and parts[1] else None
    target = parts[2] if len(parts) > 2 and parts[2] else None
    return {"path": path, "protocol": protocol, "target": target}


def _load_params(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common

    if args.params and args.params_file:
        raise common.SkillError("invalid_input", "use --params or --params-file, not both")
    raw = args.params
    if args.params_file:
        raw = common.read_input_file(args.params_file, input_name="params_file")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except ValueError as exc:
        raise common.SkillError("invalid_input", f"params are not valid JSON: {exc}") from exc
    if not isinstance(params, dict):
        raise common.SkillError("invalid_input", "params must be a JSON object")
    return params


# --------------------------------------------------------------------------- commands


def cmd_doctor(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": {
            "version": ".".join(map(str, sys.version_info[:3])),
            "ok": sys.version_info[:2] >= MIN_PYTHON,
        }
    }
    packages: dict[str, Any] = {}
    for name in ("boto3", "botocore", *PINNED):
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = None
        expected = PINNED.get(name)
        packages[name] = {
            "installed": version,
            "required": expected or "any",
            "ok": version is not None and (expected is None or version == expected),
        }
        if name in OPTIONAL_PACKAGES:
            packages[name]["optional"] = True
        if not packages[name]["ok"]:
            install = f"pip install {name}" + (f"=={expected}" if expected else "")
            packages[name]["install"] = install
            state = "missing" if version is None else f"{version} instead of {expected}"
            packages[name][
                "message"
            ] = f"{name} is {state}; it is needed {NEEDED_FOR[name]}. Install it with `{install}`."
    report["packages"] = packages

    import acp_validation

    dogwood = acp_validation.resolve_dogwood()
    dogwood_report: dict[str, Any] = {
        "supported": list(acp_validation.DOGWOOD_VERSIONS),
        "optional": True,
    }
    if dogwood:
        out = acp_validation.dogwood_version(dogwood)
        ok = out in acp_validation.DOGWOOD_VERSIONS
        dogwood_report.update({"found": True, "version": out, "ok": ok})
        if not ok:
            dogwood_report["install"] = acp_validation.DOGWOOD_SETUP
    else:
        dogwood_report.update(
            {
                "found": False,
                "ok": False,
                "message": acp_validation.DOGWOOD_MISSING,
                "install": acp_validation.DOGWOOD_SETUP,
            }
        )
    report["dogwood"] = dogwood_report
    report["ready"] = report["python"]["ok"] and all(
        p["ok"] for name, p in packages.items() if name not in OPTIONAL_PACKAGES
    )
    return report


def cmd_verify_aws(args: argparse.Namespace) -> dict[str, Any]:
    import acp_discovery

    return acp_discovery.verify_aws(_session_for(args))


def cmd_prepare_gateway(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common

    arn = common.parse_gateway_arn(args.gateway_arn)
    sess = _session_for(args, fallback_region=arn.region)
    return _manager(args).prepare_gateway(
        sess, arn.arn, client_id=args.client_id, login_failed=args.login_failed
    )


def cmd_prepare_files(args: argparse.Namespace) -> dict[str, Any]:
    files = [_parse_file_spec(spec) for spec in args.file]
    region = args.region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return _manager(args).prepare_files(
        files, auth_type=args.auth_type, gateway_arn=args.gateway_arn, region=region
    )


def cmd_login_start(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common
    import acp_oauth

    arn = common.parse_gateway_arn(args.gateway_arn)
    # The discovery URL and the allowed clients always come from the Gateway itself, so
    # nothing the agent passes can point the sign-in or the code exchange elsewhere.
    sess = _session_for(args, fallback_region=arn.region)
    client = common.control_client(sess)
    try:
        gateway = client.get_gateway(gatewayIdentifier=arn.gateway_id)
    except Exception as exc:  # botocore errors are mapped without response text
        raise common.aws_error(exc, "GetGateway") from exc
    jwt = (gateway.get("authorizerConfiguration") or {}).get("customJWTAuthorizer") or {}
    if gateway.get("authorizerType") != "CUSTOM_JWT" or not jwt:
        raise common.SkillError(
            "invalid_input",
            "this Gateway does not use CUSTOM_JWT inbound auth; no login needed",
        )
    discovery_url = jwt.get("discoveryUrl")
    if not discovery_url:
        raise common.SkillError(
            "oauth_failed", "the Gateway's CUSTOM_JWT authorizer has no discovery URL"
        )
    clients = jwt.get("allowedClients") or []
    client_id = args.client_id
    if client_id is not None and clients and client_id not in clients:
        raise common.SkillError(
            "invalid_input",
            "client_id is not one of this Gateway's allowed clients",
            input="client_id",
            choices=clients,
        )
    if client_id is None:
        if len(clients) != 1:
            return {
                "status": "input_required",
                "missing": [
                    {
                        "input": "client_id",
                        "choices": clients,
                        "message": "Which OAuth client should sign in? Ask the developer; "
                        "do not pick one.",
                    }
                ],
            }
        client_id = clients[0]
    return acp_oauth.start_login(
        arn.arn, discovery_url=discovery_url, client_id=client_id, scope=args.scope
    )


def cmd_login_status(args: argparse.Namespace) -> dict[str, Any]:
    import acp_oauth

    return acp_oauth.login_status(wait_seconds=args.wait)


def cmd_login_cancel(args: argparse.Namespace) -> dict[str, Any]:
    import acp_oauth

    return acp_oauth.cancel_login()


def cmd_login_sign_out(args: argparse.Namespace) -> dict[str, Any]:
    import acp_oauth

    return acp_oauth.sign_out(args.gateway_arn)


def cmd_describe(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).describe(
        targets=args.target or [],
        actions=args.action or [],
        include_drafts=args.drafts,
        include_policies=args.policies,
    )


def cmd_policies_load(args: argparse.Namespace) -> dict[str, Any]:
    import acp_api
    import acp_common as common

    manager = _manager(args)
    context = manager.get_context()
    engine = context.get("policy_engine") or {}
    engine_id = args.policy_engine_id
    if engine_id is None:
        if engine.get("association") != "linked" or not engine.get("arn"):
            raise common.SkillError(
                "invalid_input",
                "the Gateway has no associated policy engine; ask the developer which engine to "
                "read and pass --policy-engine-id (do not search the account for one)",
                association=engine.get("association"),
            )
        engine_id = str(engine["arn"]).rsplit("/", 1)[-1]
    sess = _session_for(args)
    listed = acp_api.run(
        sess,
        "list_policies",
        {"policy_engine_id": engine_id},
        approve=None,
        state=manager.state,
        context=context,
    )
    policies = listed.get("policies", listed.get("items", []))
    detailed = []
    for summary in policies:
        policy_id = summary.get("policyId")
        if not policy_id:
            continue
        fetched = acp_api.run(
            sess,
            "get_policy",
            {"policy_engine_id": engine_id, "policy_id": policy_id},
            approve=None,
            state=manager.state,
            context=context,
        )
        detailed.append(fetched.get("resource", fetched))
    engine_ref = engine_id if args.policy_engine_id else (engine.get("arn") or engine_id)
    record = manager.set_pre_existing_policies(engine_ref, detailed)
    return {
        "policy_engine": record["policy_engine_arn"],
        "count": len(detailed),
        "policies": detailed,
    }


def cmd_claims_set(args: argparse.Namespace) -> dict[str, Any]:
    # `--names a b`, `--names a,b` and `--names "a, b"` all give ["a", "b"].
    names = [n.strip() for arg in args.names for n in arg.split(",") if n.strip()]
    return _manager(args).set_confirmed_claims(names)


def cmd_draft_put(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common

    statement = common.read_statement_file(args.statement_file) if args.statement_file else None
    if args.statement_file and args.route == "non-translatable":
        raise common.SkillError(
            "invalid_input",
            "a non-translatable draft has no statement; drop --statement-file",
        )
    if statement is None and args.route != "non-translatable":
        raise common.SkillError(
            "invalid_input",
            "--statement-file is required unless --route non-translatable",
        )
    return _manager(args).put_draft(
        args.name,
        statement,
        rule_text=args.rule_text,
        idp_claims=_json_object(args.idp_claims, "--idp-claims"),
        route=args.route,
        reason=args.reason,
        review_required=args.review_required,
    )


def cmd_draft_resolve(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).resolve_review(args.id, args.resolution)


def _check_review(manager: Any, statement: str) -> None:
    import acp_common as common

    blockers = manager.review_blockers(statement)
    if blockers:
        raise common.SkillError(
            "review_required",
            "this statement has open review items that the developer must decide first: "
            + "; ".join(
                f"{b['name']} ({b['draft_id']}): {', '.join(b['review_required'])}"
                for b in blockers
            )
            + ". Ask the developer, update the draft if needed, then run `draft resolve --id <draft-id> "
            '--resolution "<their decision>"`.',
            drafts=blockers,
        )


def _json_object(text: str | None, label: str) -> dict[str, Any] | None:
    import acp_common as common

    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise common.SkillError("invalid_input", f"{label} is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise common.SkillError("invalid_input", f"{label} must be a JSON object")
    return value


def cmd_draft_put_many(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common

    text = common.read_input_file(args.file, input_name="drafts_file")
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise common.SkillError("invalid_input", f"drafts file is not valid JSON: {exc}") from None
    # {"idp_claims": {...}, "drafts": [...]} attaches one IdP claim list to every draft that
    # has none, so the agent writes the list once.
    if isinstance(items, dict):
        if set(items) - {"idp_claims", "drafts"} or not isinstance(items.get("drafts"), list):
            raise common.SkillError(
                "invalid_input",
                'drafts file must be a JSON list, or an object {"idp_claims": {...}, "drafts": [...]}',
            )
        shared = items.get("idp_claims")
        items = [
            (
                {**item, "idp_claims": shared}
                if shared is not None and isinstance(item, dict) and "idp_claims" not in item
                else item
            )
            for item in items["drafts"]
        ]
    return _manager(args).put_drafts(items)


def cmd_draft_export(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).export_drafts(args.output)


def cmd_draft_list(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).list_drafts()


def cmd_draft_show(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).get_draft(args.id)


def cmd_draft_remove(args: argparse.Namespace) -> dict[str, Any]:
    return _manager(args).remove_draft(args.id)


def _statement_from(args: argparse.Namespace) -> tuple[str, str | None]:
    import acp_common as common

    manager = _manager(args)
    if args.draft_id:
        draft = manager.get_translatable_draft(args.draft_id[0])
        return draft["statement"], draft["name"]
    if args.statement_file:
        return common.read_statement_file(args.statement_file), getattr(args, "name", None)
    raise common.SkillError("invalid_input", "pass --draft-id or --statement-file")


def cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    import acp_common as common

    manager = _manager(args)
    if args.approve and not args.on_service:
        raise common.SkillError("invalid_input", "--approve only applies with --on-service")
    ids = list(dict.fromkeys(args.draft_id or []))
    args.draft_id = ids
    if args.all_drafts or len(ids) > 1:
        if args.on_service:
            raise common.SkillError(
                "invalid_input",
                "service checks are one approved call per draft; run "
                "`validate --draft-id <id> --on-service` for each",
            )
        if args.name:
            raise common.SkillError("invalid_input", "--name applies to a single statement")
        return manager.validate_drafts(None if args.all_drafts else ids)
    statement, name = _statement_from(args)
    if not args.on_service:
        if ids:
            return manager.validate_draft(ids[0])
        return manager.validate(statement, name=name or args.name)
    return _validate_on_service(args, manager, statement)


def _validate_on_service(args: argparse.Namespace, manager: Any, statement: str) -> dict[str, Any]:
    import acp_api
    import acp_common as common

    statement = statement.strip() + "\n"
    last = manager.last_validation(statement)
    if last is None:
        raise common.SkillError(
            "not_validated",
            "run `validate` locally on this exact statement first; the service check is offered "
            "only for what local checks could not cover",
        )
    if last["status"] == "rejected":
        raise common.SkillError(
            "not_validated",
            "local validation rejected this statement; fix the findings before a service check",
        )
    result = acp_api.run(
        _session_for(args),
        "validate_on_service",
        {"statement": statement},
        approve=args.approve,
        state=manager.state,
        context=manager.get_context(),
    )
    if args.approve and result.get("service_validation") in ("passed", "rejected"):
        manager.record_service_validation(statement, result)
    return result


POLICY_WRITES = ("create_policy", "update_policy")


def cmd_api(args: argparse.Namespace) -> dict[str, Any]:
    import acp_api
    import acp_common as common
    import acp_validation as validation

    manager = _manager(args)
    params = _load_params(args)
    context = manager.get_context() if manager.has_context() else None
    if args.operation == "validate_on_service":
        raise common.SkillError(
            "invalid_input",
            "use `validate --draft-id <id> --on-service`; it checks the local result first",
        )
    current_statement: str | None = None
    if args.operation in POLICY_WRITES:
        if args.draft_id:
            if "statement" in params:
                raise common.SkillError(
                    "invalid_input", "use --draft-id or params.statement, not both"
                )
            draft = manager.get_translatable_draft(args.draft_id)
            params["statement"] = draft["statement"]
            if args.operation == "create_policy":
                params.setdefault("name", draft["name"])
        raw = params.get("statement")
        statement = raw if isinstance(raw, str) and raw.strip() else None
        has_statement = statement is not None
        if not has_statement and args.operation == "create_policy":
            raise common.SkillError(
                "invalid_input", "create_policy needs --draft-id or params.statement"
            )
        placeholder_ctx = bool(
            ((context or {}).get("cedar_schema") or {}).get("placeholder_gateway_arn")
        )
        if placeholder_ctx or (
            statement is not None and validation.uses_placeholder_gateway(None, statement)
        ):
            raise common.SkillError(
                "placeholder_gateway",
                "this context uses the placeholder Gateway ARN, so the policy cannot be bound to "
                "a real Gateway; prepare the context with the real --gateway-arn, re-validate, "
                "then submit",
            )
        if statement is not None:
            params["statement"] = statement.strip() + "\n"
            _check_review(manager, params["statement"])
            _check_statement_gates(manager, params["statement"])
        elif args.operation == "update_policy" and params.get("enforcement_mode") == "ACTIVE":
            # Switching an existing policy to ACTIVE starts enforcing its stored statement: it
            # must pass the same gates as a submitted one, and the preview shows it.
            current_statement = _stored_statement(args, params)
            _check_review(manager, current_statement)
            _check_statement_gates(manager, current_statement)
    return acp_api.run(
        _session_for(args),
        args.operation,
        params,
        approve=args.approve,
        state=manager.state,
        context=context,
        current_statement=current_statement,
    )


def _stored_statement(args: argparse.Namespace, params: dict[str, Any]) -> str:
    import acp_api
    import acp_common as common

    read = acp_api.run(
        _session_for(args),
        "get_policy",
        {
            "policy_engine_id": params.get("policy_engine_id"),
            "policy_id": params.get("policy_id"),
        },
        state=_manager(args).state,
    )
    definition = (read.get("resource") or {}).get("definition") or {}
    for key in ("policy", "cedar"):
        text = (definition.get(key) or {}).get("statement")
        if isinstance(text, str) and text.strip():
            return text.strip() + "\n"
    raise common.SkillError(
        "not_validated",
        "the policy has no statement this skill can check, so it is not switched to ACTIVE; "
        "submit the statement with update_policy (validated first) instead",
    )


def _check_statement_gates(manager: Any, statement: str) -> None:
    import acp_common as common

    last = manager.last_validation(statement)
    if last is None:
        raise common.SkillError(
            "not_validated",
            "run `validate` on this exact statement against the current context before "
            "submitting it",
        )
    if (last.get("service") or {}).get("service_validation") == "rejected":
        raise common.SkillError(
            "service_rejected",
            "the service rejected this statement; revise it and validate again",
        )
    if last["status"] == "rejected":
        raise common.SkillError(
            "not_validated",
            "local validation rejected this statement; fix the findings and validate again",
        )


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentcore_policy.py",
        description="Author, validate and submit Amazon Bedrock AgentCore Policy statements.",
    )
    parser.add_argument("--state-dir", help="session state directory (default ./.agentcore-policy)")
    parser.add_argument(
        "--region",
        help="AWS Region (default: profile/AWS_REGION, or the Gateway ARN's)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "doctor", help="check Python, packages and the optional dogwood CLI"
    ).set_defaults(func=cmd_doctor)
    sub.add_parser("verify-aws", help="check AWS credentials (STS)").set_defaults(
        func=cmd_verify_aws
    )

    prepare = sub.add_parser("prepare", help="build or update the policy context")
    prepare_sub = prepare.add_subparsers(dest="route", required=True)
    gw = prepare_sub.add_parser("gateway", help="from a Gateway ARN")
    gw.add_argument("--gateway-arn", required=True)
    gw.add_argument("--client-id", help="OAuth client chosen by the developer")
    gw.add_argument(
        "--login-failed",
        action="store_true",
        help="sign-in failed or was cancelled: use control-plane declarations only",
    )
    gw.set_defaults(func=cmd_prepare_gateway)
    files = prepare_sub.add_parser("files", help="from local schema files (no AWS calls)")
    files.add_argument(
        "--file",
        action="append",
        required=True,
        metavar="PATH[:PROTOCOL[:TARGET]]",
        help="schema file, its protocol (MCP|HTTP) and target name; repeatable",
    )
    files.add_argument(
        "--auth-type", choices=["AWS_IAM", "CUSTOM_JWT", "NONE", "AUTHENTICATE_ONLY"]
    )
    files.add_argument("--gateway-arn", help="optional; a placeholder ARN is used without it")
    files.set_defaults(func=cmd_prepare_files)

    login = sub.add_parser("login", help="OAuth sign-in for CUSTOM_JWT Gateways")
    login_sub = login.add_subparsers(dest="login_command", required=True)
    start = login_sub.add_parser("start")
    start.add_argument("--gateway-arn", required=True)
    start.add_argument(
        "--client-id", help="one of the Gateway's allowed clients, chosen by the developer"
    )
    start.add_argument("--scope")
    start.set_defaults(func=cmd_login_start)
    status = login_sub.add_parser("status")
    status.add_argument("--wait", type=int, default=0, help="seconds to wait for completion")
    status.set_defaults(func=cmd_login_status)
    login_sub.add_parser("cancel").set_defaults(func=cmd_login_cancel)
    sign_out = login_sub.add_parser("sign-out")
    sign_out.add_argument("--gateway-arn")
    sign_out.set_defaults(func=cmd_login_sign_out)

    describe = sub.add_parser(
        "describe", help="schemas for named targets/actions, drafts, policies"
    )
    describe.add_argument("--target", action="append")
    describe.add_argument("--action", action="append", metavar="TARGET___ACTION")
    describe.add_argument("--drafts", action="store_true")
    describe.add_argument("--policies", action="store_true")
    describe.set_defaults(func=cmd_describe)

    policies = sub.add_parser("policies", help="pre-existing policies (developer consent required)")
    policies_sub = policies.add_subparsers(dest="policies_command", required=True)
    load = policies_sub.add_parser("load")
    load.add_argument("--policy-engine-id", help="only when the developer chose an engine")
    load.set_defaults(func=cmd_policies_load)

    claims = sub.add_parser(
        "claims", help="exact token claim names the developer gave or confirmed (CUSTOM_JWT)"
    )
    claims_sub = claims.add_subparsers(dest="claims_command", required=True)
    claims_set = claims_sub.add_parser("set")
    claims_set.add_argument(
        "--names",
        required=True,
        nargs="+",
        metavar="NAME",
        help="claim names exactly as in the token, separated by spaces or commas",
    )
    claims_set.set_defaults(func=cmd_claims_set)

    draft = sub.add_parser("draft", help="store drafts for validation and submission")
    draft_sub = draft.add_subparsers(dest="draft_command", required=True)
    put = draft_sub.add_parser("put")
    put.add_argument("--name", required=True)
    put.add_argument("--statement-file", help="required unless --route non-translatable")
    put.add_argument("--rule-text", help="the natural-language rule this draft implements")
    put.add_argument("--idp-claims", metavar="JSON", help="JSON object of IdP claims the rule uses")
    put.add_argument(
        "--route", choices=["translatable", "non-translatable"], default="translatable"
    )
    put.add_argument("--reason", help="why the rule cannot be expressed (non-translatable only)")
    put.add_argument(
        "--review-required",
        action="append",
        metavar="TEXT",
        help="a point the developer must decide before submission (repeatable); kept until `draft resolve`",
    )
    put.set_defaults(func=cmd_draft_put)
    resolve = draft_sub.add_parser(
        "resolve", help="close a draft's review items with the developer's decision"
    )
    resolve.add_argument("--id", required=True)
    resolve.add_argument(
        "--resolution", required=True, help="the developer's decision, in their words"
    )
    resolve.set_defaults(func=cmd_draft_resolve)
    put_many = draft_sub.add_parser(
        "put-many", help="store many drafts from a JSON list, all or none"
    )
    put_many.add_argument(
        "--file", required=True, help="JSON list of {name, statement?, rule_text?, ...}"
    )
    put_many.set_defaults(func=cmd_draft_put_many)
    export = draft_sub.add_parser(
        "export", help="write all drafts and their verdicts to a JSON file"
    )
    export.add_argument("--output", required=True)
    export.set_defaults(func=cmd_draft_export)
    draft_sub.add_parser("list").set_defaults(func=cmd_draft_list)
    show = draft_sub.add_parser("show")
    show.add_argument("--id", required=True)
    show.set_defaults(func=cmd_draft_show)
    remove = draft_sub.add_parser("remove")
    remove.add_argument("--id", required=True)
    remove.set_defaults(func=cmd_draft_remove)

    validate = sub.add_parser("validate", help="local syntax, schema and API-limit checks")
    source = validate.add_mutually_exclusive_group(required=True)
    source.add_argument("--draft-id", action="append", help="repeat to validate several drafts")
    source.add_argument("--all-drafts", action="store_true", help="validate every stored draft")
    source.add_argument("--statement-file")
    validate.add_argument("--name", help="policy name to check against API limits")
    validate.add_argument(
        "--on-service",
        action="store_true",
        help="Gateway contexts only: validate on the service with a temporary policy engine "
        "(preview first, then --approve)",
    )
    validate.add_argument(
        "--approve",
        metavar="APPROVAL_TOKEN",
        help="token from the --on-service preview",
    )
    validate.set_defaults(func=cmd_validate)

    api = sub.add_parser("api", help="AgentCore control-plane reads and approved writes")
    api.add_argument("operation")
    api.add_argument("--params", help="JSON object of snake_case parameters")
    api.add_argument("--params-file")
    api.add_argument("--draft-id", help="create_policy/update_policy: use this draft's statement")
    api.add_argument("--approve", metavar="APPROVAL_TOKEN", help="token from the approved preview")
    api.set_defaults(func=cmd_api)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.version_info[:2] < MIN_PYTHON:
        _emit(
            {
                "error": {
                    "kind": "missing_dependency",
                    "message": "Python 3.10 or newer is required",
                }
            },
            stream=sys.stderr,
        )
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args = build_parser().parse_args(argv)
    import acp_common as common

    try:
        _emit(args.func(args))
        return 0
    except common.SkillError as exc:
        _emit(exc.to_dict(), stream=sys.stderr)
        return 2
    except KeyboardInterrupt:
        _emit(
            {"error": {"kind": "interrupted", "message": "interrupted"}},
            stream=sys.stderr,
        )
        return 130
    except Exception as exc:  # last resort: no traceback, no response bodies
        _emit(
            {
                "error": {
                    "kind": "internal",
                    "message": f"unexpected {type(exc).__name__}",
                }
            },
            stream=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
