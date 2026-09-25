"""The application-signals boto3 client seam for the dynamic-instrumentation tools.

WHY THIS EXISTS (import-cycle removal)
  This module is the LEAF that owns ``get_application_signals_client()``. Previously the seam
  lived in ``di_instrumentation`` (the CLI entry point), so the operation modules reached it via
  ``di_crud_tools/di_status_tools -> di_gateway -> di_instrumentation`` — an import cycle back
  into the entry script, which forced every op module to be imported lazily. A client seam is a
  leaf concern (it depends only on ``di_session``/``di_region``), so it belongs in its own leaf
  module. With it here, ``di_gateway`` imports DOWN into this module and nothing imports back
  into ``di_instrumentation``: the cycle is gone. This mirrors how ``di_session`` / ``di_region``
  already factor out the shared client-construction policy.

  ``boto3``/``botocore`` are imported lazily (inside ``di_session.build_client``), so importing
  this module never requires boto3 — which is what lets the build env (which omits boto3) import
  ``di_instrumentation`` for the ``APPLICATION_SIGNALS_API_VERSION`` constant. (Running
  ``--print-contract`` is a separate matter: it resolves the op functions and so does pull in
  ``botocore`` via the op modules — only the bare module import is boto3-free.)
"""

# The application-signals instrumentation API version the operations were authored against; the
# public SDK serves it. Surfaced (informationally) by di_instrumentation --print-contract.
APPLICATION_SIGNALS_API_VERSION = "2024-04-15"
# Minimum boto3/botocore that ships the DI operations in the public model. Surfaced only in the
# fail-fast upgrade message — the actual gate is operation presence (see _MIN_DI_OPERATION).
MIN_BOTO3_VERSION = "1.43.35"
# Canary operation: if the installed SDK's application-signals model lacks this, the whole DI
# surface is missing and we should tell the caller to upgrade rather than fail mid-operation.
_MIN_DI_OPERATION = "CreateInstrumentationConfiguration"

_application_signals_client = None


def get_application_signals_client():
    """Return a lazily-built `application-signals` client from the installed boto3.

    The `di_gateway` module imports this symbol. Region resolves from --region/AWS_REGION/
    AWS_DEFAULT_REGION (default us-east-1); AWS_PROFILE is honored for credentials only. The DI
    operations ship in the public SDK as of boto3 1.43.35 (MIN_BOTO3_VERSION), so this is an
    ordinary client — no bundled model, no data-loader manipulation. If the installed SDK
    predates the DI operations we raise a clear upgrade error instead of letting an
    `AttributeError` surface deep inside an operation.
    """
    global _application_signals_client
    if _application_signals_client is not None:
        return _application_signals_client

    from di_session import build_client

    client = build_client("application-signals")
    if _MIN_DI_OPERATION not in client.meta.service_model.operation_names:
        raise RuntimeError(
            "The installed AWS SDK does not expose the Dynamic Instrumentation operations "
            f"(missing {_MIN_DI_OPERATION!r} on the application-signals model). Upgrade to "
            f"boto3/botocore >= {MIN_BOTO3_VERSION}: pip install --upgrade "
            f"'boto3>={MIN_BOTO3_VERSION}'."
        )
    _application_signals_client = client
    return _application_signals_client
