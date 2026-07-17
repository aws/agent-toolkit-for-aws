#!/usr/bin/env python3
"""Host command for the dynamic-instrumentation snapshot retrieval operations.

Fetches/searches the snapshot data a breakpoint captured. Snapshot data is read from public
CloudWatch Logs Insights (`/aws/service-events/{service}`) via boto3 `logs`; no bundled model
is needed. Self-contained — requires only `python3` + `boto3`.

ARCHITECTURE
  - The two operation implementations (get_sample_snapshot_for_breakpoint,
    search_snapshots_for_status_event) plus their parsing/rendering/query layers live in the
    flat `di_snapshot_*.py` sibling modules. They carry the OTLP-aware Logs-Insights filter
    escaping and the per-attribute field documentation the agent relies on.
  - The public CloudWatch Logs client seam lives in the leaf module `di_logs_client`
    (`logs_client`), which `di_snapshot_queries` imports directly as `aws_clients`. Keeping it
    out of this entry script is what breaks the old `di_snapshot_tools -> di_snapshot_queries
    -> di_snapshots` import cycle.

SENSITIVE DATA:
  Snapshots can capture PII/secrets from live request args. The operations return JSON text;
  they do NOT write files. When `--out FILE` is used for a large result, the file is written
  with owner-only (0600) permissions. The skill body (SKILL.md) instructs the agent to parse
  saved output with jq/python and not to retain it. Real captured snapshots are never committed
  as test fixtures.

USAGE
    python3 scripts/di_snapshots.py --print-contract
    python3 scripts/di_snapshots.py sample --json-file args.json
    python3 scripts/di_snapshots.py sample --json -      # read the JSON object from stdin
    python3 scripts/di_snapshots.py search --json-file args.json --out /tmp/snaps.json
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ── the 2-op contract: op name -> (vendored module, function) ───────────────────────────
_OPS = {
    "sample": ("di_snapshot_tools", "get_sample_snapshot_for_breakpoint"),
    "search": ("di_snapshot_tools", "search_snapshots_for_status_event"),
}


def _dispatch_table() -> Dict[str, Any]:
    """Build the op -> function dispatch table by binding each function reference directly.

    NO dynamic dispatch: every function is named as a literal attribute on the freshly
    imported module (``di_snapshot_tools.get_sample_snapshot_for_breakpoint``), never resolved
    from a string via ``getattr``/``__import__``. The import stays inside the function because
    ``di_snapshot_tools`` (via ``di_snapshot_queries``) imports ``botocore`` at module top;
    keeping it lazy here lets a bare ``import di_snapshots`` stay free of a hard boto3
    dependency (the build env omits boto3 and must still import this module). Note this does
    NOT make ``--print-contract`` boto3-free: calling ``_resolve_tool`` runs this function and
    triggers the lazy ``botocore`` import. (The old import cycle that also required this is
    gone — the logs-client seam moved to ``di_logs_client``.)

    ``_resolve_tool`` and the ``test_dispatch_table_keys_match_ops`` sync guard both key off
    this table, so an op added to ``_OPS`` without a matching binding here fails loudly rather
    than silently dropping from the contract.
    """
    import di_snapshot_tools

    return {
        "sample": di_snapshot_tools.get_sample_snapshot_for_breakpoint,
        "search": di_snapshot_tools.search_snapshots_for_status_event,
    }


def _resolve_tool(op: str):
    """Return the snapshot tool function for ``op`` from the explicit dispatch table.

    Raises ``KeyError(op)`` for an unknown op (the table is the source of truth for which
    ops are callable; it is kept in sync with ``_OPS`` by the dispatch sync-guard test).
    """
    return _dispatch_table()[op]


# Semantic hints layered onto the inspected signature in the emitted contract. Notably the
# service key matches di_instrumentation.py (both use `service`), so an args object can be
# carried between the two scripts without a key rename.
_ARG_HINTS = {
    "service": {
        "note": "service identifier; di_instrumentation.py uses the same key `service`",
    },
    "custom_filters": {
        "type": "array of strings",
        "note": (
            "JSON array of raw Logs Insights filter fragments, appended with `and`, "
            'e.g. ["@message like /ORD-123/"]. A single bare string is also accepted '
            "and treated as a one-element list."
        ),
    },
    "start_time": {
        "note": (
            "optional ISO 8601 lower bound; pass with end_time to override the "
            "status_timestamp-anchored window and sweep a wider span (both or neither)"
        ),
    },
    "end_time": {
        "note": "optional ISO 8601 upper bound; see start_time (both or neither)",
    },
}


# The snapshot tools signal failure two ways, neither of which is an "ERROR:"-PREFIXED string
# for the dominant (AWS-side) case:
#   1. Deterministic INPUT failures (bad location_hash / timestamp / limit / unbalanced
#      custom_filters) return a bare "ERROR: ..." string.
#   2. AWS-QUERY failures (log group missing, throttle, polling timeout, Failed/Cancelled)
#      return a JSON string whose inner `status` field carries the failure — the string starts
#      with "{", so a prefix check never catches it. _execute_cloudwatch_query emits status in
#      {Error, Polling Timeout, Failed, Cancelled}; the renderers map those to an inner
#      "status" of "ERROR"/"TIMEOUT" (or pass the raw status through). Only Complete/SUCCESS and
#      an empty "no snapshots found" result are genuine successes.
# A CLI/CI caller must get a nonzero exit on either failure, so classify structurally.
_QUERY_FAILURE_STATUSES = {
    "ERROR",
    "TIMEOUT",
    "POLLING TIMEOUT",
    "FAILED",
    "CANCELLED",
}


def _is_failure(result: object) -> bool:
    if not isinstance(result, str):
        return False
    if result.lstrip().startswith("ERROR"):
        return True  # deterministic input failure
    # AWS-query failure: inner status field in the returned JSON.
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return False
    if isinstance(data, dict):
        status = str(data.get("status", "")).strip().upper()
        return status in _QUERY_FAILURE_STATUSES
    return False


def _write_out(path: str, text: str) -> None:
    """Write result text to a file with owner-only (0600) permissions.

    SECURITY: snapshots may contain PII/secrets; prefer an --out path on an encrypted volume
    (see snapshot-parsing.md). The on-disk copy must be owner-only and must not be
    redirected/exposed through a pre-planted path:
      - O_NOFOLLOW: refuse to follow a symlink at `path` (an attacker-planted symlink in a
        shared dir would otherwise leak the snapshot into / clobber the link target).
      - O_EXCL semantics are too strict for a re-runnable CLI (would fail on a stale file), so
        we instead fchmod the fd to 0600 explicitly AFTER open — this restricts both freshly
        created files (regardless of umask) AND a pre-existing file whose mode was looser
        (O_CREAT's mode arg is ignored when the file already exists).
    """
    # getattr here is a LITERAL capability probe (hardcoded name + 0 default), NOT dynamic
    # dispatch: O_NOFOLLOW is absent on some platforms, so we read the constant if present and
    # fall back to 0 (no-op flag) otherwise. No string-driven attribute/function dispatch.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0600 even if the file pre-existed at 0644
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _print_contract() -> int:
    import inspect

    contract: Dict[str, Any] = {
        "surface": "public CloudWatch Logs Insights (/aws/service-events/{service})",
        "encoding": "python3 scripts/di_snapshots.py <op> --json '{<args>}' [--out FILE]",
        "region": (
            "pass --region, or set AWS_REGION/AWS_DEFAULT_REGION (default us-east-1); "
            "use the same region the breakpoint was created in"
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

    Preferring a file or stdin keeps caller/source-derived values off the shell command line.
    `ap.error` exits 2 on any malformed input.
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
        prog="di_snapshots.py",
        description="Host command for dynamic-instrumentation snapshot retrieval.",
    )
    ap.add_argument("op", nargs="?", choices=sorted(_OPS), help="snapshot operation")
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
        "--out",
        help="write the result to FILE (0600 perms) instead of stdout — for large results "
        "the agent will parse with jq/python (see SKILL.md). Snapshots may contain PII.",
    )
    ap.add_argument(
        "--region",
        help="AWS region to read snapshots from. Precedence: --region > AWS_REGION > "
        "AWS_DEFAULT_REGION > us-east-1. Use the same region the breakpoint was created in. "
        "AWS_PROFILE is used for credentials only; the profile's region is ignored.",
    )
    ap.add_argument(
        "--profile",
        help="AWS named profile for credentials (sets AWS_PROFILE for this call). If omitted, "
        "the ambient default credential chain is used (env vars, shared profile, or IAM "
        "role). Use the same account the breakpoint was created in. Prefer IAM roles or SSO "
        "session credentials over long-lived access keys for these live-service operations.",
    )
    ap.add_argument(
        "--print-contract",
        action="store_true",
        help="print the canonical op + arg schema and exit",
    )
    args = ap.parse_args(argv)

    if args.print_contract:
        return _print_contract()
    if not args.op:
        ap.error("an op is required (or use --print-contract)")
    # The --region flag is a thin front-end over the env-driven logs client: set AWS_REGION
    # so _build_logs_client()'s build_client() picks it up.
    if args.region:
        os.environ["AWS_REGION"] = args.region
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
    payload = _read_payload(ap, args.json_payload, args.json_file)

    fn = _resolve_tool(args.op)
    try:
        result = fn(**payload)
    except TypeError as exc:
        print(f"ERROR: invalid arguments for op '{args.op}': {exc}", file=sys.stderr)
        return 2

    if args.out:
        _write_out(args.out, result)
        print(f"wrote result to {args.out} (0600)")
    else:
        print(result)
    return 1 if _is_failure(result) else 0


if __name__ == "__main__":
    raise SystemExit(main())
