"""Gateway to the AWS application-signals API.

The single seam where dynamic-instrumentation tools touch botocore. Each
operation here issues one boto3 call, wraps any raised exception in a
``GatewayError``, and lets the caller render the failure through
``render_error``. Tool functions never import ``botocore.exceptions`` — that
contract belongs to this module.
"""

from typing import Any, Dict, Mapping, Optional, Sequence

from botocore.exceptions import BotoCoreError, ClientError
from di_app_signals_client import get_application_signals_client
from di_error_translation import render_client_error, translate_aws_error


class GatewayError(Exception):
    """Wraps any exception raised by an application-signals call.

    The original exception is preserved on ``original_exc`` so callers can
    pass the gateway error through ``render_error`` without losing the
    botocore-specific data ``render_client_error`` needs.
    """

    def __init__(self, original_exc: BaseException):
        """Wrap ``original_exc``, preserving it for later rendering."""
        super().__init__(str(original_exc))
        self.original_exc = original_exc


# The full set of application-signals client methods these tools are allowed to call. The
# wrapper functions below pass only these hardcoded names, but ``_call`` validates against
# this frozen set before dispatch so the seam cannot be turned into an arbitrary-method
# dispatcher by any (future) caller. ``_bind_method`` then selects the bound method by LITERAL
# attribute access (one ``if`` per op) — never ``getattr(client, name)`` — so there is no
# string-driven dispatch. The two are kept in lockstep by the gateway sync-guard test.
_ALLOWED_OPERATIONS = frozenset(
    {
        "create_instrumentation_configuration",
        "list_instrumentation_configurations",
        "get_instrumentation_configuration",
        "delete_instrumentation_configuration",
        "batch_delete_instrumentation_configurations",
        "get_instrumentation_configuration_status",
    }
)


def _bind_method(client: Any, method_name: str):
    """Return the bound boto3 client method for ``method_name`` via literal attribute access.

    boto3 client methods are generated dynamically per client instance, so they cannot be
    bound as a static dict at import time the way our own module functions can. Instead each
    allowlisted op is reached by a hardcoded attribute name (``client.create_instrumentation_
    configuration`` etc.), never ``getattr(client, method_name)``. ``method_name`` has already
    been checked against ``_ALLOWED_OPERATIONS`` by ``_call``, so the final ``raise`` is
    unreachable; it keeps the allowlist and these branches in sync (asserted by the tests).
    """
    if method_name == "create_instrumentation_configuration":
        return client.create_instrumentation_configuration
    if method_name == "list_instrumentation_configurations":
        return client.list_instrumentation_configurations
    if method_name == "get_instrumentation_configuration":
        return client.get_instrumentation_configuration
    if method_name == "delete_instrumentation_configuration":
        return client.delete_instrumentation_configuration
    if method_name == "batch_delete_instrumentation_configurations":
        return client.batch_delete_instrumentation_configurations
    if method_name == "get_instrumentation_configuration_status":
        return client.get_instrumentation_configuration_status
    raise ValueError(f"Disallowed application-signals operation: {method_name!r}")


def _call(method_name: str, **kwargs: Any) -> Dict[str, Any]:
    if method_name not in _ALLOWED_OPERATIONS:
        raise ValueError(f"Disallowed application-signals operation: {method_name!r}")
    client = get_application_signals_client()
    method = _bind_method(client, method_name)
    try:
        return method(**kwargs)
    except (BotoCoreError, ClientError) as exc:
        # Narrow on purpose: these two cover the full botocore exception
        # surface (``ClientError`` for service-side errors, ``BotoCoreError``
        # for credentials/connection/timeout failures). Programming errors
        # (``AttributeError`` from a typo, ``TypeError`` from a bad kwarg)
        # propagate unwrapped so they surface as themselves in tracebacks
        # instead of masquerading as AWS failures.
        raise GatewayError(exc) from exc


def create_instrumentation_configuration(**kwargs: Any) -> Dict[str, Any]:
    """Call ``CreateInstrumentationConfiguration`` through the gateway."""
    return _call("create_instrumentation_configuration", **kwargs)


def list_instrumentation_configurations(**kwargs: Any) -> Dict[str, Any]:
    """Call ``ListInstrumentationConfigurations`` through the gateway."""
    return _call("list_instrumentation_configurations", **kwargs)


def get_instrumentation_configuration(**kwargs: Any) -> Dict[str, Any]:
    """Call ``GetInstrumentationConfiguration`` through the gateway."""
    return _call("get_instrumentation_configuration", **kwargs)


def delete_instrumentation_configuration(**kwargs: Any) -> Dict[str, Any]:
    """Call ``DeleteInstrumentationConfiguration`` through the gateway."""
    return _call("delete_instrumentation_configuration", **kwargs)


def batch_delete_instrumentation_configurations(**kwargs: Any) -> Dict[str, Any]:
    """Call ``BatchDeleteInstrumentationConfigurations`` through the gateway."""
    return _call("batch_delete_instrumentation_configurations", **kwargs)


def get_instrumentation_configuration_status(**kwargs: Any) -> Dict[str, Any]:
    """Call ``GetInstrumentationConfigurationStatus`` through the gateway."""
    return _call("get_instrumentation_configuration_status", **kwargs)


def render_error(
    err: GatewayError,
    *,
    action: str,
    attempted_label: str = "ATTEMPTED PARAMETERS:",
    attempted: Optional[Mapping[str, object]] = None,
    possible_causes: Optional[Sequence[str]] = None,
    troubleshooting: Optional[Sequence[str]] = None,
    trailer: Optional[str] = None,
) -> str:
    """Render a ``GatewayError`` using the appropriate error template.

    Callers that want tailored prose for a ``ClientError`` pass
    ``possible_causes`` / ``troubleshooting`` / ``trailer``; those flow
    through ``render_client_error``. Callers that pass none of those — and
    every non-``ClientError`` exception regardless — fall through to
    ``translate_aws_error``, which carries its own canned bullets per
    exception type. This preserves the per-tool rendering contract that
    existed before tools were routed through the gateway.
    """
    exc = err.original_exc
    has_tailored_prose = bool(possible_causes or troubleshooting or trailer)
    if isinstance(exc, ClientError) and has_tailored_prose:
        return render_client_error(
            exc,
            action=action,
            attempted_label=attempted_label,
            attempted=attempted,
            possible_causes=possible_causes,
            troubleshooting=troubleshooting,
            trailer=trailer,
        )
    return translate_aws_error(exc, action=action, context=attempted)
