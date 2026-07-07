"""Region resolution for the dynamic-instrumentation host scripts.

WHY THIS EXISTS
``di_instrumentation.py`` (application-signals client) and ``di_snapshots.py``
(CloudWatch Logs client) both need to pick an AWS region, and they must pick it
the SAME way so a breakpoint created in one region and the snapshots later read
for it land in the same region. Centralizing the policy here keeps the two
host scripts from drifting apart.

POLICY (mirrors boto3's own precedence, minus the profile region)
    explicit --region flag  >  AWS_REGION  >  AWS_DEFAULT_REGION  >  us-east-1

* ``AWS_PROFILE`` is honored for CREDENTIALS only (by the client builders); the
  profile's configured region is deliberately ignored so the target region is
  always explicit and overridable per invocation.
* Both ``AWS_REGION`` and ``AWS_DEFAULT_REGION`` are consulted because boto3
  itself honors both; reading only ``AWS_REGION`` would surprise a caller who
  set ``AWS_DEFAULT_REGION`` instead.
* The ``us-east-1`` fallback means a call never fails for lack of a region, but
  callers are expected to pass ``--region`` or set the env var to target the
  region their service actually runs in (see SKILL.md).

The ``--region`` flag is a thin front-end: the host script sets
``AWS_REGION`` from the flag before dispatch, so the existing env-driven client
builders pick it up with no change to operation signatures.
"""

import os
from typing import Optional

DEFAULT_REGION = "us-east-1"


def resolve_region(explicit: Optional[str] = None) -> str:
    """Resolve the AWS region using the documented precedence.

    Args:
        explicit: A region passed directly (e.g. from a ``--region`` flag).
            When falsy, environment variables and the default are consulted.

    Returns:
        ``explicit`` if provided, else ``AWS_REGION``, else
        ``AWS_DEFAULT_REGION``, else ``us-east-1``.
    """
    if explicit:
        return explicit
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION
