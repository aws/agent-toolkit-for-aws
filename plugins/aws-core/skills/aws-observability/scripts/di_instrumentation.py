#!/usr/bin/env python3
"""Host command for the dynamic-instrumentation instrumentation-config operations.

Creates/lists/gets/deletes breakpoints and checks their status against the
`application-signals` instrumentation API, using only `python3` + `boto3` — self-contained,
no external service required. If no interpreter is available the calling skill treats the
commands as display-only.

The instrumentation operations ship in the public AWS SDK as of **boto3/botocore 1.43.35**, so
this command builds an ordinary `application-signals` client from the ambient boto3 install — no
bundled service model and no data-loader manipulation. Older SDKs lack these operations; the
client builder fails fast with an upgrade message rather than falling through to a confusing
``AttributeError`` deep inside an operation.

ARCHITECTURE
  - The 8 operation implementations (create/list/get/delete/batch-delete-by-scope/
    batch-delete-by-arns/get-status/check-status) live in the flat `di_*.py` sibling
    modules. They carry the validation, location/capture parsing, and token-efficient
    rendering the agent relies on — this is the "ergonomic surface", not a thin boto3
    passthrough.
  - The application-signals client seam lives in the leaf module `di_app_signals_client`
    (`get_application_signals_client()`), which `di_gateway` imports directly. Keeping it out
    of this entry script is what breaks the old `di_crud_tools/di_status_tools -> di_gateway ->
    di_instrumentation` import cycle. The operation modules are still imported LAZILY (inside
    `_dispatch_table`) for a separate reason: they import `botocore` at module top, so a lazy
    import keeps a bare `import di_instrumentation` free of a hard boto3 dependency (the build
    env omits boto3 and must still be able to import this module). `--print-contract` itself is
    NOT boto3-free: it resolves the op functions to inspect their signatures, which triggers
    the lazy import of the op modules — and hence `botocore` — via `_resolve_tool`.

LOAD-BEARING DETAILS (keep exactly)
  - Region resolves from --region > AWS_REGION > AWS_DEFAULT_REGION > us-east-1, at CALL
    TIME, and the profile region is deliberately ignored. AWS_PROFILE is honored for
    CREDENTIALS only.

SECURITY
  - Credentials are inherited from the ambient boto3 chain and are never logged, echoed, or
    written. Pass operation arguments as a JSON object via `--json-file PATH` or `--json -`
    (stdin) so caller-supplied values never transit the shell command line; `--json '<text>'`
    is also accepted for short, trusted payloads.
  - Prefer IAM roles (instance profile, ECS task role, or SSO/STS session credentials) over
    long-lived IAM user access keys — these operations modify live services.

USAGE
    python3 scripts/di_instrumentation.py --print-contract
    python3 scripts/di_instrumentation.py <op> --json-file args.json
    python3 scripts/di_instrumentation.py <op> --json -     # read the JSON object from stdin
    python3 scripts/di_instrumentation.py <op> --json '{"...": ...}'   # inline (trusted only)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# scripts/ is auto-added to sys.path[0] when this file is run directly, so the flat
# `di_*.py` siblings import by bare name. Add it explicitly too, so the module also works
# when imported (e.g. by a test) rather than executed.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# The application-signals client seam now lives in the leaf module di_app_signals_client (see its
# WHY THIS EXISTS note); di_gateway imports it directly from there. Moving the seam out of this
# entry script is what breaks the old di_gateway -> di_instrumentation cycle. We import only the
# API-version constant the contract reports; the module is boto3-free to import, so this does not
# pull botocore into a bare `import di_instrumentation`.
from di_app_signals_client import APPLICATION_SIGNALS_API_VERSION  # noqa: E402

# ── the 8-op contract: op name -> (vendored module, function) ────────────────────────────
# Op names mirror the agent-facing TOOL names (crud_tools/status_tools), not the boto3
# method names. Re-verified against registration.py.
_OPS = {
    "create": ("di_crud_tools", "create_instrumentation"),
    "list": ("di_crud_tools", "list_instrumentations"),
    "get": ("di_crud_tools", "get_instrumentation"),
    "delete": ("di_crud_tools", "delete_instrumentation"),
    "batch-delete-by-scope": ("di_crud_tools", "batch_delete_instrumentations_by_scope"),
    "batch-delete-by-arns": ("di_crud_tools", "batch_delete_instrumentations_by_arns"),
    "get-status": ("di_status_tools", "get_instrumentation_configuration_status"),
    "check-status": ("di_status_tools", "check_instrumentation_status"),
}


def _dispatch_table() -> Dict[str, Any]:
    """Build the op -> function dispatch table by binding each function reference directly.

    NO dynamic dispatch: every function is named as a literal attribute on its freshly
    imported module (``di_crud_tools.create_instrumentation``), never resolved from a string
    via ``getattr``/``__import__``. The imports stay inside the function because
    ``di_crud_tools``/``di_status_tools`` import ``botocore`` at module top; keeping their
    import lazy here lets a bare ``import di_instrumentation`` stay free of a hard boto3
    dependency (the build env omits boto3 and must still import this module). Note this does
    NOT make ``--print-contract`` boto3-free: calling ``_resolve_tool`` runs this function and
    triggers the lazy ``botocore`` import. (The old import cycle that also required this is
    gone — the client seam moved to ``di_app_signals_client``.)

    ``_resolve_tool`` and the ``test_dispatch_table_keys_match_ops`` sync guard both key off
    this table, so an op added to ``_OPS`` without a matching binding here fails loudly rather
    than silently dropping from the contract.
    """
    import di_crud_tools
    import di_status_tools

    return {
        "create": di_crud_tools.create_instrumentation,
        "list": di_crud_tools.list_instrumentations,
        "get": di_crud_tools.get_instrumentation,
        "delete": di_crud_tools.delete_instrumentation,
        "batch-delete-by-scope": di_crud_tools.batch_delete_instrumentations_by_scope,
        "batch-delete-by-arns": di_crud_tools.batch_delete_instrumentations_by_arns,
        "get-status": di_status_tools.get_instrumentation_configuration_status,
        "check-status": di_status_tools.check_instrumentation_status,
    }


def _resolve_tool(op: str):
    """Return the vendored tool function for ``op`` from the explicit dispatch table.

    Raises ``KeyError(op)`` for an unknown op (the table is the source of truth for which
    ops are callable; it is kept in sync with ``_OPS`` by the dispatch sync-guard test).
    """
    return _dispatch_table()[op]


# Semantic hints layered onto the inspected signature in the emitted contract. The signature
# gives the arg SHAPE (name/required/default); these add the meaning the agent cannot infer
# from a bare name — notably that `instrumentation_type` is required on EVERY op (not just
# create) and must match how the breakpoint was created.
_ARG_HINTS = {
    "instrumentation_type": {
        "enum": ["BREAKPOINT", "PROBE"],
        "note": "required on every op; must match how the breakpoint was created",
    },
    "service": {
        "note": "service identifier; di_snapshots.py uses the same key `service`",
    },
}


def _print_contract() -> int:
    """Emit the canonical op + arg schema (argument shapes only). SKILL.md and
    references/ carry the per-operation semantics; this is the argument shape, not the rules.
    Derived from the operation signatures."""
    import inspect

    contract: Dict[str, Any] = {
        "api_version": APPLICATION_SIGNALS_API_VERSION,
        "encoding": "python3 scripts/di_instrumentation.py <op> --json-file args.json",
        "region": (
            "pass --region, or set AWS_REGION/AWS_DEFAULT_REGION (default us-east-1); "
            "use the region your instrumented service runs in"
        ),
        "ops": {},
    }
    for op in _OPS:
        fn = _resolve_tool(op)
        sig = inspect.signature(fn)
        args: Dict[str, Any] = {}
        for name, p in sig.parameters.items():
            required = p.default is inspect.Parameter.empty
            args[name] = {"required": required}
            if not required and p.default is not None:
                args[name]["default"] = p.default
            if name in _ARG_HINTS:
                args[name].update(_ARG_HINTS[name])
        contract["ops"][op] = {"args": args}
    print(json.dumps(contract, indent=2, default=str))
    return 0


def _read_payload(ap, json_text: str | None, json_file: str | None) -> dict:
    """Resolve the op's JSON-object argument from --json-file, --json - (stdin), or --json.

    Preferring a file or stdin keeps caller/source-derived values off the shell command line
    (no quoting/injection surface). `ap.error` exits 2 on any malformed input.
    """
    sources = [s for s in (json_text is not None, json_file is not None) if s]
    if len(sources) > 1:
        ap.error("pass the arguments via exactly one of --json or --json-file")
    if json_file is not None:
        try:
            raw = sys.stdin.read() if json_file == "-" else Path(json_file).read_text("utf-8")
        except OSError as exc:
            ap.error(f"--json-file could not be read: {exc}")
    elif json_text is not None:
        raw = sys.stdin.read() if json_text == "-" else json_text
    else:
        ap.error(
            "the op's arguments are required (use --json-file PATH, --json -, or --json '{...}')"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        ap.error(f"arguments are not valid JSON: {exc}")
    if not isinstance(payload, dict):
        ap.error("arguments must be a JSON object of the op's parameters")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="di_instrumentation.py",
        description="Host command for dynamic-instrumentation "
        "instrumentation-config operations.",
    )
    ap.add_argument("op", nargs="?", choices=sorted(_OPS), help="instrumentation operation")
    ap.add_argument(
        "--json",
        dest="json_payload",
        help="JSON object of the op's arguments (use '-' for stdin; prefer --json-file)",
    )
    ap.add_argument(
        "--json-file",
        dest="json_file",
        help="read the op's JSON arguments from PATH (or '-' for stdin) — keeps values off "
        "the shell command line",
    )
    ap.add_argument(
        "--region",
        help="AWS region for the operation. Precedence: --region > AWS_REGION > "
        "AWS_DEFAULT_REGION > us-east-1. AWS_PROFILE is used for credentials only; the "
        "profile's region is ignored. Pass the region your instrumented service runs in.",
    )
    ap.add_argument(
        "--profile",
        help="AWS named profile for credentials (sets AWS_PROFILE for this call). If omitted, "
        "the ambient default credential chain is used (env vars, shared profile, or IAM "
        "role). Selects the account/identity; the profile's region is ignored (use --region). "
        "Prefer IAM roles or SSO session credentials over long-lived access keys for these "
        "live-service operations.",
    )
    ap.add_argument(
        "--print-contract",
        action="store_true",
        help="print the canonical op + arg schema (single source of truth) and exit",
    )
    args = ap.parse_args(argv)

    if args.print_contract:
        return _print_contract()
    if not args.op:
        ap.error("an op is required (or use --print-contract)")
    # A --region flag is a thin front-end over the env-driven client builder: set AWS_REGION
    # so get_application_signals_client()'s build_client() picks it up without threading
    # region through every op signature and the gateway.
    if args.region:
        os.environ["AWS_REGION"] = args.region
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
    payload = _read_payload(ap, args.json_payload, args.json_file)

    fn = _resolve_tool(args.op)
    try:
        result = fn(**payload)
    except TypeError as exc:
        # Bad/unknown argument names for the op — deterministic input error.
        print(f"ERROR: invalid arguments for op '{args.op}': {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        # The only deliberate RuntimeError in the op path is the SDK-too-old guard in
        # get_application_signals_client(); surface its clean upgrade message instead of a
        # bare traceback (the di_* op modules never raise — they return strings).
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(result.text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
