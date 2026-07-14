"""AWS client construction for the dynamic-instrumentation host scripts.

WHY THIS EXISTS
``di_app_signals_client.py`` (application-signals client) and ``di_logs_client.py``
(CloudWatch Logs client) both build a boto3 client the same way: an
``AWS_PROFILE``-scoped session and a client whose region comes from
``di_region.resolve_region``. Centralizing that construction here keeps the two
client seams from drifting apart, mirroring how ``di_region`` already centralizes
the region precedence the client depends on.

POLICY
* ``AWS_PROFILE`` selects credentials only (the profile's configured region is
  ignored — region comes from ``resolve_region``).
* The region is resolved at call time via ``di_region.resolve_region`` so a
  ``--region`` flag (set into ``AWS_REGION`` by the entry script) or the env vars
  take effect.
* ``boto3`` is imported lazily inside the function so importing this module never
  requires boto3. (``--print-contract`` is a separate matter: it resolves the op
  functions, which transitively import ``botocore`` via the op modules — only a bare
  ``import di_instrumentation``/``di_snapshots`` is boto3-free.)

Per-surface concerns stay with the caller, not here:
* the application-signals SDK-version guard and its client cache live in
  ``di_app_signals_client.get_application_signals_client``;
* the lazy ``logs_client`` proxy cache lives in ``di_logs_client``.
"""

import os

from di_region import resolve_region


def build_client(service_name: str):
    """Build a boto3 client for ``service_name`` using the shared profile + region policy.

    Args:
        service_name: The boto3 service name, e.g. ``"application-signals"`` or ``"logs"``.

    Returns:
        A boto3 client whose credentials come from ``AWS_PROFILE`` (or the ambient
        default chain) and whose region comes from ``di_region.resolve_region``.
    """
    import boto3

    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
    return session.client(service_name, region_name=resolve_region())
