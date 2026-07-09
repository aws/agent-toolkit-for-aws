"""Shared rendering primitives used by every ``*_rendering.py`` module.

These convert raw AWS API values into the human-readable shapes that operation responses depend on.
"""

from datetime import datetime, timezone
from typing import Any


def format_timestamp(value: Any, default: str = "N/A") -> str:
    """Render a boto3 ``datetime`` value in the AWS-CLI ISO format.

    boto3 returns timestamp fields as native ``datetime`` objects;
    AWS-CLI-era responses are ISO 8601 strings (``YYYY-MM-DDTHH:MM:SSZ``).
    callers depend on the latter shape, so anywhere a renderer surfaces
    an AWS-returned timestamp, it must go through this helper.

    String inputs are passed through unchanged so renderers can safely
    accept either shape (e.g. tests that hand-roll ISO strings).
    """
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)
