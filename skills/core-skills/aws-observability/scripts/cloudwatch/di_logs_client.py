"""The CloudWatch Logs boto3 client seam for the dynamic-instrumentation snapshot tools.

WHY THIS EXISTS (import-cycle removal)
  This module is the LEAF that owns the lazily-built CloudWatch Logs client, exposed as the
  module attribute ``logs_client``. Previously the seam lived in ``di_snapshots`` (the CLI entry
  point), so the snapshot query layer reached it via ``di_snapshot_tools -> di_snapshot_queries
  -> di_snapshots`` — an import cycle back into the entry script. A client seam is a leaf concern
  (it depends only on ``di_session``/``di_region``), so it belongs in its own leaf module. With
  it here, ``di_snapshot_queries`` imports DOWN into this module (as ``aws_clients``) and nothing
  imports back into ``di_snapshots``: the cycle is gone. Mirrors ``di_app_signals_client``.

  ``boto3``/``botocore`` are imported lazily (inside ``di_session.build_client``), so importing
  this module never requires boto3.

SECURITY
  Attribute access on ``logs_client`` is restricted to the allowlisted CloudWatch Logs
  operations (``_ALLOWED_LOGS_OPERATIONS``) and each is returned by LITERAL attribute access on
  the boto3 client — never ``getattr(client, name)`` — so the proxy cannot be turned into an
  arbitrary-Logs-API dispatcher (ExecutableCodeSecurityReview Guideline 1). Mirrors the
  allowlist + literal-dispatch pattern in ``di_gateway``.
"""

_logs_client = None


def _build_logs_client():
    """Build the public CloudWatch Logs client via the shared di_session.build_client.

    Region/profile policy lives in di_session + di_region: --region (set into AWS_REGION by
    the entry script's main) > AWS_REGION > AWS_DEFAULT_REGION > us-east-1; AWS_PROFILE for
    credentials only.
    """
    from di_session import build_client

    return build_client("logs")


# Allowlist of CloudWatch Logs client methods the snapshot ops are permitted to call. The
# vendored di_snapshot_queries only uses start_query + get_query_results; the proxy below
# rejects any attribute outside this set before delegating to the real boto3 client so the
# proxy cannot be turned into an arbitrary-method dispatcher by any (future) caller. Mirrors
# the _ALLOWED_OPERATIONS pattern in di_gateway.py.
_ALLOWED_LOGS_OPERATIONS = frozenset({"start_query", "get_query_results"})


class _LazyLogsClient:
    """Module attribute proxy so the vendored `di_snapshot_queries` can do
    `aws_clients.logs_client` and get a lazily-built client (no client at import time).

    Attribute access is restricted to the allowlisted CloudWatch Logs operations
    (`_ALLOWED_LOGS_OPERATIONS`); any other name raises AttributeError before a client is
    built or the real attribute is reached, so the proxy cannot dispatch arbitrary Logs APIs.

    The two allowlisted methods are returned by LITERAL attribute access on the boto3 client
    (`client.start_query` / `client.get_query_results`) rather than `getattr(client, name)`,
    so there is no string-driven dispatch even though the underlying boto3 methods are
    generated dynamically (and thus cannot be bound as a static dict at import time)."""

    def __getattr__(self, name):
        if name not in _ALLOWED_LOGS_OPERATIONS:
            raise AttributeError(
                f"Disallowed CloudWatch Logs operation: {name!r} "
                f"(allowed: {sorted(_ALLOWED_LOGS_OPERATIONS)})"
            )
        global _logs_client
        if _logs_client is None:
            _logs_client = _build_logs_client()
        # Literal attribute access per allowlisted op — no getattr(client, name) dispatch.
        # _ALLOWED_LOGS_OPERATIONS above already rejected anything outside these two, so the
        # final branch is unreachable; it keeps the allowlist and this dispatch in lockstep.
        if name == "start_query":
            return _logs_client.start_query
        if name == "get_query_results":
            return _logs_client.get_query_results
        raise AttributeError(  # unreachable: allowlist and branches are kept in sync by tests
            f"Disallowed CloudWatch Logs operation: {name!r} "
            f"(allowed: {sorted(_ALLOWED_LOGS_OPERATIONS)})"
        )


# The vendored di_snapshot_queries imports this module as `aws_clients` and reads
# `aws_clients.logs_client`. Expose it as a lazy proxy.
logs_client = _LazyLogsClient()
